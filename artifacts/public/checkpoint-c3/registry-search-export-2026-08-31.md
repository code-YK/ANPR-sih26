# C3 Registry search and export verification — 2026-08-31

Scope: synthetic local verification of `GOV-M1-007`'s implemented registry
search, camera-type filter, department-scoped CSV export, and export audit.

- Candidate branch: `codex/feat-registry-search-export`
- Base revision: `f3e8aaf`
- Database: local PostgreSQL/PostGIS, migrated to `202608301800`
- Python used: 3.10.11; accepted Python 3.13 and a teammate clean-clone
  rehearsal remain `TEAM-NFR-002` gaps
- Credentials: local environment values, never recorded here
- Test camera rows: synthetic `SMOKETEST` records and cleaned by the suite
- ML and live-camera paths: not run

Commands, from `backend/`, with the service using the same local environment
values as the smoke process:

```bash
DYLD_LIBRARY_PATH=/opt/homebrew/lib <venv>/bin/uvicorn app.main:app --port 8010
<venv>/bin/python scripts/smoke_test.py --base-url http://127.0.0.1:8010
<venv>/bin/python scripts/rbac_smoke_test.py --base-url http://127.0.0.1:8010
```

Results:

- General non-ML API smoke: **11/11 executed checks passed**. The registry
  lifecycle check created two synthetic cameras, set one to `fixed`, then
  verified `/api/cameras?q=SMOKETEST+camera&camera_type=fixed` returned only
  that record.
- The same check downloaded `/api/cameras/export` with the identical filters,
  confirmed its CSV content type, one expected row, and the absence of
  `rtsp_url`, `hls_url`, and `webrtc_url` headers. It also verified the
  `camera_registry.exported` audit event's actor/result/filter/row-count data.
- RBAC smoke also passed. Its synthetic viewer exported only the home-department
  camera before a cross-department grant, then both authorised cameras after
  that viewer grant; both exports excluded source endpoint headers.
- Catalogue sync: skipped because the configured external sandbox returned
  HTTP 502, reported as an upstream condition rather than an application test
  failure.

This is candidate application evidence only. It does not prove JSON export,
per-read/denial audit, database-level audit immutability, a successful
authorised catalogue refresh, browser accessibility, Python 3.13
reproducibility, a clean-clone rehearsal, or live/ML behaviour.
