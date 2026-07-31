from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class FareZone(TimestampMixin, Base):
    __tablename__ = "fare_zones"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    code: Mapped[str | None] = mapped_column(String(32), unique=True, default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None)


class FareRule(TimestampMixin, Base):
    """Origin-zone x destination-zone price matrix.

    Same-zone fares (A -> A) are simply the diagonal of this matrix; they need
    no special handling.
    """

    __tablename__ = "fare_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    origin_zone_id: Mapped[int] = mapped_column(
        ForeignKey("fare_zones.id", ondelete="CASCADE"), index=True
    )
    destination_zone_id: Mapped[int] = mapped_column(
        ForeignKey("fare_zones.id", ondelete="CASCADE"), index=True
    )
    price_cents: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    description: Mapped[str | None] = mapped_column(Text, default=None)

    origin_zone: Mapped[FareZone] = relationship(foreign_keys=[origin_zone_id])
    destination_zone: Mapped[FareZone] = relationship(foreign_keys=[destination_zone_id])

    __table_args__ = (
        UniqueConstraint(
            "origin_zone_id", "destination_zone_id", name="uq_fare_rule_zone_pair"
        ),
        CheckConstraint("price_cents >= 0", name="price_non_negative"),
    )
