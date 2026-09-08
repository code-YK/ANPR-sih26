# Sentinel Gujarat CCTV Integration

Working repository for the Gujarat Police Innovation Hackathon 2026 CCTV Integration Challenge.

The goal is to deliver a functioning, open-source platform that:

- maintains the mandatory central CCTV registry and GIS map;
- consumes heterogeneous camera feeds without disrupting existing departmental systems;
- performs ANPR and other video analytics;
- continuously matches observations against representative watchlists;
- generates real-time, auditable alerts;
- reconstructs a vehicle's timestamped movement across cameras; and
- presents a credible path from the approximately 50-camera sandbox to approximately 80,000 cameras statewide.

The official challenge website is the authority. Repository documents translate the official material into implementation work and acceptance evidence; they do not replace the official rules.

## Start here

Read these files in order before starting work:

1. [PROJECT_STATE.md](PROJECT_STATE.md) - current status, risks, and next decisions.
2. [docs/requirements.md](docs/requirements.md) - authoritative requirement ledger and traceability matrix.
3. [docs/approach.md](docs/approach.md) - recommended execution plan for a three-person team.
4. [docs/architecture.md](docs/architecture.md) - accepted Phase 1 system shape and data flow.
5. [DESIGN.md](DESIGN.md) - merged operator-console visual direction, tokens, component rules, and remaining evidence gaps.
6. [docs/checkpoints.md](docs/checkpoints.md) - dated milestones and exit criteria.
7. [docs/context-management.md](docs/context-management.md) - cross-machine and cross-LLM collaboration protocol.
8. [docs/sandbox-access.md](docs/sandbox-access.md) - redacted local sandbox access checks, limits, and safe diagnostic commands.
9. [AGENTS.md](AGENTS.md) - operating rules for coding agents.

## Current state

The Phase 1 application stack is implemented, but the mandatory checkpoints are not complete. The repository contains a FastAPI/PostgreSQL/PostGIS backend, an authenticated React operator console, an unserved legacy UI reference, and separate media/analytics workers. Model 1 registry/onboarding/GIS/reporting basics, department RBAC/state-change/read/denial audit, server-enforced registry search/type filtering, scoped CSV/JSON export, health and maintenance history, health-oriented GIS planning controls, database-trigger audit immutability, and digest-verifiable archive export/delivery exist alongside a Model 2 observation-to-alert-to-journey slice. Browser GIS and synthetic reliability evidence are recorded, the second-machine rehearsal has been human-confirmed, and the project owner confirms that official catalogue sync is operational. Provisioned WORM/object-lock archive retention, official/live demonstration evidence, and other requirement-ledger gaps remain. See [PROJECT_STATE.md](PROJECT_STATE.md).

## Accepted solution direction

ADR 0001 accepts:

- mandatory Model 1 registry and GIS foundation;
- Model 2-style direct feed integration for the Phase 1 sandbox;
- a stable connector interface inspired by Model 3 so source-specific logic is replaceable;
- metadata-first, edge-ready analytics so the scale story does not require centralising every video stream; and
- a thin vertical slice first: one catalogue-driven stream -> ANPR observation -> watchlist match -> alert -> GIS journey.

This is a team implementation decision, not an official rule. See [ADR 0001](docs/decisions/0001-proposed-integration-shape.md) and the accepted stack in [ADR 0002](docs/decisions/0002-phase-1-implementation-stack.md).

## Repository layout

```text
.
|-- README.md
|-- AGENTS.md
|-- PROJECT_STATE.md
|-- CONTRIBUTING.md
|-- backend/
|-- frontend-v2/
|-- frontend/
|-- multi-object-tracking/
|-- docs/
|   |-- requirements.md
|   |-- approach.md
|   |-- architecture.md
|   |-- checkpoints.md
|   |-- context-management.md
|   |-- api.md
|   |-- source-register.md
|   |-- sandbox-access.md
|   |-- task-template.md
|   |-- decisions/
|   `-- handoffs/
`-- .github/
    |-- pull_request_template.md
    `-- ISSUE_TEMPLATE/
```

`frontend-v2/` is the active and only served operator console. `frontend/` is retained as migration history but is not mounted because it has no authentication flow. The backend and analytics worker remain separate processes even though the backend is a modular monolith.

## Branch and review workflow

`main` is the shared working source of truth. After this documentation baseline is accepted, all work should happen on short-lived branches and return through pull requests.

Examples:

```text
feat/camera-ingestion
feat/anpr-watchlist-alerts
feat/gis-vehicle-tracking
feat/dashboard
docs/submission-package
fix/alert-deduplication
```

Rules:

1. Pull the latest `main` before creating a branch.
2. Keep one branch focused on one independently reviewable outcome.
3. Link every PR to requirement IDs and checkpoint acceptance criteria.
4. Another teammate reviews the PR.
5. Merge only when the shared demo still runs and the evidence is recorded.
6. Delete the feature branch after merge.
7. Tag stable checkpoints, for example `v0.1-camera-ingestion`, `v0.2-alerting`, and `v1.0-submission`.

A permanent `develop` branch is intentionally not used.

## Setup and run commands

The API and persistence layer live in `backend/`. The active React console lives in `frontend-v2/`; a production build is served by FastAPI when `frontend-v2/dist/` exists. The vanilla `frontend/` is retained only as an unserved migration reference. The separate ANPR/person analytics environment is documented in [multi-object-tracking/README.md](multi-object-tracking/README.md). See [backend/README.md](backend/README.md) and [frontend-v2/README.md](frontend-v2/README.md).

The authenticated general smoke suite covers registry CRUD, health and maintenance history, CSV updates, catalogue sync, gap-report exports, watchlists, observations, matching, alerts, and journeys. A separate synthetic RBAC suite covers roles, approvals, grants, read/denial audit, maintenance controls, database-level audit immutability, and digest-verifiable archive download/delivery. They do not prove all-camera probe/survey/geocode completion, a provisioned immutable retention policy, official/live feed health, production identity security, or ML accuracy. A same-host clean-clone rehearsal passed on Python 3.13, and the project owner has confirmed a teammate second-machine rehearsal; keep a redacted reviewer transcript with the submission materials.

## Source priority

When sources disagree, use this order:

1. Current official Sentinel website and authenticated challenge resources.
2. Official announcements or direct organiser clarification.
3. Accepted repository decisions and merged contracts.
4. The supplied Sentinel Playbook and other secondary summaries.
5. Chat history, agent memory, or local notes.

See [docs/source-register.md](docs/source-register.md) for verification status and known ambiguities.
