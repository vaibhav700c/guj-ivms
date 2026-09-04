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
from collections import OrderedDict
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


def _cookie_from_headers(resp: httpx.Response) -> str | None:
    """Pull the session cookie straight off Set-Cookie headers."""
    for raw in resp.headers.get_list("set-cookie"):
        for part in raw.split(";"):
            part = part.strip()
            if part.startswith(f"{SENTINEL_COOKIE_NAME}="):
                return part.split("=", 1)[1]
    return None


async def _get_sentinel_cookie() -> str:
    """Authenticate against the Sentinel CDN once, then cache the session cookie.

    The portal's sign-in form posts BOTH `email` and `password`. Posting only the
    password re-renders the login page as HTTP 200 with no cookie, which is why
    a password-only login looks like a success to naive status-code checks.
    """
    global _cached_cookie, _cookie_fetched_at

    if _cached_cookie and (time.time() - _cookie_fetched_at) < _COOKIE_TTL:
        return _cached_cookie

    email, password = settings.SENTINEL_EMAIL, settings.SENTINEL_PASSWORD
    if not (email and password):
        raise HTTPException(
            503,
            "Sentinel credentials not configured — set SENTINEL_EMAIL and "
            "SENTINEL_PASSWORD in the environment",
        )

    async with httpx.AsyncClient(follow_redirects=False, timeout=15) as client:
        resp = await client.post(
            f"{settings.SENTINEL_HLS_BASE}/auth/login",
            data={"email": email, "password": password},
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": SPOOFED_USER_AGENT,
            },
        )

    cookie = resp.cookies.get(SENTINEL_COOKIE_NAME) or _cookie_from_headers(resp)
    if not cookie:
        raise HTTPException(
            502,
            f"Sentinel auth rejected (HTTP {resp.status_code}) — verify "
            "SENTINEL_EMAIL/SENTINEL_PASSWORD and that the account is on the "
            "grid's approved access list",
        )

    _cached_cookie = cookie
    _cookie_fetched_at = time.time()
    logger.info("Sentinel session refreshed")
    return _cached_cookie


# Cloudflare rate-limits by source IP, and this backend is a single IP serving
# every viewer. A 9-tile grid firing nine cold playlist fetches at once is
# enough to get most of them 403'd, so upstream concurrency is capped and
# identical concurrent fetches are coalesced into one.
_UPSTREAM_CONCURRENCY = 2
_upstream_gate: asyncio.Semaphore | None = None
_inflight: dict[str, asyncio.Task] = {}


def _gate() -> asyncio.Semaphore:
    # Created lazily so it binds to the running loop, not import time.
    global _upstream_gate
    if _upstream_gate is None:
        _upstream_gate = asyncio.Semaphore(_UPSTREAM_CONCURRENCY)
    return _upstream_gate


async def _fetch_once(url: str, cookie: str, timeout: float) -> httpx.Response:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        return await client.get(
            url,
            cookies={SENTINEL_COOKIE_NAME: cookie},
            headers={"User-Agent": SPOOFED_USER_AGENT},
        )


async def _do_upstream_get(url: str, timeout: float) -> httpx.Response:
    global _cached_cookie
    async with _gate():
        try:
            resp = await _fetch_once(url, await _get_sentinel_cookie(), timeout)

            if resp.status_code in (302, 401):
                # Session lapsed — a fresh login is the right remedy.
                _cached_cookie = None
                resp = await _fetch_once(url, await _get_sentinel_cookie(), timeout)
            elif resp.status_code == 403:
                # Cloudflare throttling, not an auth failure. Re-authenticating
                # would only add another request from the same IP, so back off
                # briefly and retry with the existing session instead.
                await asyncio.sleep(1.5)
                resp = await _fetch_once(url, await _get_sentinel_cookie(), timeout)
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"Upstream request failed: {exc}") from exc

    if resp.status_code != 200:
        raise HTTPException(resp.status_code, f"Upstream returned {resp.status_code}")
    return resp


async def _upstream_get(url: str, timeout: float = 20.0) -> httpx.Response:
    """Fetch a Sentinel CDN URL, coalescing concurrent requests for the same URL.

    Without coalescing, every tile showing the same camera issues its own
    upstream fetch; with it, one fetch serves them all. Transport errors are
    mapped to 502 — they previously escaped as opaque 500s.
    """
    task = _inflight.get(url)
    if task is None:
        task = asyncio.create_task(_do_upstream_get(url, timeout))
        _inflight[url] = task
        task.add_done_callback(lambda _t, u=url: _inflight.pop(u, None))
    # shield so one client disconnecting does not cancel the shared fetch
    return await asyncio.shield(task)


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

    cached = _playlist_cache.get(cam_id)
    if cached and (time.time() - cached[0]) < _PLAYLIST_TTL:
        return _playlist_response(cached[1])

    upstream_url = f"{settings.SENTINEL_HLS_BASE}/{cam_id}/index.m3u8"
    resp = await _upstream_get(upstream_url, timeout=20)

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
    _playlist_cache[cam_id] = (time.time(), rewritten)
    return _playlist_response(rewritten)


def _playlist_response(body: str) -> Response:
    return Response(
        content=body,
        media_type="application/vnd.apple.mpegurl",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-cache, no-store",
        },
    )


_enc_key_cache: tuple[float, bytes] | None = None
_ENC_KEY_TTL = 3600.0

# Cloudflare fronts the CDN and throttles by source IP. Every viewer of the
# video wall shares this backend's single egress IP, so a 9-16 tile grid can
# push the whole deployment into 403s. Caching collapses N viewers into one
# upstream fetch.
#
# Segments are safe to cache indefinitely: the playlist is EXT-X-PLAYLIST-TYPE
# VOD over a looping feed, so seg00042.ts is always identical. The playlist
# itself is a full VOD listing of the entire loop (~400KB, thousands of
# segments), not a small live-window manifest — measured at ~25-30s to
# re-fetch from the Cloudflare-fronted CDN under load. A short TTL was
# forcing that expensive re-fetch on every viewer every few seconds, which
# starved the upstream concurrency gate and stalled segment delivery behind
# it (segments only play for ~6s each; a queued cold fetch behind a 27s
# playlist re-fetch guarantees a stall). The playlist barely changes, so a
# much longer TTL removes that cost with no real staleness risk.
_playlist_cache: dict[str, tuple[float, str]] = {}
_PLAYLIST_TTL = 60.0

_segment_cache: "OrderedDict[str, bytes]" = OrderedDict()
_SEGMENT_CACHE_MAX = 200  # ~270KB each → ~54MB of the 512MB budget. 40 was too
# small for concurrent viewers advancing through the same multi-hour VOD loop:
# it evicted usable segments almost immediately, forcing a ~12s cold fetch
# (for 6s of video) on nearly every tick instead of serving from cache.


def _cache_segment(key: str, content: bytes) -> None:
    _segment_cache[key] = content
    _segment_cache.move_to_end(key)
    while len(_segment_cache) > _SEGMENT_CACHE_MAX:
        _segment_cache.popitem(last=False)


@router.get("/hls/{cam_id}/enc.key")
async def hls_enc_key(cam_id: str):
    """Serve the AES-128 key for the encrypted HLS segments.

    Every player needs this key before it can decode a single segment, so it is
    cached: the key is 16 bytes and effectively static, and re-fetching it for
    each of ~16 grid tiles is what pushes Cloudflare into rate-limiting the
    egress IP.
    """
    global _enc_key_cache

    if _enc_key_cache and (time.time() - _enc_key_cache[0]) < _ENC_KEY_TTL:
        return _key_response(_enc_key_cache[1])

    cookie = await _get_sentinel_cookie()
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(
                f"{settings.SENTINEL_HLS_BASE}/enc.key",
                cookies={SENTINEL_COOKIE_NAME: cookie},
                headers={"User-Agent": SPOOFED_USER_AGENT},
            )
    except httpx.HTTPError as exc:
        # Transport-level failures were surfacing as opaque 500s.
        raise HTTPException(502, f"Encryption key fetch failed: {exc}") from exc

    if resp.status_code != 200:
        raise HTTPException(resp.status_code, "Encryption key not found")

    _enc_key_cache = (time.time(), resp.content)
    return _key_response(resp.content)


def _key_response(content: bytes) -> Response:
    return Response(
        content=content,
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

    key = f"{cam_id}/{segment}"
    content = _segment_cache.get(key)
    if content is not None:
        _segment_cache.move_to_end(key)
    else:
        resp = await _upstream_get(
            f"{settings.SENTINEL_HLS_BASE}/{cam_id}/{segment}", timeout=30
        )
        content = resp.content
        _cache_segment(key, content)

    return Response(
        content=content,
        media_type="video/MP2T",
        headers={
            "Access-Control-Allow-Origin": "*",
            # Segments are immutable for a given id, so let the browser hold
            # them too — this is the main lever against Cloudflare throttling
            # our single shared egress IP.
            "Cache-Control": "public, max-age=3600",
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
