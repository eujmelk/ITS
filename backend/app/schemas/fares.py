from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class FareZoneBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    code: str | None = Field(default=None, max_length=32)
    description: str | None = None


class FareZoneCreate(FareZoneBase):
    pass


class FareZoneUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    code: str | None = Field(default=None, max_length=32)
    description: str | None = None


class FareZoneRead(FareZoneBase, ORMModel):
    id: int
    location_count: int = 0


class FareRuleBase(BaseModel):
    origin_zone_id: int
    destination_zone_id: int
    price_cents: int = Field(default=0, ge=0)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    description: str | None = None


class FareRuleCreate(FareRuleBase):
    pass


class FareRuleUpdate(BaseModel):
    price_cents: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    description: str | None = None


class FareRuleRead(FareRuleBase, ORMModel):
    id: int
    origin_zone_name: str | None = None
    destination_zone_name: str | None = None


class FareMatrixCell(BaseModel):
    origin_zone_id: int
    destination_zone_id: int
    rule_id: int | None = None
    price_cents: int | None = None
    currency: str | None = None


class FareMatrix(BaseModel):
    """The zone x zone grid, including empty cells needing a price."""

    zone_ids: list[int]
    zone_names: list[str]
    cells: list[FareMatrixCell]
    missing_count: int = 0


class FareQuote(BaseModel):
    origin_zone_id: int | None = None
    destination_zone_id: int | None = None
    price_cents: int | None = None
    currency: str | None = None
    rule_id: int | None = None
    matched: bool = False
    reason: str | None = None
