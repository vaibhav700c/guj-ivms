"""Camera registry routes — Model 1 foundation (CRUD + GIS + health)."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.db import get_db
from app.models import ANPREvent, Camera, Department, User
from app.security import Permission, get_current_user, require_permission

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
        "stream_url": c.stream_url,      # HLS (CDN)
        "rtsp_url": getattr(c, "rtsp_url", None),    # RTSP direct (AI/inference)
        "whep_url": getattr(c, "whep_url", None),    # WebRTC/WHEP (low-latency browser)
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


@router.get("/geo/nearby")
def cameras_nearby(lat: float, lng: float, radius_km: float = 5.0,
                   db: Session = Depends(get_db)):
    """Find cameras near a lat/lng within radius (plan §13 geo/nearby)."""
    import math

    def haversine(lat1, lng1, lat2, lng2):
        r = 6371.0
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * r * math.asin(math.sqrt(a))

    cams = db.query(Camera).all()
    hits = sorted(
        ((c, haversine(lat, lng, c.latitude, c.longitude)) for c in cams),
        key=lambda t: t[1],
    )
    return [
        {**serialize(c), "distance_km": round(d, 3)}
        for c, d in hits
        if d <= radius_km
    ][:100]


@router.get("/geo/coverage")
def coverage_heatmap(db: Session = Depends(get_db)):
    """Coverage heatmap data — per-camera event density (plan §9.2)."""
    rows = (
        db.query(Camera, func.count(ANPREvent.id).label("cnt"))
        .outerjoin(ANPREvent, ANPREvent.camera_id == Camera.id)
        .group_by(Camera.id)
        .all()
    )
    return [
        {
            "camera_id": c.id,
            "name": c.name,
            "lat": c.latitude,
            "lng": c.longitude,
            "status": c.status,
            "analytics_tier": c.analytics_tier,
            "district": c.district,
            "events": cnt,
        }
        for c, cnt in rows
    ]


@router.get("/gap-analysis")
def gap_analysis(db: Session = Depends(get_db)):
    """Uncovered zones report (plan §13 cameras/gap-analysis)."""
    cameras = db.query(Camera).all()
    districts: dict[str, dict] = {}
    for c in cameras:
        d = districts.setdefault(
            c.district or "Unknown",
            {"district": c.district or "Unknown", "total": 0, "online": 0,
             "tier_a": 0, "tier_b": 0, "tier_c": 0, "offline": 0},
        )
        d["total"] += 1
        if c.status == "online":
            d["online"] += 1
        if c.status == "offline":
            d["offline"] += 1
        d[f"tier_{c.analytics_tier.lower()}"] = d.get(f"tier_{c.analytics_tier.lower()}", 0) + 1

    report = []
    for d in sorted(districts.values(), key=lambda x: -x["total"]):
        coverage = d["online"] / max(d["total"], 1)
        # A district is a gap if coverage < 70% or has no Tier A (ANPR) camera
        gaps = []
        if coverage < 0.7:
            gaps.append("low_availability")
        if d["tier_a"] == 0:
            gaps.append("no_anpr_camera")
        if d["offline"] > 0:
            gaps.append(f"{d['offline']}_offline")
        report.append({**d, "coverage_pct": round(coverage * 100, 1),
                       "gap_flags": gaps, "is_gap": bool(gaps)})
    return {
        "districts": report,
        "gap_districts": [r for r in report if r["is_gap"]],
        "overall_coverage_pct": round(
            sum(r["online"] for r in report) / max(sum(r["total"] for r in report), 1) * 100, 1
        ),
    }


@router.post("/bulk", status_code=201)
def bulk_import_cameras(payload: list[CameraCreate], request: Request, db: Session = Depends(get_db),
                        user: User | None = Depends(require_permission(Permission.CAMERA_MANAGE))):
    """Bulk import cameras (plan §13 cameras/bulk — CSV/JSON)."""
    created = []
    for item in payload:
        cam = Camera(**item.model_dump(), status="unknown", state="Gujarat")
        db.add(cam)
        created.append(cam)
    db.commit()
    write_audit(db, actor=user, action="camera.bulk_import", target_type="camera",
                detail={"imported": len(created)}, request=request)
    return {"imported": len(created), "items": [serialize(c) for c in created]}


@router.get("/{camera_id}/health-log")
def camera_health_log(camera_id: int, limit: int = 50, db: Session = Depends(get_db)):
    """Time-series health samples for one camera (plan §9.1 camera_health_log)."""
    from app.models import CameraHealthLog

    rows = (
        db.query(CameraHealthLog)
        .filter(CameraHealthLog.camera_id == camera_id)
        .order_by(CameraHealthLog.time.desc())
        .limit(limit)
        .all()
    )
    return {"camera_id": camera_id, "items": [
        {"time": r.time.isoformat(), "status": r.status, "fps_actual": r.fps_actual,
         "latency_ms": r.latency_ms, "packet_loss": r.packet_loss,
         "error_message": r.error_message}
        for r in rows
    ]}


@router.get("/{camera_id}")
def get_camera(camera_id: int, db: Session = Depends(get_db)):
    camera = db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")
    return serialize(camera)


@router.post("", status_code=201)
def create_camera(payload: CameraCreate, request: Request, db: Session = Depends(get_db),
                  user: User | None = Depends(require_permission(Permission.CAMERA_MANAGE))):
    camera = Camera(
        **payload.model_dump(),
        status="unknown",
        state="Gujarat",
        created_at=datetime.now(timezone.utc),
    )
    db.add(camera)
    db.commit()
    db.refresh(camera)
    write_audit(db, actor=user, action="camera.create", target_type="camera",
                target_id=camera.id, detail={"name": camera.name}, request=request)
    return serialize(camera)


@router.api_route("/{camera_id}", methods=["PATCH", "PUT"])
def update_camera(camera_id: int, payload: CameraUpdate, request: Request, db: Session = Depends(get_db),
                  user: User | None = Depends(require_permission(Permission.CAMERA_MANAGE))):
    """Update camera metadata (plan §13 PATCH/PUT /cameras/{id})."""
    camera = db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")
    changes = payload.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(camera, k, v)
    db.commit()
    db.refresh(camera)
    write_audit(db, actor=user, action="camera.update", target_type="camera",
                target_id=camera.id, detail={"fields": list(changes.keys())}, request=request)
    return serialize(camera)


@router.delete("/{camera_id}", status_code=204)
def delete_camera(camera_id: int, request: Request, db: Session = Depends(get_db),
                  user: User | None = Depends(require_permission(Permission.CAMERA_MANAGE))):
    camera = db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")
    name = camera.name
    db.delete(camera)
    db.commit()
    write_audit(db, actor=user, action="camera.delete", target_type="camera",
                target_id=camera_id, detail={"name": name}, request=request)


@router.get("/departments/list")
def list_departments(db: Session = Depends(get_db)):
    return [
        {"id": d.id, "name": d.name, "code": d.code, "description": d.description}
        for d in db.query(Department).all()
    ]
