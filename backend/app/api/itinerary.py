"""Itinerary finder (phase 11)."""

from fastapi import APIRouter, HTTPException, status

from app.deps import DbSession, ReaderUser
from app.models import Location
from app.schemas.itinerary import ItineraryRequest, ItineraryResponse
from app.services import itinerary as itinerary_service
from app.services.crud import get_or_404

router = APIRouter(prefix="/itinerary", tags=["itinerary"])


@router.post(
    "/search",
    response_model=ItineraryResponse,
    summary="Find journeys between two locations",
)
def search(payload: ItineraryRequest, db: DbSession, _user: ReaderUser):
    """Earliest-arrival journeys on a given service date.

    Walking connections come only from stop areas and explicit transfer rows
    (§1a) -- nothing is inferred from how close two coordinates look.
    """
    if payload.from_location_id == payload.to_location_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Origin and destination are the same location.",
        )
    get_or_404(db, Location, payload.from_location_id, "Location")
    get_or_404(db, Location, payload.to_location_id, "Location")

    return ItineraryResponse(
        request=payload, itineraries=itinerary_service.search(db, payload)
    )


routers: list[APIRouter] = [router]
