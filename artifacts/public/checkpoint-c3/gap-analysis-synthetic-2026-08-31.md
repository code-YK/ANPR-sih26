# C3 synthetic gap-analysis report — 2026-08-31

## Scope

`GOV-M1-006` reproducible capability, coverage, and health/ageing report
evidence. This run used only `backend/fixtures/synthetic_registry.json`; every
camera name, location, identifier, department, and watchlist value in the
fixture is explicitly synthetic. No source endpoint, sandbox response, media,
or ML worker was used.

## Commands

```bash
cd backend
createdb sentinel_gap_report
psql -d sentinel_gap_report -c "CREATE EXTENSION IF NOT EXISTS postgis;"
DATABASE_URL=...sentinel_gap_report SYNC_DATABASE_URL=...sentinel_gap_report \
  .venv/bin/alembic upgrade head
DATABASE_URL=...sentinel_gap_report SYNC_DATABASE_URL=...sentinel_gap_report \
  .venv/bin/python scripts/seed_synthetic_demo.py
DATABASE_URL=...sentinel_gap_report SYNC_DATABASE_URL=...sentinel_gap_report \
  .venv/bin/python scripts/seed_synthetic_demo.py --verify

# Start the backend with the same temporary database and temporary local
# credentials, then authenticate and request:
GET /api/gap-analysis
GET /api/gap-analysis/export?format=html
GET /api/gap-analysis/export?format=pdf
```

## Result

All three report representations succeeded:

| Representation | HTTP | Result |
|---|---:|---|
| JSON | 200 | 5 cameras, 2 capability gaps, 1 unplaced asset, 3 health gaps |
| HTML | 200 | `text/html`, 6,824 bytes |
| PDF | 200 | `application/pdf`, 31,285 bytes |

The JSON report identified these deliberately synthetic examples:

- capability gaps: `demo-cam-004` (replacement priority) and `demo-cam-002`;
- health gaps: offline/unreachable `demo-cam-002`, low-resolution/bitrate
  `demo-cam-004`, and never-surveyed `demo-cam-005`;
- coverage: Ahmedabad, Vadodara, Surat, and Rajkot are represented; the report
  explicitly lists the other uncovered Gujarat districts rather than implying
  statewide coverage.

## Boundary

This proves deterministic report generation from the committed safe fixture,
not actual statewide coverage or live-feed health. A real authorised catalogue
and live probe evidence remain separate Module 1 work.
