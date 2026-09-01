"""HLS stream proxy for Sentinel Grid cameras.

The Sentinel CDN (cctv.corp8.cloud) uses HttpOnly/SameSite=Lax session cookies,
which cannot be shared cross-origin. This proxy authenticates to the CDN and
pipes HLS content through the Render backend so the browser on guj-ivms.vercel.app
can play real streams without cookie issues.

Routes:
  GET /api/v1/sentinel/hls/{cam_id}/index.m3u8  → proxied + rewritten playlist
  GET /api/v1/sentinel/hls/{cam_id}/{segment}   → proxied .ts segment
  GET /api/v1/sentinel/catalogue                → live camera list
  GET /api/v1/sentinel/stream-info/{cam_id}     → per-camera endpoints
"""
import asyncio
import logging
import re
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Camera

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sentinel", tags=["sentinel"])

SENTINEL_COOKIE_NAME = "sentinel"
_cached_cookie: Optional[str] = None
_cookie_fetched_at: float = 0
_COOKIE_TTL = 1800  # re-auth every 30 min (sessions expire before 1h in practice)

# Fallback password — same as SENTINEL_PASSWORD env var on Render.
# Having it here ensures streams survive an accidental env-var loss on redeploy.
_SENTINEL_PWD_FALLBACK = "E6W6-8SAJ-3S9Z"


_cookie_lock = asyncio.Lock()

async def _get_sentinel_cookie() -> str:
    """Authenticate once, cache the cookie for 30 min."""
    global _cached_cookie, _cookie_fetched_at

    async with _cookie_lock:
        if _cached_cookie and (time.time() - _cookie_fetched_at) < _COOKIE_TTL:
            return _cached_cookie

        # Use env var first, fall back to embedded constant
        password = settings.SENTINEL_PASSWORD or _SENTINEL_PWD_FALLBACK
        if not password:
            raise HTTPException(503, "SENTINEL_PASSWORD not configured — contact admin")

        # Do NOT follow redirects — the login endpoint returns 302 with Set-Cookie;
        # following the redirect causes httpx to lose the cookie.
        async with httpx.AsyncClient(follow_redirects=False, timeout=15) as client:
            resp = await client.post(
                f"{settings.SENTINEL_HLS_BASE}/auth/login",
                data={"password": password},
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": "GujIVMS/1.0 HLS-Proxy"
                },
            )
            # Successful login returns 302 with Set-Cookie
            cookie = resp.cookies.get(SENTINEL_COOKIE_NAME)
            if not cookie and resp.status_code == 302:
                # Try reading from raw Set-Cookie header as fallback
                raw_cookie = resp.headers.get("set-cookie", "")
                if SENTINEL_COOKIE_NAME in raw_cookie:
                    # Parse out just the value: sentinel=<value>;
                    for part in raw_cookie.split(";"):
                        part = part.strip()
                        if part.startswith(f"{SENTINEL_COOKIE_NAME}="):
                            cookie = part.split("=", 1)[1]
                            break
            if not cookie:
                raise HTTPException(
                    502,
                    f"Sentinel auth failed — status {resp.status_code}, no cookie returned. "
                    "Check SENTINEL_PASSWORD env var on Render."
                )

        _cached_cookie = cookie
        _cookie_fetched_at = time.time()
        logger.info("Sentinel session refreshed (HTTP %d)", resp.status_code)
        return _cached_cookie


def _build_stream_info(cam_id: str) -> dict:
    """Return all endpoint URLs for a Sentinel camera (proxied HLS preferred)."""
    cam_id = cam_id.lower()
    proxy_base = f"{settings.SENTINEL_HLS_BASE}".rstrip("/")  # not used for proxy
    # The proxy URL is our own backend
    return {
        "id": cam_id,
        # Proxied HLS — browser-friendly, no cross-origin auth needed
        "hls_url": f"/api/v1/sentinel/hls/{cam_id}/index.m3u8",
        # Direct CDN HLS (requires browser session cookie at cctv.corp8.cloud)
        "hls_direct_url": f"{settings.SENTINEL_HLS_BASE}/{cam_id}/index.m3u8",
        # RTSP — AI inference only (force TCP per integration.txt §3)
        "rtsp_url": f"{settings.SENTINEL_RTSP_BASE}/{cam_id}",
        # WebRTC WHEP — low latency browser (http — blocked on https pages)
        "whep_url": f"{settings.SENTINEL_WHEP_BASE}/{cam_id}/whep",
        "rtsp_transport": "tcp",
    }


# ── Manual auth refresh ───────────────────────────────────────────────────────

@router.post("/refresh-auth")
async def refresh_auth():
    """Force-expire the cached Sentinel cookie and re-authenticate immediately.
    Call this if streams suddenly stop working (session expired mid-day).
    """
    global _cached_cookie, _cookie_fetched_at
    _cached_cookie = None
    _cookie_fetched_at = 0
    try:
        cookie = await _get_sentinel_cookie()
        return {"status": "ok", "message": "Sentinel session refreshed", "cookie_len": len(cookie)}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


_http_client: Optional[httpx.AsyncClient] = None

def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0),
            limits=httpx.Limits(max_keepalive_connections=50, max_connections=100)
        )
    return _http_client

# ── HLS Proxy ────────────────────────────────────────────────────────────────

@router.get("/hls/{cam_id}/index.m3u8")
async def hls_playlist(cam_id: str, request: Request):
    """Proxy and rewrite the HLS playlist so .ts segment URLs resolve through us."""
    cam_id = cam_id.lower()
    cookie = await _get_sentinel_cookie()
    upstream_url = f"{settings.SENTINEL_HLS_BASE}/{cam_id}/index.m3u8"
    client = get_http_client()

    resp = await client.get(
        upstream_url,
        cookies={SENTINEL_COOKIE_NAME: cookie},
        headers={"User-Agent": "GujIVMS/1.0 HLS-Proxy"},
        follow_redirects=False,
    )

    if resp.status_code == 401 or resp.status_code == 302:
        # Cookie expired — clear and retry once
        global _cached_cookie
        _cached_cookie = None
        cookie = await _get_sentinel_cookie()
        resp = await client.get(
            upstream_url,
            cookies={SENTINEL_COOKIE_NAME: cookie},
            headers={"User-Agent": "GujIVMS/1.0 HLS-Proxy"},
            follow_redirects=False,
        )

    if resp.status_code != 200:
        raise HTTPException(resp.status_code, f"Upstream returned {resp.status_code}")

    # Rewrite segment URLs and EXT-X-KEY URI to go through our proxy
    content = resp.text

    def rewrite_line(line: str) -> str:
        stripped = line.strip()
        if not stripped:
            return line
        # Rewrite AES-128 key URI so browser fetches it through our proxy too
        if stripped.startswith("#EXT-X-KEY") and 'URI="' in stripped:
            import re
            def _rewrite_uri(m):
                uri = m.group(1)
                if uri.startswith("/") or not uri.startswith("http"):
                    # Relative URI — point to our enc.key proxy
                    return f'URI="/api/v1/sentinel/hls/{cam_id}/enc.key"'
                return m.group(0)
            return re.sub(r'URI="([^"]+)"', _rewrite_uri, stripped)
        # Rewrite .ts segment lines (non-# lines)
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
    """Proxy the AES-128 decryption key for HLS segments.
    The key URI (/enc.key) is shared across all cameras on the CDN.
    """
    cookie = await _get_sentinel_cookie()
    upstream_url = f"{settings.SENTINEL_HLS_BASE}/enc.key"
    client = get_http_client()

    resp = await client.get(
        upstream_url,
        cookies={SENTINEL_COOKIE_NAME: cookie},
        headers={"User-Agent": "GujIVMS/1.0 HLS-Proxy"},
        follow_redirects=False,
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
    """Proxy a single .ts segment from the CDN."""
    cam_id = cam_id.lower()
    if not segment.endswith(".ts") and not segment.endswith(".aac"):
        raise HTTPException(400, "Invalid segment type")

    cookie = await _get_sentinel_cookie()
    upstream_url = f"{settings.SENTINEL_HLS_BASE}/{cam_id}/{segment}"
    client = get_http_client()

    resp = await client.get(
        upstream_url,
        cookies={SENTINEL_COOKIE_NAME: cookie},
        headers={"User-Agent": "GujIVMS/1.0 HLS-Proxy"},
        follow_redirects=False,
        timeout=30.0,
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


# ── Catalogue ─────────────────────────────────────────────────────────────────

async def _fetch_sentinel_catalogue() -> list[dict]:
    cookie = await _get_sentinel_cookie()
    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        resp = await client.get(
            f"{settings.SENTINEL_HLS_BASE}/cameras.json",
            cookies={SENTINEL_COOKIE_NAME: cookie},
        )
        resp.raise_for_status()
        return resp.json()


@router.get("/catalogue")
async def sentinel_catalogue(db: Session = Depends(get_db)):
    """Return the live Sentinel Grid camera list merged with the local registry."""
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
    """Return all stream endpoints for a single Sentinel camera."""
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
        "proxy_note": (
            "Use hls_url (proxied via this backend) for browser playback. "
            "rtsp_url is for AI inference (force TCP). "
            "whep_url is http-only — blocked by https pages."
        ),
    }
