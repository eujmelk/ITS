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

from app.enums import LocationType
from app.models.base import Base, TimestampMixin
# Imported for real, not under TYPE_CHECKING: SQLAlchemy evaluates the
# annotation on `zone` at mapper-configuration time against this module's
# globals. models.fares imports nothing from here, so there is no cycle.
from app.models.fares import FareZone


class StopArea(TimestampMixin, Base):
    """A named grouping of locations that are effectively 'the same place'.

    Mirrors GTFS ``parent_station``. Membership is flagged once per location,
    so any two stops sharing an area are mutually transferable at
    ``default_transfer_seconds`` without wiring up pairwise rows.
    """

    __tablename__ = "stop_areas"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    default_transfer_seconds: Mapped[int] = mapped_column(Integer, default=120)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    locations: Mapped[list[Location]] = relationship(back_populates="area")

    __table_args__ = (
        CheckConstraint(
            "default_transfer_seconds >= 0", name="default_transfer_seconds_non_negative"
        ),
    )


class Location(TimestampMixin, Base):
    """Stops, depots, layover points, garages -- one table, one type flag."""

    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    code: Mapped[str | None] = mapped_column(String(32), unique=True, default=None)
    location_type: Mapped[str] = mapped_column(
        String(16), default=LocationType.STOP.value, index=True
    )
    lat: Mapped[float | None] = mapped_column(Float, default=None)
    lon: Mapped[float | None] = mapped_column(Float, default=None)

    # Depots/layovers usually have no fare zone, but it is allowed in case a
    # revenue trip ever starts there.
    zone_id: Mapped[int | None] = mapped_column(
        ForeignKey("fare_zones.id", ondelete="SET NULL"), default=None, index=True
    )
    area_id: Mapped[int | None] = mapped_column(
        ForeignKey("stop_areas.id", ondelete="SET NULL"), default=None, index=True
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    area: Mapped[StopArea | None] = relationship(back_populates="locations")
    zone: Mapped[FareZone | None] = relationship()
    attributes: Mapped[list[LocationAttribute]] = relationship(
        back_populates="location", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("lat IS NULL OR (lat >= -90 AND lat <= 90)", name="lat_range"),
        CheckConstraint("lon IS NULL OR (lon >= -180 AND lon <= 180)", name="lon_range"),
    )


class LocationAttribute(Base):
    """Generic key/value, so new attributes never need a schema change."""

    __tablename__ = "location_attributes"

    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int] = mapped_column(
        ForeignKey("locations.id", ondelete="CASCADE"), index=True
    )
    attribute_key: Mapped[str] = mapped_column(String(64))
    attribute_value: Mapped[str | None] = mapped_column(String(512), default=None)

    location: Mapped[Location] = relationship(back_populates="attributes")

    __table_args__ = (
        UniqueConstraint("location_id", "attribute_key", name="uq_location_attribute"),
    )


class LocationTransfer(TimestampMixin, Base):
    """Explicit pairwise walking connection between two locations.

    For anything that is not really 'the same place' but is still a
    reasonable walk -- a bus stop and a rail platform 300 m apart, say.
    Coordinate proximity is never used to infer a transfer.
    """

    __tablename__ = "location_transfers"

    id: Mapped[int] = mapped_column(primary_key=True)
    from_location_id: Mapped[int] = mapped_column(
        ForeignKey("locations.id", ondelete="CASCADE"), index=True
    )
    to_location_id: Mapped[int] = mapped_column(
        ForeignKey("locations.id", ondelete="CASCADE"), index=True
    )
    walk_seconds: Mapped[int] = mapped_column(Integer, default=180)
    distance_m: Mapped[int | None] = mapped_column(Integer, default=None)
    is_bidirectional: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    from_location: Mapped[Location] = relationship(foreign_keys=[from_location_id])
    to_location: Mapped[Location] = relationship(foreign_keys=[to_location_id])

    __table_args__ = (
        UniqueConstraint("from_location_id", "to_location_id", name="uq_transfer_pair"),
        CheckConstraint("from_location_id <> to_location_id", name="transfer_not_self"),
        CheckConstraint("walk_seconds >= 0", name="walk_seconds_non_negative"),
    )
