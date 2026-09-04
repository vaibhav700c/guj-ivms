"""Gujarat IVMS — FastAPI application entry point."""
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.db import Base, SessionLocal, engine, run_light_migrations
from app.eventbus import event_bus
from app.routes import (
    alerts,
    analytics,
    auth,
    cameras,
    departments,
    feeds,
    ingest,
    reports,
    sentinel as sentinel_routes,
    simulator as simulator_routes,
    system,
    users,
    vehicles,
    watchlist,
    ws,
)
from app.seed import seed
from app.simulator import simulator

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("guj-ivms")


class RateLimiter:
    """Minimal in-process fixed-window rate limiter (plan §17.1 Layer 5).

    Render's free tier runs a single instance with no shared cache, so a
    small in-memory counter per client IP is the right tool — no new
    dependency (no slowapi/redis) needed. Deliberately generous: this is a
    hackathon demo where several judges may view the dashboard from behind
    the same NAT'd IP and the frontend polls a handful of endpoints; the
    goal is to stop scripted abuse (e.g. someone hammering the public
    /vehicles/search endpoint), not to throttle normal use.
    """

    def __init__(self, limit: int = 300, window_seconds: int = 60):
        self.limit = limit
        self.window_seconds = window_seconds
        self._windows: dict[str, tuple[float, int]] = {}

    def reset(self) -> None:
        """Clear all counters — used by tests so the limiter can't leak
        state between test cases and make the suite flaky."""
        self._windows.clear()

    @staticmethod
    def client_ip(request: Request) -> str:
        # Render terminates TLS at its edge proxy and forwards the real
        # client IP via X-Forwarded-For; fall back to the raw socket peer
        # for local/dev runs where there is no proxy in front of us.
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def hit(self, request: Request) -> tuple[bool, int]:
        """Record one request; returns (allowed, retry_after_seconds)."""
        ip = self.client_ip(request)
        now = time.time()
        window_start, count = self._windows.get(ip, (now, 0))
        if now - window_start >= self.window_seconds:
            window_start, count = now, 0
        count += 1
        self._windows[ip] = (window_start, count)

        # Bound memory: occasionally sweep windows that have already expired
        # so a flood of distinct IPs can't grow this dict unboundedly.
        if len(self._windows) > 5000:
            self._windows = {
                k: v for k, v in self._windows.items()
                if now - v[0] < self.window_seconds
            }

        if count > self.limit:
            retry_after = max(1, int(self.window_seconds - (now - window_start)))
            return False, retry_after
        return True, 0


# A few hundred requests/minute/IP: generous enough for the dashboard's
# normal polling plus several concurrent judges behind one NAT, but enough
# to stop a scripted hammering of a public endpoint from taking the whole
# free-tier instance down.
rate_limiter = RateLimiter(limit=300, window_seconds=60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables + seed demo data
    Base.metadata.create_all(bind=engine)
    run_light_migrations(engine)
    if settings.SEED_ON_STARTUP:
        db = SessionLocal()
        try:
            seed(db)
        finally:
            db.close()
    await event_bus.connect_redis(settings.REDIS_URL)
    if settings.SIMULATOR_AUTO_START:
        await simulator.start()
    logger.info("%s v%s ready (env=%s)", settings.APP_NAME, settings.VERSION, settings.ENVIRONMENT)
    yield
    await simulator.stop()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    description=(
        "Gujarat Integrated Video Management & Analytics Platform — "
        "Hybrid architecture (Registry+GIS · Unified Viewing · Federation Ingest · "
        "Central Analytics/Alerts). 100% open-source stack."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Layer-5 rate limiting (plan §17.1). Only wraps HTTP requests — the
    `@app.middleware("http")` decorator never intercepts WebSocket
    connections, so /ws/alerts is unaffected. /health is exempt because
    Render's health check polls it continuously and must never be
    throttled (a throttled health check looks like a dead instance)."""
    if request.url.path == "/health":
        return await call_next(request)
    allowed, retry_after = rate_limiter.hit(request)
    if not allowed:
        return JSONResponse(
            status_code=429,
            content={
                "detail": "Too many requests — please slow down and try again shortly.",
            },
            headers={"Retry-After": str(retry_after)},
        )
    return await call_next(request)


API = settings.API_V1_PREFIX
app.include_router(auth.router, prefix=API)
app.include_router(cameras.router, prefix=API)
app.include_router(watchlist.router, prefix=API)
app.include_router(alerts.router, prefix=API)
app.include_router(analytics.router, prefix=API)
app.include_router(vehicles.router, prefix=API)
app.include_router(reports.router, prefix=API)
app.include_router(ingest.router, prefix=API)
app.include_router(sentinel_routes.router, prefix=API)
app.include_router(simulator_routes.router, prefix=API)
app.include_router(departments.router, prefix=API)
app.include_router(feeds.router, prefix=API)
app.include_router(system.router, prefix=API)
app.include_router(users.router, prefix=API)
app.include_router(ws.router)


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.VERSION}


@app.get("/", tags=["system"])
def root():
    return {
        "service": settings.APP_NAME,
        "version": settings.VERSION,
        "docs": "/docs",
        "api": settings.API_V1_PREFIX,
        "websocket": "/ws/alerts",
    }
