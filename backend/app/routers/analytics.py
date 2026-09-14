"""Start/stop/status control for the analytics workers (ANPR "vehicle" mode,
"vehicle_finetuned" for the fine-tuned veh5 checkpoint under evaluation, and
"person"/"suspicious" for their own bonus analytics), plus the auto-start
supervisor.

Workers live in multi-object-tracking/ (torch/ultralytics/fast-alpr -- heavy
ML deps this backend deliberately does not carry) and are launched as
subprocesses using that folder's own .venv interpreter. State is in-memory
only (a dict keyed by (camera_id, mode)): restarting the backend loses track
of already-running workers, an accepted limitation for this build -- there is
no message queue or process supervisor here, per the build spec's "no
microservices, no orchestration" constraint. GOV-ING-012 pacing is enforced
by independent per-mode caps (MAX_CONCURRENT_VEHICLE_WORKERS,
MAX_CONCURRENT_VEHICLE_FINETUNED_WORKERS, MAX_CONCURRENT_PERSON_WORKERS)
rather than by a scheduler. The vehicle cap is a bounded deployment setting
(the local demo profile is three); reduce or raise it only from measured
GPU, decoder, and gateway headroom. The finetuned cap defaults to 1 --
deliberately low, see _reconcile_mode and finetune/decision.md D7.

Auto-start (build spec §2.4): every camera with `analytics_enabled=true` is
scheduled for a "vehicle" (ANPR) worker, and every camera with
`analytics_finetuned_enabled=true` for a "vehicle_finetuned" one, both on the
periodic supervisor tick, up to each mode's own concurrency cap, ANPR-viable
cameras first. The two flags are mutually exclusive per camera (see
cameras.py's _apply_operator_update), so this is two independent reconciles,
never a conflict over the same camera. Focus is a viewing choice, not an
analytics lifecycle operation. The UI only toggles the column; this module
spawns/stops the process. Because worker state is in-memory, a backend
restart doesn't know what was running before -- it writes a small manifest
(camera_id, mode, pid) on every start/stop specifically so that on the next
startup it can find and kill any orphaned worker processes left over from the
previous run, rather than trying to (and being unable to) reattach to them.
"""

import asyncio
import contextlib
import json
import logging
import os
import platform
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_service import (
    AuthContext,
    authorised_departments,
    get_authorised_camera,
    get_current_auth,
    require_worker_token,
)
from app.config import get_settings
from app.db import async_session, get_session
from app.models.analytics_count import AnalyticsCount
from app.models.camera import Camera
from app.schemas import AnalyticsCountCreate, AnalyticsCountOut

logger = logging.getLogger("sentinel.analytics")

router = APIRouter()

_REPO_ROOT = Path(__file__).resolve().parents[3]
_WORKER_DIR = _REPO_ROOT / "multi-object-tracking"


def _resolve_worker_python() -> Path:
    """Find the worker venv's interpreter regardless of OS or venv naming.

    The build spec assumes a POSIX `.venv/bin/python`; a Windows venv is
    `Scripts/python.exe`, and some machines have it as a plain `venv/`
    (no dot). Trying every combination here -- rather than hardcoding one --
    is what makes `_WORKER_PYTHON.exists()` actually true on Windows instead
    of silently failing every launch with "Worker not found".
    """
    for venv_name in (".venv", "venv"):
        for rel in (("Scripts", "python.exe"), ("bin", "python")):
            candidate = _WORKER_DIR / venv_name / Path(*rel)
            if candidate.exists():
                return candidate
    return _WORKER_DIR / ".venv" / "bin" / "python"  # default, for the "not found" error message


_WORKER_PYTHON = _resolve_worker_python()
_LOG_DIR = _WORKER_DIR / "worker_logs"
_MANIFEST_PATH = _LOG_DIR / "workers_manifest.json"
# A worker is meant to keep running for as long as its own analytics toggle
# says so, independent of this backend process's lifetime. Without this, a
# plain Popen child on Windows shares its parent console and gets killed the
# instant that console receives Ctrl+C or closes -- e.g. restarting the
# backend during development silently took every running worker down with
# it. CREATE_NEW_PROCESS_GROUP detaches it from that console's control-event
# delivery; explicit stop (terminate()/proc.kill() in _stop_worker below)
# still targets the PID directly and is unaffected.
_DETACHED = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {}

_MODES = ("vehicle", "vehicle_finetuned", "person", "suspicious")
_WORKER_SCRIPTS = {
    "vehicle": _WORKER_DIR / "observation_worker.py",
    # Same worker script as "vehicle" -- observation_worker.py derives its
    # class id -> name mapping from whichever --model checkpoint is loaded
    # (see its build_vehicle_maps docstring), so only the --model argument
    # differs between these two modes. No separate script needed.
    "vehicle_finetuned": _WORKER_DIR / "observation_worker.py",
    "person": _WORKER_DIR / "person_observation_worker.py",
    "suspicious": _WORKER_DIR / "suspicious_observation_worker.py",
}
# Tracker config per mode, chosen by measurement (see multi-object-tracking's
# reference repo): a tuned tracktrack beats both bytetrack and botsort on
# this footage (36% fewer vehicle ID switches, ~12% fewer for people, vs.
# botsort). ReID is deliberately off for vehicles -- a confirmed plate is
# already a stronger identity than any embedding, and the ANPR path needs
# the throughput -- and on for people, where there is no equivalent strong
# secondary identity and counting is more sensitive to ID switches.
_TRACKER_CONFIG = {
    "vehicle": "trackers/fast.yaml",
    # Same detection task as "vehicle", so the same tuned tracker applies.
    "vehicle_finetuned": "trackers/fast.yaml",
    "person": "trackers/recommended.yaml",
    # People-tracking, same ReID-on config as person mode: counting and
    # per-person alerting are both sensitive to ID switches.
    "suspicious": "trackers/recommended.yaml",
}
# The fine-tuned veh5 checkpoint (adds auto_rickshaw; see
# multi-object-tracking/finetune/v11x_fintune_comparison.md). Relative to
# _WORKER_DIR, matching how the worker resolves --model. Kept as one named
# constant rather than inlined so there is exactly one place to update if a
# later fine-tuning round produces a new checkpoint.
_FINETUNED_VEHICLE_MODEL = "finetune/weights/yolo11x-veh5-960-20260913-232921_best.pt"
_DEFAULT_MODEL = {
    "vehicle": "yolo11x.pt",
    "vehicle_finetuned": _FINETUNED_VEHICLE_MODEL,
    "person": "yolo11n.pt",
    # The purpose-trained two-class detector (normal vs potentially dangerous
    # person). Lives next to the worker; the worker's cwd is _WORKER_DIR.
    "suspicious": "best.pt",
}
# NOTE (deliberately left as a warning): an earlier revision raised the
# worker's frame queue to 150 frames (~6s) to "stop missing vehicles" after
# sandbox stream stalls. That was wrong and is not coming back. The queue
# sits between a producer (network + decode) and a consumer (inference);
# when the producer is persistently faster than the consumer, a deeper queue
# cannot fix the deficit -- it fills to capacity, drops at exactly the same
# rate as before, and adds its full depth as permanent latency. It bought
# nothing and made the detector view ~6s staler than the live player.
# Bufferbloat, textbook.
#
# The worker's own default (30 frames, ~1.2s) with drop-oldest-on-full is
# the right policy for LIVE monitoring: always work on near-current frames
# and shed stale ones. Vehicles are not lost by this -- a vehicle is in
# frame for seconds and the tracker sees it across many frames, so dropping
# some samples it less densely rather than missing it. If throughput ever
# genuinely needs to rise, the levers are inference cost and stream health,
# never queue depth.

# A toggle in the UI should visibly do something well within an operator's
# attention span. 60s made an enabled camera look broken for a full minute.
SUPERVISOR_INTERVAL_SECONDS = 10.0

# MJPEG detector stream (see analytics_stream). Polls the published snapshot
# a little faster than the worker writes it (10/s) so no frame waits on this
# loop, and gives up well after the worker's own stall tolerance so a
# briefly-stalled stream doesn't tear the viewer's connection down.
_STREAM_POLL_SECONDS = 0.05
_STREAM_IDLE_TIMEOUT_SECONDS = 30.0

# Ordered camera_ids the supervisor wants running in "vehicle" mode, refreshed
# every tick. Anything in here that isn't in `_workers` is queued behind the
# concurrency cap -- which the UI must be able to show, because "waiting for a
# free slot" and "broken" look identical otherwise.
_desired_vehicle: list[str] = []
# Same idea, for "vehicle_finetuned". A camera is never in both lists at once
# (analytics_enabled/analytics_finetuned_enabled are mutually exclusive per
# camera -- see cameras.py's _apply_operator_update), so the two budgets
# never compete for the same camera; kept as separate lists rather than one
# tagged list so each mode's queued-entry/status logic stays as simple as
# the original single-mode version.
_desired_vehicle_finetuned: list[str] = []

# Restart backoff per (camera_id, mode). A worker that dies almost as soon as
# it starts -- which is what happens during a gateway outage, when it can't
# even resolve its source -- must not be respawned on every tick. At a 10s
# tick across several cameras that is a spin loop hammering an already
# struggling gateway, exactly what GOV-ING-006's backoff and GOV-ING-012's
# "pace load" exist to prevent.
_RESTART_BACKOFF_BASE = 10.0
_RESTART_BACKOFF_MAX = 300.0
# A worker that ran at least this long is treated as a healthy run that
# ended, not a failure to launch, so its backoff resets.
_HEALTHY_RUN_SECONDS = 60.0

_failures: dict[tuple[str, str], int] = {}
_retry_after: dict[tuple[str, str], float] = {}
# What actually went wrong last time, for a camera currently backing off or
# queued. Without this, "queued" and "silently, repeatedly failing" look
# identical to a caller -- exactly what made an earlier misdiagnosis in this
# project opaque even with direct log access. Not cleared alongside
# _failures/_retry_after on a healthy run: worth keeping "last known issue"
# visible for a beat after recovery, cleared explicitly on the next failure
# or on an operator-initiated start (see start_analytics).
_last_error: dict[tuple[str, str], str] = {}


def _note_worker_exit(key: tuple[str, str], ran_for: float, error: str | None = None) -> None:
    if ran_for >= _HEALTHY_RUN_SECONDS:
        _failures.pop(key, None)
        _retry_after.pop(key, None)
        return
    n = _failures.get(key, 0) + 1
    _failures[key] = n
    delay = min(_RESTART_BACKOFF_BASE * (2 ** (n - 1)), _RESTART_BACKOFF_MAX)
    _retry_after[key] = time.time() + delay
    if error:
        _last_error[key] = error
    logger.warning(
        "Worker %s/%s exited after %.1fs (failure #%d); not retrying for %.0fs",
        key[0], key[1], ran_for, n, delay,
    )


def _may_start(key: tuple[str, str]) -> bool:
    return time.time() >= _retry_after.get(key, 0.0)


@dataclass
class _WorkerHandle:
    camera_id: str
    mode: str
    proc: subprocess.Popen
    started_at: datetime
    model: str
    log_path: Path


_workers: dict[tuple[str, str], _WorkerHandle] = {}


def _analytics_source(camera: Camera) -> tuple[str, str]:
    """Choose the worker's source without ever returning it to a browser.

    HLS remains preferred because its program-date-time metadata supplies the
    source-time anchor used by sightings. A custom RTSP-only camera is still
    a valid live detector source; it is opened over TCP below.  There is no
    silent catalogue fallback: manually onboarded cameras are not guaranteed
    to exist in the configured sandbox catalogue.
    """
    if camera.hls_url:
        return camera.hls_url, "hls"
    if camera.rtsp_url:
        scheme = urlparse(camera.rtsp_url).scheme.lower()
        if scheme not in {"rtsp", "rtsps"}:
            raise RuntimeError("Camera RTSP endpoint has an unsupported URL scheme")
        return camera.rtsp_url, "rtsp"
    raise RuntimeError("Camera has no HLS or RTSP stream configured for analytics")


def _rtsp_capture_options(existing: str | None) -> str:
    """Append OpenCV's FFmpeg RTSP/TCP option without discarding timeouts.

    OpenCV reads this environment variable when its FFmpeg backend opens the
    capture. It must therefore be set in the child environment *before* the
    worker imports ``camera_feeds``/``cv2``; changing it in a reader thread is
    too late and would be process-global anyway.
    """
    options = existing or "timeout;60000000|rw_timeout;60000000|live_start_index;-1"
    if "rtsp_transport;tcp" not in options:
        options = f"{options}|rtsp_transport;tcp"
    return options


def _reap_finished() -> None:
    """Drop entries for processes that have already exited on their own
    (stream ended, crashed, etc.) so status/start see live state, and record
    how long each ran so the supervisor can back off on repeated fast
    failures rather than respawning them every tick."""
    for key in [k for k, h in _workers.items() if h.proc.poll() is not None]:
        handle = _workers.pop(key)
        ran_for = (datetime.now(timezone.utc) - handle.started_at).total_seconds()
        _note_worker_exit(
            key, ran_for,
            error=f"exited with code {handle.proc.returncode} after {ran_for:.0f}s; see {handle.log_path}",
        )


def _handle_status(handle: _WorkerHandle) -> dict:
    exit_code = handle.proc.poll()
    return {
        "camera_id": handle.camera_id,
        "mode": handle.mode,
        "pid": handle.proc.pid,
        "model": handle.model,
        "started_at": handle.started_at,
        "running": exit_code is None,
        "state": "running" if exit_code is None else "exited",
        "queue_position": None,
        "exit_code": exit_code,
        "log_path": str(handle.log_path),
    }


def _save_manifest() -> None:
    _LOG_DIR.mkdir(exist_ok=True)
    entries = [
        {"camera_id": h.camera_id, "mode": h.mode, "pid": h.proc.pid} for h in _workers.values()
    ]
    _MANIFEST_PATH.write_text(json.dumps(entries))


def kill_orphans_from_previous_run() -> None:
    """Called once at startup. A worker PID recorded in the manifest from a
    prior backend process is, by definition, no longer tracked by anything --
    this process's `_workers` dict starts empty. Reattaching to it isn't
    possible (Popen has no "adopt an existing pid" API), so the only safe
    move is to kill it and let the supervisor tick start a fresh one.

    No separate liveness probe: `os.kill(pid, 0)` is a POSIX idiom that does
    not survive the port. On Windows CPython maps os.kill onto
    OpenProcess/TerminateProcess, so signal 0 is not a no-op probe and a
    dead pid raises OSError(WinError 87) rather than ProcessLookupError --
    which escaped the original `except (ProcessLookupError, PermissionError)`
    and took down backend startup entirely whenever a worker had exited
    between runs. Attempting the terminate directly and treating every
    OSError as "already gone" is both correct and portable: the failure
    modes we care about (no such process, not permitted) are exactly the
    ones where there is nothing left to kill.
    """
    if not _MANIFEST_PATH.exists():
        return
    try:
        entries = json.loads(_MANIFEST_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        entries = []

    for entry in entries:
        pid = entry.get("pid")
        if not pid:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            continue  # already exited, or not ours to signal
        logger.info("Killed orphaned analytics worker pid=%s (camera=%s mode=%s) from a previous run",
                    pid, entry.get("camera_id"), entry.get("mode"))

    with contextlib.suppress(OSError):
        _MANIFEST_PATH.unlink()


async def clear_persisted_intent() -> None:
    """Called once at startup: no camera runs ANPR until someone asks for it
    in this session.

    `analytics_enabled` is a persistent column, so a camera left enabled when
    the backend went down would have a yolo11x worker auto-started for it on
    the next boot -- GPU load and a live gateway connection that nobody in
    front of the console asked for, and which nothing in the UI explains
    (the toggle only appears once you focus that camera). Since ANPR is now
    no operator has explicitly resumed monitoring after a restart, so the
    correct startup state is off and clearing the column represents that
    honestly.
    """
    async with async_session() as session:
        result = await session.execute(
            update(Camera).where(Camera.analytics_enabled.is_(True)).values(analytics_enabled=False)
        )
        finetuned_result = await session.execute(
            update(Camera).where(Camera.analytics_finetuned_enabled.is_(True))
            .values(analytics_finetuned_enabled=False)
        )
        await session.commit()
        if result.rowcount:
            logger.info("Cleared analytics_enabled on %d camera(s) at startup; "
                        "ANPR starts only when an operator enables it", result.rowcount)
        if finetuned_result.rowcount:
            logger.info("Cleared analytics_finetuned_enabled on %d camera(s) at startup; "
                        "same reasoning as analytics_enabled above", finetuned_result.rowcount)


async def _start_worker(camera_id: str, mode: str, model: str, session: AsyncSession) -> dict:
    """Shared by the HTTP endpoint and the auto-start supervisor tick."""
    if mode not in _MODES:
        raise ValueError(f"mode must be one of {_MODES}")

    camera = await session.get(Camera, camera_id)
    if camera is None:
        raise LookupError(f"Camera {camera_id!r} not found")

    worker_script = _WORKER_SCRIPTS[mode]
    if not _WORKER_PYTHON.exists() or not worker_script.exists():
        raise RuntimeError(
            f"Worker not found at {worker_script} using {_WORKER_PYTHON}. "
            "See multi-object-tracking/requirements.txt for setup."
        )

    _reap_finished()

    key = (camera_id, mode)
    if key in _workers:
        raise FileExistsError(f"{mode} analytics already running for camera {camera_id!r}")

    settings = get_settings()
    limit = {
        "vehicle": settings.max_concurrent_vehicle_workers,
        "vehicle_finetuned": settings.max_concurrent_vehicle_finetuned_workers,
        "person": settings.max_concurrent_person_workers,
        "suspicious": settings.max_concurrent_suspicious_workers,
    }[mode]
    mode_count = sum(1 for (_cid, m) in _workers if m == mode)
    if mode_count >= limit:
        raise OverflowError(
            f"Max concurrent {mode} analytics workers ({limit}) already running; "
            "stop one before starting another"
        )

    _LOG_DIR.mkdir(exist_ok=True)
    log_path = _LOG_DIR / f"camera-{camera_id}-{mode}.log"
    log_file = open(log_path, "ab")

    worker_args = [
        # -u: unbuffered stdout/stderr, otherwise Python fully buffers
        # non-interactive output and the log file shows nothing until
        # the process exits or the buffer fills.
        str(_WORKER_PYTHON), "-u", str(worker_script),
        "--camera-id", camera_id,
        "--report-to", settings.backend_base_url,
        "--model", model,
        "--tracker", _TRACKER_CONFIG[mode],
        "--open-timeout", str(settings.analytics_open_timeout_seconds),
    ]
    # Never make a worker resolve the source through the external catalogue:
    # manually onboarded and named-source cameras are only known to this
    # registry. Passing the selected source directly also lets an RTSP-only
    # custom stream run analytics instead of failing back to that catalogue.
    source_url, source_transport = _analytics_source(camera)
    worker_args += ["--url", source_url]
    if mode in ("vehicle", "vehicle_finetuned"):
        # Absolute, not relative: the worker's cwd is _WORKER_DIR
        # (multi-object-tracking/), not this process's -- a relative
        # evidence_dir would silently land in the wrong folder.
        worker_args += ["--evidence-dir", str(Path(settings.evidence_dir).resolve())]
        # observation_worker.py's telemetry stem defaults to "vehicle" --
        # only "vehicle_finetuned" needs to say so explicitly, but passing it
        # for both is one code path instead of two and is harmless (matches
        # the default). Without this, a finetuned worker would publish under
        # the same "camera-<id>-vehicle" telemetry files as a baseline one,
        # and analytics_telemetry()/analytics_stream() below (which build the
        # path from `mode`) would look in the wrong place for it.
        worker_args += ["--telemetry-mode", mode]

    worker_env = os.environ.copy()
    worker_env.setdefault("SANDBOX_CATALOGUE_URL", settings.sandbox_catalogue_url)
    worker_env.setdefault("SANDBOX_BROWSER_BASE_URL", settings.sandbox_browser_base_url)
    if source_transport == "rtsp":
        # GOV-ING-003: inference must never default to RTSP/UDP.
        worker_env["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = _rtsp_capture_options(
            worker_env.get("OPENCV_FFMPEG_CAPTURE_OPTIONS")
        )
    if settings.worker_api_token:
        worker_env["SENTINEL_WORKER_API_TOKEN"] = settings.worker_api_token
    # See plates.py's _resolve_onnx_providers docstring: a worker spawned
    # this way (vs. run by hand for dev/test) has been observed to crash
    # with SIGABRT inside onnxruntime's CoreML execution provider a few
    # seconds in -- a native crash, not a Python bug, and one that did not
    # reproduce when the identical subprocess.Popen call was made outside
    # this backend process. CPU is slower (~90ms/crop vs ~10ms/crop) but
    # was never observed to crash.
    #
    # CoreML is exclusively a macOS execution provider -- it is never even a
    # candidate on Windows/Linux (see _resolve_onnx_providers), so forcing
    # CPU there buys no crash protection, only a needless ~9x slowdown that
    # was observed to starve short/looping demo and government-mode clips
    # of enough sampled frames to ever confirm a plate before its track
    # ends (see queue backlog and dropped-frame counts in worker logs).
    if platform.system() == "Darwin":
        worker_env["SENTINEL_FORCE_CPU_PLATES"] = "1"

    proc = subprocess.Popen(
        worker_args,
        cwd=str(_WORKER_DIR),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        env=worker_env,
        **_DETACHED,
    )
    log_file.close()  # the child holds its own fd to the same file

    _workers[key] = _WorkerHandle(
        camera_id=camera_id, mode=mode, proc=proc, started_at=datetime.now(timezone.utc),
        model=model, log_path=log_path,
    )
    _save_manifest()
    return _handle_status(_workers[key])


@router.post("/analytics/start")
async def start_analytics(
    camera_id: str,
    mode: str = "vehicle",
    model: str | None = None,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    await get_authorised_camera(session, auth, camera_id, "operator")
    # An explicit operator action overrides any supervisor backoff -- if
    # someone presses Start, they get an attempt and a real error, not a
    # silent no-op because an automatic retry timer hasn't elapsed.
    _failures.pop((camera_id, mode), None)
    _retry_after.pop((camera_id, mode), None)
    _last_error.pop((camera_id, mode), None)
    try:
        return await _start_worker(camera_id, mode, model or _DEFAULT_MODEL.get(mode, "yolo11n.pt"), session)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except OverflowError as exc:
        raise HTTPException(status_code=429, detail=str(exc))


def _stop_worker(key: tuple[str, str]) -> dict | None:
    """Terminate one worker and drop it from the registry. Returns its final
    status, or None if it wasn't running."""
    handle = _workers.get(key)
    if handle is None:
        return None

    handle.proc.terminate()
    try:
        handle.proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        handle.proc.kill()
        handle.proc.wait(timeout=5)

    status = _handle_status(handle)
    del _workers[key]
    _save_manifest()
    return status


@router.post("/analytics/stop")
async def stop_analytics(
    camera_id: str,
    mode: str = "vehicle",
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    await get_authorised_camera(session, auth, camera_id, "operator")
    status = _stop_worker((camera_id, mode))
    if status is None:
        raise HTTPException(status_code=404, detail=f"No {mode} analytics worker running for camera {camera_id!r}")
    return status


def _desired_list(mode: str) -> list[str]:
    """Looked up by name at call time, not captured once -- supervisor_tick
    rebinds `_desired_vehicle`/`_desired_vehicle_finetuned` to a brand-new
    list every tick (global reassignment, not in-place mutation), so a dict
    built once at import time would hold a permanently-stale reference."""
    return _desired_vehicle if mode == "vehicle" else _desired_vehicle_finetuned


def _queued_entry(camera_id: str, mode: str = "vehicle") -> dict | None:
    """A synthetic status row for a camera that's enabled but hasn't been
    given a worker slot yet -- without it, "queued" and "silently, repeatedly
    failing to start" both just look like "not running" to a caller. Shared
    by both status endpoints below so a bulk poll gets the exact same
    queued/failure picture a per-camera poll would, in one round trip
    instead of one-per-camera.

    `mode` is "vehicle" or "vehicle_finetuned" -- the only two modes with a
    persistent, supervisor-managed desired-set; person/suspicious are manual
    start/stop and never queue."""
    desired = _desired_list(mode)
    if camera_id not in desired or (camera_id, mode) in _workers:
        return None
    ahead = [
        cid for cid in desired
        if (cid, mode) not in _workers and desired.index(cid) < desired.index(camera_id)
    ]
    key = (camera_id, mode)
    retry_after = _retry_after.get(key)
    return {
        "camera_id": camera_id,
        "mode": mode,
        "pid": None,
        "model": None,
        "started_at": None,
        "running": False,
        "state": "queued",
        "queue_position": len(ahead) + 1,
        "exit_code": None,
        "log_path": None,
        "failure_count": _failures.get(key, 0),
        "retry_after": datetime.fromtimestamp(retry_after, tz=timezone.utc) if retry_after else None,
        "last_error": _last_error.get(key),
    }


@router.get("/analytics/capacity")
async def analytics_capacity(_auth: AuthContext = Depends(get_current_auth)):
    """The configured concurrency ceiling for each mode, so the frontend can
    render an honest "N of M running" instead of a hardcoded assumption --
    this is exactly what MAX_CONCURRENT_VEHICLE_WORKERS's demo-vs-production
    value (see config.py) is for. Static for the process lifetime; worth
    fetching once, not polling."""
    settings = get_settings()
    return {
        "vehicle": settings.max_concurrent_vehicle_workers,
        "vehicle_finetuned": settings.max_concurrent_vehicle_finetuned_workers,
        "person": settings.max_concurrent_person_workers,
        "suspicious": settings.max_concurrent_suspicious_workers,
    }


@router.get("/analytics/status")
async def analytics_status(
    auth: AuthContext = Depends(get_current_auth), session: AsyncSession = Depends(get_session)
):
    """Running workers plus queued/backing-off cameras, in one poll -- the
    bulk view needs the same "why isn't this running" picture the per-camera
    endpoint already gave, or a caller has to poll every camera individually
    just to render a capacity summary."""
    _reap_finished()
    entries = [_handle_status(handle) for handle in _workers.values()]
    entries += [e for e in (_queued_entry(cid, "vehicle") for cid in _desired_vehicle) if e is not None]
    entries += [
        e for e in (_queued_entry(cid, "vehicle_finetuned") for cid in _desired_vehicle_finetuned) if e is not None
    ]

    allowed = authorised_departments(auth)
    if allowed is None:
        return entries
    camera_ids = {e["camera_id"] for e in entries}
    rows = (
        await session.execute(select(Camera.camera_id, Camera.department).where(Camera.camera_id.in_(camera_ids)))
    ).all() if camera_ids else []
    visible_ids = {camera_id for camera_id, department in rows if department in allowed}
    return [e for e in entries if e["camera_id"] in visible_ids]


@router.get("/analytics/status/{camera_id}")
async def analytics_status_one(
    camera_id: str,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    """Every mode this camera currently has state for.

    Includes a synthetic `state: "queued"` entry when the operator has
    enabled ANPR but the concurrency cap hasn't freed a slot yet. Without
    it a queued camera is indistinguishable from a broken one in the UI --
    both would just show "not running".
    """
    await get_authorised_camera(session, auth, camera_id, "viewer")
    _reap_finished()
    out = [_handle_status(h) for (cid, _mode), h in _workers.items() if cid == camera_id]
    for mode in ("vehicle", "vehicle_finetuned"):
        queued = _queued_entry(camera_id, mode)
        if queued is not None:
            out.append(queued)
    return out


def _telemetry_paths(camera_id: str, mode: str) -> tuple[Path, Path]:
    stem = f"camera-{camera_id}-{mode}"
    return _LOG_DIR / f"{stem}.status.json", _LOG_DIR / f"{stem}.jpg"


@router.get("/analytics/telemetry/{camera_id}")
async def analytics_telemetry(
    camera_id: str,
    mode: str = "vehicle",
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    """What this camera's detector is seeing right now.

    Published by the worker itself (multi-object-tracking/worker_telemetry.py)
    as a file next to its log, then read back here. Exists because a worker
    on a camera that cannot resolve plates -- most of the sandbox at night --
    otherwise emits nothing at all for its whole run, which looks identical
    to a worker that is broken.

    `stale` is the honest bit: the file lingers for a moment after a worker
    dies, so an old status is reported as stale rather than presented as a
    live reading.
    """
    if mode not in _MODES:
        raise HTTPException(status_code=422, detail=f"mode must be one of {_MODES}")

    await get_authorised_camera(session, auth, camera_id, "viewer")
    status_path, _ = _telemetry_paths(camera_id, mode)
    if not status_path.exists():
        raise HTTPException(status_code=404, detail=f"No {mode} telemetry for camera {camera_id!r}")

    try:
        payload = json.loads(status_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        raise HTTPException(status_code=503, detail=f"Telemetry unreadable: {exc}")

    age = time.time() - payload.get("updated_at", 0)
    payload["age_seconds"] = round(age, 1)
    payload["stale"] = age > 15
    return payload


@router.get("/analytics/snapshot/{camera_id}")
async def analytics_snapshot(
    camera_id: str,
    mode: str = "vehicle",
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    """Latest annotated frame from the detector: boxes, track ids, and the
    plate reader's current belief per track (confirmed plates plain,
    uncorroborated ones suffixed "?").

    This is a detector view, not evidence and not a synced overlay on the
    live player -- the worker and the browser hold independent connections
    to the same stream, so their frames are seconds apart by construction.
    Labelled as such in the UI.
    """
    if mode not in _MODES:
        raise HTTPException(status_code=422, detail=f"mode must be one of {_MODES}")

    await get_authorised_camera(session, auth, camera_id, "viewer")
    _, snapshot_path = _telemetry_paths(camera_id, mode)
    if not snapshot_path.exists():
        raise HTTPException(status_code=404, detail=f"No {mode} snapshot for camera {camera_id!r}")

    return Response(
        content=snapshot_path.read_bytes(),
        media_type="image/jpeg",
        # The file is replaced in place every couple of seconds; without this
        # the browser would keep showing the first frame it ever fetched.
        headers={"Cache-Control": "no-store"},
    )


@router.get("/analytics/stream/{camera_id}")
async def analytics_stream(
    camera_id: str,
    mode: str = "vehicle",
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    """The detector view as a continuous MJPEG stream.

    Replaces per-frame polling of /analytics/snapshot. The browser renders
    `multipart/x-mixed-replace` natively in a plain <img>, so this is one
    long-lived connection that the server pushes frames down, instead of ~8
    requests a second competing for the browser's connection budget.

    That budget is the whole reason this exists. HTTP/1.1 browsers allow
    only ~6 connections per origin, and the Live view can hold nine HLS
    players open on this same origin. Measured with the grid streaming, a
    58KB snapshot took 2.0s and a 400-byte telemetry poll timed out at 4s --
    on localhost. The detector view looked seconds behind the live feed
    because its frames were queued behind video segments in the browser,
    not because the detector was slow (it was reporting 24 fps at the time).
    One connection that stays open sidesteps that queueing entirely.

    Frames are emitted only when the file actually changes (mtime), so a
    stalled worker costs nothing, and the stream ends itself once the
    worker stops publishing rather than holding a connection forever.
    """
    if mode not in _MODES:
        raise HTTPException(status_code=422, detail=f"mode must be one of {_MODES}")

    await get_authorised_camera(session, auth, camera_id, "viewer")
    _, snapshot_path = _telemetry_paths(camera_id, mode)

    async def frames():
        last_mtime = None
        idle_since = time.monotonic()
        while True:
            try:
                mtime = snapshot_path.stat().st_mtime
                if mtime != last_mtime:
                    last_mtime = mtime
                    payload = snapshot_path.read_bytes()
                    idle_since = time.monotonic()
                    yield (b"--frame\r\nContent-Type: image/jpeg\r\n"
                           b"Content-Length: " + str(len(payload)).encode() + b"\r\n\r\n"
                           + payload + b"\r\n")
            except (FileNotFoundError, OSError):
                # Mid-replace on Windows, or the worker hasn't published yet.
                pass
            # Ends the response instead of leaking a connection when the
            # worker has gone away (stopped, crashed, camera unfocused).
            if time.monotonic() - idle_since > _STREAM_IDLE_TIMEOUT_SECONDS:
                return
            await asyncio.sleep(_STREAM_POLL_SECONDS)

    return StreamingResponse(
        frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/analytics/counts", response_model=AnalyticsCountOut, status_code=201)
async def create_analytics_count(
    payload: AnalyticsCountCreate,
    _worker: None = Depends(require_worker_token),
    session: AsyncSession = Depends(get_session),
):
    """Periodic aggregate from a non-ANPR worker (person mode so far).

    Deliberately separate from POST /sightings: a person detection carries no
    identifier, so it cannot match a watchlist, correlate across cameras, or
    appear in a journey (see AnalyticsCount's docstring).
    """
    camera = await session.get(Camera, payload.camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail=f"Camera {payload.camera_id!r} not found")

    count = AnalyticsCount(
        camera_id=payload.camera_id,
        mode=payload.mode,
        window_start=payload.window_start,
        window_end=payload.window_end,
        unique_tracks=payload.unique_tracks,
        peak_concurrent=payload.peak_concurrent,
    )
    session.add(count)
    await session.commit()
    await session.refresh(count)
    return count


@router.get("/analytics/counts", response_model=list[AnalyticsCountOut])
async def list_analytics_counts(
    camera_id: str | None = None,
    limit: int = 200,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(AnalyticsCount).join(Camera, Camera.camera_id == AnalyticsCount.camera_id)
    allowed = authorised_departments(auth)
    if allowed is not None:
        stmt = stmt.where(Camera.department.in_(allowed))
    if camera_id is not None:
        stmt = stmt.where(AnalyticsCount.camera_id == camera_id)
    stmt = stmt.order_by(AnalyticsCount.window_start.desc()).limit(min(limit, 1000))
    return (await session.execute(stmt)).scalars().all()


# --------------------------------------------------------------------------
# Auto-start supervisor (build spec §2.4)
# --------------------------------------------------------------------------

async def _reconcile_mode(mode: str, enabled_column, budget: int, session: AsyncSession) -> list[str]:
    """Shared by "vehicle" (analytics_enabled) and "vehicle_finetuned"
    (analytics_finetuned_enabled): decide the desired camera set for one
    vehicle-family mode, stop workers no longer wanted, start what's wanted
    and isn't running. Returns the ordered desired-camera-id list so the
    caller can publish it to the module-level `_desired_*` global.

    This is a full reconcile, not start-only, for the same reason the
    original single-mode version was: turning ANPR *off* must free the
    worker rather than leave it running forever, and a higher-priority
    camera enabled later must be able to displace a lower-priority one
    already holding a slot -- priority only applying at cold start was the
    original bug this shape fixes.

    The two modes never compete for the same camera: analytics_enabled and
    analytics_finetuned_enabled are mutually exclusive per camera (enforced
    in cameras.py's _apply_operator_update), so calling this once per mode
    with each mode's own budget is equivalent to one combined reconcile and
    considerably simpler to read.
    """
    stmt = (
        select(Camera)
        .where(enabled_column.is_(True))
        # Cameras that can actually read a plate come first -- a slot
        # spent on a camera surveyed as unreadable is a slot an
        # ANPR-viable camera isn't using.
        .order_by(Camera.anpr_viable.desc().nullslast(), Camera.camera_number)
    )
    enabled = (await session.execute(stmt)).scalars().all()
    should_run = {c.camera_id for c in enabled[:budget]}

    # 1. Stop workers that are no longer wanted -- either the operator
    #    turned the camera off, or a higher-priority camera displaced it.
    #    Frees the slot before we try to fill it.
    for camera_id, worker_mode in [k for k in _workers if k[1] == mode]:
        if camera_id not in should_run:
            _stop_worker((camera_id, mode))
            logger.info("Stopped %s analytics for camera %s (no longer scheduled)", mode, camera_id)

    # 2. Start what's wanted and isn't running, unless it's still inside its
    #    restart backoff from a recent failed launch.
    for camera in enabled:
        if camera.camera_id not in should_run:
            continue
        if (camera.camera_id, mode) in _workers:
            continue
        if not _may_start((camera.camera_id, mode)):
            continue
        try:
            await _start_worker(camera.camera_id, mode, _DEFAULT_MODEL[mode], session)
            logger.info("Auto-started %s analytics for camera %s", mode, camera.camera_id)
        except Exception as exc:  # noqa: BLE001 - one camera's failure must not stop the tick
            _last_error[(camera.camera_id, mode)] = f"failed to start: {exc}"
            logger.warning("Auto-start failed for camera %s (%s): %s", camera.camera_id, mode, exc)

    return [c.camera_id for c in enabled]


async def supervisor_tick() -> None:
    """Reconcile running "vehicle" (ANPR) and "vehicle_finetuned" workers
    against what the operator asked for via `cameras.analytics_enabled` /
    `analytics_finetuned_enabled`. See _reconcile_mode for the reconcile
    shape shared by both.

    "person" and "suspicious" are never touched here: both stay manual
    (bonus analytics, GOV-FUN-013) rather than being part of the
    continuous-ANPR requirement this exists to satisfy, and each has its own
    independent concurrency budget so neither competes with the vehicle-
    family budgets below.
    """
    global _desired_vehicle, _desired_vehicle_finetuned

    _reap_finished()
    settings = get_settings()

    async with async_session() as session:
        _desired_vehicle = await _reconcile_mode(
            "vehicle", Camera.analytics_enabled, settings.max_concurrent_vehicle_workers, session)
        _desired_vehicle_finetuned = await _reconcile_mode(
            "vehicle_finetuned", Camera.analytics_finetuned_enabled,
            settings.max_concurrent_vehicle_finetuned_workers, session)


async def supervisor_loop() -> None:
    while True:
        try:
            await supervisor_tick()
        except Exception:  # noqa: BLE001 - the loop must survive a bad tick
            logger.exception("Analytics supervisor tick failed")
        await asyncio.sleep(SUPERVISOR_INTERVAL_SECONDS)
