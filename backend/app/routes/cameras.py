"""Camera registry routes — Model 1 foundation (CRUD + GIS + health)."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Camera, Department
from app.security import get_current_user

router = APIRouter(prefix="/cameras", tags=["cameras"])


class CameraCreate(BaseModel):
    name: str
    latitude: float
    longitude: float
    city: str | None = None
    district: str | None = None
    address: str | None = None
    camera_type: str | None = None
    stream_url: str | None = None
    stream_protocol: str | None = None
    resolution: str | None = None
    fps: int | None = None
    analytics_tier: str = "C"
    department_id: int | None = None


class CameraUpdate(BaseModel):
    name: str | None = None
    status: str | None = None
    stream_url: str | None = None
    analytics_tier: str | None = None
    latitude: float | None = None
    longitude: float | None = None


def serialize(c: Camera) -> dict:
    return {
        "id": c.id,
        "external_id": c.external_id,
        "name": c.name,
        "latitude": c.latitude,
        "longitude": c.longitude,
        "address": c.address,
        "city": c.city,
        "district": c.district,
        "camera_type": c.camera_type,
        "resolution": c.resolution,
        "fps": c.fps,
        "stream_url": c.stream_url,
        "stream_protocol": c.stream_protocol,
        "vms_vendor": c.vms_vendor,
        "status": c.status,
        "health_score": c.health_score,
        "last_seen": c.last_seen.isoformat() if c.last_seen else None,
        "analytics_tier": c.analytics_tier,
        "department_id": c.department_id,
        "has_ir": c.has_ir,
        "has_ptz": c.has_ptz,
    }


@router.get("")
def list_cameras(
    city: str | None = None,
    district: str | None = None,
    status: str | None = None,
    tier: str | None = Query(None, alias="tier"),
    q: str | None = None,
    limit: int = 500,
    offset: int = 0,
    db: Session = Depends(get_db),
    _: object = Depends(get_current_user),
):
    query = db.query(Camera)
    if city:
        query = query.filter(Camera.city == city)
    if district:
        query = query.filter(Camera.district == district)
    if status:
        query = query.filter(Camera.status == status)
    if tier:
        query = query.filter(Camera.analytics_tier == tier)
    if q:
        like = f"%{q}%"
        query = query.filter(Camera.name.ilike(like) | Camera.city.ilike(like) | Camera.address.ilike(like))
    total = query.count()
    cameras = query.order_by(Camera.id).offset(offset).limit(limit).all()
    return {"total": total, "items": [serialize(c) for c in cameras]}


@router.get("/stats")
def camera_stats(db: Session = Depends(get_db)):
    by_status = dict(db.query(Camera.status, func.count(Camera.id)).group_by(Camera.status).all())
    by_tier = dict(db.query(Camera.analytics_tier, func.count(Camera.id)).group_by(Camera.analytics_tier).all())
    by_city = dict(db.query(Camera.city, func.count(Camera.id)).group_by(Camera.city).all())
    return {"by_status": by_status, "by_tier": by_tier, "by_city": by_city,
            "total": sum(by_status.values())}


@router.get("/{camera_id}")
def get_camera(camera_id: int, db: Session = Depends(get_db)):
    camera = db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")
    return serialize(camera)


@router.post("", status_code=201)
def create_camera(payload: CameraCreate, db: Session = Depends(get_db),
                  _: object = Depends(get_current_user)):
    camera = Camera(
        **payload.model_dump(),
        status="unknown",
        state="Gujarat",
        created_at=datetime.now(timezone.utc),
    )
    db.add(camera)
    db.commit()
    db.refresh(camera)
    return serialize(camera)


@router.patch("/{camera_id}")
def update_camera(camera_id: int, payload: CameraUpdate, db: Session = Depends(get_db),
                  _: object = Depends(get_current_user)):
    camera = db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")
    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(camera, k, v)
    db.commit()
    db.refresh(camera)
    return serialize(camera)


@router.delete("/{camera_id}", status_code=204)
def delete_camera(camera_id: int, db: Session = Depends(get_db),
                  _: object = Depends(get_current_user)):
    camera = db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")
    db.delete(camera)
    db.commit()


@router.get("/departments/list")
def list_departments(db: Session = Depends(get_db)):
    return [
        {"id": d.id, "name": d.name, "code": d.code, "description": d.description}
        for d in db.query(Department).all()
    ]
