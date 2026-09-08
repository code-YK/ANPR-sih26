# ADR 0002: Phase 1 implementation stack

Status: Accepted

Date: 2026-08-30

Owners: Team

## Context

The application stack was implemented before the C1 stack decision was recorded. Leaving the decision open would make the documentation disagree with merged reality and would encourage incompatible parallel implementations. The selected stack must support a short Phase 1 delivery window, reproducible local development, PostGIS-backed Model 1 features, live media processing, and a replaceable connector boundary.

## Decision

Use the following Phase 1 stack:

- Python 3.13 for the backend and media/analytics workers;
- FastAPI 0.115.6 with Uvicorn 0.34.0 for the HTTP application;
- SQLAlchemy 2.0.36 and Alembic 1.14.0 for persistence and migrations;
- PostgreSQL 17 with PostGIS for registry, spatial, observation, watchlist, alert, and journey metadata;
- React 19 with Vite 8 and React Router for the active operator console;
- Leaflet 1.9 through React Leaflet 5 for GIS presentation;
- FFmpeg/ffprobe and OpenCV for stream probing, capture, decode, and frame handling;
- YOLO11 with ByteTrack and fast-alpr/ONNX Runtime for the current ANPR baseline; and
- direct worker subprocesses supervised by the modular monolith for Phase 1, without Redis, Kafka, Kubernetes, or a local microservice split.

The exact backend package lock is `backend/requirements.txt`. The exact frontend dependency graph is `frontend-v2/package-lock.json`. Native dependencies such as PostgreSQL/PostGIS, FFmpeg, GPU drivers, CUDA, and ONNX Runtime compatibility must be recorded on the demo machine.

The ML requirements currently use minimum-version ranges for several packages. They are accepted as the working baseline, not as a reproducible lock. Producing a tested ML lock or environment manifest remains a `TEAM-NFR-002` gap and is deliberately not claimed complete by this ADR.

## Consequences

Positive:

- the accepted decision matches the implemented code;
- one backend process keeps Phase 1 deployment and transactions simple;
- PostGIS supports registry/GIS and journey enrichment without a separate spatial service;
- the React console and media workers can evolve independently behind documented APIs; and
- heavy distributed infrastructure is deferred until measurements justify it.

Negative:

- worker supervision is process-local and is not a production scheduler;
- the unversioned `/api` implementation diverges from the target `/api/v1` contract;
- native media/GPU dependencies are harder to reproduce than pure package locks; and
- the ML environment is not yet fully pinned.

## Alternatives considered

- Django or Node backend: viable, but replacing the merged FastAPI implementation would add risk without improving checkpoint evidence.
- Redis/Kafka orchestration in Phase 1: useful later, but unnecessary for the current bounded worker count.
- Kubernetes for the local demo: deferred because it adds operational scope without satisfying a current checkpoint.
- A full central VMS: rejected for Phase 1 under ADR 0001.

## Validation / revisit trigger

- A clean-clone rehearsal must prove the documented backend and frontend setup.
- Record exact native and ML versions used for the submission candidate.
- Revisit process-local worker supervision when concurrency, failure recovery, multi-host deployment, or regional buffering requires a durable scheduler/event bus.
- Revisit PostgreSQL-only search when measured event volume or query latency requires a separate search system.
