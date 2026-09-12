# Recommended Approach

## Outcome first

Build one reliable end-to-end path before dividing the system into many services:

```text
registered camera node
  -> resilient RTSP/TCP capture
  -> ANPR observation with source PTS
  -> normalised plate
  -> watchlist match
  -> deduplicated alert
  -> stored event
  -> GIS marker and vehicle trajectory
```

This path directly demonstrates the core of what SIH26127 asks for and gives every later feature a real integration point.

## Recommended architecture choice

Build the camera registry and GIS foundation first, then integrate directly with camera sources. Put every source behind a connector interface so the code can later evolve toward federation middleware without rewriting analytics or UI components.

The registry comes first for a concrete reason, not tidiness: trajectory reconstruction plots stops on a map and traffic analytics aggregates per node. Both are impossible without authoritative camera geometry.

Why this fits a small hackathon team:

- direct-integration is the shortest path to the organiser's direct RTSP/HTTP sandbox endpoints.
- registry/GIS creates the official registry/GIS deliverables and the location data required for route reconstruction.
- An adapter boundary preserves the vendor-neutral story without requiring a full federation product during Phase 1.
- Metadata-first upstream flow is what makes the city-wide scale narrative credible: analyse at the zone edge and centralise only observations, alerts, health, and selectively requested evidence. A plate read is a few hundred bytes; a video stream is megabits per second.
- A full central VMS, a city-wide recording system, and production database integrations are too broad to build safely in the available window; they belong in the HLD and roadmap unless the team already owns mature components.

This direction is accepted in [ADR 0001](decisions/0001-integration-shape.md). The concrete implementation stack is accepted in [ADR 0002](decisions/0002-implementation-stack.md).

## Delivery sequence

### 1. Freeze contracts before parallel work

Agree on:

- camera registry schema;
- catalogue connector contract;
- observation, watchlist, alert, and journey schemas;
- event/source-time rules;
- API endpoints;
- the local development stack and one startup command; and
- who owns each work lane and who reviews it.

### 2. Build the vertical slice

Start with one synthetic/protocol-compatible feed if official access is not ready, then switch to an official feed as early as possible. Do not wait for the dashboard to test ingestion and matching.

Minimum evidence:

- camera comes from a catalogue response, not a hard-coded ID;
- capture uses RTSP/TCP and survives a restart;
- observation retains source PTS and UTC event time;
- plate normalisation and confidence are visible;
- a synthetic watchlist entry produces exactly one deduplicated alert; and
- a simple map/table displays the camera and observation.

### 3. Split into three work lanes

| Lane | Primary scope | Required integration contract |
|---|---|---|
| A - Media and AI | catalogue client, capture, codec handling, ANPR, observation publishing, resilience tests | Camera and Observation schemas |
| B - Platform and data | registry, PostGIS, watchlists, matching, alerts, journey query, RBAC/audit | API and event contracts |
| C - Operator experience and submission | GIS/dashboard, camera health, alert workflow, journey view, demo harness, documentation/evidence | API contract and checkpoint scripts |

Each lane has one primary owner and a different reviewer. Pair on the vertical slice and cross-lane contract changes.

### 4. Add reliability before bonus analytics

Mandatory reliability work comes before additional models:

- variable frame intervals and PTS timing;
- feed restart and exponential backoff;
- mixed H.264/H.265 and resolution handling;
- scene discontinuity recovery;
- catalogue refresh and health state;
- alert idempotency and deduplication; and
- degraded/offline UI states.

### 5. Build the evaluation story alongside the product

For every checkpoint, retain:

- a deterministic runbook;
- machine-readable results;
- one short screen recording or screenshot set where useful;
- timing/resource measurements;
- known limitations; and
- requirement IDs satisfied.

Do not postpone the HLD, scale calculations, cost model, or output-report format until the last day.

## Scope discipline

### Must build

- registry/GIS registry/GIS essentials;
- catalogue-driven ingestion;
- resilient live-simulated feed handling;
- ANPR observation path;
- representative watchlist and match;
- automatic alert;
- timestamped multi-camera vehicle journey;
- operator-facing evidence; and
- repeatable own-feed and government-feed demos.

### Must document, may be partially implemented in Phase 1

- real VAHAN/SARTHI/eGujCop/AFIS/NAFIS adapters;
- private CCTV onboarding governance;
- full regional/edge topology;
- city-wide storage and disaster recovery;
- complete department-specific connector estate; and
- production facial recognition or biometric matching.

### Defer until mandatory flow is stable

- extra analytics;
- complex microservice decomposition;
- a bespoke video player when HLS/WebRTC already works;
- full central recording of all streams;
- Kubernetes for the local demo; and
- visual polish that does not improve evaluation evidence.

## Daily operating rhythm

1. Ten-minute sync: checkpoint, blockers, contract changes, demo health.
2. Pull `main`; create or continue one task branch.
3. Merge small vertical increments throughout the day.
4. Run the shared demo after every integration merge.
5. End-of-day evidence review and repository handoff update.
6. Keep a frozen fallback tag once a checkpoint is stable.

## Definition of a winning submission

The platform works under the organiser's feed conditions; the vehicle journey and alerts are understandable and auditable; the architecture is feasible rather than theatrical; the scale story is numerically credible; and every claim in the presentation points to reproducible evidence.
