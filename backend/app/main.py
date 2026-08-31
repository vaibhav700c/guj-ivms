"""Gujarat IVMS — FastAPI application entry point."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import Base, SessionLocal, engine
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables + seed demo data
    Base.metadata.create_all(bind=engine)
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

API = settings.API_V1_PREFIX
app.include_router(auth.router, prefix=API)
app.include_router(cameras.router, prefix=API)
app.include_router(watchlist.router, prefix=API)
app.include_router(alerts.router, prefix=API)
app.include_router(analytics.router, prefix=API)
app.include_router(vehicles.router, prefix=API)
app.include_router(reports.router, prefix=API)
app.include_router(ingest.router, prefix=API)
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
