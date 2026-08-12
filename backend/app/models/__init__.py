"""Import every model here so Alembic and ``Base.metadata`` see all tables."""

from app.models.auth import User
from app.models.base import Base
from app.models.fares import FareRule, FareZone
from app.models.fleet import Block, BlockPiece, Vehicle, VehicleType
from app.models.lines import Line, Pattern, PatternAttribute, PatternStop
from app.models.locations import (
    Location,
    LocationAttribute,
    LocationTransfer,
    StopArea,
)
from app.models.roster import Driver, Duty, DutyPiece
from app.models.schedule import (
    Calendar,
    CalendarException,
    ScheduleVersion,
    StopTime,
    Trip,
)
from app.models.settings import Parameter

__all__ = [
    "Base",
    "Block",
    "BlockPiece",
    "Calendar",
    "CalendarException",
    "Driver",
    "Duty",
    "DutyPiece",
    "FareRule",
    "FareZone",
    "Line",
    "Location",
    "LocationAttribute",
    "LocationTransfer",
    "Parameter",
    "Pattern",
    "PatternAttribute",
    "PatternStop",
    "ScheduleVersion",
    "StopArea",
    "StopTime",
    "Trip",
    "User",
    "Vehicle",
    "VehicleType",
]
