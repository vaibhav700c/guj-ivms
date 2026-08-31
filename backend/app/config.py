"""Application configuration via environment variables."""
from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Gujarat IVMS API"
    VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"  # development | production
    API_V1_PREFIX: str = "/api/v1"

    # Database — falls back to SQLite for zero-config local dev
    DATABASE_URL: str = "sqlite:///./guj_ivms.db"

    # Redis (optional — in-process bus used when absent)
    REDIS_URL: str = ""

    # Auth
    SECRET_KEY: str = "change-me-in-production-guj-ivms-secret"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 12
    ALGORITHM: str = "HS256"
    REQUIRE_AUTH: bool = False  # set true in production to enforce JWT on APIs

    # CORS
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    # Demo simulator (edge/analytics node emulation)
    SIMULATOR_AUTO_START: bool = True
    SIMULATOR_INTERVAL_SECONDS: float = 2.0

    # Seed
    SEED_ON_STARTUP: bool = True

    # Sentinel Camera Grid — real stream infrastructure
    SENTINEL_HLS_BASE: str = "https://cctv.corp8.cloud"
    SENTINEL_RTSP_BASE: str = "rtsp://103.250.160.189:8554/stream"
    SENTINEL_WHEP_BASE: str = "http://103.250.160.189:8889/stream"
    SENTINEL_PASSWORD: str = ""  # set in Render dashboard (E6W6-8SAJ-3S9Z)
    # Ingest federation
    INGEST_API_KEY: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = True

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
