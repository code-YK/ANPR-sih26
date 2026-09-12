# Backend - control plane and API

FastAPI + PostgreSQL/PostGIS control plane for **SIH26127**. It owns the camera registry, the observation store, watchlist matching, alerting, trajectory reconstruction, RBAC, and the audit trail, and it supervises the analytics worker subprocesses and local media relays.

Design context: [../docs/hld.md](../docs/hld.md) | [../docs/architecture.md](../docs/architecture.md) | [../docs/registry-gis-build-spec.md](../docs/registry-gis-build-spec.md)

The served operator console is `frontend-v3/`. FastAPI serves its production build at `/` when `frontend-v3/dist/` exists. `frontend-v2/` is the previous console, retained as reference; `frontend/` is the original vanilla UI and is not served because it has no authentication flow.

## Directory map

| Path | Contents |
|---|---|
| `app/routers/` | HTTP surface: cameras, sightings, watchlist, alerts, analytics, investigate, auth, demo/government modes |
| `app/services/` | Domain logic outliving a request: gap analysis, districts, demo and government mode |
| `app/models/` | SQLAlchemy models: camera, sighting, alert, watchlist, track, recording, auth, analytics counts |
| `app/pipeline/` | Media and ingest plumbing: capture, probe, media normalisation, catalogue sync, geocode, WebRTC relay |
| `app/templates/` | Jinja templates for HTML/PDF report exports |
| `migrations/` | Alembic migrations. Current head: `202608312000` |
| `scripts/` | Seeds, smoke tests, relay launchers |
| `fixtures/` | Committed, safe camera datasets (see `fixtures/README.md`) |
| `survey/`, `recordings/`, `evidence/` | Runtime output, git-ignored |

## Prerequisites

- **Python 3.11** (not 3.12+ - see [../SETUP.md](../SETUP.md))
- PostgreSQL 16+ with PostGIS, **or** the team's hosted database
- `ffmpeg` / `ffprobe` on `PATH`
- `mediamtx` for live preview and the demonstration modes

## Setup

Full instructions for Windows and Linux are in [../SETUP.md](../SETUP.md). In brief:

```bash
# Linux
python3.11 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt

cd backend
cp .env.example .env    # fill in database URLs, super-admin, worker token, MEDIAMTX_BIN
.venv/bin/alembic upgrade head
```

The database may be local PostgreSQL+PostGIS or the team's hosted instance; swapping between them is a two-line `.env` change, because nothing in the code hard-codes a DSN.

For offline registry/API work, leave the example `.invalid` catalogue URLs unchanged and do not call the live sync/probe/survey stages. Use the committed fixtures described below.

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

## Government camera registry

The real government camera nodes that government mode swaps stream URLs on. Without these rows the toggle has nothing to act on.

```bash
.venv/bin/python scripts/seed_government_cameras.py           # load / refresh
.venv/bin/python scripts/seed_government_cameras.py --verify  # report what is present
.venv/bin/python scripts/seed_government_cameras.py --reset   # remove (refuses if observed)
```

Safe to re-run: it updates metadata but deliberately **never** writes the stream-endpoint columns on an existing row, so re-seeding while government mode is active cannot tear its relay URLs out from under it. `--reset` refuses to delete a camera that already has sightings, alerts, or counts rather than failing on a foreign key.

## Build the served frontend

```bash
npm --prefix frontend-v3 ci
npm --prefix frontend-v3 run build
```

A successful build creates `frontend-v3/dist/`, which FastAPI serves at `/`. For hot-reload development, follow [../frontend-v3/README.md](../frontend-v3/README.md) instead.

## Run

```bash
cd backend
.venv/bin/uvicorn app.main:app --reload --port 8000            # Linux
.venv\Scripts\uvicorn.exe app.main:app --reload --port 8000    # Windows
```

- UI: http://127.0.0.1:8000/
- API docs (after login): http://127.0.0.1:8000/docs
- Authenticated health check: http://127.0.0.1:8000/api/health
- Live backend log stream: `GET /api/logs/backend` (SSE) - how to read a traceback when the server runs in a terminal you cannot see

WeasyPrint powers the HTML/PDF report exports. On Linux, install its native dependencies (cairo, pango, gdk-pixbuf) through your package manager if PDF export fails; the Windows wheels bundle what they need.

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

Write every migration to be **idempotent where it cheaply can be** (`if_not_exists` on index creation). The database is shared across machines, and a migration that assumes a clean schema fails on the second one.

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
