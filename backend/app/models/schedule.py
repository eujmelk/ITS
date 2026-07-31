from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.enums import BoardingType, VersionStatus
from app.models.base import Base, TimestampMixin
from app.models.lines import Pattern, PatternStop


class ScheduleVersion(TimestampMixin, Base):
    """A schedule board: everything valid over one date range."""

    __tablename__ = "schedule_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    start_date: Mapped[dt.date] = mapped_column(Date)
    end_date: Mapped[dt.date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default=VersionStatus.DRAFT.value)

    calendars: Mapped[list[Calendar]] = relationship(
        back_populates="schedule_version", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="version_dates_ordered"),
    )


class Calendar(TimestampMixin, Base):
    """A service pattern (weekday / Saturday / school holidays / ...)."""

    __tablename__ = "calendars"

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_version_id: Mapped[int] = mapped_column(
        ForeignKey("schedule_versions.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    monday: Mapped[bool] = mapped_column(Boolean, default=False)
    tuesday: Mapped[bool] = mapped_column(Boolean, default=False)
    wednesday: Mapped[bool] = mapped_column(Boolean, default=False)
    thursday: Mapped[bool] = mapped_column(Boolean, default=False)
    friday: Mapped[bool] = mapped_column(Boolean, default=False)
    saturday: Mapped[bool] = mapped_column(Boolean, default=False)
    sunday: Mapped[bool] = mapped_column(Boolean, default=False)
    start_date: Mapped[dt.date | None] = mapped_column(Date, default=None)
    end_date: Mapped[dt.date | None] = mapped_column(Date, default=None)

    schedule_version: Mapped[ScheduleVersion] = relationship(back_populates="calendars")
    exceptions: Mapped[list[CalendarException]] = relationship(
        back_populates="calendar", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("schedule_version_id", "name", name="uq_calendar_name"),
    )


class CalendarException(Base):
    """A single date added to, or removed from, a calendar."""

    __tablename__ = "calendar_exceptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    calendar_id: Mapped[int] = mapped_column(
        ForeignKey("calendars.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[dt.date] = mapped_column(Date)
    exception_type: Mapped[str] = mapped_column(String(8))
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    calendar: Mapped[Calendar] = relationship(back_populates="exceptions")

    __table_args__ = (
        UniqueConstraint("calendar_id", "date", name="uq_calendar_exception_date"),
    )


class Trip(TimestampMixin, Base):
    __tablename__ = "trips"

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_version_id: Mapped[int] = mapped_column(
        ForeignKey("schedule_versions.id", ondelete="CASCADE"), index=True
    )
    pattern_id: Mapped[int] = mapped_column(
        ForeignKey("patterns.id", ondelete="RESTRICT"), index=True
    )
    calendar_id: Mapped[int] = mapped_column(
        ForeignKey("calendars.id", ondelete="RESTRICT"), index=True
    )
    # Set when the trip has been assigned to a vehicle block (phase 8).
    block_id: Mapped[int | None] = mapped_column(
        ForeignKey("blocks.id", ondelete="SET NULL"), default=None, index=True
    )
    headsign: Mapped[str | None] = mapped_column(String(255), default=None)
    short_name: Mapped[str | None] = mapped_column(String(64), default=None)
    vehicle_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("vehicle_types.id", ondelete="SET NULL"), default=None
    )
    wheelchair_accessible: Mapped[bool | None] = mapped_column(Boolean, default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    pattern: Mapped[Pattern] = relationship()
    calendar: Mapped[Calendar] = relationship()
    # Deliberately no `block` relationship: Block lives in models.fleet, which
    # imports this module, so importing it back would be a cycle -- and a
    # string annotation would have nothing to resolve against. The serializer
    # looks the block up by id instead (session-cached, so it costs one query
    # per distinct block, not per trip).
    stop_times: Mapped[list[StopTime]] = relationship(
        back_populates="trip",
        cascade="all, delete-orphan",
        order_by="StopTime.arrival_seconds",
    )


class StopTime(Base):
    """A trip's call at one pattern stop.

    Linked to ``pattern_stops`` rather than to ``locations`` directly, so a
    trip can never drift out of sync with the pattern it belongs to. The
    stop's location and sequence come from the pattern stop.

    Times are integer seconds from the start of the service day -- see
    ``app.timeutil``.
    """

    __tablename__ = "stop_times"

    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(
        ForeignKey("trips.id", ondelete="CASCADE"), index=True
    )
    pattern_stop_id: Mapped[int] = mapped_column(
        ForeignKey("pattern_stops.id", ondelete="CASCADE"), index=True
    )
    arrival_seconds: Mapped[int] = mapped_column(Integer)
    departure_seconds: Mapped[int] = mapped_column(Integer)
    is_timepoint: Mapped[bool] = mapped_column(Boolean, default=False)
    pickup_type: Mapped[str] = mapped_column(
        String(24), default=BoardingType.REGULAR.value
    )
    drop_off_type: Mapped[str] = mapped_column(
        String(24), default=BoardingType.REGULAR.value
    )

    trip: Mapped[Trip] = relationship(back_populates="stop_times")
    pattern_stop: Mapped[PatternStop] = relationship()

    __table_args__ = (
        UniqueConstraint("trip_id", "pattern_stop_id", name="uq_stop_time_trip_stop"),
        CheckConstraint(
            "departure_seconds >= arrival_seconds", name="departure_after_arrival"
        ),
    )
