"""Named, credentialed catalogue sources -- multi-source camera onboarding.

The original single-source sync (app/pipeline/sync.py's run_catalogue_sync,
against settings.sandbox_catalogue_url) is untouched by this module and
stays the one thing GOV-ING-001 actually requires. This is purely additive:
a super admin registers a named source (see routers/catalogue_sources.py),
and this module knows how to validate its URL and run a read-only sync
against it, keeping clear provenance on every camera it creates.

Camera IDs from a source are namespaced `src{source.id}-{raw_id}` --
guaranteed disjoint from the legacy sync's bare catalogue ids, from
`manual-<n>` onboarding, and from every other source, by construction
(two different customer catalogues could easily both use small integers).
"""

import ipaddress
import logging
import socket
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.camera import Camera
from app.models.catalogue_source import CatalogueSource
from app.pipeline.catalogue import parse_sentinel_default
from app.schemas import SyncResult

logger = logging.getLogger("sentinel.pipeline.catalogue_sources")

# One entry per adapter name, each a callable(data, browser_base_url) ->
# list[CatalogueCamera]. Extend this and CatalogueSource.ADAPTERS (and the
# DB check constraint) together -- never accept an adapter string that
# isn't a real, tested parser.
ADAPTERS = {
    "sentinel_default": parse_sentinel_default,
}

_CATALOGUE_COLUMNS = (
    "camera_number",
    "name",
    "location_text",
    "rtsp_url",
    "hls_url",
    "webrtc_url",
    "is_live",
    "source_id",
)


class InvalidSourceUrl(ValueError):
    pass


def validate_base_url(base_url: str, allow_private_host: bool) -> None:
    """Registering a source (and triggering its sync) is already
    super-admin-only, which is most of the SSRF mitigation -- this is not a
    caller-supplied-URL-per-request feature. On top of that: the scheme
    must be http(s), and unless the source explicitly opts in (needed for
    this project's own local-synthetic-catalogue testing, the same pattern
    the WebRTC relay's own testing already established), every resolved
    address for the host must not be loopback/private/link-local.
    """
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https"):
        raise InvalidSourceUrl(f"base_url must be http:// or https://, got {parsed.scheme!r}")
    if not parsed.hostname:
        raise InvalidSourceUrl("base_url has no host")
    if allow_private_host:
        return

    try:
        addrinfo = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise InvalidSourceUrl(f"could not resolve host {parsed.hostname!r}: {exc}") from exc

    for family, _type, _proto, _canon, sockaddr in addrinfo:
        ip = ipaddress.ip_address(sockaddr[0])
        if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved:
            raise InvalidSourceUrl(
                f"{parsed.hostname!r} resolves to {ip}, a non-public address -- "
                "set allow_private_host to register a local/test source anyway"
            )


async def run_source_sync(session: AsyncSession, source: CatalogueSource) -> SyncResult:
    parser = ADAPTERS[source.adapter]  # validated at create/update time; a stale bad value would be a bug, not user input
    headers = {}
    if source.auth_header_name and source.auth_secret:
        headers[source.auth_header_name] = source.auth_secret

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(source.base_url, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    cameras = parser(data, source.browser_base_url or "")

    # Scoped to this source only -- one source's absence list must never
    # mention another source's cameras, the legacy sync's, or manual ones.
    existing_ids = set(
        (await session.execute(select(Camera.camera_id).where(Camera.source_id == source.id))).scalars().all()
    )
    fetched_ids = {f"src{source.id}-{cam.camera_id}" for cam in cameras}

    inserted = 0
    updated = 0
    for cam in cameras:
        camera_id = f"src{source.id}-{cam.camera_id}"
        values = dict(
            camera_id=camera_id,
            camera_number=cam.camera_number,
            name=cam.name,
            location_text=cam.location,
            rtsp_url=cam.rtsp_url,
            hls_url=cam.hls_url,
            webrtc_url=cam.webrtc_url,
            is_live=cam.live,
            source_id=source.id,
        )
        stmt = insert(Camera).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Camera.camera_id],
            set_={col: getattr(stmt.excluded, col) for col in _CATALOGUE_COLUMNS},
        )
        await session.execute(stmt)
        if camera_id in existing_ids:
            updated += 1
        else:
            inserted += 1

    disappeared = sorted(existing_ids - fetched_ids)
    if disappeared:
        logger.warning(
            "catalogue source %r sync: %d camera(s) no longer present (rows retained): %s",
            source.name, len(disappeared), ", ".join(disappeared),
        )

    result = SyncResult(fetched=len(cameras), inserted=inserted, updated=updated, disappeared=disappeared)
    source.last_sync_result = result.model_dump()
    source.last_synced_at = datetime.now(timezone.utc)

    await session.commit()
    return result
