"""Roster module: drivers, and the duty builder (phase 10)."""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.deps import DbSession, ReaderUser, require_planner
from app.enums import DutyPieceType
from app.models import Block, Driver, Duty, DutyPiece, Location, ScheduleVersion
from app.schemas.common import ValidationReport
from app.schemas.roster import (
    BlockCoverage,
    DriverCreate,
    DriverRead,
    DriverUpdate,
    DutyCreate,
    DutyDetail,
    DutyPieceRead,
    DutyPiecesReplace,
    DutyRead,
    DutyUpdate,
)
from app.services import duties as duty_service
from app.services.crud import apply_updates, check_exists, commit, crud_router, get_or_404
from app.services.parameters import resolve


def serialize_driver(obj: Driver, db: Session) -> DriverRead:
    data = DriverRead.model_validate(obj)
    data.display_name = obj.display_name
    data.base_location_name = obj.base_location.name if obj.base_location else None
    return data


def _driver_check(obj: Driver, payload, db: Session) -> None:
    if obj.base_location_id is not None:
        check_exists(db, Location, obj.base_location_id, "base_location_id")


def _driver_on_delete(obj: Driver, db: Session) -> None:
    duty_id = db.scalar(select(Duty.id).where(Duty.driver_id == obj.id).limit(1))
    if duty_id is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{obj.display_name} is still assigned to duties (e.g. duty "
            f"{duty_id}). Unassign or delete those first, or mark the driver "
            "inactive instead.",
        )


drivers_router = crud_router(
    model=Driver,
    read_schema=DriverRead,
    create_schema=DriverCreate,
    update_schema=DriverUpdate,
    prefix="/drivers",
    tags=["roster"],
    search_fields=("code", "first_name", "last_name", "email"),
    filter_fields=("is_active", "base_location_id"),
    order_by=("last_name", "first_name"),
    options=(selectinload(Driver.base_location),),
    serialize=serialize_driver,
    on_create=_driver_check,
    on_update=_driver_check,
    on_delete=_driver_on_delete,
    label="Driver",
)

# --------------------------------------------------------------------------
# Duties
# --------------------------------------------------------------------------

duties_router = APIRouter(prefix="/duties", tags=["roster"])

_DUTY_OPTIONS = (selectinload(Duty.pieces), selectinload(Duty.driver))


def _fill_summary(duty: Duty, data: DutyRead, resolved, min_single_break: int) -> None:
    # The same threshold the validator uses, so the break total shown in a
    # list can never disagree with the one the rule check applied.
    summary = duty_service.summarise(resolved, min_single_break)
    data.driver_name = duty.driver.display_name if duty.driver else None
    data.piece_count = len(resolved)
    data.start_seconds = summary.start_seconds
    data.end_seconds = summary.end_seconds
    data.working_minutes = summary.working_minutes
    data.driving_minutes = summary.driving_minutes
    data.break_minutes = summary.break_minutes


def _min_single_break(db: Session) -> int:
    return resolve(db, "min_single_break_minutes") or 0


def serialize_duty(duty: Duty, db: Session, min_single_break: int | None = None) -> DutyRead:
    data = DutyRead.model_validate(duty)
    _fill_summary(
        duty,
        data,
        duty_service.resolve_duty(db, duty),
        _min_single_break(db) if min_single_break is None else min_single_break,
    )
    return data


def serialize_duty_detail(duty: Duty, db: Session, validate: bool = True) -> DutyDetail:
    resolved = duty_service.resolve_duty(db, duty)
    data = DutyDetail.model_validate(duty)
    _fill_summary(duty, data, resolved, _min_single_break(db))

    pieces: list[DutyPieceRead] = []
    for entry in resolved:
        piece = DutyPieceRead.model_validate(entry.piece)
        piece.block_name = entry.block_name
        piece.location_name = entry.location_name
        piece.effective_start_seconds = entry.start_seconds
        piece.effective_end_seconds = entry.end_seconds
        piece.covers_piece_count = len(entry.covered_sequences)
        pieces.append(piece)
    data.pieces = pieces

    if validate:
        data.validation = ValidationReport.from_issues(
            duty_service.validate_duty(db, duty)
        )
    return data


def _write_pieces(db: Session, duty: Duty, pieces) -> None:
    """Replace a duty's pieces, renumbering sequences 1..n."""
    block_ids = {p.block_id for p in pieces if p.block_id is not None}
    if block_ids:
        found = db.scalars(select(Block).where(Block.id.in_(block_ids))).all()
        by_id = {b.id: b for b in found}
        missing = block_ids - set(by_id)
        if missing:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Unknown block ids: {sorted(missing)}",
            )
        wrong_board = [
            b.name
            for b in found
            if b.schedule_version_id != duty.schedule_version_id
        ]
        if wrong_board:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "These blocks belong to a different schedule board: "
                + ", ".join(sorted(wrong_board)),
            )

    location_ids = {p.location_id for p in pieces if p.location_id is not None}
    if location_ids:
        known = set(
            db.scalars(select(Location.id).where(Location.id.in_(location_ids))).all()
        )
        unknown = location_ids - known
        if unknown:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Unknown location ids: {sorted(unknown)}",
            )

    for existing in list(duty.pieces):
        db.delete(existing)
    db.flush()

    for index, entry in enumerate(sorted(pieces, key=lambda p: p.sequence), start=1):
        db.add(
            DutyPiece(
                duty_id=duty.id,
                sequence=index,
                piece_type=entry.piece_type.value,
                block_id=entry.block_id,
                from_block_piece_sequence=entry.from_block_piece_sequence,
                to_block_piece_sequence=entry.to_block_piece_sequence,
                location_id=entry.location_id,
                start_seconds=entry.start_seconds,
                end_seconds=entry.end_seconds,
                notes=entry.notes,
            )
        )
    db.flush()


@duties_router.get("", response_model=list[DutyRead], summary="List duties")
def list_duties(
    db: DbSession,
    _user: ReaderUser,
    schedule_version_id: int | None = None,
    date: dt.date | None = None,
    driver_id: int | None = None,
    unassigned_only: bool = False,
):
    """Duties are listed a day at a time, which is how a roster is worked on."""
    stmt = select(Duty).options(*_DUTY_OPTIONS)
    if schedule_version_id is not None:
        stmt = stmt.where(Duty.schedule_version_id == schedule_version_id)
    if date is not None:
        stmt = stmt.where(Duty.date == date)
    if driver_id is not None:
        stmt = stmt.where(Duty.driver_id == driver_id)
    if unassigned_only:
        stmt = stmt.where(Duty.driver_id.is_(None))

    rows = db.scalars(stmt.order_by(Duty.date, Duty.name)).all()
    # Resolved once for the whole page rather than per duty.
    threshold = _min_single_break(db)
    return [serialize_duty(duty, db, threshold) for duty in rows]


@duties_router.post(
    "",
    response_model=DutyDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create a duty",
    dependencies=[Depends(require_planner)],
)
def create_duty(payload: DutyCreate, db: DbSession):
    check_exists(db, ScheduleVersion, payload.schedule_version_id, "schedule_version_id")
    if payload.driver_id is not None:
        check_exists(db, Driver, payload.driver_id, "driver_id")

    duty = Duty(
        name=payload.name,
        date=payload.date,
        schedule_version_id=payload.schedule_version_id,
        driver_id=payload.driver_id,
        notes=payload.notes,
    )
    db.add(duty)
    db.flush()
    if payload.pieces:
        _write_pieces(db, duty, payload.pieces)
    commit(db)
    db.refresh(duty)
    return serialize_duty_detail(duty, db)


@duties_router.get("/{duty_id}", response_model=DutyDetail, summary="Duty with its pieces")
def get_duty(duty_id: int, db: DbSession, _user: ReaderUser):
    duty = get_or_404(db, Duty, duty_id, "Duty")
    return serialize_duty_detail(duty, db)


@duties_router.patch(
    "/{duty_id}",
    response_model=DutyDetail,
    summary="Update a duty",
    dependencies=[Depends(require_planner)],
)
def update_duty(duty_id: int, payload: DutyUpdate, db: DbSession):
    duty = get_or_404(db, Duty, duty_id, "Duty")
    if payload.driver_id is not None:
        check_exists(db, Driver, payload.driver_id, "driver_id")
    apply_updates(duty, payload)
    commit(db)
    db.refresh(duty)
    return serialize_duty_detail(duty, db)


@duties_router.delete(
    "/{duty_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a duty",
    dependencies=[Depends(require_planner)],
)
def delete_duty(duty_id: int, db: DbSession):
    duty = get_or_404(db, Duty, duty_id, "Duty")
    db.delete(duty)
    commit(db)


@duties_router.put(
    "/{duty_id}/pieces",
    response_model=DutyDetail,
    summary="Replace a duty's pieces",
    dependencies=[Depends(require_planner)],
)
def replace_duty_pieces(duty_id: int, payload: DutyPiecesReplace, db: DbSession):
    """Send the finished piece list; sequences are renumbered 1..n.

    The response includes the rule check, so the builder can show the result
    of a save without a second round trip. Violations never prevent the save.
    """
    duty = get_or_404(db, Duty, duty_id, "Duty")
    _write_pieces(db, duty, payload.pieces)
    commit(db)
    db.refresh(duty)
    return serialize_duty_detail(duty, db)


@duties_router.get(
    "/{duty_id}/validate",
    response_model=ValidationReport,
    summary="Check a duty against the operating parameters",
)
def validate_duty(duty_id: int, db: DbSession, _user: ReaderUser):
    """Max driving time, minimum break, continuous driving and duty length.

    Reported, never enforced -- §4 step 5.
    """
    duty = get_or_404(db, Duty, duty_id, "Duty")
    return ValidationReport.from_issues(duty_service.validate_duty(db, duty))


@duties_router.get(
    "/coverage/report",
    response_model=list[BlockCoverage],
    summary="Which block pieces still have no driver",
)
def block_coverage(
    db: DbSession,
    _user: ReaderUser,
    schedule_version_id: int,
    date: dt.date,
    incomplete_only: bool = Query(
        default=False, description="Hide blocks that are already fully covered."
    ),
):
    """The roster's to-do list: what is still unstaffed on this date."""
    blocks = db.scalars(
        select(Block)
        .where(Block.schedule_version_id == schedule_version_id)
        .options(selectinload(Block.pieces))
        .order_by(Block.name)
    ).all()

    segments = db.execute(
        select(
            DutyPiece.block_id,
            DutyPiece.from_block_piece_sequence,
            DutyPiece.to_block_piece_sequence,
        )
        .join(Duty, DutyPiece.duty_id == Duty.id)
        .where(Duty.schedule_version_id == schedule_version_id)
        .where(Duty.date == date)
        .where(DutyPiece.piece_type == DutyPieceType.BLOCK_SEGMENT.value)
        .where(DutyPiece.block_id.is_not(None))
    ).all()

    covered: dict[int, set[int]] = {}
    for block_id, low, high in segments:
        covered.setdefault(block_id, set())
        block = next((b for b in blocks if b.id == block_id), None)
        if block is None:
            continue
        for piece in block.pieces:
            if (low is None or piece.sequence >= low) and (
                high is None or piece.sequence <= high
            ):
                covered[block_id].add(piece.sequence)

    result: list[BlockCoverage] = []
    for block in blocks:
        sequences = sorted(p.sequence for p in block.pieces)
        done = covered.get(block.id, set())
        missing = [s for s in sequences if s not in done]
        entry = BlockCoverage(
            block_id=block.id,
            block_name=block.name,
            total_pieces=len(sequences),
            covered_sequences=sorted(done),
            uncovered_sequences=missing,
            fully_covered=bool(sequences) and not missing,
        )
        if incomplete_only and entry.fully_covered:
            continue
        result.append(entry)
    return result


routers: list[APIRouter] = [drivers_router, duties_router]
