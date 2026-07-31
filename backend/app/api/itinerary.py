"""Itinerary finder.

Scope note: the search itself is phase 11 and is not implemented here. What
*is* implemented is the part the v3 doc actually changed -- the transfer
graph the search will walk (``app.services.transfers``), exposed at
``GET /location-transfers/graph/edges`` so the edges can be inspected today.

The search will consume exactly those edges: stop-area members at the area's
default cross time, plus explicit ``location_transfers`` rows. It will not
infer a connection from coordinate proximity.
"""

from fastapi import APIRouter, HTTPException, status

from app.deps import DbSession, ReaderUser
from app.schemas.itinerary import ItineraryRequest, ItineraryResponse

router = APIRouter(prefix="/itinerary", tags=["itinerary"])

_NOT_YET = (
    "The itinerary search is phase 11 and is not implemented in this build. "
    "The transfer graph it will use is live -- see "
    "GET /api/v1/location-transfers/graph/edges."
)


@router.post(
    "/search",
    response_model=ItineraryResponse,
    summary="Find journeys between two locations (phase 11)",
)
def search(payload: ItineraryRequest, db: DbSession, _user: ReaderUser):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, _NOT_YET)


routers: list[APIRouter] = [router]
