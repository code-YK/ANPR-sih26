"""Investigate: offline forensic search over uploaded recordings.

Vehicle-first (Phase 1): upload a recording, run it through the ANPR
pipeline offline, search by plate. Person search (Phase 2, search_by_person
below) ranks person tracks by a generic appearance embedding
(multi-object-tracking/person_embedding.py) computed at ingest time for
every person track's best crop -- a photo in, ranked candidates out, never
a single asserted match. See PersonSearchHit's docstring for exactly what
that ranking does and does not claim.

Three design points carried over from planning, each backed by reading the
actual tracker source rather than assumed:

  - Ingest run state lives in Postgres, not an in-memory dict like the live
    analytics workers use. A run can take many minutes; it must survive a
    backend restart.
  - Ingest workers are NOT registered in the live workers' manifest
    (`analytics._MANIFEST_PATH`) -- `kill_orphans_from_previous_run` there
    would kill a long ingest on every `uvicorn --reload`.
  - Track results arrive as small POSTed chunks, never one terminal JSON --
    see `IngestChunkPayload` in schemas.py for why.
"""

import asyncio
import base64
import contextlib
import json
import logging
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.auth_service import (
    AuthContext,
    add_audit_event,
    authorised_departments,
    get_current_auth,
    require_department_access,
    require_super_admin,
    require_worker_token,
)
from app.config import get_settings
from app.db import async_session, get_session
from app.models.auth import Department
from app.models.recording import IngestRun, Recording
from app.models.subject import Subject
from app.models.track import Track
from app.pipeline.media import MediaError, normalise_video, parse_frame_rate_fraction, probe_local_file, sha256_file
from app.routers.analytics import _DEFAULT_MODEL, _TRACKER_CONFIG, _WORKER_DIR, _resolve_worker_python
from app.schemas import (
    IngestChunkPayload,
    IngestCompletePayload,
    IngestHeartbeatPayload,
    IngestRunCreate,
    IngestRunOut,
    PersonSearchHit,
    PlateSearchHit,
    PlateSearchQuery,
    RecordingOut,
    RecordingUploadFields,
    SubjectCreate,
    SubjectOut,
    TrackBoxesOut,
    TrackLinkRequest,
    TrackOut,
)

logger = logging.getLogger("sentinel.investigate")

router = APIRouter()

_WORKER_PYTHON = _resolve_worker_python()
_INGEST_SCRIPT = _WORKER_DIR / "recording_ingest_worker.py"
_PERSON_SEARCH_SCRIPT = _WORKER_DIR / "person_search.py"
_LOG_DIR = _WORKER_DIR / "worker_logs"
# Deliberately separate from analytics._MANIFEST_PATH -- see module docstring.
_INGEST_MANIFEST_PATH = _LOG_DIR / "ingest_manifest.json"

_OCCURRENCE_MERGE_GAP_MS = 5000

# Chunk size limits: a rejected-too-large chunk is a worker bug (it should
# already be flushing well under this), so 413 here is a safety net, not
# the primary control.
_MAX_CHUNK_BYTES = 2 * 1024 * 1024
_MAX_CHUNK_TRACKS = 500


# --------------------------------------------------------------------------
# In-process handles for runs this backend process itself spawned. NOT the
# source of truth for status (Postgres is) -- only used to reap exit codes
# and to send a termination signal on cancel. A run started by a since-
# restarted backend process has no entry here; its state is reconciled
# purely from the DB row plus incoming chunk/heartbeat traffic.
# --------------------------------------------------------------------------

@dataclass
class _IngestProc:
    run_id: int
    proc: subprocess.Popen
    log_path: Path


_ingest_procs: dict[int, _IngestProc] = {}


def _save_ingest_manifest() -> None:
    _LOG_DIR.mkdir(exist_ok=True)
    entries = [{"run_id": h.run_id, "pid": h.proc.pid} for h in _ingest_procs.values()]
    _INGEST_MANIFEST_PATH.write_text(json.dumps(entries))


async def reap_stuck_normalising_on_startup() -> None:
    """Called once at backend startup, alongside reconcile_ingest_on_startup.

    Normalisation runs inline inside the upload request (see upload_recording
    below) -- unlike an ingest run, there is no separate subprocess with a PID
    to check for liveness. That makes this reconciliation simpler than the
    ingest one, not riskier: this backend process is the only thing that was
    ever running that normalisation, so if it is starting up now, any row
    still "normalising" belongs to a request that cannot possibly still be in
    flight -- either a previous instance of this same process handled it (and
    is gone), or the ffmpeg it spawned died alongside it (ffmpeg is not
    detached from this process, unlike the government-mode/demo-mode relay
    subprocesses, which are kept alive deliberately). There is no live case
    this could wrongly interrupt.

    Without this, the except clause added for exactly this situation
    (upload_recording's `except Exception`) never runs -- the crash was the
    whole process going down, not a normal exception inside its try block --
    and the row is left saying "normalising" forever, indistinguishable from
    one that is still genuinely in progress.
    """
    async with async_session() as session:
        stuck = (
            await session.execute(select(Recording).where(Recording.status == "normalising"))
        ).scalars().all()
        for recording in stuck:
            recording.status = "rejected"
            recording.reject_reason = (
                "Normalisation did not finish -- the backend restarted or crashed "
                "while this recording was processing. Re-upload to try again."
            )
        if stuck:
            await session.commit()
            logger.info("Reaped %d recording(s) stuck in 'normalising' from a previous run", len(stuck))


async def reconcile_ingest_on_startup() -> None:
    """Called once at backend startup. A manifest entry from a previous
    process is not necessarily dead the way the live-worker manifest's
    entries are -- an ingest run is designed to survive a backend restart.
    So this only fixes up runs whose worker has ALSO died; a still-alive
    worker is left alone and will keep reporting via HTTP once requests
    resume flowing."""
    if not _INGEST_MANIFEST_PATH.exists():
        return
    try:
        entries = json.loads(_INGEST_MANIFEST_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        entries = []

    async with async_session() as session:
        for entry in entries:
            pid = entry.get("pid")
            run_id = entry.get("run_id")
            alive = False
            if isinstance(pid, int):
                try:
                    os.kill(pid, 0)
                    alive = True
                except ProcessLookupError:
                    alive = False
                except PermissionError:
                    alive = True  # exists, owned by someone else -- treat as alive
            if alive:
                continue
            run = await session.get(IngestRun, run_id) if run_id is not None else None
            if run is not None and run.status in ("queued", "running"):
                run.status = "failed"
                run.error = "worker process was not found after a backend restart"
                run.finished_at = datetime.now(timezone.utc)
        await session.commit()

    _INGEST_MANIFEST_PATH.unlink(missing_ok=True)


# --------------------------------------------------------------------------
# Upload
# --------------------------------------------------------------------------

def _content_dir(sha256: str) -> Path:
    return Path(get_settings().recordings_dir) / sha256


async def _finalise_recording(session: AsyncSession, recording: Recording, original_path: Path, settings) -> None:
    """Probe, normalise, and update `recording` in place; commits its own
    transaction. Never raises -- any failure, including a crash inside
    ffmpeg or this process itself, resolves the row to "rejected" rather
    than leaving it on "normalising" with nothing watching it.

    Shared by a fresh upload and a retry of a previously rejected one (see
    upload_recording's `existing.status == "rejected"` branch) so a retry
    genuinely re-runs this step against the same row instead of the caller
    getting back the same dead one a second time.
    """
    try:
        info = await probe_local_file(original_path, timeout_seconds=settings.ffprobe_timeout_seconds)
        fps = parse_frame_rate_fraction(info["r_frame_rate"])
        if fps is None:
            raise MediaError("could not determine a valid frame rate for this file")

        normalised_path = original_path.parent / "normalised.mp4"
        await normalise_video(
            original_path, normalised_path,
            target_fps=fps, timeout_seconds=settings.ffmpeg_normalise_timeout_seconds,
        )
        norm_info = await probe_local_file(normalised_path, timeout_seconds=settings.ffprobe_timeout_seconds)
        norm_fps = parse_frame_rate_fraction(norm_info["r_frame_rate"]) or fps

        recording.normalised_path = str(normalised_path.relative_to(Path(settings.recordings_dir)))
        recording.duration_seconds = norm_info["duration_seconds"]
        recording.fps_num = norm_fps.numerator
        recording.fps_den = norm_fps.denominator
        recording.frame_count = int(norm_info["nb_frames"]) if norm_info.get("nb_frames") else None
        recording.width = norm_info["width"]
        recording.height = norm_info["height"]
        recording.reject_reason = None
        recording.status = "ready"
    except MediaError as exc:
        recording.status = "rejected"
        recording.reject_reason = str(exc)
        logger.info("Recording %s rejected: %s", recording.id, exc)
    except Exception as exc:  # noqa: BLE001 - any crash here must still resolve the row
        # Narrowing this to MediaError left an unhandled exception (backend
        # restart mid-normalise, disk full, a killed ffmpeg) sitting on an
        # await forever: the row had already been committed as "normalising"
        # before this step started, so an unresolved crash here left it stuck
        # in that state permanently -- no error shown, no way to retry, the
        # only fix was reaching into the database by hand. See also the
        # startup reaper (reap_stuck_normalising_on_startup) for the case
        # where the crash was the whole process going down rather than one
        # that reached this except.
        recording.status = "rejected"
        recording.reject_reason = f"Normalisation failed: {exc}"
        logger.exception("Recording %s normalisation crashed", recording.id)

    await session.commit()
    await session.refresh(recording)


@router.post("/investigate/recordings", response_model=RecordingOut, status_code=201)
async def upload_recording(
    request: Request,
    response: Response,
    file: UploadFile,
    department: str,
    camera_id: str | None = None,
    location_text: str | None = None,
    recorded_at: datetime | None = None,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    fields = RecordingUploadFields(
        department=department, camera_id=camera_id, location_text=location_text, recorded_at=recorded_at,
    )
    errors = fields.validate_choices()
    if errors:
        raise HTTPException(status_code=422, detail=errors)

    require_department_access(auth, fields.department, "operator")

    dept_row = await session.get(Department, fields.department)
    if dept_row is None or not dept_row.active:
        raise HTTPException(status_code=422, detail=f"Unknown or inactive department {fields.department!r}")

    settings = get_settings()
    max_bytes = settings.max_upload_mb * 1024 * 1024

    staging_dir = Path(settings.recordings_dir) / "_staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    staging_path = staging_dir / f"{uuid4().hex}.upload"

    size = 0
    try:
        with open(staging_path, "wb") as out:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Upload exceeds the {settings.max_upload_mb} MB limit",
                    )
                out.write(chunk)
    except HTTPException:
        staging_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        staging_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Upload failed: {exc}") from exc

    content_sha256 = await sha256_file(staging_path)

    existing = (
        await session.execute(select(Recording).where(Recording.content_sha256 == content_sha256))
    ).scalar_one_or_none()
    if existing is not None:
        # Identical bytes already known: do not re-ingest, do not create a
        # second row. The caller's department/camera hints for this upload
        # are simply discarded in favour of the recording's original ones.
        staging_path.unlink(missing_ok=True)
        require_department_access(auth, existing.department, "viewer")

        if existing.status == "normalising":
            # A restart can never leave a row here at request time -- the
            # startup reaper (reap_stuck_normalising_on_startup) resolves
            # every one to "rejected" before this process accepts traffic.
            # So a live "normalising" row here means another request for
            # these exact bytes is genuinely in flight right now. Refuse
            # rather than starting a second ffmpeg against the same
            # normalised_path -- concurrent writers to one file corrupt it.
            raise HTTPException(
                status_code=409,
                detail="This recording is still being processed by another request; check back shortly.",
            )

        if existing.status == "rejected":
            # The whole point of reject_reason telling an operator to
            # "re-upload to try again": that must actually retry, not hand
            # back the same dead row a second time. The original bytes are
            # still on disk (this branch never deletes them), so re-run
            # normalisation in place on the existing row instead of the
            # early-return every other status takes.
            content_dir = _content_dir(content_sha256)
            original_path = content_dir / ("original" + Path(existing.original_filename).suffix)
            if not original_path.exists():
                raise HTTPException(
                    status_code=422,
                    detail="The original file for this recording is no longer on disk; it cannot be retried.",
                )
            existing.status = "normalising"
            existing.reject_reason = None
            await session.commit()
            await session.refresh(existing)
            await _finalise_recording(session, existing, original_path, settings)
            response.status_code = 200
            return existing

        response.status_code = 200
        return existing

    content_dir = _content_dir(content_sha256)
    content_dir.mkdir(parents=True, exist_ok=True)
    original_path = content_dir / ("original" + Path(file.filename or "").suffix)
    staging_path.rename(original_path)

    recording = Recording(
        original_filename=file.filename or "upload",
        content_sha256=content_sha256,
        content_type=file.content_type,
        size_bytes=size,
        department=fields.department,
        camera_id=fields.camera_id,
        location_text=fields.location_text,
        recorded_at=fields.recorded_at,
        status="normalising",
        uploaded_by=auth.user.id,
    )
    session.add(recording)
    await session.flush()

    add_audit_event(
        session, actor=auth.user, action="recording.uploaded", target_type="recording",
        target_id=recording.id, department=fields.department, result="success",
        details={"original_filename": recording.original_filename, "size_bytes": size},
    )
    await session.commit()
    await session.refresh(recording)

    await _finalise_recording(session, recording, original_path, settings)
    return recording


# --------------------------------------------------------------------------
# Recordings CRUD
# --------------------------------------------------------------------------

@router.get("/investigate/recordings", response_model=list[RecordingOut])
async def list_recordings(
    status: str | None = None,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Recording).order_by(Recording.created_at.desc())
    allowed = authorised_departments(auth)
    if allowed is not None:
        stmt = stmt.where(Recording.department.in_(allowed))
    if status is not None:
        stmt = stmt.where(Recording.status == status)
    return (await session.execute(stmt)).scalars().all()


async def _get_authorised_recording(
    session: AsyncSession, auth: AuthContext, recording_id: int, clearance: str = "viewer",
) -> Recording:
    recording = await session.get(Recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail=f"Recording {recording_id} not found")
    require_department_access(auth, recording.department, clearance)
    return recording


@router.get("/investigate/recordings/{recording_id}", response_model=RecordingOut)
async def get_recording(
    recording_id: int,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    return await _get_authorised_recording(session, auth, recording_id)


@router.delete("/investigate/recordings/{recording_id}", status_code=204)
async def delete_recording(
    recording_id: int,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    recording = await _get_authorised_recording(session, auth, recording_id, "operator")
    if not (auth.is_super_admin or (auth.is_department_admin and auth.user.home_department == recording.department)):
        raise HTTPException(status_code=403, detail="Recording deletion requires department admin or super admin")

    content_dir = _content_dir(recording.content_sha256)
    department = recording.department
    await session.delete(recording)
    add_audit_event(
        session, actor=auth.user, action="recording.deleted", target_type="recording",
        target_id=recording_id, department=department, result="success",
    )
    await session.commit()

    import shutil
    shutil.rmtree(content_dir, ignore_errors=True)
    return None


@router.get("/investigate/recordings/{recording_id}/media")
async def get_recording_media(
    recording_id: int,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    recording = await _get_authorised_recording(session, auth, recording_id)
    if not recording.normalised_path:
        raise HTTPException(status_code=404, detail="This recording has no playable media (not yet normalised)")
    path = Path(get_settings().recordings_dir) / recording.normalised_path
    if not path.exists():
        raise HTTPException(status_code=404, detail="Media file missing on disk")
    # FileResponse already sets accept-ranges/handles 206 (Starlette 0.41),
    # so seeking works with no custom Range code here.
    return FileResponse(path, media_type="video/mp4")


# --------------------------------------------------------------------------
# Ingest runs: enqueue, status, cancel
# --------------------------------------------------------------------------

async def _queue_position(session: AsyncSession, run: IngestRun) -> int | None:
    if run.status != "queued":
        return None
    ahead = (
        await session.execute(
            select(func.count()).select_from(IngestRun)
            .where(IngestRun.status == "queued", IngestRun.created_at < run.created_at)
        )
    ).scalar_one()
    return ahead + 1


async def _run_out(session: AsyncSession, run: IngestRun) -> IngestRunOut:
    out = IngestRunOut.model_validate(run)
    out.queue_position = await _queue_position(session, run)
    return out


@router.post("/investigate/recordings/{recording_id}/runs", response_model=IngestRunOut, status_code=201)
async def create_ingest_run(
    recording_id: int,
    payload: IngestRunCreate,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    errors = payload.validate_choices()
    if errors:
        raise HTTPException(status_code=422, detail=errors)

    recording = await _get_authorised_recording(session, auth, recording_id, "operator")
    if recording.status != "ready":
        raise HTTPException(status_code=409, detail=f"Recording is {recording.status!r}, not ready for ingest")

    run = IngestRun(
        recording_id=recording.id,
        kind=payload.kind,
        model=payload.model or _DEFAULT_MODEL[payload.kind],
        tracker_config=_TRACKER_CONFIG[payload.kind],
        imgsz=payload.imgsz or 960,
        # Stride 1 by default -- deliberately. TRACKTRACK hard-gates
        # association on IoU (cost[~supported]=1.0 for iou<0.10) AFTER the
        # appearance term, so a strided run's larger inter-frame displacement
        # makes fast-moving objects unmatchable regardless of ReID. Get
        # throughput from imgsz/model instead; see docs/investigate-testing.md.
        frame_stride=1,
        status="queued",
        created_by=auth.user.id,
    )
    session.add(run)
    add_audit_event(
        session, actor=auth.user, action="ingest.enqueued", target_type="ingest_run",
        target_id=None, department=recording.department, result="success",
        details={"recording_id": recording.id, "kind": payload.kind},
    )
    await session.commit()
    await session.refresh(run)
    add_audit_event(
        session, actor=auth.user, action="ingest.enqueued", target_type="ingest_run",
        target_id=run.id, department=recording.department, result="success",
    )
    await session.commit()
    return await _run_out(session, run)


@router.get("/investigate/recordings/{recording_id}/runs", response_model=list[IngestRunOut])
async def list_ingest_runs(
    recording_id: int,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    """Lets a reloaded page recover "what run is/was active for this
    recording" -- otherwise that state only ever existed in the browser's
    memory of the id returned by the enqueue call."""
    await _get_authorised_recording(session, auth, recording_id)
    runs = (
        await session.execute(
            select(IngestRun).where(IngestRun.recording_id == recording_id).order_by(IngestRun.created_at.desc())
        )
    ).scalars().all()
    return [await _run_out(session, run) for run in runs]


async def _get_authorised_run(
    session: AsyncSession, auth: AuthContext, run_id: int, clearance: str = "viewer",
) -> tuple[IngestRun, Recording]:
    run = await session.get(IngestRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Ingest run {run_id} not found")
    recording = await session.get(Recording, run.recording_id)
    require_department_access(auth, recording.department if recording else None, clearance)
    return run, recording


@router.get("/investigate/runs/{run_id}", response_model=IngestRunOut)
async def get_ingest_run(
    run_id: int,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    run, _recording = await _get_authorised_run(session, auth, run_id)
    return await _run_out(session, run)


@router.post("/investigate/runs/{run_id}/cancel", response_model=IngestRunOut)
async def cancel_ingest_run(
    run_id: int,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    run, recording = await _get_authorised_run(session, auth, run_id, "operator")
    if run.status not in ("queued", "running"):
        raise HTTPException(status_code=409, detail=f"Run is {run.status!r}, cannot cancel")

    handle = _ingest_procs.pop(run_id, None)
    if handle is not None:
        handle.proc.terminate()
        try:
            handle.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            handle.proc.kill()
        _save_ingest_manifest()

    run.status = "cancelled"
    run.finished_at = datetime.now(timezone.utc)
    add_audit_event(
        session, actor=auth.user, action="ingest.cancelled", target_type="ingest_run",
        target_id=run_id, department=recording.department if recording else None, result="success",
    )
    await session.commit()
    return await _run_out(session, run)


# --------------------------------------------------------------------------
# Ingest results: worker-token only, no AuthContext (matches POST /sightings)
# --------------------------------------------------------------------------

def _merge_occurrences(existing_last_ms_by_occurrence: dict[int, int], new_first_ms: int, next_index: int) -> tuple[int, int]:
    """Given the last-seen ms of every occurrence so far, decide whether
    `new_first_ms` continues one of them (gap under the merge threshold) or
    starts a new occurrence. Returns (occurrence_index, next_index)."""
    for occ_index, last_ms in existing_last_ms_by_occurrence.items():
        if 0 <= new_first_ms - last_ms <= _OCCURRENCE_MERGE_GAP_MS:
            return occ_index, next_index
    return next_index, next_index + 1


@router.post("/investigate/runs/{run_id}/chunk", status_code=204)
async def post_ingest_chunk(
    run_id: int,
    payload: IngestChunkPayload,
    _worker: None = Depends(require_worker_token),
    session: AsyncSession = Depends(get_session),
):
    body_size = len(json.dumps(payload.model_dump()).encode())
    if body_size > _MAX_CHUNK_BYTES or len(payload.tracks) > _MAX_CHUNK_TRACKS:
        raise HTTPException(status_code=413, detail="Chunk too large; the worker should flush more often")

    run = await session.get(IngestRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Ingest run {run_id} not found")
    if run.status not in ("running", "queued"):
        # A cancelled/failed run's worker may still be mid-flush; accept and
        # drop rather than error, so the worker doesn't retry forever.
        return None

    # seq-idempotent: replaying the same chunk (after a network hiccup on
    # the worker's side) must never duplicate rows. Composite PK on
    # (run_id, track_ref) already gives us that for free via ON CONFLICT.
    existing_occurrences = dict(
        (
            await session.execute(
                select(Track.occurrence_index, func.max(Track.last_ms))
                .where(Track.run_id == run_id)
                .group_by(Track.occurrence_index)
            )
        ).all()
    )
    next_occ = (max(existing_occurrences) + 1) if existing_occurrences else 0

    from sqlalchemy.dialects.postgresql import insert as pg_insert

    for t in payload.tracks:
        occ_index, next_occ = _merge_occurrences(existing_occurrences, t.first_ms, next_occ)
        existing_occurrences[occ_index] = t.last_ms

        stmt = pg_insert(Track).values(
            run_id=run_id,
            track_ref=t.track_ref,
            recording_id=run.recording_id,
            kind=t.kind,
            occurrence_index=occ_index,
            first_frame=t.first_frame,
            last_frame=t.last_frame,
            first_ms=t.first_ms,
            last_ms=t.last_ms,
            frame_count=t.frame_count,
            best_conf=t.best_conf,
            boxes=t.boxes.model_dump(),
            thumb_path=t.thumb_path,
            plate_confirmed=t.plate_confirmed,
            plate_tentative=t.plate_tentative,
            plate_confidence=t.plate_confidence,
            plate_votes=t.plate_votes,
            embedding=base64.b64decode(t.embedding) if t.embedding else None,
            embedding_dim=t.embedding_dim,
            embedding_model=t.embedding_model,
        ).on_conflict_do_nothing(index_elements=["run_id", "track_ref"])
        await session.execute(stmt)

    run.chunk_count_received += 1
    run.track_count = (
        await session.execute(select(func.count()).select_from(Track).where(Track.run_id == run_id))
    ).scalar_one()
    run.last_heartbeat_at = datetime.now(timezone.utc)
    run.status = "running"
    if run.started_at is None:
        run.started_at = datetime.now(timezone.utc)

    await session.commit()
    return None


@router.post("/investigate/runs/{run_id}/heartbeat", status_code=204)
async def post_ingest_heartbeat(
    run_id: int,
    payload: IngestHeartbeatPayload,
    _worker: None = Depends(require_worker_token),
    session: AsyncSession = Depends(get_session),
):
    run = await session.get(IngestRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Ingest run {run_id} not found")
    if run.status not in ("queued", "running"):
        return None

    run.status = "running"
    if run.started_at is None:
        run.started_at = datetime.now(timezone.utc)
    run.frames_processed = payload.frames_processed
    run.frames_expected = payload.frames_expected
    run.last_heartbeat_at = datetime.now(timezone.utc)
    if payload.frames_expected:
        run.progress_pct = min(100.0, 100.0 * payload.frames_processed / payload.frames_expected)
    await session.commit()
    return None


@router.post("/investigate/runs/{run_id}/complete", response_model=IngestRunOut)
async def complete_ingest_run(
    run_id: int,
    payload: IngestCompletePayload,
    _worker: None = Depends(require_worker_token),
    session: AsyncSession = Depends(get_session),
):
    run = await session.get(IngestRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Ingest run {run_id} not found")

    run.frames_processed = payload.frames_processed
    run.chunk_count_expected = payload.chunk_count
    run.finished_at = datetime.now(timezone.utc)
    run.progress_pct = 100.0

    if payload.error:
        run.status = "failed"
        run.error = payload.error
    elif run.chunk_count_received != payload.chunk_count:
        run.status = "completed_partial"
        run.error = (
            f"Expected {payload.chunk_count} chunks, received {run.chunk_count_received}. "
            "Some tracks from this run were likely lost in transit."
        )
    else:
        run.status = "completed"

    await session.commit()
    await session.refresh(run)

    handle = _ingest_procs.pop(run_id, None)
    if handle is not None:
        _save_ingest_manifest()

    recording = await session.get(Recording, run.recording_id)
    add_audit_event(
        session, action="ingest.completed", target_type="ingest_run", target_id=run_id,
        department=recording.department if recording else None, result=run.status,
        details={"track_count": run.track_count, "chunk_count_received": run.chunk_count_received},
    )
    await session.commit()
    return await _run_out(session, run)


# --------------------------------------------------------------------------
# Tracks: boxes (deferred), thumbnail, linking
# --------------------------------------------------------------------------

@router.get("/investigate/runs/{run_id}/tracks", response_model=list[TrackOut])
async def list_tracks(
    run_id: int,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    await _get_authorised_run(session, auth, run_id)
    # Explicit column list, never `select(Track)` -- `boxes`/`embedding` are
    # `deferred()` on the model precisely so a list endpoint like this one
    # never drags a full timeline along for every row.
    cols = [c for c in Track.__table__.columns if c.name not in ("boxes", "embedding")]
    rows = (await session.execute(select(*cols).where(Track.run_id == run_id))).all()
    return [TrackOut.model_validate(dict(r._mapping)) for r in rows]


async def _get_track(session: AsyncSession, auth: AuthContext, run_id: int, track_ref: int, clearance="viewer") -> Track:
    await _get_authorised_run(session, auth, run_id, clearance)
    track = await session.get(Track, {"run_id": run_id, "track_ref": track_ref})
    if track is None:
        raise HTTPException(status_code=404, detail="Track not found")
    return track


@router.get("/investigate/runs/{run_id}/tracks/{track_ref}/boxes", response_model=TrackBoxesOut)
async def get_track_boxes(
    run_id: int,
    track_ref: int,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    await _get_authorised_run(session, auth, run_id)
    # Explicit column select, not `session.get(Track, ...)` then `.boxes` --
    # `deferred()` disables IMPLICIT lazy loading under AsyncSession (there
    # is no synchronous context for it to run in), so touching the
    # attribute on an already-fetched object raises MissingGreenlet. This is
    # exactly the "never `select(Track)`" rule list_tracks already follows,
    # applied the other way: here we want ONLY the deferred column.
    boxes = (
        await session.execute(
            select(Track.boxes).where(Track.run_id == run_id, Track.track_ref == track_ref)
        )
    ).scalar_one_or_none()
    if not boxes:
        raise HTTPException(status_code=404, detail="Track not found or has no recorded timeline")
    return boxes


@router.get("/investigate/runs/{run_id}/tracks/{track_ref}/thumb")
async def get_track_thumb(
    run_id: int,
    track_ref: int,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    track = await _get_track(session, auth, run_id, track_ref)
    if not track.thumb_path:
        raise HTTPException(status_code=404, detail="No thumbnail for this track")
    path = Path(get_settings().recordings_dir) / track.thumb_path
    if not path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail missing on disk")
    # A track's crop never changes. `private` keeps it out of shared caches;
    # the short max-age spares a results page re-authenticating dozens of
    # thumbnails every time it re-renders.
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=600"})


@router.post("/investigate/runs/{run_id}/tracks/{track_ref}/link", response_model=TrackOut)
async def link_track_to_subject(
    run_id: int,
    track_ref: int,
    payload: TrackLinkRequest,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    track = await _get_track(session, auth, run_id, track_ref, "operator")
    subject = await session.get(Subject, payload.subject_id)
    if subject is None:
        raise HTTPException(status_code=404, detail="Subject not found")

    track.subject_id = subject.id
    track.link_method = "operator_confirmed"
    track.link_score = None

    add_audit_event(
        session, actor=auth.user, action="track.linked", target_type="track",
        target_id=f"{run_id}:{track_ref}", department=None, result="success",
        details={"subject_id": subject.id},
    )
    await session.commit()
    await session.refresh(track)
    return TrackOut.model_validate(track, from_attributes=True)


# --------------------------------------------------------------------------
# Subjects
# --------------------------------------------------------------------------

@router.post("/investigate/subjects", response_model=SubjectOut, status_code=201)
async def create_subject(
    payload: SubjectCreate,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    errors = payload.validate_choices()
    if errors:
        raise HTTPException(status_code=422, detail=errors)

    subject = Subject(
        kind=payload.kind, label=payload.label, plate=payload.plate,
        notes=payload.notes, created_by=auth.user.id,
    )
    session.add(subject)
    await session.flush()
    add_audit_event(
        session, actor=auth.user, action="subject.created", target_type="subject",
        target_id=subject.id, department=None, result="success",
    )
    await session.commit()
    await session.refresh(subject)
    return subject


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------

@router.post("/investigate/search/plate", response_model=list[PlateSearchHit])
async def search_by_plate(
    payload: PlateSearchQuery,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    from app.plate_format import normalise as normalise_plate

    errors = payload.validate_choices()
    if errors:
        raise HTTPException(status_code=422, detail=errors)

    query_plate = normalise_plate(payload.plate)

    stmt = select(Track, Recording).join(Recording, Recording.id == Track.recording_id)
    allowed = authorised_departments(auth)
    if allowed is not None:
        stmt = stmt.where(Recording.department.in_(allowed))

    if payload.fuzzy:
        stmt = stmt.where(
            or_(
                func.similarity(Track.plate_confirmed, query_plate) > 0.4,
                func.similarity(Track.plate_tentative, query_plate) > 0.4,
                Track.plate_confirmed == query_plate,
                Track.plate_tentative == query_plate,
            )
        ).order_by(
            func.greatest(
                func.similarity(func.coalesce(Track.plate_confirmed, ""), query_plate),
                func.similarity(func.coalesce(Track.plate_tentative, ""), query_plate),
            ).desc()
        )
    else:
        stmt = stmt.where(or_(Track.plate_confirmed == query_plate, Track.plate_tentative == query_plate))

    stmt = stmt.limit(payload.limit)
    rows = (await session.execute(stmt)).all()

    add_audit_event(
        session, actor=auth.user, action="investigation.searched", target_type="search",
        target_id=None, department=None, result="success",
        details={"kind": "plate", "query": query_plate, "fuzzy": payload.fuzzy, "hits": len(rows)},
    )
    await session.commit()

    hits = []
    for track, recording in rows:
        matched = track.plate_confirmed if track.plate_confirmed == query_plate else (
            track.plate_tentative if track.plate_tentative == query_plate else
            (track.plate_confirmed or track.plate_tentative)
        )
        hits.append(PlateSearchHit(
            track=TrackOut.model_validate(
                {c.name: getattr(track, c.name) for c in Track.__table__.columns if c.name not in ("boxes", "embedding")}
            ),
            recording=RecordingOut.model_validate(recording, from_attributes=True),
            matched_plate=matched or "",
            match_kind="exact" if matched == query_plate else "fuzzy",
        ))
    return hits


@router.post("/investigate/search/person", response_model=list[PersonSearchHit])
async def search_by_person(
    file: UploadFile,
    limit: int = 50,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    """Upload a person photo; ranks every person track with a stored
    embedding by cosine similarity to it (both sides L2-normalised at
    embed time, so this is a plain dot product). See PersonSearchHit's
    docstring for what a high score does and does not mean -- this is
    appearance similarity from a generic model, not a verified identity
    match, and the response is ranked, not filtered to "the" answer.
    """
    if not _WORKER_PYTHON.exists() or not _PERSON_SEARCH_SCRIPT.exists():
        raise HTTPException(status_code=503, detail="Person-embedding worker not available")

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=422, detail="Empty file")

    # delete=False + an explicit close before the subprocess runs, rather than
    # the obvious `with NamedTemporaryFile(...) as tmp:` around it. On Windows
    # NamedTemporaryFile holds the file open with exclusive sharing, so while
    # this process still has the handle, person_search.py cannot open the same
    # path and dies with "PermissionError: [Errno 13] Permission denied".
    # POSIX allows the concurrent open, which is why the original form worked
    # on the machine this was written on and failed on every Windows box.
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    try:
        tmp.write(image_bytes)
        tmp.close()
        proc = await asyncio.to_thread(
            subprocess.run,
            [str(_WORKER_PYTHON), str(_PERSON_SEARCH_SCRIPT), "--image", tmp.name],
            cwd=str(_WORKER_DIR), capture_output=True, text=True, timeout=60,
        )
    finally:
        # delete=False means nothing else will: the query photo is the
        # operator's own upload and must not outlive the request.
        with contextlib.suppress(OSError):
            os.unlink(tmp.name)

    stdout_lines = proc.stdout.strip().splitlines()
    try:
        result = json.loads(stdout_lines[-1]) if stdout_lines else {}
    except json.JSONDecodeError:
        result = {}
    if proc.returncode != 0 or "error" in result:
        detail = result.get("error") or proc.stderr[-300:] or "embedding worker produced no output"
        raise HTTPException(status_code=422, detail=f"Could not read a query embedding from this image: {detail}")

    query_vec = np.frombuffer(base64.b64decode(result["embedding"]), dtype=np.float32)

    stmt = (
        select(Track, Recording)
        .join(Recording, Recording.id == Track.recording_id)
        .options(undefer(Track.embedding))
        .where(Track.kind == "person", Track.embedding.is_not(None))
    )
    allowed = authorised_departments(auth)
    if allowed is not None:
        stmt = stmt.where(Recording.department.in_(allowed))
    rows = (await session.execute(stmt)).all()

    scored = []
    for track, recording in rows:
        vec = np.frombuffer(track.embedding, dtype=np.float32)
        if vec.shape != query_vec.shape:
            # A stored embedding from a since-changed model shape -- skip
            # rather than crash the whole search over one stale row.
            continue
        scored.append((float(np.dot(vec, query_vec)), track, recording))
    scored.sort(key=lambda row: row[0], reverse=True)
    top = scored[:limit]

    add_audit_event(
        session, actor=auth.user, action="investigation.searched", target_type="search",
        target_id=None, department=None, result="success",
        details={"kind": "person", "candidates": len(rows), "hits": len(top)},
    )
    await session.commit()

    return [
        PersonSearchHit(
            track=TrackOut.model_validate(
                {c.name: getattr(track, c.name) for c in Track.__table__.columns if c.name not in ("boxes", "embedding")}
            ),
            recording=RecordingOut.model_validate(recording, from_attributes=True),
            similarity=similarity,
        )
        for similarity, track, recording in top
    ]


# --------------------------------------------------------------------------
# Supervisor: queue promotion, heartbeat reaping. Its own loop, separate
# from analytics.supervisor_loop -- a different concurrency domain (offline
# batch jobs vs. live per-camera workers), and keeping them apart means a
# bug in one loop can't affect the other's cadence.
# --------------------------------------------------------------------------

SUPERVISOR_INTERVAL_SECONDS = 10.0


async def _spawn_ingest_worker(run: IngestRun, recording: Recording) -> None:
    if not _WORKER_PYTHON.exists() or not _INGEST_SCRIPT.exists():
        raise RuntimeError(f"Ingest worker not found at {_INGEST_SCRIPT} using {_WORKER_PYTHON}")

    settings = get_settings()
    _LOG_DIR.mkdir(exist_ok=True)
    log_path = _LOG_DIR / f"ingest-run-{run.id}.log"
    log_file = open(log_path, "ab")

    # Absolute, deliberately: this subprocess is spawned with cwd=_WORKER_DIR
    # (multi-object-tracking/), not the backend's own working directory, so
    # settings.recordings_dir's relative path would otherwise resolve
    # against the wrong directory entirely.
    media_path = (Path(settings.recordings_dir) / recording.normalised_path).resolve()

    worker_args = [
        str(_WORKER_PYTHON), "-u", str(_INGEST_SCRIPT),
        "--run-id", str(run.id),
        "--video-path", str(media_path),
        "--report-to", settings.backend_base_url,
        "--kind", run.kind,
        "--model", run.model,
        "--tracker", run.tracker_config,
        "--imgsz", str(run.imgsz),
        "--frame-stride", str(run.frame_stride),
    ]
    worker_env = os.environ.copy()
    if settings.worker_api_token:
        worker_env["SENTINEL_WORKER_API_TOKEN"] = settings.worker_api_token

    proc = subprocess.Popen(
        worker_args, cwd=str(_WORKER_DIR),
        stdout=log_file, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        env=worker_env,
    )
    log_file.close()

    run.pid = proc.pid
    run.worker_started_at = datetime.now(timezone.utc)
    run.last_heartbeat_at = run.worker_started_at
    run.status = "running"
    run.started_at = run.worker_started_at

    _ingest_procs[run.id] = _IngestProc(run_id=run.id, proc=proc, log_path=log_path)
    _save_ingest_manifest()


async def ingest_supervisor_tick() -> None:
    settings = get_settings()
    now = datetime.now(timezone.utc)

    # 1. Reap processes that exited without ever calling /complete.
    for run_id in [rid for rid, h in _ingest_procs.items() if h.proc.poll() is not None]:
        handle = _ingest_procs.pop(run_id)
        _save_ingest_manifest()
        async with async_session() as session:
            run = await session.get(IngestRun, run_id)
            if run is not None and run.status in ("queued", "running"):
                run.status = "failed"
                run.error = f"Worker process exited unexpectedly (code {handle.proc.returncode})"
                run.finished_at = now
                await session.commit()

    async with async_session() as session:
        # 2. Heartbeat staleness -> stalled.
        cutoff = now.timestamp() - settings.ingest_heartbeat_stale_seconds
        stale_runs = (
            await session.execute(
                select(IngestRun).where(
                    IngestRun.status == "running",
                    or_(
                        IngestRun.last_heartbeat_at.is_(None),
                        func.extract("epoch", IngestRun.last_heartbeat_at) < cutoff,
                    ),
                )
            )
        ).scalars().all()
        for run in stale_runs:
            run.status = "stalled"
            run.error = "No progress or heartbeat from the worker within the stall timeout"
            run.finished_at = now
            _ingest_procs.pop(run.id, None)
        if stale_runs:
            await session.commit()

        # 3. Promote queued runs up to the concurrency cap.
        running_count = (
            await session.execute(select(func.count()).select_from(IngestRun).where(IngestRun.status == "running"))
        ).scalar_one()
        budget = settings.max_concurrent_ingest_workers - running_count
        if budget <= 0:
            return

        queued = (
            await session.execute(
                select(IngestRun).where(IngestRun.status == "queued").order_by(IngestRun.created_at).limit(budget)
            )
        ).scalars().all()
        for run in queued:
            recording = await session.get(Recording, run.recording_id)
            if recording is None or recording.status != "ready":
                run.status = "failed"
                run.error = "Recording is no longer ready for ingest"
                run.finished_at = now
                continue
            try:
                await _spawn_ingest_worker(run, recording)
                logger.info("Started ingest run %s for recording %s", run.id, run.recording_id)
            except Exception as exc:  # noqa: BLE001 - one run's failure must not stop the tick
                run.status = "failed"
                run.error = str(exc)
                run.finished_at = now
                logger.warning("Failed to start ingest run %s: %s", run.id, exc)
        await session.commit()


async def ingest_supervisor_loop() -> None:
    while True:
        try:
            await ingest_supervisor_tick()
        except Exception:  # noqa: BLE001 - the loop must survive a bad tick
            logger.exception("Ingest supervisor tick failed")
        await asyncio.sleep(SUPERVISOR_INTERVAL_SECONDS)
