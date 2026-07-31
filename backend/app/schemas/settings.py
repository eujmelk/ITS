from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ParameterBase(BaseModel):
    value: str = Field(max_length=255)
    value_type: str = Field(default="int", pattern=r"^(int|string|bool|float)$")
    description: str | None = None
    unit: str | None = Field(default=None, max_length=32)


class ParameterCreate(ParameterBase):
    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")


class ParameterUpdate(BaseModel):
    value: str | None = Field(default=None, max_length=255)
    value_type: str | None = Field(default=None, pattern=r"^(int|string|bool|float)$")
    description: str | None = None
    unit: str | None = Field(default=None, max_length=32)


class ParameterRead(ParameterBase, ORMModel):
    key: str
