# High-Level Design — SIH26127

**City-Wide AI Engine for Multi-Camera ANPR Trajectory Tracking and Urban Traffic Analytics**
Bharat Electronics Limited · Smart India Hackathon 2026

This is the technical proposal for `SIH-SUB-003`. It describes what the platform is, how the four expected components fit together, and — explicitly — what it does not do. [architecture.md](architecture.md) carries the component-by-component responsibilities; this document is the level above it.

---

## 1. The problem being solved

A city already owns the cameras. What it does not own is the **linkage between them**.

```mermaid
flowchart LR
    subgraph Today["Today — isolated silos"]
        direction TB
        C1[Camera 1] --> P1[Plate read] --> S1[(Local log)]
        C2[Camera 2] --> P2[Plate read] --> S2[(Local log)]
        C3[Camera 3] --> P3[Plate read] --> S3[(Local log)]
    end
    Today -.->|no linkage across space or time| Gap[["cannot follow a vehicle<br/>cannot see city-wide trends"]]
```

Each feed produces plate reads that die in their own silo. A vehicle crossing three sectors produces three unrelated records. The platform's job is to turn those into **one trajectory** and, in aggregate, into **city-wide movement intelligence**.

```mermaid
flowchart LR
    subgraph Target["This platform"]
        direction TB
        CAM[Distributed ANPR cameras] --> OCR[1 · OCR engine]
        OCR --> OBS[(Observation store<br/>plate + camera + time + geo)]
        OBS --> TRAJ[2 · Trajectory engine]
        OBS --> ANLY[3 · Traffic analytics]
        OBS --> ALERT[4 · Alert system]
        TRAJ --> GIS[GIS-integrated console]
        ANLY --> GIS
        ALERT --> GIS
    end
```

The **observation store is the hinge**. Every one of the four components reads from the same normalised record, which is why they can never disagree about what a camera saw.

---

## 2. System context

```mermaid
flowchart TB
    Operator([Traffic / enforcement operator])
    Admin([Super admin])

    subgraph Edge["Camera estate"]
        RealCam[City ANPR cameras<br/>RTSP · HLS]
        Recorded[Recorded government feeds<br/>replayed via MediaMTX]
    end

    subgraph Platform["Sentinel platform"]
        Conn[Source connectors]
        Workers[Analytics workers<br/>GPU]
        API[FastAPI control plane]
        DB[(PostgreSQL + PostGIS)]
        Console[React operator console]
    end

    RealCam --> Conn
    Recorded --> Conn
    Conn --> Workers
    Workers -->|observations over HTTP<br/>service token| API
    API <--> DB
    Operator --> Console
    Admin --> Console
    Console -->|session cookie| API
    API -->|authenticated relay| Console
```

Two properties matter here:

- **Workers never touch the database.** They post observations to the API over HTTP with a service token separate from human sessions. That keeps the schema private to the control plane and lets workers run on other hosts later without a database credential.
- **The browser never receives a raw camera endpoint.** It gets capability flags; media arrives through an authenticated, department-checked relay.

---

## 3. Data flow — a single plate, end to end

```mermaid
sequenceDiagram
    participant Cam as Camera
    participant W as ANPR worker
    participant API as Control plane
    participant DB as PostGIS
    participant UI as Console

    Cam->>W: RTSP / HLS frames
    W->>W: YOLO11 detect + ByteTrack track
    W->>W: fast-alpr OCR per vehicle crop
    W->>W: vote across frames of one track
    Note over W: only a CONFIRMED plate is published<br/>tentative reads are never written
    W->>API: POST /api/sightings (plate, conf, PTS-anchored time, crop)
    API->>DB: INSERT sighting
    API->>DB: normalise + match against watchlist
    alt plate is blacklisted AND confidence ≥ threshold
        API->>DB: INSERT alert (deduplicated, 15-min window)
        API-->>UI: alert appears in queue
    else sub-threshold
        Note over API: sighting still recorded —<br/>observation data stays complete
    end
    UI->>API: GET /vehicles/{plate}/journey
    API->>DB: ordered sightings + camera geometry
    API-->>UI: chronological stops → route on map
```

The **confirm-then-publish** rule is deliberate. Publishing every intermediate OCR output would let unvalidated guesses masquerade as settled fact in the registry, and would corrupt both the trajectory and the traffic counts.

---

## 4. The four expected components

### 4.1 Component 1 — High-Precision OCR Module

```mermaid
flowchart LR
    F[Frame] --> D[YOLO11<br/>vehicle detection]
    D --> T[ByteTrack<br/>track association]
    T --> G{crop ≥ min width?}
    G -- no --> Skip[skip: too small to read]
    G -- yes --> P[fast-alpr<br/>plate detect + OCR]
    P --> V[PlateVote<br/>consensus across frames]
    V --> C{votes ≥ 2?}
    C -- no --> Tent[tentative — not published]
    C -- yes --> Pub[confirmed → sighting]
```

Running on CUDA via ONNX Runtime. A per-vehicle **pre-gate** skips crops too small to read, so GPU time is spent on plates that can actually resolve.

**Status:** works; reads real Indian plates at 0.88–1.00 confidence. The problem statement's **>90 % accuracy target is not yet measured** — that requires ground-truth labelled footage covering lighting, weather, angle, blur, and damaged plates. Until that exists, no accuracy figure is claimed.

### 4.2 Component 2 — Trajectory Reconstruction Engine

```mermaid
flowchart LR
    Q[Query: plate] --> N[Normalise plate]
    N --> S[(Sightings<br/>ordered by source time)]
    S --> E[Enrich with camera geometry]
    E --> L[Consecutive-pair legs]
    L --> B{both cameras<br/>exact-geocoded?}
    B -- yes --> Dir[bearing + corridor lower-bound speed]
    B -- no --> Sup[suppressed, counted in exclusions]
    Dir --> Out[Timeline + numbered route + export]
    Sup --> Out
```

Ordered by **source-anchored time**, never frame-arrival time. A stream that cannot be time-anchored reports `null` and the backend rejects the sighting rather than inventing a timestamp — a fabricated time would silently corrupt every trajectory built on it.

### 4.3 Component 3 — City Traffic Analytics Dashboard

```mermaid
flowchart TB
    S[(Sightings)] --> Trip[Per-plate trip reconstruction]
    AC[(analytics_counts<br/>vehicles tracked)] --> Yield[Read yield]
    S --> Yield
    Trip --> Corr[Corridor transit]
    Trip --> OD[First/last observed node pairs]
    Trip --> Anom[Dwell · loop · implausible transit]
    S --> Dens[Time-bucketed density per camera]
    Dens --> Cong[Latest hour vs own recent median]
    Corr --> Dash[GIS dashboard]
    OD --> Dash
    Dens --> Dash
    Cong --> Dash
    Yield --> Dash
    Anom --> Dash
```

**Read yield is not decoration.** A sighting exists only when a plate was *confirmed*, so raw counts are a floor on real traffic, not a measurement of it. Publishing reads-over-vehicles-tracked alongside every density figure keeps a plate-conditioned undercount from being read as traffic volume.

**Status: unmerged.** Built on `new-implementations`, unit-tested 15/15 without a database, never run against Postgres. The heatmap layer is not built.

### 4.4 Component 4 — Alert System

```mermaid
flowchart LR
    Obs[Observation] --> M{on watchlist?}
    M -- no --> End[record only]
    M -- yes --> Conf{confidence ≥<br/>ALERT_MIN_CONFIDENCE}
    Conf -- no --> End
    Conf -- yes --> Dedup{open alert for this<br/>plate+camera in 15 min?}
    Dedup -- yes --> Sup[suppress: no storm]
    Dedup -- no --> A[Raise alert]
    A --> Q[Operator queue]
    Q --> Ack[acknowledge / resolve → audit]

    Route[Route anomalies<br/>dwell · loop · implausible] -.->|not yet wired| Q
```

Blacklist alerting is verified end to end. **Route-anomaly alerting is the outstanding gap** — the anomalies are derived on the analytics branch but surface only through traffic endpoints, not the alert queue.

---

## 5. Deployment

### Current — single host, hosted database

```mermaid
flowchart TB
    subgraph Host["One workstation (GPU)"]
        UV[Uvicorn · FastAPI]
        SUP[Worker supervisor]
        W1[ANPR worker]
        W2[Person / suspicious worker]
        MTX[MediaMTX relay]
        FF[FFmpeg publishers]
    end
    Neon[(Neon PostgreSQL 18 + PostGIS<br/>ap-southeast-1, TLS)]
    Browser([Browser])

    Browser --> UV
    UV --> Neon
    UV --> SUP
    SUP --> W1
    SUP --> W2
    FF --> MTX
    MTX --> W1
    W1 -->|HTTP + worker token| UV
```

Only the database is remote. **Video never leaves the host** — inference runs against the local GPU, and only derived metadata is persisted.

### Proposed — city scale

```mermaid
flowchart LR
    subgraph Z1["Zone / sector edge"]
        C1[Connectors] --> I1[Inference nodes] --> B1[Local buffer]
    end
    subgraph Z2["Zone / sector edge"]
        C2[Connectors] --> I2[Inference nodes] --> B2[Local buffer]
    end
    B1 --> Bus[[Durable event bus]]
    B2 --> Bus
    Bus --> Core[Central observation · trajectory · analytics · alert services]
    Core --> Store[(PostGIS + search + tiered evidence)]
    Core --> CC[Command centre consoles]
```

Inference moves to the edge; only metadata crosses the network. This is the **metadata-first** property that makes city scale plausible: a plate read is a few hundred bytes, a video stream is megabits per second.

Quantifying this — streams per GPU, bitrate distribution, retention tiers, bus throughput — is `SIH-PLAT-010` and is **not yet written**.

---

## 6. Demo and government modes

A city-wide platform cannot be demonstrated without a city. Two toggles solve this **without special-casing any downstream logic**:

```mermaid
flowchart LR
    subgraph Off["Government mode OFF"]
        R1[Camera row] -->|real gov endpoint| Live[Live city feed]
    end
    subgraph On["Government mode ON"]
        R2[Same camera row] -->|relay URL| MTX[MediaMTX] --> Clip[Recorded footage]
    end
    Off -->|toggle| On
    On -->|toggle: originals restored| Off
```

The toggle swaps **two columns** on rows that already exist. ANPR, trajectory, analytics, and alerting cannot tell the difference, because as far as they are concerned it is simply that camera's stream URL. Onboarding, scaling, and registry behaviour are untouched.

Because the mode's state lives in a file while the URLs live in the database, the two can drift. The status endpoint reports `degraded` when they do, and re-pressing the toggle repairs it.

---

## 7. What this design deliberately does not do

Stating these is part of the design, not an apology for it:

| Not done | Why |
|---|---|
| Per-camera speed or heading | No camera is calibrated — no homography, pixels-per-metre, mounting height, or FOV, and some are PTZ. Corridor speed ships as a straight-line **lower bound**, never a speeding finding |
| Predictive congestion forecasting | With a plate-conditioned undercount and limited history it would be unfalsifiable. A labelled baseline comparison ships instead |
| Face recognition | Out of scope and legally gated. Person search returns ranked appearance candidates, never an asserted identity |
| Central video recording | Metadata-first by design; only bounded evidence crops are retained, on a short expiry |
| Claiming >90 % OCR accuracy | Unmeasured. It stays unclaimed until ground truth exists |

---

## 8. Technology

| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3.11 · FastAPI · SQLAlchemy 2 · Alembic | Async I/O suits stream-adjacent work; one language across API and CV workers |
| Database | PostgreSQL + PostGIS | Trajectory and analytics are inherently spatial; avoids a separate spatial service |
| Detection / tracking | YOLO11 + ByteTrack | Strong accuracy-per-FLOP; ByteTrack keeps identity across frames so votes can accumulate |
| OCR | fast-alpr + ONNX Runtime (CUDA) | Purpose-built for plates; ONNX gives GPU execution without a second training stack |
| Media | FFmpeg · MediaMTX | Real transport semantics (RTSP/HLS/WHEP), not seekable files |
| Frontend | React 19 · Vite 8 · React Leaflet | GIS-integrated console is a stated requirement |

Pinned versions: [ADR 0002](decisions/0002-implementation-stack.md), `backend/requirements.txt`, `frontend-v3/package-lock.json`.

---

## 9. Traceability

Every claim above maps to a requirement ID in [requirements.md](requirements.md). Component sections map to `SIH-OCR-*`, `SIH-TRAJ-*`, `SIH-ANLY-*`, `SIH-ALERT-*`; platform and deployment map to `SIH-PLAT-*`; section 5's scale gap is `SIH-PLAT-010`; section 7's limitations are recorded as explicit `In progress`/`Not started` states rather than omitted.
