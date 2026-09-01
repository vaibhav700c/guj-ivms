"""HLS stream proxy for Sentinel Grid cameras.

The Sentinel CDN (cctv.corp8.cloud) uses HttpOnly/SameSite=Lax session cookies,
which cannot be shared cross-origin. This proxy authenticates to the CDN and
pipes HLS content through the Render backend so the browser on guj-ivms.vercel.app
can play real streams without cookie issues.
"""
import asyncio
import logging
import re
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Camera

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sentinel", tags=["sentinel"])

SENTINEL_COOKIE_NAME = "sentinel"
_cached_cookie: Optional[str] = None
_cookie_fetched_at: float = 0
_COOKIE_TTL = 1800  # re-auth every 30 min

# A real browser User-Agent is REQUIRED to prevent Cloudflare from tarpitting requests.
SPOOFED_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36"


async def _get_sentinel_cookie() -> str:
    """Authenticate once, cache the cookie."""
    global _cached_cookie, _cookie_fetched_at

    if _cached_cookie and (time.time() - _cookie_fetched_at) < _COOKIE_TTL:
        return _cached_cookie

    password = settings.SENTINEL_PASSWORD or "E6W6-8SAJ-3S9Z"
    if not password:
        raise HTTPException(503, "SENTINEL_PASSWORD not configured")

    async with httpx.AsyncClient(follow_redirects=False, timeout=15) as client:
        resp = await client.post(
            f"{settings.SENTINEL_HLS_BASE}/auth/login",
            data={"password": password},
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": SPOOFED_USER_AGENT
            },
        )
        
        cookie = resp.cookies.get(SENTINEL_COOKIE_NAME)
        if not cookie and resp.status_code == 302:
            raw_cookie = resp.headers.get("set-cookie", "")
            if SENTINEL_COOKIE_NAME in raw_cookie:
                for part in raw_cookie.split(";"):
                    part = part.strip()
                    if part.startswith(f"{SENTINEL_COOKIE_NAME}="):
                        cookie = part.split("=", 1)[1]
                        break
        
        if not cookie:
            raise HTTPException(502, f"Sentinel auth failed: HTTP {resp.status_code}")

    _cached_cookie = cookie
    _cookie_fetched_at = time.time()
    logger.info("Sentinel session refreshed")
    return _cached_cookie


def _build_stream_info(cam_id: str) -> dict:
    cam_id = cam_id.lower()
    return {
        "id": cam_id,
        "hls_url": f"/api/v1/sentinel/hls/{cam_id}/index.m3u8",
        "hls_direct_url": f"{settings.SENTINEL_HLS_BASE}/{cam_id}/index.m3u8",
        "rtsp_url": f"{settings.SENTINEL_RTSP_BASE}/{cam_id}",
        "whep_url": f"{settings.SENTINEL_WHEP_BASE}/{cam_id}/whep",
        "rtsp_transport": "tcp",
    }


@router.post("/refresh-auth")
async def refresh_auth():
    global _cached_cookie, _cookie_fetched_at
    _cached_cookie = None
    _cookie_fetched_at = 0
    try:
        await _get_sentinel_cookie()
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


@router.get("/hls/{cam_id}/index.m3u8")
async def hls_playlist(cam_id: str, request: Request):
    cam_id = cam_id.lower()
    cookie = await _get_sentinel_cookie()
    upstream_url = f"{settings.SENTINEL_HLS_BASE}/{cam_id}/index.m3u8"

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(
            upstream_url,
            cookies={SENTINEL_COOKIE_NAME: cookie},
            headers={"User-Agent": SPOOFED_USER_AGENT},
        )

    if resp.status_code == 401 or resp.status_code == 302:
        global _cached_cookie
        _cached_cookie = None
        cookie = await _get_sentinel_cookie()
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                upstream_url,
                cookies={SENTINEL_COOKIE_NAME: cookie},
                headers={"User-Agent": SPOOFED_USER_AGENT},
            )

    if resp.status_code != 200:
        raise HTTPException(resp.status_code, f"Upstream returned {resp.status_code}")

    content = resp.text

    def rewrite_line(line: str) -> str:
        stripped = line.strip()
        if not stripped:
            return line
        if stripped.startswith("#EXT-X-KEY") and 'URI="' in stripped:
            def _rewrite_uri(m):
                uri = m.group(1)
                if uri.startswith("/") or not uri.startswith("http"):
                    return f'URI="/api/v1/sentinel/hls/{cam_id}/enc.key"'
                return m.group(0)
            return re.sub(r'URI="([^"]+)"', _rewrite_uri, stripped)
        if not stripped.startswith("#"):
            seg = stripped.split("/")[-1].split("?")[0]
            return f"/api/v1/sentinel/hls/{cam_id}/{seg}"
        return line

    rewritten = "\n".join(rewrite_line(l) for l in content.splitlines())

    return Response(
        content=rewritten,
        media_type="application/vnd.apple.mpegurl",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-cache, no-store",
        },
    )


@router.get("/hls/{cam_id}/enc.key")
async def hls_enc_key(cam_id: str):
    cookie = await _get_sentinel_cookie()
    upstream_url = f"{settings.SENTINEL_HLS_BASE}/enc.key"

    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        resp = await client.get(
            upstream_url,
            cookies={SENTINEL_COOKIE_NAME: cookie},
            headers={"User-Agent": SPOOFED_USER_AGENT},
        )

    if resp.status_code != 200:
        raise HTTPException(resp.status_code, "Encryption key not found")

    return Response(
        content=resp.content,
        media_type="application/octet-stream",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=3600",
        },
    )


@router.get("/hls/{cam_id}/{segment}")
async def hls_segment(cam_id: str, segment: str):
    cam_id = cam_id.lower()
    if not segment.endswith(".ts") and not segment.endswith(".aac"):
        raise HTTPException(400, "Invalid segment type")

    cookie = await _get_sentinel_cookie()
    upstream_url = f"{settings.SENTINEL_HLS_BASE}/{cam_id}/{segment}"

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(
            upstream_url,
            cookies={SENTINEL_COOKIE_NAME: cookie},
            headers={"User-Agent": SPOOFED_USER_AGENT},
        )

    if resp.status_code != 200:
        raise HTTPException(resp.status_code, f"Segment not found: {segment}")

    return Response(
        content=resp.content,
        media_type="video/MP2T",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=10",
        },
    )


async def _fetch_sentinel_catalogue() -> list[dict]:
    cookie = await _get_sentinel_cookie()
    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        resp = await client.get(
            f"{settings.SENTINEL_HLS_BASE}/cameras.json",
            cookies={SENTINEL_COOKIE_NAME: cookie},
            headers={"User-Agent": SPOOFED_USER_AGENT},
        )
        resp.raise_for_status()
        return resp.json()


@router.get("/catalogue")
async def sentinel_catalogue(db: Session = Depends(get_db)):
    live: list[dict] = []
    source = "live"
    try:
        live = await _fetch_sentinel_catalogue()
    except Exception as exc:
        logger.warning("Could not fetch live catalogue: %s — using db fallback", exc)
        source = "db_fallback"

    local_cams = {
        c.external_id: c
        for c in db.query(Camera).filter(Camera.vms_vendor == "Sentinel Grid").all()
    }

    result = []
    catalogue_items = live if live else [{"id": k, "name": v.name} for k, v in local_cams.items()]

    for entry in catalogue_items:
        cam_id = entry["id"]
        local = local_cams.get(cam_id)
        result.append({
            "id": cam_id,
            "name": entry.get("name", local.name if local else cam_id),
            "db_id": local.id if local else None,
            "city": local.city if local else None,
            "district": local.district if local else None,
            "status": local.status if local else "unknown",
            "analytics_tier": local.analytics_tier if local else "C",
            **_build_stream_info(cam_id),
        })

    return {
        "count": len(result),
        "cameras": result,
        "source": source,
    }


@router.get("/stream-info/{cam_id}")
async def stream_info(cam_id: str, db: Session = Depends(get_db)):
    cam_id = cam_id.lower()
    if not cam_id.startswith("cam"):
        raise HTTPException(400, "Camera ID must be cam01 … cam30")
    local = db.query(Camera).filter(Camera.external_id == cam_id).first()
    return {
        **_build_stream_info(cam_id),
        "name": local.name if local else cam_id,
        "city": local.city if local else None,
        "db_id": local.id if local else None,
        "status": local.status if local else "unknown",
        "proxy_note": "Proxied",
    }
