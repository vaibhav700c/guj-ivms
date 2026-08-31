"""Federation ingest endpoint (Model 3) — regional/edge nodes push events here.

Adapter contract for departmental VMS / regional analytics nodes:
POST /api/v1/ingest/anpr   {camera_id, plate_text, confidence, timestamp?, ...}
POST /api/v1/ingest/detection {camera_id, event_type, confidence, ...}
Optional X-API-Key header checked against INGEST_API_KEY when set.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.alert_engine import alert_engine, normalize_plate
from app.config import settings
from app.db import get_db
from app.models import ANPREvent, Camera, DetectionEvent

router = APIRouter(prefix="/ingest", tags=["ingest"])


def check_api_key(x_api_key: str | None = Header(None)) -> None:
    import os

    expected = os.environ.get("INGEST_API_KEY", "")
    if expected and x_api_key != expected:
        raise HTTPException(401, "Invalid ingest API key")


class ANPRIngest(BaseModel):
    camera_id: int
    plate_text: str = Field(min_length=4, max_length=20)
    confidence: float = Field(ge=0, le=1, default=0.9)
    ocr_confidence: float | None = None
    vehicle_type: str | None = None
    vehicle_color: str | None = None
    direction: str | None = None
    lane: int | None = None
    snapshot_ref: str | None = None
    timestamp: datetime | None = None


class DetectionIngest(BaseModel):
    camera_id: int
    event_type: str
    track_id: str | None = None
    confidence: float = Field(ge=0, le=1, default=0.8)
    bbox: dict = {}
    metadata: dict = {}
    timestamp: datetime | None = None


@router.post("/anpr", status_code=201)
async def ingest_anpr(payload: ANPRIngest, db: Session = Depends(get_db),
                      _: None = Depends(check_api_key)):
    if not db.get(Camera, payload.camera_id):
        raise HTTPException(404, f"Unknown camera_id {payload.camera_id} — register first")
    event = ANPREvent(
        camera_id=payload.camera_id,
        plate_text=payload.plate_text,
        plate_normalized=normalize_plate(payload.plate_text),
        vehicle_type=payload.vehicle_type,
        vehicle_color=payload.vehicle_color,
        confidence=payload.confidence,
        ocr_confidence=payload.ocr_confidence,
        direction=payload.direction,
        lane=payload.lane,
        snapshot_ref=payload.snapshot_ref,
        timestamp=payload.timestamp or datetime.now(timezone.utc),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    alert = alert_engine.evaluate_anpr_event(db, event)
    return {
        "event_id": event.id,
        "alert_id": alert.id if alert else None,
        "status": "alert_created" if alert else "logged",
    }


@router.post("/detection", status_code=201)
def ingest_detection(payload: DetectionIngest, db: Session = Depends(get_db),
                     _: None = Depends(check_api_key)):
    if not db.get(Camera, payload.camera_id):
        raise HTTPException(404, f"Unknown camera_id {payload.camera_id}")
    det = DetectionEvent(
        camera_id=payload.camera_id,
        event_type=payload.event_type,
        track_id=payload.track_id,
        confidence=payload.confidence,
        bbox=payload.bbox,
        metadata_json=payload.metadata,
        timestamp=payload.timestamp or datetime.now(timezone.utc),
    )
    db.add(det)
    db.commit()
    return {"event_id": det.id, "status": "logged"}
