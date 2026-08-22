from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Transit Scheduling"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"

    #: The *control* database: users and the environment registry. On an
    #: upgraded single-database install it doubles as the first environment.
    database_url: str = "postgresql+psycopg://transit:transit@localhost:5432/transit"
    #: New environments get a database named `<prefix><key>`.
    environment_db_prefix: str = "its_"

    secret_key: str = "insecure-development-key-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 720

    # Bootstrap admin, created only when the users table is empty.
    first_admin_username: str = "admin"
    first_admin_password: str = "admin"
    first_admin_email: str = "admin@example.com"

    seed_demo_data: bool = False

    # Handed to the frontend via GET {api_prefix}/config so the map can be
    # pointed at an internal tile server on an air-gapped host.
    map_tile_url: str = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
    map_attribution: str = "&copy; OpenStreetMap contributors"
    map_default_lat: float = 52.3676
    map_default_lon: float = 4.9041
    map_default_zoom: int = 12

    # Only needed when the frontend is served from a different origin than the
    # API. The bundled nginx reverse-proxies /api, so same-origin by default.
    cors_origins: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
