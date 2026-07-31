from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field, model_validator

from app.enums import BoardingType, ExceptionType, VersionStatus
from app.schemas.common import ORMModel
from app.timeutil import OptionalTimeStr, TimeStr

# --------------------------------------------------------------------------
# Schedule versions (boards)
# --------------------------------------------------------------------------


class ScheduleVersionBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    start_date: dt.date
    end_date: dt.date
    status: VersionStatus = VersionStatus.DRAFT

    @model_validator(mode="after")
    def _dates_ordered(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        return self


class ScheduleVersionCreate(ScheduleVersionBase):
    pass


class ScheduleVersionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    status: VersionStatus | None = None


class ScheduleVersionRead(ScheduleVersionBase, ORMModel):
    id: int
    trip_count: int = 0
    block_count: int = 0


# --------------------------------------------------------------------------
# Calendars
# --------------------------------------------------------------------------


class CalendarBase(BaseModel):
    schedule_version_id: int
    name: str = Field(min_length=1, max_length=255)
    monday: bool = False
    tuesday: bool = False
    wednesday: bool = False
    thursday: bool = False
    friday: bool = False
    saturday: bool = False
    sunday: bool = False
    start_date: dt.date | None = None
    end_date: dt.date | None = None


class CalendarCreate(CalendarBase):
    pass


class CalendarUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    monday: bool | None = None
    tuesday: bool | None = None
    wednesday: bool | None = None
    thursday: bool | None = None
    friday: bool | None = None
    saturday: bool | None = None
    sunday: bool | None = None
    start_date: dt.date | None = None
    end_date: dt.date | None = None


class CalendarRead(CalendarBase, ORMModel):
    id: int


class CalendarExceptionBase(BaseModel):
    calendar_id: int
    date: dt.date
    exception_type: ExceptionType
    notes: str | None = None


class CalendarExceptionCreate(CalendarExceptionBase):
    pass


class CalendarExceptionUpdate(BaseModel):
    date: dt.date | None = None
    exception_type: ExceptionType | None = None
    notes: str | None = None


class CalendarExceptionRead(CalendarExceptionBase, ORMModel):
    id: int


# --------------------------------------------------------------------------
# Trips and stop times
# --------------------------------------------------------------------------


class StopTimeBase(BaseModel):
    pattern_stop_id: int
    arrival_seconds: TimeStr
    departure_seconds: TimeStr
    is_timepoint: bool = False
    pickup_type: BoardingType = BoardingType.REGULAR
    drop_off_type: BoardingType = BoardingType.REGULAR


class StopTimeRead(StopTimeBase, ORMModel):
    id: int
    trip_id: int
    sequence: int = 0
    location_id: int | None = None
    location_name: str | None = None


class TripBase(BaseModel):
    schedule_version_id: int
    pattern_id: int
    calendar_id: int
    headsign: str | None = Field(default=None, max_length=255)
    short_name: str | None = Field(default=None, max_length=64)
    block_id: int | None = None
    vehicle_type_id: int | None = None
    wheelchair_accessible: bool | None = None
    notes: str | None = None


class TripCreate(TripBase):
    """Create a trip.

    Supply either an explicit ``stop_times`` list, or a ``start_time`` -- in
    which case the times are generated from the pattern's default run and
    dwell seconds and can be adjusted afterwards.
    """

    start_time: OptionalTimeStr = None
    stop_times: list[StopTimeBase] | None = None

    @model_validator(mode="after")
    def _one_source_of_times(self):
        if self.start_time is None and not self.stop_times:
            raise ValueError("provide either start_time or stop_times")
        return self


class TripUpdate(BaseModel):
    pattern_id: int | None = None
    calendar_id: int | None = None
    headsign: str | None = Field(default=None, max_length=255)
    short_name: str | None = Field(default=None, max_length=64)
    block_id: int | None = None
    vehicle_type_id: int | None = None
    wheelchair_accessible: bool | None = None
    notes: str | None = None
    stop_times: list[StopTimeBase] | None = None
    # Move the whole trip by this many seconds, keeping the shape intact.
    shift_seconds: int | None = None


class TripRead(TripBase, ORMModel):
    id: int
    line_id: int | None = None
    line_short_name: str | None = None
    pattern_name: str | None = None
    calendar_name: str | None = None
    block_name: str | None = None
    start_seconds: OptionalTimeStr = None
    end_seconds: OptionalTimeStr = None
    stop_count: int = 0


class TripDetail(TripRead):
    stop_times: list[StopTimeRead] = []


class TripGenerateRequest(BaseModel):
    """Generate a series of trips at a fixed headway.

    The single most common schedule-building action: "line 4 outbound, every
    12 minutes from 06:00 to 09:00, weekdays".
    """

    schedule_version_id: int
    pattern_id: int
    calendar_id: int
    first_departure: TimeStr
    last_departure: TimeStr
    headway_minutes: int = Field(ge=1, le=720)
    headsign: str | None = None
    vehicle_type_id: int | None = None

    @model_validator(mode="after")
    def _window_ordered(self):
        if self.last_departure < self.first_departure:
            raise ValueError("last_departure must not be before first_departure")
        return self


class TripGenerateResult(BaseModel):
    created_trip_ids: list[int]
    count: int


# --------------------------------------------------------------------------
# Timetable view (used by the schedule grid and the PDF renderer)
# --------------------------------------------------------------------------


class TimetableCell(BaseModel):
    trip_id: int
    departure_seconds: OptionalTimeStr = None


class TimetableRow(BaseModel):
    pattern_stop_id: int
    sequence: int
    location_id: int
    location_name: str
    is_timepoint: bool
    cells: list[TimetableCell]


class Timetable(BaseModel):
    """A pattern's trips as a stops-down / trips-across grid."""

    schedule_version_id: int
    schedule_version_name: str
    line_id: int
    line_short_name: str
    line_long_name: str | None = None
    pattern_id: int
    pattern_name: str
    direction: int
    calendar_id: int | None = None
    calendar_name: str | None = None
    #: The trips on this page, left to right in departure order.
    trip_ids: list[int]
    rows: list[TimetableRow]
    #: Trips matching the filter in total, so the client can page rather than
    #: quietly show a slice as if it were everything.
    total_trips: int = 0
    limit: int | None = None
    offset: int = 0
