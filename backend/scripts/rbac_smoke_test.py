#!/usr/bin/env python3
"""End-to-end demo RBAC verification against a running local backend.

Uses only synthetic accounts and cleans them, their requests, sessions, and
test cameras from the local database when finished. The backend must use the
same SUPER_ADMIN_* settings as this process.
"""

import argparse
import csv
import hashlib
import io
import json
import re
import secrets
import sys
import time
from pathlib import Path

import httpx
import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import get_settings  # noqa: E402


def pg_dsn(value: str) -> str:
    return re.sub(r"^postgresql\+\w+://", "postgresql://", value)


def require(response: httpx.Response, expected: int, label: str):
    if response.status_code != expected:
        raise AssertionError(f"{label}: expected {expected}, got {response.status_code}: {response.text[:300]}")
    return response.json() if response.content else None


def login(base_url: str, email: str, password: str) -> httpx.Client:
    client = httpx.Client(base_url=base_url, timeout=20.0)
    require(client.post("/api/auth/login", json={"email": email, "password": password}), 200, f"login {email}")
    return client


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    settings = get_settings()
    if not settings.super_admin_email or not settings.super_admin_password:
        raise RuntimeError("Set SUPER_ADMIN_EMAIL and SUPER_ADMIN_PASSWORD for the backend and this test")

    base_url = args.base_url.rstrip("/")
    suffix = str(int(time.time() * 1000))
    admin_email = f"rbac-admin-{suffix}@sentinel.test"
    viewer_email = f"rbac-viewer-{suffix}@sentinel.test"
    other_admin_email = f"rbac-other-admin-{suffix}@sentinel.test"
    password = secrets.token_urlsafe(24)
    emails = [admin_email, viewer_email, other_admin_email]
    camera_ids = []
    db = psycopg2.connect(pg_dsn(settings.sync_database_url))
    db.autocommit = True

    def sql(query, params=None):
        with db.cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchall() if cursor.description else None

    public = httpx.Client(base_url=base_url, timeout=20.0)
    super_client = None
    department_admin = None
    viewer = None
    try:
        require(public.get("/api/cameras"), 401, "protected camera list")
        require(public.get("/openapi.json"), 401, "protected OpenAPI")
        options = require(public.get("/api/auth/registration-options"), 200, "public registration options")
        assert {row["name"] for row in options} >= {"Police", "Health"}

        super_client = login(base_url, settings.super_admin_email, settings.super_admin_password)
        audit_total_before = require(
            super_client.get("/api/admin/audit-events", params={"limit": 1}),
            200,
            "audit baseline",
        )["total"]

        for payload in (
            {
                "full_name": "RBAC Police Admin", "email": admin_email, "password": password,
                "requested_department": "Police", "requested_role": "department_admin",
            },
            {
                "full_name": "RBAC Police Viewer", "email": viewer_email, "password": password,
                "requested_department": "Police", "requested_role": "department_user",
            },
            {
                "full_name": "RBAC Health Admin", "email": other_admin_email, "password": password,
                "requested_department": "Health", "requested_role": "department_admin",
            },
        ):
            require(public.post("/api/registration-requests", json=payload), 201, f"register {payload['email']}")

        pending = require(super_client.get("/api/admin/registration-requests"), 200, "super pending list")
        by_email = {row["email"]: row for row in pending}
        approved_admin = require(
            super_client.post(
                f"/api/admin/registration-requests/{by_email[admin_email]['id']}/approve",
                json={"clearance": "viewer"},
            ),
            200,
            "super approves department admin",
        )
        assert approved_admin["role"] == "department_admin"
        assert len(approved_admin["grants"]) == 1
        assert approved_admin["grants"][0]["department"] == "Police"
        assert approved_admin["grants"][0]["clearance"] == "operator"
        assert approved_admin["grants"][0]["is_home"] is True

        department_admin = login(base_url, admin_email, password)
        scoped_pending = require(
            department_admin.get("/api/admin/registration-requests"), 200, "department-admin pending list"
        )
        assert [row["email"] for row in scoped_pending] == [viewer_email]
        require(
            department_admin.post(
                f"/api/admin/registration-requests/{by_email[other_admin_email]['id']}/approve",
                json={"clearance": "operator"},
            ),
            403,
            "department admin cannot approve department admins",
        )
        viewer_account = require(
            department_admin.post(
                f"/api/admin/registration-requests/{by_email[viewer_email]['id']}/approve",
                json={"clearance": "viewer"},
            ),
            200,
            "department admin approves employee",
        )

        for department in ("Police", "Health"):
            camera = require(
                super_client.post(
                    "/api/cameras",
                    json={"name": f"RBAC {department} camera", "location_text": "Synthetic RBAC test", "department": department},
                ),
                201,
                f"create {department} camera",
            )
            camera_ids.append(camera["camera_id"])

        viewer = login(base_url, viewer_email, password)
        cameras = require(viewer.get("/api/cameras"), 200, "viewer camera list")
        assert cameras and all(camera["department"] == "Police" for camera in cameras)
        police_camera, health_camera = camera_ids
        scoped_export = viewer.get("/api/cameras/export", params={"q": "RBAC"})
        assert scoped_export.status_code == 200 and "text/csv" in scoped_export.headers.get("content-type", "")
        scoped_export_rows = list(csv.DictReader(io.StringIO(scoped_export.text)))
        assert [row["camera_id"] for row in scoped_export_rows] == [police_camera]
        assert not {"rtsp_url", "hls_url", "webrtc_url"} & set(scoped_export_rows[0])
        require(viewer.get(f"/api/cameras/{police_camera}"), 200, "viewer home camera")
        require(viewer.get(f"/api/cameras/{health_camera}"), 403, "viewer restricted camera")
        require(viewer.put(f"/api/cameras/{police_camera}", json={"connectivity": "test"}), 403, "viewer camera mutation")
        require(
            viewer.post(
                f"/api/cameras/{police_camera}/maintenance-work-orders",
                json={"summary": "Viewer must not create maintenance work"},
            ),
            403,
            "viewer maintenance mutation",
        )
        require(viewer.get(f"/api/cameras/{police_camera}/maintenance-work-orders"), 200, "viewer maintenance history")
        maintenance_order = require(
            department_admin.post(
                f"/api/cameras/{police_camera}/maintenance-work-orders",
                json={"summary": "RBAC maintenance test", "note": "Created by home department admin"},
            ),
            201,
            "home department admin maintenance create",
        )
        require(
            department_admin.patch(
                f"/api/cameras/{police_camera}/maintenance-work-orders/{maintenance_order['id']}",
                json={"status": "resolved", "note": "RBAC test complete"},
            ),
            200,
            "home department admin maintenance resolution",
        )
        require(
            viewer.post("/api/analytics/stop", params={"camera_id": police_camera, "mode": "vehicle"}),
            403,
            "viewer analytics action",
        )

        require(
            super_client.put(
                f"/api/admin/users/{viewer_account['id']}/grants/Health", json={"clearance": "viewer"}
            ),
            200,
            "super cross-department viewer grant",
        )
        require(viewer.get(f"/api/cameras/{health_camera}"), 200, "cross-department read grant")
        cross_department_export = viewer.get("/api/cameras/export", params={"q": "RBAC"})
        assert cross_department_export.status_code == 200
        cross_department_rows = list(csv.DictReader(io.StringIO(cross_department_export.text)))
        assert {row["camera_id"] for row in cross_department_rows} == set(camera_ids)
        require(
            viewer.post("/api/analytics/stop", params={"camera_id": health_camera, "mode": "vehicle"}),
            403,
            "cross-department viewer still read-only",
        )
        require(
            super_client.put(
                f"/api/admin/users/{viewer_account['id']}/grants/Health", json={"clearance": "operator"}
            ),
            200,
            "upgrade cross-department grant",
        )
        require(
            viewer.post("/api/analytics/stop", params={"camera_id": health_camera, "mode": "vehicle"}),
            404,
            "operator passes authorisation to analytics action",
        )

        require(
            department_admin.get("/api/admin/audit-events/export"),
            403,
            "department admin cannot export cross-department audit archive",
        )
        archive = super_client.get("/api/admin/audit-events/export")
        if archive.status_code != 200:
            raise AssertionError(f"audit archive: expected 200, got {archive.status_code}: {archive.text[:300]}")
        assert archive.headers.get("content-type", "").startswith("application/x-ndjson")
        assert archive.headers.get("cache-control") == "no-store"
        assert archive.headers.get("x-sentinel-audit-sha256") == hashlib.sha256(archive.content).hexdigest()
        archive_rows = [json.loads(line) for line in archive.text.splitlines()]
        assert len(archive_rows) == int(archive.headers["x-sentinel-audit-event-count"])
        assert archive_rows == sorted(archive_rows, key=lambda row: (row["occurred_at"], row["id"]))
        assert all(set(row) == {
            "action", "actor_email", "actor_user_id", "department", "details", "id", "occurred_at", "result",
            "target_id", "target_type",
        } for row in archive_rows)

        delivered_archive = super_client.post("/api/admin/audit-events/archive")
        if delivered_archive.status_code != 201:
            raise AssertionError(
                "external audit archive delivery: expected 201, got "
                f"{delivered_archive.status_code}: {delivered_archive.text[:300]}"
            )
        delivered = delivered_archive.json()
        assert set(delivered) == {"archive_name", "event_count", "sha256"}
        assert delivered["archive_name"].endswith(".ndjson")
        assert delivered["event_count"] >= len(archive_rows)
        assert len(delivered["sha256"]) == 64

        audit_page = require(
            super_client.get("/api/admin/audit-events", params={"limit": 1000}),
            200,
            "audit log",
        )
        assert audit_page["limit"] == 1000 and audit_page["offset"] == 0
        assert audit_page["total"] >= len(audit_page["events"])
        new_event_count = audit_page["total"] - audit_total_before
        assert 0 < new_event_count <= len(audit_page["events"])
        actions = {event["action"] for event in audit_page["events"][:new_event_count]}
        assert {
            "registration.approved",
            "department_access.granted",
            "department_access.clearance_changed",
            "camera.created",
            "camera_registry.exported",
            "camera_maintenance.created",
            "camera_maintenance.updated",
            "audit.exported",
            "audit.archive_delivered",
        } <= actions
        assert any(
            event["action"] == "api.read"
            and event["target_id"] == "/api/cameras"
            and event["result"] == "success"
            for event in audit_page["events"][:new_event_count]
        )
        assert any(
            event["action"] == "api.access_denied"
            and event["actor_email"] == viewer_email
            and event["target_id"] == "/api/cameras/{camera_id}"
            and event["details"] == {"method": "GET", "status_code": 403, "reason": "authorisation"}
            for event in audit_page["events"][:new_event_count]
        )
        protected_audit_id = audit_page["events"][0]["id"]
        for statement, label in (
            ("UPDATE audit_events SET action = 'tampered' WHERE id = %s", "update"),
            ("DELETE FROM audit_events WHERE id = %s", "delete"),
        ):
            try:
                sql(statement, (protected_audit_id,))
            except psycopg2.Error as exc:
                assert "append-only" in str(exc), f"unexpected audit {label} failure: {exc}"
            else:
                raise AssertionError(f"audit {label} should be rejected by the database trigger")

        print("PASS: authentication, approvals, home/cross-department scope, camera maintenance controls, read/denial audit, scoped exports, and database-immutable audit")
        return 0
    finally:
        for client in (viewer, department_admin, super_client, public):
            if client is not None:
                client.close()
        if camera_ids:
            sql("DELETE FROM cameras WHERE camera_id = ANY(%s)", (camera_ids,))
        sql("DELETE FROM registration_requests WHERE email = ANY(%s)", (emails,))
        sql("DELETE FROM users WHERE email = ANY(%s)", (emails,))
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
