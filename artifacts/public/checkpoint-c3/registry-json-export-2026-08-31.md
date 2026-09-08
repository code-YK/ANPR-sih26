# C3 Registry JSON export verification — 2026-08-31

Scope: synthetic local verification of `GOV-M1-007`'s JSON export addition.

- Candidate branch: `codex/feat-registry-json-export`
- Base revision: `8c2647f`
- Database: local PostgreSQL/PostGIS migrated through `202608311600`
- Test data: synthetic `SMOKETEST` cameras only; cleaned by the suite
- Live feeds and ML: not run

Commands, from `backend/`:

```bash
<venv>/bin/python scripts/smoke_test.py --base-url http://127.0.0.1:8013
<venv>/bin/python scripts/rbac_smoke_test.py --base-url http://127.0.0.1:8013
```

Results:

- General non-ML API smoke: **11/11 executed checks passed**. The same
  filtered camera query was downloaded as both CSV and `?format=json`; both
  contained exactly the expected camera and neither exposed RTSP/HLS/WebRTC
  fields. The suite verified the JSON export audit event includes
  `format: json`.
- RBAC smoke passed, including viewer CSV export before/after a
  cross-department grant. Its scope enforcement is shared by JSON export.
- Catalogue sync skipped on upstream HTTP 502, reported separately.

This does not prove per-read/denial audit, database-level immutable audit
retention, a teammate clean clone, or live/ML behavior.
