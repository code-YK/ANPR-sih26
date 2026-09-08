"""Stage 1 -- catalogue sync.

Fetches /api/ingest and upserts every camera, idempotent on camera_id.
Populates only the catalogue-sourced columns plus is_live; never touches
probe results, survey verdicts, geocoding, or operator-supplied fields.
Cameras that disappear from the catalogue are logged, never deleted --
the registry is the durable record even for a currently-absent camera.
"""

import logging

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.camera import Camera
from app.pipeline.catalogue import fetch_catalogue
from app.schemas import SyncResult

logger = logging.getLogger("sentinel.pipeline.sync")

_CATALOGUE_COLUMNS = (
    "camera_number",
    "name",
    "location_text",
    "rtsp_url",
    "hls_url",
    "webrtc_url",
    "is_live",
)


async def run_catalogue_sync(session: AsyncSession) -> SyncResult:
    cameras = await fetch_catalogue()

    existing_ids = set((await session.execute(select(Camera.camera_id))).scalars().all())
    # Manually-registered cameras (see routers/cameras.py) were never in the
    # catalogue to begin with -- they're not "disappeared", they just aren't
    # this connector's concern.
    existing_ids = {cid for cid in existing_ids if not cid.startswith("manual-")}
    fetched_ids = {c.camera_id for c in cameras}

    inserted = 0
    updated = 0

    for cam in cameras:
        values = dict(
            camera_id=cam.camera_id,
            camera_number=cam.camera_number,
            name=cam.name,
            location_text=cam.location,
            rtsp_url=cam.rtsp_url,
            hls_url=cam.hls_url,
            webrtc_url=cam.webrtc_url,
            is_live=cam.live,
        )
        stmt = insert(Camera).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Camera.camera_id],
            set_={col: getattr(stmt.excluded, col) for col in _CATALOGUE_COLUMNS},
        )
        await session.execute(stmt)
        if cam.camera_id in existing_ids:
            updated += 1
        else:
            inserted += 1

    disappeared = sorted(existing_ids - fetched_ids)
    if disappeared:
        logger.warning(
            "catalogue sync: %d camera(s) no longer present in the catalogue (rows retained): %s",
            len(disappeared),
            ", ".join(disappeared),
        )

    await session.commit()

    return SyncResult(
        fetched=len(cameras),
        inserted=inserted,
        updated=updated,
        disappeared=disappeared,
    )
