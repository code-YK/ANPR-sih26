# Same-host clean-clone rehearsal — 2026-08-31

## Scope

`TEAM-NFR-002`, plus reproducibility evidence for the Model 1 synthetic path.
This was an isolated clean clone on the same macOS host, not a teammate or
second-machine result.

## Baseline and prerequisites

- Source revision: `1f146ef` (`feat: add digest-verifiable audit export`).
- Python: Homebrew Python 3.13.15.
- Database: a newly created disposable PostgreSQL 17 database with PostGIS.
- Frontend: Node 22.20.0 with the committed `package-lock.json`.
- Only the committed synthetic fixture and temporary non-production local
  credentials were used. No live stream, sandbox, or ML path was invoked.

## Commands

```bash
git clone --no-local <source> <temporary-clone>
cd <temporary-clone>
createdb sentinel_clean_clone
psql -d sentinel_clean_clone -c "CREATE EXTENSION IF NOT EXISTS postgis;"
/opt/homebrew/bin/python3.13 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt

cd backend
DATABASE_URL=...sentinel_clean_clone SYNC_DATABASE_URL=...sentinel_clean_clone \
  .venv/bin/alembic upgrade head
DATABASE_URL=...sentinel_clean_clone SYNC_DATABASE_URL=...sentinel_clean_clone \
  .venv/bin/python scripts/seed_synthetic_demo.py
DATABASE_URL=...sentinel_clean_clone SYNC_DATABASE_URL=...sentinel_clean_clone \
  .venv/bin/python scripts/seed_synthetic_demo.py --verify

cd ../frontend-v2
npm ci
npm run lint
npm run build
```

The backend was then started with the same temporary database and credentials;
`scripts/rbac_smoke_test.py` and `scripts/smoke_test.py` ran against it.

## Result

- Full tracked migration chain, including `202608311800`, completed.
- Fixture verification found five synthetic cameras and two synthetic watchlist
  entries, with no source endpoints.
- `npm ci`, lint (warnings only), and production build passed.
- RBAC/audit-export smoke passed.
- General non-ML smoke passed 11/11 checks. Catalogue sync was skipped after
  the configured upstream returned HTTP 502. PDF export passed when the server
  used the documented macOS `DYLD_LIBRARY_PATH=/opt/homebrew/lib` setting.

## Remaining boundary

A teammate must repeat the documented path from a clean clone on a second
machine using only approved local secrets. This evidence neither verifies the
live sandbox/ML paths nor substitutes for that separate reproduction.
