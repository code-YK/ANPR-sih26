"""Authenticated WHEP proxy for the local MediaMTX relay (see
app/pipeline/webrtc_relay.py for why this exists and how the relay is fed).

Only the WHEP *signaling* is proxied here -- the SDP offer/answer exchange
is plain HTTP, so it can be RBAC-gated exactly like hls_proxy.py gates HLS
segments. The actual media (RTP/ICE/DTLS) negotiated by that exchange flows
directly between the browser and mediamtx's WebRTC listener afterwards; see
the module docstring in webrtc_relay.py and docs/webrtc-relay-testing.md for
what that does and doesn't cover.

No audit event: routine stream viewing isn't audited today either (hls_proxy
has none), so this stays consistent with that existing precedent rather
than introducing a new inconsistency between the two preview transports.
"""

import logging
import secrets
import time
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_service import AuthContext, get_authorised_camera, get_current_auth
from app.config import get_settings
from app.db import get_session
from app.models.camera import Camera
from app.pipeline import webrtc_relay

logger = logging.getLogger("sentinel.webrtc")

router = APIRouter()

# Opaque session_id -> (real mediamtx WHEP resource URL, created_at). Never
# hand the raw mediamtx URL (a 127.0.0.1 address, but still an internal
# implementation detail) back to the browser -- same principle hls_proxy.py
# applies to hls_url.
_sessions: dict[str, tuple[str, float]] = {}
_SESSION_TTL_SECONDS = 600.0


def _purge_stale_sessions() -> None:
    now = time.time()
    for session_id in [sid for sid, (_, created) in _sessions.items() if now - created > _SESSION_TTL_SECONDS]:
        _sessions.pop(session_id, None)


def _preview_source(camera: Camera) -> tuple[str, str]:
    """Prefer low-latency RTSP/TCP, falling back to HLS availability."""
    if camera.rtsp_url:
        scheme = urlparse(camera.rtsp_url).scheme.lower()
        if scheme not in {"rtsp", "rtsps"}:
            raise HTTPException(status_code=422, detail="Camera RTSP endpoint has an unsupported URL scheme")
        return camera.rtsp_url, "rtsp"
    if camera.hls_url:
        return camera.hls_url, "hls"
    raise HTTPException(status_code=404, detail="Camera has no RTSP or HLS preview source")


@router.post("/webrtc/{camera_id}/whep")
async def webrtc_whep_offer(
    camera_id: str,
    request: Request,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    camera = await get_authorised_camera(session, auth, camera_id, "viewer")
    source_url, source_transport = _preview_source(camera)

    settings = get_settings()
    try:
        await webrtc_relay.ensure_relay_running(camera_id, source_url, source_transport)
        await webrtc_relay.wait_path_ready(camera_id, settings.webrtc_relay_start_timeout_seconds)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=f"WebRTC relay failed to start: {exc}") from exc

    offer_sdp = await request.body()
    whep_url = f"http://127.0.0.1:{settings.mediamtx_webrtc_port}/{camera_id}/whep"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            upstream = await client.post(
                whep_url, content=offer_sdp, headers={"Content-Type": "application/sdp"}
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Relay negotiation failed: {exc}") from exc

    if upstream.status_code != 201:
        raise HTTPException(
            status_code=502, detail=f"Relay rejected the offer (status {upstream.status_code})"
        )

    webrtc_relay.touch(camera_id)
    _purge_stale_sessions()
    session_id = secrets.token_urlsafe(16)
    real_location = upstream.headers.get("location")
    if real_location:
        _sessions[session_id] = (urljoin(whep_url, real_location), time.time())

    return Response(
        content=upstream.content,
        media_type="application/sdp",
        status_code=201,
        headers={"Location": f"/api/webrtc/{camera_id}/whep/{session_id}"},
    )


@router.delete("/webrtc/{camera_id}/whep/{session_id}", status_code=204)
async def webrtc_whep_terminate(
    camera_id: str,
    session_id: str,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    await get_authorised_camera(session, auth, camera_id, "viewer")
    entry = _sessions.pop(session_id, None)
    if entry is None:
        return Response(status_code=204)  # already gone / unknown -- WHEP DELETE is idempotent
    real_url, _ = entry
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.delete(real_url)
    except httpx.HTTPError as exc:
        logger.info("WHEP session teardown for camera %s failed (relay likely already gone): %s", camera_id, exc)
    return Response(status_code=204)
