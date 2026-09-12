# ADR 0002: Implementation stack

Status: Accepted

Date: 2026-08-30

Owners: Team

## Context

The application stack was implemented before the decision was recorded. Leaving it open would make the documentation disagree with merged reality and encourage incompatible parallel implementations. The selected stack must support a short delivery window, reproducible local development on **Windows and Linux**, PostGIS-backed registry and GIS features, live media processing, and a replaceable connector boundary.

## Decision

Use the following Phase 1 stack:

- **Python 3.11** for the backend and media/analytics workers (see the version note below);
- FastAPI 0.115.6 with Uvicorn 0.34.0 for the HTTP application;
- SQLAlchemy 2.0.36 and Alembic 1.14.0 for persistence and migrations;
- PostgreSQL 16+ with PostGIS for registry, spatial, observation, watchlist, alert, and trajectory metadata (currently hosted: PostgreSQL 18.6 / PostGIS 3.6.4);
- React 19 with Vite 8 and React Router for the served operator console (`frontend-v3`);
- Leaflet 1.9 through React Leaflet 5 for GIS presentation;
- FFmpeg/ffprobe and OpenCV for stream probing, capture, decode, and frame handling;
- YOLO11 with ByteTrack and fast-alpr/ONNX Runtime for the current ANPR baseline; and
- direct worker subprocesses supervised by the modular monolith, without Redis, Kafka, Kubernetes, or a local microservice split; and
- **CUDA 12.8+** with torch 2.11.0+cu128 for the analytics environment - mandatory, not advisory, on RTX 50-series (Blackwell, sm_120) hardware.

The exact backend package lock is `backend/requirements.txt`. The exact frontend dependency graph is `frontend-v3/package-lock.json`. Native dependencies - PostgreSQL/PostGIS, FFmpeg, MediaMTX, GPU drivers, CUDA, ONNX Runtime - must be recorded on the demonstration machine.

### Why Python 3.11, not newer

The team standardised on 3.11 when the hosted database and Windows/Linux split were adopted. The whole codebase is verified against 3.11.9 via `compileall` plus live exercise. This is a real constraint, not a preference: one file previously used an f-string containing a backslash, which parses only on 3.12+ and fails outright on 3.11. Pinning one version across the team means everyone hits the same behaviour.

The ML requirements currently use minimum-version ranges for several packages. They are accepted as the working baseline, not as a reproducible lock. Producing a tested ML lock or environment manifest remains a `SIH-NFR-008` gap and is deliberately not claimed complete by this ADR.

## Consequences

Positive:

- the accepted decision matches the implemented code;
- one backend process keeps deployment and transactions simple;
- PostGIS supports registry/GIS and trajectory enrichment without a separate spatial service;
- the React console and media workers can evolve independently behind documented APIs; and
- heavy distributed infrastructure is deferred until measurements justify it.

Negative:

- worker supervision is process-local and is not a production scheduler;
- the unversioned `/api` implementation diverges from the target `/api/v1` contract;
- native media/GPU dependencies are harder to reproduce than pure package locks; and
- the ML environment is not yet fully pinned.

## Alternatives considered

- Django or Node backend: viable, but replacing the merged FastAPI implementation would add risk without improving checkpoint evidence.
- Redis/Kafka orchestration now: useful later, but unnecessary for the current bounded worker count.
- Kubernetes for the local demo: deferred because it adds operational scope without satisfying a current checkpoint.
- A full central VMS: rejected under ADR 0001.

## Validation / revisit trigger

- A clean-clone rehearsal must prove the documented backend and frontend setup.
- Record exact native and ML versions used for the submission candidate.
- Revisit process-local worker supervision when concurrency, failure recovery, multi-host deployment, or regional buffering requires a durable scheduler/event bus.
- Revisit PostgreSQL-only search when measured event volume or query latency requires a separate search system.
