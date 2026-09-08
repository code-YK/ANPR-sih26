# C3 read and denial audit verification — 2026-08-31

## Scope

`GOV-M1-007` and `GOV-NFR-003` application-level access-history evidence.
The implementation records successful authenticated metadata reads and 401/403
authentication or authorisation denials by matched route template; it does not
retain query values or raw route parameters.

## Commands

```bash
cd backend
DYLD_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/uvicorn app.main:app --port 8016
.venv/bin/python scripts/rbac_smoke_test.py --base-url http://127.0.0.1:8016
.venv/bin/python scripts/smoke_test.py --base-url http://127.0.0.1:8016
```

## Result

- RBAC smoke passed, including an asserted `api.read` record for
  `GET /api/cameras` and an asserted `api.access_denied` record for a viewer
  denied `GET /api/cameras/{camera_id}`. The denial details contain only
  method, HTTP 403, and `authorisation`—not a camera value or query string.
- General non-ML smoke passed 11/11. The catalogue-sync check skipped because
  the configured upstream returned HTTP 502.

## Boundaries

State-change routes retain their domain-specific audit events. HLS relay,
media-file/thumbnail/track-box, and high-frequency analytics telemetry
*successful reads* are excluded from per-request audit to prevent audit-volume
amplification; their authentication/authorisation denials remain auditable.
Database administrators can still alter rows, and there is no external audit
export yet; those are separate remaining gaps.
