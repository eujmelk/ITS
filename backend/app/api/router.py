from fastapi import APIRouter

from app.api import (
    auth,
    environments,
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
from app.deps import CurrentEnvironment, DbSession
from app.schemas.common import AppConfig
from app.services.parameters import resolve_text

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(auth.users_router)

for module in (
    environments,
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
def app_config(db: DbSession, environment: CurrentEnvironment) -> AppConfig:
    """Read before login, so the map works on an air-gapped host too.

    The instance name comes from the `instance_name` parameter of the *current
    environment*, so each city names itself. It falls back to the env var only
    when that row is missing, which is the case for one request during first
    startup.
    """
    return AppConfig(
        app_name=resolve_text(db, "instance_name", settings.app_name),
        environment_key=environment.key,
        environment_name=environment.name,
        map_tile_url=settings.map_tile_url,
        map_attribution=settings.map_attribution,
        map_default_lat=settings.map_default_lat,
        map_default_lon=settings.map_default_lon,
        map_default_zoom=settings.map_default_zoom,
    )
