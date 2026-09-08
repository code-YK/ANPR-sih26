#!/usr/bin/env python3
"""
Deterministic tests for the watchlist matching policy (Section 5 live-test
Phase 4, app/routers/sightings.py's create_sighting).

Each case below is called out by name in the live-test plan:
    - Exact match above threshold -> alert.
    - Exact match below threshold -> no alert.
    - Normalisation variants -> same plate.
    - Different plate -> no alert.
    - Repeated match inside dedup window -> one alert.
    - Match after resolution/window expiry -> new alert.

All test data uses the f"{MARKER}MP..." plate prefix and is deleted at the
end regardless of pass/fail. Reuses smoke_test.py's Ctx (login, worker
token, db handle) rather than re-implementing it.

Usage (from backend/, using the backend's own .venv):
    <venv>/bin/python scripts/matching_policy_test.py
    <venv>/bin/python scripts/matching_policy_test.py --base-url http://127.0.0.1:8000

Assumes the backend is already running with default alert_min_confidence
(0.85) -- a deployment that overrides this setting will see case 1/2's
sighting confidences (0.9 above / 0.5 below) still land on the correct
side of a custom threshold only by coincidence; this is a live-config
assumption, not a bug in the test.
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from smoke_test import Ctx, MARKER  # noqa: E402
from app.plate_format import normalise  # noqa: E402

PREFIX = f"{MARKER}MP"
RESULTS = []


def check(name):
    def wrap(fn):
        def runner(ctx):
            try:
                ok, detail = fn(ctx)
            except Exception as exc:  # noqa: BLE001 - a test crashing is a failure, not a crash
                ok, detail = False, f"raised {type(exc).__name__}: {exc}"
            RESULTS.append((name, ok, detail))
            print(f"  [{'PASS' if ok else 'FAIL'}] {name} - {detail}")
            return ok
        runner.__name__ = fn.__name__
        return runner
    return wrap


def post_sighting(ctx, camera_id, plate, confidence, seen_at):
    return ctx.client.post("/api/sightings", headers=ctx.worker_headers, json={
        "camera_id": camera_id, "plate": plate, "confidence": confidence,
        "seen_at": seen_at.isoformat(),
    })


def make_watchlist_entry(ctx, raw_value):
    r = ctx.client.post("/api/watchlist", json={"raw_value": raw_value, "severity": "high"})
    if r.status_code != 201:
        raise RuntimeError(f"watchlist create for {raw_value!r} -> HTTP {r.status_code}: {r.text[:200]}")
    return r.json()


def one_camera(ctx):
    cameras = ctx.client.get("/api/cameras").json()
    if not cameras:
        raise RuntimeError("no camera to attach sightings to")
    return cameras[0]["camera_id"]


@check("exact match above threshold -> alert")
def test_above_threshold(ctx):
    plate = f"{PREFIX}1"
    camera_id = one_camera(ctx)
    make_watchlist_entry(ctx, plate)
    r = post_sighting(ctx, camera_id, plate, 0.90, datetime.now(timezone.utc))
    body = r.json()
    if r.status_code != 201 or not body["matched"] or not body["alert_id"]:
        return False, f"expected match+alert at confidence 0.90, got HTTP {r.status_code} {body}"
    return True, f"confidence 0.90 -> alert {body['alert_id']}"


@check("exact match below threshold -> no alert, sighting still recorded")
def test_below_threshold(ctx):
    plate = f"{PREFIX}2"
    camera_id = one_camera(ctx)
    make_watchlist_entry(ctx, plate)
    r = post_sighting(ctx, camera_id, plate, 0.50, datetime.now(timezone.utc))
    body = r.json()
    if r.status_code != 201 or body["matched"] is not False or body["alert_id"] is not None:
        return False, f"expected no alert at confidence 0.50, got HTTP {r.status_code} {body}"
    found = ctx.client.get("/api/sightings", params={"plate": plate}).json()
    if len(found) != 1:
        return False, f"below-threshold sighting should still be recorded, found {len(found)}"
    return True, "confidence 0.50 -> recorded, no alert"


@check("normalisation variants match the same watchlist entry")
def test_normalisation_variants(ctx):
    plate = f"{PREFIX}3"
    camera_id = one_camera(ctx)
    # Register the watchlist entry in one format...
    make_watchlist_entry(ctx, f"{plate[:4]}-{plate[4:]}")
    # ...and report a sighting in a differently-punctuated, differently-cased
    # format for the exact same underlying plate.
    variant = f" {plate[:4].lower()} {plate[4:]} "
    if normalise(variant) != plate:
        return False, f"test setup bug: normalise({variant!r}) = {normalise(variant)!r}, expected {plate!r}"
    r = post_sighting(ctx, camera_id, variant, 0.90, datetime.now(timezone.utc))
    body = r.json()
    if r.status_code != 201 or not body["matched"]:
        return False, f"differently-formatted same plate should still match, got HTTP {r.status_code} {body}"
    stored = ctx.client.get("/api/sightings", params={"plate": plate}).json()
    if len(stored) != 1 or stored[0]["plate"] != plate:
        return False, f"stored plate should be the normalised form, got {stored}"
    return True, f"{variant!r} normalised to {plate!r} and matched"


@check("different plate -> no alert")
def test_different_plate(ctx):
    watchlisted = f"{PREFIX}4A"
    other = f"{PREFIX}4B"
    camera_id = one_camera(ctx)
    make_watchlist_entry(ctx, watchlisted)
    r = post_sighting(ctx, camera_id, other, 0.95, datetime.now(timezone.utc))
    body = r.json()
    if r.status_code != 201 or body["matched"] is not False or body["alert_id"] is not None:
        return False, f"unrelated plate should not match, got HTTP {r.status_code} {body}"
    return True, f"{other!r} not on watchlist -> no alert"


@check("repeated match inside dedup window -> one alert")
def test_dedup_window(ctx):
    plate = f"{PREFIX}5"
    camera_id = one_camera(ctx)
    make_watchlist_entry(ctx, plate)
    now = datetime.now(timezone.utc)
    r1 = post_sighting(ctx, camera_id, plate, 0.90, now)
    if r1.status_code != 201 or not r1.json()["alert_id"]:
        return False, f"first sighting should alert, got {r1.status_code} {r1.json()}"
    alert_id = r1.json()["alert_id"]
    r2 = post_sighting(ctx, camera_id, plate, 0.95, now + timedelta(minutes=5))
    if r2.status_code != 201 or r2.json()["matched"] is not False:
        return False, f"repeat inside dedup window should not re-alert, got {r2.json()}"
    alerts = ctx.client.get("/api/alerts", params={"camera_id": camera_id}).json()
    matching = [a for a in alerts if a["plate"] == plate]
    if len(matching) != 1 or matching[0]["id"] != alert_id:
        return False, f"expected exactly 1 alert for {plate!r}, found {matching}"
    return True, f"2 sightings inside window -> 1 alert ({alert_id})"


@check("match after resolution -> new alert")
def test_resolution_reopens(ctx):
    plate = f"{PREFIX}6"
    camera_id = one_camera(ctx)
    make_watchlist_entry(ctx, plate)
    now = datetime.now(timezone.utc)
    r1 = post_sighting(ctx, camera_id, plate, 0.90, now)
    if r1.status_code != 201 or not r1.json()["alert_id"]:
        return False, f"first sighting should alert, got {r1.status_code} {r1.json()}"
    alert1_id = r1.json()["alert_id"]

    resolved = ctx.client.post(f"/api/alerts/{alert1_id}/resolve")
    if resolved.status_code != 200 or resolved.json()["status"] != "resolved":
        return False, f"resolve alert {alert1_id} -> HTTP {resolved.status_code}: {resolved.text[:200]}"

    # Still inside the original dedup window, but the first alert is no
    # longer OPEN -- the policy's dedup filter only suppresses against an
    # open alert, so this must raise a fresh one.
    r2 = post_sighting(ctx, camera_id, plate, 0.90, now + timedelta(minutes=5))
    body2 = r2.json()
    if r2.status_code != 201 or not body2["matched"] or not body2["alert_id"]:
        return False, f"match after resolution should re-alert, got HTTP {r2.status_code} {body2}"
    if body2["alert_id"] == alert1_id:
        return False, "expected a new alert id, got the same resolved one back"
    return True, f"resolved alert {alert1_id} -> new alert {body2['alert_id']}"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    ctx = Ctx(args.base_url)
    try:
        print(f"Matching policy tests against {args.base_url}\n")
        for fn in (test_above_threshold, test_below_threshold, test_normalisation_variants,
                   test_different_plate, test_dedup_window, test_resolution_reopens):
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
        ctx.close()


if __name__ == "__main__":
    main()
