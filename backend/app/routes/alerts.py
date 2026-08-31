"""Alert routes — list, filter, acknowledge/resolve workflow."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Alert, Camera
from app.security import get_current_user

router = APIRouter(prefix="/alerts", tags=["alerts"])


class AlertStatusUpdate(BaseModel):
    status: str  # acknowledged | resolved | false_positive
    acknowledged_by: str | None = None


def serialize(a: Alert) -> dict:
    return {
        "id": a.id,
        "alert_type": a.alert_type,
        "severity": a.severity,
        "camera_id": a.camera_id,
        "camera_name": a.camera.name if a.camera else None,
        "camera_location": {"lat": a.camera.latitude, "lng": a.camera.longitude}
        if a.camera else None,
        "detected_identifier": a.detected_identifier,
        "match_confidence": a.match_confidence,
        "message": a.message,
        "status": a.status,
        "acknowledged_by": a.acknowledged_by,
        "snapshot_ref": a.snapshot_ref,
        "timestamp": a.timestamp.isoformat() if a.timestamp else None,
        "watchlist": {
            "id": a.watchlist.id,
            "category": a.watchlist.category,
            "fir_number": a.watchlist.fir_number,
            "police_station": a.watchlist.police_station,
        } if a.watchlist else None,
    }


@router.get("")
def list_alerts(
    status_filter: str | None = Query(None, alias="status"),
    severity: str | None = None,
    alert_type: str | None = None,
    camera_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    _: object = Depends(get_current_user),
):
    q = db.query(Alert)
    if status_filter:
        q = q.filter(Alert.status == status_filter)
    if severity:
        q = q.filter(Alert.severity == severity)
    if alert_type:
        q = q.filter(Alert.alert_type == alert_type)
    if camera_id:
        q = q.filter(Alert.camera_id == camera_id)
    total = q.count()
    items = q.order_by(Alert.timestamp.desc()).offset(offset).limit(limit).all()
    return {"total": total, "items": [serialize(a) for a in items]}


@router.get("/stats")
def alert_stats(db: Session = Depends(get_db)):
    by_status = dict(db.query(Alert.status, func.count(Alert.id)).group_by(Alert.status).all())
    by_severity = dict(db.query(Alert.severity, func.count(Alert.id)).group_by(Alert.severity).all())
    by_type = dict(db.query(Alert.alert_type, func.count(Alert.id)).group_by(Alert.alert_type).all())
    return {
        "by_status": by_status,
        "by_severity": by_severity,
        "by_type": by_type,
        "total": sum(by_status.values()),
        "unacknowledged": by_status.get("new", 0),
    }


@router.patch("/{alert_id}/status")
def update_status(alert_id: int, payload: AlertStatusUpdate, db: Session = Depends(get_db),
                  _: object = Depends(get_current_user)):
    alert = db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")
    if payload.status not in {"new", "acknowledged", "resolved", "false_positive"}:
        raise HTTPException(422, "Invalid status")
    alert.status = payload.status
    now = datetime.now(timezone.utc)
    if payload.status == "acknowledged":
        alert.acknowledged_at = now
        alert.acknowledged_by = payload.acknowledged_by or "control-room"
    if payload.status in {"resolved", "false_positive"}:
        alert.resolved_at = now
    db.commit()
    db.refresh(alert)
    return serialize(alert)
