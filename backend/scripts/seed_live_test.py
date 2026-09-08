#!/usr/bin/env python3
"""
Onboards the Section 5 live-test fixture cameras and watchlist entry
through the real API -- never raw SQL for creation, mirroring
investigate_smoke_test.py's established convention. Pairs with
build_live_test_fixture.py (produces the clips + manifest.json) and
live_test_relay.py (serves them; must already be running so the seeded
hls_url values are actually reachable).

Cameras have no DELETE endpoint in this app (see docs/api.md's manual-
onboarding note), so --teardown removes exactly the rows this script
created via a scoped SQL delete -- the same accepted pattern already used
for scratch test cameras elsewhere in this project. The watchlist entry
does have a real DELETE endpoint and is removed through it.

Usage (from backend/, live_test_relay.py already running):
    ../.venv/bin/python scripts/seed_live_test.py
    ../.venv/bin/python scripts/seed_live_test.py --teardown
"""

import argparse
import json
import os
import re
import sys

import httpx
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import get_settings  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_test_relay import camera_id, hls_url, rtsp_url  # noqa: E402

_FIXTURE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "fixtures", "live-test")
_MANIFEST_PATH = os.path.join(_FIXTURE_DIR, "manifest.json")
_STATE_PATH = os.path.join(_FIXTURE_DIR, "seed_state.json")

DEPARTMENT = "Police"
# Distinct, plausible-but-fake coordinates so the three cameras plot as a
# real route on the map/journey view rather than stacking on one point.
_COORDS = {
    "a": (23.0225, 72.5714),   # Ahmedabad-ish
    "b": (23.0300, 72.5850),
    "c": (23.0400, 72.6000),
    "decoy": (23.0100, 72.5600),
}


def _pg_dsn(sqlalchemy_url: str) -> str:
    return re.sub(r"^postgresql\+\w+://", "postgresql://", sqlalchemy_url)


def seed(base_url: str) -> dict:
    if not os.path.exists(_MANIFEST_PATH):
        raise SystemExit(f"{_MANIFEST_PATH} not found -- run build_live_test_fixture.py first")
    with open(_MANIFEST_PATH) as f:
        manifest = json.load(f)

    settings = get_settings()
    if not settings.super_admin_email or not settings.super_admin_password:
        raise SystemExit("SUPER_ADMIN_EMAIL/PASSWORD required")

    client = httpx.Client(base_url=base_url, timeout=30.0)
    resp = client.post("/api/auth/login", json={"email": settings.super_admin_email, "password": settings.super_admin_password})
    resp.raise_for_status()

    created_camera_ids = []
    camera_id_by_role = {}
    watchlist_id = None
    try:
        for cam in manifest["cameras"]:
            role = cam["role"]
            lat, lng = _COORDS[role]
            resp = client.post(
                "/api/cameras",
                json={
                    "name": f"Live test camera {role.upper()}",
                    "location_text": f"Section 5 live-test fixture, role={role}",
                    "department": DEPARTMENT,
                    "hls_url": hls_url(role),
                    "rtsp_url": rtsp_url(role),
                    "latitude": lat,
                    "longitude": lng,
                    "geocode_confidence": "exact",
                },
            )
            resp.raise_for_status()
            body = resp.json()
            created_camera_ids.append(body["camera_id"])
            camera_id_by_role[role] = body["camera_id"]
            print(f"[{role}] camera {body['camera_id']} created, stream_available={body['stream_available']}")

        resp = client.post(
            "/api/watchlist",
            json={
                "raw_value": manifest["plate"],
                "reason_code": "live-test-fixture",
                "severity": "high",
                "notes": "Section 5 live-test synthetic watchlist entry -- not a real vehicle identifier",
                "source": "seed_live_test.py",
            },
        )
        resp.raise_for_status()
        watchlist_id = resp.json()["id"]
        print(f"watchlist entry {watchlist_id} created for plate {manifest['plate']}")
    finally:
        client.close()

    state = {
        "camera_ids": created_camera_ids,
        # role -> backend camera_id, so a caller (run_live_test.py) that
        # only knows fixture roles like "test-camera-a" can resolve the
        # real registry id it needs to call the rest of the API with.
        "camera_id_by_role": camera_id_by_role,
        "watchlist_id": watchlist_id,
        "plate": manifest["plate"],
    }
    with open(_STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)
    print(f"\nWrote {_STATE_PATH}")
    return state


def teardown(base_url: str) -> None:
    if not os.path.exists(_STATE_PATH):
        print("nothing to tear down (no seed_state.json)")
        return
    with open(_STATE_PATH) as f:
        state = json.load(f)

    settings = get_settings()

    # Every table with a camera_id FK back to cameras (checked directly
    # against information_schema, not assumed -- this list has grown twice
    # already as real exploration exercised paths a first pass missed:
    # alerts and sightings from ANPR, then analytics_counts from Person
    # mode. recordings is included for the same reason even though a
    # live-test camera is unlikely to have one -- cheap to cover, expensive
    # to rediscover the hard way a third time.
    if state.get("camera_ids"):
        conn = psycopg2.connect(_pg_dsn(settings.sync_database_url))
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM alerts WHERE sighting_id IN "
                "(SELECT id FROM sightings WHERE camera_id = ANY(%s)) OR camera_id = ANY(%s)",
                (state["camera_ids"], state["camera_ids"]),
            )
            cur.execute("DELETE FROM sightings WHERE camera_id = ANY(%s)", (state["camera_ids"],))
            cur.execute("DELETE FROM analytics_counts WHERE camera_id = ANY(%s)", (state["camera_ids"],))
            cur.execute("UPDATE recordings SET camera_id = NULL WHERE camera_id = ANY(%s)", (state["camera_ids"],))
            cur.execute("DELETE FROM cameras WHERE camera_id = ANY(%s)", (state["camera_ids"],))
        conn.close()
        print(f"deleted cameras {state['camera_ids']} (and their sightings/alerts/analytics_counts)")

    client = httpx.Client(base_url=base_url, timeout=30.0)
    resp = client.post("/api/auth/login", json={"email": settings.super_admin_email, "password": settings.super_admin_password})
    resp.raise_for_status()

    if state.get("watchlist_id"):
        resp = client.delete(f"/api/watchlist/{state['watchlist_id']}")
        if resp.status_code not in (204, 404):
            raise RuntimeError(f"delete watchlist entry {state['watchlist_id']} failed: {resp.status_code} {resp.text}")
        print(f"deleted watchlist entry {state['watchlist_id']}")
    client.close()

    os.remove(_STATE_PATH)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--teardown", action="store_true")
    args = parser.parse_args()

    if args.teardown:
        teardown(args.base_url)
    else:
        seed(args.base_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
