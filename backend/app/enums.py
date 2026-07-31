"""Controlled vocabularies.

These are stored as plain ``VARCHAR`` rather than native PostgreSQL enum
types. Adding a value to a native enum requires a migration and an exclusive
lock; here it is a one-line code change. Validation happens in the Pydantic
layer, which also matches the doc's preference for friendly validation errors
over hard database constraints.
"""

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    PLANNER = "planner"
    VIEWER = "viewer"


class LocationType(StrEnum):
    STOP = "stop"
    DEPOT = "depot"
    LAYOVER = "layover"
    GARAGE = "garage"
    OTHER = "other"


#: Location types a vehicle can start or end a non-revenue leg at.
NON_REVENUE_TYPES = {LocationType.DEPOT, LocationType.GARAGE, LocationType.LAYOVER}


class TransportMode(StrEnum):
    BUS = "bus"
    TRAM = "tram"
    METRO = "metro"
    RAIL = "rail"
    FERRY = "ferry"
    OTHER = "other"


class VersionStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class ExceptionType(StrEnum):
    ADDED = "added"
    REMOVED = "removed"


class BlockPieceType(StrEnum):
    TRIP = "trip"
    DEADHEAD = "deadhead"
    PULL_OUT = "pull_out"
    PULL_IN = "pull_in"


#: Piece types whose endpoints are given explicitly rather than derived from
#: a trip's stop_times.
NON_TRIP_PIECE_TYPES = {
    BlockPieceType.DEADHEAD,
    BlockPieceType.PULL_OUT,
    BlockPieceType.PULL_IN,
}


class DutyPieceType(StrEnum):
    BLOCK_SEGMENT = "block_segment"
    BREAK = "break"
    SIGN_ON = "sign_on"
    SIGN_OFF = "sign_off"


class BoardingType(StrEnum):
    REGULAR = "regular"
    NONE = "none"
    PHONE_AGENCY = "phone_agency"
    COORDINATE_WITH_DRIVER = "coordinate_with_driver"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
