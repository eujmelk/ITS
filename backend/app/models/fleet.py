from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.locations import Location
from app.models.schedule import Trip


class VehicleType(TimestampMixin, Base):
    __tablename__ = "vehicle_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    code: Mapped[str | None] = mapped_column(String(32), unique=True, default=None)
    capacity_seated: Mapped[int | None] = mapped_column(Integer, default=None)
    capacity_standing: Mapped[int | None] = mapped_column(Integer, default=None)
    fuel_type: Mapped[str | None] = mapped_column(String(32), default=None)
    length_m: Mapped[float | None] = mapped_column(Float, default=None)
    wheelchair_accessible: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text, default=None)


class Vehicle(TimestampMixin, Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(primary_key=True)
    fleet_number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    vehicle_type_id: Mapped[int] = mapped_column(
        ForeignKey("vehicle_types.id", ondelete="RESTRICT"), index=True
    )
    depot_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL"), default=None
    )
    registration: Mapped[str | None] = mapped_column(String(32), default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    vehicle_type: Mapped[VehicleType] = relationship()
    depot: Mapped[Location | None] = relationship()


class Block(TimestampMixin, Base):
    """A vehicle's whole working day, as an ordered list of pieces."""

    __tablename__ = "blocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_version_id: Mapped[int] = mapped_column(
        ForeignKey("schedule_versions.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    vehicle_id: Mapped[int | None] = mapped_column(
        ForeignKey("vehicles.id", ondelete="SET NULL"), default=None
    )
    vehicle_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("vehicle_types.id", ondelete="SET NULL"), default=None
    )
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    pieces: Mapped[list[BlockPiece]] = relationship(
        back_populates="block",
        cascade="all, delete-orphan",
        order_by="BlockPiece.sequence",
    )
    vehicle: Mapped[Vehicle | None] = relationship()

    __table_args__ = (
        UniqueConstraint("schedule_version_id", "name", name="uq_block_name"),
    )


class BlockPiece(Base):
    """One leg of a block: a revenue trip, or a non-revenue movement.

    For ``piece_type = 'trip'`` the effective start/end location and time come
    from the trip's own ``stop_times`` and are *not* duplicated here -- the
    columns stay NULL. For deadhead / pull_out / pull_in the endpoints and
    times are given explicitly, and may reference any location type.
    """

    __tablename__ = "block_pieces"

    id: Mapped[int] = mapped_column(primary_key=True)
    block_id: Mapped[int] = mapped_column(
        ForeignKey("blocks.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    piece_type: Mapped[str] = mapped_column(String(16))

    trip_id: Mapped[int | None] = mapped_column(
        ForeignKey("trips.id", ondelete="CASCADE"), default=None, index=True
    )
    from_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT"), default=None
    )
    to_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT"), default=None
    )
    start_seconds: Mapped[int | None] = mapped_column(Integer, default=None)
    end_seconds: Mapped[int | None] = mapped_column(Integer, default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    block: Mapped[Block] = relationship(back_populates="pieces")
    trip: Mapped[Trip | None] = relationship()
    from_location: Mapped[Location | None] = relationship(
        foreign_keys=[from_location_id]
    )
    to_location: Mapped[Location | None] = relationship(foreign_keys=[to_location_id])

    __table_args__ = (
        UniqueConstraint("block_id", "sequence", name="uq_block_piece_sequence"),
        CheckConstraint(
            "end_seconds IS NULL OR start_seconds IS NULL "
            "OR end_seconds >= start_seconds",
            name="piece_times_ordered",
        ),
    )
