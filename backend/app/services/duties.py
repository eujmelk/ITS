"""Duty resolution and the rule checks from §4 and §5.

A duty mirrors a block: an ordered list of pieces. The difference is that a
``block_segment`` piece does not carry its own times -- it names a contiguous
range of one block's pieces, and its times are whatever those pieces span.
That indirection is what lets one block be split between an AM and a PM
driver without duplicating any schedule data.

Like the block validator, everything here reports and never blocks. §4 step 5
is explicit that a save must succeed so an operator can consciously override
an edge case.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.enums import DutyPieceType, Severity
from app.models import Block, BlockPiece, Duty, DutyPiece
from app.schemas.common import ValidationIssue
from app.services import blocks as block_service
from app.services.parameters import resolve_all
from app.timeutil import format_time


@dataclass
class ResolvedPiece:
    piece: DutyPiece
    start_seconds: int | None = None
    end_seconds: int | None = None
    from_location_id: int | None = None
    to_location_id: int | None = None
    from_location_name: str | None = None
    to_location_name: str | None = None
    block_name: str | None = None
    location_name: str | None = None
    covered_sequences: list[int] = field(default_factory=list)
    #: Revenue + non-revenue driving, i.e. time actually behind the wheel.
    is_driving: bool = False

    @property
    def duration(self) -> int:
        if self.start_seconds is None or self.end_seconds is None:
            return 0
        return max(0, self.end_seconds - self.start_seconds)


def resolve_duty(db: Session, duty: Duty) -> list[ResolvedPiece]:
    """Work out each piece's real times and endpoints."""
    pieces = sorted(duty.pieces, key=lambda p: p.sequence)
    if not pieces:
        return []

    block_ids = {p.block_id for p in pieces if p.block_id is not None}
    blocks: dict[int, Block] = {}
    if block_ids:
        blocks = {
            b.id: b
            for b in db.scalars(
                select(Block)
                .where(Block.id.in_(block_ids))
                .options(selectinload(Block.pieces))
            ).all()
        }

    # One resolution pass per block, reused across every duty piece that
    # references it.
    block_endpoints: dict[int, dict[int, block_service.Endpoints]] = {}
    for block_id, block in blocks.items():
        block_endpoints[block_id] = block_service.resolve_pieces(db, list(block.pieces))

    location_ids = {p.location_id for p in pieces if p.location_id is not None}
    location_names: dict[int, str] = {}
    if location_ids:
        from app.models import Location

        location_names = {
            lid: name
            for lid, name in db.execute(
                select(Location.id, Location.name).where(Location.id.in_(location_ids))
            ).all()
        }

    resolved: list[ResolvedPiece] = []
    for piece in pieces:
        entry = ResolvedPiece(piece=piece)

        if piece.piece_type == DutyPieceType.BLOCK_SEGMENT.value and piece.block_id:
            block = blocks.get(piece.block_id)
            entry.block_name = block.name if block else None
            if block is None:
                resolved.append(entry)
                continue

            ends = block_endpoints.get(piece.block_id, {})
            ordered = sorted(block.pieces, key=lambda bp: bp.sequence)
            # An unset range means "the whole block", which is the common case.
            low = piece.from_block_piece_sequence
            high = piece.to_block_piece_sequence
            covered = [
                bp
                for bp in ordered
                if (low is None or bp.sequence >= low)
                and (high is None or bp.sequence <= high)
            ]
            entry.covered_sequences = [bp.sequence for bp in covered]

            starts = [
                ends[bp.id].start_seconds
                for bp in covered
                if bp.id in ends and ends[bp.id].start_seconds is not None
            ]
            finishes = [
                ends[bp.id].end_seconds
                for bp in covered
                if bp.id in ends and ends[bp.id].end_seconds is not None
            ]
            entry.start_seconds = min(starts) if starts else None
            entry.end_seconds = max(finishes) if finishes else None
            if covered:
                first, last = covered[0], covered[-1]
                entry.from_location_id = ends.get(first.id, block_service.Endpoints()).from_location_id
                entry.from_location_name = ends.get(first.id, block_service.Endpoints()).from_location_name
                entry.to_location_id = ends.get(last.id, block_service.Endpoints()).to_location_id
                entry.to_location_name = ends.get(last.id, block_service.Endpoints()).to_location_name
            entry.is_driving = True
        else:
            entry.start_seconds = piece.start_seconds
            entry.end_seconds = piece.end_seconds
            entry.from_location_id = piece.location_id
            entry.to_location_id = piece.location_id
            entry.location_name = location_names.get(piece.location_id or -1)
            entry.from_location_name = entry.location_name
            entry.to_location_name = entry.location_name

        resolved.append(entry)

    return resolved


@dataclass
class DutySummary:
    start_seconds: int | None = None
    end_seconds: int | None = None
    working_minutes: int = 0
    driving_minutes: int = 0
    break_minutes: int = 0


def summarise(resolved: list[ResolvedPiece], min_single_break_minutes: int = 0) -> DutySummary:
    summary = DutySummary()
    starts = [r.start_seconds for r in resolved if r.start_seconds is not None]
    ends = [r.end_seconds for r in resolved if r.end_seconds is not None]
    if starts and ends:
        summary.start_seconds = min(starts)
        summary.end_seconds = max(ends)
        summary.working_minutes = (summary.end_seconds - summary.start_seconds) // 60

    summary.driving_minutes = sum(r.duration for r in resolved if r.is_driving) // 60
    # Only rests long enough to count as a break contribute to the total; a
    # three-minute gap is not a break in any rulebook.
    summary.break_minutes = (
        sum(
            r.duration
            for r in resolved
            if r.piece.piece_type == DutyPieceType.BREAK.value
            and r.duration >= min_single_break_minutes * 60
        )
        // 60
    )
    return summary


def validate_duty(db: Session, duty: Duty) -> list[ValidationIssue]:
    """Check a duty against the operating parameters."""
    issues: list[ValidationIssue] = []
    resolved = resolve_duty(db, duty)

    if not resolved:
        return [
            ValidationIssue(
                code="DUTY_EMPTY",
                severity=Severity.WARNING,
                message="Duty has no pieces.",
                entity="duty",
                entity_id=duty.id,
            )
        ]

    params = resolve_all(db)
    min_single_break = params["min_single_break_minutes"]
    summary = summarise(resolved, min_single_break)

    for entry in resolved:
        if entry.start_seconds is None or entry.end_seconds is None:
            issues.append(
                ValidationIssue(
                    code="DUTY_PIECE_UNRESOLVED",
                    severity=Severity.ERROR,
                    message=(
                        f"Piece {entry.piece.sequence} "
                        f"({entry.piece.piece_type}) has no resolvable times. "
                        "Check the block range it refers to."
                    ),
                    entity="duty_piece",
                    entity_id=entry.piece.id,
                    sequence=entry.piece.sequence,
                )
            )
        if (
            entry.piece.piece_type == DutyPieceType.BLOCK_SEGMENT.value
            and entry.piece.block_id
            and not entry.covered_sequences
        ):
            issues.append(
                ValidationIssue(
                    code="BLOCK_RANGE_EMPTY",
                    severity=Severity.ERROR,
                    message=(
                        f"Piece {entry.piece.sequence} covers no pieces of block "
                        f"'{entry.block_name}' -- check the sequence range."
                    ),
                    entity="duty_piece",
                    entity_id=entry.piece.id,
                    sequence=entry.piece.sequence,
                )
            )

    # Overlaps and gaps between consecutive pieces.
    timed = [r for r in resolved if r.start_seconds is not None and r.end_seconds is not None]
    for previous, current in zip(timed, timed[1:]):
        if current.start_seconds < previous.end_seconds:
            issues.append(
                ValidationIssue(
                    code="DUTY_PIECE_OVERLAP",
                    severity=Severity.ERROR,
                    message=(
                        f"Piece {current.piece.sequence} starts at "
                        f"{format_time(current.start_seconds)}, before piece "
                        f"{previous.piece.sequence} ends at "
                        f"{format_time(previous.end_seconds)}. A driver cannot "
                        "be in two places at once."
                    ),
                    entity="duty_piece",
                    entity_id=current.piece.id,
                    sequence=current.piece.sequence,
                )
            )
        elif current.start_seconds > previous.end_seconds:
            gap = (current.start_seconds - previous.end_seconds) // 60
            if gap >= 5 and current.piece.piece_type != DutyPieceType.BREAK.value:
                issues.append(
                    ValidationIssue(
                        code="DUTY_UNRECORDED_GAP",
                        severity=Severity.INFO,
                        message=(
                            f"{gap} min of unrecorded time between pieces "
                            f"{previous.piece.sequence} and "
                            f"{current.piece.sequence}. Add a break piece if "
                            "that is what it is."
                        ),
                        entity="duty_piece",
                        entity_id=current.piece.id,
                        sequence=current.piece.sequence,
                    )
                )

    # --- the §5 parameter checks ------------------------------------------
    max_driving = params["max_driving_minutes_per_day"]
    if max_driving and summary.driving_minutes > max_driving:
        issues.append(
            ValidationIssue(
                code="MAX_DRIVING_EXCEEDED",
                severity=Severity.ERROR,
                message=(
                    f"{summary.driving_minutes} min of driving exceeds the "
                    f"{max_driving} min daily maximum."
                ),
                entity="duty",
                entity_id=duty.id,
            )
        )

    max_duty = params["max_duty_length_minutes"]
    if max_duty and summary.working_minutes > max_duty:
        issues.append(
            ValidationIssue(
                code="DUTY_TOO_LONG",
                severity=Severity.ERROR,
                message=(
                    f"Sign-on to sign-off is {summary.working_minutes} min, "
                    f"over the {max_duty} min maximum."
                ),
                entity="duty",
                entity_id=duty.id,
            )
        )

    before_break = params["min_driving_minutes_before_break_required"]
    min_break = params["min_break_minutes"]

    if before_break and summary.driving_minutes > before_break:
        if summary.break_minutes < min_break:
            issues.append(
                ValidationIssue(
                    code="INSUFFICIENT_BREAK",
                    severity=Severity.ERROR,
                    message=(
                        f"{summary.driving_minutes} min of driving requires at "
                        f"least {min_break} min of break; this duty has "
                        f"{summary.break_minutes} min. Breaks shorter than "
                        f"{min_single_break} min do not count."
                    ),
                    entity="duty",
                    entity_id=duty.id,
                )
            )

        # Continuous stretch: reset whenever a qualifying break is taken.
        continuous = 0
        for entry in resolved:
            if entry.is_driving:
                continuous += entry.duration
            elif (
                entry.piece.piece_type == DutyPieceType.BREAK.value
                and entry.duration >= min_single_break * 60
            ):
                continuous = 0
            if continuous > before_break * 60:
                issues.append(
                    ValidationIssue(
                        code="CONTINUOUS_DRIVING_EXCEEDED",
                        severity=Severity.ERROR,
                        message=(
                            f"{continuous // 60} min of continuous driving by "
                            f"piece {entry.piece.sequence}, without a break of "
                            f"at least {min_single_break} min. The limit is "
                            f"{before_break} min."
                        ),
                        entity="duty_piece",
                        entity_id=entry.piece.id,
                        sequence=entry.piece.sequence,
                    )
                )
                break

    # --- sign-on / sign-off ------------------------------------------------
    kinds = [r.piece.piece_type for r in resolved]
    if DutyPieceType.SIGN_ON.value not in kinds:
        issues.append(
            ValidationIssue(
                code="NO_SIGN_ON",
                severity=Severity.WARNING,
                message="Duty has no sign-on piece, so preparation time is unpaid.",
                entity="duty",
                entity_id=duty.id,
            )
        )
    else:
        first_sign_on = next(r for r in resolved if r.piece.piece_type == DutyPieceType.SIGN_ON.value)
        needed = params["min_sign_on_minutes"]
        if needed and first_sign_on.duration < needed * 60:
            issues.append(
                ValidationIssue(
                    code="SIGN_ON_TOO_SHORT",
                    severity=Severity.WARNING,
                    message=(
                        f"Sign-on is {first_sign_on.duration // 60} min; the "
                        f"minimum is {needed} min."
                    ),
                    entity="duty_piece",
                    entity_id=first_sign_on.piece.id,
                    sequence=first_sign_on.piece.sequence,
                )
            )

    if DutyPieceType.SIGN_OFF.value not in kinds:
        issues.append(
            ValidationIssue(
                code="NO_SIGN_OFF",
                severity=Severity.WARNING,
                message="Duty has no sign-off piece.",
                entity="duty",
                entity_id=duty.id,
            )
        )

    issues.extend(_check_driver_clashes(db, duty, summary))
    issues.extend(_check_relief_handovers(db, duty, resolved))
    return issues


def _check_driver_clashes(db: Session, duty: Duty, summary: DutySummary) -> list[ValidationIssue]:
    """A driver cannot work two overlapping duties on the same date."""
    if duty.driver_id is None or summary.start_seconds is None:
        return []

    others = db.scalars(
        select(Duty)
        .where(Duty.driver_id == duty.driver_id)
        .where(Duty.date == duty.date)
        .where(Duty.id != duty.id)
        .options(selectinload(Duty.pieces))
    ).all()

    issues: list[ValidationIssue] = []
    for other in others:
        other_summary = summarise(resolve_duty(db, other))
        if other_summary.start_seconds is None or other_summary.end_seconds is None:
            continue
        if (
            summary.start_seconds < other_summary.end_seconds
            and other_summary.start_seconds < summary.end_seconds
        ):
            issues.append(
                ValidationIssue(
                    code="DRIVER_DOUBLE_BOOKED",
                    severity=Severity.ERROR,
                    message=(
                        f"This driver also works duty '{other.name}' "
                        f"({format_time(other_summary.start_seconds)}–"
                        f"{format_time(other_summary.end_seconds)}) on the same date."
                    ),
                    entity="duty",
                    entity_id=duty.id,
                )
            )
    return issues


def _check_relief_handovers(
    db: Session, duty: Duty, resolved: list[ResolvedPiece]
) -> list[ValidationIssue]:
    """Flag a mid-block driver changeover with no break at the split point.

    Answering §10's second open question: a direct hand-off is permitted, and
    only warned about, unless ``require_break_at_driver_changeover`` is turned
    on -- in which case it is an error.
    """
    params = resolve_all(db)
    if not params["require_break_at_driver_changeover"]:
        severity = Severity.INFO
    else:
        severity = Severity.ERROR

    issues: list[ValidationIssue] = []
    for entry in resolved:
        if not entry.is_driving or not entry.piece.block_id or not entry.covered_sequences:
            continue

        total_pieces = db.scalar(
            select(BlockPiece.sequence)
            .where(BlockPiece.block_id == entry.piece.block_id)
            .order_by(BlockPiece.sequence.desc())
            .limit(1)
        )
        if total_pieces is None:
            continue

        partial = entry.covered_sequences[0] > 1 or entry.covered_sequences[-1] < total_pieces
        if not partial:
            continue

        neighbours = [r.piece.piece_type for r in resolved]
        index = resolved.index(entry)
        has_break_before = index > 0 and neighbours[index - 1] == DutyPieceType.BREAK.value
        has_break_after = (
            index < len(resolved) - 1 and neighbours[index + 1] == DutyPieceType.BREAK.value
        )
        if has_break_before or has_break_after:
            continue

        issues.append(
            ValidationIssue(
                code="RELIEF_WITHOUT_BREAK",
                severity=severity,
                message=(
                    f"Piece {entry.piece.sequence} takes over part of block "
                    f"'{entry.block_name}' with no break at the changeover -- "
                    "a direct hand-off mid-route."
                ),
                entity="duty_piece",
                entity_id=entry.piece.id,
                sequence=entry.piece.sequence,
            )
        )
    return issues
