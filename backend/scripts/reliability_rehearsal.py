#!/usr/bin/env python3
"""
Reliability and performance rehearsal (Section 5 live-test Phase 7).

Runs controlled fault-injection scenarios against the live-test fixture
and records the metrics the plan asks for: detection-to-alert latency
(p50/p95), per-worker FPS, dropped frames, queue depth, and recovery time
after feed interruption, worker crash, backend restart, and a database
connection interruption. Checks the plan's explicit targets:
    - Alert visible within five seconds of a usable confirmed observation.
    - No unbounded queue growth.
    - No duplicate alert storm.
    - No tight reconnect loop.

Assumes live_test_relay.py is already running (this script seeds/tears
down cameras + watchlist itself but does not manage the relay process,
since a backend restart mid-scenario must not also kill the media
source). Assumes the backend is already running under `--reload`-free
uvicorn on --base-url (this script restarts it by pid, so it must be the
only backend process on that port).

Usage (from backend/, using the backend's own .venv):
    ../.venv/bin/python scripts/reliability_rehearsal.py --output ../artifacts/public/checkpoint-c7/run-1
"""

import argparse
import json
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import psycopg2

_HERE = Path(__file__).resolve().parent
_BACKEND_ROOT = _HERE.parent
_REPO_ROOT = _BACKEND_ROOT.parent
_WORKER_DIR = _REPO_ROOT / "multi-object-tracking"
_WORKER_LOG_DIR = _WORKER_DIR / "worker_logs"

sys.path.insert(0, str(_BACKEND_ROOT))
from app.config import get_settings  # noqa: E402

sys.path.insert(0, str(_HERE))
import live_test_relay  # noqa: E402
import seed_live_test  # noqa: E402


def pg_dsn(url: str) -> str:
    return re.sub(r"^postgresql\+\w+://", "postgresql://", url)


class Rehearsal:
    def __init__(self, base_url, output_dir):
        self.base_url = base_url.rstrip("/")
        self.output_dir = output_dir
        self.settings = get_settings()
        self.client = httpx.Client(base_url=self.base_url, timeout=30.0)
        self.db = psycopg2.connect(pg_dsn(self.settings.sync_database_url))
        self.db.autocommit = True
        self.scenarios: list[dict] = []
        self.camera_ids: list[str] = []
        self.plate = None

    def sql(self, query, params=None):
        with self.db.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall() if cur.description else None

    def login(self):
        r = self.client.post("/api/auth/login", json={
            "email": self.settings.super_admin_email, "password": self.settings.super_admin_password,
        })
        r.raise_for_status()

    def record(self, name, target, passed, detail, measurements=None):
        entry = {"name": name, "target": target, "passed": passed, "detail": detail}
        if measurements is not None:
            entry["measurements"] = measurements
        self.scenarios.append(entry)
        print(f"  [{'PASS' if passed else 'FAIL'}] {name} -- {detail}")


def setup(reh: Rehearsal):
    print("[setup] seeding fixture cameras")
    import os
    if os.path.exists(seed_live_test._STATE_PATH):
        seed_live_test.teardown(reh.base_url)
    state = seed_live_test.seed(reh.base_url)
    reh.plate = state["plate"]
    by_role = state["camera_id_by_role"]
    reh.camera_ids = [by_role["a"], by_role["b"], by_role["c"]]
    for camera_id in reh.camera_ids:
        r = reh.client.put(f"/api/cameras/{camera_id}", json={"analytics_enabled": True})
        r.raise_for_status()
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        statuses = reh.client.get("/api/analytics/status").json()
        running = {s["camera_id"] for s in statuses if s["camera_id"] in reh.camera_ids and s["running"]}
        if len(running) == len(reh.camera_ids):
            break
        time.sleep(1.0)
    else:
        raise RuntimeError("workers did not reach running state during setup")
    print(f"[setup] {len(reh.camera_ids)} camera(s) running ANPR: {reh.camera_ids}")


def teardown(reh: Rehearsal):
    for camera_id in reh.camera_ids:
        reh.client.put(f"/api/cameras/{camera_id}", json={"analytics_enabled": False})
    seed_live_test.teardown(reh.base_url)
    print("[teardown] cameras disabled, seed state removed")


def scenario_latency_distribution(reh: Rehearsal, samples: int, per_sample_timeout: float):
    """Repeatedly force a fresh alert (resolve the open one, wait for the
    looping fixture clip to re-trigger a confirmed sighting) and measure
    detection-to-alert latency each time -- a real distribution, not one
    sample, since the fixture naturally only alerts once per dedup window
    otherwise."""
    latencies = []
    queue_depth_samples = []
    fps_samples = {cid: [] for cid in reh.camera_ids}
    dropped_at_start = {}
    for camera_id in reh.camera_ids:
        status_path = _WORKER_LOG_DIR / f"camera-{camera_id}-vehicle.status.json"
        if status_path.exists():
            try:
                dropped_at_start[camera_id] = json.loads(status_path.read_text()).get("dropped_frames", 0)
            except (json.JSONDecodeError, OSError):
                dropped_at_start[camera_id] = 0

    for i in range(samples):
        t0 = time.monotonic()
        alert = None
        while time.monotonic() - t0 < per_sample_timeout and alert is None:
            for camera_id in reh.camera_ids:
                alerts = reh.client.get("/api/alerts", params={"camera_id": camera_id, "status": "open"}).json()
                match = next((a for a in alerts if a["plate"] == reh.plate), None)
                if match:
                    alert = match
                    break
            if alert is None:
                # sample worker telemetry while we wait, for the resource/queue checks
                for camera_id in reh.camera_ids:
                    status_path = _WORKER_LOG_DIR / f"camera-{camera_id}-vehicle.status.json"
                    if status_path.exists():
                        try:
                            payload = json.loads(status_path.read_text())
                            if "fps" in payload:
                                fps_samples[camera_id].append(payload["fps"])
                            if "queue_depth" in payload:
                                queue_depth_samples.append(payload["queue_depth"])
                        except (json.JSONDecodeError, OSError):
                            pass
                time.sleep(1.0)
        if alert is None:
            continue
        journey = reh.client.get(f"/api/vehicles/{reh.plate}/journey").json()
        # stops are ordered by seen_at ascending -- the most recent one is
        # the sighting that just triggered this freshly-created alert.
        seen_at = datetime.fromisoformat(journey["stops"][-1]["seen_at"].replace("Z", "+00:00"))
        alert_at = datetime.fromisoformat(alert["created_at"].replace("Z", "+00:00"))
        latency = (alert_at - seen_at).total_seconds()
        if 0 <= latency < 60:  # sanity guard against picking up a stale/unrelated alert
            latencies.append(latency)
        # Resolve so the next loop-triggered confirmation raises a fresh alert.
        reh.client.post(f"/api/alerts/{alert['id']}/resolve")

    dropped_delta = {}
    for camera_id in reh.camera_ids:
        status_path = _WORKER_LOG_DIR / f"camera-{camera_id}-vehicle.status.json"
        if status_path.exists():
            try:
                current = json.loads(status_path.read_text()).get("dropped_frames", 0)
                dropped_delta[camera_id] = current - dropped_at_start.get(camera_id, 0)
            except (json.JSONDecodeError, OSError):
                pass

    measurements = {
        "sample_count": len(latencies),
        "latencies_s": [round(x, 3) for x in latencies],
        "p50_s": round(statistics.median(latencies), 3) if latencies else None,
        "p95_s": round(statistics.quantiles(latencies, n=20)[18], 3) if len(latencies) >= 5 else (
            round(max(latencies), 3) if latencies else None
        ),
        "queue_depth_max": max(queue_depth_samples) if queue_depth_samples else None,
        "queue_depth_samples": len(queue_depth_samples),
        "queue_depth_at_cap_fraction": (
            round(sum(1 for q in queue_depth_samples if q >= 30) / len(queue_depth_samples), 2)
            if queue_depth_samples else None
        ),
        "fps_by_camera": {
            cid: {"min": round(min(v), 1), "max": round(max(v), 1), "avg": round(statistics.mean(v), 1)}
            for cid, v in fps_samples.items() if v
        },
        "dropped_frames_delta": dropped_delta,
    }
    p95_ok = measurements["p95_s"] is not None and measurements["p95_s"] <= 5.0
    reh.record(
        "detection-to-alert latency (p50/p95)",
        "alert visible within 5s of a usable confirmed observation (p95)",
        p95_ok and len(latencies) > 0,
        f"{len(latencies)} sample(s), p50={measurements['p50_s']}s p95={measurements['p95_s']}s",
        measurements,
    )

    # Buffer cap comes from observation_worker.py's default --buffer=30.
    # Touching the cap is the bounded, drop-oldest queue doing exactly what
    # it's designed to do under momentary overload -- that IS the "no
    # unbounded growth" guarantee, not a violation of it. What would be a
    # real problem is the queue sitting pinned at the cap for most of the
    # observation window (inference permanently unable to keep up, not
    # just absorbing a transient burst).
    at_cap_fraction = measurements["queue_depth_at_cap_fraction"]
    queue_ok = at_cap_fraction is None or at_cap_fraction < 0.5
    reh.record(
        "queue growth",
        "bounded (drop-oldest) rather than unbounded; not pinned at cap for a sustained period",
        queue_ok,
        f"max observed queue_depth={measurements['queue_depth_max']} (cap=30, hard-bounded by design), "
        f"at-cap for {at_cap_fraction if at_cap_fraction is not None else 'n/a'} of samples",
    )

    # alerts has no plate column directly -- dedup_key is "{plate}:{watchlist_entry_id}".
    total_alerts = reh.sql("SELECT count(*) FROM alerts WHERE dedup_key LIKE %s", (f"{reh.plate}:%",))[0][0]
    total_sightings = reh.sql("SELECT count(*) FROM sightings WHERE plate = %s", (reh.plate,))[0][0]
    storm_ok = total_alerts <= total_sightings
    reh.record(
        "duplicate alert storm",
        "no duplicate alert storm (at most one alert per sighting)",
        storm_ok,
        f"{total_alerts} alert(s) across {total_sightings} sighting(s) for {reh.plate}",
    )


def scenario_feed_interruption(reh: Rehearsal):
    camera_id = reh.camera_ids[1]
    role = "b"
    status_path = _WORKER_LOG_DIR / f"camera-{camera_id}-vehicle.status.json"
    reconnects_before = 0
    if status_path.exists():
        try:
            reconnects_before = json.loads(status_path.read_text()).get("reconnects", 0)
        except (json.JSONDecodeError, OSError):
            pass

    live_test_relay.cmd_kill(argparse.Namespace(role=role))
    time.sleep(3.0)  # let the feed actually go down before checking
    down_probe = reh.client.post("/api/probe", params={"camera_id": camera_id}).json()
    confirmed_down = down_probe["results"][0]["transport_ok"] == "none"

    # cmd_kill is a one-shot interruption -- nothing auto-respawns the
    # publisher (see its own docstring), so recovery only starts once we
    # explicitly bring the source back, same as an operator restoring a
    # camera after an outage.
    t0 = time.monotonic()
    live_test_relay.cmd_restart(argparse.Namespace(role=role))

    deadline = t0 + 60.0
    recovered_at = None
    reconnect_events = 0
    last_seen_reconnects = reconnects_before
    while time.monotonic() < deadline:
        if status_path.exists():
            try:
                payload = json.loads(status_path.read_text())
                reconnects_now = payload.get("reconnects", 0)
                if reconnects_now > last_seen_reconnects:
                    reconnect_events += reconnects_now - last_seen_reconnects
                    last_seen_reconnects = reconnects_now
            except (json.JSONDecodeError, OSError):
                pass
        probe = reh.client.post("/api/probe", params={"camera_id": camera_id}).json()
        if probe["results"][0]["transport_ok"] != "none":
            recovered_at = time.monotonic()
            break
        time.sleep(1.0)

    recovery_time = round((recovered_at - t0), 1) if recovered_at else None
    # One clean reconnect for one kill is the expected, healthy case;
    # several would mean the worker is flapping against a source that
    # keeps dropping.
    tight_loop = reconnect_events > 3
    reh.record(
        "feed interruption and recovery",
        "recovers without a tight reconnect loop",
        confirmed_down and recovered_at is not None and not tight_loop,
        f"confirmed_down={confirmed_down}, recovery_time_s={recovery_time}, reconnect_events={reconnect_events}",
        {"recovery_time_s": recovery_time, "reconnect_events": reconnect_events},
    )


def scenario_worker_crash(reh: Rehearsal, python_bin: str):
    """Reuses the already-verified worker-crash-recovery coverage in
    analytics_concurrency_smoke_test.py (kill pid directly -> supervisor
    reaps, backs off, restarts) rather than re-implementing it -- see that
    script's own scenario table."""
    t0 = time.monotonic()
    proc = subprocess.run(
        [python_bin, str(_HERE / "analytics_concurrency_smoke_test.py"), "--base-url", reh.base_url],
        cwd=str(_BACKEND_ROOT), capture_output=True, text=True, timeout=180,
    )
    duration = round(time.monotonic() - t0, 1)
    passed = proc.returncode == 0
    tail = "\n".join(proc.stdout.splitlines()[-6:])
    if not passed:
        tail += "\n" + "\n".join(proc.stderr.splitlines()[-10:])
    reh.record(
        "worker crash and recovery",
        "supervisor reaps, backs off, and restarts a killed worker",
        passed,
        f"analytics_concurrency_smoke_test.py exit={proc.returncode} ({duration}s)\n{tail}",
    )


def scenario_backend_restart(reh: Rehearsal, backend_pid: int):
    counts_before = reh.sql("SELECT count(*) FROM sightings WHERE plate = %s", (reh.plate,))[0][0]
    alerts_before = reh.sql("SELECT count(*) FROM alerts WHERE dedup_key LIKE %s", (f"{reh.plate}:%",))[0][0]

    import os
    import signal
    t0 = time.monotonic()
    os.kill(backend_pid, signal.SIGTERM)
    deadline = t0 + 30.0
    down_confirmed = False
    while time.monotonic() < deadline:
        try:
            httpx.get(f"{reh.base_url}/api/health", timeout=1.0)
        except httpx.TransportError:
            down_confirmed = True
            break
        time.sleep(0.5)

    log_path = Path(f"/tmp/reliability_rehearsal_backend_{int(time.time())}.log")
    new_proc = subprocess.Popen(
        [str(_BACKEND_ROOT.parent / ".venv" / "bin" / "uvicorn"), "app.main:app",
         "--host", "127.0.0.1", "--port", "8000"],
        cwd=str(_BACKEND_ROOT), stdout=open(log_path, "ab"), stderr=subprocess.STDOUT,
    )
    deadline = time.monotonic() + 30.0
    up_at = None
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{reh.base_url}/api/health", timeout=1.0)
            if r.status_code == 401:
                up_at = time.monotonic()
                break
        except httpx.TransportError:
            pass
        time.sleep(0.5)
    downtime_s = round((up_at - t0), 1) if up_at else None

    if up_at is None:
        reh.record("backend restart", "backend recovers cleanly", False,
                   f"backend did not come back up within 30s (pid={new_proc.pid}, log={log_path})")
        return None

    reh.login()
    counts_after = reh.sql("SELECT count(*) FROM sightings WHERE plate = %s", (reh.plate,))[0][0]
    alerts_after = reh.sql("SELECT count(*) FROM alerts WHERE dedup_key LIKE %s", (f"{reh.plate}:%",))[0][0]
    data_intact = counts_after >= counts_before and alerts_after >= alerts_before

    cameras_after = reh.client.get("/api/cameras").json()
    still_enabled = [c["camera_id"] for c in cameras_after
                     if c["camera_id"] in reh.camera_ids and c["analytics_enabled"]]
    # clear_persisted_intent() on startup is documented, intentional
    # behaviour (main.py's lifespan): analytics never auto-resumes across
    # a restart, an operator must re-enable it. That is what we expect
    # here, not a bug.
    intent_cleared_as_designed = len(still_enabled) == 0

    reh.record(
        "backend restart",
        "recovers within 30s, no data loss, analytics_enabled cleared by design (not auto-resumed)",
        down_confirmed and data_intact and intent_cleared_as_designed,
        f"downtime_s={downtime_s}, sightings {counts_before}->{counts_after}, "
        f"alerts {alerts_before}->{alerts_after}, still-enabled after restart={still_enabled}",
        {"downtime_s": downtime_s},
    )
    return new_proc.pid


def scenario_db_interruption(reh: Rehearsal):
    """Safe, reversible simulation: terminate this backend's own active
    Postgres backend connections (not the Postgres service itself, which
    may serve other local work) and confirm the connection pool recovers
    on the next request rather than the process crashing."""
    settings = reh.settings
    dsn = pg_dsn(settings.sync_database_url)
    admin = psycopg2.connect(dsn)
    admin.autocommit = True
    dbname = re.search(r"/([^/?]+)(\?|$)", dsn).group(1)
    with admin.cursor() as cur:
        cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (dbname,),
        )
        terminated = cur.rowcount
    admin.close()

    t0 = time.monotonic()
    recovered = False
    last_status = None
    while time.monotonic() - t0 < 20.0:
        try:
            r = reh.client.get("/api/cameras")
            last_status = r.status_code
            if r.status_code == 200:
                recovered = True
                break
        except httpx.TransportError:
            pass
        time.sleep(1.0)
    recovery_time = round(time.monotonic() - t0, 1)

    reh.record(
        "database connection interruption",
        "recovers without the backend process crashing",
        recovered,
        f"terminated {terminated} backend connection(s); recovered={recovered} "
        f"in {recovery_time}s (last_status={last_status})",
        {"recovery_time_s": recovery_time if recovered else None},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", required=True)
    parser.add_argument("--latency-samples", type=int, default=6)
    args = parser.parse_args()

    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    import os
    backend_pids = subprocess.run(
        ["pgrep", "-f", "uvicorn app.main:app"], capture_output=True, text=True,
    ).stdout.split()
    if len(backend_pids) != 1:
        print(f"error: expected exactly one uvicorn app.main:app process, found {backend_pids}", file=sys.stderr)
        return 1
    backend_pid = int(backend_pids[0])

    reh = Rehearsal(args.base_url, output_dir)
    reh.login()
    print(f"Reliability rehearsal against {args.base_url}\n")

    try:
        setup(reh)

        print("\n[1] latency / FPS / dropped-frame / queue-depth distribution")
        scenario_latency_distribution(reh, samples=args.latency_samples, per_sample_timeout=40.0)

        print("\n[2] feed interruption and recovery")
        scenario_feed_interruption(reh)

        print("\n[3] worker crash and recovery")
        # analytics_concurrency_smoke_test.py needs the full
        # MAX_CONCURRENT_VEHICLE_WORKERS=3 pool to itself -- free the
        # slots our own setup() is holding, then restore them after.
        for camera_id in reh.camera_ids:
            reh.client.put(f"/api/cameras/{camera_id}", json={"analytics_enabled": False})
        time.sleep(2.0)
        scenario_worker_crash(reh, sys.executable)
        for camera_id in reh.camera_ids:
            reh.client.put(f"/api/cameras/{camera_id}", json={"analytics_enabled": True})
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            statuses = reh.client.get("/api/analytics/status").json()
            running = {s["camera_id"] for s in statuses if s["camera_id"] in reh.camera_ids and s["running"]}
            if len(running) == len(reh.camera_ids):
                break
            time.sleep(1.0)

        print("\n[4] backend restart")
        new_pid = scenario_backend_restart(reh, backend_pid)
        if new_pid:
            backend_pid = new_pid
            # re-enable analytics (cleared by design on restart) so the
            # remaining scenarios still have running workers.
            for camera_id in reh.camera_ids:
                reh.client.put(f"/api/cameras/{camera_id}", json={"analytics_enabled": True})
            time.sleep(10)

        print("\n[5] database connection interruption")
        scenario_db_interruption(reh)

        print(f"\n[6] three concurrent ANPR workers (already running throughout: {reh.camera_ids})")
        statuses = reh.client.get("/api/analytics/status").json()
        running = [s for s in statuses if s["camera_id"] in reh.camera_ids and s["running"]]
        reh.record(
            "three concurrent ANPR workers",
            "at least three cameras run ANPR concurrently",
            len(running) >= 3,
            f"{len(running)}/{len(reh.camera_ids)} workers running concurrently at end of rehearsal",
        )
    finally:
        try:
            teardown(reh)
        except Exception as exc:  # noqa: BLE001
            print(f"teardown warning: {exc}")
        reh.client.close()
        reh.db.close()

    passed = sum(1 for s in reh.scenarios if s["passed"])
    report = {
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "plate": reh.plate,
        "camera_ids": reh.camera_ids,
        "scenarios": reh.scenarios,
        "passed": passed,
        "total": len(reh.scenarios),
    }
    (output_dir / "reliability_report.json").write_text(json.dumps(report, indent=2))

    print(f"\n{'=' * 60}")
    print(f"{passed}/{len(reh.scenarios)} scenarios passed")
    failed = [s["name"] for s in reh.scenarios if not s["passed"]]
    if failed:
        print("FAILED: " + ", ".join(failed))
    print(f"Report: {output_dir / 'reliability_report.json'}")
    print(f"{'=' * 60}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
