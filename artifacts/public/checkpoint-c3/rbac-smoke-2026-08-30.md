# C3/C4 RBAC verification — 2026-08-30

Scope: synthetic local verification of `GOV-M1-007`, `GOV-FUN-007`, `GOV-NFR-001`, and the implemented portion of `GOV-NFR-003`.

- Branch: `codex/feat-department-rbac`
- Baseline: `d780fca`
- Database: local PostgreSQL/PostGIS, migrated from `202608292344` to `202608301200`
- Credentials and worker token: temporary environment values, not retained in this artifact or Git
- Camera/account/request data created by the RBAC test: synthetic and cleaned by the script

Commands, from `backend/` with the backend running under matching local environment values:

```bash
<venv>/bin/alembic upgrade head
<venv>/bin/python scripts/rbac_smoke_test.py --base-url http://127.0.0.1:8010
<venv>/bin/python scripts/smoke_test.py --base-url http://127.0.0.1:8010
```

Results:

- Alembic migration: passed.
- RBAC smoke: passed authentication denial, public registration, two-level approval, home-department scoping, cross-department viewer/operator grants, viewer mutation denial, operator action authorisation, and audit-event checks.
- General smoke: 11/11 passed.
- Catalogue sync: skipped because the configured external sandbox returned HTTP 502; the script treats this upstream condition separately from application failures.
- Frontend: `npm run lint` completed with warnings and no errors; `npm run build` completed. The existing bundle-size warning remains.

This is application-level evidence, not a production security certification. It does not prove MFA/SSO, rate limiting, per-read audit, database-level audit immutability, TLS/storage encryption, browser accessibility, or a teammate clean-clone rehearsal.
