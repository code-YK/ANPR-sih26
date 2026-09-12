"""Catalogue client for the Sentinel sandbox /api/ingest endpoint.

The catalogue is the contract: camera IDs, URLs, and availability all come
from here at request time. Never hardcode or reconstruct a stream URL --
the one exception is the 2026-09-01 integrator's-guide sandbox
(parse_gov_feed_catalogue below), whose own catalogue deliberately carries
only {id, name} and documents RTSP/WHEP/HLS as fixed URL templates keyed
on that id; constructing them here is following that contract, not
bypassing it.
"""

import re
from dataclasses import dataclass

import httpx

from app.config import get_settings


@dataclass(frozen=True)
class CatalogueCamera:
    camera_id: str
    camera_number: int
    name: str
    location: str
    codec: str | None
    live: bool
    width: int | None
    height: int | None
    fps: float | None
    bitrate_kbps: int | None
    rtsp_url: str
    webrtc_url: str
    hls_url: str  # resolved to an absolute URL


def _resolve_hls(path_or_url: str | None, browser_base_url: str) -> str:
    if not path_or_url:
        return ""
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        return path_or_url
    return f"{browser_base_url}{path_or_url}"


def _empty_to_none(value):
    if value in ("", 0, 0.0, None):
        return None
    return value


def parse_sentinel_default(data: dict | list, browser_base_url: str) -> list[CatalogueCamera]:
    """Parses the one catalogue JSON shape this project has seen (see
    docs/registry-gis-build-spec.md's schema table). Split out from the HTTP fetch
    below so both the original single-source sync and the newer named
    catalogue_sources adapter registry (app/pipeline/catalogue_sources.py)
    share this one proven-correct parser instead of duplicating it."""
    raw_cameras = data.get("cameras", data if isinstance(data, list) else []) if isinstance(data, dict) else data
    cameras = []
    for raw in raw_cameras:
        cameras.append(
            CatalogueCamera(
                camera_id=str(raw["id"]),
                camera_number=int(raw["number"]),
                name=raw.get("name") or f"Camera {raw['number']}",
                location=raw.get("location") or "",
                codec=_empty_to_none(raw.get("codec")),
                live=bool(raw.get("live")),
                width=_empty_to_none(raw.get("width")),
                height=_empty_to_none(raw.get("height")),
                fps=_empty_to_none(raw.get("fps")),
                bitrate_kbps=_empty_to_none(raw.get("bitrate_kbps")),
                rtsp_url=raw.get("rtsp_url") or "",
                webrtc_url=raw.get("webrtc_url") or "",
                hls_url=_resolve_hls(raw.get("hls_live_url"), browser_base_url),
            )
        )
    return cameras


_GOV_FEED_ID_RE = re.compile(r"^cam(\d+)$")


def parse_gov_feed_catalogue(data: list[dict], settings) -> list[CatalogueCamera]:
    """The 2026-09-01 integrator's-guide sandbox: each entry is only
    ``{"id": "cam01", "name": "01 Chiman bhai Bridge"}`` -- no per-camera
    media URLs, no sequential/unique number in `name` (several cameras
    share a leading number, and at least one has none at all -- confirmed
    against the real 30-camera response, not assumed). `camera_number` is
    therefore taken from the id's own numeric suffix, which the guide
    documents as stable (`cam01`..`cam30`) and every observed row matched.

    RTSP and WHEP are served unauthenticated directly off
    `sandbox_stream_host` (confirmed by a real, unauthenticated `ffprobe`
    against two separate cameras); HLS stays on the CDN/browser host and
    needs the session cookie `fetch_catalogue` already obtained to fetch
    even the catalogue itself -- so unlike RTSP, playback of this hls_url
    outside an already-authenticated client (i.e. hls_proxy.py) will fail.
    """
    cameras = []
    for raw in data:
        camera_id = str(raw["id"])
        match = _GOV_FEED_ID_RE.match(camera_id)
        camera_number = int(match.group(1)) if match else 0
        rtsp_url = (
            f"rtsp://{settings.sandbox_stream_host}:{settings.sandbox_rtsp_port}/stream/{camera_id}"
            if settings.sandbox_stream_host else ""
        )
        webrtc_url = (
            f"http://{settings.sandbox_stream_host}:{settings.sandbox_webrtc_port}/stream/{camera_id}/whep"
            if settings.sandbox_stream_host else ""
        )
        cameras.append(
            CatalogueCamera(
                camera_id=camera_id,
                camera_number=camera_number,
                name=raw.get("name") or camera_id,
                location=raw.get("name") or "",
                codec=None,
                live=True,
                width=None,
                height=None,
                fps=None,
                bitrate_kbps=None,
                rtsp_url=rtsp_url,
                webrtc_url=webrtc_url,
                hls_url=f"{settings.sandbox_browser_base_url}/{camera_id}/index.m3u8",
            )
        )
    return cameras


async def sandbox_login(client: httpx.AsyncClient, settings) -> None:
    """Authenticates `client` against the sandbox's password-gated session
    (see Settings.sandbox_access_password's docstring) -- a no-op, not an
    error, when no password is configured, so a no-auth sandbox is
    unaffected. The resulting cookie lives on `client` itself; callers
    that need it for more than one request (fetch_catalogue, hls_proxy)
    just keep reusing the same client rather than re-authenticating."""
    if not settings.sandbox_access_password:
        return
    resp = await client.post(
        f"{settings.sandbox_browser_base_url}/auth/login",
        data={"password": settings.sandbox_access_password},
    )
    resp.raise_for_status()


async def fetch_catalogue() -> list[CatalogueCamera]:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        await sandbox_login(client, settings)
        resp = await client.get(settings.sandbox_catalogue_url)
        resp.raise_for_status()
        data = resp.json()
    if settings.sandbox_stream_host:
        return parse_gov_feed_catalogue(data, settings)
    return parse_sentinel_default(data, settings.sandbox_browser_base_url)
