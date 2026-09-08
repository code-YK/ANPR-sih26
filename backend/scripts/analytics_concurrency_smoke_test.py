#!/usr/bin/env python3
"""
Smoke test for Section 5 live-test Phase 2: multi-camera concurrent ANPR.

Reuses Phase 1's live-test fixture (build_live_test_fixture.py's clips,
served live by live_test_relay.py) as the controllable multi-camera source
-- no new fixture needed here. Seeds/tears down the four fixture cameras +
watchlist entry itself via seed_live_test.py's real functions (never raw
SQL for creation), but does NOT start/stop the relay (mediamtx + the ffmpeg
publishers) -- that's a heavier-weight prerequisite this script checks for
and SKIPs cleanly on, rather than duplicating live_test_relay.py's own
process-management logic.

Requires the demo concurrency profile (MAX_CONCURRENT_VEHICLE_WORKERS=3,
see backend/.env) -- SKIPs with a clear message against the production
default of 1, since this test is specifically about concurrency > 1.

Usage (from backend/, live_test_relay.py already running with the fixture
built via build_live_test_fixture.py):
    ../.venv/bin/python scripts/analytics_concurrency_smoke_test.py
"""

import contextlib
import os
import signal
import sys
import time

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import seed_live_test  # noqa: E402
from live_test_relay import API_PORT  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import get_settings  # noqa: E402

MARKER = "ANALYTICS_CONCURRENCY_SMOKETEST"
RESULTS = []
# Supervisor tick is 10s (SUPERVISOR_INTERVAL_SECONDS in analytics.py) --
# every wait below is a bit more than that so a reconcile has definitely run.
TICK_WAIT_S = 13
BACKOFF_BASE_S = 10  # _RESTART_BACKOFF_BASE in analytics.py


def check(name):
    def wrap(fn):
        def runner(*args, **kwargs):
            try:
                ok, detail = fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - a test crashing is a failure, not a crash
                ok, detail = False, f"raised {type(exc).__name__}: {exc}"
            RESULTS.append((name, ok, detail))
            status = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
            print(f"  [{status}] {name} - {detail}")
            return ok
        runner.__name__ = fn.__name__
        return runner
    return wrap


def require(response: httpx.Response, expected, label: str):
    expected_codes = expected if isinstance(expected, (list, tuple)) else (expected,)
    if response.status_code not in expected_codes:
        raise AssertionError(f"{label}: expected {expected_codes}, got {response.status_code}: {response.text[:300]}")
    return response.json() if response.content else None


class Ctx:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        settings = get_settings()
        if not settings.super_admin_email or not settings.super_admin_password:
            raise RuntimeError("SUPER_ADMIN_EMAIL/PASSWORD required")
        self.client = httpx.Client(base_url=self.base_url, timeout=30.0)
        require(
            self.client.post("/api/auth/login", json={"email": settings.super_admin_email, "password": settings.super_admin_password}),
            200, "super admin login",
        )
        self.camera_ids: list[str] = []  # [a, b, c, decoy], in that order

    def status(self) -> list[dict]:
        return require(self.client.get("/api/analytics/status"), 200, "bulk status")

    def status_for(self, camera_id: str) -> dict | None:
        for entry in self.status():
            if entry["camera_id"] == camera_id and entry["mode"] == "vehicle":
                return entry
        return None

    def set_enabled(self, camera_id: str, enabled: bool):
        require(
            self.client.put(f"/api/cameras/{camera_id}", json={"analytics_enabled": enabled}),
            200, f"set analytics_enabled={enabled} on {camera_id}",
        )

    def cleanup(self):
        for cid in self.camera_ids:
            with contextlib.suppress(Exception):
                self.set_enabled(cid, False)
        if self.camera_ids:
            time.sleep(TICK_WAIT_S)  # let the supervisor actually stop them before teardown deletes the rows
        self.client.close()
        seed_live_test.teardown(self.base_url)


@check("relay is reachable (live_test_relay.py already running)")
def test_relay_up(ctx: Ctx):
    try:
        resp = httpx.get(f"http://127.0.0.1:{API_PORT}/v3/paths/list", timeout=2.0)
    except httpx.HTTPError as exc:
        return None, f"skipping suite: mediamtx not reachable ({exc}) -- run: live_test_relay.py start"
    return resp.status_code == 200, f"HTTP {resp.status_code}"


@check("demo concurrency profile is active")
def test_capacity(ctx: Ctx):
    capacity = require(ctx.client.get("/api/analytics/capacity"), 200, "capacity")
    if capacity["vehicle"] < 3:
        return None, (
            f"skipping suite: vehicle capacity is {capacity['vehicle']}, need >=3 -- "
            "set MAX_CONCURRENT_VEHICLE_WORKERS=3 in backend/.env and restart the backend"
        )
    return True, f"vehicle capacity = {capacity['vehicle']}"


@check("fixture cameras seed cleanly")
def test_seed(ctx: Ctx):
    state = seed_live_test.seed(ctx.base_url)
    ctx.camera_ids = state["camera_ids"]
    return len(ctx.camera_ids) == 4, f"seeded {ctx.camera_ids}"


@check("three cameras enabled all reach running")
def test_three_running(ctx: Ctx):
    for cid in ctx.camera_ids[:3]:
        ctx.set_enabled(cid, True)
    time.sleep(TICK_WAIT_S)
    states = {cid: (ctx.status_for(cid) or {}).get("state") for cid in ctx.camera_ids[:3]}
    return all(s == "running" for s in states.values()), str(states)


@check("a fourth enabled camera is queued, not broken")
def test_fourth_queued(ctx: Ctx):
    decoy = ctx.camera_ids[3]
    ctx.set_enabled(decoy, True)
    time.sleep(TICK_WAIT_S)
    entry = ctx.status_for(decoy)
    ok = bool(entry) and entry.get("state") == "queued" and entry.get("queue_position") == 1
    return ok, str(entry)


@check("disabling a running camera promotes the queued one")
def test_disable_promotes(ctx: Ctx):
    first, decoy = ctx.camera_ids[0], ctx.camera_ids[3]
    ctx.set_enabled(first, False)
    time.sleep(TICK_WAIT_S)
    first_entry = ctx.status_for(first)
    decoy_entry = ctx.status_for(decoy)
    ok = first_entry is None and decoy_entry is not None and decoy_entry.get("state") == "running"
    return ok, f"first={first_entry}, decoy={decoy_entry}"


@check("killing a running worker triggers backoff, then recovery")
def test_kill_recovers(ctx: Ctx):
    # camera_ids[1] ("b") is still running at this point (only [0] was
    # disabled above) -- kill its pid directly, out from under the
    # supervisor, the way a real crash would.
    target = ctx.camera_ids[1]
    before = ctx.status_for(target)
    if not before or before.get("state") != "running" or not before.get("pid"):
        return False, f"precondition failed: {target} was not running: {before}"
    os.kill(before["pid"], signal.SIGKILL)

    time.sleep(3)  # give _reap_finished a moment to notice the dead pid
    backing_off = ctx.status_for(target)
    if not backing_off or backing_off.get("state") != "queued" or not backing_off.get("retry_after"):
        return False, f"expected a backing-off queued entry with retry_after, got {backing_off}"

    time.sleep(BACKOFF_BASE_S + TICK_WAIT_S)  # backoff expiry + one more tick to restart it
    recovered = ctx.status_for(target)
    ok = bool(recovered) and recovered.get("state") == "running" and recovered.get("pid") != before["pid"]
    return ok, f"before={before.get('pid')}, backing_off={backing_off}, recovered={recovered}"


@check("enabling an already-running camera never spawns a duplicate")
def test_no_duplicates(ctx: Ctx):
    target = ctx.camera_ids[2]  # "c", running since test_three_running
    before_count = len([e for e in ctx.status() if e["mode"] == "vehicle" and e["state"] == "running"])
    resp = ctx.client.post(f"/api/analytics/start?camera_id={target}&mode=vehicle")
    after_count = len([e for e in ctx.status() if e["mode"] == "vehicle" and e["state"] == "running"])
    ok = resp.status_code == 409 and after_count == before_count
    return ok, f"start returned {resp.status_code}, running count {before_count} -> {after_count}"


@check("bulk status alone reflects the true running/queued split")
def test_bulk_status_accuracy(ctx: Ctx):
    entries = [e for e in ctx.status() if e["mode"] == "vehicle" and e["camera_id"] in ctx.camera_ids]
    running = [e for e in entries if e["state"] == "running"]
    queued = [e for e in entries if e["state"] == "queued"]
    # By this point in the run: b (recovered) and c (never touched) and
    # decoy (promoted) should be running; "a" was disabled and shouldn't
    # appear at all.
    ok = len(running) == 3 and len(queued) == 0
    return ok, f"running={[e['camera_id'] for e in running]}, queued={[e['camera_id'] for e in queued]}"


def main() -> int:
    ctx = Ctx("http://127.0.0.1:8000")
    try:
        print("Prerequisites")
        if not test_relay_up(ctx):
            print(f"\n{'=' * 60}\n0/0 passed (suite skipped)\n{'=' * 60}")
            return 0
        if not test_capacity(ctx):
            print(f"\n{'=' * 60}\n0/0 passed (suite skipped)\n{'=' * 60}")
            return 0

        print("\nFixture")
        if not test_seed(ctx):
            print("\n(skipping remaining checks: fixture seeding failed)")
        else:
            print("\nConcurrency and reconciliation")
            test_three_running(ctx)
            test_fourth_queued(ctx)
            test_disable_promotes(ctx)
            test_kill_recovers(ctx)
            test_no_duplicates(ctx)
            test_bulk_status_accuracy(ctx)

        print(f"\n{'=' * 60}")
        passed = sum(1 for _, ok, _ in RESULTS if ok)
        skipped = [n for n, ok, _ in RESULTS if ok is None]
        failed = [n for n, ok, _ in RESULTS if ok is not None and not ok]
        print(f"{passed}/{len(RESULTS) - len(skipped)} passed" + (f" ({len(skipped)} skipped)" if skipped else ""))
        if skipped:
            print("SKIPPED: " + ", ".join(skipped))
        if failed:
            print("FAILED: " + ", ".join(failed))
        print(f"{'=' * 60}")
        return 0 if not failed else 1
    finally:
        ctx.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
