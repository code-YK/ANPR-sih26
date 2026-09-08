# C3/C4 RBAC verification — 2026-08-31

Scope: synthetic local verification of `GOV-M1-003`, `GOV-M1-007`,
`GOV-FUN-007`, `GOV-NFR-001`, and the implemented portion of
`GOV-NFR-003` after the audit endpoint became paginated.

- Candidate branch: `codex/fix-rbac-audit-smoke`
- Base revision: `bdf0463`
- Evidence revision: the commit containing this artifact and the smoke-script fix
- Database: local PostgreSQL/PostGIS, migrated to `202608301800`
- Python used for this run: 3.10.11; the accepted Python 3.13 environment and
  teammate clean-clone rehearsal remain separate `TEAM-NFR-002` gaps
- Credentials and worker token: local environment values, not retained here or in Git
- Camera/account/request/watchlist/sighting data: synthetic and cleaned by the scripts
- ML/live-camera path: not run

Commands, from `backend/`, with the backend using the same local environment
values as the test processes:

```bash
<venv>/bin/alembic upgrade head
DYLD_LIBRARY_PATH=/opt/homebrew/lib <venv>/bin/uvicorn app.main:app --port 8010
<venv>/bin/python scripts/rbac_smoke_test.py --base-url http://127.0.0.1:8010
<venv>/bin/python scripts/smoke_test.py --base-url http://127.0.0.1:8010
```

Results:

- Alembic upgrade: passed; database advanced from `202608301200` to
  `202608301800`.
- RBAC smoke: passed authentication denial, public registration, two-level
  approval, home-department scoping, cross-department viewer/operator grants,
  viewer mutation denial, operator action authorisation, paginated audit
  response validation, and required audit-action checks.
- General non-ML API smoke: 11/11 executed checks passed. Camera
  create/update/partial-bulk audit records and alert acknowledge/resolve audit
  records were queried through the paginated endpoint and verified as part of
  their corresponding checks.
- Gap-analysis JSON, HTML, and PDF exports passed; the final PDF response was 42,080
  bytes. The documented macOS `DYLD_LIBRARY_PATH` is required for WeasyPrint's
  Homebrew native libraries.
- Catalogue sync: skipped because the configured external sandbox returned HTTP
  502; the script reports this upstream condition separately from application
  failures.
- Frontend, live browser playback, and ML workers were not run in this evidence pass.

This is application-level candidate evidence, not a production security
certification. It does not prove per-read or denied-authorisation audit,
database-level audit immutability/retention, MFA/SSO, rate limiting, TLS/storage
encryption, browser accessibility, live-feed behaviour, Python 3.13
reproducibility, or a teammate clean-clone rehearsal.
