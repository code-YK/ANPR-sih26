# Requirements and Traceability Ledger

This file translates **SIH26127** (Bharat Electronics Limited — *City-Wide AI Engine for Multi-Camera ANPR Trajectory Tracking and Urban Traffic Analytics*) into testable implementation requirements. It is the execution checklist and the evidence index for the submission.

Sources are coded in [source-register.md](source-register.md). The status column must describe **merged reality on `main`**, not intent and not unmerged branches.

## How this ledger is organised

The problem statement names three core functionalities and four expected components. This ledger uses the **four expected components** as its top-level structure, because those are what the solution is judged against, plus the platform-level requirements needed to make them real.

| Prefix | Area | Maps to |
|---|---|---|
| `SIH-OCR` | High-Precision OCR / ANPR engine | Expected component 1, core functionality 1 |
| `SIH-TRAJ` | Trajectory Reconstruction Engine | Expected component 2, core functionality 2 |
| `SIH-ANLY` | City Traffic Analytics Dashboard | Expected component 3, core functionality 3 |
| `SIH-ALERT` | Alert System | Expected component 4 |
| `SIH-PLAT` | Platform foundations the four components stand on | Implied by "centralised", "city-wide", "scalable, enterprise-grade" |
| `SIH-NFR` | Security, privacy, reliability, operability | Implied by "enterprise-grade" |
| `SIH-SUB` | Submission deliverables | Idea submission, 2026-09-30 |

> **Terminology note.** Earlier revisions of this repository used a `Model 1 / Model 2 / Model 3 / Model 4` vocabulary inherited from a different programme. SIH26127 has no such concept and those terms have been removed. Where that earlier work is still the evidence for a requirement, it is described by what it *is* — camera registry, direct feed integration — not by a model number.

## Status vocabulary

- `Not started` — no merged implementation or evidence.
- `In progress` — implementation exists but acceptance evidence is incomplete.
- `Blocked` — cannot proceed without an external input or unresolved decision.
- `Ready for review` — acceptance evidence exists and awaits teammate review.
- `Done` — reviewed evidence satisfies the stated acceptance check.
- `Unmerged` — implemented on a branch, not on `main`; does not count as delivered.
- `N/A` — deliberately excluded, with an accepted ADR giving the justification.

## Priority vocabulary

- `Mandatory` — stated or directly implied by the problem statement.
- `Selected` — required by the team's accepted architecture, not by the organiser.
- `Bonus` — useful only after mandatory requirements work.
- `Administrative` — submission operations and deadlines.

---

## A. Expected component 1 — High-Precision OCR Module

> *"a deep-learning model exceeding 90% recognition accuracy for license plates in multi-lane traffic streams"*, robust to *"varying lighting, poor weather, angled shots, motion blur, and dirty or damaged license plates"*.

| ID | Priority | Requirement | Acceptance check / evidence | Status |
|---|---|---|---|---|
| `SIH-OCR-001` | Mandatory | Detect and read number plates from live multi-camera streams with a deep-learning OCR model. | Worker reads plates from a live stream and publishes timestamped observations. | **Ready for review** — `multi-object-tracking/observation_worker.py` (YOLO11 detection + ByteTrack tracking + fast-alpr OCR) publishes to `POST /api/sightings`. Verified 2026-09-12 against a relayed government feed: 13 distinct plates, per-read confidence 0.881–1.000, correct Indian formats, vehicle type classified. |
| `SIH-OCR-002` | Mandatory | Exceed 90 % recognition accuracy across diverse real-world conditions. | Accuracy measured against a **ground-truth labelled** set covering lighting, weather, angle, motion blur, and damaged/dirty plates; precision/recall and error taxonomy published. | **Not started** — this is the single largest open gap. No ground-truth labelled footage exists in this repository, so no accuracy figure can honestly be claimed. Needs a labelled evaluation set before any >90 % statement is made. |
| `SIH-OCR-003` | Mandatory | Operate on multi-lane traffic streams, not single-vehicle stills. | Multiple concurrent vehicles tracked and read in one frame without cross-assignment. | **Ready for review** — per-track plate voting (`plates.py` `PlateVote`) assigns reads to tracked vehicles; a 1280×720 multi-lane clip produced 158 distinct vehicle tracks in 74 s. |
| `SIH-OCR-004` | Mandatory | Only publish a plate once the read is settled, not every intermediate OCR output. | Confirmed/tentative split is enforced before a sighting is written. | **Ready for review** — a sighting is written only on a **confirmed** vote (≥3 independent frames agreeing on the plate's length and on every character, over reads valid exactly as read), never on a tentative read. This deliberately makes every count a floor on real traffic rather than an inflated one. |
| `SIH-OCR-005` | Mandatory | Run inference on GPU at a rate that keeps up with live streams. | Measured FPS and dropped-frame counts on the target hardware. | **In progress** — verified CUDA end to end on an RTX 5060 (sm_120, torch 2.11.0+cu128); ANPR ONNX runs on `CUDAExecutionProvider`, ~22 FPS sustained on one 2558×1258 stream. A fix on 2026-09-12 removed a silent CPU fallback that had been costing ~9× (`plates.py` device-convention bug). Per-GPU stream capacity is not yet measured. |
| `SIH-OCR-006` | Selected | Retain a bounded evidence crop per confirmed sighting for operator review. | Evidence image is retrievable for an authorised operator and expires on a configured schedule. | **Ready for review** — `evidence_dir` + `evidence_retention_hours` (default 72 h); the sighting row keeps its `evidence_path` permanently while the file itself expires. |

---

## B. Expected component 2 — Trajectory Reconstruction Engine

> *"a query-based tracking interface that plots a vehicle's historical path chronologically across the city map with accurate timestamps and camera locations"*.

| ID | Priority | Requirement | Acceptance check / evidence | Status |
|---|---|---|---|---|
| `SIH-TRAJ-001` | Mandatory | Given any plate at query time, return its complete observed trajectory across the camera network. | Operator enters a plate with no redeployment; ordered stops are returned across multiple cameras. | **Ready for review** — `GET /api/vehicles/{plate}/journey`, ordered by `seen_at`, plus the Journey view in the operator console. Runtime plate entry, no redeployment. |
| `SIH-TRAJ-002` | Mandatory | Each stop carries camera identity, geographic location, accurate timestamp, and confidence. | Journey rows reconcile exactly with stored sightings across every export format. | **Ready for review** — each stop carries camera id, name, coordinates, source-anchored UTC time, confidence, and an authorised evidence URL. JSON/CSV/HTML/PDF exports are generated from one builder so they cannot disagree. |
| `SIH-TRAJ-003` | Mandatory | Plot the path chronologically on a GIS map. | Numbered route is drawn on a map in camera-visit order. | **Ready for review** — `client/src/views/Journey/` renders a numbered route map plus a chronological timeline, backed by PostGIS coordinates. |
| `SIH-TRAJ-004` | Mandatory | Report direction of travel along the reconstructed route. | Onward direction between consecutive observations is derived and displayed. | **Unmerged** — implemented on `new-implementations` as a chord bearing between consecutive camera points, suppressed unless both endpoints are `exact`-geocoded. Not on `main`. |
| `SIH-TRAJ-005` | Mandatory | Timestamps must be anchored to the source stream, never to frame-arrival wall time. | Timing is derived from stream PTS / program-date-time; a stream that cannot be anchored does not silently invent a time. | **Ready for review** — `seen_at` comes from `camera_feeds.ProgramDateTimeAnchor`. An unanchored stream reports `null` and the backend rejects the sighting rather than fabricating a timestamp. |
| `SIH-TRAJ-006` | Mandatory | Deduplicate repeated reads of the same vehicle at the same camera. | Repeat observations within a window do not create spurious trajectory stops. | **In progress** — sightings are written once per track. Same-camera repeats across a stream `epoch_id` boundary are treated as replay/reconnect rather than a genuine revisit. An explicit ambiguous-match policy remains open. |
| `SIH-TRAJ-007` | Selected | Flag physically implausible transits rather than presenting them as fact. | A leg implying an impossible speed is surfaced as a data fault, not a movement finding. | **Unmerged** — implemented on `new-implementations`: an over-threshold leg is reported as a **data fault** (one plate string misread across two vehicles, or a clock/anchor fault), never as a speeding finding. |

---

## C. Expected component 3 — City Traffic Analytics Dashboard

> *"a centralized, GIS-integrated web platform displaying heatmaps, average vehicle speeds, route densities, and traffic flow trends across all camera nodes"*; measuring *"traffic density, identifying origin-destination patterns, detecting congestion bottlenecks, and providing real-time heatmaps"*.

| ID | Priority | Requirement | Acceptance check / evidence | Status |
|---|---|---|---|---|
| `SIH-ANLY-001` | Mandatory | Measure traffic density per camera over time. | Time-bucketed counts per camera, department-scoped, bounded window. | **Unmerged** — `GET /traffic/flow` on `new-implementations`. |
| `SIH-ANLY-002` | Mandatory | Identify origin–destination patterns across the network. | First/last observed node pairs per trip, aggregated. | **Unmerged** — `GET /traffic/movement`. Named `first_camera_id`/`last_camera_id` deliberately: they are the ends of the *observed* portion of a trip, not a claim about true origin or destination. |
| `SIH-ANLY-003` | Mandatory | Detect congestion bottlenecks. | Each camera's recent behaviour compared against its own baseline. | **Unmerged** — `GET /traffic/congestion` compares the latest hour against that camera's own recent median. Labelled a baseline comparison, not a forecast. |
| `SIH-ANLY-004` | Mandatory | Provide real-time heatmaps of city traffic movement on a GIS-integrated dashboard. | Map-based density visualisation across all camera nodes. | **Not started** — the underlying per-camera density series exists on `new-implementations`, and the console already renders a PostGIS-backed map, but a heatmap layer joining the two is not built. |
| `SIH-ANLY-005` | Mandatory | Report route densities and traffic-flow trends across all camera nodes. | Corridor-level aggregates with stated exclusions. | **Unmerged** — corridor transit legs and trend series on `new-implementations`, with a four-format export. |
| `SIH-ANLY-006` | Mandatory | Report average vehicle speeds. | Speed figures are derivable and their basis is stated. | **In progress, with a stated limitation.** No camera in the registry carries calibration — no homography, pixels-per-metre, mounting height, or field of view — and some are PTZ. **Speed *at* a camera is therefore not derivable and is deliberately absent from the contract.** What ships instead is `min_avg_speed_kmh`: a great-circle *lower bound* between two cameras (road distance is at least the straight-line distance, so a vehicle cannot have averaged less). It is never a speeding finding. Closing this properly requires camera calibration, which is a deployment input, not a code change. |
| `SIH-ANLY-007` | Mandatory | Every published figure states its own exclusions rather than silently dropping data. | Each response and export carries the counts behind it. | **Unmerged** — suppressed legs are counted in an `exclusions` block, never dropped silently. |
| `SIH-ANLY-008` | Selected | Publish the measured plate-read yield so a plate-conditioned undercount is never mistaken for traffic volume. | Ratio of plate reads to vehicles tracked, per camera. | **Unmerged** — `GET /traffic/read-yield`, backed by `mode="vehicle"` rows in `analytics_counts`. |
| `SIH-ANLY-009` | Mandatory | Merge the analytics dashboard to `main` and verify it against a live database. | Endpoints, migration, and department-scoping exercised against a running backend. | **Not started** — the branch's own notes record that it has never run against Postgres. Its migration `202609101000` is not idempotent and will need `if_not_exists` before it can be applied to the shared database, whose indexes already exist. |

---

## D. Expected component 4 — Alert System

> *"capable of flagging blacklisted vehicles and suspicious route anomalies in real time"*.

| ID | Priority | Requirement | Acceptance check / evidence | Status |
|---|---|---|---|---|
| `SIH-ALERT-001` | Mandatory | Maintain a searchable blacklist / watchlist of vehicles of interest. | CRUD, bulk import, and filtering demonstrated with synthetic data. | **Ready for review** — `backend/app/routers/watchlist.py`: CRUD, bulk CSV import, active/plate filtering. |
| `SIH-ALERT-002` | Mandatory | Correlate every observation against the blacklist continuously and flag matches in real time. | Deterministic matching covers normalisation, confidence threshold, and no-match cases. | **Ready for review** — `POST /api/sightings` normalises and matches on write. Verified end to end 2026-09-12: two watchlisted plates observed on a live relayed feed produced two `watchlist` alerts within one clip loop. `scripts/matching_policy_test.py` covers threshold/normalisation/no-match/dedup. |
| `SIH-ALERT-003` | Mandatory | An alert carries enough context to act on. | Alert references observation, watchlist entry, camera, location, time, confidence, status, and evidence. | **Ready for review** — verified in the live run; the alert joins evidence presence for the operator. |
| `SIH-ALERT-004` | Mandatory | Apply a confidence gate so operators are not sent to chase weak OCR reads. | Sub-threshold reads are still recorded but do not raise an alert. | **Ready for review** — `ALERT_MIN_CONFIDENCE` (default 0.85). A sub-threshold sighting is **never dropped** — observation data stays complete — it simply does not raise an alert. |
| `SIH-ALERT-005` | Mandatory | Avoid alert storms; keep an auditable alert lifecycle. | Dedup window, idempotency, acknowledge/resolve, actor, and audit history tested. | **Ready for review** — 15-minute open-alert dedup plus acknowledge/resolve lifecycle with paginated actor/action/target audit history. |
| `SIH-ALERT-006` | Mandatory | Flag **suspicious route anomalies** in real time. | Dwell, looping, and implausible-transit anomalies are derived and surfaced as alerts. | **Unmerged** — the derivations exist on `new-implementations` (dwell, loop, implausible transit) but are reported through the traffic endpoints, **not yet raised as alerts** in the alert queue. Wiring them into the alert lifecycle is outstanding work even after that branch merges. |
| `SIH-ALERT-007` | Bonus | Additional analytics alerts beyond ANPR. | Each claimed analytic has measurable evidence and does not weaken mandatory ANPR performance. | **In progress** — a suspicious-activity worker raises standalone, track-deduplicated `alert_type: suspicious` alerts with no identity, watchlist, or face recognition. Detection quality and false-positive limits are not measured. |

---

## E. Platform foundations (`SIH-PLAT`)

These are not separately listed by the organiser but are required for a "centralized", "city-wide", "scalable, enterprise-grade" platform to exist at all.

| ID | Priority | Requirement | Acceptance check / evidence | Status |
|---|---|---|---|---|
| `SIH-PLAT-001` | Mandatory | Maintain a central registry of every camera node with location, ownership, type, and connectivity. | Schema, migration, validation, and API examples merged. | **Ready for review** — `backend/app/models/camera.py` + PostGIS migration + `routers/cameras.py`. 16 real government camera nodes onboarded with coordinates (`backend/fixtures/government_cameras.json`). |
| `SIH-PLAT-002` | Mandatory | Onboard cameras by manual entry, bulk import, and API — without hard-coding camera identities. | Each path demonstrated with validation errors and audit evidence. | **Ready for review** — manual creation, CSV create/update, catalogue sync, and a reproducible government-camera seed all exist; no camera ID is hard-coded in application code. |
| `SIH-PLAT-003` | Mandatory | Present all camera nodes on an interactive GIS map with filters. | Map renders cameras, health state, and filters; unplaced cameras are shown explicitly rather than hidden. | **Ready for review** — `client/src/views/Registry/MapView.jsx`, verified in-browser 2026-09-12: Leaflet tiles, department/type/ANPR/live filters, health-coloured markers, explicit unplaced list. |
| `SIH-PLAT-004` | Mandatory | Ingest many geographically distributed camera feeds concurrently. | Bounded concurrent capture with per-mode worker budgets. | **In progress** — bounded worker pools per mode (`MAX_CONCURRENT_*`), supervised subprocesses, live grid with an operator-selectable preview cap. 16 concurrent relayed feeds ran alongside ANPR on 2026-09-12. Per-GPU and per-gateway capacity are not yet measured. |
| `SIH-PLAT-005` | Mandatory | Handle heterogeneous sources, codecs, resolutions, and frame rates. | Mixed-codec and mixed-resolution capture verified. | **In progress** — H.264 and H.265, mixed resolutions, and VFR sources verified through the FFmpeg/OpenCV path. |
| `SIH-PLAT-006` | Mandatory | Reconnect automatically from feed loss without a busy loop. | Bounded exponential backoff, recovery demonstrated. | **Ready for review** — bounded backoff in the worker reader, the browser HLS hook, and the analytics supervisor. |
| `SIH-PLAT-007` | Mandatory | Provide searchable observation and movement records. | Search by plate, camera, and time range returns stable results. | **In progress** — `GET /api/sightings` (plate/camera/time range) and `GET /api/alerts` (status/camera). A single cross-department combined search remains open. |
| `SIH-PLAT-008` | Selected | Provide offline forensic search over uploaded recordings, not only live feeds. | Upload → normalise → ingest → search, department-scoped and audited. | **Ready for review** — the Investigate feature: CFR normalisation, vehicle and person ingest, exact+fuzzy plate search, and person-photo search by appearance embedding. Verified 2026-09-12 (158 vehicle tracks; 154 person tracks with 154 embeddings). Person search uses a **generic pretrained backbone, not a dedicated ReID model**, and returns a ranked candidate list, never an asserted identity. |
| `SIH-PLAT-009` | Selected | Allow the full pipeline to be demonstrated without reachable live cameras. | A toggle swaps stream sources with no change to downstream logic. | **Done** — government mode and demo mode. Government mode repoints existing camera rows at a local MediaMTX relay serving recorded footage and restores the originals on disable; ANPR, trajectory, analytics, and alerting run unmodified. Verified end to end 2026-09-12 across 16 cameras. Drift between the mode's state file and the database is detected (`degraded`) and repaired by re-pressing the toggle. |
| `SIH-PLAT-010` | Mandatory | Present a credible path from this demo scale to a city-wide deployment. | Numbers-backed capacity model separating what is built from what is proposed. | **Not started.** |
| `SIH-PLAT-011` | Bonus | Let an authorised operator drive investigation and live-analytics tasks in natural language, without weakening the API authorisation boundary. | Assistant resolves an ambiguous request by asking rather than guessing; every tool runs under the caller's `AuthContext` with department scoping intact; no irreversible operation is reachable; every invocation is audited. | **Unmerged** — branch `feat/copilot-agent`, not on `main`. 19 tools in `backend/app/agent/`, endpoint `backend/app/routers/copilot.py`, panels in `frontend-v5/src/features/copilot/` and `client/src/components/Copilot.jsx`. Design: [ADR 0005](decisions/0005-copilot-in-process-agent.md). Scope is never a model parameter and destructive operations are absent from the registry, both asserted by test. Measured 2026-09-23 on `openai/gpt-5-mini`: `scripts/copilot.py tools` 14/14 tools and 4/4 refusals against the live database; `scripts/copilot.py prompts` 9/9 behaviour cases. **Not verified:** either panel in a signed-in browser, and prompt-injection resistance against adversarial OCR text reaching the model context — the system prompt states the rule, no test proves it holds. |

---

## F. Security, privacy, reliability (`SIH-NFR`)

| ID | Priority | Requirement | Acceptance check / evidence | Status |
|---|---|---|---|---|
| `SIH-NFR-001` | Mandatory | Enforce role-based, department-aware access control with least privilege. | Authorisation tests cover every role boundary. | **Ready for review** — ADR 0003 role set (`super_admin`, `department_admin`, `department_user` plus per-department viewer/operator grants); the API, not the UI, is the enforcement point. |
| `SIH-NFR-002` | Mandatory | Maintain an auditable access and change history. | Security-relevant reads and changes record actor, time, action, target, result. | **In progress** — audit covers logins, approvals, grants, camera/watchlist changes, alert actions, authorised metadata reads, and denials. A database trigger rejects application-role `UPDATE`/`DELETE` on `audit_events`. A SHA-256-verifiable NDJSON archive can be delivered externally; provisioning a genuine WORM/object-lock destination remains open. |
| `SIH-NFR-003` | Mandatory | Never expose raw camera endpoints or credentials to the browser. | Browser receives capability flags only; media flows through an authenticated relay. | **Ready for review** — camera responses carry `stream_available` / `webrtc_preview_available` flags; video is served through department-checked HLS or WHEP relays. |
| `SIH-NFR-004` | Mandatory | Keep credentials, feed URLs, and personal data out of Git. | Secret scan passes before every tag. | **Ready for review** — `.env`, recordings, model weights, and the mediamtx binary are all git-ignored; a pre-commit secret scan over all 31 changed files passed clean on 2026-09-12. |
| `SIH-NFR-005` | Mandatory | Protect data in transit and at rest; segment media networks. | TLS, storage encryption, and trust-zone design documented. | **Not started** — the hosted database connection uses TLS (`sslmode=require`), but there is no written deployment security design. |
| `SIH-NFR-006` | Mandatory | Provide health checks, structured logs, and failure visibility. | Readiness checks and log surfaces cover feeds, inference, database, and alerts. | **In progress** — authenticated health, worker status/telemetry, and a live log stream (`/api/logs/*`) exist. A complete operational runbook does not. |
| `SIH-NFR-007` | Selected | Apply data minimisation and configurable retention to evidence. | Retention is configurable and shorter than source video retention. | **Ready for review** — evidence crops expire on a configured schedule; no source video is centrally stored by the live path. |
| `SIH-NFR-008` | Selected | Every service reproducible from a clean clone on Windows and Linux with pinned dependencies. | A teammate succeeds on another machine using only repository instructions. | **In progress** — [SETUP.md](../SETUP.md) documents both OSes against Python 3.11 with pinned backend requirements. Three Windows-specific defects were found and fixed on 2026-09-12 (see `docs/platform-notes.md`); a fresh second-machine rehearsal under these instructions has not yet been run. |

---

## G. Submission deliverables (`SIH-SUB`)

| ID | Priority | Requirement | Acceptance check / evidence | Status |
|---|---|---|---|---|
| `SIH-SUB-001` | Administrative | Submit the idea by **2026-09-30**. | Submission receipt retained outside Git. | **Not started.** |
| `SIH-SUB-002` | Mandatory | Provide a solution presentation covering problem understanding, architecture, the four components, analytics, alerts, stack, security, and scale. | Deck opens correctly and every claim traces to this ledger. | **In progress** — `Sentinel-Gujarat-Solution-Presentation*.pptx` in the repository root are **from the earlier programme and are not valid for this submission**; they need replacing with an SIH26127 deck. |
| `SIH-SUB-003` | Mandatory | Provide a technical proposal / HLD. | HLD covers components, integration, analytics, deployment, performance, security, and scale. | **In progress** — [docs/hld.md](hld.md) exists with architecture diagrams; deployment, performance, and scale sections are outstanding. |
| `SIH-SUB-004` | Mandatory | Demonstrate functioning software, not mock-ups. | Recording shows onboarding, ANPR, trajectory, analytics, and alerting on a real backend. | **Not started** — the capability exists and has been exercised; no recording has been produced. |
| `SIH-SUB-005` | Mandatory | Produce an output report of detected plates with timestamps. | Machine-readable export agrees with stored observations. | **Ready for review** — per-camera sightings export in JSON/CSV/HTML/PDF, plus the journey export, all generated from one builder. |

---

## Traceability rules

For every completed requirement, replace the status with evidence links in this format:

```text
Code: backend/app/routers/sightings.py:120
Test: backend/scripts/matching_policy_test.py::test_threshold
Demo: artifacts/public/<packet>/README.md
Docs: docs/hld.md#alert-system
PR:   #123
```

Evidence must be reproducible and must never contain credentials, private feed URLs, personal data, or unauthorised footage.

## Honesty rules for this ledger

These exist because an over-claimed ledger is worse than an empty one:

1. A requirement implemented on a branch is `Unmerged`, never `Ready for review`.
2. A quantitative claim (accuracy, throughput, latency) requires a measurement, not an expectation. `SIH-OCR-002` stays `Not started` until labelled ground truth exists.
3. Where the deployed metadata cannot support a quantity — per-camera speed without calibration — the ledger says so and the API omits the field, rather than shipping an approximation that reads as fact.
