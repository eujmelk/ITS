from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from app.enums import BlockPieceType, NON_TRIP_PIECE_TYPES
from app.schemas.common import ORMModel
from app.timeutil import OptionalTimeStr


class VehicleTypeBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    code: str | None = Field(default=None, max_length=32)
    capacity_seated: int | None = Field(default=None, ge=0)
    capacity_standing: int | None = Field(default=None, ge=0)
    fuel_type: str | None = Field(default=None, max_length=32)
    length_m: float | None = Field(default=None, ge=0)
    wheelchair_accessible: bool = True
    notes: str | None = None


class VehicleTypeCreate(VehicleTypeBase):
    pass


class VehicleTypeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    code: str | None = Field(default=None, max_length=32)
    capacity_seated: int | None = Field(default=None, ge=0)
    capacity_standing: int | None = Field(default=None, ge=0)
    fuel_type: str | None = Field(default=None, max_length=32)
    length_m: float | None = Field(default=None, ge=0)
    wheelchair_accessible: bool | None = None
    notes: str | None = None


class VehicleTypeRead(VehicleTypeBase, ORMModel):
    id: int


class VehicleBase(BaseModel):
    fleet_number: str = Field(min_length=1, max_length=32)
    vehicle_type_id: int
    depot_location_id: int | None = None
    registration: str | None = Field(default=None, max_length=32)
    is_active: bool = True
    notes: str | None = None


class VehicleCreate(VehicleBase):
    pass


class VehicleUpdate(BaseModel):
    fleet_number: str | None = Field(default=None, min_length=1, max_length=32)
    vehicle_type_id: int | None = None
    depot_location_id: int | None = None
    registration: str | None = Field(default=None, max_length=32)
    is_active: bool | None = None
    notes: str | None = None


class VehicleRead(VehicleBase, ORMModel):
    id: int
    vehicle_type_name: str | None = None
    depot_name: str | None = None


# --------------------------------------------------------------------------
# Blocks
# --------------------------------------------------------------------------


class BlockPieceFields(BaseModel):
    sequence: int = Field(ge=0)
    piece_type: BlockPieceType
    trip_id: int | None = None
    from_location_id: int | None = None
    to_location_id: int | None = None
    start_seconds: OptionalTimeStr = None
    end_seconds: OptionalTimeStr = None
    notes: str | None = None


class BlockPieceBase(BlockPieceFields):
    """Write shape. The shape rule lives here and not on the read model: a row
    already in the database must always be serialisable, even if an older
    version of the rules let it in."""

    @model_validator(mode="after")
    def _shape_matches_type(self):
        if self.piece_type == BlockPieceType.TRIP:
            if self.trip_id is None:
                raise ValueError("a 'trip' piece requires trip_id")
        elif self.piece_type in NON_TRIP_PIECE_TYPES:
            missing = [
                name
                for name, value in (
                    ("from_location_id", self.from_location_id),
                    ("to_location_id", self.to_location_id),
                    ("start_seconds", self.start_seconds),
                    ("end_seconds", self.end_seconds),
                )
                if value is None
            ]
            if missing:
                raise ValueError(
                    f"a '{self.piece_type.value}' piece requires: {', '.join(missing)}"
                )
        return self


class BlockPieceRead(BlockPieceFields, ORMModel):
    id: int
    block_id: int
    # Resolved endpoints: for a trip piece these come from the trip's
    # stop_times, for the rest from the explicit location columns.
    effective_from_location_id: int | None = None
    effective_to_location_id: int | None = None
    effective_from_location_name: str | None = None
    effective_to_location_name: str | None = None
    effective_start_seconds: OptionalTimeStr = None
    effective_end_seconds: OptionalTimeStr = None
    trip_label: str | None = None
    line_short_name: str | None = None


class BlockBase(BaseModel):
    schedule_version_id: int
    name: str = Field(min_length=1, max_length=64)
    vehicle_id: int | None = None
    vehicle_type_id: int | None = None
    notes: str | None = None


class BlockCreate(BlockBase):
    pieces: list[BlockPieceBase] = []


class BlockUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    vehicle_id: int | None = None
    vehicle_type_id: int | None = None
    notes: str | None = None


class BlockRead(BlockBase, ORMModel):
    id: int
    vehicle_fleet_number: str | None = None
    piece_count: int = 0
    start_seconds: OptionalTimeStr = None
    end_seconds: OptionalTimeStr = None


class BlockDetail(BlockRead):
    pieces: list[BlockPieceRead] = []


class BlockPiecesReplace(BaseModel):
    """Replace a block's whole piece list; sequences renumbered 1..n."""

    pieces: list[BlockPieceBase]


class UnassignedTrip(BaseModel):
    """A trip on a board that no block has claimed yet."""

    trip_id: int
    line_short_name: str | None = None
    headsign: str | None = None
    direction: int = 0
    pattern_id: int | None = None
    from_location_id: int | None = None
    from_location_name: str | None = None
    to_location_id: int | None = None
    to_location_name: str | None = None
    start_seconds: OptionalTimeStr = None
    end_seconds: OptionalTimeStr = None
