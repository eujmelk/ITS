"""Lines module: lines, generic line attributes, patterns and pattern stops."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.deps import DbSession, ReaderUser, require_planner
from app.enums import LocationType
from app.models import Line, Location, Pattern, PatternAttribute, PatternStop, Trip
from app.schemas.lines import (
    LineCreate,
    LineRead,
    LineUpdate,
    PatternAttributeCreate,
    PatternAttributeRead,
    PatternAttributeUpdate,
    PatternCreate,
    PatternDetail,
    PatternStopRead,
    PatternStopsReplace,
    PatternUpdate,
)
from app.services import pattern_attributes as pattern_attribute_service
from app.services.crud import check_exists, commit, crud_router, get_or_404


def serialize_line(obj: Line, db: Session) -> LineRead:
    data = LineRead.model_validate(obj)
    data.pattern_count = len(obj.patterns)
    return data


def pattern_badges(attributes) -> list[str]:
    """The values printed as bubbles: "TYPE=EXP" shows as "EXP"."""
    return pattern_attribute_service.badge_values(attributes)


def _serialize_pattern_stop(stop: PatternStop) -> PatternStopRead:
    data = PatternStopRead.model_validate(stop)
    if stop.location is not None:
        data.location_name = stop.location.name
        data.location_code = stop.location.code
        data.lat = stop.location.lat
        data.lon = stop.location.lon
    return data


def serialize_pattern(obj: Pattern, db: Session) -> PatternDetail:
    data = PatternDetail.model_validate(obj)
    data.badges = pattern_badges(obj.attributes)
    stops = sorted(obj.pattern_stops, key=lambda s: s.sequence)
    data.stops = [_serialize_pattern_stop(s) for s in stops]
    data.stop_count = len(stops)
    # The first stop's run time is the time to reach it, which is nothing --
    # the trip starts there.
    data.total_run_seconds = sum(
        s.default_run_seconds + s.default_dwell_seconds for s in stops[1:]
    ) + (stops[0].default_dwell_seconds if stops else 0)
    return data


router = crud_router(
    model=Line,
    read_schema=LineRead,
    create_schema=LineCreate,
    update_schema=LineUpdate,
    prefix="/lines",
    tags=["lines"],
    search_fields=("short_name", "long_name", "description"),
    filter_fields=("mode", "is_active"),
    order_by=("sort_order", "short_name"),
    options=(selectinload(Line.patterns),),
    serialize=serialize_line,
    label="Line",
)


def _replace_pattern_attributes(obj: Pattern, entries, db: Session) -> None:
    # Reserved GTFS keys are checked before anything is written, so a bad
    # value is a 422 rather than a feed that fails validation weeks later.
    pattern_attribute_service.validate(entries)
    for existing in list(obj.attributes):
        db.delete(existing)
    db.flush()
    for entry in entries:
        db.add(
            PatternAttribute(
                pattern_id=obj.id,
                attribute_key=entry.attribute_key.strip(),
                attribute_value=entry.attribute_value,
            )
        )
    db.flush()


def _pattern_on_create(obj: Pattern, payload: PatternCreate, db: Session) -> None:
    check_exists(db, Line, obj.line_id, "line_id")
    if payload.stops:
        _write_pattern_stops(db, obj, payload.stops)
    if payload.attributes:
        _replace_pattern_attributes(obj, payload.attributes, db)


def _pattern_on_update(obj: Pattern, payload: PatternUpdate, db: Session) -> None:
    if payload.attributes is not None:
        _replace_pattern_attributes(obj, payload.attributes, db)


def _pattern_on_delete(obj: Pattern, db: Session) -> None:
    trip_id = db.scalar(select(Trip.id).where(Trip.pattern_id == obj.id).limit(1))
    if trip_id is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Pattern '{obj.name}' still has trips (e.g. trip {trip_id}). "
            "Delete or re-point those trips first.",
        )


patterns_router = crud_router(
    model=Pattern,
    read_schema=PatternDetail,
    create_schema=PatternCreate,
    update_schema=PatternUpdate,
    prefix="/patterns",
    tags=["lines"],
    search_fields=("name", "headsign"),
    filter_fields=("line_id", "direction", "is_primary"),
    order_by=("line_id", "direction", "name"),
    options=(
        selectinload(Pattern.pattern_stops).selectinload(PatternStop.location),
        selectinload(Pattern.attributes),
    ),
    serialize=serialize_pattern,
    on_create=_pattern_on_create,
    on_update=_pattern_on_update,
    on_delete=_pattern_on_delete,
    label="Pattern",
)

def _attribute_check(obj: PatternAttribute, payload, db: Session) -> None:
    pattern_attribute_service.validate([obj])


pattern_attributes_router = crud_router(
    model=PatternAttribute,
    read_schema=PatternAttributeRead,
    create_schema=PatternAttributeCreate,
    update_schema=PatternAttributeUpdate,
    prefix="/pattern-attributes",
    tags=["lines"],
    search_fields=("attribute_key", "attribute_value"),
    filter_fields=("pattern_id", "attribute_key"),
    order_by=("pattern_id", "attribute_key"),
    on_create=_attribute_check,
    on_update=_attribute_check,
    label="Pattern attribute",
)


@pattern_attributes_router.get(
    "/reserved/gtfs",
    response_model=list[dict],
    summary="Attribute keys that map to GTFS fields",
)
def reserved_keys(_user: ReaderUser):
    """Keys whose values are validated and exported into ``trips.txt``.

    Everything else is internal: it prints as a bubble but GTFS has nowhere
    to carry it.
    """
    return [
        {
            "key": spec.key,
            "gtfs_field": spec.gtfs_field,
            "description": spec.description,
            "accepted": ["yes", "no", "unknown"],
        }
        for spec in pattern_attribute_service.GTFS_ATTRIBUTES
    ]


def _write_pattern_stops(db: Session, pattern: Pattern, stops) -> None:
    """Replace a pattern's stop list, renumbering sequences 1..n."""
    location_ids = [s.location_id for s in stops]
    if location_ids:
        found = db.execute(
            select(Location.id, Location.name, Location.location_type).where(
                Location.id.in_(set(location_ids))
            )
        ).all()
        by_id = {row[0]: row for row in found}
        missing = [lid for lid in location_ids if lid not in by_id]
        if missing:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Unknown location ids: {sorted(set(missing))}",
            )
        # Service-layer rule, deliberately not a DB constraint: a pattern
        # calls at stops, not at depots.
        wrong_type = [
            f"{by_id[lid][1]} ({by_id[lid][2]})"
            for lid in dict.fromkeys(location_ids)
            if by_id[lid][2] != LocationType.STOP.value
        ]
        if wrong_type:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "A pattern can only call at 'stop' locations. Rejected: "
                + ", ".join(wrong_type),
            )

    for existing in list(pattern.pattern_stops):
        db.delete(existing)
    db.flush()

    ordered = sorted(stops, key=lambda s: s.sequence)
    for index, entry in enumerate(ordered, start=1):
        db.add(
            PatternStop(
                pattern_id=pattern.id,
                sequence=index,
                location_id=entry.location_id,
                is_timepoint=entry.is_timepoint,
                default_run_seconds=entry.default_run_seconds,
                default_dwell_seconds=entry.default_dwell_seconds,
                distance_from_start_m=entry.distance_from_start_m,
                pickup_type=entry.pickup_type.value,
                drop_off_type=entry.drop_off_type.value,
            )
        )
    db.flush()


@patterns_router.put(
    "/{pattern_id}/stops",
    response_model=PatternDetail,
    summary="Replace a pattern's stop list",
    dependencies=[Depends(require_planner)],
)
def replace_pattern_stops(pattern_id: int, payload: PatternStopsReplace, db: DbSession):
    """Send the finished stop list; sequences are renumbered 1..n.

    Whole-list replacement rather than row-at-a-time editing: reordering
    otherwise needs a sequence of updates that leave the pattern temporarily
    inconsistent, and any trip built on it invalid in between.
    """
    pattern = get_or_404(db, Pattern, pattern_id, "Pattern")

    trip_id = db.scalar(select(Trip.id).where(Trip.pattern_id == pattern_id).limit(1))
    if trip_id is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Pattern '{pattern.name}' already has trips (e.g. trip {trip_id}), "
            "whose stop times reference the current stop list. Changing the "
            "stops now would orphan them -- copy the pattern instead.",
        )

    _write_pattern_stops(db, pattern, payload.stops)
    commit(db)
    db.refresh(pattern)
    return serialize_pattern(pattern, db)


@patterns_router.post(
    "/{pattern_id}/duplicate",
    response_model=PatternDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Copy a pattern, stops included",
    dependencies=[Depends(require_planner)],
)
def duplicate_pattern(pattern_id: int, db: DbSession, name: str | None = None):
    """Copy a pattern so a variant can be edited without touching live trips."""
    source = get_or_404(db, Pattern, pattern_id, "Pattern")
    copy = Pattern(
        line_id=source.line_id,
        name=name or f"{source.name} (copy)",
        direction=source.direction,
        headsign=source.headsign,
        is_primary=False,
        notes=source.notes,
    )
    db.add(copy)
    db.flush()
    for stop in sorted(source.pattern_stops, key=lambda s: s.sequence):
        db.add(
            PatternStop(
                pattern_id=copy.id,
                sequence=stop.sequence,
                location_id=stop.location_id,
                is_timepoint=stop.is_timepoint,
                default_run_seconds=stop.default_run_seconds,
                default_dwell_seconds=stop.default_dwell_seconds,
                distance_from_start_m=stop.distance_from_start_m,
                pickup_type=stop.pickup_type,
                drop_off_type=stop.drop_off_type,
            )
        )
    # A variant of an express pattern is still express until told otherwise.
    for attribute in source.attributes:
        db.add(
            PatternAttribute(
                pattern_id=copy.id,
                attribute_key=attribute.attribute_key,
                attribute_value=attribute.attribute_value,
            )
        )
    commit(db)
    db.refresh(copy)
    return serialize_pattern(copy, db)


routers: list[APIRouter] = [router, patterns_router, pattern_attributes_router]
