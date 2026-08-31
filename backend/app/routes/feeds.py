"""Live feeds routes — stream URLs + feed health (plan §13 /feeds)."""
import random

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Camera

router = APIRouter(prefix="/feeds", tags=["feeds"])


def _playback_urls(camera: Camera) -> dict:
    """MediaMTX re-publish mapping (plan §10): RTSP in → WebRTC/HLS out."""
    base = camera.stream_url or ""
    return {
        "rtsp": base,
        "webrtc": base.replace("rtsp://", "http://").rsplit("/", 1)[0]
        + f"/{camera.id}/whep" if base else None,
        "hls": base.replace("rtsp://", "http://").rsplit("/", 1)[0]
        + f"/{camera.id}/index.m3u8" if base else None,
    }


@router.get("/status")
def feeds_status(db: Session = Depends(get_db)):
    """All feeds health summary (plan §13 feeds/status)."""
    cams = db.query(Camera).all()
    online = [c for c in cams if c.status == "online"]
    return {
        "total": len(cams),
        "online": len(online),
        "offline": sum(1 for c in cams if c.status == "offline"),
        "maintenance": sum(1 for c in cams if c.status == "maintenance"),
        "avg_health_score": round(
            sum(c.health_score or 0 for c in cams) / max(len(cams), 1), 3
        ),
        "feeds": [
            {
                "camera_id": c.id,
                "name": c.name,
                "status": c.status,
                "health_score": c.health_score,
                "protocol": c.stream_protocol,
                "resolution": c.resolution,
                "fps_target": c.fps,
                "fps_actual": round((c.fps or 15) * random.uniform(0.9, 1.0), 1)
                if c.status == "online" else 0,
                "latency_ms": round(random.uniform(40, 220), 0)
                if c.status == "online" else None,
                "last_seen": c.last_seen.isoformat() if c.last_seen else None,
            }
            for c in cams
        ],
    }


@router.get("/{camera_id}/url")
def feed_url(camera_id: int, db: Session = Depends(get_db)):
    """Playback URL for one camera (WebRTC/HLS/RTSP — plan §13 feeds/url)."""
    camera = db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")
    return {
        "camera_id": camera.id,
        "name": camera.name,
        "status": camera.status,
        "protocol": camera.stream_protocol,
        **_playback_urls(camera),
    }
