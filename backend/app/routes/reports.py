"""Report exports — CSV + PDF (alerts, ANPR events, camera registry).

Plan §13 /reports + §20 Week 3 "Analytics export (PDF/CSV reports)".
"""
import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.models import Alert, ANPREvent, Camera
from app.pdf import build_pdf

router = APIRouter(prefix="/reports", tags=["reports"])

# Hard ceiling on any exported row count. Render's free tier has 512MB RAM
# and no autoscaling — a caller passing `?limit=5000000` on a CSV/PDF export
# must not be able to force the whole ANPR table into memory at once.
MAX_EXPORT_LIMIT = 5000


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


def _pdf_response(filename: str, title: str, header: list[str], rows) -> Response:
    pdf = build_pdf(title, "Gujarat IVMS — automated export", header, rows)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _alert_rows(db: Session, source: str | None = None):
    # joinedload(Alert.camera) turns what was up to 5000 lazy-loaded
    # `a.camera` round-trips into a single SELECT ... JOIN cameras query.
    q = db.query(Alert).options(joinedload(Alert.camera))
    if source:
        q = q.filter(Alert.source == source)
    alerts = q.order_by(Alert.timestamp.desc()).limit(MAX_EXPORT_LIMIT).all()
    header = ["id", "type", "severity", "identifier", "camera", "status", "source", "timestamp"]
    rows = [
        [a.id, a.alert_type, a.severity, a.detected_identifier,
         a.camera.name if a.camera else "", a.status, a.source,
         a.timestamp.isoformat() if a.timestamp else ""]
        for a in alerts
    ]
    return header, rows


def _anpr_rows(db: Session, limit: int = MAX_EXPORT_LIMIT, source: str | None = None):
    # Same fix as above: eager-load ANPREvent.camera instead of one query
    # per row (up to `limit` extra round-trips previously).
    q = db.query(ANPREvent).options(joinedload(ANPREvent.camera))
    if source:
        q = q.filter(ANPREvent.source == source)
    events = q.order_by(ANPREvent.timestamp.desc()).limit(limit).all()
    header = ["id", "plate", "camera", "vehicle_type", "direction", "confidence", "source", "timestamp"]
    rows = [
        [e.id, e.plate_text, e.camera.name if e.camera else e.camera_id,
         e.vehicle_type or "", e.direction or "", e.confidence, e.source,
         e.timestamp.isoformat() if e.timestamp else ""]
        for e in events
    ]
    return header, rows


def _camera_rows(db: Session):
    cams = db.query(Camera).order_by(Camera.id).all()
    header = ["id", "name", "city", "district", "lat", "lng", "type", "tier", "status"]
    rows = [
        [c.id, c.name, c.city or "", c.district or "", c.latitude, c.longitude,
         c.camera_type or "", c.analytics_tier, c.status]
        for c in cams
    ]
    return header, rows


@router.get("/alerts.csv")
def export_alerts(source: str | None = None, db: Session = Depends(get_db)):
    header, rows = _alert_rows(db, source)
    return _csv_response("alerts.csv", header, rows)


@router.get("/alerts.pdf")
def export_alerts_pdf(source: str | None = None, db: Session = Depends(get_db)):
    header, rows = _alert_rows(db, source)
    return _pdf_response("alerts.pdf", "Watchlist Alert Report", header, rows)


@router.get("/anpr.csv")
def export_anpr(
    db: Session = Depends(get_db),
    limit: int = Query(MAX_EXPORT_LIMIT, ge=1, le=MAX_EXPORT_LIMIT),
    source: str | None = None,
):
    header, rows = _anpr_rows(db, limit, source)
    return _csv_response("anpr_events.csv", header, rows)


@router.get("/anpr.pdf")
def export_anpr_pdf(
    db: Session = Depends(get_db),
    limit: int = Query(MAX_EXPORT_LIMIT, ge=1, le=MAX_EXPORT_LIMIT),
    source: str | None = None,
):
    header, rows = _anpr_rows(db, limit, source)
    return _pdf_response("anpr_events.pdf", "ANPR Detection Report", header, rows)


@router.get("/cameras.csv")
def export_cameras(db: Session = Depends(get_db)):
    header, rows = _camera_rows(db)
    return _csv_response("camera_registry.csv", header, rows)


@router.get("/cameras.pdf")
def export_cameras_pdf(db: Session = Depends(get_db)):
    header, rows = _camera_rows(db)
    return _pdf_response("camera_registry.pdf", "Camera Registry Report", header, rows)
