# C3 audit archive export verification — 2026-08-31

## Scope

`GOV-NFR-003` portable audit-history hand-off. `GET
/api/admin/audit-events/export` supplies a complete, oldest-first canonical
NDJSON snapshot only to a super admin. The response contains its event count
and SHA-256 digest in headers and is marked `Cache-Control: no-store`.

## Commands

```bash
cd backend
DYLD_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/uvicorn app.main:app --port 8018
.venv/bin/python scripts/rbac_smoke_test.py --base-url http://127.0.0.1:8018
.venv/bin/python scripts/smoke_test.py --base-url http://127.0.0.1:8018
```

## Result

The RBAC smoke test passed. It asserts that a department admin receives `403`,
then that the super-admin response is NDJSON, no-store, ordered by UTC event
time/id, has the stated number of canonical records, and hashes to exactly the
returned SHA-256 value. It also verifies an `audit.exported` event is recorded.
The general non-ML suite passed 11/11 checks; catalogue sync was skipped after
the configured upstream returned HTTP 502.

## Boundary

The downloaded archive and digest must be placed together in an approved
immutable retention service by an authorised operator. This route deliberately
does not configure a cloud bucket, retention lock, or credentials, and it does
not make a database-superuser/schema-owner unable to alter database controls.
