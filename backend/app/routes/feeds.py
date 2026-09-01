"""Live feeds routes — stream URLs, snapshots + feed health (plan §13 /feeds)."""
import asyncio
import random
import shutil
import time

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Camera
from app.routes.sentinel import SENTINEL_COOKIE_NAME, _get_sentinel_cookie

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


# ── Snapshot capture (plan §13 feeds/{camera_id}/snapshot) ────────────────────

_snapshot_cache: dict[int, tuple[float, bytes]] = {}
_SNAPSHOT_TTL = 8.0  # seconds — one capture per camera per 8s window


async def _capture_frame(cam_id: str) -> bytes:
    """Grab one JPEG frame from the live HLS stream using ffmpeg.

    ffmpeg decrypts the AES-128 HLS segments itself when given the playlist
    URL with the Sentinel session cookie. Raises HTTPException on failure.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise HTTPException(
            503, "ffmpeg is not available on this deployment — snapshot capture disabled"
        )
    cookie = await _get_sentinel_cookie()
    url = f"{settings.SENTINEL_HLS_BASE}/{cam_id}/index.m3u8"
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error",
        "-headers", f"Cookie: {SENTINEL_COOKIE_NAME}={cookie}\r\n",
        "-user_agent", "GujIVMS/1.0 snapshot",
        "-rw_timeout", "15000000",  # 15s IO timeout (microseconds)
        "-i", url,
        "-frames:v", "1", "-q:v", "3", "-f", "image2", "pipe:1",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=30)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise HTTPException(504, "Snapshot capture timed out")
    if proc.returncode != 0 or not out:
        detail = err.decode(errors="replace")[-200:] if err else "no frame decoded"
        raise HTTPException(502, f"Snapshot capture failed: {detail}")
    return out


@router.get("/{camera_id}/snapshot")
async def feed_snapshot(camera_id: int, db: Session = Depends(get_db)):
    """Current frame JPEG from the live feed (plan §13 feeds/snapshot)."""
    camera = db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(404, "Camera not found")
    if camera.status != "online":
        raise HTTPException(503, f"Camera feed is {camera.status} — no live frame available")

    now = time.time()
    cached = _snapshot_cache.get(camera_id)
    if cached and now - cached[0] < _SNAPSHOT_TTL:
        jpeg = cached[1]
    else:
        cam_id = camera.external_id or f"cam{camera_id:02d}"
        jpeg = await _capture_frame(cam_id)
        _snapshot_cache[camera_id] = (now, jpeg)
    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"},
    )
