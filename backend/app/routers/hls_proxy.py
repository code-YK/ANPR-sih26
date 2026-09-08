import re
import time
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_service import AuthContext, get_authorised_camera, get_current_auth
from app.config import get_settings
from app.db import get_session
from app.models.camera import Camera
from app.pipeline.catalogue import sandbox_login

router = APIRouter()

_M3U8_CONTENT_TYPES = ("mpegurl",)

# One upstream client per (camera, viewer). Viewer-scoped rather than
# camera-scoped on purpose: the gateway tracks a live playback position per
# session, and two viewers sharing one session fight over it. It also gives
# the browser a way to get a genuinely fresh session -- reconnecting with a
# new viewer id gets a new client here, new cookies, new gateway session.
#
# The gateway drops a session's media playlist (serves it empty) every
# ~15-35s in this sandbox; the Python workers already survive that by
# reconnecting, and this is what lets the browser player do the same.
_clients: dict[tuple[str, str], httpx.AsyncClient] = {}
_last_used: dict[tuple[str, str], float] = {}

# hls_url is effectively static per camera and this endpoint is hit for
# every segment, so a DB round trip per request is latency the live window
# can't spare.
_hls_url_cache: dict[str, str] = {}

_CLIENT_IDLE_TIMEOUT = 120.0

# Matches an HLS tag attribute like URI="/enc.key" whose value is an
# *absolute* path. A relative reference (e.g. "seg00000.ts") already
# resolves correctly against wherever the player fetched the m3u8 from --
# this proxy's own URL -- so it needs no rewriting. An absolute one
# (confirmed live: the AES-128 key on the 2026-09-01 government sandbox
# is referenced as URI="/enc.key") resolves against the *page's* origin
# per the HLS/URI spec, not the playlist's directory, so hls.js would
# fetch it from this app's own frontend origin instead of the upstream --
# never proxied, never authenticated, decryption fails silently and every
# segment reads as "invalid data" even though the segment fetch itself
# succeeded. Rewriting it to route through this same per-camera-viewer
# proxy path is the fix.
_ABSOLUTE_URI_RE = re.compile(r'URI="(/[^"]*)"')

# Reserved path segment marking a rewritten absolute-path URI so the route
# handler below can tell it apart from an ordinary (relative) segment/
# sub-playlist filename -- an absolute path like /enc.key must resolve
# against the upstream's own scheme+host root, not against this camera's
# segment directory the way a bare "seg00000.ts" does.
_ABS_MARKER = "_abs"


def _rewrite_absolute_uris(playlist_text: str, camera_id: str, viewer: str) -> str:
    prefix = f"/api/hls/{camera_id}/{viewer}/{_ABS_MARKER}"
    return _ABSOLUTE_URI_RE.sub(lambda m: f'URI="{prefix}{m.group(1)}"', playlist_text)


async def _reap_idle_clients() -> None:
    """Close clients whose viewer has gone away. Each open client is a held
    gateway connection (GOV-ING-012), so leaking them would keep consuming
    stream copies for players that closed long ago."""
    now = time.time()
    for key in [k for k, seen in _last_used.items() if now - seen > _CLIENT_IDLE_TIMEOUT]:
        client = _clients.pop(key, None)
        _last_used.pop(key, None)
        if client is not None and not client.is_closed:
            await client.aclose()


async def _client_for(camera_id: str, viewer: str) -> httpx.AsyncClient:
    await _reap_idle_clients()
    key = (camera_id, viewer)
    client = _clients.get(key)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(follow_redirects=True, timeout=15.0)
        # A no-op when the configured sandbox doesn't gate HLS behind a
        # login (see sandbox_login's own docstring) -- only the
        # password-gated sandbox pays for this extra round trip, and only
        # once per fresh client, not per segment.
        await sandbox_login(client, get_settings())
        _clients[key] = client
    _last_used[key] = time.time()
    return client


@router.get("/hls/{camera_id}/{viewer}/{filename:path}")
async def hls_proxy(
    camera_id: str,
    viewer: str,
    filename: str,
    request: Request,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    """Relays HLS playlists and segments through the backend so the browser
    never makes a cross-origin request to the streaming gateway directly.

    This exists because the gateway's edge sends a duplicated
    `Access-Control-Allow-Origin` header (`*, *`) on every response --
    confirmed with `curl -v`, not a proxy artifact. That's malformed per the
    CORS spec, and every CORS-enforcing browser rejects it outright, which
    silently breaks hls.js playback from a browser. It does not affect the
    ANPR/person workers: OpenCV and ffmpeg don't enforce CORS.

    `viewer` is an opaque per-player token and is deliberately part of the
    path, not the query: HLS child playlists and segments are referenced by
    relative URL, so a path prefix is inherited automatically while a query
    parameter would be dropped the moment the master playlist points at
    `video1_stream.m3u8?session=...`.
    """
    await get_authorised_camera(session, auth, camera_id, "viewer")
    hls_url = _hls_url_cache.get(camera_id)
    if hls_url is None:
        result = await session.execute(select(Camera.hls_url).where(Camera.camera_id == camera_id))
        hls_url = result.scalar_one_or_none()
        if not hls_url:
            raise HTTPException(status_code=404, detail="Camera has no stream URL")
        _hls_url_cache[camera_id] = hls_url

    if filename.startswith(f"{_ABS_MARKER}/"):
        # A rewritten absolute-path URI (see _rewrite_absolute_uris) --
        # resolve against the upstream's own scheme+host root, matching
        # where the original, unrewritten URI="/..." would have resolved
        # on the upstream itself.
        parsed = urlparse(hls_url)
        upstream_url = f"{parsed.scheme}://{parsed.netloc}/{filename[len(_ABS_MARKER) + 1:]}"
    else:
        base = hls_url.rsplit("/", 1)[0] + "/"
        upstream_url = urljoin(base, filename)
    if request.url.query:
        upstream_url = f"{upstream_url}?{request.url.query}"

    client = await _client_for(camera_id, viewer)
    try:
        upstream = await client.get(upstream_url)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Upstream fetch failed: {exc}") from exc

    if upstream.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Upstream returned {upstream.status_code}")

    content_type = upstream.headers.get("content-type", "application/octet-stream")
    if filename.endswith(".m3u8") or any(t in content_type for t in _M3U8_CONTENT_TYPES):
        # An empty media playlist is how this gateway signals a dead session.
        # Reported as 503 rather than passed through as a valid-but-empty
        # playlist, so the client can tell "session expired, reconnect" apart
        # from "playlist fetched fine".
        if "#EXTINF" not in upstream.text and "#EXT-X-STREAM-INF" not in upstream.text:
            raise HTTPException(status_code=503, detail="Upstream playlist is empty (session expired)")
        rewritten = _rewrite_absolute_uris(upstream.text, camera_id, viewer)
        return Response(
            content=rewritten,
            media_type="application/vnd.apple.mpegurl",
            headers={"Cache-Control": "no-store"},
        )
    return Response(content=upstream.content, media_type=content_type)
