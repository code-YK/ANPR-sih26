# Backend - control plane and API

FastAPI + PostgreSQL/PostGIS control plane for **SIH26127**. It owns the camera registry, the observation store, watchlist matching, alerting, trajectory reconstruction, RBAC, and the audit trail, and it supervises the analytics worker subprocesses and local media relays.

Design context: [../docs/hld.md](../docs/hld.md) | [../docs/architecture.md](../docs/architecture.md) | [../docs/registry-gis-build-spec.md](../docs/registry-gis-build-spec.md)

The served operator console is `frontend-v5/`. FastAPI serves its production build at `/` when `frontend-v5/dist/` exists. `client/` is a second console under active development and proxies `/api` here from its own dev server on port 5174, but its build is **never** mounted — see the repository [README](../README.md#which-console-is-served).

## Directory map

| Path | Contents |
|---|---|
| `app/routers/` | HTTP surface: cameras, sightings, watchlist, alerts, analytics, investigate, auth, demo/government modes, copilot |
| `app/agent/` | Copilot: tool registry, system prompt, model loop, and the tools themselves (see [Copilot](#copilot)) |
| `app/services/` | Domain logic outliving a request: gap analysis, districts, demo and government mode |
| `app/models/` | SQLAlchemy models: camera, sighting, alert, watchlist, track, recording, auth, analytics counts |
| `app/pipeline/` | Media and ingest plumbing: capture, probe, media normalisation, catalogue sync, geocode, WebRTC relay |
| `app/templates/` | Jinja templates for HTML/PDF report exports |
| `migrations/` | Alembic migrations. Current head: `202608312000` |
| `scripts/` | Seeds, smoke tests, relay launchers |
| `tests/` | Offline `pytest` suite (no database, no network) |
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
npm --prefix frontend-v5 ci
npm --prefix frontend-v5 run build
```

A successful build creates `frontend-v5/dist/`, which FastAPI serves at `/`. Building `client/` does not change what is served; run it on its own dev server (`npm --prefix client run dev`, port 5174) instead. For hot-reload development of the served console, follow [../frontend-v5/README.md](../frontend-v5/README.md).

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

## Copilot

The console's natural-language assistant. An operator types "trace HR29BG7381"; the assistant calls the matching backend operation, answers from tool results, and opens the Journey page behind the chat panel.

It runs **in-process** rather than as an MCP server so its tools execute under the caller's own `AuthContext` — see [ADR 0005](../docs/decisions/0005-copilot-in-process-agent.md) for why that is a security requirement rather than a preference. Endpoint contract: [../docs/api.md](../docs/api.md).

The backend half is UI-agnostic, and both live consoles have a panel over it: `frontend-v5/src/features/copilot/` (zustand + react-query) and `client/src/components/Copilot.jsx` with `client/src/lib/copilot.js` (React context + plain hooks). The two SSE parsers are deliberate duplicates — the consoles have separate builds and no shared package — so a change to the event protocol must be made in both. `client` translates the backend's `frontend-v5` routes to its own (`/journeys` → `/journey`); it focuses a camera through local state rather than the URL, so `navigate_to(page='live_camera')` opens the Live view without deep-linking that camera.

### Enabling it

Add an [OpenRouter](https://openrouter.ai/keys) key to `backend/.env` and restart:

```
OPENROUTER_API_KEY=sk-or-v1-...
```

Startup logs which way it went (`Copilot enabled (model: …)` / `Copilot disabled: OPENROUTER_API_KEY is not set`). Unset, `GET /api/copilot/status` reports `available: false`, the console hides its launcher, and nothing else is affected. The key is server-side only — never place it in a `VITE_*` variable, which Vite compiles into the browser bundle.

The model **must** support native tool calling (`"tools"` in its `supported_parameters` on OpenRouter); without it the assistant can only chat. Override with `OPENROUTER_MODEL`. Costs below are per exchange at roughly 10k input tokens — the system prompt plus 19 tool schemas, resent on each completion, twice for a tool-calling turn — and ~300 output.

| Model | per 1M tokens | per exchange | |
|---|---|---|---|
| `openai/gpt-5-mini` | $0.25 / $2 | ~$0.003 | default; the cost/accuracy knee |
| `google/gemini-2.5-flash` | $0.30 / $2.50 | ~$0.004 | equivalent, 1M context |
| `openai/gpt-5-nano` | $0.05 / $0.40 | ~$0.0006 | cheaper, weaker on multi-tool turns |
| `openrouter/free` | free | free | rate-limited; development only |

### Guardrails

Scope never comes from the model: no tool exposes `department`, `user_id`, `role`, `clearance`, `auth` or `session` in its schema, asserted at registration and by test. There is no per-action confirmation step, which is safe only because the registry contains no irreversible operation — no delete, camera administration, catalogue sync, mode toggle or user administration is reachable, and a test asserts those names stay absent. Adding a destructive tool means building a confirmation flow first. Every call appends a `copilot.tool_invoked` audit event.

### Operating it

```bash
cd backend
.venv/bin/python scripts/copilot.py key              # balance, configured model, cost per exchange
.venv/bin/python scripts/copilot.py key --models     # cheapest tool-capable models
.venv/bin/python scripts/copilot.py tools            # every tool against the real database
.venv/bin/python scripts/copilot.py tools --mutate   # also start, then stop, ANPR on one camera
.venv/bin/python scripts/copilot.py prompts          # behaviour checklist against the real model
.venv/bin/python scripts/copilot.py ask "trace HR29BG7381"
```

`tools` needs only the database. `key`, `prompts` and `ask` call OpenRouter and cost a request. The API key is never printed.

`prompts` is the check that matters: `pytest` fakes the model, so it proves the plumbing but says nothing about whether the system prompt actually asks instead of guessing. Models are non-deterministic — re-run a single failure with `--case <name>` before editing `app/agent/prompt.py`.

**Recorded 2026-09-23** on `openai/gpt-5-mini`, commit pending: `tools` 14/14 read tools and 4/4 refusals; `prompts` 9/9 — including asking which camera rather than choosing one, calling `find_cameras_near` instead of inventing a camera id, declining `delete camera cam11`, and demanding a reason before a watchlist write. Not yet verified: prompt-injection resistance against adversarial OCR text, and the panel in a signed-in browser.

## Migrations

```bash
cd backend
.venv/bin/alembic revision -m "description"   # new migration
.venv/bin/alembic upgrade head                 # apply
.venv/bin/alembic downgrade -1                 # roll back one
```

Write every migration to be **idempotent where it cheaply can be** (`if_not_exists` on index creation). The database is shared across machines, and a migration that assumes a clean schema fails on the second one.

## Tests

```bash
cd backend
.venv/bin/python -m pytest        # 76 offline tests; no database, no network, no API key
```

`tests/` covers the Copilot only. It runs against fakes on purpose — the point is the registry's contract, not SQLAlchemy, and the routers it delegates to are covered by the smoke tests below. `test_copilot_registry.py` asserts the scope invariant (no tool leaks `department`/`user_id`/`auth` into a generated schema), the exact set of mutating tools, and the absence of every destructive name. `test_copilot_permissions.py` covers ANPR needing camera-admin while Person/Suspicious need only operator clearance, and 404-before-403 ordering. `test_copilot_loop.py` covers streamed tool-call reassembly, result truncation, the iteration cap, and that dispatches never overlap on the shared `AsyncSession`. `test_copilot_endpoint.py` drives the real HTTP endpoint: SSE framing, 503 when unconfigured, request validation, rate limiting, and that a `system` role cannot be injected through the transcript.

For behaviour against a real model, see [Copilot](#copilot) — `pytest` cannot prove the system prompt works.

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

Outside `tests/` and these two scripts, no other automated tests exist yet.
