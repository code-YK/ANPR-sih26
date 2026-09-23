# Project State

Last updated: 2026-09-22 — plate confirmation reworked (padded OCR crops, per-character multi-frame vote, Delhi/BH plate grammar) and reflected in the backend, `client` and `frontend-v5`. Earlier, 2026-09-12 — repository re-scoped from the earlier Gujarat CCTV programme to **SIH 2026 PS SIH26127 (Bharat Electronics Limited)**; government/demo mode toggles ported into `main`; hosted database adopted; Windows platform defects fixed.

This is the smallest canonical snapshot of the project. Update it in any PR that changes priorities, architecture status, milestone status, or known risks. It must describe **merged reality on `main`**, not unmerged aspirations.

## Problem statement

| | |
|---|---|
| ID | **SIH26127** (S.No. 127) |
| Title | City-Wide AI Engine for Multi-Camera ANPR Trajectory Tracking and Urban Traffic Analytics |
| Organisation | Bharat Electronics Limited (BEL) |
| Category / Theme | Software / Transportation & Logistics |
| Idea submission deadline | **2026-09-30** |
| Organiser-supplied dataset | None |

## Status

- **Phase:** a working vertical slice is merged — camera registry → live feed → ANPR → sighting → watchlist alert → cross-camera trajectory on a GIS map — with an authenticated operator console, department-scoped RBAC, and an audit trail. Of the four expected components, 1, 2 and 4 have working implementations with open accuracy/coverage gaps; component 3 (traffic analytics dashboard) is built but **unmerged**. A conversational assistant over the existing API (`SIH-PLAT-011`, Bonus) is also built and **unmerged**.
- **Branch:** `main`. Unmerged work lives on `new-implementations` (traffic analytics) and `feat/copilot-agent` (the assistant).
- **Application code:**
  - `backend/` — FastAPI + PostgreSQL/PostGIS control plane; supervises analytics subprocesses and local MediaMTX relays.
  - `frontend-v5/` — React 19 + Vite operator console, **the served UI** (`backend/app/main.py` mounts `frontend-v5/dist` at `/`). Dev server on port 5175.
  - `client/` — a second React 19 + Vite console under active development on port 5174. It proxies `/api` to the backend but **its build is never served** — `main.py` does not list `client/dist`. Two consoles are maintained in parallel; a feature added to one does not appear in the other, which has already caused confusion. Which becomes canonical is an open decision.
  - `multi-object-tracking/` — ANPR, person-count, suspicious-activity, and offline recording-ingest workers, plus person-appearance embedding. Own virtualenv and GPU stack.
- **Database:** hosted PostgreSQL 18.6 + PostGIS 3.6.4 (Neon, `ap-southeast-1`). The direct endpoint is used deliberately, not the pooler — PgBouncer transaction pooling breaks asyncpg prepared statements. Swapping back to a local Postgres is a two-line `.env` change; nothing in the code hard-codes a DSN.
- **Alembic head:** `202608312000`. Note the shared database was stamped back to this from `202609101000` on 2026-09-12 so `main` could migrate; see *Open decisions*.
- **Local runtimes:** Python 3.11.9 (both venvs), Node 24.19.0, PostgreSQL client 16, FFmpeg 9.0.1, MediaMTX (project-local), CUDA 12.8 / torch 2.11.0+cu128 on an RTX 5060 (sm_120).

## Verified on 2026-09-12

All of the following were exercised end to end against the hosted database on this machine:

| Capability | Result |
|---|---|
| Government mode | 16/16 cameras swapped to the local relay; real recorded footage playing in the Live wall; original URLs restored on disable |
| ANPR | 13 distinct plates read from a relayed feed, confidence 0.881–1.000, vehicle types classified |
| Watchlist alerting | 2 watchlisted plates → 2 `watchlist` alerts, correct camera and severity |
| Trajectory | Journey query, timeline, numbered route map, four-format export |
| Investigate (vehicle) | 1136 frames → 158 tracks in 74 s |
| Investigate (person) | 1136 frames → 154 tracks, 154 appearance embeddings |
| Person-photo search | 5 ranked candidates; query image matched itself at 1.0000 |
| Operator console | All six views render; no JS errors; only pre-login `401` session probes |

## Current objective

In priority order:

1. **Measure OCR accuracy** against ground-truth labelled footage (`SIH-OCR-002`). This is the only way the problem statement's headline >90 % claim becomes defensible, and it is currently unevidenced.
2. **Merge the traffic-analytics branch** (`SIH-ANLY-*`) and verify it against the live database.
3. **Wire route anomalies into the alert queue** (`SIH-ALERT-006`) — they are currently derived but only reported through traffic endpoints.
4. **Build the heatmap layer** (`SIH-ANLY-004`).
5. Replace the earlier programme's presentation deck with an SIH26127 one.

## Architecture status

Accepted: a **modular monolith** for registry, watchlists, alerts, trajectories, RBAC, and API, with **independent media/analytics workers** and a replaceable source-connector boundary. See [docs/hld.md](docs/hld.md) and [docs/architecture.md](docs/architecture.md).

Decision records: [ADR 0001](docs/decisions/0001-integration-shape.md), [ADR 0002](docs/decisions/0002-implementation-stack.md), [ADR 0003](docs/decisions/0003-department-rbac.md), [ADR 0004](docs/decisions/0004-sih26127-rescope.md), [ADR 0005](docs/decisions/0005-copilot-in-process-agent.md).

## Open decisions

| Decision | Owner | Status |
|---|---|---|
| Replace the inherited presentation deck with an SIH26127 one | Team | **Open** — the committed `Sentinel-Gujarat-*.pptx` files are from the previous programme and are not valid for this submission |
| Which operator console is canonical — `frontend-v5/` or `client/` | Team | **Open** — both are actively developed React 19 + Vite consoles, but only `frontend-v5/dist` is mounted at `/`; `client/` exists only behind its own dev server. Maintaining both doubles every UI change and has already produced a feature that appeared in one console and not the other. Pick one, or state explicitly why two are kept |
| Merge `feat/copilot-agent` (conversational assistant) into `main` | Team | **Open** — implemented for both consoles with 76 backend tests and measured tool/behaviour evidence ([ADR 0005](docs/decisions/0005-copilot-in-process-agent.md), `SIH-PLAT-011`). Neither panel has been exercised in a signed-in browser, and prompt-injection resistance is unproven |
| Merge `new-implementations` (traffic analytics) into `main` | Team | **Open** — its migration `202609101000` uses bare `op.create_index` and will fail against the shared database, whose indexes already exist. Add `if_not_exists`, or stamp forward. The branch has never run against Postgres |
| Obtain or produce ground-truth labelled footage for OCR accuracy | Team | **Open** — blocks `SIH-OCR-002`, the headline requirement |
| Camera calibration for per-camera speed | Team | **Open** — without homography/PTZ handling, only corridor lower-bound speed is honest. This is a deployment input, not a code change |
| Where `cam01`'s recording belongs | Team | **Open** — 16 of 17 recordings map to a registry camera; `cam01` has no row in any database and stays unmatched |
| Rotate the shared database and worker credentials before submission | Team | **Open** — they have circulated in team channels |
| Repository licence before any publication | Team | **Open** |

## Progress by expected component

| Component | State | Notes |
|---|---|---|
| 1. High-Precision OCR Module | In progress | Works and is GPU-accelerated; **>90 % accuracy unmeasured** (`SIH-OCR-002`). A silent CPU-fallback bug costing ~9× was fixed 2026-09-12. Plate confirmation reworked 2026-09-22 (padded OCR crop, per-character vote over ≥3 frames, strict grammar incl. Delhi and BH series, two-row plates read from 55 px): on 60 hand-labelled plates from 9 recorded clips, confirmed-plate precision went from 10/18 (8 false plates) to 22/22 with no speed cost except ~18% on two-wheeler-heavy scenes. That is precision of what gets published, not the >90 % read-accuracy benchmark, and recall stays low on overhead/blurred cameras |
| 2. Trajectory Reconstruction Engine | In progress | Query → ordered stops → map/timeline → export all work. Direction of travel and implausible-transit flagging are unmerged |
| 3. City Traffic Analytics Dashboard | **Unmerged** | Density, O–D pairs, congestion baseline, route density, read-yield and a `Traffic` view exist on `new-implementations`; heatmap layer not built; never run against a database |
| 4. Alert System | In progress | Blacklist alerting verified end to end. **Route-anomaly alerts are not yet raised into the alert queue** |
| Platform: registry + GIS | Ready for review | 16 government cameras with real coordinates; map, filters, health, unplaced list all verified in-browser |
| Platform: multi-camera ingestion | In progress | 16 concurrent relayed feeds; bounded per-mode worker pools. Per-GPU capacity unmeasured |
| Platform: Investigate (offline search) | Ready for review | Vehicle and person ingest, plate search, person-photo search. Person search uses a generic backbone, not a ReID model |
| Platform: demo / government modes | Done | Verified across 16 cameras; drift between state file and database is detected and one-click repairable |
| Security / RBAC / audit | In progress | Roles, scoping, append-only audit, and a verifiable archive exist. No deployment security design; WORM destination unprovisioned |
| Scale and cost narrative | Not started | |
| Submission package | Not started | |

Allowed states: `Not started`, `In progress`, `Blocked`, `Unmerged`, `Ready for review`, `Done`.

## Known risks

| Risk | Impact | Mitigation |
|---|---|---|
| The headline >90 % OCR accuracy is unmeasured | **High** | Obtain labelled ground truth and publish precision/recall with an error taxonomy. Never state >90 % without it |
| Cameras are uncalibrated, so per-camera speed is not derivable | High | Ship corridor lower-bound speed only, label it as such, and state the limitation in the API and the deck |
| Component 3 is unmerged and unverified against a database | High | Merge early, fix the non-idempotent migration, and exercise every endpoint against the hosted database |
| Plate misread creates a false cross-camera link | High | Confirmed-vote-only writes (≥3 frames agreeing on every character of a plate valid as read), confidence gate for alerts, implausible-transit flagged as a data fault. A misread that repeats identically across frames can still be confirmed; only a better OCR model removes that |
| Traffic counts mistaken for true volume | Medium | A sighting requires a confirmed plate, so every count is a floor. Publish read-yield alongside every density figure |
| Recorded demo footage mistaken for a live city deployment | Medium | Government mode is clearly labelled in the console and in this document |
| Shared credentials have circulated | Medium | Rotate before submission; `.env` is git-ignored and the secret scan is clean |
| Team spans Windows and Linux | Medium | Both documented in SETUP.md; three Windows-only defects already found and fixed. Run a clean-clone rehearsal on both |
| Status claims outrun evidence | High | `Unmerged` is a distinct state; quantitative claims require measurements |

## Inherited work

This repository began as a submission for a different programme (a Gujarat CCTV integration challenge) and was re-scoped to SIH26127. That history is useful, not embarrassing: the registry, GIS, RBAC, audit, watchlist, alerting, and media-ingestion foundations were all built there and map cleanly onto this problem statement's platform needs.

Two consequences to be aware of:

- That programme's `Model 1 / 2 / 3 / 4` vocabulary **does not exist in SIH26127** and has been removed from the documentation. Where you still see it in `artifacts/` (dated evidence packets) it is left untouched, because rewriting historical evidence would be dishonest.
- `sentinel-playbook.md` and the `Sentinel-Gujarat-*.pptx` files are prior-programme material retained for reference only. They are not SIH26127 deliverables.

See [ADR 0004](docs/decisions/0004-sih26127-rescope.md) for the re-scope decision and what it did and did not change.
