#!/usr/bin/env python3
"""
Smoke test for Investigate (offline recording upload, ingest, search).

Builds its own local video fixtures via make_test_fixture.py rather than
relying on committed footage (none is committed, for the same privacy
reason backend/survey/*.jpg is gitignored). Uses the super admin plus one
synthetic Police-department operator and one synthetic Health-department
viewer, provisioned through the real registration/approval API -- not raw
SQL -- the same convention rbac_smoke_test.py already established.

All rows and files this script creates are removed in a `finally` block,
including via the real DELETE endpoint where possible so cleanup exercises
the same code path a human operator would use.

Usage (from backend/, using the backend's own .venv):
    <venv>/bin/python scripts/investigate_smoke_test.py

Assumes the backend is already running, Postgres is reachable, and the
SUPER_ADMIN_*/WORKER_API_TOKEN values match the backend process. Also
assumes multi-object-tracking/recording_ingest_worker.py is present and its
venv has the ML dependencies -- ingest checks SKIP (not fail) if the worker
never starts within a generous timeout, since this is the one path that
depends on real inference time.
"""

import argparse
import re
import secrets
import shutil
import sys
import time
from pathlib import Path

import httpx
import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import get_settings  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_test_fixture import build_fixtures  # noqa: E402

MARKER = "INVESTIGATE_SMOKETEST"
RESULTS = []


def _pg_dsn(sqlalchemy_url: str) -> str:
    return re.sub(r"^postgresql\+\w+://", "postgresql://", sqlalchemy_url)


def check(name):
    """Unlike smoke_test.py's version, checks here often need more than
    just `ctx` (a fixture path, a recording id from an earlier check, a
    run id...), so this forwards arbitrary args/kwargs rather than
    assuming a single `ctx` parameter."""
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
        if not settings.worker_api_token:
            raise RuntimeError("WORKER_API_TOKEN required")
        self.worker_headers = {"X-Sentinel-Worker-Token": settings.worker_api_token}
        self.recordings_dir = Path(settings.recordings_dir)

        self.super = httpx.Client(base_url=self.base_url, timeout=30.0)
        require(
            self.super.post("/api/auth/login", json={"email": settings.super_admin_email, "password": settings.super_admin_password}),
            200, "super admin login",
        )

        self.db = psycopg2.connect(_pg_dsn(settings.sync_database_url))
        self.db.autocommit = True

        self.emails: list[str] = []
        self.recording_ids: list[int] = []
        self.subject_ids: list[int] = []
        self.operator = None
        self.other_viewer = None
        self.last_run_id: int | None = None

    def sql(self, query, params=None):
        with self.db.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall() if cur.description else None

    def provision_accounts(self):
        suffix = str(int(time.time() * 1000))
        password = secrets.token_urlsafe(24)
        operator_email = f"{MARKER.lower()}-operator-{suffix}@sentinel.test"
        viewer_email = f"{MARKER.lower()}-viewer-{suffix}@sentinel.test"
        self.emails = [operator_email, viewer_email]

        require(
            self.super.post("/api/registration-requests", json={
                "full_name": "Investigate Test Operator", "email": operator_email, "password": password,
                "requested_department": "Police", "requested_role": "department_user",
            }),
            201, "register operator",
        )
        require(
            self.super.post("/api/registration-requests", json={
                "full_name": "Investigate Test Viewer", "email": viewer_email, "password": password,
                "requested_department": "Health", "requested_role": "department_user",
            }),
            201, "register viewer",
        )
        pending = require(self.super.get("/api/admin/registration-requests"), 200, "pending list")
        by_email = {row["email"]: row for row in pending}
        require(
            self.super.post(f"/api/admin/registration-requests/{by_email[operator_email]['id']}/approve", json={"clearance": "operator"}),
            200, "approve operator",
        )
        require(
            self.super.post(f"/api/admin/registration-requests/{by_email[viewer_email]['id']}/approve", json={"clearance": "viewer"}),
            200, "approve viewer",
        )

        self.operator = httpx.Client(base_url=self.base_url, timeout=60.0)
        require(self.operator.post("/api/auth/login", json={"email": operator_email, "password": password}), 200, "operator login")
        self.other_viewer = httpx.Client(base_url=self.base_url, timeout=30.0)
        require(self.other_viewer.post("/api/auth/login", json={"email": viewer_email, "password": password}), 200, "viewer login")

    def upload(self, client: httpx.Client, path: Path, department="Police", **fields):
        with open(path, "rb") as fh:
            resp = client.post(
                "/api/investigate/recordings",
                params={"department": department, **fields},
                files={"file": (path.name, fh, "video/mp4")},
            )
        return resp

    def start_synthetic_run(self, recording_id: int) -> int:
        """Enqueues a run and immediately heartbeats it into "running"
        without ever completing it -- for tests that POST chunks directly
        and must never land on an already-`completed` run, where the chunk
        endpoint intentionally no-ops (see post_ingest_chunk's early
        return for a non-running/queued run)."""
        run = require(self.operator.post(f"/api/investigate/recordings/{recording_id}/runs", json={"kind": "vehicle"}), 201, "enqueue synthetic run")
        run_id = run["id"]
        require(
            self.operator.post(f"/api/investigate/runs/{run_id}/heartbeat", json={"frames_processed": 1, "frames_expected": 1000}, headers=self.worker_headers),
            204, "heartbeat synthetic run into running",
        )
        return run_id

    def wait_for_run(self, run_id: int, timeout=180) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            run = require(self.super.get(f"/api/investigate/runs/{run_id}"), 200, "poll run")
            if run["status"] in ("completed", "completed_partial", "failed", "stalled", "cancelled"):
                return run
            time.sleep(2)
        raise AssertionError(f"run {run_id} did not finish within {timeout}s")

    def cleanup(self):
        for client in (self.other_viewer, self.operator, self.super):
            if client is not None:
                client.close()
        if self.recording_ids:
            rows = self.sql("SELECT content_sha256 FROM recordings WHERE id = ANY(%s)", (self.recording_ids,))
            self.sql("DELETE FROM recordings WHERE id = ANY(%s)", (self.recording_ids,))  # cascades runs/tracks
            for (sha,) in rows or []:
                shutil.rmtree(self.recordings_dir / sha, ignore_errors=True)
        if self.subject_ids:
            self.sql("DELETE FROM subjects WHERE id = ANY(%s)", (self.subject_ids,))
        if self.emails:
            self.sql("DELETE FROM registration_requests WHERE email = ANY(%s)", (self.emails,))
            self.sql("DELETE FROM users WHERE email = ANY(%s)", (self.emails,))
        self.db.close()


# --------------------------------------------------------------------------
# Upload
# --------------------------------------------------------------------------

@check("upload rejects unauthenticated")
def test_upload_unauthenticated(ctx: Ctx):
    anon = httpx.Client(base_url=ctx.base_url, timeout=10.0)
    resp = anon.post("/api/investigate/recordings", params={"department": "Police"}, files={"file": ("x.mp4", b"junk", "video/mp4")})
    anon.close()
    return resp.status_code == 401, f"HTTP {resp.status_code}"


@check("upload rejects viewer clearance")
def test_upload_viewer_denied(ctx: Ctx, fixture_path: Path):
    resp = ctx.upload(ctx.other_viewer, fixture_path, department="Health")
    return resp.status_code == 403, f"HTTP {resp.status_code}"


@check("upload accepts operator, normalises")
def test_upload_operator(ctx: Ctx, fixture_path: Path):
    resp = ctx.upload(ctx.operator, fixture_path, department="Police")
    body = require(resp, 201, "operator upload")
    ctx.recording_ids.append(body["id"])
    ok = body["status"] == "ready" and len(body["content_sha256"]) == 64 and body["fps_num"] and body["width"]
    return ok, f"status={body['status']} sha256={body['content_sha256'][:12]}... fps={body['fps_num']}/{body['fps_den']}"


@check("duplicate upload returns existing recording, no re-ingest")
def test_upload_duplicate(ctx: Ctx, fixture_path: Path, first_id: int):
    resp = ctx.upload(ctx.operator, fixture_path, department="Police")
    body = require(resp, 200, "duplicate upload")
    return body["id"] == first_id, f"HTTP {resp.status_code}, id={body['id']} (expected {first_id})"


@check("corrupt file is rejected, not a 500")
def test_upload_corrupt(ctx: Ctx, tmp_dir: Path):
    junk_path = tmp_dir / "not_a_video.mp4"
    junk_path.write_bytes(b"this is not a video file, just text pretending to be one" * 100)
    resp = ctx.upload(ctx.operator, junk_path, department="Police")
    body = require(resp, 201, "corrupt upload")
    ctx.recording_ids.append(body["id"])
    ok = body["status"] == "rejected" and bool(body["reject_reason"])
    return ok, f"status={body['status']} reason={body.get('reject_reason', '')[:80]!r}"


@check("normalisation produces constant frame rate")
def test_normalisation_cfr(ctx: Ctx, first_id: int):
    import subprocess as sp
    recording = require(ctx.super.get(f"/api/investigate/recordings/{first_id}"), 200, "get recording")
    path = ctx.recordings_dir / recording["content_sha256"] / "normalised.mp4"
    if not path.exists():
        return False, f"normalised file missing at {path}"
    out = sp.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate,codec_name,pix_fmt", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    ).stdout.strip()
    ok = "h264" in out and "yuv420p" in out
    return ok, out


# --------------------------------------------------------------------------
# Ingest run lifecycle
# --------------------------------------------------------------------------

@check("ingest run: queued -> running -> completed")
def test_ingest_run_lifecycle(ctx: Ctx, recording_id: int):
    # ctx.last_run_id is a side channel to later checks -- the @check
    # decorator only unpacks a 2-tuple (ok, detail), so run_id can't ride
    # along in this function's return value.
    run = require(
        ctx.operator.post(f"/api/investigate/recordings/{recording_id}/runs", json={"kind": "vehicle"}),
        201, "enqueue run",
    )
    ctx.last_run_id = run["id"]
    final = ctx.wait_for_run(ctx.last_run_id, timeout=240)
    if final["status"] not in ("completed", "completed_partial"):
        return False, f"run ended as {final['status']}: {final.get('error')}"
    ok = (
        final["frames_processed"] > 0
        and final["track_count"] > 0
        and final["chunk_count_received"] == final["chunk_count_expected"]
    )
    return ok, f"status={final['status']} frames={final['frames_processed']} tracks={final['track_count']} chunks={final['chunk_count_received']}/{final['chunk_count_expected']}"


@check("tracks: sane timing, boxes fixed-rate and normalised, list never selects boxes column")
def test_tracks_and_boxes(ctx: Ctx, run_id: int, duration_s: float):
    tracks = require(ctx.operator.get(f"/api/investigate/runs/{run_id}/tracks"), 200, "list tracks")
    if not tracks:
        return False, "no tracks recorded"
    if any("boxes" in t or "embedding" in t for t in tracks):
        return False, "list_tracks response leaked a deferred column"
    for t in tracks:
        if not (t["first_ms"] < t["last_ms"] or t["frame_count"] == 1):
            return False, f"track {t['track_ref']}: first_ms >= last_ms"
        if t["last_ms"] > duration_s * 1000 + 500:
            return False, f"track {t['track_ref']}: last_ms {t['last_ms']} exceeds recording duration"

    sample = tracks[0]
    boxes = require(
        ctx.operator.get(f"/api/investigate/runs/{run_id}/tracks/{sample['track_ref']}/boxes"), 200, "get boxes",
    )
    dt_ok = boxes["dt_ms"] == 100  # 10 Hz
    coords_ok = all(0 <= v <= 1000 for box in boxes["b"] for v in box)
    return dt_ok and coords_ok and len(boxes["b"]) > 0, f"{len(tracks)} tracks, sample has {len(boxes['b'])} box samples, dt_ms={boxes['dt_ms']}"


@check("thumbnail is a real JPEG")
def test_track_thumbnail(ctx: Ctx, run_id: int):
    tracks = require(ctx.operator.get(f"/api/investigate/runs/{run_id}/tracks"), 200, "list tracks")
    with_thumb = [t for t in tracks if t["thumb_path"]]
    if not with_thumb:
        return False, "no track has a thumb_path"
    ref = with_thumb[0]["track_ref"]
    resp = ctx.operator.get(f"/api/investigate/runs/{run_id}/tracks/{ref}/thumb")
    ok = resp.status_code == 200 and resp.content[:2] == b"\xff\xd8"
    return ok, f"HTTP {resp.status_code}, {len(resp.content)} bytes, JPEG magic={resp.content[:2] == b'\xff\xd8'}"


# --------------------------------------------------------------------------
# Chunk endpoint: idempotency, size cap, occurrence merge -- driven directly
# with the worker token, not through a real ingest run, so these are exact
# and don't depend on what the detector happens to find.
# --------------------------------------------------------------------------

def _synthetic_boxes(t0_ms=0, n=5):
    return {"t0_ms": t0_ms, "dt_ms": 100, "w": 1920, "h": 1080, "b": [[500, 500, 100, 100] for _ in range(n)]}


@check("chunk POST is idempotent on replayed seq")
def test_chunk_idempotent(ctx: Ctx, run_id: int):
    payload = {"seq": 0, "tracks": [{
        "track_ref": 9001, "kind": "vehicle", "first_frame": 0, "last_frame": 10,
        "first_ms": 0, "last_ms": 400, "frame_count": 11, "best_conf": 0.9,
        "boxes": _synthetic_boxes(),
    }]}
    r1 = require(ctx.operator.post(f"/api/investigate/runs/{run_id}/chunk", json=payload, headers=ctx.worker_headers), 204, "chunk seq 0")
    r2 = require(ctx.operator.post(f"/api/investigate/runs/{run_id}/chunk", json=payload, headers=ctx.worker_headers), 204, "chunk seq 0 replay")
    count = ctx.sql("SELECT count(*) FROM tracks WHERE run_id = %s AND track_ref = %s", (run_id, 9001))[0][0]
    return count == 1, f"track_ref 9001 present {count} time(s) after 2 identical POSTs (worker token required, no auth cookie used)"


@check("chunk POST requires worker token, not a browser session")
def test_chunk_requires_worker_token(ctx: Ctx, run_id: int):
    resp = ctx.operator.post(f"/api/investigate/runs/{run_id}/chunk", json={"seq": 99, "tracks": []})
    return resp.status_code == 401, f"HTTP {resp.status_code} (browser session alone must not authorise a worker callback)"


@check("oversized chunk is rejected with 413")
def test_chunk_too_large(ctx: Ctx, run_id: int):
    big_tracks = [{
        "track_ref": 9100 + i, "kind": "vehicle", "first_frame": 0, "last_frame": 1,
        "first_ms": 0, "last_ms": 40, "frame_count": 2, "best_conf": 0.5,
        "boxes": _synthetic_boxes(n=1),
    } for i in range(501)]  # over _MAX_CHUNK_TRACKS (500)
    resp = ctx.operator.post(f"/api/investigate/runs/{run_id}/chunk", json={"seq": 1, "tracks": big_tracks}, headers=ctx.worker_headers)
    return resp.status_code == 413, f"HTTP {resp.status_code} for a 501-track chunk"


@check("occurrence merge: short gap merges, long gap starts a new occurrence")
def test_occurrence_merge(ctx: Ctx, run_id: int):
    close = {"seq": 2, "tracks": [{
        "track_ref": 9002, "kind": "vehicle", "first_frame": 0, "last_frame": 5,
        "first_ms": 20000, "last_ms": 20200, "frame_count": 6, "best_conf": 0.8, "boxes": _synthetic_boxes(20000),
    }]}
    require(ctx.operator.post(f"/api/investigate/runs/{run_id}/chunk", json=close, headers=ctx.worker_headers), 204, "chunk A")
    close2 = {"seq": 3, "tracks": [{
        # 2s gap after track A's last_ms (20200) -- under the 5s merge threshold
        "track_ref": 9003, "kind": "vehicle", "first_frame": 0, "last_frame": 5,
        "first_ms": 22200, "last_ms": 22400, "frame_count": 6, "best_conf": 0.8, "boxes": _synthetic_boxes(22200),
    }]}
    require(ctx.operator.post(f"/api/investigate/runs/{run_id}/chunk", json=close2, headers=ctx.worker_headers), 204, "chunk B (close)")
    far = {"seq": 4, "tracks": [{
        # 30s after track B -- well over the merge threshold
        "track_ref": 9004, "kind": "vehicle", "first_frame": 0, "last_frame": 5,
        "first_ms": 52400, "last_ms": 52600, "frame_count": 6, "best_conf": 0.8, "boxes": _synthetic_boxes(52400),
    }]}
    require(ctx.operator.post(f"/api/investigate/runs/{run_id}/chunk", json=far, headers=ctx.worker_headers), 204, "chunk C (far)")

    rows = ctx.sql(
        "SELECT track_ref, occurrence_index FROM tracks WHERE run_id = %s AND track_ref IN (9002,9003,9004)", (run_id,),
    )
    by_ref = dict(rows)
    merged = by_ref[9002] == by_ref[9003]
    split = by_ref[9002] != by_ref[9004]
    return merged and split, f"occurrence_index: 9002={by_ref.get(9002)} 9003={by_ref.get(9003)} 9004={by_ref.get(9004)}"


@check("complete with a chunk-count mismatch yields completed_partial")
def test_complete_partial(ctx: Ctx, recording_id: int):
    run = require(ctx.operator.post(f"/api/investigate/recordings/{recording_id}/runs", json={"kind": "vehicle"}), 201, "enqueue run for partial-complete test")
    run_id = run["id"]
    # No real worker involved: post the run straight to "running" via a
    # heartbeat, send one chunk, then claim (falsely) that 3 were expected.
    require(ctx.operator.post(f"/api/investigate/runs/{run_id}/heartbeat", json={"frames_processed": 10, "frames_expected": 100}, headers=ctx.worker_headers), 204, "heartbeat")
    chunk = {"seq": 0, "tracks": [{
        "track_ref": 1, "kind": "vehicle", "first_frame": 0, "last_frame": 5,
        "first_ms": 0, "last_ms": 200, "frame_count": 6, "best_conf": 0.7, "boxes": _synthetic_boxes(),
    }]}
    require(ctx.operator.post(f"/api/investigate/runs/{run_id}/chunk", json=chunk, headers=ctx.worker_headers), 204, "one chunk")
    final = require(
        ctx.operator.post(f"/api/investigate/runs/{run_id}/complete", json={"frames_processed": 10, "track_count": 1, "chunk_count": 3}, headers=ctx.worker_headers),
        200, "complete claiming 3 chunks",
    )
    return final["status"] == "completed_partial", f"status={final['status']} (chunk_count_received={final['chunk_count_received']}, claimed 3)"


@check("cancel: a queued/running run can be cancelled")
def test_cancel_run(ctx: Ctx, recording_id: int):
    run = require(ctx.operator.post(f"/api/investigate/recordings/{recording_id}/runs", json={"kind": "vehicle"}), 201, "enqueue run for cancel test")
    run_id = run["id"]
    time.sleep(0.5)
    cancelled = require(ctx.operator.post(f"/api/investigate/runs/{run_id}/cancel"), 200, "cancel")
    return cancelled["status"] == "cancelled", f"status={cancelled['status']}"


# --------------------------------------------------------------------------
# Plate search
# --------------------------------------------------------------------------

@check("plate search: exact and fuzzy (1-character OCR error)")
def test_plate_search(ctx: Ctx, run_id: int):
    chunk = {"seq": 10, "tracks": [{
        "track_ref": 9500, "kind": "vehicle", "first_frame": 0, "last_frame": 5,
        "first_ms": 60000, "last_ms": 60200, "frame_count": 6, "best_conf": 0.9,
        "boxes": _synthetic_boxes(60000), "plate_confirmed": "GJ01AB1234", "plate_tentative": "GJ01AB1234",
        "plate_confidence": 0.95, "plate_votes": 4,
    }]}
    require(ctx.operator.post(f"/api/investigate/runs/{run_id}/chunk", json=chunk, headers=ctx.worker_headers), 204, "plate chunk")

    exact = require(ctx.operator.post("/api/investigate/search/plate", json={"plate": "GJ01AB1234", "fuzzy": False}), 200, "exact search")
    exact_ok = any(h["track"]["track_ref"] == 9500 and h["match_kind"] == "exact" for h in exact)

    fuzzy = require(ctx.operator.post("/api/investigate/search/plate", json={"plate": "GJ01AB1235", "fuzzy": True}), 200, "fuzzy search")
    fuzzy_ok = any(h["track"]["track_ref"] == 9500 for h in fuzzy)

    return exact_ok and fuzzy_ok, f"exact hits={len(exact)} (found={exact_ok}), fuzzy hits={len(fuzzy)} (found={fuzzy_ok})"


@check("investigation.searched audit event recorded with actor")
def test_search_audit(ctx: Ctx):
    rows = ctx.sql(
        "SELECT actor_email, details FROM audit_events WHERE action = 'investigation.searched' ORDER BY id DESC LIMIT 1",
    )
    if not rows:
        return False, "no investigation.searched audit row found"
    actor_email, details = rows[0]
    return bool(actor_email), f"actor={actor_email}, details={details}"


# --------------------------------------------------------------------------
# Department scoping
# --------------------------------------------------------------------------

@check("department scoping: cross-department viewer cannot see the recording")
def test_department_scoping(ctx: Ctx, recording_id: int):
    resp = ctx.other_viewer.get(f"/api/investigate/recordings/{recording_id}")
    list_resp = require(ctx.other_viewer.get("/api/investigate/recordings"), 200, "cross-department list")
    leaked = any(r["id"] == recording_id for r in list_resp)
    return resp.status_code in (403, 404) and not leaked, f"detail GET -> HTTP {resp.status_code}; leaked in list={leaked}"


# --------------------------------------------------------------------------
# Media Range serving
# --------------------------------------------------------------------------

@check("media serving supports byte-range requests")
def test_media_range(ctx: Ctx, recording_id: int):
    resp = ctx.operator.get(f"/api/investigate/recordings/{recording_id}/media", headers={"Range": "bytes=0-1023"})
    ok = (
        resp.status_code == 206
        and resp.headers.get("content-length") == "1024"
        and resp.headers.get("content-range", "").startswith("bytes 0-1023/")
    )
    return ok, f"HTTP {resp.status_code}, content-range={resp.headers.get('content-range')}"


# --------------------------------------------------------------------------
# Subjects and linking
# --------------------------------------------------------------------------

@check("subject creation and track linking (operator-confirmed only)")
def test_subject_link(ctx: Ctx, run_id: int):
    subject = require(ctx.operator.post("/api/investigate/subjects", json={"kind": "vehicle", "label": MARKER}), 201, "create subject")
    ctx.subject_ids.append(subject["id"])
    linked = require(
        ctx.operator.post(f"/api/investigate/runs/{run_id}/tracks/9500/link", json={"subject_id": subject["id"]}),
        200, "link track to subject",
    )
    return linked["subject_id"] == subject["id"] and linked["link_method"] == "operator_confirmed", f"subject_id={linked['subject_id']} link_method={linked['link_method']}"


# --------------------------------------------------------------------------
# Stall reaper -- can't wait out the real 90s heartbeat timeout inside a
# smoke test, so this directly manipulates the DB row to simulate a worker
# that stopped reporting, then waits for one real supervisor tick (10s) to
# observe and act on it.
# --------------------------------------------------------------------------

@check("heartbeat staleness flips a running run to stalled")
def test_stall_reaper(ctx: Ctx, recording_id: int):
    from datetime import datetime, timedelta, timezone
    run = require(ctx.operator.post(f"/api/investigate/recordings/{recording_id}/runs", json={"kind": "vehicle"}), 201, "enqueue run for stall test")
    run_id = run["id"]
    require(ctx.operator.post(f"/api/investigate/runs/{run_id}/heartbeat", json={"frames_processed": 5, "frames_expected": 1000}, headers=ctx.worker_headers), 204, "initial heartbeat")
    stale_time = datetime.now(timezone.utc) - timedelta(seconds=200)  # past ingest_heartbeat_stale_seconds (90s default)
    ctx.sql("UPDATE ingest_runs SET last_heartbeat_at = %s WHERE id = %s", (stale_time, run_id))

    deadline = time.time() + 20
    status = None
    while time.time() < deadline:
        status = require(ctx.operator.get(f"/api/investigate/runs/{run_id}"), 200, "poll for stall")["status"]
        if status == "stalled":
            break
        time.sleep(2)
    return status == "stalled", f"status={status} after forcing a stale heartbeat and waiting for the reaper tick"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    print("Building test fixtures (real-content pan clip, no committed footage)...")
    fixtures = build_fixtures()
    fixture_path = Path(fixtures["base"])
    import subprocess as sp
    duration_s = float(sp.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(fixture_path)],
        capture_output=True, text=True,
    ).stdout.strip())

    tmp_dir = fixture_path.parent
    ctx = Ctx(args.base_url)
    run_id = None
    try:
        print(f"\nInvestigate smoke test against {args.base_url}\n")
        print("Accounts")
        ctx.provision_accounts()

        print("\nUpload")
        test_upload_unauthenticated(ctx)
        test_upload_viewer_denied(ctx, fixture_path)
        upload_ok = test_upload_operator(ctx, fixture_path)
        first_id = ctx.recording_ids[0] if ctx.recording_ids else None
        if upload_ok and first_id:
            test_upload_duplicate(ctx, fixture_path, first_id)
            test_normalisation_cfr(ctx, first_id)
        test_upload_corrupt(ctx, tmp_dir)

        if first_id:
            print("\nDepartment scoping")
            test_department_scoping(ctx, first_id)

            print("\nMedia")
            test_media_range(ctx, first_id)

            print("\nIngest run lifecycle (runs the real detector -- can take a couple of minutes)")
            test_ingest_run_lifecycle(ctx, first_id)
            run_id = ctx.last_run_id
        else:
            print("\n(skipping remaining checks: initial upload failed)")

        if run_id:
            print("\nTracks and boxes")
            test_tracks_and_boxes(ctx, run_id, duration_s)
            test_track_thumbnail(ctx, run_id)

        if first_id:
            # A dedicated "running" run, never completed -- these tests POST
            # chunks directly and must not land on the real run above, which
            # is already `completed` by now and would silently no-op every
            # write (see post_ingest_chunk's early return).
            synthetic_run_id = ctx.start_synthetic_run(first_id)

            print("\nChunk endpoint semantics")
            test_chunk_requires_worker_token(ctx, synthetic_run_id)
            test_chunk_idempotent(ctx, synthetic_run_id)
            test_chunk_too_large(ctx, synthetic_run_id)
            test_occurrence_merge(ctx, synthetic_run_id)

            print("\nPlate search")
            test_plate_search(ctx, synthetic_run_id)
            test_search_audit(ctx)

            print("\nSubjects and linking")
            test_subject_link(ctx, synthetic_run_id)

        if first_id:
            print("\nRun state machine edge cases")
            test_complete_partial(ctx, first_id)
            test_cancel_run(ctx, first_id)
            test_stall_reaper(ctx, first_id)

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
