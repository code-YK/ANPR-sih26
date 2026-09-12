"""Demo-mode orchestration: a single admin-only switch that stands up a
polished, fully-real rehearsal environment for recorded product demos.

Deliberately does not invent a fake-data layer. It orchestrates the same
proven, protocol-compatible synthetic-camera pipeline built for the Section 5
live-test evidence (scripts/live_test_relay.py serves
fixtures/live-test/*.mp4 as genuinely continuous RTSP+HLS; the real ANPR
worker, watchlist match, and alert/journey logic all run unchanged against
it) -- this module just gives an operator one switch instead of running
several CLI scripts by hand, applies demo-friendly camera names instead of
the raw fixture's "Live test camera A" / role=a labelling, and backdates a
couple of historical Sighting rows so a plate's journey already shows a
route the moment demo mode turns on, rather than needing several real loop
cycles to accumulate one.

State lives in fixtures/live-test/demo_mode_state.json -- the same
gitignored, local-runtime-only convention scripts/seed_live_test.py's own
seed_state.json already established, not a database table: this is a local
demo-recording convenience with no multi-instance requirement.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_service import AuthContext, add_audit_event
from app.config import get_settings
from app.models.alert import Alert
from app.models.analytics_count import AnalyticsCount
from app.models.auth import Department
from app.models.camera import Camera, Sighting
from app.models.watchlist import WatchlistEntry
from app.routers.cameras import CameraOperatorUpdate, _apply_operator_update, _new_manual_camera
from app.schemas import DemoModeStatus
from app.services import demo_state, government_mode

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(os.path.dirname(_HERE))
_REPO_ROOT = os.path.dirname(_BACKEND_DIR)
_RELAY_SCRIPT = os.path.join(_BACKEND_DIR, "scripts", "live_test_relay.py")
_FIXTURE_DIR = os.path.join(_REPO_ROOT, "fixtures", "live-test")
_MANIFEST_PATH = os.path.join(_FIXTURE_DIR, "manifest.json")

# Must stay identical to live_test_relay.py's own camera_id()/hls_url()/
# rtsp_url() -- duplicated rather than imported so this app package never
# depends on backend/scripts (the dependency runs the other way: scripts
# import from app, not app from scripts).
_RELAY_HLS_PORT = 8888
_RELAY_RTSP_PORT = 8557  # not 8554 -- see live_test_relay.py's own port comment
_ROLE_CAMERA_ID_PREFIX = "test-camera-"

DEMO_DEPARTMENT = "Police"

# Polished display identity per fixture role, standing in for the raw
# fixture's "Live test camera A" / role=a labelling. Coordinates form a
# plausible Ahmedabad-area route so the journey map draws a real-looking
# path rather than stacking stops on one point.
_ROLE_DISPLAY = {
    # a -> b -> c roughly retraces NH48/the Surat-Vadodara-Ahmedabad
    # corridor -- ~280km state-spanning, not three tiles ten minutes apart
    # in the same neighbourhood, so the journey map actually reads as a
    # journey. Real localities, not fabricated ones, only the camera/plate
    # sighting there is synthetic.
    "a": {
        "name": "Adajan Bridge – CAM 14",
        "location_text": "Adajan Bridge, Surat",
        "lat": 21.1959, "lng": 72.7933,
    },
    "b": {
        "name": "Sayajigunj Circle – CAM 22",
        "location_text": "Sayajigunj, Vadodara",
        "lat": 22.3130, "lng": 73.1900,
    },
    "c": {
        "name": "SG Highway Junction – CAM 09",
        "location_text": "SG Highway x Makarba Rd, Ahmedabad",
        "lat": 23.0225, "lng": 72.5714,
    },
    # A different city entirely (Saurashtra, not the a/b/c corridor) for the
    # fixture's negative-control camera -- reinforces visually that it's an
    # unrelated camera/plate, not a fourth stop on this vehicle's route.
    "decoy": {
        "name": "150 Feet Ring Road – CAM 31",
        "location_text": "150 Feet Ring Road, Rajkot",
        "lat": 22.2850, "lng": 70.7649,
    },
}
# The plate's actual route (in order); "decoy" carries a different plate
# (the fixture's negative control) and is deliberately left out of the
# backdated history below.
_ROUTE_ROLES = ("a", "b", "c")
# Surat -> Vadodara (~150km) in 100min, Vadodara -> Ahmedabad (~110km) in
# 75min -- both close to a consistent ~90km/h highway average, so the
# timestamps read as one continuous real drive rather than an arbitrary
# spread. Oldest to most-recent stop.
_HISTORICAL_OFFSETS_MIN = (210, 110, 35)


def _role_hls_url(role: str) -> str:
    return f"http://127.0.0.1:{_RELAY_HLS_PORT}/{_ROLE_CAMERA_ID_PREFIX}{role}/index.m3u8"


def _role_rtsp_url(role: str) -> str:
    return f"rtsp://127.0.0.1:{_RELAY_RTSP_PORT}/{_ROLE_CAMERA_ID_PREFIX}{role}"


def _load_manifest() -> dict:
    if not os.path.exists(_MANIFEST_PATH):
        raise RuntimeError(
            "fixtures/live-test/manifest.json not found -- run "
            "backend/scripts/build_live_test_fixture.py once (from backend/, "
            "with the multi-object-tracking venv available) before enabling demo mode"
        )
    with open(_MANIFEST_PATH) as f:
        return json.load(f)


def _status_from_state(state: dict | None) -> DemoModeStatus:
    if not state:
        return DemoModeStatus(enabled=False, activated_at=None, camera_count=0, plate=None)
    return DemoModeStatus(
        enabled=True,
        activated_at=state["activated_at"],
        camera_count=len(state.get("camera_ids", [])),
        plate=state.get("plate"),
    )


async def get_status() -> DemoModeStatus:
    return _status_from_state(demo_state.load())


def _relay_env() -> dict:
    # live_test_relay.py is a standalone script (no pydantic-settings import),
    # so it can't see Settings.mediamtx_bin on its own -- and since this
    # backend is normally launched as plain `uvicorn app.main:app` (no
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
            f"live_test_relay.py start failed (needs mediamtx + ffmpeg installed): "
            f"{result.stdout}\n{result.stderr}"
        )


def _stop_relay() -> None:
    subprocess.run(
        [sys.executable, _RELAY_SCRIPT, "stop"],
        cwd=_BACKEND_DIR, capture_output=True, text=True, timeout=15,
    )


async def enable(session: AsyncSession, auth: AuthContext) -> DemoModeStatus:
    existing = demo_state.load()
    if existing:
        # The state file surviving does not mean the relay is still alive --
        # a backend restart, a closed terminal, or a machine sleep can kill
        # the mediamtx/ffmpeg processes while this file just sits there.
        # _start_relay() -> live_test_relay.py's own cmd_start is already
        # idempotent per-process (checks _alive() and only (re)starts what's
        # actually dead), so re-running it here is cheap when everything is
        # fine and self-healing when it isn't -- no separate liveness check
        # needed, and no manual disable/enable cycle required to recover.
        _start_relay()
        return _status_from_state(existing)

    # Mutually exclusive with government_mode: it deliberately does the
    # opposite curation (real catalogue cameras only, see LiveView.jsx).
    if government_mode.is_active():
        raise RuntimeError("Government mode is currently on -- turn it off before enabling demo mode.")

    manifest = _load_manifest()
    plate = manifest["plate"]

    if await session.get(Department, DEMO_DEPARTMENT) is None:
        raise RuntimeError(f"Department {DEMO_DEPARTMENT!r} does not exist -- create it in Admin first")

    _start_relay()

    camera_ids: list[str] = []
    camera_id_by_role: dict[str, str] = {}
    for role, display in _ROLE_DISPLAY.items():
        camera = await _new_manual_camera(
            session,
            name=display["name"],
            location_text=display["location_text"],
            hls_url=_role_hls_url(role),
            rtsp_url=_role_rtsp_url(role),
        )
        _apply_operator_update(
            camera,
            CameraOperatorUpdate(
                department=DEMO_DEPARTMENT,
                latitude=display["lat"],
                longitude=display["lng"],
                geocode_confidence="exact",
            ),
        )
        session.add(camera)
        await session.flush()
        camera_ids.append(camera.camera_id)
        camera_id_by_role[role] = camera.camera_id

    entry = WatchlistEntry(
        raw_value=plate,
        normalised_value=plate,  # manifest plate already matches the Indian-plate format the app normalises to
        reason_code="demo-mode",
        severity="high",
        notes="Demo-mode rehearsal watchlist entry -- not a real vehicle identifier.",
        source="demo_mode",
        active=True,
    )
    session.add(entry)
    await session.flush()

    now = datetime.now(timezone.utc)
    historical_sighting_ids: list[int] = []
    for role, minutes_ago in zip(_ROUTE_ROLES, _HISTORICAL_OFFSETS_MIN, strict=True):
        sighting = Sighting(
            camera_id=camera_id_by_role[role],
            seen_at=now - timedelta(minutes=minutes_ago),
            plate=plate,
            confidence=0.93,
            model_version="demo-mode-seed",
        )
        session.add(sighting)
        await session.flush()
        historical_sighting_ids.append(sighting.id)

    add_audit_event(
        session,
        actor=auth.user,
        action="demo_mode.enabled",
        target_type="demo_mode",
        target_id="singleton",
        result="success",
        details={"camera_ids": camera_ids, "watchlist_id": entry.id, "plate": plate},
    )
    await session.commit()

    state = {
        "activated_at": now.isoformat(),
        "camera_ids": camera_ids,
        "camera_id_by_role": camera_id_by_role,
        "watchlist_id": entry.id,
        "historical_sighting_ids": historical_sighting_ids,
        "plate": plate,
    }
    demo_state.save(state)
    return _status_from_state(state)


async def disable(session: AsyncSession, auth: AuthContext) -> DemoModeStatus:
    state = demo_state.load()
    if not state:
        return _status_from_state(None)

    camera_ids = state.get("camera_ids", [])
    if camera_ids:
        # Dependency order matters: alerts/analytics_counts/sightings all
        # carry a plain (non-cascading) FK onto cameras.camera_id, so the
        # camera row can't be deleted until each of these is cleared first --
        # same order scripts/seed_live_test.py's own --teardown already uses.
        await session.execute(delete(Alert).where(Alert.camera_id.in_(camera_ids)))
        await session.execute(delete(Sighting).where(Sighting.camera_id.in_(camera_ids)))
        await session.execute(delete(AnalyticsCount).where(AnalyticsCount.camera_id.in_(camera_ids)))
        await session.execute(delete(Camera).where(Camera.camera_id.in_(camera_ids)))

    watchlist_id = state.get("watchlist_id")
    if watchlist_id:
        entry = await session.get(WatchlistEntry, watchlist_id)
        if entry is not None:
            await session.delete(entry)

    add_audit_event(
        session,
        actor=auth.user,
        action="demo_mode.disabled",
        target_type="demo_mode",
        target_id="singleton",
        result="success",
        details={"camera_ids": camera_ids},
    )
    await session.commit()

    _stop_relay()
    demo_state.clear()
    return _status_from_state(None)
