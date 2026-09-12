# Sentinel — City-Wide AI Engine for Multi-Camera ANPR Trajectory Tracking and Urban Traffic Analytics

Working repository for **Smart India Hackathon 2026, Problem Statement SIH26127**, proposed by **Bharat Electronics Limited (BEL)**.

| | |
|---|---|
| Problem Statement ID | **SIH26127** (S.No. 127) |
| Title | City-Wide AI Engine for Multi-Camera ANPR Trajectory Tracking and Urban Traffic Analytics |
| Organisation / Department | Bharat Electronics Limited (BEL) |
| Category | Software |
| Theme | Transportation & Logistics |
| Idea submission deadline | **2026-09-30** |
| Dataset supplied by organiser | None (`N/A` on the problem-statement listing) |

> `Sentinel` is this team's internal codename for the platform. It is not a BEL or SIH product name.

## The problem, in the organiser's terms

Cities already run large CCTV and ANPR estates, but most systems **process those feeds in isolated silos** — reading plates without linking observations across space and time. Authorities therefore cannot automatically follow a vehicle of interest between sectors, and cannot extract macro-level movement trends from cameras they already own.

The platform must therefore do three things across a **city-wide, multi-camera** network:

1. **High-accuracy ANPR/OCR** — >90 % recognition across varying lighting, poor weather, angled shots, motion blur, and dirty or damaged plates.
2. **Single-plate trajectory tracking** — reconstruct any one plate's complete travel path across the city, with movement history, timestamps, direction, and route drawn on a GIS map.
3. **Macro traffic flow and movement analytics** — traffic density, origin–destination patterns, congestion bottlenecks, and real-time heatmaps from the aggregated camera data.

## The four expected components, and where each stands

The problem statement names four components. This table is the honest, one-glance status; the per-requirement detail and evidence live in [docs/requirements.md](docs/requirements.md).

| # | Expected component | State | What exists today |
|---|---|---|---|
| 1 | **High-Precision OCR Module** (>90 % on multi-lane streams) | In progress | YOLO11 + ByteTrack + fast-alpr running on CUDA, confirmed reading real Indian plates at 0.88–1.00 confidence with vote-based confirmation. **The >90 % figure is not yet measured** — that needs ground-truth labelled footage this repository does not have. |
| 2 | **Trajectory Reconstruction Engine** (query-based, chronological, on a map) | In progress | Query any plate → ordered stops with camera, coordinates, source timestamp, confidence, evidence crop; timeline + numbered route map; JSON/CSV/HTML/PDF export. Direction and corridor speed exist on an unmerged branch (see below). |
| 3 | **City Traffic Analytics Dashboard** (heatmaps, speeds, route density, flow trends) | Partially built, **unmerged** | Built on the `new-implementations` branch: corridor transit, density over time, congestion vs. baseline, origin/destination node pairs, read-yield, four-format export, and a `Traffic` console view. Not yet on `main` and never run against a live database. |
| 4 | **Alert System** (blacklisted vehicles + suspicious route anomalies) | In progress | Blacklist alerting works end to end — watchlist match → deduplicated alert → operator acknowledge/resolve, all audited. **Route-anomaly** detection (dwell, looping, implausible transit) is implemented in the same unmerged analytics branch. |

## Current state, plainly

A working vertical slice runs today: **camera registry → live feed → ANPR → sighting → watchlist alert → cross-camera journey on a GIS map**, with an authenticated React operator console, department-scoped RBAC, and an audit trail.

Verified on this machine (2026-09-12):

- 16 government cameras onboarded with real coordinates; a five-camera corridor along Ahmedabad's SG Highway is `exact`-geocoded specifically so trajectory and corridor analytics have real geometry to work with.
- ANPR reading 13 distinct plates from a live relayed feed, writing `sightings`, and raising watchlist alerts.
- Offline forensic search (**Investigate**) ingesting an uploaded recording: 158 vehicle tracks and 154 person tracks with appearance embeddings, plate search, and person-photo search.

Not yet true, and deliberately not claimed:

- No measured OCR accuracy figure against ground truth.
- The traffic-analytics dashboard is not merged to `main`.
- No per-camera speed or heading — **no camera in the registry is calibrated**, and some are PTZ. Corridor speed ships as a straight-line *lower bound*, never a speeding finding. See [`docs/requirements.md`](docs/requirements.md) `SIH-ANLY-006`.
- Scale, cost, and production-security narratives are not written.

## Start here

Read in this order before changing anything:

1. [SETUP.md](SETUP.md) — get it running on Windows or Linux.
2. [PROJECT_STATE.md](PROJECT_STATE.md) — current status, risks, open decisions.
3. [docs/requirements.md](docs/requirements.md) — the requirement ledger and traceability matrix.
4. [docs/hld.md](docs/hld.md) — High-Level Design, with architecture diagrams.
5. [docs/architecture.md](docs/architecture.md) — component responsibilities and data flow.
6. [docs/decisions/](docs/decisions/) — accepted architecture decisions (ADRs).
7. [AGENTS.md](AGENTS.md) — operating rules for coding agents and contributors.

## Repository layout

```text
.
├── backend/                  FastAPI + PostgreSQL/PostGIS control plane and API
│   ├── app/                  routers, services, models, media pipeline
│   ├── migrations/           Alembic migrations
│   ├── scripts/              seeds, smoke tests, relay launchers
│   └── fixtures/             safe synthetic + government camera fixtures
├── frontend-v3/              React 19 + Vite operator console  ← served at /
├── frontend-v2/              previous console, retained as reference
├── frontend/                 original vanilla UI, unserved, historical
├── multi-object-tracking/    ANPR / person / suspicious / ingest workers (own venv)
├── docs/                     requirements, HLD, architecture, ADRs, testing guides
├── artifacts/                dated, redacted verification evidence packets
└── sandbox-test/             standalone client used to probe a camera catalogue
```

Each of those directories has its own `README.md` describing its contents in depth.

Three directories are **required to run the demo but deliberately not in Git** — see [SETUP.md](SETUP.md#external-assets-not-in-git):

- `recorded-streams/` — real government-feed recordings (~673 MB) replayed by government mode
- `tools/` — the `mediamtx` binary (per-OS, not vendored)
- `multi-object-tracking/*.pt`, `*.onnx` — model weights

## Technology

| Layer | Choice |
|---|---|
| Backend | Python 3.11, FastAPI, SQLAlchemy 2, Alembic, Uvicorn |
| Database | PostgreSQL 16+ with PostGIS (currently hosted on Neon, PostgreSQL 18.6 / PostGIS 3.6.4) |
| Frontend | React 19, Vite 8, React Router, React Leaflet, GSAP |
| ANPR / CV | YOLO11, ByteTrack, fast-alpr, ONNX Runtime (CUDA), OpenCV |
| Media | FFmpeg / ffprobe, MediaMTX (RTSP/HLS/WHEP relay) |

Exact pinned versions are in [docs/decisions/0002-implementation-stack.md](docs/decisions/0002-implementation-stack.md), `backend/requirements.txt`, and `frontend-v3/package-lock.json`.

## Demo and government modes

Two super-admin toggles in **Access admin → Advanced** let the platform run without reachable live cameras, without changing any downstream logic:

- **Government mode** — repoints already-onboarded cameras at a local MediaMTX relay serving real recorded government footage. Onboarding, ANPR, trajectory, analytics, and alerting all run *completely unmodified*, because as far as the rest of the system is concerned these are just that camera's stream URLs. Turning it off restores the original URLs.
- **Demo mode** — the mirror image: hides catalogue cameras and stands up a small synthetic rehearsal environment.

The two are mutually exclusive. Details in [docs/demo-and-government-modes.md](docs/demo-and-government-modes.md).

## Branch and review workflow

`main` is the shared source of truth. Work on short-lived branches and return through pull requests.

```text
feat/ocr-accuracy-benchmark
feat/traffic-analytics-merge
fix/trajectory-ambiguous-match
docs/submission-package
```

1. Pull the latest `main` before branching.
2. One branch, one independently reviewable outcome.
3. Link every PR to requirement IDs from [docs/requirements.md](docs/requirements.md).
4. Another teammate reviews.
5. Merge only when the demo still runs and the evidence is recorded.
6. Delete the branch after merge.

There is no permanent `develop` branch.

### Active branches

- `main` — integrated reality.
- `new-implementations` — city-wide traffic-flow analytics (expected component 3) plus route anomalies. Unit-tested (15/15, no database) but never exercised against a running backend. See [PROJECT_STATE.md](PROJECT_STATE.md) for the merge considerations.

## Source priority

When sources disagree:

1. The official SIH 2026 problem-statement listing for SIH26127 and any organiser clarification.
2. The supplied BEL requirements document.
3. Accepted repository decisions (ADRs) and merged contracts.
4. Chat history, agent memory, or local notes — lowest.

See [docs/source-register.md](docs/source-register.md) for verification status and known ambiguities.
