"""Fleet: vehicle types, vehicles, and location-aware interlined blocks."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.deps import DbSession, ReaderUser, require_planner
from app.timeutil import TimeParseError, parse_time
from app.models import (
    Block,
    BlockPiece,
    Line,
    Location,
    Pattern,
    ScheduleVersion,
    Trip,
    Vehicle,
    VehicleType,
)
from app.schemas.common import Page, ValidationReport
from app.schemas.fleet import (
    BlockCreate,
    BlockDetail,
    BlockPieceRead,
    BlockPiecesReplace,
    BlockRead,
    BlockUpdate,
    VehicleCreate,
    VehicleRead,
    VehicleTypeCreate,
    VehicleTypeRead,
    UnassignedTrip,
    VehicleTypeUpdate,
    VehicleUpdate,
)
from app.services import blocks as block_service
from app.services.crud import check_exists, commit, crud_router, get_or_404

vehicle_types_router = crud_router(
    model=VehicleType,
    read_schema=VehicleTypeRead,
    create_schema=VehicleTypeCreate,
    update_schema=VehicleTypeUpdate,
    prefix="/vehicle-types",
    tags=["fleet"],
    search_fields=("name", "code", "fuel_type"),
    order_by=("name",),
    label="Vehicle type",
)


def serialize_vehicle(obj: Vehicle, db: Session) -> VehicleRead:
    data = VehicleRead.model_validate(obj)
    data.vehicle_type_name = obj.vehicle_type.name if obj.vehicle_type else None
    data.depot_name = obj.depot.name if obj.depot else None
    return data


def _vehicle_check(obj: Vehicle, payload, db: Session) -> None:
    check_exists(db, VehicleType, obj.vehicle_type_id, "vehicle_type_id")
    if obj.depot_location_id is not None:
        check_exists(db, Location, obj.depot_location_id, "depot_location_id")


vehicles_router = crud_router(
    model=Vehicle,
    read_schema=VehicleRead,
    create_schema=VehicleCreate,
    update_schema=VehicleUpdate,
    prefix="/vehicles",
    tags=["fleet"],
    search_fields=("fleet_number", "registration"),
    filter_fields=("vehicle_type_id", "depot_location_id", "is_active"),
    order_by=("fleet_number",),
    options=(selectinload(Vehicle.vehicle_type), selectinload(Vehicle.depot)),
    serialize=serialize_vehicle,
    on_create=_vehicle_check,
    on_update=_vehicle_check,
    label="Vehicle",
)

# --------------------------------------------------------------------------
# Blocks
# --------------------------------------------------------------------------

_BLOCK_OPTIONS = (
    selectinload(Block.pieces),
    selectinload(Block.vehicle),
)


def _serialize_pieces(db: Session, block: Block) -> list[BlockPieceRead]:
    pieces = sorted(block.pieces, key=lambda p: p.sequence)
    resolved = block_service.resolve_pieces(db, pieces)
    output: list[BlockPieceRead] = []
    for piece in pieces:
        data = BlockPieceRead.model_validate(piece)
        ep = resolved[piece.id]
        data.effective_from_location_id = ep.from_location_id
        data.effective_to_location_id = ep.to_location_id
        data.effective_from_location_name = ep.from_location_name
        data.effective_to_location_name = ep.to_location_name
        data.effective_start_seconds = ep.start_seconds
        data.effective_end_seconds = ep.end_seconds
        data.trip_label = ep.label
        data.line_short_name = ep.line_short_name
        output.append(data)
    return output


def serialize_block(obj: Block, db: Session) -> BlockRead:
    data = BlockRead.model_validate(obj)
    data.vehicle_fleet_number = obj.vehicle.fleet_number if obj.vehicle else None
    data.piece_count = len(obj.pieces)
    start, end = block_service.block_span(db, obj)
    data.start_seconds = start
    data.end_seconds = end
    return data


def serialize_block_detail(obj: Block, db: Session) -> BlockDetail:
    data = BlockDetail.model_validate(obj)
    data.vehicle_fleet_number = obj.vehicle.fleet_number if obj.vehicle else None
    data.pieces = _serialize_pieces(db, obj)
    data.piece_count = len(data.pieces)
    starts = [p.effective_start_seconds for p in data.pieces if p.effective_start_seconds is not None]
    ends = [p.effective_end_seconds for p in data.pieces if p.effective_end_seconds is not None]
    data.start_seconds = min(starts) if starts else None
    data.end_seconds = max(ends) if ends else None
    return data


def _block_on_create(obj: Block, payload: BlockCreate, db: Session) -> None:
    check_exists(db, ScheduleVersion, obj.schedule_version_id, "schedule_version_id")
    if payload.pieces:
        _write_pieces(db, obj, payload.pieces)


blocks_router = crud_router(
    model=Block,
    read_schema=BlockRead,
    create_schema=BlockCreate,
    update_schema=BlockUpdate,
    prefix="/blocks",
    tags=["fleet"],
    search_fields=("name",),
    filter_fields=("schedule_version_id", "vehicle_id", "vehicle_type_id"),
    order_by=("schedule_version_id", "name"),
    options=_BLOCK_OPTIONS,
    serialize=serialize_block,
    on_create=_block_on_create,
    label="Block",
)


def _write_pieces(db: Session, block: Block, pieces) -> None:
    """Replace a block's pieces, renumbering sequences 1..n.

    Keeps ``trips.block_id`` in step: a trip dropped from the block is
    released, a trip added is claimed. A trip already claimed by a *different*
    block is rejected -- one bus cannot run two blocks at once.
    """
    trip_ids = [p.trip_id for p in pieces if p.trip_id is not None]
    if len(trip_ids) != len(set(trip_ids)):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "The same trip appears twice in this block.",
        )

    if trip_ids:
        found = db.scalars(select(Trip).where(Trip.id.in_(trip_ids))).all()
        by_id = {t.id: t for t in found}
        missing = [tid for tid in trip_ids if tid not in by_id]
        if missing:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Unknown trip ids: {sorted(set(missing))}",
            )
        wrong_board = [
            tid
            for tid in trip_ids
            if by_id[tid].schedule_version_id != block.schedule_version_id
        ]
        if wrong_board:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Trips {sorted(wrong_board)} belong to a different schedule board.",
            )
        taken = [
            f"trip {tid} (block {by_id[tid].block_id})"
            for tid in trip_ids
            if by_id[tid].block_id is not None and by_id[tid].block_id != block.id
        ]
        if taken:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Already assigned to another block: " + ", ".join(taken),
            )

    location_ids = {
        lid
        for p in pieces
        for lid in (p.from_location_id, p.to_location_id)
        if lid is not None
    }
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

    # Release trips that are no longer part of this block.
    for old in db.scalars(select(Trip).where(Trip.block_id == block.id)).all():
        old.block_id = None

    for existing in list(block.pieces):
        db.delete(existing)
    db.flush()

    for index, entry in enumerate(sorted(pieces, key=lambda p: p.sequence), start=1):
        db.add(
            BlockPiece(
                block_id=block.id,
                sequence=index,
                piece_type=entry.piece_type.value,
                trip_id=entry.trip_id,
                from_location_id=entry.from_location_id,
                to_location_id=entry.to_location_id,
                start_seconds=entry.start_seconds,
                end_seconds=entry.end_seconds,
                notes=entry.notes,
            )
        )
        if entry.trip_id is not None:
            db.get(Trip, entry.trip_id).block_id = block.id
    db.flush()


@blocks_router.get(
    "/{block_id}/detail",
    response_model=BlockDetail,
    summary="Block with resolved piece endpoints",
)
def block_detail(block_id: int, db: DbSession, _user: ReaderUser):
    """Each piece carries its *effective* endpoints.

    For a trip piece those are read from the trip's stop times; for a
    deadhead, pull-out or pull-in they are the explicit columns. The frontend
    therefore never has to know which kind it is looking at.
    """
    block = get_or_404(db, Block, block_id, "Block")
    return serialize_block_detail(block, db)


@blocks_router.put(
    "/{block_id}/pieces",
    response_model=BlockDetail,
    summary="Replace a block's pieces",
    dependencies=[Depends(require_planner)],
)
def replace_block_pieces(block_id: int, payload: BlockPiecesReplace, db: DbSession):
    block = get_or_404(db, Block, block_id, "Block")
    _write_pieces(db, block, payload.pieces)
    commit(db)
    db.refresh(block)
    return serialize_block_detail(block, db)


@blocks_router.get(
    "/{block_id}/validate",
    response_model=ValidationReport,
    summary="Check a block for continuity and timing problems",
)
def validate_block(block_id: int, db: DbSession, _user: ReaderUser):
    """Location continuity is checked against real location ids.

    Reported, never enforced -- a save always succeeds so an operator can
    knowingly accept an edge case.
    """
    block = get_or_404(db, Block, block_id, "Block")
    return ValidationReport.from_issues(block_service.validate_block(db, block))


tools_router = APIRouter(prefix="/fleet", tags=["fleet"])


@tools_router.get(
    "/unassigned-trips",
    response_model=Page[UnassignedTrip],
    summary="Trips on a board not yet in any block",
)
def unassigned_trips(
    db: DbSession,
    _user: ReaderUser,
    schedule_version_id: int,
    line_id: int | None = None,
    connects_from_location_id: int | None = Query(
        default=None,
        description="Only trips starting here -- where the block currently is.",
    ),
    # Plain string, parsed by hand below. The Annotated service-day time type
    # works on request *bodies*, where Pydantic owns the whole model, but as a
    # query parameter FastAPI rebuilds the field from the base annotation and
    # the "HH:MM:SS" -> seconds validator is dropped, so a perfectly good
    # "06:09:30" came back as "Input should be a valid integer".
    not_before: str | None = Query(
        default=None,
        description="Only trips departing at or after this time, e.g. 06:09:30.",
    ),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    """The work list for block building, with each trip's real endpoints.

    The "connects here" filter runs in the database, not the browser. A whole
    board's unassigned trips can be thousands of rows, and the shortlist a
    scheduler actually wants -- trips that start where the bus already is, no
    earlier than it gets there -- is usually a handful of them.
    """
    try:
        not_before_seconds = parse_time(not_before) if not_before else None
    except TimeParseError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"not_before: {exc}"
        ) from exc

    stmt = (
        select(Trip.id, Line.short_name, Trip.headsign, Pattern.direction, Trip.pattern_id)
        .join(Pattern, Trip.pattern_id == Pattern.id)
        .join(Line, Pattern.line_id == Line.id)
        .where(Trip.schedule_version_id == schedule_version_id)
        .where(Trip.block_id.is_(None))
    )
    if line_id is not None:
        stmt = stmt.where(Pattern.line_id == line_id)

    rows = db.execute(stmt).all()
    ends = block_service.trip_endpoints(db, [r[0] for r in rows])

    result = []
    for trip_id, short_name, headsign, direction, pattern_id in rows:
        endpoint = ends.get(trip_id)
        if connects_from_location_id is not None and (
            endpoint is None or endpoint.from_location_id != connects_from_location_id
        ):
            continue
        if not_before_seconds is not None and (
            endpoint is None
            or endpoint.start_seconds is None
            or endpoint.start_seconds < not_before_seconds
        ):
            continue
        result.append(
            UnassignedTrip(
                trip_id=trip_id,
                line_short_name=short_name,
                headsign=headsign,
                direction=direction,
                pattern_id=pattern_id,
                from_location_id=endpoint.from_location_id if endpoint else None,
                from_location_name=endpoint.from_location_name if endpoint else None,
                to_location_id=endpoint.to_location_id if endpoint else None,
                to_location_name=endpoint.to_location_name if endpoint else None,
                start_seconds=endpoint.start_seconds if endpoint else None,
                end_seconds=endpoint.end_seconds if endpoint else None,
            )
        )

    result.sort(key=lambda t: (t.start_seconds is None, t.start_seconds or 0, t.trip_id))
    return Page(
        items=result[offset : offset + limit],
        total=len(result),
        limit=limit,
        offset=offset,
    )


@tools_router.get(
    "/blocks/validate-all",
    response_model=ValidationReport,
    summary="Validate every block on a board",
)
def validate_all_blocks(db: DbSession, _user: ReaderUser, schedule_version_id: int):
    blocks = db.scalars(
        select(Block)
        .where(Block.schedule_version_id == schedule_version_id)
        .options(selectinload(Block.pieces))
    ).all()
    issues = []
    for block in blocks:
        issues.extend(block_service.validate_block(db, block))
    return ValidationReport.from_issues(issues)


routers: list[APIRouter] = [
    vehicle_types_router,
    vehicles_router,
    blocks_router,
    tools_router,
]
