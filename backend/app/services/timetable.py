"""Turn trips into a stops-down / trips-across grid.

Shared by the schedule grid in the UI and the PDF renderer, so the printed
timetable and the on-screen one can never disagree.

Several patterns can be combined into one grid. That is what a public
timetable normally is: line 127's express and stopping variants belong on one
sheet, not two, and a passenger reads a single column of stops. Merging those
stop lists is the interesting part -- see :func:`merge_stop_orders`.
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
    PatternAttribute,
    PatternStop,
    ScheduleVersion,
    StopTime,
    Trip,
)
from app.schemas.schedule import (
    Timetable,
    TimetableCell,
    TimetableColumn,
    TimetableRow,
)


def merge_stop_orders(orders: list[list[int]]) -> list[int]:
    """Merge several stop sequences into one that respects them all.

    Takes the longest sequence as the spine, then folds each remaining one in:
    stops already present anchor the position, and stops that are not get
    inserted just after the last anchor. So an express pattern that skips
    three stops slots into the stopping pattern's order rather than producing
    a second, near-duplicate list.

    This is a merge, not a topological sort: if two patterns genuinely
    disagree about the order of two stops, the first one wins. Real variants
    of a line do not disagree, and a pattern that does is a different route
    that wants its own sheet.
    """
    if not orders:
        return []

    ordered = sorted(orders, key=len, reverse=True)
    merged: list[int] = list(ordered[0])

    for sequence in ordered[1:]:
        position = 0  # where in `merged` we have got to
        for location_id in sequence:
            if location_id in merged:
                position = merged.index(location_id) + 1
                continue
            merged.insert(position, location_id)
            position += 1

    return merged


def _resolve_patterns(db: Session, pattern_ids: list[int]) -> list[Pattern]:
    patterns = list(
        db.scalars(select(Pattern).where(Pattern.id.in_(pattern_ids))).all()
    )
    found = {p.id for p in patterns}
    missing = [pid for pid in pattern_ids if pid not in found]
    if missing:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Pattern(s) not found: {sorted(missing)}"
        )
    # Preserve the caller's order; it decides which pattern is primary.
    by_id = {p.id: p for p in patterns}
    return [by_id[pid] for pid in pattern_ids]


def build_timetable(
    db: Session,
    schedule_version_id: int,
    pattern_ids: list[int],
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
    if not pattern_ids:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "At least one pattern is required."
        )

    patterns = _resolve_patterns(db, pattern_ids)
    primary = patterns[0]
    version = db.get(ScheduleVersion, schedule_version_id)
    if version is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Schedule version {schedule_version_id} not found"
        )

    line_ids = {p.line_id for p in patterns}
    if len(line_ids) > 1:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Combined timetables must be patterns of the same line.",
        )
    line = db.get(Line, primary.line_id)

    calendar_name = None
    if calendar_id is not None:
        calendar = db.get(Calendar, calendar_id)
        if calendar is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"Calendar {calendar_id} not found"
            )
        calendar_name = calendar.name

    # --- stops -------------------------------------------------------------
    stop_rows = db.execute(
        select(
            PatternStop.id,
            PatternStop.pattern_id,
            PatternStop.sequence,
            PatternStop.location_id,
            Location.name,
            PatternStop.is_timepoint,
        )
        .join(Location, PatternStop.location_id == Location.id)
        .where(PatternStop.pattern_id.in_([p.id for p in patterns]))
        .order_by(PatternStop.pattern_id, PatternStop.sequence)
    ).all()

    per_pattern: dict[int, list[int]] = {p.id: [] for p in patterns}
    location_names: dict[int, str] = {}
    timepoint_locations: set[int] = set()
    representative_stop: dict[int, int] = {}
    for ps_id, pattern_id, _sequence, location_id, name, is_timepoint in stop_rows:
        per_pattern[pattern_id].append(location_id)
        location_names[location_id] = name
        if is_timepoint:
            timepoint_locations.add(location_id)
        representative_stop.setdefault(location_id, ps_id)

    merged_locations = merge_stop_orders(
        [per_pattern[p.id] for p in patterns if per_pattern[p.id]]
    )

    if timepoints_only and timepoint_locations:
        keep = set(timepoint_locations)
        if merged_locations:
            # Keep the termini whether or not anyone flagged them.
            keep.add(merged_locations[0])
            keep.add(merged_locations[-1])
        merged_locations = [lid for lid in merged_locations if lid in keep]

    served_by = {
        location_id: {p.id for p in patterns if location_id in per_pattern[p.id]}
        for location_id in merged_locations
    }

    # --- trips -------------------------------------------------------------
    trip_stmt = (
        select(Trip.id, Trip.pattern_id, Trip.headsign)
        .where(Trip.schedule_version_id == schedule_version_id)
        .where(Trip.pattern_id.in_([p.id for p in patterns]))
    )
    if calendar_id is not None:
        trip_stmt = trip_stmt.where(Trip.calendar_id == calendar_id)
    trip_rows = db.execute(trip_stmt).all()
    trip_ids = [row[0] for row in trip_rows]
    trip_pattern = {row[0]: row[1] for row in trip_rows}
    trip_headsign = {row[0]: row[2] for row in trip_rows}
    total_trips = len(trip_ids)

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

    # Keyed by location, not pattern stop: in a combined grid two patterns'
    # stops at the same place share one row.
    times: dict[tuple[int, int], int] = {}
    if trip_ids:
        for trip_id, location_id, departure in db.execute(
            select(StopTime.trip_id, PatternStop.location_id, StopTime.departure_seconds)
            .join(PatternStop, StopTime.pattern_stop_id == PatternStop.id)
            .where(StopTime.trip_id.in_(trip_ids))
        ).all():
            times[(trip_id, location_id)] = departure

    rows = [
        TimetableRow(
            pattern_stop_id=representative_stop.get(location_id, 0),
            sequence=index + 1,
            location_id=location_id,
            location_name=location_names.get(location_id, str(location_id)),
            is_timepoint=location_id in timepoint_locations,
            partial=len(served_by.get(location_id, set())) < len(patterns),
            cells=[
                TimetableCell(
                    trip_id=trip_id,
                    departure_seconds=times.get((trip_id, location_id)),
                )
                for trip_id in trip_ids
            ],
        )
        for index, location_id in enumerate(merged_locations)
    ]

    badges = _pattern_badges(db, [p.id for p in patterns])
    pattern_names = {p.id: p.name for p in patterns}
    columns = [
        TimetableColumn(
            trip_id=trip_id,
            pattern_id=trip_pattern[trip_id],
            pattern_name=pattern_names.get(trip_pattern[trip_id]),
            line_short_name=line.short_name if line else None,
            headsign=trip_headsign.get(trip_id),
            badges=badges.get(trip_pattern[trip_id], []),
        )
        for trip_id in trip_ids
    ]

    combined = len(patterns) > 1
    return Timetable(
        schedule_version_id=schedule_version_id,
        schedule_version_name=version.name,
        line_id=primary.line_id,
        line_short_name=line.short_name if line else "",
        line_long_name=line.long_name if line else None,
        pattern_id=primary.id,
        pattern_name=(
            primary.name if not combined else f"{primary.name} + {len(patterns) - 1} more"
        ),
        pattern_ids=[p.id for p in patterns],
        pattern_names=[p.name for p in patterns],
        combined=combined,
        direction=primary.direction,
        calendar_id=calendar_id,
        calendar_name=calendar_name,
        trip_ids=trip_ids,
        columns=columns,
        rows=rows,
        total_trips=total_trips,
        limit=limit,
        offset=offset,
    )


def _pattern_badges(db: Session, pattern_ids: list[int]) -> dict[int, list[str]]:
    if not pattern_ids:
        return {}
    result: dict[int, list[str]] = {}
    for pattern_id, value in db.execute(
        select(PatternAttribute.pattern_id, PatternAttribute.attribute_value)
        .where(PatternAttribute.pattern_id.in_(pattern_ids))
        .order_by(PatternAttribute.attribute_key)
    ).all():
        if (value or "").strip():
            result.setdefault(pattern_id, []).append(value.strip())
    return result
