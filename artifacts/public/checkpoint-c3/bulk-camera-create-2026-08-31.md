# C3 CSV camera onboarding verification — 2026-08-31

Scope: synthetic local verification of the implemented bulk/manual/API paths for
`GOV-M1-003`, including namespace-safe CSV camera creation and its audit event.

- Candidate branch: `codex/feat-bulk-camera-create`
- Base revision: `5417cbb`
- Database: local PostgreSQL/PostGIS, already migrated to `202608301800`
- Python used for this run: 3.10.11; the accepted Python 3.13 environment and
  teammate clean-clone rehearsal remain separate `TEAM-NFR-002` gaps
- Credentials and worker token: local environment values, not retained here or in Git
- Camera, watchlist, sighting, and alert rows: synthetic and cleaned by the suite
- ML and live-camera paths: not run

Commands, from `backend/`, with the backend using the same local environment
values as the test process:

```bash
DYLD_LIBRARY_PATH=/opt/homebrew/lib <venv>/bin/uvicorn app.main:app --port 8010
<venv>/bin/python scripts/smoke_test.py --base-url http://127.0.0.1:8010
<venv>/bin/python scripts/rbac_smoke_test.py --base-url http://127.0.0.1:8010
```

Results:

- General non-ML API smoke: **11/11 executed checks passed**. Its CSV case
  created one manual camera from a blank `camera_id`, updated one existing
  camera, and retained three independent validation failures: blank creation
  name, unknown supplied ID, and invalid department. It verified the generated
  `manual-` ID, persisted fields/geocode result, and the partial
  `camera.bulk_updated` audit totals (`5` rows, `1` created, `1` updated,
  `3` failed). All temporary cameras were deleted by the test.
- RBAC smoke: passed after the shared manual-camera allocator refactor.
- Frontend lint passed with the repository's existing warnings, and `npm run build`
  passed. Vite retained its existing bundle-size warning (the main JS bundle is
  above 500 kB after minification).
- Catalogue sync: skipped because the configured external sandbox returned HTTP
  502; the suite reports this upstream condition separately from application
  failures.

This is application-level candidate evidence, not proof of a successful
authorised catalogue refresh, a representative committed camera fixture,
browser usability, per-read/denial audit, database-level audit immutability,
Python 3.13 reproducibility, a clean-clone rehearsal, or live/ML behaviour.
