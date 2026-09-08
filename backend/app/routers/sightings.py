import asyncio
import csv
import io
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import plate_format
from app.auth_service import (
    AuthContext,
    authorised_departments,
    get_current_auth,
    require_department_access,
    require_worker_token,
)
from app.config import get_settings
from app.db import get_session
from app.models.alert import Alert
from app.models.camera import Camera, Sighting
from app.models.watchlist import WatchlistEntry
from app.schemas import (
    JourneyExportReport,
    JourneyExportStop,
    JourneyStop,
    SightingCreate,
    SightingIngestResult,
    SightingOut,
    VehicleJourney,
)

router = APIRouter()
logger = logging.getLogger(__name__)

EVIDENCE_RETENTION_SWEEP_SECONDS = 3600.0

_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
_jinja_env = Environment(loader=FileSystemLoader(_TEMPLATE_DIR), autoescape=True)

# How long an OPEN alert for the same (plate, watchlist entry) suppresses a
# new one. Not specified anywhere in the spec; chosen as a reasonable default
# and easy to tune here. A resolved/acknowledged alert never suppresses --
# only a still-open one does, so a plate seen again long after review still
# raises fresh attention.
ALERT_DEDUP_WINDOW = timedelta(minutes=15)


@router.post("/sightings", response_model=SightingIngestResult, status_code=201)
async def create_sighting(
    payload: SightingCreate,
    _worker: None = Depends(require_worker_token),
    session: AsyncSession = Depends(get_session),
):
    camera = await session.get(Camera, payload.camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail=f"Camera {payload.camera_id!r} not found")

    normalised = plate_format.normalise(payload.plate) if payload.plate else None

    sighting = Sighting(
        camera_id=payload.camera_id,
        seen_at=payload.seen_at,
        plate=normalised,
        vehicle_type=payload.vehicle_type,
        vehicle_colour=payload.vehicle_colour,
        confidence=payload.confidence,
        frame_pts_ms=payload.frame_pts_ms,
        epoch_id=payload.epoch_id,
        raw_ocr_text=payload.raw_ocr_text,
        bbox=payload.bbox,
        model_version=payload.model_version,
        evidence_path=payload.evidence_path,
    )
    session.add(sighting)
    await session.flush()  # assigns sighting.id without ending the transaction

    # Watchlist matching policy (Section 5 live-test Phase 4), deterministic
    # and fully documented here -- this is the one place a sighting becomes
    # an alert:
    #  1. Exact match on the normalised plate (above) -- no fuzzy matching.
    #  2. Only a CONFIRMED OCR result reaches this endpoint at all: every
    #     caller (observation_worker.py) reports on plate_reader.confirmed()
    #     -- see its module docstring -- so "match only confirmed reads" is
    #     enforced by construction, not re-checked here.
    #  3/4. Below alert_min_confidence, or confidence missing entirely
    #     (ambiguous: a caller that genuinely cannot state a confidence,
    #     e.g. a manual/backfilled sighting) -- the sighting is still
    #     recorded in full, but never raises an alert. Failing closed on an
    #     unknown confidence is the explicit ambiguous-result behaviour: an
    #     operator should never see an alert whose confidence basis is
    #     unstated.
    #  5. Dedup window (ALERT_DEDUP_WINDOW) unchanged -- see its own comment.
    alert_id = None
    settings = get_settings()
    meets_threshold = payload.confidence is not None and payload.confidence >= settings.alert_min_confidence
    if normalised and meets_threshold:
        entries = (
            await session.execute(
                select(WatchlistEntry).where(
                    WatchlistEntry.active.is_(True),
                    WatchlistEntry.normalised_value == normalised,
                )
            )
        ).scalars().all()

        for entry in entries:
            dedup_key = f"{normalised}:{entry.id}"
            recent_cutoff = payload.seen_at - ALERT_DEDUP_WINDOW
            existing_open = (
                await session.execute(
                    select(Alert)
                    .where(
                        Alert.dedup_key == dedup_key,
                        Alert.status == "open",
                        Alert.event_time >= recent_cutoff,
                    )
                    .order_by(Alert.event_time.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if existing_open is not None:
                continue

            alert = Alert(
                sighting_id=sighting.id,
                watchlist_entry_id=entry.id,
                camera_id=payload.camera_id,
                event_time=payload.seen_at,
                match_confidence=payload.confidence,
                dedup_key=dedup_key,
                status="open",
            )
            session.add(alert)
            await session.flush()
            alert_id = alert.id  # last match wins if a plate is on >1 entry (rare)

    await session.commit()
    return SightingIngestResult(sighting_id=sighting.id, matched=alert_id is not None, alert_id=alert_id)


@router.get("/sightings", response_model=list[SightingOut])
async def list_sightings(
    plate: str | None = None,
    camera_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 200,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Sighting).join(Camera, Camera.camera_id == Sighting.camera_id)
    allowed = authorised_departments(auth)
    if allowed is not None:
        stmt = stmt.where(Camera.department.in_(allowed))
    if plate is not None:
        stmt = stmt.where(Sighting.plate == plate_format.normalise(plate))
    if camera_id is not None:
        stmt = stmt.where(Sighting.camera_id == camera_id)
    if since is not None:
        stmt = stmt.where(Sighting.seen_at >= since)
    if until is not None:
        stmt = stmt.where(Sighting.seen_at <= until)
    stmt = stmt.order_by(Sighting.seen_at.desc()).limit(min(limit, 1000))
    return (await session.execute(stmt)).scalars().all()


@router.get("/sightings/{sighting_id}/evidence")
async def get_sighting_evidence(
    sighting_id: int,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    """The evidence crop for one sighting -- mirrors investigate.py's
    get_track_thumb: 404 if the sighting never had evidence, and 404 (not
    500) if retention has already deleted the file out from under a still-
    live evidence_path reference."""
    sighting = await session.get(Sighting, sighting_id)
    if sighting is None:
        raise HTTPException(status_code=404, detail=f"Sighting {sighting_id} not found")
    camera = await session.get(Camera, sighting.camera_id)
    require_department_access(auth, camera.department if camera else None)
    if not sighting.evidence_path:
        raise HTTPException(status_code=404, detail="No evidence recorded for this sighting")
    path = Path(get_settings().evidence_dir) / sighting.evidence_path
    if not path.exists():
        raise HTTPException(status_code=404, detail="Evidence image has expired and is no longer on disk")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/vehicles/{plate}/journey", response_model=VehicleJourney)
async def vehicle_journey(
    plate: str,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    """Ordered, camera-joined movement history for one plate.

    A plate with no sightings is not an error -- returns an empty journey,
    same convention as GET /sightings?plate= returning an empty list.
    """
    normalised = plate_format.normalise(plate)
    stmt = (
        select(Sighting, Camera)
        .join(Camera, Camera.camera_id == Sighting.camera_id)
        .where(Sighting.plate == normalised)
        .order_by(Sighting.seen_at.asc())
    )
    all_rows = (await session.execute(stmt)).all()
    allowed = authorised_departments(auth)
    rows = all_rows if allowed is None else [(s, c) for s, c in all_rows if c.department in allowed]
    restricted = len(all_rows) - len(rows)

    stops: list[JourneyStop] = []
    camera_ids: set[str] = set()
    unplaced = 0
    for sighting, camera in rows:
        camera_ids.add(camera.camera_id)
        if camera.latitude is None or camera.longitude is None:
            unplaced += 1
        stops.append(
            JourneyStop(
                sighting_id=sighting.id,
                camera_id=camera.camera_id,
                camera_name=camera.name,
                location_text=camera.location_text,
                department=camera.department,
                latitude=float(camera.latitude) if camera.latitude is not None else None,
                longitude=float(camera.longitude) if camera.longitude is not None else None,
                geocode_confidence=camera.geocode_confidence,
                seen_at=sighting.seen_at,
                confidence=float(sighting.confidence) if sighting.confidence is not None else None,
                vehicle_type=sighting.vehicle_type,
                epoch_id=sighting.epoch_id,
                has_evidence=sighting.has_evidence,
            )
        )

    return VehicleJourney(
        plate=normalised,
        sighting_count=len(stops),
        camera_count=len(camera_ids),
        first_seen=stops[0].seen_at if stops else None,
        last_seen=stops[-1].seen_at if stops else None,
        stops=stops,
        unplaced_stops=unplaced,
        restricted_stops=restricted,
    )


async def build_journey_export(session: AsyncSession, auth: AuthContext, plate: str) -> JourneyExportReport:
    """Shared by every format the export endpoint serves (JSON/CSV/HTML/PDF)
    -- one query, one authorisation pass, so the reconciliation requirement
    ("JSON, CSV and HTML/PDF contain the same stops and timestamps") holds
    by construction rather than by keeping four code paths in sync by hand.
    """
    normalised = plate_format.normalise(plate)
    stmt = (
        select(Sighting, Camera)
        .join(Camera, Camera.camera_id == Sighting.camera_id)
        .where(Sighting.plate == normalised)
        .order_by(Sighting.seen_at.asc())
    )
    all_rows = (await session.execute(stmt)).all()
    allowed = authorised_departments(auth)
    rows = all_rows if allowed is None else [(s, c) for s, c in all_rows if c.department in allowed]
    restricted = len(all_rows) - len(rows)

    sighting_ids = [s.id for s, _c in rows]
    # Latest alert per sighting -- a plate can in principle match more than
    # one active watchlist entry (create_sighting loops over all matches),
    # so more than one Alert can share a sighting_id; ordering by
    # created_at desc and keeping the first per sighting_id picks the most
    # recent one deterministically rather than an arbitrary row.
    alerts_by_sighting: dict[int, tuple[int, str]] = {}
    if sighting_ids:
        alert_rows = (
            await session.execute(
                select(Alert.sighting_id, Alert.id, Alert.status)
                .where(Alert.sighting_id.in_(sighting_ids))
                .order_by(Alert.sighting_id, Alert.created_at.desc())
            )
        ).all()
        for sighting_id, alert_id, status in alert_rows:
            alerts_by_sighting.setdefault(sighting_id, (alert_id, status))

    stops: list[JourneyExportStop] = []
    camera_ids: set[str] = set()
    unplaced = 0
    for sequence, (sighting, camera) in enumerate(rows, start=1):
        camera_ids.add(camera.camera_id)
        if camera.latitude is None or camera.longitude is None:
            unplaced += 1
        alert_id, alert_status = alerts_by_sighting.get(sighting.id, (None, None))
        stops.append(
            JourneyExportStop(
                sequence=sequence,
                sighting_id=sighting.id,
                camera_id=camera.camera_id,
                camera_name=camera.name,
                department=camera.department,
                location_text=camera.location_text,
                latitude=float(camera.latitude) if camera.latitude is not None else None,
                longitude=float(camera.longitude) if camera.longitude is not None else None,
                geocode_confidence=camera.geocode_confidence,
                seen_at=sighting.seen_at,
                confidence=float(sighting.confidence) if sighting.confidence is not None else None,
                evidence_url=f"/api/sightings/{sighting.id}/evidence" if sighting.has_evidence else None,
                alert_id=alert_id,
                alert_status=alert_status,
            )
        )

    return JourneyExportReport(
        plate=normalised,
        generated_at=datetime.now(timezone.utc),
        sighting_count=len(stops),
        camera_count=len(camera_ids),
        first_seen=stops[0].seen_at if stops else None,
        last_seen=stops[-1].seen_at if stops else None,
        unplaced_stops=unplaced,
        restricted_stops=restricted,
        stops=stops,
    )


@router.get("/vehicles/{plate}/journey/export")
async def vehicle_journey_export(
    plate: str,
    format: str = "json",
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    if format not in {"json", "csv", "html", "pdf"}:
        raise HTTPException(status_code=422, detail="format must be one of json, csv, html, pdf")

    report = await build_journey_export(session, auth, plate)
    date = datetime.now(timezone.utc).date().isoformat()

    if format == "json":
        return Response(
            content=report.model_dump_json(),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="journey-{report.plate}-{date}.json"'},
        )

    if format == "csv":
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow([
            "sequence", "seen_at", "camera_id", "camera_name", "department",
            "location_text", "latitude", "longitude", "geocode_confidence",
            "confidence", "evidence_url", "alert_id", "alert_status",
        ])
        for stop in report.stops:
            # Match Pydantic's own JSON datetime serialisation (trailing Z,
            # not +00:00) so a byte-for-byte diff of the two export formats
            # doesn't false-positive on an aware-datetime formatting choice.
            seen_at_iso = stop.seen_at.isoformat().replace("+00:00", "Z")
            writer.writerow([
                stop.sequence, seen_at_iso, stop.camera_id, stop.camera_name,
                stop.department or "", stop.location_text, stop.latitude, stop.longitude,
                stop.geocode_confidence or "", stop.confidence, stop.evidence_url or "",
                stop.alert_id or "", stop.alert_status or "",
            ])
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="journey-{report.plate}-{date}.csv"'},
        )

    template = _jinja_env.get_template("journey_report.html")
    html = template.render(report=report)
    if format == "html":
        return HTMLResponse(content=html)

    from weasyprint import HTML

    pdf_bytes = HTML(string=html, base_url=_TEMPLATE_DIR).write_pdf()
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="journey-{report.plate}-{date}.pdf"'},
    )


def sweep_expired_evidence_files() -> int:
    """Delete evidence files older than evidence_retention_hours.

    File-only, same split as everything else here: the sightings row
    (and evidence_path itself) is never touched -- has_evidence and the
    GET .../evidence endpoint both key off evidence_path being non-null,
    not off the file being present, so the endpoint's own 404-on-missing
    check is what turns "expired" into an honest answer, not this sweep.
    Runs on the filesystem only (no DB query needed): every evidence file
    is named track-<id>-<seen_at ms>.jpg, so its age is in its own mtime.
    """
    settings = get_settings()
    root = Path(settings.evidence_dir)
    if not root.is_dir():
        return 0
    cutoff = datetime.now(timezone.utc).timestamp() - settings.evidence_retention_hours * 3600
    removed = 0
    for path in root.glob("*/*.jpg"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError as exc:
            logger.warning("evidence retention: could not remove %s: %s", path, exc)
    return removed


async def evidence_retention_loop() -> None:
    """Background sweep, same shape as analytics.supervisor_loop -- runs
    for the lifetime of the app, started from main.py's lifespan."""
    while True:
        try:
            removed = await asyncio.to_thread(sweep_expired_evidence_files)
            if removed:
                logger.info("evidence retention: removed %d expired file(s)", removed)
        except Exception:
            logger.exception("evidence retention sweep failed")
        await asyncio.sleep(EVIDENCE_RETENTION_SWEEP_SECONDS)
