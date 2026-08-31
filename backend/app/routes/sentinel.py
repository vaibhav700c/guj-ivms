"""Sentinel Grid catalogue proxy.

Fetches the live cameras.json from cctv.corp8.cloud using the configured
access password and merges it with the local camera registry so the frontend
always has up-to-date stream URLs even if new cameras are added to the grid.

GET /api/v1/sentinel/catalogue   → live list (falls back to db if CDN unreachable)
GET /api/v1/sentinel/stream-info → stream URL patterns for a given camera id
"""
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Camera

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sentinel", tags=["sentinel"])

SENTINEL_COOKIE_NAME = "sentinel"


async def _fetch_sentinel_catalogue() -> list[dict]:
    """Login to cctv.corp8.cloud and fetch cameras.json."""
    if not settings.SENTINEL_PASSWORD:
        raise ValueError("SENTINEL_PASSWORD not configured")

    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        # Authenticate — returns Set-Cookie: sentinel=<token>
        login_resp = await client.post(
            f"{settings.SENTINEL_HLS_BASE}/auth/login",
            data={"password": settings.SENTINEL_PASSWORD},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        session_cookie = login_resp.cookies.get(SENTINEL_COOKIE_NAME)
        if not session_cookie:
            raise ValueError("Authentication failed — check SENTINEL_PASSWORD")

        catalogue_resp = await client.get(
            f"{settings.SENTINEL_HLS_BASE}/cameras.json",
            cookies={SENTINEL_COOKIE_NAME: session_cookie},
        )
        catalogue_resp.raise_for_status()
        return catalogue_resp.json()


def _build_stream_info(cam_id: str) -> dict:
    return {
        "id": cam_id,
        "hls_url": f"{settings.SENTINEL_HLS_BASE}/{cam_id}/index.m3u8",
        "rtsp_url": f"{settings.SENTINEL_RTSP_BASE}/{cam_id}",
        "whep_url": f"{settings.SENTINEL_WHEP_BASE}/{cam_id}/whep",
        "rtsp_transport": "tcp",  # per integration.txt §3 — always force TCP
    }


@router.get("/catalogue")
async def sentinel_catalogue(db: Session = Depends(get_db)):
    """Return the live Sentinel Grid camera list merged with the local registry."""
    live: list[dict] = []
    try:
        live = await _fetch_sentinel_catalogue()
    except Exception as exc:
        logger.warning("Could not fetch live Sentinel catalogue: %s — using db fallback", exc)

    # Build a lookup from the local registry (sentinel cameras have external_id = cam01 … cam30)
    local_cams = {
        c.external_id: c
        for c in db.query(Camera).filter(Camera.vms_vendor == "Sentinel Grid").all()
    }

    result = []
    for entry in live:
        cam_id = entry["id"]
        local = local_cams.get(cam_id)
        result.append({
            "id": cam_id,
            "name": entry.get("name", cam_id),
            "db_id": local.id if local else None,
            "city": local.city if local else None,
            "status": local.status if local else "unknown",
            "analytics_tier": local.analytics_tier if local else "C",
            **_build_stream_info(cam_id),
        })

    # If live fetch failed, fall back to db sentinel cameras
    if not live:
        for cam_id, local in local_cams.items():
            result.append({
                "id": cam_id,
                "name": local.name,
                "db_id": local.id,
                "city": local.city,
                "status": local.status,
                "analytics_tier": local.analytics_tier,
                **_build_stream_info(cam_id),
            })

    return {"count": len(result), "cameras": result, "source": "live" if live else "db_fallback"}


@router.get("/stream-info/{cam_id}")
async def stream_info(cam_id: str, db: Session = Depends(get_db)):
    """Return all stream endpoints for a single Sentinel camera."""
    cam_id = cam_id.lower()
    if not cam_id.startswith("cam"):
        raise HTTPException(400, "Camera ID must be in format cam01 … cam30")

    local = db.query(Camera).filter(Camera.external_id == cam_id).first()
    return {
        **_build_stream_info(cam_id),
        "name": local.name if local else cam_id,
        "city": local.city if local else None,
        "db_id": local.id if local else None,
        "status": local.status if local else "unknown",
        "note": (
            "HLS streams require Sentinel Grid session cookie. "
            "RTSP: force TCP (rtsp_transport=tcp). "
            "WHEP: http — avoid mixed-content on https pages."
        ),
    }
