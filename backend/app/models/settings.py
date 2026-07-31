from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Parameter(TimestampMixin, Base):
    """Global operating parameters, edited from the Settings page.

    Deliberately flat (no per-line/per-driver scoping) for now. The roster
    validator reads parameters through ``app.services.parameters.resolve()``,
    which already takes a scope argument -- adding a ``parameter_overrides``
    table later needs no change to any caller.
    """

    __tablename__ = "parameters"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))
    value_type: Mapped[str] = mapped_column(String(16), default="int")
    description: Mapped[str | None] = mapped_column(Text, default=None)
    unit: Mapped[str | None] = mapped_column(String(32), default=None)
