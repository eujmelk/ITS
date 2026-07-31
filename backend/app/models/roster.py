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

from app.models.base import Base, TimestampMixin
from app.models.fleet import Block
from app.models.locations import Location


class Driver(TimestampMixin, Base):
    __tablename__ = "drivers"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(128))
    last_name: Mapped[str] = mapped_column(String(128))
    email: Mapped[str | None] = mapped_column(String(255), default=None)
    phone: Mapped[str | None] = mapped_column(String(32), default=None)
    base_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL"), default=None
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    base_location: Mapped[Location | None] = relationship()

    @property
    def display_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class Duty(TimestampMixin, Base):
    """One driver's work on one date.

    ``driver_id`` is nullable on purpose: duties are commonly built first and
    assigned to people afterwards.
    """

    __tablename__ = "duties"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    schedule_version_id: Mapped[int] = mapped_column(
        ForeignKey("schedule_versions.id", ondelete="CASCADE"), index=True
    )
    driver_id: Mapped[int | None] = mapped_column(
        ForeignKey("drivers.id", ondelete="SET NULL"), default=None, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    driver: Mapped[Driver | None] = relationship()
    pieces: Mapped[list[DutyPiece]] = relationship(
        back_populates="duty",
        cascade="all, delete-orphan",
        order_by="DutyPiece.sequence",
    )

    __table_args__ = (
        UniqueConstraint("schedule_version_id", "date", "name", name="uq_duty_name"),
    )


class DutyPiece(Base):
    """One segment of a duty.

    A ``block_segment`` covers a contiguous range of one block's pieces
    (``from_block_piece_sequence`` .. ``to_block_piece_sequence`` inclusive),
    which is what lets a single block be split between an AM and a PM driver.
    ``break`` / ``sign_on`` / ``sign_off`` pieces carry a ``location_id``
    instead.
    """

    __tablename__ = "duty_pieces"

    id: Mapped[int] = mapped_column(primary_key=True)
    duty_id: Mapped[int] = mapped_column(
        ForeignKey("duties.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    piece_type: Mapped[str] = mapped_column(String(16))

    block_id: Mapped[int | None] = mapped_column(
        ForeignKey("blocks.id", ondelete="CASCADE"), default=None, index=True
    )
    from_block_piece_sequence: Mapped[int | None] = mapped_column(Integer, default=None)
    to_block_piece_sequence: Mapped[int | None] = mapped_column(Integer, default=None)
    location_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT"), default=None
    )
    start_seconds: Mapped[int | None] = mapped_column(Integer, default=None)
    end_seconds: Mapped[int | None] = mapped_column(Integer, default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    duty: Mapped[Duty] = relationship(back_populates="pieces")
    block: Mapped[Block | None] = relationship()
    location: Mapped[Location | None] = relationship()

    __table_args__ = (
        UniqueConstraint("duty_id", "sequence", name="uq_duty_piece_sequence"),
        CheckConstraint(
            "to_block_piece_sequence IS NULL OR from_block_piece_sequence IS NULL "
            "OR to_block_piece_sequence >= from_block_piece_sequence",
            name="duty_piece_range_ordered",
        ),
        CheckConstraint(
            "end_seconds IS NULL OR start_seconds IS NULL "
            "OR end_seconds >= start_seconds",
            name="duty_piece_times_ordered",
        ),
    )
