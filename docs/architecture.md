# Architecture

Status: Accepted for Phase 1 by ADR 0001 and ADR 0002

This architecture is optimised for a three-person Phase 1 team while preserving a credible evolution path to statewide deployment. It combines the mandatory Model 1 registry/GIS foundation with Model 2-style direct feed integration behind adapter contracts.

## Principles

- Build a modular monolith plus independent media workers before creating many network services.
- Separate the control plane, media/analytics plane, and operator experience.
- Keep source video close to the source where possible; centralise metadata, alerts, health, and selectively retained evidence.
- Make every external integration replaceable behind a documented adapter.
- Preserve source PTS and provenance through every derived event.
- Design for degraded links, restarts, mixed codecs, and partial availability.
- Use synthetic data by default and least-privilege access for official resources.

## System context

```mermaid
flowchart LR
    Dept[Department CCTV / VMS] -->|RTSP / ONVIF / SDK / API| Conn[Source connectors]
    Cat[Sentinel catalogue] --> Conn
    Private[Authorised private CCTV] -. optional .-> Conn
    Conn --> Media[Media workers]
    Media --> AI[ANPR and analytics]
    AI --> Events[Observation and event pipeline]
    Watch[Representative watchlists] --> Match[Matching service]
    Events --> Match
    Match --> Alerts[Alerts and workflow]
    Registry[Camera registry + PostGIS] --> GIS[GIS and operator dashboard]
    Events --> Journey[Vehicle journey service]
    Registry --> Journey
    Journey --> GIS
    Alerts --> GIS
    Govt[Authorised government databases] -. production adapters .-> Watch
```

## Logical components

### 1. Camera registry and GIS control plane

Responsibilities:

- mandatory Model 1 metadata;
- bulk/manual/API onboarding;
- camera ownership, department, location, type, storage, and connectivity;
- current health and maintenance status;
- GIS layers, search, filters, exports, and gap reports;
- access control and audit.

Accepted Phase 1 implementation: PostgreSQL with PostGIS, a single FastAPI backend, and React Leaflet in the active frontend. The listed responsibilities include mandatory gaps that are not all implemented yet; current evidence is tracked in `docs/requirements.md`.

### 2. Catalogue and source connectors

The connector boundary converts a source-specific catalogue/stream description into a canonical CameraSource. The first connector targets the Sentinel `/api/ingest` catalogue. Later connectors can target ONVIF, vendor SDKs, or federation middleware.

Connector requirements:

- read-only discovery and health;
- no hard-coded camera IDs;
- current catalogue-provided RTSP, WHEP, and HLS endpoint references;
- redacted diagnostics;
- explicit supported protocols and credentials reference;
- bounded connect/disconnect lifecycle; and
- normalised errors without losing source detail.

### 3. Media workers

Responsibilities:

- RTSP/TCP capture for inference;
- optional HLS/WebRTC paths for viewing;
- H.264/H.265 decode and resolution normalisation;
- PTS extraction and discontinuity detection;
- reconnect/backoff and load pacing;
- frame sampling and backpressure; and
- observation publication.

Transport invariants:

- The feed is live: one second of video takes one second to arrive.
- PTS, not frame-arrival wall time or reported FPS, drives motion and dwell-time calculations.
- Initial buffered GOP replay may arrive faster than real time and must not produce impossible velocities.
- Seeking, complete-file download, byte-range access to a recording, and running ahead are unavailable.
- PTS is monotonic within a stream epoch. Reconnects and loop discontinuities create an explicit new epoch when continuing prior tracker timing would be unsafe.
- Each connected client receives its own stream copy, so capture ownership, concurrency, and bandwidth must be bounded.

Workers must be independently restartable. Phase 1 runs them as subprocesses under the backend's process-local supervisor; no durable job queue is implemented. Prefer one owned capture per actively processed camera with internal fan-out to analytics where practical, rather than opening duplicate gateway connections. Statewide design partitions workers by region/source and scales horizontally.

### 4. Analytics

The mandatory path is ANPR. The output is an Observation, not an alert. This separation allows models to be replaced and reprocessed without changing watchlist logic.

An observation includes:

- immutable ID;
- camera and department;
- source PTS and UTC event time;
- stream epoch/discontinuity identity;
- analytic/model/version;
- raw and normalised result;
- confidence and quality flags;
- bounding box/evidence reference when permitted; and
- provenance and processing timestamps.

Additional analytics must publish the same envelope and remain optional.

### 5. Watchlist matching and alerts

Matching normalises plates, applies configured confidence/policy thresholds, and emits a MatchDecision. Alert creation is idempotent and deduplicated over a defined camera/entity/time window.

Keep these distinct:

```text
Observation -> MatchDecision -> Alert -> AlertAction/AuditEvent
```

This preserves explainability and prevents a UI acknowledgement from altering the original analytic result.

### 6. Vehicle journey

The first implementation reconstructs a journey from plate observations ordered by source time and enriched with registry coordinates. It should expose both map and tabular views.

Quality controls:

- plate normalisation and aliases;
- confidence threshold and low-confidence flagging;
- per-camera/time-window deduplication;
- impossible-time/distance warning;
- stable UTC ordering with source PTS retained; and
- evidence link and model version per point.

Advanced cross-camera re-identification is bonus work after the auditable plate-based journey is stable.

### 7. Operator dashboard

Minimum views:

- camera registry and GIS layers;
- camera health and active preview;
- observations and searchable events;
- live alert queue with acknowledge/resolve workflow;
- vehicle search and route history;
- operational health; and
- export/report action.

Every screen must show degraded/offline/unknown states rather than silently omitting failed data.

## Implemented Phase 1 deployment

```mermaid
flowchart TB
    Browser[Operator browser]
    API[Backend API / modular monolith]
    DB[(PostgreSQL + PostGIS)]
    Supervisor[Process-local worker supervisor]
    Worker1[Media + ANPR worker]
    WorkerN[Additional analytics worker]
    Sources[Sentinel camera grid]

    Browser --> API
    API --> DB
    API --> Supervisor
    Supervisor --> Worker1
    Supervisor --> WorkerN
    Worker1 --> Sources
    WorkerN --> Sources
    Worker1 -->|observations over HTTP| API
    WorkerN -->|counts/telemetry| API
```

Accepted stack; exact package sources are recorded in ADR 0002:

- Python/FastAPI backend and Python media workers;
- OpenCV and FFmpeg/ffprobe for capture and probing;
- YOLO11, ByteTrack, fast-alpr, and ONNX Runtime for the current ANPR baseline;
- PostgreSQL/PostGIS;
- React/Vite with React Leaflet (two frontend variants: `frontend-v2` for the baseline, `frontend-v3` for the Buildathon-reskinned operator console with GSAP animations); and
- process-local worker supervision for the current bounded demo.

Redis/Kafka, Kubernetes, Docker Compose, and S3-compatible evidence storage are not implemented Phase 1 dependencies. They remain possible scale/deployment choices only after measurements and retention requirements justify them.

## Statewide evolution

```mermaid
flowchart LR
    subgraph RegionA[Regional / department edge]
      CA[Connectors] --> WA[Inference workers]
      WA --> BA[Local buffer]
    end
    subgraph RegionB[Regional / department edge]
      CB[Connectors] --> WB[Inference workers]
      WB --> BB[Local buffer]
    end
    BA --> Bus[Durable event bus]
    BB --> Bus
    Bus --> Central[Central metadata, alert, journey, and registry services]
    Central --> Store[(PostGIS / search / tiered evidence)]
    Central --> Command[Authorised command centres]
```

Scale assumptions must be quantified in the HLD:

- active analytics percentage versus registered cameras;
- average/peak bitrate and resolution distributions;
- frames sampled per analytic;
- streams per CPU/GPU worker;
- metadata and evidence bytes per observation;
- hot/warm/cold retention;
- regional outage buffer duration;
- replication and recovery objectives; and
- operator/search concurrency.

## Security and privacy boundaries

- The Phase 1 identity and access decision is [ADR 0003](decisions/0003-department-rbac.md): `super_admin`, `department_admin`, and `department_user` roles plus per-department `viewer`/`operator` grants.
- The API, not the React UI, enforces the boundary. Camera/media access, observations, alerts, analytics, journeys, reports, and survey frames are filtered or rejected before data is returned.
- Human users authenticate with an opaque HttpOnly session cookie; only a token digest is stored. Worker ingestion uses a separate service token.
- The home department is granted automatically. Only the super admin may add cross-department access; department admins govern employees in their own home department.
- Raw camera endpoints remain in the backend/worker trust zone. Browser clients receive a capability flag and use the authenticated HLS relay.
- Credentials are referenced through environment/secret identifiers, never stored in registry rows or Git.
- TLS protects service and external connections where supported.
- Camera/media networks are isolated from public/operator networks.
- Department and purpose constrain access to streams, observations, watchlists, and alerts.
- Implemented security and state-changing operations append audit events; successful authenticated metadata reads and denied authorisation are audited too. A database trigger rejects application-role audit-row updates/deletes, except the foreign-key actor-reference cleanup on account deletion. A super-admin-only canonical NDJSON archive provides a SHA-256-verifiable external hand-off, but storage in an approved immutable destination remains an explicit `GOV-NFR-003` gap, and a database superuser can still alter database controls.
- Development uses synthetic data or explicitly approved representative material only.
- Evidence retention is selective, configurable, encrypted, and shorter than source video retention unless authorised.
- Biometric or person-identification features require explicit legal/organiser approval and a documented privacy assessment.

## Failure behaviour

| Failure | Expected behaviour |
|---|---|
| Catalogue unavailable | Use last known non-secret metadata for display, stop new discovery, surface stale status. |
| Feed unavailable | Bounded reconnect, health degradation, no busy loop. |
| Decoder join warning | Continue until keyframe/deadline; record diagnostic. |
| Scene discontinuity | Reset unsafe tracker state and retain a discontinuity event. |
| Duplicate capture demand | Reuse the owned active capture where practical or enforce a hard client/concurrency budget. |
| Inference overloaded | Apply sampling/backpressure; never allow unbounded memory growth. |
| Database unavailable | Buffer within a bounded policy or fail visibly; never silently discard alerts. |
| Duplicate observation | Preserve observation as policy allows; deduplicate alert creation idempotently. |
| Dashboard unavailable | Processing continues; operators see service health after recovery. |

## Deliberate non-goals for the first vertical slice

- replacing departmental VMS products;
- recording every stream centrally;
- implementing live production government database integrations;
- production-grade facial recognition;
- deploying Kubernetes locally; and
- solving every analytics category before ANPR and journey evidence work.
