from fastapi import APIRouter

from app.api import (
    auth,
    exports,
    fares,
    fleet,
    itinerary,
    lines,
    locations,
    roster,
    schedule,
    settings as settings_api,
)
from app.config import settings
from app.schemas.common import AppConfig

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(auth.users_router)

for module in (
    locations,
    lines,
    schedule,
    fares,
    fleet,
    settings_api,
    roster,
    itinerary,
    exports,
):
    for sub in module.routers:
        api_router.include_router(sub)


@api_router.get("/health", tags=["system"], summary="Liveness probe")
def health() -> dict:
    return {"status": "ok"}


@api_router.get(
    "/config",
    tags=["system"],
    response_model=AppConfig,
    summary="Public runtime configuration",
)
def app_config() -> AppConfig:
    """Read before login, so the map works on an air-gapped host too."""
    return AppConfig(
        app_name=settings.app_name,
        map_tile_url=settings.map_tile_url,
        map_attribution=settings.map_attribution,
        map_default_lat=settings.map_default_lat,
        map_default_lon=settings.map_default_lon,
        map_default_zoom=settings.map_default_zoom,
    )
