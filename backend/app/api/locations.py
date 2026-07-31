"""Locations module: stops, depots, layovers, stop areas and transfers."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.deps import DbSession, ReaderUser, require_planner
from app.enums import LocationType, Severity
from app.models import (
    FareZone,
    Location,
    LocationAttribute,
    LocationTransfer,
    PatternStop,
    StopArea,
)
from app.schemas.common import ValidationIssue, ValidationReport
from app.schemas.locations import (
    LocationAttributeCreate,
    LocationAttributeRead,
    LocationAttributeUpdate,
    LocationCreate,
    LocationRead,
    LocationTransferCreate,
    LocationTransferRead,
    LocationTransferUpdate,
    LocationUpdate,
    StopAreaCreate,
    StopAreaDetail,
    StopAreaMembership,
    StopAreaRead,
    StopAreaUpdate,
    TransferEdge,
)
from app.services import transfers as transfer_service
from app.services.crud import check_exists, commit, crud_router, get_or_404

# --------------------------------------------------------------------------
# Serializers
# --------------------------------------------------------------------------


def serialize_location(obj: Location, db: Session) -> LocationRead:
    data = LocationRead.model_validate(obj)
    data.area_name = obj.area.name if obj.area else None
    data.zone_name = obj.zone.name if obj.zone else None
    return data


def serialize_transfer(obj: LocationTransfer, db: Session) -> LocationTransferRead:
    data = LocationTransferRead.model_validate(obj)
    data.from_location_name = obj.from_location.name if obj.from_location else None
    data.to_location_name = obj.to_location.name if obj.to_location else None
    return data


def serialize_area(obj: StopArea, db: Session) -> StopAreaDetail:
    data = StopAreaDetail.model_validate(obj)
    members = sorted(obj.locations, key=lambda loc: loc.name)
    data.location_ids = [loc.id for loc in members]
    data.location_names = [loc.name for loc in members]
    return data


def _replace_attributes(obj: Location, entries, db: Session) -> None:
    for existing in list(obj.attributes):
        db.delete(existing)
    db.flush()
    for entry in entries:
        db.add(
            LocationAttribute(
                location_id=obj.id,
                attribute_key=entry.attribute_key,
                attribute_value=entry.attribute_value,
            )
        )
    db.flush()


def _location_on_create(obj: Location, payload: LocationCreate, db: Session) -> None:
    _validate_refs(obj, db)
    if payload.attributes:
        _replace_attributes(obj, payload.attributes, db)


def _location_on_update(obj: Location, payload: LocationUpdate, db: Session) -> None:
    _validate_refs(obj, db)
    if payload.attributes is not None:
        _replace_attributes(obj, payload.attributes, db)


def _validate_refs(obj: Location, db: Session) -> None:
    if obj.zone_id is not None:
        check_exists(db, FareZone, obj.zone_id, "zone_id")
    if obj.area_id is not None:
        check_exists(db, StopArea, obj.area_id, "area_id")
        if obj.location_type != LocationType.STOP.value:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Only 'stop' locations can belong to a stop area -- a depot is "
                "not somewhere a passenger transfers.",
            )


def _location_on_delete(obj: Location, db: Session) -> None:
    used_by = db.scalar(
        select(PatternStop.pattern_id).where(PatternStop.location_id == obj.id).limit(1)
    )
    if used_by is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"'{obj.name}' is still used by pattern {used_by}. Remove it from "
            "the pattern first.",
        )


# --------------------------------------------------------------------------
# Routers
# --------------------------------------------------------------------------

router = crud_router(
    model=Location,
    read_schema=LocationRead,
    create_schema=LocationCreate,
    update_schema=LocationUpdate,
    prefix="/locations",
    tags=["locations"],
    search_fields=("name", "code"),
    filter_fields=("location_type", "zone_id", "area_id", "is_active"),
    order_by=("name",),
    options=(
        selectinload(Location.attributes),
        selectinload(Location.area),
        selectinload(Location.zone),
    ),
    serialize=serialize_location,
    on_create=_location_on_create,
    on_update=_location_on_update,
    on_delete=_location_on_delete,
    label="Location",
)

attributes_router = crud_router(
    model=LocationAttribute,
    read_schema=LocationAttributeRead,
    create_schema=LocationAttributeCreate,
    update_schema=LocationAttributeUpdate,
    prefix="/location-attributes",
    tags=["locations"],
    search_fields=("attribute_key", "attribute_value"),
    filter_fields=("location_id", "attribute_key"),
    order_by=("location_id", "attribute_key"),
    label="Location attribute",
)

areas_router = crud_router(
    model=StopArea,
    read_schema=StopAreaDetail,
    create_schema=StopAreaCreate,
    update_schema=StopAreaUpdate,
    prefix="/stop-areas",
    tags=["locations"],
    search_fields=("name",),
    order_by=("name",),
    options=(selectinload(StopArea.locations),),
    serialize=serialize_area,
    label="Stop area",
)

transfers_router = crud_router(
    model=LocationTransfer,
    read_schema=LocationTransferRead,
    create_schema=LocationTransferCreate,
    update_schema=LocationTransferUpdate,
    prefix="/location-transfers",
    tags=["locations"],
    filter_fields=("from_location_id", "to_location_id"),
    order_by=("from_location_id",),
    options=(
        selectinload(LocationTransfer.from_location),
        selectinload(LocationTransfer.to_location),
    ),
    serialize=serialize_transfer,
    label="Transfer",
)


@areas_router.put(
    "/{area_id}/members",
    response_model=StopAreaDetail,
    summary="Set which locations belong to a stop area",
    dependencies=[Depends(require_planner)],
)
def set_area_members(area_id: int, payload: StopAreaMembership, db: DbSession):
    """Replace an area's membership in one call.

    Membership lives on ``locations.area_id``, but it is edited
    area-at-a-time, so the whole set is sent here rather than patching each
    location individually.
    """
    area = get_or_404(db, StopArea, area_id, "Stop area")

    requested = set(payload.location_ids)
    if requested:
        found = db.scalars(select(Location).where(Location.id.in_(requested))).all()
        missing = requested - {loc.id for loc in found}
        if missing:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Unknown location ids: {sorted(missing)}",
            )
        not_stops = [
            loc.name for loc in found if loc.location_type != LocationType.STOP.value
        ]
        if not_stops:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Only 'stop' locations can join a stop area. Rejected: "
                f"{', '.join(not_stops)}",
            )

    for current in list(area.locations):
        if current.id not in requested:
            current.area_id = None
    if requested:
        for loc in db.scalars(select(Location).where(Location.id.in_(requested))).all():
            loc.area_id = area_id

    commit(db)
    db.refresh(area)
    return serialize_area(area, db)


@transfers_router.get(
    "/graph/edges",
    response_model=list[TransferEdge],
    summary="The resolved walking-transfer graph",
)
def transfer_graph(db: DbSession, _user: ReaderUser, location_id: int | None = None):
    """Every walking edge the itinerary finder will see.

    Useful for checking that a stop area or a new transfer row produced the
    connection you expected. Nothing here is inferred from coordinates.
    """
    if location_id is not None:
        return transfer_service.edges_for_location(db, location_id)
    return transfer_service.build_edges(db)


@router.get(
    "/validate/report",
    response_model=ValidationReport,
    summary="Data-quality check over all locations",
)
def validate_locations(
    db: DbSession,
    _user: ReaderUser,
    limit: int = Query(default=500, ge=1, le=5000),
):
    issues: list[ValidationIssue] = []

    missing_coords = db.scalars(
        select(Location)
        .where(Location.is_active.is_(True))
        .where((Location.lat.is_(None)) | (Location.lon.is_(None)))
        .order_by(Location.name)
        .limit(limit)
    ).all()
    for loc in missing_coords:
        issues.append(
            ValidationIssue(
                code="LOCATION_NO_COORDINATES",
                severity=Severity.WARNING,
                message=f"'{loc.name}' has no coordinates, so it cannot be mapped.",
                entity="location",
                entity_id=loc.id,
            )
        )

    # pattern_stops should only ever point at stop-type locations. Enforced
    # here rather than in the database so it reads as a friendly warning.
    bad_pattern_stops = db.execute(
        select(PatternStop.id, PatternStop.pattern_id, Location.name, Location.location_type)
        .join(Location, PatternStop.location_id == Location.id)
        .where(Location.location_type != LocationType.STOP.value)
        .limit(limit)
    ).all()
    for ps_id, pattern_id, name, ltype in bad_pattern_stops:
        issues.append(
            ValidationIssue(
                code="PATTERN_STOP_NOT_A_STOP",
                severity=Severity.ERROR,
                message=(
                    f"Pattern {pattern_id} calls at '{name}', which is a "
                    f"'{ltype}' rather than a stop. Passengers cannot board there."
                ),
                entity="pattern_stop",
                entity_id=ps_id,
            )
        )

    lone_areas = db.execute(
        select(StopArea.id, StopArea.name).where(
            ~StopArea.id.in_(select(Location.area_id).where(Location.area_id.is_not(None)))
        )
    ).all()
    for area_id, name in lone_areas:
        issues.append(
            ValidationIssue(
                code="STOP_AREA_EMPTY",
                severity=Severity.INFO,
                message=f"Stop area '{name}' has no member stops.",
                entity="stop_area",
                entity_id=area_id,
            )
        )

    return ValidationReport.from_issues(issues)


routers: list[APIRouter] = [router, attributes_router, areas_router, transfers_router]
