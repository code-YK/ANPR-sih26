#!/usr/bin/env python3
"""
One-command Section 5 live-test rehearsal (live-test plan Phase 6).

Runs the entire chain end to end -- readiness, seed/sync, stream
reachability, watchlist activation, ANPR, alert, journey, export,
reconciliation, metrics, cleanup -- and writes a self-contained evidence
bundle. Exits non-zero on the first failed stage.

Two camera-id shapes are supported:
  - "test-camera-a,test-camera-b,test-camera-c" (fixture role ids, as in
    the plan's own example): the runner manages the whole synthetic
    fixture lifecycle itself -- tears down any previous seed, rebuilds
    build_live_test_fixture.py's clips with the supplied --plate baked
    into the vehicle photo, (re)starts live_test_relay.py, and seeds
    through the real onboarding API to get this run's actual registry
    camera_ids.
  - Real registry camera_ids (e.g. "34" or a catalogue id): assumed
    already onboarded (government-feed rehearsal, Phase 9) -- the runner
    only verifies they exist and are reachable, and activates the
    supplied plate on the existing watchlist.

Usage (from backend/, using the backend's own .venv):
    ../.venv/bin/python scripts/run_live_test.py \\
        --plate GJ01TT9911 \\
        --camera-ids test-camera-a,test-camera-b,test-camera-c \\
        --output ../artifacts/public/checkpoint-c6/run-1

    ../.venv/bin/python scripts/run_live_test.py \\
        --plate GJ22AB1234 --camera-ids 34,35,41 \\
        --output ../artifacts/public/checkpoint-c6/run-gov-1
"""

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
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
_FIXTURE_DIR = _REPO_ROOT / "fixtures" / "live-test"
_WORKER_DIR = _REPO_ROOT / "multi-object-tracking"
_WORKER_LOG_DIR = _WORKER_DIR / "worker_logs"

sys.path.insert(0, str(_BACKEND_ROOT))
from app.config import get_settings  # noqa: E402

sys.path.insert(0, str(_HERE))
import live_test_relay  # noqa: E402
import seed_live_test  # noqa: E402

_FIXTURE_ROLE_PREFIX = "test-camera-"

# Never let a raw stream URL or bearer-style token reach stdout or the
# results bundle -- exit criteria: "It never prints secrets or raw feed
# URLs." Broad enough to catch rtsp://, http(s):// to the relay's own
# ports, and any Authorization/token-shaped string.
_REDACT_PATTERNS = [
    re.compile(r"rtsp://\S+"),
    re.compile(r"https?://[^\s\"']*(?:8554|8888|9997)[^\s\"']*"),
    re.compile(r"(?i)(authorization|token|password|secret)\s*[:=]\s*\S+"),
]


def redact(text: str) -> str:
    for pattern in _REDACT_PATTERNS:
        text = pattern.sub("[redacted]", text)
    return text


class StageFailed(Exception):
    pass


class Run:
    def __init__(self, base_url, plate, camera_ids, output_dir, wait_timeout):
        self.base_url = base_url.rstrip("/")
        self.plate = plate
        self.requested_camera_ids = camera_ids
        self.output_dir = output_dir
        self.wait_timeout = wait_timeout
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.started_at = datetime.now(timezone.utc)
        self.stages: list[dict] = []
        self.resolved_camera_ids: list[str] = []
        self.synthetic = all(c.startswith(_FIXTURE_ROLE_PREFIX) for c in camera_ids)
        self.watchlist_id = None
        self.client: httpx.Client | None = None
        self.log_lines: list[str] = []
        self.metrics: dict = {}

    def log(self, line: str):
        line = redact(line)
        print(f"  {line}")
        self.log_lines.append(line)

    def stage(self, name):
        def decorator(fn):
            def runner(*args, **kwargs):
                t0 = time.monotonic()
                print(f"[{len(self.stages) + 1}] {name}")
                entry = {"name": name, "status": "running"}
                self.stages.append(entry)
                try:
                    result = fn(*args, **kwargs)
                    entry["status"] = "passed"
                    return result
                except Exception as exc:  # noqa: BLE001
                    entry["status"] = "failed"
                    entry["error"] = redact(str(exc))
                    raise StageFailed(f"{name}: {exc}") from exc
                finally:
                    entry["duration_s"] = round(time.monotonic() - t0, 2)
                    print(f"    -> {entry['status']} ({entry['duration_s']}s)")
            return runner
        return decorator


def stage_readiness(run: Run):
    settings = get_settings()
    if not settings.super_admin_email or not settings.super_admin_password:
        raise RuntimeError("SUPER_ADMIN_EMAIL/PASSWORD not configured for this backend")

    dsn = re.sub(r"^postgresql\+\w+://", "postgresql://", settings.sync_database_url)
    conn = psycopg2.connect(dsn)
    conn.close()
    run.log("database reachable")

    run.client = httpx.Client(base_url=run.base_url, timeout=30.0)
    unauth = httpx.get(f"{run.base_url}/api/health", timeout=10.0)
    if unauth.status_code != 401:
        raise RuntimeError(f"expected 401 from unauthenticated /api/health, got {unauth.status_code}")
    login = run.client.post("/api/auth/login", json={
        "email": settings.super_admin_email, "password": settings.super_admin_password,
    })
    if login.status_code != 200:
        raise RuntimeError(f"backend login failed: HTTP {login.status_code}")
    health = run.client.get("/api/health")
    if health.status_code != 200:
        raise RuntimeError(f"authenticated /api/health failed: HTTP {health.status_code}")
    run.log("backend reachable and authenticated")

    if run.synthetic:
        for binary in ("mediamtx", "ffmpeg", "ffprobe"):
            if shutil.which(binary) is None:
                raise RuntimeError(f"required binary {binary!r} not on PATH")
        run.log("mediamtx/ffmpeg/ffprobe present")

    worker_python = _WORKER_DIR / ".venv" / "bin" / "python3"
    if not worker_python.exists():
        raise RuntimeError(f"worker interpreter not found at {worker_python}")
    run.log("analytics worker environment present")


def stage_sync_or_seed(run: Run):
    if not run.synthetic:
        for camera_id in run.requested_camera_ids:
            r = run.client.get(f"/api/cameras/{camera_id}")
            if r.status_code != 200:
                raise RuntimeError(f"camera {camera_id!r} not found in registry (HTTP {r.status_code})")
        run.resolved_camera_ids = list(run.requested_camera_ids)
        run.log(f"{len(run.resolved_camera_ids)} real registry camera(s) confirmed present")
        return

    if os.path.exists(seed_live_test._STATE_PATH):
        run.log("tearing down previous synthetic seed state")
        seed_live_test.teardown(run.base_url)

    decoy_plate = "GJ05ZZ4321" if run.plate != "GJ05ZZ4321" else "GJ09YY1111"
    build_cmd = [
        sys.executable, str(_HERE / "build_live_test_fixture.py"),
        "--plate", run.plate, "--decoy-plate", decoy_plate,
    ]
    proc = subprocess.run(build_cmd, cwd=str(_BACKEND_ROOT), capture_output=True, text=True, timeout=300)
    for line in proc.stdout.splitlines()[-10:]:
        run.log(line)
    if proc.returncode != 0:
        raise RuntimeError(f"build_live_test_fixture.py failed: {redact(proc.stderr[-500:])}")
    run.log(f"fixture rebuilt with plate {run.plate}")

    if live_test_relay.cmd_stop(None) != 0:
        raise RuntimeError("live_test_relay stop failed")
    if live_test_relay.cmd_start(None) != 0:
        raise RuntimeError("live_test_relay start failed (paths not ready in time)")
    run.log("relay serving fresh clips")

    state = seed_live_test.seed(run.base_url)
    run.watchlist_id = state["watchlist_id"]
    by_role = state["camera_id_by_role"]
    for requested in run.requested_camera_ids:
        role = requested.removeprefix(_FIXTURE_ROLE_PREFIX)
        if role not in by_role:
            raise RuntimeError(f"requested {requested!r} has no matching fixture role")
        run.resolved_camera_ids.append(by_role[role])
    run.log(f"seeded {len(run.resolved_camera_ids)} camera(s), watchlist entry {run.watchlist_id}")


def stage_verify_streams(run: Run):
    for camera_id in run.resolved_camera_ids:
        cam = run.client.get(f"/api/cameras/{camera_id}").json()
        if not cam.get("stream_available"):
            raise RuntimeError(f"camera {camera_id} has no stream configured")
        probe = run.client.post("/api/probe", params={"camera_id": camera_id})
        if probe.status_code != 200:
            raise RuntimeError(f"probe failed for {camera_id}: HTTP {probe.status_code}")
        transport_ok = probe.json()["results"][0]["transport_ok"]
        if transport_ok == "none":
            raise RuntimeError(f"camera {camera_id} unreachable (transport_ok=none)")
        run.log(f"{camera_id}: reachable (transport_ok={transport_ok})")


def stage_activate_watchlist(run: Run):
    if run.watchlist_id is not None:
        run.log(f"watchlist entry {run.watchlist_id} already active (seeded)")
        return
    existing = run.client.get("/api/watchlist", params={"plate": run.plate}).json()
    match = existing[0] if existing else None
    if match:
        if not match["active"]:
            r = run.client.put(f"/api/watchlist/{match['id']}", json={"active": True})
            if r.status_code != 200:
                raise RuntimeError(f"reactivate watchlist entry failed: HTTP {r.status_code}")
        run.watchlist_id = match["id"]
        run.log(f"reused/activated existing watchlist entry {run.watchlist_id}")
        return
    r = run.client.post("/api/watchlist", json={
        "raw_value": run.plate, "reason_code": "run_live_test", "severity": "high",
        "notes": f"Section 5 live-test run {run.run_id}",
    })
    if r.status_code != 201:
        raise RuntimeError(f"watchlist create failed: HTTP {r.status_code}: {r.text[:200]}")
    run.watchlist_id = r.json()["id"]
    run.log(f"created watchlist entry {run.watchlist_id} for {run.plate}")


def stage_enable_analytics(run: Run):
    for camera_id in run.resolved_camera_ids:
        r = run.client.put(f"/api/cameras/{camera_id}", json={"analytics_enabled": True})
        if r.status_code != 200:
            raise RuntimeError(f"enable analytics failed for {camera_id}: HTTP {r.status_code}")
    run.log(f"analytics enabled on {len(run.resolved_camera_ids)} camera(s)")

    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        statuses = run.client.get("/api/analytics/status").json()
        running = {s["camera_id"] for s in statuses if s["camera_id"] in run.resolved_camera_ids and s["running"]}
        if len(running) == len(run.resolved_camera_ids):
            run.log(f"all {len(running)} worker(s) running")
            return
        time.sleep(1.0)
    raise RuntimeError(f"not all workers reached running state within 30s (running: {sorted(running)})")


def stage_wait_for_sightings(run: Run):
    deadline = time.monotonic() + run.wait_timeout
    seen_cameras: set[str] = set()
    while time.monotonic() < deadline and len(seen_cameras) < len(run.resolved_camera_ids):
        for camera_id in run.resolved_camera_ids:
            if camera_id in seen_cameras:
                continue
            r = run.client.get("/api/sightings", params={"plate": run.plate, "camera_id": camera_id, "limit": 1})
            if r.status_code == 200 and r.json():
                seen_cameras.add(camera_id)
                run.log(f"{camera_id}: sighting confirmed")
        if len(seen_cameras) < len(run.resolved_camera_ids):
            time.sleep(2.0)
    missing = [c for c in run.resolved_camera_ids if c not in seen_cameras]
    if missing:
        raise RuntimeError(f"no sighting within {run.wait_timeout}s for camera(s): {missing}")


def stage_verify_alert(run: Run):
    deadline = time.monotonic() + run.wait_timeout
    found = None
    while time.monotonic() < deadline and found is None:
        for camera_id in run.resolved_camera_ids:
            alerts = run.client.get("/api/alerts", params={"camera_id": camera_id}).json()
            match = next((a for a in alerts if a["plate"] == run.plate), None)
            if match:
                found = match
                break
        if found is None:
            time.sleep(2.0)
    if found is None:
        raise RuntimeError(f"no alert raised for {run.plate} within {run.wait_timeout}s")
    run.log(f"alert {found['id']} status={found['status']}")
    run.metrics["alert_id"] = found["id"]
    run.metrics["alert_created_at"] = found["created_at"]


def stage_query_journey(run: Run):
    r = run.client.get(f"/api/vehicles/{run.plate}/journey")
    if r.status_code != 200:
        raise RuntimeError(f"journey query failed: HTTP {r.status_code}")
    journey = r.json()
    if journey["sighting_count"] < len(run.resolved_camera_ids):
        raise RuntimeError(
            f"journey has {journey['sighting_count']} sighting(s), expected >= {len(run.resolved_camera_ids)}"
        )
    run.log(f"journey: {journey['sighting_count']} sighting(s) across {journey['camera_count']} camera(s)")
    run.metrics["first_seen"] = journey["first_seen"]
    run.metrics["last_seen"] = journey["last_seen"]
    return journey


def stage_export_and_reconcile(run: Run):
    exports = {}
    for fmt, filename in (("json", "journey.json"), ("csv", "journey.csv"),
                           ("html", "journey.html"), ("pdf", "journey.pdf")):
        r = run.client.get(f"/api/vehicles/{run.plate}/journey/export", params={"format": fmt})
        if r.status_code != 200:
            raise RuntimeError(f"{fmt} export failed: HTTP {r.status_code}")
        path = run.output_dir / filename
        path.write_bytes(r.content)
        exports[fmt] = path
    run.log("json/csv/html/pdf all exported")

    report = json.loads(exports["json"].read_bytes())
    stops = report["stops"]
    rows = list(csv.DictReader(io.StringIO(exports["csv"].read_text())))
    if len(rows) != len(stops):
        raise RuntimeError(f"CSV has {len(rows)} rows, JSON has {len(stops)} stops")
    for jr, cr in zip(stops, rows):
        for key in ("camera_id", "camera_name", "seen_at", "department"):
            if str(jr[key]) != cr[key]:
                raise RuntimeError(f"JSON/CSV disagree on {key}: {jr[key]!r} != {cr[key]!r}")
    html = exports["html"].read_text()
    for stop in stops:
        if stop["camera_id"] not in html:
            raise RuntimeError(f"HTML export missing camera {stop['camera_id']}")
    if not exports["pdf"].read_bytes().startswith(b"%PDF"):
        raise RuntimeError("PDF export is not a valid PDF")
    run.log(f"all formats reconcile: {len(stops)} stop(s) agree across json/csv/html; pdf is valid")
    run.metrics["export_stop_count"] = len(stops)


def stage_record_metrics(run: Run):
    if "alert_created_at" in run.metrics and "first_seen" in run.metrics:
        alert_time = datetime.fromisoformat(run.metrics["alert_created_at"].replace("Z", "+00:00"))
        first_seen = datetime.fromisoformat(run.metrics["first_seen"].replace("Z", "+00:00"))
        run.metrics["detection_to_alert_latency_s"] = round((alert_time - first_seen).total_seconds(), 3)
        run.log(f"detection-to-alert latency: {run.metrics['detection_to_alert_latency_s']}s")

    worker_stats = {}
    for camera_id in run.resolved_camera_ids:
        status_path = _WORKER_LOG_DIR / f"camera-{camera_id}-vehicle.status.json"
        if status_path.exists():
            try:
                payload = json.loads(status_path.read_text())
                worker_stats[camera_id] = {
                    k: payload.get(k) for k in
                    ("fps", "dropped_frames", "reconnects", "queue_depth", "stream_lag_seconds",
                     "frames_processed", "uptime_seconds")
                    if k in payload
                }
            except (json.JSONDecodeError, OSError):
                pass
    run.metrics["workers"] = worker_stats
    run.log(f"captured worker telemetry for {len(worker_stats)} camera(s)")

    run.metrics["stage_durations_s"] = {s["name"]: s["duration_s"] for s in run.stages if "duration_s" in s}


def stage_cleanup(run: Run):
    for camera_id in run.resolved_camera_ids:
        r = run.client.put(f"/api/cameras/{camera_id}", json={"analytics_enabled": False})
        if r.status_code != 200:
            run.log(f"warning: could not disable analytics on {camera_id} (HTTP {r.status_code})")
    run.log("analytics disabled on all run cameras")

    if run.synthetic:
        seed_live_test.teardown(run.base_url)
        run.log("synthetic seed state torn down (cameras + watchlist entry removed)")
    else:
        run.log("real registry cameras left in place (not synthetic; nothing to tear down)")


def write_bundle(run: Run, status: str):
    run.output_dir.mkdir(parents=True, exist_ok=True)

    env_manifest = {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "git_commit": None,
    }
    try:
        env_manifest["git_commit"] = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=10,
        ).stdout.strip() or None
    except Exception:
        pass
    for pkg in ("fastapi", "sqlalchemy", "alembic"):
        try:
            import importlib.metadata
            env_manifest[pkg] = importlib.metadata.version(pkg)
        except Exception:
            env_manifest[pkg] = None

    # ultralytics/onnxruntime/torch live in the analytics worker's own
    # .venv, not this backend process's -- query that interpreter directly
    # rather than reporting a false "not installed".
    worker_python = _WORKER_DIR / ".venv" / "bin" / "python3"
    for pkg in ("ultralytics", "onnxruntime", "torch"):
        env_manifest[pkg] = None
        if worker_python.exists():
            try:
                proc = subprocess.run(
                    [str(worker_python), "-c", f"import importlib.metadata as m; print(m.version({pkg!r}))"],
                    capture_output=True, text=True, timeout=15,
                )
                if proc.returncode == 0:
                    env_manifest[pkg] = proc.stdout.strip()
            except Exception:
                pass
    (run.output_dir / "environment.json").write_text(json.dumps(env_manifest, indent=2))

    log_text = redact("\n".join(run.log_lines))
    (run.output_dir / "run.log").write_text(log_text)

    results = {
        "run_id": run.run_id,
        "status": status,
        "plate": run.plate,
        "requested_camera_ids": run.requested_camera_ids,
        "resolved_camera_ids": run.resolved_camera_ids,
        "synthetic_fixture": run.synthetic,
        "started_at": run.started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "stages": run.stages,
        "metrics": run.metrics,
    }
    (run.output_dir / "results.json").write_text(json.dumps(results, indent=2))

    checksums = {}
    for path in sorted(run.output_dir.iterdir()):
        if path.is_file() and path.name != "checksums.json":
            checksums[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (run.output_dir / "checksums.json").write_text(json.dumps(checksums, indent=2))

    readme = f"""# Section 5 live-test run {run.run_id}

Status: **{status}**
Plate: {run.plate}
Cameras requested: {', '.join(run.requested_camera_ids)}
Synthetic fixture: {run.synthetic}
Started: {run.started_at.isoformat()}

## Stages

{chr(10).join(f"- {s['name']}: {s['status']} ({s.get('duration_s', '?')}s)" for s in run.stages)}

## Contents

- `results.json` -- full machine-readable run record
- `run.log` -- redacted stage log (no raw feed URLs or secrets)
- `journey.json` / `journey.csv` / `journey.html` / `journey.pdf` -- journey export in every format
- `environment.json` -- interpreter, git commit, key package versions
- `checksums.json` -- sha256 of every file in this bundle
"""
    (run.output_dir / "README.md").write_text(readme)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plate", required=True)
    parser.add_argument("--camera-ids", required=True, help="comma-separated fixture roles or real camera_ids")
    parser.add_argument("--output", required=True, help="directory to write the evidence bundle into")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--wait-timeout", type=float, default=90.0,
                         help="seconds to wait for sightings/alerts before failing (default: 90)")
    args = parser.parse_args()

    camera_ids = [c.strip() for c in args.camera_ids.split(",") if c.strip()]
    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    run = Run(args.base_url, args.plate, camera_ids, output_dir, args.wait_timeout)
    print(f"Section 5 live-test run {run.run_id} -- plate {run.plate}, {len(camera_ids)} camera(s)\n")

    status = "passed"
    try:
        run.stage("readiness check")(stage_readiness)(run)
        run.stage("synchronise catalogue / seed fixture")(stage_sync_or_seed)(run)
        run.stage("verify stream reachability")(stage_verify_streams)(run)
        run.stage("activate plate on watchlist")(stage_activate_watchlist)(run)
        run.stage("enable analytics on selected cameras")(stage_enable_analytics)(run)
        run.stage("wait for sightings")(stage_wait_for_sightings)(run)
        run.stage("verify alert")(stage_verify_alert)(run)
        run.stage("query journey")(stage_query_journey)(run)
        run.stage("export and reconcile json/csv/html/pdf")(stage_export_and_reconcile)(run)
        run.stage("record timing and resource metrics")(stage_record_metrics)(run)
    except StageFailed as exc:
        status = "failed"
        print(f"\nFAILED: {exc}")
    finally:
        try:
            run.stage("stop workers and clean synthetic state")(stage_cleanup)(run)
        except StageFailed as exc:
            status = "failed"
            print(f"\ncleanup FAILED: {exc}")
        if run.client is not None:
            run.client.close()
        write_bundle(run, status)

    print(f"\n{'=' * 60}")
    print(f"Run {run.run_id}: {status.upper()} -- bundle written to {run.output_dir}")
    print(f"{'=' * 60}")
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
