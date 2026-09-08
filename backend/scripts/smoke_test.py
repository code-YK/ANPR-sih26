#!/usr/bin/env python3
"""
Smoke test covering selected API flows from Model 1 (registry, catalogue sync,
gap analysis) and Model 2 (ANPR ingestion, watchlist, alerts, journey, and an
optional analytics worker lifecycle check).

The default checks create synthetic rows, but they are not fully offline: the
catalogue-sync check contacts the configured sandbox and may skip when it is
unavailable. The --live test is opt-in and inherently best-effort: the sandbox's
camera availability is intermittent (we hit this directly -- camera 21
timed out one run, worked minutes later), so it probes for a working camera
first rather than assuming a fixed id, and reports a mechanical pass (worker
connected) separately from a full pass (a plate was actually confirmed).

All test data this script creates is cleaned up afterward and is
distinguishable by a "SMOKETEST" marker. Catalogue sync may still update
catalogue-sourced registry rows, so run this only against an intended test
database and configured environment.

Usage (from backend/, using the backend's own .venv):
    <venv>/bin/python scripts/smoke_test.py                        # fast tests only
    <venv>/bin/python scripts/smoke_test.py --live                 # + live camera pipeline
    <venv>/bin/python scripts/smoke_test.py --live --camera-id 10  # pin a camera instead of probing
    <venv>/bin/python scripts/smoke_test.py --base-url http://127.0.0.1:8000

Assumes the backend is already running, Postgres is reachable, and the
SUPER_ADMIN_* and WORKER_API_TOKEN values match the backend process.
"""

import argparse
import csv
import io
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import get_settings  # noqa: E402

MARKER = "SMOKETEST"


def _pg_dsn(sqlalchemy_url: str) -> str:
    """postgresql+psycopg2://... -> postgresql://... (psycopg2.connect wants
    a plain DSN, not a SQLAlchemy dialect URL)."""
    return re.sub(r"^postgresql\+\w+://", "postgresql://", sqlalchemy_url)


class Ctx:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(base_url=self.base_url, timeout=30.0)
        settings = get_settings()
        if not settings.super_admin_email or not settings.super_admin_password:
            raise RuntimeError("SUPER_ADMIN_EMAIL and SUPER_ADMIN_PASSWORD are required for smoke tests")
        if not settings.worker_api_token:
            raise RuntimeError("WORKER_API_TOKEN is required for smoke tests")
        self.worker_headers = {"X-Sentinel-Worker-Token": settings.worker_api_token}
        login = self.client.post(
            "/api/auth/login",
            json={"email": settings.super_admin_email, "password": settings.super_admin_password},
        )
        if login.status_code != 200:
            raise RuntimeError(f"super-admin login failed with HTTP {login.status_code}: {login.text[:200]}")
        audit_page = self.client.get("/api/admin/audit-events", params={"limit": 1})
        if audit_page.status_code != 200:
            raise RuntimeError(f"audit baseline failed with HTTP {audit_page.status_code}: {audit_page.text[:200]}")
        self.audit_total_at_start = audit_page.json()["total"]
        self.db = psycopg2.connect(_pg_dsn(settings.sync_database_url))
        self.db.autocommit = True

    def close(self):
        self.client.close()
        self.db.close()

    def sql(self, query, params=None):
        with self.db.cursor() as cur:
            cur.execute(query, params)
            if cur.description:
                return cur.fetchall()
            return None

    def current_run_audit_events(self):
        response = self.client.get("/api/admin/audit-events", params={"limit": 1000})
        if response.status_code != 200:
            raise RuntimeError(f"audit log failed with HTTP {response.status_code}: {response.text[:200]}")
        page = response.json()
        new_event_count = page["total"] - self.audit_total_at_start
        if not 0 <= new_event_count <= len(page["events"]):
            raise RuntimeError(
                f"current run produced {new_event_count} audit events, but the page contains {len(page['events'])}"
            )
        return page["events"][:new_event_count]


RESULTS = []


def check(name):
    """Decorator: run a test, catch anything, record (name, ok, detail)."""
    def wrap(fn):
        def runner(ctx):
            try:
                ok, detail = fn(ctx)
            except Exception as exc:  # noqa: BLE001 - a test crashing is a failure, not a crash
                ok, detail = False, f"raised {type(exc).__name__}: {exc}"
            RESULTS.append((name, ok, detail))
            # ok is None for a check that could not run for a reason that
            # isn't a defect (an upstream outage) -- reported, but not a
            # failure, so a red run always means something we can fix.
            status = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
            print(f"  [{status}] {name} - {detail}")
            return ok
        runner.__name__ = fn.__name__
        return runner
    return wrap


# --------------------------------------------------------------------------
# Model 1: registry, onboarding, gap analysis
# --------------------------------------------------------------------------

@check("health check")
def test_health(ctx):
    unauthenticated = httpx.get(f"{ctx.base_url}/api/health", timeout=10.0)
    if unauthenticated.status_code != 401:
        return False, f"unauthenticated health should 401, got {unauthenticated.status_code}"
    r = ctx.client.get("/api/health")
    return r.status_code == 200 and r.json().get("status") == "ok", f"unauthenticated 401; authenticated HTTP {r.status_code}"


@check("camera list")
def test_camera_list(ctx):
    r = ctx.client.get("/api/cameras")
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}"
    cameras = r.json()
    return len(cameras) >= 1, f"{len(cameras)} camera(s)"


@check("camera detail + filters")
def test_camera_detail(ctx):
    cameras = ctx.client.get("/api/cameras").json()
    if not cameras:
        return False, "no cameras in registry to test against"
    cam_id = cameras[0]["camera_id"]
    r = ctx.client.get(f"/api/cameras/{cam_id}")
    if r.status_code != 200 or r.json()["camera_id"] != cam_id:
        return False, f"GET /api/cameras/{cam_id} -> HTTP {r.status_code}"
    r404 = ctx.client.get("/api/cameras/does-not-exist")
    if r404.status_code != 404:
        return False, f"unknown camera_id should 404, got {r404.status_code}"
    r_live = ctx.client.get("/api/cameras", params={"is_live": "true"})
    return r_live.status_code == 200, f"detail ok, 404 ok, ?is_live=true -> HTTP {r_live.status_code}"


@check("manual camera create/update lifecycle")
def test_manual_camera_lifecycle(ctx):
    created_ids = []
    try:
        r = ctx.client.post("/api/cameras", json={
            "name": f"{MARKER} camera", "location_text": f"{MARKER} location, nowhere",
        })
        if r.status_code != 201:
            return False, f"metadata-only create -> HTTP {r.status_code}: {r.text[:200]}"
        cam = r.json()
        created_ids.append(cam["camera_id"])
        if not cam["camera_id"].startswith("manual-"):
            return False, f"expected manual-N id, got {cam['camera_id']!r}"
        if cam["stream_available"] is not False:
            return False, "metadata-only camera should have stream_available=false"

        r2 = ctx.client.post("/api/cameras", json={
            "name": f"{MARKER} camera 2", "location_text": f"{MARKER} location 2",
            "latitude": 23.03, "longitude": 72.58,
        })
        if r2.status_code != 201:
            return False, f"create with lat/lng -> HTTP {r2.status_code}"
        cam2 = r2.json()
        created_ids.append(cam2["camera_id"])
        if cam2["geocode_confidence"] != "exact":
            return False, f"lat/lng at create should imply geocode_confidence=exact, got {cam2['geocode_confidence']!r}"

        r3 = ctx.client.put(f"/api/cameras/{cam['camera_id']}", json={
            "department": "Police", "ownership": "government", "camera_type": "fixed",
            "metadata_confidence": "confirmed",
        })
        if r3.status_code != 200 or r3.json()["department"] != "Police":
            return False, f"PUT operator fields -> HTTP {r3.status_code}"

        r_bad = ctx.client.put(f"/api/cameras/{cam['camera_id']}", json={"department": "NotReal"})
        if r_bad.status_code != 422:
            return False, f"invalid department should 422, got {r_bad.status_code}"

        # Metadata-only camera has no endpoint, so a single-camera probe is a
        # deterministic, offline-safe transition to an `offline` observation.
        probe = ctx.client.post("/api/probe", params={"camera_id": cam["camera_id"]})
        if probe.status_code != 200 or probe.json()["results"][0]["transport_ok"] != "none":
            return False, f"metadata-only probe should be offline, got {probe.status_code}: {probe.text[:200]}"
        history = ctx.client.get(f"/api/cameras/{cam['camera_id']}/health-history")
        if history.status_code != 200 or not history.json():
            return False, f"health history -> HTTP {history.status_code}"
        observation = history.json()[0]
        if observation["status"] != "offline" or observation["transport_ok"] != "none" or not observation["reason"]:
            return False, f"offline health observation wrong: {observation}"

        opened = ctx.client.post(
            f"/api/cameras/{cam['camera_id']}/maintenance-work-orders",
            json={"summary": f"{MARKER} restore transport", "note": "Initial offline assessment"},
        )
        if opened.status_code != 201:
            return False, f"maintenance work-order create -> HTTP {opened.status_code}: {opened.text[:200]}"
        work_order = opened.json()
        if work_order["status"] != "open" or [event["event_type"] for event in work_order["events"]] != ["created"]:
            return False, f"maintenance create history wrong: {work_order}"

        progressed = ctx.client.patch(
            f"/api/cameras/{cam['camera_id']}/maintenance-work-orders/{work_order['id']}",
            json={"status": "in_progress", "note": "Technician assigned"},
        )
        if progressed.status_code != 200 or progressed.json()["status"] != "in_progress":
            return False, f"maintenance work-order progress -> HTTP {progressed.status_code}: {progressed.text[:200]}"
        no_op = ctx.client.patch(
            f"/api/cameras/{cam['camera_id']}/maintenance-work-orders/{work_order['id']}",
            json={"status": "in_progress"},
        )
        if no_op.status_code != 422:
            return False, f"no-op maintenance update should be rejected, got {no_op.status_code}"
        resolved = ctx.client.patch(
            f"/api/cameras/{cam['camera_id']}/maintenance-work-orders/{work_order['id']}",
            json={"status": "resolved", "note": "Metadata remediation complete"},
        )
        if resolved.status_code != 200 or resolved.json()["status"] != "resolved" or not resolved.json()["closed_at"]:
            return False, f"maintenance work-order resolution wrong: {resolved.text[:200]}"
        if [event["event_type"] for event in resolved.json()["events"]] != ["created", "status_changed", "status_changed"]:
            return False, f"maintenance event history wrong: {resolved.json()}"
        immutable = ctx.client.patch(
            f"/api/cameras/{cam['camera_id']}/maintenance-work-orders/{work_order['id']}",
            json={"note": "This must not be accepted"},
        )
        if immutable.status_code != 409:
            return False, f"resolved work order should be immutable, got {immutable.status_code}"
        listed_work_orders = ctx.client.get(f"/api/cameras/{cam['camera_id']}/maintenance-work-orders")
        if listed_work_orders.status_code != 200 or listed_work_orders.json()[0]["id"] != work_order["id"]:
            return False, f"maintenance work-order history -> HTTP {listed_work_orders.status_code}: {listed_work_orders.text[:200]}"

        searched = ctx.client.get("/api/cameras", params={"q": "SMOKETEST camera", "camera_type": "fixed"})
        if searched.status_code != 200:
            return False, f"camera search -> HTTP {searched.status_code}"
        if [row["camera_id"] for row in searched.json()] != [cam["camera_id"]]:
            return False, f"camera search/type filter returned wrong rows: {searched.json()}"

        exported = ctx.client.get("/api/cameras/export", params={"q": "SMOKETEST camera", "camera_type": "fixed"})
        if exported.status_code != 200 or "text/csv" not in exported.headers.get("content-type", ""):
            return False, f"camera CSV export -> HTTP {exported.status_code}"
        export_rows = list(csv.DictReader(io.StringIO(exported.text)))
        if len(export_rows) != 1 or export_rows[0]["camera_id"] != cam["camera_id"]:
            return False, f"camera CSV export contained wrong rows: {export_rows}"
        if {"rtsp_url", "hls_url", "webrtc_url"} & set(export_rows[0]):
            return False, "camera CSV export exposes source endpoint fields"

        json_export = ctx.client.get(
            "/api/cameras/export",
            params={"q": "SMOKETEST camera", "camera_type": "fixed", "format": "json"},
        )
        if json_export.status_code != 200 or "application/json" not in json_export.headers.get("content-type", ""):
            return False, f"camera JSON export -> HTTP {json_export.status_code}"
        json_rows = json_export.json()
        if len(json_rows) != 1 or json_rows[0]["camera_id"] != cam["camera_id"]:
            return False, f"camera JSON export contained wrong rows: {json_rows}"
        if {"rtsp_url", "hls_url", "webrtc_url"} & set(json_rows[0]):
            return False, "camera JSON export exposes source endpoint fields"

        audit = ctx.current_run_audit_events()
        audited = {(event["action"], event["target_id"]) for event in audit}
        if ("camera.created", cam["camera_id"]) not in audited or ("camera.updated", cam["camera_id"]) not in audited:
            return False, "camera create/update audit events missing"
        if ("camera.probed", cam["camera_id"]) not in audited:
            return False, "camera probe audit event missing"
        if ("camera_maintenance.created", str(work_order["id"])) not in audited or (
            "camera_maintenance.updated", str(work_order["id"])
        ) not in audited:
            return False, "maintenance work-order audit events missing"
        if not any(
            event["action"] == "camera_registry.exported"
            and event["result"] == "success"
            and event["details"] == {
                "rows": 1,
                "department": None,
                "camera_type": "fixed",
                "anpr_viable": None,
                "is_live": None,
                "q": "SMOKETEST camera",
                "format": "json",
            }
            for event in audit
        ):
            return False, "camera JSON export audit event missing"

        return True, f"created {created_ids}, health/maintenance history/search/CSV+JSON export/audit all correct"
    finally:
        for cid in created_ids:
            ctx.sql("DELETE FROM cameras WHERE camera_id = %s", (cid,))


@check("bulk CSV import (valid + invalid rows)")
def test_bulk_import(ctx):
    r = ctx.client.post("/api/cameras", json={
        "name": f"{MARKER} bulk target", "location_text": f"{MARKER} bulk location",
    })
    if r.status_code != 201:
        return False, f"bulk target create -> HTTP {r.status_code}"
    cam_id = r.json()["camera_id"]
    created_id = None
    try:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "camera_id", "name", "location_text", "department", "ownership",
            "metadata_confidence", "latitude", "longitude",
        ])
        writer.writerow([cam_id, "", "", "GSRTC", "government", "confirmed", "", ""])
        writer.writerow([
            "", f"{MARKER} bulk created", f"{MARKER} bulk created location",
            "Police", "government", "confirmed", "23.03", "72.58",
        ])
        writer.writerow(["", "", f"{MARKER} missing name", "Police", "government", "confirmed", "", ""])
        writer.writerow(["does-not-exist", "", "", "Police", "government", "confirmed", "", ""])
        writer.writerow([cam_id, "", "", "NotReal", "government", "confirmed", "", ""])
        files = {"file": ("bulk.csv", buf.getvalue(), "text/csv")}
        r = ctx.client.post("/api/cameras/bulk", files=files)
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        result = r.json()
        # Existing ids update in place. A blank id creates a server-assigned
        # manual-N camera; blank required creation fields, an unknown supplied
        # id, and an invalid department each fail independently.
        created_rows = [row for row in result["results"] if row["status"] == "created"]
        if len(created_rows) != 1:
            return False, f"expected one created row, got {created_rows}"
        created_id = created_rows[0]["camera_id"]
        ok = (
            result["total_rows"] == 5
            and result["created"] == 1
            and result["updated"] == 1
            and result["failed"] == 3
            and created_id.startswith("manual-")
        )
        created = ctx.client.get(f"/api/cameras/{created_id}")
        if created.status_code != 200:
            return False, f"created bulk camera detail -> HTTP {created.status_code}"
        created_camera = created.json()
        if (
            created_camera["name"] != f"{MARKER} bulk created"
            or created_camera["department"] != "Police"
            or created_camera["geocode_confidence"] != "exact"
        ):
            return False, f"created bulk camera fields wrong: {created_camera}"
        audit = ctx.current_run_audit_events()
        if not any(
            event["action"] == "camera.bulk_updated"
            and event["result"] == "partial"
            and event["details"] == {"total_rows": 5, "created": 1, "updated": 1, "failed": 3}
            for event in audit
        ):
            return False, "partial bulk-update audit event missing"
        return ok, (
            f"{result['created']} created, {result['updated']} updated, "
            f"{result['failed']} failed of {result['total_rows']}"
        )
    finally:
        for camera_id in (created_id, cam_id):
            if camera_id:
                ctx.sql("DELETE FROM cameras WHERE camera_id = %s", (camera_id,))


@check("catalogue sync (idempotent)")
def test_sync(ctx):
    before = ctx.client.get("/api/cameras").json()
    r = ctx.client.post("/api/sync")
    if r.status_code == 502:
        # The sandbox catalogue is down. That is a real condition to report,
        # but it is not a defect in this codebase -- failing the run for it
        # would train us to ignore a red smoke test during every outage.
        return None, "SKIPPED: sandbox catalogue API unavailable (upstream 502)"
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}"
    result = r.json()
    after = ctx.client.get("/api/cameras").json()
    return (result["fetched"] >= 1 and len(after) >= len(before)),\
        f"fetched={result['fetched']} inserted={result['inserted']} updated={result['updated']}"


@check("gap analysis (JSON + HTML + PDF)")
def test_gap_analysis(ctx):
    r = ctx.client.get("/api/gap-analysis")
    if r.status_code != 200:
        return False, f"JSON HTTP {r.status_code}"
    body = r.json()
    for key in ("capability_gaps", "coverage", "health_gaps"):
        if key not in body:
            return False, f"missing {key!r} in JSON response"

    r_html = ctx.client.get("/api/gap-analysis/export", params={"format": "html"})
    if r_html.status_code != 200 or "text/html" not in r_html.headers.get("content-type", ""):
        return False, f"HTML export HTTP {r_html.status_code}"

    r_pdf = ctx.client.get("/api/gap-analysis/export", params={"format": "pdf"})
    if r_pdf.status_code != 200 or "application/pdf" not in r_pdf.headers.get("content-type", ""):
        return False, f"PDF export HTTP {r_pdf.status_code}"

    return True, f"JSON+HTML+PDF all 200 ({len(r_pdf.content)} byte PDF)"


# --------------------------------------------------------------------------
# Model 2: watchlist, sightings ingestion, matching, alerts
# --------------------------------------------------------------------------

@check("watchlist CRUD")
def test_watchlist_crud(ctx):
    plate = f"{MARKER}01"
    try:
        r = ctx.client.post("/api/watchlist", json={
            "raw_value": plate, "reason_code": "test", "severity": "high",
        })
        if r.status_code != 201:
            return False, f"create HTTP {r.status_code}"
        entry_id = r.json()["id"]
        if r.json()["normalised_value"] != plate:
            return False, "normalisation mismatch on a clean plate"

        r_bad = ctx.client.post("/api/watchlist", json={"raw_value": "x", "severity": "extreme"})
        if r_bad.status_code != 422:
            return False, f"invalid severity should 422, got {r_bad.status_code}"

        r_list = ctx.client.get("/api/watchlist", params={"plate": plate})
        if not any(e["id"] == entry_id for e in r_list.json()):
            return False, "created entry not found by ?plate= filter"

        r_upd = ctx.client.put(f"/api/watchlist/{entry_id}", json={"severity": "low"})
        if r_upd.status_code != 200 or r_upd.json()["severity"] != "low":
            return False, f"update HTTP {r_upd.status_code}"

        r_del = ctx.client.delete(f"/api/watchlist/{entry_id}")
        if r_del.status_code != 204:
            return False, f"delete HTTP {r_del.status_code}"
        r_gone = ctx.client.get("/api/watchlist", params={"plate": plate})
        if any(e["id"] == entry_id for e in r_gone.json()):
            return False, "entry still present after delete"

        return True, "create/list/update/delete + validation all correct"
    finally:
        ctx.sql("DELETE FROM watchlist_entries WHERE normalised_value = %s", (plate,))


@check("watchlist bulk CSV import")
def test_watchlist_bulk(ctx):
    plate = f"{MARKER}02"
    try:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["raw_value", "reason_code", "severity"])
        writer.writerow([plate, "test", "medium"])
        writer.writerow(["", "test", "medium"])  # missing raw_value -> error row
        files = {"file": ("watchlist.csv", buf.getvalue(), "text/csv")}
        r = ctx.client.post("/api/watchlist/bulk", files=files)
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        result = r.json()
        return result["added"] == 1 and result["failed"] == 1, \
            f"{result['added']} added, {result['failed']} failed of {result['total_rows']}"
    finally:
        ctx.sql("DELETE FROM watchlist_entries WHERE normalised_value = %s", (plate,))


@check("sighting ingestion -> watchlist match -> alert -> dedup")
def test_sighting_matching_and_dedup(ctx):
    plate = f"{MARKER}03"
    cameras = ctx.client.get("/api/cameras").json()
    if not cameras:
        return False, "no camera to attach sightings to"
    camera_id = cameras[0]["camera_id"]
    now = datetime.now(timezone.utc)
    try:
        # 1. sighting with no matching watchlist entry yet.
        r1 = ctx.client.post("/api/sightings", headers=ctx.worker_headers, json={
            "camera_id": camera_id, "plate": plate, "confidence": 0.9,
            "seen_at": now.isoformat(),
        })
        if r1.status_code != 201 or r1.json()["matched"] is not False:
            return False, f"first sighting should not match, got {r1.status_code} {r1.json()}"

        # 2. add the watchlist entry.
        rw = ctx.client.post("/api/watchlist", json={"raw_value": plate, "severity": "high"})
        if rw.status_code != 201:
            return False, f"watchlist create HTTP {rw.status_code}"

        # 3. same plate again -> should match and create exactly one alert.
        r2 = ctx.client.post("/api/sightings", headers=ctx.worker_headers, json={
            "camera_id": camera_id, "plate": plate, "confidence": 0.95,
            "seen_at": (now + timedelta(minutes=1)).isoformat(),
        })
        if r2.status_code != 201 or not r2.json()["matched"] or not r2.json()["alert_id"]:
            return False, f"second sighting should match, got {r2.json()}"
        alert_id = r2.json()["alert_id"]

        # 4. same plate again immediately -> deduped, no new alert.
        r3 = ctx.client.post("/api/sightings", headers=ctx.worker_headers, json={
            "camera_id": camera_id, "plate": plate, "confidence": 0.9,
            "seen_at": (now + timedelta(minutes=2)).isoformat(),
        })
        if r3.status_code != 201 or r3.json()["matched"] is not False:
            return False, f"third sighting within dedup window should not re-alert, got {r3.json()}"

        # 5. search finds all three sightings.
        r_search = ctx.client.get("/api/sightings", params={"plate": plate})
        if len(r_search.json()) != 3:
            return False, f"expected 3 sightings for {plate}, found {len(r_search.json())}"

        # 5b. journey joins camera and orders by seen_at ascending.
        r_journey = ctx.client.get(f"/api/vehicles/{plate}/journey")
        journey = r_journey.json()
        if journey["sighting_count"] != 3 or journey["stops"][0]["camera_id"] != camera_id:
            return False, f"journey mismatch: {journey}"
        seen_ats = [s["seen_at"] for s in journey["stops"]]
        if seen_ats != sorted(seen_ats):
            return False, "journey stops not ordered by seen_at ascending"

        # 6. alert lifecycle. Enriched fields (plate/camera_name/severity)
        # are joined at read time, not stored on the row -- verify they
        # actually resolve, not just that the alert exists.
        r_alerts = ctx.client.get("/api/alerts", params={"status": "open"})
        alert_row = next((a for a in r_alerts.json() if a["id"] == alert_id), None)
        if alert_row is None:
            return False, "alert not visible via GET /api/alerts?status=open"
        if alert_row["plate"] != plate or not alert_row["camera_name"] or alert_row["severity"] != "high":
            return False, f"enriched alert fields wrong: {alert_row}"
        r_ack = ctx.client.post(f"/api/alerts/{alert_id}/acknowledge")
        if r_ack.status_code != 200 or r_ack.json()["status"] != "acknowledged":
            return False, f"acknowledge HTTP {r_ack.status_code}"
        r_res = ctx.client.post(f"/api/alerts/{alert_id}/resolve")
        if r_res.status_code != 200 or r_res.json()["status"] != "resolved":
            return False, f"resolve HTTP {r_res.status_code}"

        audit = ctx.current_run_audit_events()
        alert_actions = {
            event["action"]
            for event in audit
            if event["target_type"] == "alert" and event["target_id"] == str(alert_id)
        }
        if {"alert.acknowledged", "alert.resolved"} - alert_actions:
            return False, f"alert lifecycle audit events missing: {sorted(alert_actions)}"

        return True, f"match+dedup+search+acknowledge+resolve+audit all correct (alert {alert_id})"
    finally:
        ctx.sql("DELETE FROM alerts WHERE dedup_key LIKE %s", (f"{plate}%",))
        ctx.sql("DELETE FROM sightings WHERE plate = %s", (plate,))
        ctx.sql("DELETE FROM watchlist_entries WHERE normalised_value = %s", (plate,))


@check("analytics mode validation + person counts ingestion (zero counted as data)")
def test_analytics_modes_and_counts(ctx):
    cameras = ctx.client.get("/api/cameras").json()
    if not cameras:
        return False, "no camera to attach counts to"
    camera_id = cameras[0]["camera_id"]

    r_bad = ctx.client.post("/api/analytics/start", params={"camera_id": camera_id, "mode": "bogus"})
    if r_bad.status_code != 422:
        return False, f"invalid mode should 422, got {r_bad.status_code}"

    try:
        # A window with zero people is a real measurement, not a gap -- must
        # not be rejected or silently coerced.
        payload = {
            "camera_id": camera_id, "mode": "person",
            "window_start": "2026-08-29T18:00:00Z", "window_end": "2026-08-29T18:00:30Z",
            "unique_tracks": 0, "peak_concurrent": 0,
        }
        r = ctx.client.post("/api/analytics/counts", headers=ctx.worker_headers, json=payload)
        if r.status_code != 201 or r.json()["unique_tracks"] != 0:
            return False, f"zero-count POST failed: HTTP {r.status_code} {r.text[:200]}"
        count_id = r.json()["id"]

        r_list = ctx.client.get("/api/analytics/counts", params={"camera_id": camera_id})
        if not any(c["id"] == count_id for c in r_list.json()):
            return False, "posted count not visible via GET /api/analytics/counts"

        return True, f"mode validation + zero-count ingestion correct (count {count_id})"
    finally:
        ctx.sql("DELETE FROM analytics_counts WHERE camera_id = %s AND mode = 'person' AND unique_tracks = 0 AND peak_concurrent = 0", (camera_id,))


@check("analytics status endpoint (no worker running)")
def test_analytics_status(ctx):
    r = ctx.client.get("/api/analytics/status")
    return r.status_code == 200 and isinstance(r.json(), list), f"HTTP {r.status_code}: {r.text[:200]}"


# --------------------------------------------------------------------------
# Optional: live camera pipeline (--live)
# --------------------------------------------------------------------------

def _find_working_camera(preferred_id: str | None) -> str | None:
    """Probe candidate cameras and return the first that actually opens.
    Mirrors the lesson from this session: never assume a fixed camera id is
    up, since sandbox availability is intermittent."""
    worker_dir = Path(__file__).resolve().parents[2] / "multi-object-tracking"
    candidates = [preferred_id] if preferred_id else ["10", "12", "21", "4", "20"]
    for cam_id in candidates:
        if cam_id is None:
            continue
        proc = subprocess.run(
            [str(worker_dir / ".venv" / "bin" / "python"), "camera_feeds.py", "--probe", "--id", cam_id],
            cwd=str(worker_dir), capture_output=True, text=True, timeout=60,
        )
        if "1/1 streams decoded" in proc.stdout:
            return cam_id
    return None


def test_live_analytics_pipeline(ctx, camera_id_override):
    name = "live analytics pipeline (worker start -> sighting -> stop)"
    print(f"  probing for a currently-reachable camera{' (' + camera_id_override + ')' if camera_id_override else ''}...")
    camera_id = _find_working_camera(camera_id_override)
    if camera_id is None:
        RESULTS.append((name, False, "no candidate camera is reachable right now (sandbox-side, not a code issue)"))
        print(f"  [FAIL] {name} - no candidate camera reachable right now")
        return False
    print(f"  using camera {camera_id}")

    before_count = ctx.sql("SELECT count(*) FROM sightings")[0][0]
    r = ctx.client.post("/api/analytics/start", params={"camera_id": camera_id, "model": "yolo11n.pt"})
    if r.status_code != 200:
        RESULTS.append((name, False, f"start HTTP {r.status_code}: {r.text[:200]}"))
        print(f"  [FAIL] {name} - start HTTP {r.status_code}")
        return False

    log_path = Path(r.json()["log_path"])
    connected, deadline = False, time.time() + 60
    while time.time() < deadline:
        if log_path.exists() and "Connected:" in log_path.read_text(errors="replace"):
            connected = True
            break
        time.sleep(2)

    # Give it a bit longer to actually confirm a plate -- best-effort, depends
    # on real traffic being in frame; not required for a mechanical pass.
    got_sighting, deadline = False, time.time() + 90
    while connected and time.time() < deadline:
        after_count = ctx.sql("SELECT count(*) FROM sightings")[0][0]
        if after_count > before_count:
            got_sighting = True
            break
        time.sleep(5)

    r_stop = ctx.client.post("/api/analytics/stop", params={"camera_id": camera_id})
    stopped_clean = r_stop.status_code == 200 and r_stop.json()["running"] is False

    ok = connected and stopped_clean
    detail = (
        f"camera {camera_id}: connected={connected}, "
        f"sighting_confirmed={got_sighting} (best-effort, needs real traffic), "
        f"stopped_clean={stopped_clean}"
    )
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} - {detail}")
    return ok


# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--live", action="store_true", help="also run the live-camera analytics pipeline test")
    parser.add_argument("--camera-id", default=None, help="pin a camera id for --live instead of auto-probing")
    args = parser.parse_args()

    ctx = Ctx(args.base_url)
    try:
        print(f"Sentinel smoke test against {args.base_url}\n")

        print("Model 1 -- registry, onboarding, gap analysis")
        for fn in (test_health, test_camera_list, test_camera_detail,
                   test_manual_camera_lifecycle, test_bulk_import, test_sync, test_gap_analysis):
            fn(ctx)

        print("\nModel 2 -- watchlist, sightings, matching, alerts")
        for fn in (test_watchlist_crud, test_watchlist_bulk,
                   test_sighting_matching_and_dedup, test_analytics_status,
                   test_analytics_modes_and_counts):
            fn(ctx)

        if args.live:
            print("\nModel 2 -- live camera pipeline (best-effort, sandbox-dependent)")
            test_live_analytics_pipeline(ctx, args.camera_id)
        else:
            print("\n(skipping live camera pipeline test; pass --live to include it)")

        print(f"\n{'=' * 60}")
        passed = sum(1 for _, ok, _ in RESULTS if ok)
        skipped = [n for n, ok, _ in RESULTS if ok is None]
        failed = [n for n, ok, _ in RESULTS if ok is not None and not ok]
        print(f"{passed}/{len(RESULTS) - len(skipped)} passed"
              + (f" ({len(skipped)} skipped)" if skipped else ""))
        if skipped:
            print("SKIPPED: " + ", ".join(skipped))
        if failed:
            print("FAILED: " + ", ".join(failed))
        print(f"{'=' * 60}")
        sys.exit(0 if not failed else 1)
    finally:
        ctx.close()


if __name__ == "__main__":
    main()
