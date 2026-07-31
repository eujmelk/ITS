"""Schedule boards, calendars, trips and the timetable grid."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.deps import DbSession, ReaderUser, require_planner
from app.models import (
    Block,
    Calendar,
    CalendarException,
    Line,
    Pattern,
    PatternStop,
    ScheduleVersion,
    StopTime,
    Trip,
)
from app.schemas.schedule import (
    CalendarCreate,
    CalendarExceptionCreate,
    CalendarExceptionRead,
    CalendarExceptionUpdate,
    CalendarRead,
    CalendarUpdate,
    ScheduleVersionCreate,
    ScheduleVersionRead,
    ScheduleVersionUpdate,
    StopTimeRead,
    Timetable,
    TripCreate,
    TripDetail,
    TripGenerateRequest,
    TripGenerateResult,
    TripRead,
    TripUpdate,
)
from app.services import trips as trip_service
from app.services.crud import apply_updates, check_exists, commit, crud_router, get_or_404
from app.services.timetable import build_timetable

# --------------------------------------------------------------------------
# Schedule versions (boards)
# --------------------------------------------------------------------------


def serialize_version(obj: ScheduleVersion, db: Session) -> ScheduleVersionRead:
    data = ScheduleVersionRead.model_validate(obj)
    data.trip_count = (
        db.scalar(
            select(func.count())
            .select_from(Trip)
            .where(Trip.schedule_version_id == obj.id)
        )
        or 0
    )
    data.block_count = (
        db.scalar(
            select(func.count())
            .select_from(Block)
            .where(Block.schedule_version_id == obj.id)
        )
        or 0
    )
    return data


versions_router = crud_router(
    model=ScheduleVersion,
    read_schema=ScheduleVersionRead,
    create_schema=ScheduleVersionCreate,
    update_schema=ScheduleVersionUpdate,
    prefix="/schedule-versions",
    tags=["schedule"],
    search_fields=("name", "description"),
    filter_fields=("status",),
    order_by=("start_date", "name"),
    serialize=serialize_version,
    label="Schedule board",
)


@versions_router.post(
    "/{version_id}/duplicate",
    response_model=ScheduleVersionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Copy a board, with its calendars and trips",
    dependencies=[Depends(require_planner)],
)
def duplicate_version(
    version_id: int,
    db: DbSession,
    name: str = Query(description="Name for the new board"),
    include_trips: bool = Query(default=True),
    include_blocks: bool = Query(default=False),
):
    """Start next season's board from this one instead of from nothing.

    Blocks are copied only on request: their pieces reference specific trips,
    so copying them without the trips would produce a broken block.
    """
    source = get_or_404(db, ScheduleVersion, version_id, "Schedule board")
    if include_blocks and not include_trips:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Blocks reference trips, so include_trips must be true to copy them.",
        )

    copy = ScheduleVersion(
        name=name,
        description=source.description,
        start_date=source.start_date,
        end_date=source.end_date,
        status="draft",
    )
    db.add(copy)
    db.flush()

    calendar_map: dict[int, int] = {}
    for calendar in source.calendars:
        new_calendar = Calendar(
            schedule_version_id=copy.id,
            name=calendar.name,
            monday=calendar.monday,
            tuesday=calendar.tuesday,
            wednesday=calendar.wednesday,
            thursday=calendar.thursday,
            friday=calendar.friday,
            saturday=calendar.saturday,
            sunday=calendar.sunday,
            start_date=calendar.start_date,
            end_date=calendar.end_date,
        )
        db.add(new_calendar)
        db.flush()
        calendar_map[calendar.id] = new_calendar.id
        for exception in calendar.exceptions:
            db.add(
                CalendarException(
                    calendar_id=new_calendar.id,
                    date=exception.date,
                    exception_type=exception.exception_type,
                    notes=exception.notes,
                )
            )

    if include_trips:
        source_trips = db.scalars(
            select(Trip)
            .where(Trip.schedule_version_id == version_id)
            .options(selectinload(Trip.stop_times))
        ).all()
        block_map: dict[int, int] = {}
        if include_blocks:
            for block in db.scalars(
                select(Block).where(Block.schedule_version_id == version_id)
            ).all():
                new_block = Block(
                    schedule_version_id=copy.id,
                    name=block.name,
                    vehicle_id=block.vehicle_id,
                    vehicle_type_id=block.vehicle_type_id,
                    notes=block.notes,
                )
                db.add(new_block)
                db.flush()
                block_map[block.id] = new_block.id

        for trip in source_trips:
            new_trip = Trip(
                schedule_version_id=copy.id,
                pattern_id=trip.pattern_id,
                calendar_id=calendar_map[trip.calendar_id],
                block_id=block_map.get(trip.block_id) if trip.block_id else None,
                headsign=trip.headsign,
                short_name=trip.short_name,
                vehicle_type_id=trip.vehicle_type_id,
                wheelchair_accessible=trip.wheelchair_accessible,
                notes=trip.notes,
            )
            db.add(new_trip)
            db.flush()
            for stop_time in trip.stop_times:
                db.add(
                    StopTime(
                        trip_id=new_trip.id,
                        pattern_stop_id=stop_time.pattern_stop_id,
                        arrival_seconds=stop_time.arrival_seconds,
                        departure_seconds=stop_time.departure_seconds,
                        is_timepoint=stop_time.is_timepoint,
                        pickup_type=stop_time.pickup_type,
                        drop_off_type=stop_time.drop_off_type,
                    )
                )

    commit(db)
    db.refresh(copy)
    return serialize_version(copy, db)


# --------------------------------------------------------------------------
# Calendars
# --------------------------------------------------------------------------


def _calendar_on_create(obj: Calendar, payload: CalendarCreate, db: Session) -> None:
    check_exists(db, ScheduleVersion, obj.schedule_version_id, "schedule_version_id")


def _calendar_on_delete(obj: Calendar, db: Session) -> None:
    trip_id = db.scalar(select(Trip.id).where(Trip.calendar_id == obj.id).limit(1))
    if trip_id is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Calendar '{obj.name}' is still used by trips (e.g. trip {trip_id}).",
        )


calendars_router = crud_router(
    model=Calendar,
    read_schema=CalendarRead,
    create_schema=CalendarCreate,
    update_schema=CalendarUpdate,
    prefix="/calendars",
    tags=["schedule"],
    search_fields=("name",),
    filter_fields=("schedule_version_id",),
    order_by=("schedule_version_id", "name"),
    on_create=_calendar_on_create,
    on_delete=_calendar_on_delete,
    label="Calendar",
)

calendar_exceptions_router = crud_router(
    model=CalendarException,
    read_schema=CalendarExceptionRead,
    create_schema=CalendarExceptionCreate,
    update_schema=CalendarExceptionUpdate,
    prefix="/calendar-exceptions",
    tags=["schedule"],
    filter_fields=("calendar_id", "exception_type"),
    order_by=("calendar_id", "date"),
    label="Calendar exception",
)

# --------------------------------------------------------------------------
# Trips
# --------------------------------------------------------------------------


def _serialize_stop_time(stop_time: StopTime) -> StopTimeRead:
    data = StopTimeRead.model_validate(stop_time)
    pattern_stop = stop_time.pattern_stop
    if pattern_stop is not None:
        data.sequence = pattern_stop.sequence
        data.location_id = pattern_stop.location_id
        if pattern_stop.location is not None:
            data.location_name = pattern_stop.location.name
    return data


def _fill_trip_common(obj: Trip, data: TripRead, db: Session) -> None:
    if obj.pattern is not None:
        data.pattern_name = obj.pattern.name
        data.line_id = obj.pattern.line_id
        if obj.pattern.line is not None:
            data.line_short_name = obj.pattern.line.short_name
    if obj.calendar is not None:
        data.calendar_name = obj.calendar.name
    if obj.block_id is not None:
        block = db.get(Block, obj.block_id)
        data.block_name = block.name if block else None
    times = list(obj.stop_times)
    data.stop_count = len(times)
    if times:
        data.start_seconds = min(t.departure_seconds for t in times)
        data.end_seconds = max(t.arrival_seconds for t in times)


def serialize_trip(obj: Trip, db: Session) -> TripRead:
    data = TripRead.model_validate(obj)
    _fill_trip_common(obj, data, db)
    return data


def serialize_trip_detail(obj: Trip, db: Session) -> TripDetail:
    data = TripDetail.model_validate(obj)
    _fill_trip_common(obj, data, db)
    data.stop_times = [
        _serialize_stop_time(st)
        for st in sorted(
            obj.stop_times,
            key=lambda st: st.pattern_stop.sequence if st.pattern_stop else 0,
        )
    ]
    return data


_TRIP_OPTIONS = (
    selectinload(Trip.pattern).selectinload(Pattern.line),
    selectinload(Trip.calendar),
    selectinload(Trip.stop_times)
    .selectinload(StopTime.pattern_stop)
    .selectinload(PatternStop.location),
)

# Create/update go through dedicated endpoints below, because both accept a
# stop-times payload that the generic factory knows nothing about.
trips_router = crud_router(
    model=Trip,
    read_schema=TripRead,
    create_schema=None,
    update_schema=None,
    prefix="/trips",
    tags=["schedule"],
    search_fields=("headsign", "short_name"),
    filter_fields=(
        "schedule_version_id",
        "pattern_id",
        "calendar_id",
        "block_id",
        "vehicle_type_id",
    ),
    order_by=("id",),
    options=_TRIP_OPTIONS,
    serialize=serialize_trip,
    label="Trip",
)


@trips_router.post(
    "",
    response_model=TripDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create a trip",
    dependencies=[Depends(require_planner)],
)
def create_trip(payload: TripCreate, db: DbSession):
    """Give either an explicit ``stop_times`` list or a ``start_time``.

    With ``start_time`` the times are laid out from the pattern's default run
    and dwell values, then remain editable per trip.
    """
    trip = trip_service.create_trip(db, payload)
    commit(db)
    db.refresh(trip)
    return serialize_trip_detail(trip, db)


@trips_router.patch(
    "/{trip_id}",
    response_model=TripDetail,
    summary="Update a trip",
    dependencies=[Depends(require_planner)],
)
def update_trip(trip_id: int, payload: TripUpdate, db: DbSession):
    trip = get_or_404(db, Trip, trip_id, "Trip")
    data = payload.model_dump(exclude_unset=True)

    if "pattern_id" in data and data["pattern_id"] != trip.pattern_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "A trip's pattern cannot be changed -- its stop times belong to "
            "the current pattern's stops. Create a new trip instead.",
        )

    apply_updates(trip, payload, skip=("stop_times", "shift_seconds", "pattern_id"))

    if payload.stop_times is not None:
        trip_service.set_stop_times(db, trip, payload.stop_times)
    if payload.shift_seconds:
        trip_service.shift_trip(db, trip, payload.shift_seconds)

    commit(db)
    db.refresh(trip)
    return serialize_trip_detail(trip, db)


@trips_router.get(
    "/{trip_id}/detail", response_model=TripDetail, summary="Trip with its stop times"
)
def trip_detail(trip_id: int, db: DbSession, _user: ReaderUser):
    trip = get_or_404(db, Trip, trip_id, "Trip")
    return serialize_trip_detail(trip, db)


@trips_router.post(
    "/generate",
    response_model=TripGenerateResult,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a series of trips at a fixed headway",
    dependencies=[Depends(require_planner)],
)
def generate_trips(payload: TripGenerateRequest, db: DbSession):
    """"Line 4 outbound, every 12 minutes from 06:00 to 09:00, weekdays"."""
    created = trip_service.generate_series(db, payload)
    commit(db)
    return TripGenerateResult(created_trip_ids=created, count=len(created))


@trips_router.post(
    "/bulk-delete",
    summary="Delete many trips at once",
    dependencies=[Depends(require_planner)],
)
def bulk_delete_trips(trip_ids: list[int], db: DbSession) -> dict:
    if not trip_ids:
        return {"deleted": 0}
    rows = db.scalars(select(Trip).where(Trip.id.in_(trip_ids))).all()
    for trip in rows:
        db.delete(trip)
    commit(db)
    return {"deleted": len(rows)}


# --------------------------------------------------------------------------
# Timetable grid
# --------------------------------------------------------------------------

timetable_router = APIRouter(prefix="/timetables", tags=["schedule"])


@timetable_router.get(
    "", response_model=Timetable, summary="A pattern's trips as a printable grid"
)
def get_timetable(
    db: DbSession,
    _user: ReaderUser,
    schedule_version_id: int,
    pattern_id: int,
    calendar_id: int | None = None,
    timepoints_only: bool = False,
):
    return build_timetable(
        db, schedule_version_id, pattern_id, calendar_id, timepoints_only
    )


routers: list[APIRouter] = [
    versions_router,
    calendars_router,
    calendar_exceptions_router,
    trips_router,
    timetable_router,
]
