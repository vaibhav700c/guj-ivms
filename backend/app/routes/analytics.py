"""Analytics dashboard aggregates (plan §14)."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.alert_engine import normalize_plate
from app.db import get_db
from app.models import ANPREvent, Camera, DetectionEvent, VehicleRecord, WatchlistEntry

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(hours=24)
    total = db.query(Camera).count()
    online = db.query(Camera).filter(Camera.status == "online").count()
    offline = db.query(Camera).filter(Camera.status == "offline").count()
    sentinel_total = db.query(Camera).filter(Camera.vms_vendor == "Sentinel Grid").count()
    sentinel_online = db.query(Camera).filter(
        Camera.vms_vendor == "Sentinel Grid", Camera.status == "online"
    ).count()
    return {
        "cameras_total": total,
        "cameras_online": online,
        "cameras_offline": offline,
        "cameras_maintenance": db.query(Camera).filter(Camera.status == "maintenance").count(),
        "sentinel_cameras_total": sentinel_total,
        "sentinel_cameras_online": sentinel_online,
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


@router.get("/anpr")
def anpr_events(
    camera_id: int | None = None,
    plate: str | None = None,
    vehicle_type: str | None = None,
    hours: float = 24.0,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """ANPR detections with filters (plan §13 analytics/anpr)."""
    from datetime import datetime, timedelta, timezone

    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    q = db.query(ANPREvent).filter(ANPREvent.timestamp >= since)
    if camera_id:
        q = q.filter(ANPREvent.camera_id == camera_id)
    if vehicle_type:
        q = q.filter(ANPREvent.vehicle_type == vehicle_type)
    if plate:
        q = q.filter(ANPREvent.plate_normalized.contains(normalize_plate(plate)))
    total = q.count()
    events = q.order_by(ANPREvent.timestamp.desc()).offset(offset).limit(limit).all()
    return {"total": total, "items": [_anpr_item(e) for e in events]}


def _anpr_item(e: ANPREvent) -> dict:
    return {
        "id": e.id,
        "camera_id": e.camera_id,
        "camera_name": e.camera.name if e.camera else None,
        "city": e.camera.city if e.camera else None,
        "plate_text": e.plate_text,
        "plate_normalized": e.plate_normalized,
        "vehicle_type": e.vehicle_type,
        "vehicle_color": e.vehicle_color,
        "direction": e.direction,
        "confidence": e.confidence,
        "ocr_confidence": e.ocr_confidence,
        "snapshot_ref": e.snapshot_ref,
        "timestamp": e.timestamp.isoformat(),
    }


@router.get("/anpr/search")
def anpr_search(plate: str, limit: int = 50, db: Session = Depends(get_db)):
    """Search ANPR detections by plate number (plan §13 analytics/anpr/search)."""
    norm = normalize_plate(plate)
    events = (
        db.query(ANPREvent)
        .filter(ANPREvent.plate_normalized.contains(norm))
        .order_by(ANPREvent.timestamp.desc())
        .limit(limit)
        .all()
    )
    return {"query": plate, "total": len(events), "items": [_anpr_item(e) for e in events]}


@router.get("/faces")
def face_events(limit: int = 50, db: Session = Depends(get_db)):
    """Face detection events from Tier A cameras (plan §6 / §13 analytics/faces)."""
    from app.models import DetectionEvent

    events = (
        db.query(DetectionEvent)
        .filter(DetectionEvent.event_type == "face")
        .order_by(DetectionEvent.timestamp.desc())
        .limit(limit)
        .all()
    )
    return {"total": len(events), "items": [
        {
            "id": d.id,
            "camera_id": d.camera_id,
            "camera_name": d.metadata_json.get("camera_name"),
            "face_name": d.metadata_json.get("face_name"),
            "embedding_dims": len(d.metadata_json.get("embedding_stub", [])),
            "confidence": d.confidence,
            "bbox": d.bbox,
            "timestamp": d.timestamp.isoformat(),
        }
        for d in events
    ]}


@router.get("/traffic")
def traffic_density(db: Session = Depends(get_db)):
    """Traffic density per camera (plan §13 analytics/traffic)."""
    rows = (
        db.query(Camera, func.count(ANPREvent.id).label("cnt"))
        .outerjoin(ANPREvent, ANPREvent.camera_id == Camera.id)
        .group_by(Camera.id)
        .all()
    )
    items = [
        {"camera_id": c.id, "name": c.name, "city": c.city,
         "lat": c.latitude, "lng": c.longitude, "events": cnt}
        for c, cnt in rows
    ]
    items.sort(key=lambda x: -x["events"])
    max_events = max((i["events"] for i in items), default=0) or 1
    for i in items:
        i["density"] = round(i["events"] / max_events, 3)
    return {"total": len(items), "items": items}


@router.get("/events")
def generic_events(limit: int = 100, event_type: str | None = None,
                   db: Session = Depends(get_db)):
    """Generic detection event stream (plan §13 analytics/events)."""
    from app.models import DetectionEvent

    q = db.query(DetectionEvent)
    if event_type:
        q = q.filter(DetectionEvent.event_type == event_type)
    events = q.order_by(DetectionEvent.timestamp.desc()).limit(limit).all()
    return {"total": len(events), "items": [
        {
            "id": d.id,
            "camera_id": d.camera_id,
            "event_type": d.event_type,
            "track_id": d.track_id,
            "confidence": d.confidence,
            "bbox": d.bbox,
            "timestamp": d.timestamp.isoformat(),
        }
        for d in events
    ]}
