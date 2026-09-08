# C3 Probe health-history verification — 2026-08-31

Scope: synthetic local verification of the implemented health portion of
`GOV-M1-005`: current reason, append-only probe observation, viewer-scoped
history route, and an offline transition.

- Candidate branch: `codex/feat-camera-health-history`
- Base revision: `be5bb0f`
- Database: local PostgreSQL/PostGIS migrated through `202608311600`
- Python used: 3.10.11; accepted Python 3.13 and clean-clone rehearsal remain
  separate gaps
- Test rows: synthetic `SMOKETEST` cameras, cleaned by the suite
- Live feeds and ML: not run

Commands, from `backend/`, with the backend using matching local environment
values:

```bash
<venv>/bin/alembic upgrade head
DYLD_LIBRARY_PATH=/opt/homebrew/lib <venv>/bin/uvicorn app.main:app --port 8012
<venv>/bin/python scripts/smoke_test.py --base-url http://127.0.0.1:8012
<venv>/bin/python scripts/rbac_smoke_test.py --base-url http://127.0.0.1:8012
```

Results:

- Alembic applied `202608311600` successfully.
- General non-ML API smoke: **11/11 executed checks passed**. A metadata-only
  synthetic camera was probed without an RTSP/HLS call, producing a
  deterministic `transport_ok=none` result. The test then verified its newest
  health-history row was `offline`, preserved a reason, and that the probe
  audit event was present.
- RBAC smoke passed unchanged after the new viewer-scoped history route.
- Catalogue sync skipped because the configured external sandbox returned HTTP
  502, reported separately as an upstream condition.

This proves the synthetic no-endpoint offline case, not a production health
monitor, a real-feed outage/recovery, maintenance work orders, immutable
database audit retention, Python 3.13 reproduction, or a teammate clean clone.
