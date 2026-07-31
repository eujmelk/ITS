"""Which services actually run on a given date.

Shared by the roster (a duty is worked on a real date) and the itinerary
finder (a journey is searched for on a real date). Getting this wrong is the
classic transit bug: a timetable that looks right all week and is wrong on
Good Friday.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import ExceptionType
from app.models import Calendar, CalendarException, ScheduleVersion

_WEEKDAY_COLUMNS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def active_schedule_versions(db: Session, date: dt.date) -> list[ScheduleVersion]:
    """Boards whose validity window covers ``date``.

    Archived boards are excluded; a draft board is included so a planner can
    test next season before it goes live.
    """
    return list(
        db.scalars(
            select(ScheduleVersion)
            .where(ScheduleVersion.start_date <= date)
            .where(ScheduleVersion.end_date >= date)
            .where(ScheduleVersion.status != "archived")
            .order_by(ScheduleVersion.start_date.desc())
        ).all()
    )


def active_calendar_ids(
    db: Session, date: dt.date, schedule_version_id: int | None = None
) -> set[int]:
    """Calendars running on ``date``.

    A calendar runs when its weekday flag is set and the date falls inside its
    own window (or its board's, if it has none). An exception row then
    overrides that either way -- which is the whole point of exceptions, so
    they are applied last.
    """
    stmt = select(Calendar, ScheduleVersion).join(
        ScheduleVersion, Calendar.schedule_version_id == ScheduleVersion.id
    )
    if schedule_version_id is not None:
        stmt = stmt.where(Calendar.schedule_version_id == schedule_version_id)
    else:
        stmt = stmt.where(ScheduleVersion.start_date <= date).where(
            ScheduleVersion.end_date >= date
        ).where(ScheduleVersion.status != "archived")

    running: set[int] = set()
    candidates: set[int] = set()
    for calendar, version in db.execute(stmt).all():
        candidates.add(calendar.id)

        start = calendar.start_date or version.start_date
        end = calendar.end_date or version.end_date
        if start and date < start:
            continue
        if end and date > end:
            continue
        if getattr(calendar, _WEEKDAY_COLUMNS[date.weekday()]):
            running.add(calendar.id)

    if not candidates:
        return running

    for calendar_id, exception_type in db.execute(
        select(CalendarException.calendar_id, CalendarException.exception_type)
        .where(CalendarException.date == date)
        .where(CalendarException.calendar_id.in_(candidates))
    ).all():
        if exception_type == ExceptionType.ADDED.value:
            running.add(calendar_id)
        else:
            running.discard(calendar_id)

    return running
