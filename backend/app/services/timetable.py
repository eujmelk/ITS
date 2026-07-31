"""Turn a pattern's trips into a stops-down / trips-across grid.

Shared by the schedule grid in the UI and the PDF renderer, so the printed
timetable and the on-screen one can never disagree.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Calendar,
    Line,
    Location,
    Pattern,
    PatternStop,
    ScheduleVersion,
    StopTime,
    Trip,
)
from app.schemas.schedule import Timetable, TimetableCell, TimetableRow


def build_timetable(
    db: Session,
    schedule_version_id: int,
    pattern_id: int,
    calendar_id: int | None = None,
    timepoints_only: bool = False,
    limit: int | None = None,
    offset: int = 0,
) -> Timetable:
    """Build the grid, optionally for one page of trip columns.

    A busy urban pattern can carry several hundred trips a day. Rendering that
    as one table is ~300 columns x 40 rows of DOM, so the columns are paged:
    trips are ordered by departure first, then sliced, and only the sliced
    trips' stop times are fetched.
    """
    pattern = db.get(Pattern, pattern_id)
    if pattern is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Pattern {pattern_id} not found")
    version = db.get(ScheduleVersion, schedule_version_id)
    if version is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Schedule version {schedule_version_id} not found"
        )
    line = db.get(Line, pattern.line_id)

    calendar_name = None
    if calendar_id is not None:
        calendar = db.get(Calendar, calendar_id)
        if calendar is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"Calendar {calendar_id} not found"
            )
        calendar_name = calendar.name

    stop_rows = db.execute(
        select(
            PatternStop.id,
            PatternStop.sequence,
            PatternStop.location_id,
            Location.name,
            PatternStop.is_timepoint,
        )
        .join(Location, PatternStop.location_id == Location.id)
        .where(PatternStop.pattern_id == pattern_id)
        .order_by(PatternStop.sequence)
    ).all()

    if timepoints_only:
        # Keep the first and last stop even when they are not flagged, so the
        # printed column always has a recognisable origin and destination.
        marked = [r for r in stop_rows if r[4]]
        if marked and len(marked) < len(stop_rows):
            keep_ids = {r[0] for r in marked} | {stop_rows[0][0], stop_rows[-1][0]}
            stop_rows = [r for r in stop_rows if r[0] in keep_ids]

    trip_stmt = (
        select(Trip.id)
        .where(Trip.schedule_version_id == schedule_version_id)
        .where(Trip.pattern_id == pattern_id)
    )
    if calendar_id is not None:
        trip_stmt = trip_stmt.where(Trip.calendar_id == calendar_id)
    trip_ids = list(db.scalars(trip_stmt).all())
    total_trips = len(trip_ids)

    # Order the columns before slicing them. Only the first departure of each
    # trip is needed for that, which is one cheap grouped query rather than
    # every stop time on the pattern.
    first_departure: dict[int, int] = {}
    if trip_ids:
        first_departure = {
            trip_id: departure
            for trip_id, departure in db.execute(
                select(StopTime.trip_id, func.min(StopTime.departure_seconds))
                .where(StopTime.trip_id.in_(trip_ids))
                .group_by(StopTime.trip_id)
            ).all()
        }

    # Columns run left to right in departure order; trips with no stop times
    # sort last rather than disappearing, so the gap is visible.
    trip_ids.sort(key=lambda t: (first_departure.get(t) is None, first_departure.get(t, 0), t))

    if limit is not None:
        trip_ids = trip_ids[offset : offset + limit]
    elif offset:
        trip_ids = trip_ids[offset:]

    times: dict[tuple[int, int], int] = {}
    if trip_ids:
        for trip_id, pattern_stop_id, departure in db.execute(
            select(StopTime.trip_id, StopTime.pattern_stop_id, StopTime.departure_seconds)
            .where(StopTime.trip_id.in_(trip_ids))
        ).all():
            times[(trip_id, pattern_stop_id)] = departure

    rows = [
        TimetableRow(
            pattern_stop_id=ps_id,
            sequence=sequence,
            location_id=location_id,
            location_name=location_name,
            is_timepoint=is_timepoint,
            cells=[
                TimetableCell(
                    trip_id=trip_id,
                    departure_seconds=times.get((trip_id, ps_id)),
                )
                for trip_id in trip_ids
            ],
        )
        for ps_id, sequence, location_id, location_name, is_timepoint in stop_rows
    ]

    return Timetable(
        schedule_version_id=schedule_version_id,
        schedule_version_name=version.name,
        line_id=pattern.line_id,
        line_short_name=line.short_name if line else "",
        line_long_name=line.long_name if line else None,
        pattern_id=pattern.id,
        pattern_name=pattern.name,
        direction=pattern.direction,
        calendar_id=calendar_id,
        calendar_name=calendar_name,
        trip_ids=trip_ids,
        rows=rows,
        total_trips=total_trips,
        limit=limit,
        offset=offset,
    )
