"""Trip construction: generated stop times, shifting, and headway series."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Calendar, Line, Pattern, PatternStop, ScheduleVersion, StopTime, Trip
from app.schemas.schedule import StopTimeBase, TripCreate, TripGenerateRequest
from app.services.crud import check_exists
from app.timeutil import MAX_SERVICE_SECONDS, format_time


def generate_stop_times(
    db: Session, pattern_id: int, start_seconds: int
) -> list[StopTimeBase]:
    """Lay a pattern's default running times out from one departure time.

    ``default_run_seconds`` on a pattern stop is the time taken to reach it
    from the previous stop; ``default_dwell_seconds`` is the time spent at it.
    The first stop's run time is ignored -- the trip starts there.
    """
    stops = db.scalars(
        select(PatternStop)
        .where(PatternStop.pattern_id == pattern_id)
        .order_by(PatternStop.sequence)
    ).all()
    if not stops:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Pattern {pattern_id} has no stops, so trip times cannot be generated.",
        )

    result: list[StopTimeBase] = []
    cursor = start_seconds
    for index, stop in enumerate(stops):
        arrival = cursor if index == 0 else cursor + stop.default_run_seconds
        departure = arrival + stop.default_dwell_seconds
        result.append(
            StopTimeBase(
                pattern_stop_id=stop.id,
                arrival_seconds=arrival,
                departure_seconds=departure,
                is_timepoint=stop.is_timepoint,
                pickup_type=stop.pickup_type,
                drop_off_type=stop.drop_off_type,
            )
        )
        cursor = departure

    if cursor > MAX_SERVICE_SECONDS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Generated trip runs past the end of the service day (48:00:00). "
            "Check the pattern's default running times.",
        )
    return result


def _validate_pattern_stops(db: Session, pattern_id: int, times: list[StopTimeBase]) -> None:
    valid = {
        row
        for row in db.scalars(
            select(PatternStop.id).where(PatternStop.pattern_id == pattern_id)
        ).all()
    }
    unknown = [t.pattern_stop_id for t in times if t.pattern_stop_id not in valid]
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"pattern_stop_id {unknown} do not belong to pattern {pattern_id}.",
        )
    seen: set[int] = set()
    duplicates: set[int] = set()
    for entry in times:
        if entry.pattern_stop_id in seen:
            duplicates.add(entry.pattern_stop_id)
        seen.add(entry.pattern_stop_id)
    if duplicates:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"pattern_stop_id {sorted(duplicates)} appear more than once.",
        )


def _validate_ordering(db: Session, pattern_id: int, times: list[StopTimeBase]) -> None:
    """A trip must still call somewhere, in the pattern's order.

    Skipping stops is allowed; skipping so many that nothing is left, or
    entering times that run backwards along the route, is not -- both would
    produce a timetable column nobody can read.
    """
    if len(times) < 2:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "A trip must call at at least two stops. Skip fewer stops, or "
            "delete the trip.",
        )

    sequences = {
        ps_id: sequence
        for ps_id, sequence in db.execute(
            select(PatternStop.id, PatternStop.sequence).where(
                PatternStop.pattern_id == pattern_id
            )
        ).all()
    }
    ordered = sorted(times, key=lambda t: sequences.get(t.pattern_stop_id, 0))

    for previous, current in zip(ordered, ordered[1:]):
        if current.arrival_seconds < previous.departure_seconds:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Stop {sequences.get(current.pattern_stop_id)} arrives at "
                f"{format_time(current.arrival_seconds)}, before stop "
                f"{sequences.get(previous.pattern_stop_id)} is departed at "
                f"{format_time(previous.departure_seconds)}. Times must run "
                "forwards along the route.",
            )


def set_stop_times(db: Session, trip: Trip, times: list[StopTimeBase]) -> None:
    """Replace a trip's stop times wholesale.

    A pattern stop with no row here is **skipped** by this trip: the vehicle
    runs past without calling. That is how a limited-stop or short-working
    journey is expressed without needing a separate pattern, and the timetable
    grid renders the gap as a dot.
    """
    _validate_pattern_stops(db, trip.pattern_id, times)
    _validate_ordering(db, trip.pattern_id, times)

    for existing in list(trip.stop_times):
        db.delete(existing)
    db.flush()

    for entry in times:
        db.add(
            StopTime(
                trip_id=trip.id,
                pattern_stop_id=entry.pattern_stop_id,
                arrival_seconds=entry.arrival_seconds,
                departure_seconds=entry.departure_seconds,
                is_timepoint=entry.is_timepoint,
                pickup_type=entry.pickup_type.value,
                drop_off_type=entry.drop_off_type.value,
            )
        )
    db.flush()


def shift_trip(db: Session, trip: Trip, seconds: int) -> None:
    """Move a whole trip earlier or later, preserving its internal shape."""
    times = list(trip.stop_times)
    if not times:
        return
    lowest = min(t.arrival_seconds for t in times)
    highest = max(t.departure_seconds for t in times)
    if lowest + seconds < 0 or highest + seconds > MAX_SERVICE_SECONDS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Shifting this trip would move it outside the service day.",
        )
    for entry in times:
        entry.arrival_seconds += seconds
        entry.departure_seconds += seconds
    db.flush()


def create_trip(db: Session, payload: TripCreate) -> Trip:
    check_exists(db, ScheduleVersion, payload.schedule_version_id, "schedule_version_id")
    pattern = check_exists(db, Pattern, payload.pattern_id, "pattern_id")
    calendar = check_exists(db, Calendar, payload.calendar_id, "calendar_id")

    if calendar.schedule_version_id != payload.schedule_version_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Calendar '{calendar.name}' belongs to a different schedule board.",
        )

    headsign = payload.headsign or pattern.headsign
    trip = Trip(
        schedule_version_id=payload.schedule_version_id,
        pattern_id=payload.pattern_id,
        calendar_id=payload.calendar_id,
        headsign=headsign,
        short_name=payload.short_name,
        block_id=payload.block_id,
        vehicle_type_id=payload.vehicle_type_id,
        wheelchair_accessible=payload.wheelchair_accessible,
        notes=payload.notes,
    )
    db.add(trip)
    db.flush()

    times = payload.stop_times
    if not times:
        times = generate_stop_times(db, payload.pattern_id, payload.start_time)
    set_stop_times(db, trip, times)
    return trip


def generate_series(db: Session, payload: TripGenerateRequest) -> list[int]:
    """Create one trip per headway step across the requested window."""
    check_exists(db, ScheduleVersion, payload.schedule_version_id, "schedule_version_id")
    pattern = check_exists(db, Pattern, payload.pattern_id, "pattern_id")
    calendar = check_exists(db, Calendar, payload.calendar_id, "calendar_id")

    if calendar.schedule_version_id != payload.schedule_version_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Calendar '{calendar.name}' belongs to a different schedule board.",
        )

    line = db.get(Line, pattern.line_id)
    headway = payload.headway_minutes * 60
    departures = list(range(payload.first_departure, payload.last_departure + 1, headway))

    created: list[int] = []
    for departure in departures:
        trip = Trip(
            schedule_version_id=payload.schedule_version_id,
            pattern_id=payload.pattern_id,
            calendar_id=payload.calendar_id,
            headsign=payload.headsign or pattern.headsign,
            short_name=line.short_name if line else None,
            vehicle_type_id=payload.vehicle_type_id,
        )
        db.add(trip)
        db.flush()
        set_stop_times(db, trip, generate_stop_times(db, payload.pattern_id, departure))
        created.append(trip.id)

    return created
