"""System routes — health, config, adapter status (plan §13 /system)."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import AuditLog, Camera, Department, User, VehicleRecord, WatchlistEntry
from app.security import Permission, get_current_user, require_permission
from app.simulator import simulator

router = APIRouter(prefix="/system", tags=["system"])

# Federation adapter registry (plan §11.2)
ADAPTER_REGISTRY = {
    "sentinel": {"status": "available", "description": "Sentinel Camera Grid (hackathon)"},
    "rtsp_generic": {"status": "available", "description": "Generic RTSP — any IP camera/NVR"},
    "onvif": {"status": "available", "description": "ONVIF-compliant discovery"},
    "hikvision": {"status": "planned", "description": "Hikvision ISAPI"},
    "dahua": {"status": "planned", "description": "Dahua HTTP API"},
    "milestone": {"status": "planned", "description": "Milestone XProtect"},
}


@router.get("/health")
def system_health(db: Session = Depends(get_db)):
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "connected" if db_ok else "error",
        "database_dialect": db.bind.dialect.name,
        "environment": settings.ENVIRONMENT,
        "version": settings.VERSION,
        "simulator": simulator.status(),
    }


@router.get("/config")
def system_config(_: object = Depends(get_current_user)):
    return {
        "app": settings.APP_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "auth_required": settings.REQUIRE_AUTH,
        "simulator_auto_start": settings.SIMULATOR_AUTO_START,
        "simulator_interval_seconds": settings.SIMULATOR_INTERVAL_SECONDS,
        "redis_configured": bool(settings.REDIS_URL),
        "api_prefix": settings.API_V1_PREFIX,
    }


@router.get("/adapters")
def adapter_status(db: Session = Depends(get_db)):
    """Federation connector registry status (plan §11)."""
    vendors = {}
    for (vendor,) in db.query(Camera.vms_vendor).distinct():
        vendors[vendor or "unspecified"] = (
            db.query(Camera).filter(Camera.vms_vendor == vendor).count()
        )
    return {
        "registry": ADAPTER_REGISTRY,
        "connected_vms_vendors": vendors,
        "ingest_endpoints": [
            "POST /api/v1/ingest/anpr",
            "POST /api/v1/ingest/detection",
        ],
    }


@router.get("/audit")
def audit_log(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: object = Depends(require_permission(Permission.SYSTEM_CONFIG)),
):
    """Recent audit trail entries (plan §17.1 Layer 4). `limit` is capped at 200."""
    rows = (
        db.query(AuditLog)
        .order_by(AuditLog.timestamp.desc())
        .limit(limit)
        .all()
    )
    return {
        "total": db.query(AuditLog).count(),
        "items": [
            {
                "id": r.id,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "actor": r.actor,
                "actor_role": r.actor_role,
                "action": r.action,
                "target_type": r.target_type,
                "target_id": r.target_id,
                "detail": r.detail,
                "ip_address": r.ip_address,
            }
            for r in rows
        ],
    }


@router.post("/reseed")
def reseed(
    secret: str,
    db: Session = Depends(get_db),
):
    """Drop and re-seed cameras, users, vehicles, and watchlist.
    Protected by INGEST_API_KEY — do not expose to the public."""
    expected = settings.INGEST_API_KEY or ""
    if not expected or secret != expected:
        raise HTTPException(403, "Invalid secret")

    from app.seed import seed

    # Use raw SQL so FK order is irrelevant (TRUNCATE ... CASCADE on Postgres,
    # individual DELETEs on SQLite)
    dialect = db.bind.dialect.name
    if dialect == "postgresql":
        db.execute(text(
            "TRUNCATE TABLE alerts, anpr_events, detection_events, camera_health_log, "
            "cameras, watchlist, vehicle_records, users, departments "
            "RESTART IDENTITY CASCADE"
        ))
    else:
        # SQLite: delete in FK order
        for tbl in [
            "alerts", "anpr_events", "detection_events", "camera_health_log",
            "cameras", "watchlist", "vehicle_records", "users", "departments",
        ]:
            db.execute(text(f"DELETE FROM {tbl}"))
    db.commit()

    seed(db)

    return {
        "status": "reseeded",
        "cameras": db.query(Camera).count(),
        "vehicles": db.query(VehicleRecord).count(),
        "watchlist": db.query(WatchlistEntry).count(),
        "users": db.query(User).count(),
    }
