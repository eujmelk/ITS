from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class EnvironmentBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    notes: str | None = None


class EnvironmentCreate(EnvironmentBase):
    key: str = Field(
        min_length=2,
        max_length=48,
        description=(
            "Stable identifier, e.g. 'city1'. Becomes part of the database "
            "name and cannot be changed afterwards."
        ),
    )


class EnvironmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None
    notes: str | None = None


class EnvironmentRead(EnvironmentBase, ORMModel):
    id: int
    key: str
    database_name: str
    is_active: bool
    is_default: bool
    #: True for the environment serving the current request.
    is_current: bool = False
