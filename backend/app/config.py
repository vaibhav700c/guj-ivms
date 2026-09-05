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
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000,https://guj-ivms.vercel.app,https://live.sentinelgujarat.in"

    # Demo simulator (edge/analytics node emulation). Fabricates ANPR/detection/
    # health events — every row is stamped source="simulator" (see models.py)
    # so it can never be mistaken for a genuine edge-worker detection, but the
    # honest default is still to have it OFF: real deployments (and this repo's
    # public demo) should show only what the real pipeline actually detected
    # unless someone deliberately opts into the fabricated data for a live demo.
    SIMULATOR_AUTO_START: bool = False
    # Second, explicit opt-in required to auto-start the simulator when
    # ENVIRONMENT=production — see the guard in main.py's lifespan.
    SIMULATOR_ALLOW_IN_PRODUCTION: bool = False
    SIMULATOR_INTERVAL_SECONDS: float = 2.0

    # Seed
    SEED_ON_STARTUP: bool = True

    # Sentinel Camera Grid — real stream infrastructure.
    # The grid authenticates with the registered email + access password. Both are
    # secrets: supply them via the environment (Render dashboard / backend/.env),
    # never in source.
    SENTINEL_HLS_BASE: str = "https://cctv.corp8.cloud"
    SENTINEL_RTSP_BASE: str = "rtsp://103.250.160.189:8554/stream"
    SENTINEL_WHEP_BASE: str = "http://103.250.160.189:8889/stream"
    SENTINEL_EMAIL: str = ""
    SENTINEL_PASSWORD: str = ""
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
