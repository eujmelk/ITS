from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field, model_validator

from app.enums import DutyPieceType
from app.schemas.common import ORMModel, ValidationReport
from app.timeutil import OptionalTimeStr


class DriverBase(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    first_name: str = Field(min_length=1, max_length=128)
    last_name: str = Field(min_length=1, max_length=128)
    email: str | None = None
    phone: str | None = Field(default=None, max_length=32)
    base_location_id: int | None = None
    is_active: bool = True
    notes: str | None = None


class DriverCreate(DriverBase):
    pass


class DriverUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=32)
    first_name: str | None = Field(default=None, min_length=1, max_length=128)
    last_name: str | None = Field(default=None, min_length=1, max_length=128)
    email: str | None = None
    phone: str | None = Field(default=None, max_length=32)
    base_location_id: int | None = None
    is_active: bool | None = None
    notes: str | None = None


class DriverRead(DriverBase, ORMModel):
    id: int
    display_name: str = ""
    base_location_name: str | None = None


# --------------------------------------------------------------------------
# Duties
# --------------------------------------------------------------------------


class DutyPieceFields(BaseModel):
    sequence: int = Field(ge=0)
    piece_type: DutyPieceType
    block_id: int | None = None
    from_block_piece_sequence: int | None = None
    to_block_piece_sequence: int | None = None
    location_id: int | None = None
    start_seconds: OptionalTimeStr = None
    end_seconds: OptionalTimeStr = None
    notes: str | None = None


class DutyPieceBase(DutyPieceFields):
    """Write shape; the read model deliberately omits this rule so a stored
    row can always be serialised."""

    @model_validator(mode="after")
    def _shape_matches_type(self):
        if self.piece_type == DutyPieceType.BLOCK_SEGMENT:
            if self.block_id is None:
                raise ValueError("a 'block_segment' piece requires block_id")
        else:
            if self.start_seconds is None or self.end_seconds is None:
                raise ValueError(
                    f"a '{self.piece_type.value}' piece requires start and end times"
                )
        return self


class DutyPieceRead(DutyPieceFields, ORMModel):
    id: int
    duty_id: int
    block_name: str | None = None
    location_name: str | None = None
    effective_start_seconds: OptionalTimeStr = None
    effective_end_seconds: OptionalTimeStr = None
    covers_piece_count: int = 0


class DutyBase(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    date: dt.date
    schedule_version_id: int
    driver_id: int | None = None
    notes: str | None = None


class DutyCreate(DutyBase):
    pieces: list[DutyPieceBase] = []


class DutyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    date: dt.date | None = None
    driver_id: int | None = None
    notes: str | None = None


class DutyRead(DutyBase, ORMModel):
    id: int
    driver_name: str | None = None
    piece_count: int = 0
    start_seconds: OptionalTimeStr = None
    end_seconds: OptionalTimeStr = None
    working_minutes: int = 0
    driving_minutes: int = 0
    break_minutes: int = 0


class DutyDetail(DutyRead):
    pieces: list[DutyPieceRead] = []
    validation: ValidationReport | None = None


class DutyPiecesReplace(BaseModel):
    pieces: list[DutyPieceBase]


class BlockCoverage(BaseModel):
    """How much of a block is already covered by duties on a given date."""

    block_id: int
    block_name: str
    total_pieces: int
    covered_sequences: list[int] = []
    uncovered_sequences: list[int] = []
    fully_covered: bool = False
