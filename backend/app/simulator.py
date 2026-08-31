"""Demo simulator — emulates edge/regional analytics nodes.

Generates realistic ANPR + detection events across the camera registry,
including periodic sightings of watchlisted vehicles so the alert engine,
WebSocket live feed, and journey reconstruction are all demonstrably
working end-to-end without physical cameras. In production this module is
disabled and events arrive via the ingest API instead.
"""
import asyncio
import logging
import random
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.alert_engine import alert_engine, normalize_plate
from app.config import settings
from app.db import SessionLocal
from app.models import ANPREvent, Camera, DetectionEvent, WatchlistEntry
from app.seed_data import COLORS, VEHICLE_TYPES

logger = logging.getLogger(__name__)

WATCHLIST_PLATES = [
    "GJ 01 AB 1234",
    "GJ 05 CD 5678",
    "GJ 03 EF 9012",
    "GJ 18 GH 3456",
    "GJ 01 JK 7890",
]


def random_plate() -> str:
    codes = ["01", "03", "05", "06", "10", "12", "18", "27"]
    letters = "".join(random.choices("ABCDEFGHJKLMNPRSTUVWXYZ", k=2))
    return f"GJ {random.choice(codes)} {letters} {random.randint(1000, 9999)}"


class Simulator:
    def __init__(self) -> None:
        self.running = False
        self._task: asyncio.Task | None = None
        self.stats = {"events_generated": 0, "alerts_generated": 0, "started_at": None}
        # A "tracked" vehicle that tours multiple cameras → journey demo
        self.tracked_plate = "GJ 01 AB 1234"

    async def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.stats["started_at"] = datetime.now(timezone.utc).isoformat()
        self._task = asyncio.create_task(self._loop())
        logger.info("Simulator started (interval=%ss)", settings.SIMULATOR_INTERVAL_SECONDS)

    async def stop(self) -> None:
        self.running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("Simulator stopped")

    async def _loop(self) -> None:
        while self.running:
            try:
                db: Session = SessionLocal()
                try:
                    await self._tick(db)
                finally:
                    db.close()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Simulator tick failed")
            await asyncio.sleep(settings.SIMULATOR_INTERVAL_SECONDS)

    async def _tick(self, db: Session) -> None:
        cameras = db.query(Camera).filter(Camera.status == "online").all()
        if not cameras:
            return

        # 1) ANPR event from a random camera
        camera = random.choice(cameras)
        if camera.id % 7 == 0 and random.random() < 0.6:
            plate = self.tracked_plate  # tracked vehicle sighting pattern
        elif random.random() < 0.18:
            plate = random.choice(WATCHLIST_PLATES)
        else:
            plate = random_plate()
        vtype, models = random.choice(VEHICLE_TYPES)

        event = ANPREvent(
            camera_id=camera.id,
            plate_text=plate,
            plate_normalized=normalize_plate(plate),
            vehicle_type=vtype,
            vehicle_color=random.choice(COLORS),
            confidence=round(random.uniform(0.86, 0.99), 2),
            ocr_confidence=round(random.uniform(0.78, 0.98), 2),
            direction=random.choice(["inbound", "outbound"]),
            lane=random.randint(1, 3),
            snapshot_ref=f"snapshots/{camera.id}/{normalize_plate(plate)}-{int(datetime.now().timestamp())}.jpg",
            timestamp=datetime.now(timezone.utc),
        )
        db.add(event)
        db.commit()
        db.refresh(event)
        self.stats["events_generated"] += 1

        alert = alert_engine.evaluate_anpr_event(db, event)
        if alert:
            self.stats["alerts_generated"] += 1

        # 2) Occasional generic detection event
        if random.random() < 0.5:
            det = DetectionEvent(
                camera_id=random.choice(cameras).id,
                event_type=random.choices(
                    ["person", "vehicle", "crowd"], weights=[5, 4, 1]
                )[0],
                track_id=f"trk-{random.randint(10000, 99999)}",
                confidence=round(random.uniform(0.7, 0.97), 2),
                bbox={"x": random.randint(0, 800), "y": random.randint(0, 400),
                      "w": random.randint(40, 220), "h": random.randint(60, 320)},
                timestamp=datetime.now(timezone.utc),
            )
            db.add(det)
            db.commit()

        # 3) Camera health heartbeat
        cam = camera
        cam.last_seen = datetime.now(timezone.utc)
        if cam.status == "online":
            cam.health_score = round(min(1.0, (cam.health_score or 0.9) + random.uniform(-0.02, 0.02)), 2)
        db.commit()

    def status(self) -> dict:
        return {"running": self.running, **self.stats}


simulator = Simulator()
