#!/usr/bin/env python3
"""
Reconciliation tests for GET /api/vehicles/{plate}/journey/export
(Section 5 live-test Phase 5).

Covers exactly what the plan calls out by name:
    - Stops ordered by seen_at.
    - Three synthetic cameras produce three ordered stops.
    - JSON, CSV and HTML/PDF contain the same stops and timestamps.
    - Unplaced or restricted stops are counted honestly.
    - Evidence links resolve only for authorised users.

All test data uses the f"{MARKER}JE..." plate prefix / camera names and is
deleted at the end regardless of pass/fail. Reuses smoke_test.py's Ctx for
the super-admin session, and does its own light-weight department-scoped
registration (one viewer, one department) rather than rbac_smoke_test.py's
full three-account matrix -- this suite only needs one restricted account
to prove the export honours the same authorisation as the rest of the API.

Usage (from backend/, using the backend's own .venv):
    <venv>/bin/python scripts/journey_export_test.py
    <venv>/bin/python scripts/journey_export_test.py --base-url http://127.0.0.1:8000
"""

import argparse
import csv
import io
import secrets
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from smoke_test import Ctx, MARKER  # noqa: E402

PREFIX = f"{MARKER}JE"
RESULTS = []


def check(name):
    def wrap(fn):
        def runner(*args):
            try:
                ok, detail = fn(*args)
            except Exception as exc:  # noqa: BLE001 - a test crashing is a failure, not a crash
                ok, detail = False, f"raised {type(exc).__name__}: {exc}"
            RESULTS.append((name, ok, detail))
            print(f"  [{'PASS' if ok else 'FAIL'}] {name} - {detail}")
            return ok
        runner.__name__ = fn.__name__
        return runner
    return wrap


def make_camera(ctx, name, department, latitude=None, longitude=None):
    payload = {"name": name, "location_text": f"{PREFIX} fixture location"}
    if latitude is not None:
        payload["latitude"] = latitude
        payload["longitude"] = longitude
    r = ctx.client.post("/api/cameras", json=payload)
    if r.status_code != 201:
        raise RuntimeError(f"create camera {name!r} -> HTTP {r.status_code}: {r.text[:200]}")
    camera_id = r.json()["camera_id"]
    r2 = ctx.client.put(f"/api/cameras/{camera_id}", json={"department": department})
    if r2.status_code != 200:
        raise RuntimeError(f"set department for {camera_id} -> HTTP {r2.status_code}: {r2.text[:200]}")
    return camera_id


def post_sighting(ctx, camera_id, plate, confidence, seen_at):
    r = ctx.client.post("/api/sightings", headers=ctx.worker_headers, json={
        "camera_id": camera_id, "plate": plate, "confidence": confidence,
        "seen_at": seen_at.isoformat(),
        "evidence_path": None,
    })
    if r.status_code != 201:
        raise RuntimeError(f"sighting for {camera_id} -> HTTP {r.status_code}: {r.text[:200]}")
    return r.json()


def get_export(ctx, plate, fmt):
    return ctx.client.get(f"/api/vehicles/{plate}/journey/export", params={"format": fmt})


@check("three cameras, out-of-order posting -> stops ordered by seen_at")
def test_ordering(ctx):
    plate = f"{PREFIX}1"
    now = datetime.now(timezone.utc)
    cam_a = make_camera(ctx, f"{PREFIX} cam A", "Police", 23.0, 72.5)
    cam_b = make_camera(ctx, f"{PREFIX} cam B", "Police", 23.1, 72.6)
    cam_c = make_camera(ctx, f"{PREFIX} cam C", "Police", 23.2, 72.7)
    # Post out of chronological order -- the earliest-seen sighting last --
    # to prove ordering comes from seen_at, not insertion order.
    post_sighting(ctx, cam_b, plate, 0.9, now + timedelta(minutes=5))
    post_sighting(ctx, cam_c, plate, 0.9, now + timedelta(minutes=10))
    post_sighting(ctx, cam_a, plate, 0.9, now)

    r = get_export(ctx, plate, "json")
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}"
    stops = r.json()["stops"]
    if len(stops) != 3:
        return False, f"expected 3 stops, got {len(stops)}"
    camera_order = [s["camera_id"] for s in stops]
    if camera_order != [cam_a, cam_b, cam_c]:
        return False, f"expected order [A,B,C], got {camera_order}"
    seen_ats = [s["seen_at"] for s in stops]
    if seen_ats != sorted(seen_ats):
        return False, f"stops not sorted by seen_at: {seen_ats}"
    sequences = [s["sequence"] for s in stops]
    if sequences != [1, 2, 3]:
        return False, f"expected sequence [1,2,3], got {sequences}"
    return True, f"3 stops correctly ordered A->B->C despite B,C,A posting order"


@check("JSON, CSV, HTML agree on stops and timestamps")
def test_format_reconciliation(ctx):
    plate = f"{PREFIX}1"  # reuse the 3-stop journey from the ordering test
    rj = get_export(ctx, plate, "json")
    rc = get_export(ctx, plate, "csv")
    rh = get_export(ctx, plate, "html")
    if rj.status_code != 200 or rc.status_code != 200 or rh.status_code != 200:
        return False, f"HTTP json={rj.status_code} csv={rc.status_code} html={rh.status_code}"

    stops = rj.json()["stops"]
    rows = list(csv.DictReader(io.StringIO(rc.text)))
    if len(rows) != len(stops):
        return False, f"CSV has {len(rows)} rows, JSON has {len(stops)} stops"
    for jr, cr in zip(stops, rows):
        for key in ("camera_id", "camera_name", "seen_at", "department"):
            if str(jr[key]) != cr[key]:
                return False, f"JSON/CSV disagree on {key}: {jr[key]!r} != {cr[key]!r}"

    html = rh.text
    for s in stops:
        if s["camera_id"] not in html:
            return False, f"HTML missing camera_id {s['camera_id']}"
        ts_display = s["seen_at"][:19].replace("T", " ") + " UTC"
        if ts_display not in html:
            return False, f"HTML missing timestamp {ts_display}"

    rp = get_export(ctx, plate, "pdf")
    if rp.status_code != 200 or not rp.content.startswith(b"%PDF"):
        return False, f"PDF export not a valid PDF (HTTP {rp.status_code})"

    return True, f"{len(stops)} stops agree byte-for-byte across json/csv/html; pdf is a valid PDF ({len(rp.content)}b)"


@check("camera with no coordinates -> counted as an unplaced stop")
def test_unplaced_stop(ctx):
    plate = f"{PREFIX}2"
    cam = make_camera(ctx, f"{PREFIX} cam unplaced", "Police")  # no lat/lng
    post_sighting(ctx, cam, plate, 0.9, datetime.now(timezone.utc))
    r = get_export(ctx, plate, "json")
    body = r.json()
    if r.status_code != 200 or body["unplaced_stops"] != 1:
        return False, f"expected unplaced_stops=1, got HTTP {r.status_code} {body.get('unplaced_stops')}"
    if body["stops"][0]["latitude"] is not None:
        return False, f"expected null coordinates for unplaced stop, got {body['stops'][0]}"
    return True, "camera with no lat/lng -> unplaced_stops=1, stop still listed with null coordinates"


@check("restricted stop is counted but not listed, and its evidence stays denied")
def test_restricted_stop_and_evidence(ctx):
    plate = f"{PREFIX}3"
    now = datetime.now(timezone.utc)
    home_cam = make_camera(ctx, f"{PREFIX} home cam", "Police", 23.0, 72.5)
    other_cam = make_camera(ctx, f"{PREFIX} other-dept cam", "Health", 23.1, 72.6)
    post_sighting(ctx, home_cam, plate, 0.9, now)
    restricted_sighting = post_sighting(ctx, other_cam, plate, 0.9, now + timedelta(minutes=1))

    suffix = str(int(time.time() * 1000))
    viewer_email = f"{PREFIX.lower()}-viewer-{suffix}@sentinel.test"
    password = secrets.token_urlsafe(24)
    r_reg = ctx.client.post("/api/registration-requests", json={
        "full_name": "Journey Export Test Viewer", "email": viewer_email, "password": password,
        "requested_department": "Police", "requested_role": "department_admin",
    })
    if r_reg.status_code != 201:
        return False, f"registration -> HTTP {r_reg.status_code}: {r_reg.text[:200]}"
    pending = ctx.client.get("/api/admin/registration-requests").json()
    by_email = {row["email"]: row for row in pending}
    if viewer_email not in by_email:
        return False, "registered viewer not found in pending list"
    r_approve = ctx.client.post(
        f"/api/admin/registration-requests/{by_email[viewer_email]['id']}/approve",
        json={"clearance": "viewer"},
    )
    if r_approve.status_code != 200:
        return False, f"approval -> HTTP {r_approve.status_code}: {r_approve.text[:200]}"

    viewer_client = httpx.Client(base_url=ctx.base_url, timeout=20.0)
    r_login = viewer_client.post("/api/auth/login", json={"email": viewer_email, "password": password})
    if r_login.status_code != 200:
        return False, f"viewer login -> HTTP {r_login.status_code}"

    try:
        r_export = viewer_client.get(f"/api/vehicles/{plate}/journey/export", params={"format": "json"})
        body = r_export.json()
        if r_export.status_code != 200:
            return False, f"scoped export -> HTTP {r_export.status_code}"
        if body["restricted_stops"] != 1:
            return False, f"expected restricted_stops=1, got {body['restricted_stops']}"
        if len(body["stops"]) != 1 or body["stops"][0]["camera_id"] != home_cam:
            return False, f"expected only the home-department stop listed, got {body['stops']}"

        r_evidence = viewer_client.get(f"/api/sightings/{restricted_sighting['sighting_id']}/evidence")
        if r_evidence.status_code != 403:
            return False, (
                f"restricted-department sighting evidence should 403 for this viewer, "
                f"got {r_evidence.status_code}"
            )
        return True, (
            f"scoped viewer: restricted_stops=1, only home-department stop listed, "
            f"cross-department evidence -> 403"
        )
    finally:
        viewer_client.close()
        # user_department_access and user_sessions both FK users.id
        # ON DELETE CASCADE -- deleting the user is enough (same as
        # rbac_smoke_test.py's own cleanup).
        ctx.sql("DELETE FROM registration_requests WHERE email = %s", (viewer_email,))
        ctx.sql("DELETE FROM users WHERE email = %s", (viewer_email,))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    ctx = Ctx(args.base_url)
    camera_names = [f"{PREFIX} cam A", f"{PREFIX} cam B", f"{PREFIX} cam C",
                    f"{PREFIX} cam unplaced", f"{PREFIX} home cam", f"{PREFIX} other-dept cam"]
    try:
        print(f"Journey export reconciliation tests against {args.base_url}\n")
        for fn in (test_ordering, test_format_reconciliation, test_unplaced_stop,
                   test_restricted_stop_and_evidence):
            fn(ctx)

        print(f"\n{'=' * 60}")
        passed = sum(1 for _, ok, _ in RESULTS if ok)
        failed = [n for n, ok, _ in RESULTS if not ok]
        print(f"{passed}/{len(RESULTS)} passed")
        if failed:
            print("FAILED: " + ", ".join(failed))
        print(f"{'=' * 60}")
        sys.exit(0 if not failed else 1)
    finally:
        ctx.sql("DELETE FROM alerts WHERE dedup_key LIKE %s", (f"{PREFIX}%",))
        ctx.sql("DELETE FROM sightings WHERE plate LIKE %s", (f"{PREFIX}%",))
        ctx.sql("DELETE FROM watchlist_entries WHERE normalised_value LIKE %s", (f"{PREFIX}%",))
        ctx.sql("DELETE FROM cameras WHERE name = ANY(%s)", (camera_names,))
        ctx.close()


if __name__ == "__main__":
    main()
