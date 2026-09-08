# Sentinel Model 1 backend

FastAPI + PostgreSQL/PostGIS implementation of the camera registry and onboarding pipeline described in [../docs/model1-build-spec.md](../docs/model1-build-spec.md).

The active operator console is `frontend-v2/`. FastAPI serves its production build at `/` when `frontend-v2/dist/` exists. The old vanilla UI remains in the repository as historical migration context but is not served because it has no authentication flow.

## Prerequisites

- Python 3.13
- PostgreSQL 17 with the PostGIS extension available (on macOS: `brew install postgresql@17 postgis`)
- `ffmpeg`/`ffprobe` on `PATH` (on macOS: `brew install ffmpeg`)
- On macOS, WeasyPrint (used for the gap-analysis PDF export) needs Homebrew's native libs on the dynamic loader path: run the server with `DYLD_LIBRARY_PATH=/opt/homebrew/lib`.

## Setup

```bash
# from the repository root
python3.13 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt

# start Postgres and create the database once
brew services start postgresql@17
createdb sentinel
psql -d sentinel -c "CREATE EXTENSION IF NOT EXISTS postgis;"

cd backend
cp .env.example .env
# edit database URLs for your local user/socket and obtain sandbox endpoint
# values through the approved team channel. Also set a long demo super-admin
# password and a distinct worker token; never commit the populated .env.
.venv/bin/alembic upgrade head
```

For offline registry/API work, leave the example `.invalid` sandbox URLs unchanged and do not call the live sync/probe/survey stages. Use the committed synthetic fixture described below.

## Safe synthetic demo data

After migrating, load the committed metadata-only camera and watchlist dataset:

```bash
cd backend
.venv/bin/python scripts/seed_synthetic_demo.py
.venv/bin/python scripts/seed_synthetic_demo.py --verify
```

It upserts only `demo-cam-*` cameras and watchlist entries from the dedicated
`sentinel-synthetic-demo-v1` source. No stream URLs, credentials, footage, or
real identifiers are included. See [fixtures/README.md](fixtures/README.md).

## Build the active frontend

```bash
# from the repository root
cd frontend-v2
npm ci
npm run lint
npm run build
```

Return to the repository root before starting the backend. A successful build creates `frontend-v2/dist/`, which FastAPI serves at `/`. For frontend development with hot reload, follow [../frontend-v2/README.md](../frontend-v2/README.md) instead.

## Run

```bash
cd backend
DYLD_LIBRARY_PATH="/opt/homebrew/lib" .venv/bin/uvicorn app.main:app --reload --port 8000
```

- UI: http://127.0.0.1:8000/
- API docs (after login): http://127.0.0.1:8000/docs
- Authenticated health check: http://127.0.0.1:8000/api/health

`DYLD_LIBRARY_PATH` is only needed on macOS/Homebrew for WeasyPrint's native libs (cairo/pango/gdk-pixbuf); it's a no-op elsewhere.

At startup the backend idempotently creates the demo super admin from `SUPER_ADMIN_EMAIL`, `SUPER_ADMIN_PASSWORD`, and `SUPER_ADMIN_NAME`. The secret is never embedded in source. Open the UI to sign in or submit a department registration request. Super admins approve department-admin requests; department admins approve employees in their own department. See [ADR 0003](../docs/decisions/0003-department-rbac.md).

Except for login, registration submission/options, and static login assets, routes require the HttpOnly browser session. `POST /api/sightings` and `POST /api/analytics/counts` instead require the separate `X-Sentinel-Worker-Token`; local worker subprocesses receive it from `WORKER_API_TOKEN` without writing it to arguments or logs.

## Running the onboarding pipeline

Each stage is idempotent and independently re-runnable, matching the build spec. The examples below assume an authenticated cookie jar created through `/api/auth/login`; using the operator UI avoids manually handling the HttpOnly session.

```bash
curl -X POST http://127.0.0.1:8000/api/sync              # Stage 1: catalogue sync
curl -X POST http://127.0.0.1:8000/api/probe              # Stage 2: stream probe (all cameras)
curl -X POST http://127.0.0.1:8000/api/survey/capture      # Stage 3: one survey still per camera
curl -X POST http://127.0.0.1:8000/api/geocode             # Stage 4: geocode ungeocoded cameras
```

Append `?camera_id=<id>` to re-run any stage against a single camera. `/api/geocode` also accepts `?force=true` to re-geocode cameras that already have a result.

Stages 1-3 access the configured sandbox; Stages 2/3 open live streams per camera (RTSP with a TCP-forced timeout, falling back to HLS). They can take 20-30s per camera when RTSP is blocked on the current network, so a full catalogue run can take several minutes. Do not run these stages without authorised endpoint configuration and an explicit need for live evidence.

Stage 3 (`anpr_viable` / `anpr_notes`) and department/ownership/type/connectivity/storage/retention are then set per camera through the UI edit form, the `PUT /api/cameras/:id` endpoint, or a CSV bulk import (`POST /api/cameras/bulk`). In CSV, a known nonblank `camera_id` updates a record; a blank ID creates a metadata-first `manual-N` record and requires `name` plus `location_text`; a supplied unknown ID is rejected. There is no automated ANPR-viability judgement, per the build spec.

## Migrations

```bash
cd backend
.venv/bin/alembic revision -m "description"   # new migration
.venv/bin/alembic upgrade head                 # apply
.venv/bin/alembic downgrade -1                 # roll back one
```

## Tests

`scripts/smoke_test.py` exercises a useful API slice against a running backend: authenticated camera CRUD, deterministic offline probe/health-history and maintenance-work-order lifecycle verification, CSV create/update validation, catalogue sync, gap-analysis export, watchlist CRUD/bulk import, worker-authenticated sighting ingestion, watchlist matching, alert deduplication/lifecycle, and journey lookup. Its created rows use a `SMOKETEST` marker and are cleaned up afterward. The test process must have the same `SUPER_ADMIN_*` and `WORKER_API_TOKEN` settings as the backend.

`scripts/rbac_smoke_test.py` uses synthetic accounts/cameras to verify unauthenticated denial, the two-level approval flow, viewer/operator boundaries, home and cross-department grants, camera-maintenance controls, read/denial audit coverage, the paginated audit-event response, database-trigger rejection of direct audit `UPDATE`/`DELETE`, and super-admin-only digest-verifiable NDJSON archive download and external delivery. Configure `AUDIT_ARCHIVE_DIR` to an empty approved test/retention mount before this test; it deliberately leaves a newly delivered archive there. The mount must enforce WORM/object-lock retention in real use—an ordinary local directory only proves delivery, not immutability.

```bash
cd backend
.venv/bin/python scripts/smoke_test.py                        # non-ML API checks; catalogue sync still contacts the configured sandbox
.venv/bin/python scripts/smoke_test.py --live                 # + starts a real analytics worker against a live camera
.venv/bin/python scripts/smoke_test.py --live --camera-id 10  # pin a camera instead of auto-probing
# Start the backend itself with AUDIT_ARCHIVE_DIR configured, then:
.venv/bin/python scripts/rbac_smoke_test.py                    # RBAC + archive delivery
```

The default run is not a complete offline or deterministic test suite: its catalogue-sync check can contact the configured sandbox and skip when unavailable. When both scripts pass on the recorded revision, they provide API-level RBAC/audit evidence including health/maintenance history and registry export, but they do not prove a provisioned WORM/object-lock policy, probe/survey/geocode completion, successful official-live health, ML accuracy, or production identity security. Authenticated GIS browser and project-owner-confirmed second-machine evidence are recorded separately. Record the command, revision, environment, redacted output, and skips before treating a run as checkpoint evidence.

The optional `--live` test probes for a currently reachable camera rather than assuming a fixed ID. It reports worker lifecycle separately from whether a plate happened to be confirmed during the run. Do not use `--live` for routine verification, and never retain observed identifiers or footage in Git or shared logs.

No other automated tests exist yet.
