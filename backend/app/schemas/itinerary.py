from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field

from app.timeutil import OptionalTimeStr, TimeStr


class ItineraryRequest(BaseModel):
    from_location_id: int
    to_location_id: int
    date: dt.date
    depart_after: TimeStr | None = None
    arrive_before: TimeStr | None = None
    max_transfers: int = Field(default=3, ge=0, le=6)
    max_results: int = Field(default=5, ge=1, le=20)
    min_transfer_seconds: int = Field(default=0, ge=0)


class ItineraryLeg(BaseModel):
    kind: str = Field(description="'ride' or 'walk'")
    from_location_id: int
    from_location_name: str
    to_location_id: int
    to_location_name: str
    depart_seconds: OptionalTimeStr = None
    arrive_seconds: OptionalTimeStr = None
    duration_seconds: int = 0
    # Ride legs only
    trip_id: int | None = None
    line_id: int | None = None
    line_short_name: str | None = None
    headsign: str | None = None
    intermediate_stop_count: int = 0
    # Walk legs only
    transfer_source: str | None = None


class Itinerary(BaseModel):
    depart_seconds: OptionalTimeStr = None
    arrive_seconds: OptionalTimeStr = None
    duration_seconds: int = 0
    transfer_count: int = 0
    legs: list[ItineraryLeg] = []
    fare_price_cents: int | None = None
    fare_currency: str | None = None


class ItineraryResponse(BaseModel):
    request: ItineraryRequest
    itineraries: list[Itinerary] = []
