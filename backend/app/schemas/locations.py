from __future__ import annotations

from pydantic import BaseModel, Field

from app.enums import LocationType
from app.schemas.common import ORMModel

# --------------------------------------------------------------------------
# Stop areas
# --------------------------------------------------------------------------


class StopAreaBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    default_transfer_seconds: int = Field(default=120, ge=0, le=3600)
    notes: str | None = None


class StopAreaCreate(StopAreaBase):
    pass


class StopAreaUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    default_transfer_seconds: int | None = Field(default=None, ge=0, le=3600)
    notes: str | None = None


class StopAreaRead(StopAreaBase, ORMModel):
    id: int


class StopAreaDetail(StopAreaRead):
    location_ids: list[int] = []
    location_names: list[str] = []


class StopAreaMembership(BaseModel):
    """Replace the full membership of an area in one call.

    Membership is a property of the location (``locations.area_id``), but it
    is edited area-at-a-time in the UI, so the write goes through here.
    """

    location_ids: list[int]


# --------------------------------------------------------------------------
# Location attributes
# --------------------------------------------------------------------------


class LocationAttributeBase(BaseModel):
    attribute_key: str = Field(min_length=1, max_length=64)
    attribute_value: str | None = Field(default=None, max_length=512)


class LocationAttributeCreate(LocationAttributeBase):
    location_id: int


class LocationAttributeUpdate(BaseModel):
    attribute_key: str | None = Field(default=None, min_length=1, max_length=64)
    attribute_value: str | None = Field(default=None, max_length=512)


class LocationAttributeRead(LocationAttributeBase, ORMModel):
    id: int
    location_id: int


# --------------------------------------------------------------------------
# Locations
# --------------------------------------------------------------------------


class LocationBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    code: str | None = Field(default=None, max_length=32)
    location_type: LocationType = LocationType.STOP
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    zone_id: int | None = None
    area_id: int | None = None
    is_active: bool = True
    notes: str | None = None


class LocationCreate(LocationBase):
    attributes: list[LocationAttributeBase] = []


class LocationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    code: str | None = Field(default=None, max_length=32)
    location_type: LocationType | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    zone_id: int | None = None
    area_id: int | None = None
    is_active: bool | None = None
    notes: str | None = None
    # When present, replaces the whole attribute set for this location.
    attributes: list[LocationAttributeBase] | None = None


class LocationRead(LocationBase, ORMModel):
    id: int
    area_name: str | None = None
    zone_name: str | None = None
    attributes: list[LocationAttributeRead] = []


# --------------------------------------------------------------------------
# Transfers
# --------------------------------------------------------------------------


class LocationTransferBase(BaseModel):
    from_location_id: int
    to_location_id: int
    walk_seconds: int = Field(default=180, ge=0, le=7200)
    distance_m: int | None = Field(default=None, ge=0)
    is_bidirectional: bool = True
    notes: str | None = None


class LocationTransferCreate(LocationTransferBase):
    pass


class LocationTransferUpdate(BaseModel):
    from_location_id: int | None = None
    to_location_id: int | None = None
    walk_seconds: int | None = Field(default=None, ge=0, le=7200)
    distance_m: int | None = Field(default=None, ge=0)
    is_bidirectional: bool | None = None
    notes: str | None = None


class LocationTransferRead(LocationTransferBase, ORMModel):
    id: int
    from_location_name: str | None = None
    to_location_name: str | None = None


class ImportRowResult(BaseModel):
    line: int
    action: str = Field(description="created | updated | skipped | failed")
    name: str = ""
    code: str = ""
    location_id: int | None = None
    message: str = ""


class ImportReport(BaseModel):
    """What an import did, or would do.

    A dry run reports exactly this and keeps none of it, so the operator sees
    the outcome before anything is written.
    """

    dry_run: bool
    ok: bool
    delimiter: str
    columns: list[str] = []
    #: Header columns not recognised as fields; these became attributes.
    attribute_columns: list[str] = []
    total: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    rows: list[ImportRowResult] = []
    fatal: str | None = None


class TransferEdge(BaseModel):
    """One walking edge as the itinerary finder sees it.

    Carries the endpoint names so a client can render the graph without
    holding the whole locations table in memory to look ids up.
    """

    from_location_id: int
    to_location_id: int
    from_location_name: str | None = None
    to_location_name: str | None = None
    walk_seconds: int
    source: str = Field(description="'stop_area' or 'explicit'")
