"""Analytics dashboard aggregates (plan §14)."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ANPREvent, Camera, DetectionEvent, VehicleRecord, WatchlistEntry

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(hours=24)
    return {
        "cameras_total": db.query(Camera).count(),
        "cameras_online": db.query(Camera).filter(Camera.status == "online").count(),
        "cameras_offline": db.query(Camera).filter(Camera.status == "offline").count(),
        "anpr_events_24h": db.query(ANPREvent).filter(ANPREvent.timestamp >= day_ago).count(),
        "anpr_events_total": db.query(ANPREvent).count(),
        "detections_24h": db.query(DetectionEvent).filter(DetectionEvent.timestamp >= day_ago).count(),
        "watchlist_active": db.query(WatchlistEntry).filter(WatchlistEntry.active.is_(True)).count(),
        "registry_vehicles": db.query(VehicleRecord).count(),
        "server_time": now.isoformat(),
    }


@router.get("/events/timeline")
def events_timeline(hours: int = 24, db: Session = Depends(get_db)):
    """ANPR event counts bucketed by hour for the last N hours."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    if db.bind.dialect.name == "sqlite":
        rows = db.query(
            func.strftime("%Y-%m-%dT%H:00:00", ANPREvent.timestamp).label("bucket"),
            func.count(ANPREvent.id),
        ).filter(ANPREvent.timestamp >= since).group_by("bucket").all()
    else:
        rows = db.query(
            func.to_char(func.date_trunc("hour", ANPREvent.timestamp), "YYYY-MM-DD\"T\"HH24:00:00").label("bucket"),
            func.count(ANPREvent.id),
        ).filter(ANPREvent.timestamp >= since).group_by("bucket").all()
    return [{"bucket": b, "count": c} for b, c in sorted(rows or []) if b]


@router.get("/detections/by-type")
def detections_by_type(db: Session = Depends(get_db)):
    rows = db.query(DetectionEvent.event_type, func.count(DetectionEvent.id)).group_by(
        DetectionEvent.event_type
    ).all()
    return [{"event_type": t, "count": c} for t, c in rows]


@router.get("/tiers/coverage")
def tier_coverage(db: Session = Depends(get_db)):
    """Camera analytics tier distribution (plan §4)."""
    rows = db.query(Camera.analytics_tier, func.count(Camera.id)).group_by(
        Camera.analytics_tier
    ).all()
    descriptions = {
        "A": "Full ANPR + Face + Detection (5-10 FPS)",
        "B": "Detection + Tracking (2-5 FPS)",
        "C": "Presence/health monitoring (1 FPS)",
    }
    return [
        {"tier": t, "count": c, "description": descriptions.get(t, "")} for t, c in rows
    ]
