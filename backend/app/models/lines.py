from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.enums import BoardingType, TransportMode
from app.models.base import Base, TimestampMixin
from app.models.locations import Location


class Line(TimestampMixin, Base):
    __tablename__ = "lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    short_name: Mapped[str] = mapped_column(String(16), index=True)
    long_name: Mapped[str | None] = mapped_column(String(255), default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    mode: Mapped[str] = mapped_column(String(16), default=TransportMode.BUS.value)
    color: Mapped[str | None] = mapped_column(String(6), default=None)
    text_color: Mapped[str | None] = mapped_column(String(6), default=None)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    attributes: Mapped[list[LineAttribute]] = relationship(
        back_populates="line", cascade="all, delete-orphan"
    )
    patterns: Mapped[list[Pattern]] = relationship(
        back_populates="line", cascade="all, delete-orphan"
    )


class LineAttribute(Base):
    __tablename__ = "line_attributes"

    id: Mapped[int] = mapped_column(primary_key=True)
    line_id: Mapped[int] = mapped_column(
        ForeignKey("lines.id", ondelete="CASCADE"), index=True
    )
    attribute_key: Mapped[str] = mapped_column(String(64))
    attribute_value: Mapped[str | None] = mapped_column(String(512), default=None)

    line: Mapped[Line] = relationship(back_populates="attributes")

    __table_args__ = (
        UniqueConstraint("line_id", "attribute_key", name="uq_line_attribute"),
    )


class Pattern(TimestampMixin, Base):
    """An ordered sequence of stops a line's trips can follow."""

    __tablename__ = "patterns"

    id: Mapped[int] = mapped_column(primary_key=True)
    line_id: Mapped[int] = mapped_column(
        ForeignKey("lines.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    direction: Mapped[int] = mapped_column(Integer, default=0)
    headsign: Mapped[str | None] = mapped_column(String(255), default=None)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    line: Mapped[Line] = relationship(back_populates="patterns")
    pattern_stops: Mapped[list[PatternStop]] = relationship(
        back_populates="pattern",
        cascade="all, delete-orphan",
        order_by="PatternStop.sequence",
    )

    __table_args__ = (
        CheckConstraint("direction IN (0, 1)", name="direction_zero_or_one"),
    )


class PatternStop(Base):
    """One stop within a pattern.

    ``default_run_seconds`` / ``default_dwell_seconds`` are the running times
    used to generate a trip's ``stop_times`` from a single departure time;
    the generated values are then editable per trip.
    """

    __tablename__ = "pattern_stops"

    id: Mapped[int] = mapped_column(primary_key=True)
    pattern_id: Mapped[int] = mapped_column(
        ForeignKey("patterns.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    location_id: Mapped[int] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT"), index=True
    )
    is_timepoint: Mapped[bool] = mapped_column(Boolean, default=False)
    default_run_seconds: Mapped[int] = mapped_column(Integer, default=0)
    default_dwell_seconds: Mapped[int] = mapped_column(Integer, default=0)
    distance_from_start_m: Mapped[int | None] = mapped_column(Integer, default=None)
    pickup_type: Mapped[str] = mapped_column(
        String(24), default=BoardingType.REGULAR.value
    )
    drop_off_type: Mapped[str] = mapped_column(
        String(24), default=BoardingType.REGULAR.value
    )

    pattern: Mapped[Pattern] = relationship(back_populates="pattern_stops")
    location: Mapped[Location] = relationship()

    __table_args__ = (
        UniqueConstraint("pattern_id", "sequence", name="uq_pattern_stop_sequence"),
        CheckConstraint("default_run_seconds >= 0", name="run_seconds_non_negative"),
        CheckConstraint("default_dwell_seconds >= 0", name="dwell_seconds_non_negative"),
    )
