"""Block piece resolution and the block-consistency validator."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.enums import (
    NON_REVENUE_TYPES,
    BlockPieceType,
    LocationType,
    Severity,
)
from app.models import Block, BlockPiece, Location, PatternStop, StopTime, Trip
from app.schemas.common import ValidationIssue
from app.services.parameters import resolve
from app.timeutil import format_time


@dataclass
class Endpoints:
    """A piece's effective start and end, however they were derived."""

    from_location_id: int | None = None
    to_location_id: int | None = None
    from_location_name: str | None = None
    to_location_name: str | None = None
    start_seconds: int | None = None
    end_seconds: int | None = None
    label: str | None = None
    line_short_name: str | None = None
    headsign: str | None = None
    #: Pattern attribute values, e.g. ["EXP"]. Printed as bubbles next to the
    #: line number on duty cards.
    badges: list[str] = field(default_factory=list)


def trip_endpoints(db: Session, trip_ids: list[int]) -> dict[int, Endpoints]:
    """First/last call of each trip, in one query.

    A trip piece never duplicates its own times or locations; they are read
    back out of ``stop_times`` here.

    Only the first and last call are needed, so the database does the picking
    with a window function rather than shipping every intermediate stop back
    to be discarded. On a board with 4,000 trips averaging 25 stops that is
    ~8,000 rows instead of ~100,000, which is the difference between the block
    builder feeling instant and feeling broken.
    """
    if not trip_ids:
        return {}

    ranked = (
        select(
            StopTime.trip_id.label("trip_id"),
            PatternStop.location_id.label("location_id"),
            Location.name.label("location_name"),
            StopTime.arrival_seconds.label("arrival_seconds"),
            StopTime.departure_seconds.label("departure_seconds"),
            func.row_number()
            .over(partition_by=StopTime.trip_id, order_by=PatternStop.sequence.asc())
            .label("rank_from_start"),
            func.row_number()
            .over(partition_by=StopTime.trip_id, order_by=PatternStop.sequence.desc())
            .label("rank_from_end"),
        )
        .join(PatternStop, StopTime.pattern_stop_id == PatternStop.id)
        .join(Location, PatternStop.location_id == Location.id)
        .where(StopTime.trip_id.in_(trip_ids))
        .subquery()
    )

    rows = db.execute(
        select(ranked).where(
            (ranked.c.rank_from_start == 1) | (ranked.c.rank_from_end == 1)
        )
    ).all()

    result: dict[int, Endpoints] = {}
    for row in rows:
        ep = result.setdefault(row.trip_id, Endpoints())
        if row.rank_from_start == 1:
            ep.from_location_id = row.location_id
            ep.from_location_name = row.location_name
            ep.start_seconds = row.departure_seconds
        if row.rank_from_end == 1:
            ep.to_location_id = row.location_id
            ep.to_location_name = row.location_name
            ep.end_seconds = row.arrival_seconds
    return result


def resolve_pieces(db: Session, pieces: list[BlockPiece]) -> dict[int, Endpoints]:
    """Effective endpoints for every piece, keyed by piece id."""
    trip_ids = [p.trip_id for p in pieces if p.trip_id is not None]
    ends = trip_endpoints(db, trip_ids)

    trip_labels: dict[int, tuple[str | None, str | None]] = {}
    trip_badges: dict[int, list[str]] = {}
    if trip_ids:
        from app.models import Line, Pattern, PatternAttribute  # local: avoids a cycle

        trip_patterns: dict[int, int] = {}
        for trip_id, pattern_id, short_name, headsign in db.execute(
            select(Trip.id, Pattern.id, Line.short_name, Trip.headsign)
            .join(Pattern, Trip.pattern_id == Pattern.id)
            .join(Line, Pattern.line_id == Line.id)
            .where(Trip.id.in_(trip_ids))
        ).all():
            trip_labels[trip_id] = (short_name, headsign)
            trip_patterns[trip_id] = pattern_id

        if trip_patterns:
            by_pattern: dict[int, list[str]] = {}
            for pattern_id, key, value in db.execute(
                select(
                    PatternAttribute.pattern_id,
                    PatternAttribute.attribute_key,
                    PatternAttribute.attribute_value,
                )
                .where(PatternAttribute.pattern_id.in_(set(trip_patterns.values())))
                .order_by(PatternAttribute.attribute_key)
            ).all():
                del key
                if (value or "").strip():
                    by_pattern.setdefault(pattern_id, []).append(value.strip())
            trip_badges = {
                trip_id: by_pattern.get(pattern_id, [])
                for trip_id, pattern_id in trip_patterns.items()
            }

    location_ids = {
        lid
        for p in pieces
        for lid in (p.from_location_id, p.to_location_id)
        if lid is not None
    }
    names: dict[int, str] = {}
    if location_ids:
        names = {
            lid: name
            for lid, name in db.execute(
                select(Location.id, Location.name).where(Location.id.in_(location_ids))
            ).all()
        }

    resolved: dict[int, Endpoints] = {}
    for piece in pieces:
        if piece.piece_type == BlockPieceType.TRIP.value and piece.trip_id is not None:
            ep = ends.get(piece.trip_id)
            if ep is None:
                # Trip exists but has no stop_times yet.
                resolved[piece.id] = Endpoints(label="(trip has no stop times)")
                continue
            short_name, headsign = trip_labels.get(piece.trip_id, (None, None))
            resolved[piece.id] = Endpoints(
                from_location_id=ep.from_location_id,
                to_location_id=ep.to_location_id,
                from_location_name=ep.from_location_name,
                to_location_name=ep.to_location_name,
                start_seconds=ep.start_seconds,
                end_seconds=ep.end_seconds,
                label=f"{short_name or '?'} {headsign or ''}".strip(),
                line_short_name=short_name,
                headsign=headsign,
                badges=trip_badges.get(piece.trip_id, []),
            )
        else:
            resolved[piece.id] = Endpoints(
                from_location_id=piece.from_location_id,
                to_location_id=piece.to_location_id,
                from_location_name=names.get(piece.from_location_id or -1),
                to_location_name=names.get(piece.to_location_id or -1),
                start_seconds=piece.start_seconds,
                end_seconds=piece.end_seconds,
                label=piece.piece_type.replace("_", " "),
            )
    return resolved


def block_span(db: Session, block: Block) -> tuple[int | None, int | None]:
    resolved = resolve_pieces(db, list(block.pieces))
    starts = [e.start_seconds for e in resolved.values() if e.start_seconds is not None]
    ends = [e.end_seconds for e in resolved.values() if e.end_seconds is not None]
    return (min(starts) if starts else None, max(ends) if ends else None)


def validate_block(db: Session, block: Block) -> list[ValidationIssue]:
    """Check one block for continuity, ordering and shape problems.

    Reports; never blocks a save.
    """
    issues: list[ValidationIssue] = []
    pieces = sorted(block.pieces, key=lambda p: p.sequence)

    if not pieces:
        issues.append(
            ValidationIssue(
                code="BLOCK_EMPTY",
                severity=Severity.WARNING,
                message="Block has no pieces.",
                entity="block",
                entity_id=block.id,
            )
        )
        return issues

    resolved = resolve_pieces(db, pieces)
    min_layover = resolve(db, "min_layover_seconds_between_pieces") or 0

    location_types = _location_types(db, resolved)

    for index, piece in enumerate(pieces):
        ep = resolved[piece.id]

        if ep.start_seconds is None or ep.end_seconds is None:
            issues.append(
                ValidationIssue(
                    code="PIECE_TIMES_MISSING",
                    severity=Severity.ERROR,
                    message=(
                        f"Piece {piece.sequence} ({piece.piece_type}) has no "
                        "resolvable start/end time."
                    ),
                    entity="block_piece",
                    entity_id=piece.id,
                    sequence=piece.sequence,
                )
            )
        elif ep.end_seconds < ep.start_seconds:
            issues.append(
                ValidationIssue(
                    code="PIECE_TIMES_REVERSED",
                    severity=Severity.ERROR,
                    message=(
                        f"Piece {piece.sequence} ends "
                        f"({format_time(ep.end_seconds)}) before it starts "
                        f"({format_time(ep.start_seconds)})."
                    ),
                    entity="block_piece",
                    entity_id=piece.id,
                    sequence=piece.sequence,
                )
            )

        if index == 0 and piece.piece_type != BlockPieceType.PULL_OUT.value:
            issues.append(
                ValidationIssue(
                    code="BLOCK_NO_PULL_OUT",
                    severity=Severity.WARNING,
                    message=(
                        "Block does not start with a pull-out; the vehicle "
                        "appears out of nowhere at its first piece."
                    ),
                    entity="block_piece",
                    entity_id=piece.id,
                    sequence=piece.sequence,
                )
            )
        if index == len(pieces) - 1 and piece.piece_type != BlockPieceType.PULL_IN.value:
            issues.append(
                ValidationIssue(
                    code="BLOCK_NO_PULL_IN",
                    severity=Severity.WARNING,
                    message="Block does not end with a pull-in to a depot.",
                    entity="block_piece",
                    entity_id=piece.id,
                    sequence=piece.sequence,
                )
            )

        if piece.piece_type == BlockPieceType.PULL_OUT.value:
            _check_terminal_type(
                issues, piece, ep.from_location_id, location_types, "start"
            )
        if piece.piece_type == BlockPieceType.PULL_IN.value:
            _check_terminal_type(
                issues, piece, ep.to_location_id, location_types, "end"
            )

    # Continuity between consecutive pieces.
    for previous, current in zip(pieces, pieces[1:]):
        prev_ep = resolved[previous.id]
        curr_ep = resolved[current.id]

        if (
            prev_ep.to_location_id is not None
            and curr_ep.from_location_id is not None
            and prev_ep.to_location_id != curr_ep.from_location_id
        ):
            issues.append(
                ValidationIssue(
                    code="LOCATION_DISCONTINUITY",
                    severity=Severity.ERROR,
                    message=(
                        f"Piece {previous.sequence} ends at "
                        f"'{prev_ep.to_location_name or prev_ep.to_location_id}' but "
                        f"piece {current.sequence} starts at "
                        f"'{curr_ep.from_location_name or curr_ep.from_location_id}'. "
                        "Insert a deadhead between them."
                    ),
                    entity="block_piece",
                    entity_id=current.id,
                    sequence=current.sequence,
                )
            )

        if prev_ep.end_seconds is None or curr_ep.start_seconds is None:
            continue

        gap = curr_ep.start_seconds - prev_ep.end_seconds
        if gap < 0:
            issues.append(
                ValidationIssue(
                    code="TIME_OVERLAP",
                    severity=Severity.ERROR,
                    message=(
                        f"Piece {current.sequence} starts at "
                        f"{format_time(curr_ep.start_seconds)}, before piece "
                        f"{previous.sequence} ends at "
                        f"{format_time(prev_ep.end_seconds)}."
                    ),
                    entity="block_piece",
                    entity_id=current.id,
                    sequence=current.sequence,
                )
            )
        elif min_layover and gap < min_layover:
            issues.append(
                ValidationIssue(
                    code="LAYOVER_TOO_SHORT",
                    severity=Severity.WARNING,
                    message=(
                        f"Only {gap // 60} min between pieces "
                        f"{previous.sequence} and {current.sequence}; "
                        f"minimum is {min_layover // 60} min."
                    ),
                    entity="block_piece",
                    entity_id=current.id,
                    sequence=current.sequence,
                )
            )

    return issues


def _location_types(db: Session, resolved: dict[int, Endpoints]) -> dict[int, str]:
    ids = {
        lid
        for ep in resolved.values()
        for lid in (ep.from_location_id, ep.to_location_id)
        if lid is not None
    }
    if not ids:
        return {}
    return {
        lid: ltype
        for lid, ltype in db.execute(
            select(Location.id, Location.location_type).where(Location.id.in_(ids))
        ).all()
    }


def _check_terminal_type(
    issues: list[ValidationIssue],
    piece: BlockPiece,
    location_id: int | None,
    location_types: dict[int, str],
    which: str,
) -> None:
    if location_id is None:
        return
    ltype = location_types.get(location_id)
    if ltype is None:
        return
    if LocationType(ltype) not in NON_REVENUE_TYPES:
        issues.append(
            ValidationIssue(
                code="TERMINAL_NOT_A_DEPOT",
                severity=Severity.WARNING,
                message=(
                    f"Piece {piece.sequence} ({piece.piece_type}) has its "
                    f"{which} at a '{ltype}' location rather than a depot, "
                    "garage or layover."
                ),
                entity="block_piece",
                entity_id=piece.id,
                sequence=piece.sequence,
            )
        )
