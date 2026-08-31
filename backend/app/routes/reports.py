"""Report exports — CSV (alerts, ANPR events, journey, camera registry)."""
import csv
import io

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Alert, ANPREvent, Camera

router = APIRouter(prefix="/reports", tags=["reports"])


def _csv_response(filename: str, header: list[str], rows) -> Response:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/alerts.csv")
def export_alerts(db: Session = Depends(get_db)):
    alerts = db.query(Alert).order_by(Alert.timestamp.desc()).limit(5000).all()
    rows = [
        [a.id, a.alert_type, a.severity, a.detected_identifier,
         a.camera.name if a.camera else "", a.status,
         a.timestamp.isoformat() if a.timestamp else ""]
        for a in alerts
    ]
    return _csv_response("alerts.csv",
                         ["id", "type", "severity", "identifier", "camera", "status", "timestamp"],
                         rows)


@router.get("/anpr.csv")
def export_anpr(db: Session = Depends(get_db), limit: int = 5000):
    events = db.query(ANPREvent).order_by(ANPREvent.timestamp.desc()).limit(limit).all()
    rows = [
        [e.id, e.plate_text, e.camera.name if e.camera else e.camera_id,
         e.vehicle_type or "", e.direction or "", e.confidence,
         e.timestamp.isoformat() if e.timestamp else ""]
        for e in events
    ]
    return _csv_response("anpr_events.csv",
                         ["id", "plate", "camera", "vehicle_type", "direction", "confidence", "timestamp"],
                         rows)


@router.get("/cameras.csv")
def export_cameras(db: Session = Depends(get_db)):
    cams = db.query(Camera).order_by(Camera.id).all()
    rows = [
        [c.id, c.name, c.city or "", c.district or "", c.latitude, c.longitude,
         c.camera_type or "", c.analytics_tier, c.status]
        for c in cams
    ]
    return _csv_response("camera_registry.csv",
                         ["id", "name", "city", "district", "lat", "lng", "type", "tier", "status"],
                         rows)
