"""Government-feed mode: the mirror image of demo_mode.py for the Video 2
("Live Demonstration on Government-Provided CCTV Feed") requirement.

Where demo mode hides the real catalogue cameras and shows a curated set of
synthetic ones, government mode does the opposite: while it is on, the Live
view shows only real catalogue-provided cameras (see cameras.py's own
manual-N namespace distinction, mirrored client-side in LiveView.jsx) --
nothing this app itself created.

The actual swap this module performs: for every completed recording under
recorded-streams/ (repo root, gitignored -- multi-object-tracking/
record_live_clips.py's own output, one camera-<id>-<ts>-<dur>s.mp4 plus a
.json sidecar naming the real camera_id it belongs to), this serves that
recording as a genuinely continuous RTSP+HLS stream
(scripts/government_feed_relay.py, the same MediaMTX-based technique
already proven for the Section 5 live-test fixture) and temporarily points
that EXISTING camera row's hls_url/rtsp_url at the relay instead of the real
(and for now, unreachable) government endpoint. Every downstream feature --
ANPR/person/suspicious analytics, the live player, the new camera-wise
sightings report -- runs completely unmodified against it, because as far as
the rest of the app is concerned it is just this camera's stream URL.

Unlike demo mode, this never creates or deletes a Camera row -- these are
real, already-onboarded government cameras. It only overwrites two columns
temporarily and restores them on disable, tracked in
recorded-streams/_relay/government_mode_state.json (the same gitignored,
local-runtime-state convention demo_mode_state.json already established).
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_service import AuthContext, add_audit_event
from app.config import get_settings
from app.models.camera import Camera
from app.schemas import GovernmentModeStatus
from app.services import demo_state

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(os.path.dirname(_HERE))
_REPO_ROOT = os.path.dirname(_BACKEND_DIR)
_RELAY_SCRIPT = os.path.join(_BACKEND_DIR, "scripts", "government_feed_relay.py")
_RECORDING_DIR = os.path.join(_REPO_ROOT, "recorded-streams")
_STATE_PATH = os.path.join(_RECORDING_DIR, "_relay", "government_mode_state.json")

# Must stay identical to government_feed_relay.py's own path_name()/
# hls_url()/rtsp_url() -- duplicated rather than imported for the same
# reason demo_mode.py duplicates live_test_relay.py's: this app package
# never depends on backend/scripts.
_RELAY_HLS_PORT = 8890
_RELAY_RTSP_PORT = 8556
_PATH_PREFIX = "gov-camera-"


def _relay_hls_url(camera_id: str) -> str:
    return f"http://127.0.0.1:{_RELAY_HLS_PORT}/{_PATH_PREFIX}{camera_id}/index.m3u8"


def _relay_rtsp_url(camera_id: str) -> str:
    return f"rtsp://127.0.0.1:{_RELAY_RTSP_PORT}/{_PATH_PREFIX}{camera_id}"


def _discover_recordings() -> dict[str, str]:
    """Must stay in lockstep with government_feed_relay.py's own
    discover_recordings() -- same completed-recording-plus-sidecar,
    latest-wins logic (including subdirectories, e.g. an operator's own
    "newly added clips/" folder), so this module's camera_id -> hls/rtsp
    swap always matches whatever the relay actually ends up serving."""
    if not os.path.isdir(_RECORDING_DIR):
        return {}
    state_dir = os.path.dirname(_STATE_PATH)
    best: dict[str, tuple[str, str]] = {}
    for root, dirs, files in os.walk(_RECORDING_DIR):
        dirs[:] = [d for d in dirs if os.path.join(root, d) != state_dir]
        for entry in sorted(files):
            if not entry.endswith(".json"):
                continue
            try:
                with open(os.path.join(root, entry)) as f:
                    meta = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            camera_id = meta.get("camera_id")
            if not camera_id:
                continue
            # Normally the sidecar and clip share a basename (one recording,
            # one camera). An explicit "clip_path" (a filename relative to
            # the sidecar's own directory) lets several camera_ids re-onboard
            # the *same* physical recording under different identities --
            # e.g. building a multi-stop journey demo along a real corridor
            # from one clip, without duplicating tens of MB of video per stop.
            explicit_clip = meta.get("clip_path")
            clip_path = (
                os.path.join(root, explicit_clip) if explicit_clip
                else os.path.join(root, entry[: -len(".json")] + ".mp4")
            )
            if not os.path.isfile(clip_path):
                continue
            recorded_at = meta.get("recorded_at_utc", "")
            current = best.get(camera_id)
            if current is None or recorded_at > current[0]:
                best[camera_id] = (recorded_at, clip_path)
    return {camera_id: clip_path for camera_id, (_, clip_path) in best.items()}


# demo_state.py is deliberately generic but hardcoded to one fixed path,
# so it can't be reused as-is for a second, differently-pathed state file --
# reimplemented here at government-mode's own path instead of stretching
# that module's contract. demo_state itself is still used below, just for
# its is_active() check (the two modes are mutually exclusive).
def _load_gov_state() -> dict | None:
    if not os.path.exists(_STATE_PATH):
        return None
    with open(_STATE_PATH) as f:
        return json.load(f)


def _save_gov_state(state: dict) -> None:
    os.makedirs(os.path.dirname(_STATE_PATH), exist_ok=True)
    with open(_STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def _clear_gov_state() -> None:
    if os.path.exists(_STATE_PATH):
        os.remove(_STATE_PATH)


def is_active() -> bool:
    return _load_gov_state() is not None


def _status_from_state(state: dict | None, *, degraded: bool = False) -> GovernmentModeStatus:
    if not state:
        return GovernmentModeStatus(enabled=False, activated_at=None, camera_ids=[])
    return GovernmentModeStatus(
        enabled=True,
        activated_at=state["activated_at"],
        camera_ids=list(state.get("cameras", {}).keys()),
        degraded=degraded,
    )


async def _mismatched_cameras(session: AsyncSession, state: dict) -> dict[str, Camera]:
    """Cameras this mode believes it owns whose DB row no longer points at
    the relay. The state file and the `cameras` table are two independent
    stores with no foreign key or trigger between them -- anything that
    writes hls_url/rtsp_url outside this module (a direct edit, a seed
    script's upsert, another admin session) can silently pull a camera out
    from under an "enabled" government mode, and nothing before this
    detected it. Reproduced 2026-09-12: re-seeding the government camera
    fixture blanked all 16 cameras' URLs while the state file still said
    enabled -- the Live view kept showing "connected" tiles with nothing to
    play."""
    camera_ids = list(state.get("cameras", {}))
    if not camera_ids:
        return {}
    # One query for all owned cameras, not one per camera: this runs on every
    # status read, which the console polls, and sixteen sequential round trips
    # to a remote database took well over a second.
    rows = (await session.execute(select(Camera).where(Camera.camera_id.in_(camera_ids)))).scalars().all()
    return {camera.camera_id: camera for camera in rows if camera.hls_url != _relay_hls_url(camera.camera_id)}


async def get_status(session: AsyncSession | None = None) -> GovernmentModeStatus:
    state = _load_gov_state()
    if not state or session is None:
        return _status_from_state(state)
    degraded = bool(await _mismatched_cameras(session, state))
    return _status_from_state(state, degraded=degraded)


def _relay_env() -> dict:
    # government_feed_relay.py is a standalone script (no pydantic-settings
    # import), so it can't see Settings.mediamtx_bin on its own -- and since
    # this backend is normally launched as plain `uvicorn app.main:app` (no
    # --env-file, no dotenv-into-os.environ step), .env-only values like
    # MEDIAMTX_BIN never reach os.environ here either. Resolve it the same
    # way the in-process webrtc relay does and forward it explicitly.
    return {**os.environ, "MEDIAMTX_BIN": get_settings().mediamtx_bin}


def _start_relay() -> None:
    result = subprocess.run(
        [sys.executable, _RELAY_SCRIPT, "start"],
        cwd=_BACKEND_DIR, capture_output=True, text=True, timeout=40, env=_relay_env(),
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"government_feed_relay.py start failed (needs mediamtx + ffmpeg installed, and at "
            f"least one completed recording under recorded-streams/): {result.stdout}\n{result.stderr}"
        )


def _stop_relay() -> None:
    subprocess.run(
        [sys.executable, _RELAY_SCRIPT, "stop"],
        cwd=_BACKEND_DIR, capture_output=True, text=True, timeout=15,
    )


async def enable(session: AsyncSession, auth: AuthContext) -> GovernmentModeStatus:
    existing = _load_gov_state()
    if existing:
        # The state file surviving does not mean the relay is still alive --
        # a backend restart, a closed terminal, or a machine sleep can kill
        # the mediamtx/ffmpeg processes while this file just sits there.
        # _start_relay() -> government_feed_relay.py's own cmd_start is
        # already idempotent per-process (checks _alive() and only
        # (re)starts what's actually dead), so re-running it here is cheap
        # when everything is fine and self-healing when it isn't -- no
        # separate liveness check needed, and no manual disable/enable
        # cycle required to recover.
        _start_relay()

        # The relay process being fine does not mean the DB still points at
        # it -- see _mismatched_cameras. Re-apply this mode's own URLs to
        # any camera that drifted, the same write enable() does below for a
        # fresh activation, so "press the toggle on again" is the recovery
        # for both a dead relay and a DB-level drift, not just the former.
        mismatched = await _mismatched_cameras(session, existing)
        if mismatched:
            for camera_id, camera in mismatched.items():
                camera.hls_url = _relay_hls_url(camera_id)
                camera.rtsp_url = _relay_rtsp_url(camera_id)
                session.add(camera)
            add_audit_event(
                session,
                actor=auth.user,
                action="government_mode.repaired",
                target_type="government_mode",
                target_id="singleton",
                result="success",
                details={"camera_ids": list(mismatched)},
            )
            await session.commit()

        return _status_from_state(existing)

    if demo_state.is_active():
        raise RuntimeError("Demo mode is currently on -- turn it off before enabling government mode.")

    recordings = _discover_recordings()
    if not recordings:
        raise RuntimeError(
            f"No completed recording found under {_RECORDING_DIR!r} -- record_live_clips.py writes "
            "a .json sidecar only once a clip finishes, so a still-in-progress *.partial.mp4 doesn't "
            "count yet."
        )

    matched: dict[str, str] = {}
    unmatched: list[str] = []
    for camera_id in recordings:
        camera = await session.get(Camera, camera_id)
        if camera is None:
            unmatched.append(camera_id)
            continue
        matched[camera_id] = camera_id

    if not matched:
        raise RuntimeError(
            f"None of the recorded camera_ids ({', '.join(recordings)}) match an existing camera in "
            "the registry -- check the .json sidecars' camera_id field against the Registry list."
        )

    _start_relay()

    saved_originals: dict[str, dict] = {}
    for camera_id in matched:
        camera = await session.get(Camera, camera_id)
        saved_originals[camera_id] = {
            "hls_url": camera.hls_url,
            "rtsp_url": camera.rtsp_url,
        }
        camera.hls_url = _relay_hls_url(camera_id)
        camera.rtsp_url = _relay_rtsp_url(camera_id)
        session.add(camera)

    add_audit_event(
        session,
        actor=auth.user,
        action="government_mode.enabled",
        target_type="government_mode",
        target_id="singleton",
        result="success",
        details={"camera_ids": list(matched), "unmatched_files": unmatched},
    )
    await session.commit()

    state = {
        "activated_at": datetime.now(timezone.utc).isoformat(),
        "cameras": saved_originals,
    }
    _save_gov_state(state)
    return _status_from_state(state)


async def disable(session: AsyncSession, auth: AuthContext) -> GovernmentModeStatus:
    state = _load_gov_state()
    if not state:
        return _status_from_state(None)

    camera_ids = list(state.get("cameras", {}).keys())
    for camera_id, original in state.get("cameras", {}).items():
        camera = await session.get(Camera, camera_id)
        if camera is None:
            continue
        camera.hls_url = original.get("hls_url")
        camera.rtsp_url = original.get("rtsp_url")
        session.add(camera)

    add_audit_event(
        session,
        actor=auth.user,
        action="government_mode.disabled",
        target_type="government_mode",
        target_id="singleton",
        result="success",
        details={"camera_ids": camera_ids},
    )
    await session.commit()

    _stop_relay()
    _clear_gov_state()
    return _status_from_state(None)
