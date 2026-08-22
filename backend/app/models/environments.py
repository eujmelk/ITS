from __future__ import annotations

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Environment(TimestampMixin, Base):
    """One city or operation, with its own database.

    Only ever read from the *control* database — the copy of this table that
    exists in each environment database is unused. See ``app.db`` for why the
    schema is not split.
    """

    __tablename__ = "environments"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: Stable identifier used in the X-Environment header and the database
    #: name. Lowercase, no spaces, never reused.
    key: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    #: The PostgreSQL database holding this environment's planning data.
    database_name: Mapped[str] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    #: The one environment used when a request names none.
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
