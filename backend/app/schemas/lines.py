from __future__ import annotations

from pydantic import BaseModel, Field

from app.enums import BoardingType, TransportMode
from app.schemas.common import ORMModel


class LineAttributeBase(BaseModel):
    attribute_key: str = Field(min_length=1, max_length=64)
    attribute_value: str | None = Field(default=None, max_length=512)


class LineAttributeCreate(LineAttributeBase):
    line_id: int


class LineAttributeUpdate(BaseModel):
    attribute_key: str | None = Field(default=None, min_length=1, max_length=64)
    attribute_value: str | None = Field(default=None, max_length=512)


class LineAttributeRead(LineAttributeBase, ORMModel):
    id: int
    line_id: int


class LineBase(BaseModel):
    short_name: str = Field(min_length=1, max_length=16)
    long_name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    mode: TransportMode = TransportMode.BUS
    color: str | None = Field(default=None, pattern=r"^[0-9A-Fa-f]{6}$")
    text_color: str | None = Field(default=None, pattern=r"^[0-9A-Fa-f]{6}$")
    sort_order: int = 0
    is_active: bool = True


class LineCreate(LineBase):
    attributes: list[LineAttributeBase] = []


class LineUpdate(BaseModel):
    short_name: str | None = Field(default=None, min_length=1, max_length=16)
    long_name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    mode: TransportMode | None = None
    color: str | None = Field(default=None, pattern=r"^[0-9A-Fa-f]{6}$")
    text_color: str | None = Field(default=None, pattern=r"^[0-9A-Fa-f]{6}$")
    sort_order: int | None = None
    is_active: bool | None = None
    attributes: list[LineAttributeBase] | None = None


class LineRead(LineBase, ORMModel):
    id: int
    attributes: list[LineAttributeRead] = []
    pattern_count: int = 0


# --------------------------------------------------------------------------
# Patterns
# --------------------------------------------------------------------------


class PatternStopBase(BaseModel):
    location_id: int
    sequence: int = Field(ge=0)
    is_timepoint: bool = False
    default_run_seconds: int = Field(default=0, ge=0, le=86400)
    default_dwell_seconds: int = Field(default=0, ge=0, le=86400)
    distance_from_start_m: int | None = Field(default=None, ge=0)
    pickup_type: BoardingType = BoardingType.REGULAR
    drop_off_type: BoardingType = BoardingType.REGULAR


class PatternStopRead(PatternStopBase, ORMModel):
    id: int
    pattern_id: int
    location_name: str | None = None
    location_code: str | None = None
    lat: float | None = None
    lon: float | None = None


class PatternBase(BaseModel):
    line_id: int
    name: str = Field(min_length=1, max_length=255)
    direction: int = Field(default=0, ge=0, le=1)
    headsign: str | None = Field(default=None, max_length=255)
    is_primary: bool = False
    notes: str | None = None


class PatternCreate(PatternBase):
    stops: list[PatternStopBase] = []


class PatternUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    direction: int | None = Field(default=None, ge=0, le=1)
    headsign: str | None = Field(default=None, max_length=255)
    is_primary: bool | None = None
    notes: str | None = None


class PatternRead(PatternBase, ORMModel):
    id: int
    stop_count: int = 0
    total_run_seconds: int = 0


class PatternDetail(PatternRead):
    stops: list[PatternStopRead] = []


class PatternStopsReplace(BaseModel):
    """Replace a pattern's whole stop list.

    Editing stops one row at a time makes reordering awkward and leaves the
    pattern briefly invalid; the editor sends the finished list instead.
    Sequences are renumbered 1..n server-side, so the client can send them in
    display order without worrying about gaps.
    """

    stops: list[PatternStopBase]
