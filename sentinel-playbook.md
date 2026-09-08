---
title: "Sentinel Playbook"
subtitle: "Gujarat Police CCTV Integration Hackathon 2026 — Working Reference"
---

# Sentinel Playbook

**Gujarat Police Innovation Hackathon 2026 — CCTV Integration Challenge**

Everything needed to start building: the problem the state has posed, the four reference architectures, the live sandbox protocol, the deliverables, and how submissions are judged.

| Submission closes | Event          | Total prize pool | Target scale    | Live test rig | Departments today      |
| ----------------- | -------------- | ---------------- | --------------- | ------------- | ---------------------- |
| 07 Sep 2026       | 10–11 Sep 2026 | ₹51,00,000       | ~80,000 cameras | ~50 cameras   | 26 independent systems |

---

## Contents

1. [Background & core goal](#background-core-goal)
2. [Architecture principles](#architecture-principles)
3. [Integration models](#integration-models)
4. [Hackathon process — the 7-step journey](#hackathon-process-the-7-step-journey)
5. [Live technical test case](#live-technical-test-case)
6. [Sandbox integration guide](#sandbox-integration-guide)
7. [Tech stack matrix](#tech-stack-matrix)
8. [Submission requirements](#submission-requirements)
9. [Scaling to ~80,000 cameras](#scaling-to-80000-cameras)
10. [Evaluation & bonus consideration](#evaluation-bonus-consideration)
11. [Format, eligibility & prizes](#format-eligibility-prizes)
12. [Dates & contacts](#dates-contacts)
13. [Team working notes](#team-working-notes)

---

## 1. Background & core goal

26 Government of Gujarat departments each run an independent CCTV system today — a mix of analog and IP cameras spread from border districts to Valsad, Dahod, Somnath, Jamnagar and Dwarka, roughly 1,000 km apart at the extremes.

Storage is split between cloud and local infrastructure, and retention ranges from 7 days to 15+ days depending on the department. Usage patterns differ by mandate:

- **Home Department** — public-domain traffic monitoring, law & order, crime detection.
- **Food & Civil Supplies** — godowns, PDS shops, related facilities.
- **RTO** — offices, testing tracks, checkpoints.

The state wants these government cameras — plus, wherever feasible and permitted, public-facing private CCTV from societies, malls and commercial establishments — unified into one video management and analytics ecosystem. That ecosystem must also connect to existing law-enforcement databases for automated real-time alerts:

`VAHAN` · `SARTHI` · `eGujCop (CCTNS)` · `AFIS` · `NAFIS`

— covering arrested persons, stolen vehicles, wanted criminals, missing persons, unidentified bodies and fingerprint records.

> **Core goal (verbatim):** Propose a secure, scalable, interoperable, technically feasible, and cost-effective approach that uses existing infrastructure to the maximum practical extent.

### Four standing challenges

| Challenge                        | Detail                                                                                                                  |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| **Heterogeneous infrastructure** | Different vendors, VMS platforms, AMC periods, storage architectures, camera types, formats and feed-sharing protocols. |
| **Geographical dispersion**      | Camera sites distributed statewide, distances extending to ~1,000 km.                                                   |
| **Unified analytics**            | Analytics and event handling must work across onboarded cameras through one framework.                                  |
| **Scalability**                  | New cameras, departments and analytics must onboard without major redesign.                                             |

---

## 2. Architecture principles

The solution must be **open, modular, scalable, secure, standards-based and vendor-neutral** — no vendor lock-in, and seamless integration, interoperability, replacement, upgrade and future expansion of cameras, VMS, analytics engines, storage and AI modules via documented APIs, open protocols, SDKs and adapter-based frameworks. It must stay technology-agnostic, support heterogeneous multi-vendor environments, and accommodate future enhancement without a major redesign.

**Permitted approaches:**

1. Any one of the five reference solution models (Model 1 alone is not a complete submission — see below).
2. A hybrid architecture combining two or more reference models.
3. A fully customised architecture — provided it still integrates diverse CCTV systems, correlates live feeds with watchlist databases, and generates AI-powered real-time alerts.

---

## 3. Integration models

Model 1 is the **mandatory common foundation**. It must be paired with at least one of Models 2–4, or with a hybrid/custom architecture, to form a complete submission.

### Model 1 — Centralised CCTV Registry & GIS Mapping _(mandatory foundation)_

A metadata & asset-visibility layer only — no centralised live streaming or recording. It onboards and maintains camera metadata (location, department, type, ownership, connectivity, storage) to create a unified inventory for planning, gap-analysis and decision-making. Must be combined with another model to actually move video or analytics.

**Key functional features**

- Bulk import, manual entry, and API-based camera onboarding
- Interactive GIS map with department / type / status / coverage layers
- Camera health & maintenance-status monitoring
- Gap-analysis reports for uncovered zones and ageing infrastructure
- Role-based search, filtering, export, and metadata audit trails

**Suggested stack:** Leaflet · OpenLayers · PostGIS · Node.js · Python (Django/FastAPI) · PostgreSQL · React.js · department-wise RBAC

**Expected deliverables**

- Working registry portal with GIS map view
- Bulk + manual onboarding demonstration
- Sample onboarded metadata dataset
- Registry API documentation
- Sample gap-analysis report

**Flow:** Dept. CCTV assets → Onboarding & validation → Central registry → PostgreSQL + PostGIS → GIS dashboard & APIs

### Model 2 — Unified Viewing & Metadata Analytics

Connects **directly** to each departmental CCTV/VMS system (RTSP, ONVIF, vendor SDKs, APIs) and aggregates the streams into one interface — no middleware layer, existing departmental systems keep running untouched. Focus is centralised viewing plus selective metadata/analytics (ANPR, event tagging) without necessarily storing all video centrally.

**Key functional features**

- Feed aggregation via RTSP / ONVIF / vendor APIs
- ANPR-based metadata generation
- Event tagging and camera-wise indexing
- Searchable vehicle-movement records
- Configurable video walls / multi-camera grids
- Alerts for tagged events and vehicles of interest

**Suggested stack:** WebRTC / HLS relay · ONVIF/RTSP libraries · vendor SDKs · ANPR (open-source or custom) · Node.js / Python microservices · Kafka · Elasticsearch · PostgreSQL

**Expected deliverables**

- Unified viewer connected to ≥2 different source systems
- ANPR demonstration on live or recorded feeds
- Searchable metadata dashboard
- Architecture note proving departmental systems remain unaffected

**Flow:** Departmental VMS (remain independent) → RTSP/ONVIF/APIs → Unified stream gateway → Analytics & metadata → Unified control-room view

### Model 3 — VMS Federation & Middleware

A middleware/federation layer sits **between** the platform and every departmental VMS — unlike Model 2, nothing connects to departmental systems directly. The middleware integrates via APIs, SDKs, metadata exchange and event-sharing, then exposes one unified interface downstream, while departments keep full control of their own infrastructure.

**Key functional features**

- Adapter/plugin architecture for multiple VMS vendors
- Metadata exchange bus for camera and event information
- Cross-system event-correlation engine
- Unified workflow and alert dashboard
- Extensible connector framework for future vendors

**Suggested stack:** Node.js / Java (Spring Boot) · Kafka / RabbitMQ · Kong / NGINX · PostgreSQL · Redis · React.js

**Expected deliverables**

- Working middleware demo federating ≥2 systems
- Unified event-correlation dashboard
- Adapter/plugin architecture documentation
- Sample federated analytics report

**Flow:** Multiple vendor VMS (dept-controlled) → Adapters/connectors → Federation middleware → Event & metadata bus (Kafka/RabbitMQ) → Unified dashboard

### Model 4 — Central VMS & AI Platform

One consolidated Central VMS for centralised monitoring, recording, storage, playback and advanced AI analytics across every department — the fully-centralised, statewide-scale option. Needs the heaviest infrastructure: scalable storage, high-bandwidth connectivity, centralised compute, redundancy and cybersecurity controls sized for large-scale ingestion and real-time processing.

**Key functional features**

- Centralised feed ingestion
- Tiered hot / warm / cold storage
- ANPR, face recognition, crowd/vehicle counting, anomaly detection
- Statewide vehicle tracking & route reconstruction
- Integration-ready for VAHAN, SARTHI, eGujCop, AFIS, NAFIS
- Redundancy, disaster recovery, encryption, network segmentation, RBAC

**Suggested stack:** Custom/extended open-source VMS · S3-compatible object storage / Ceph · Kafka + GPU inference · PostgreSQL / TimescaleDB · Kubernetes · high-bandwidth backbone with regional edge

**Expected deliverables**

- Working centralised VMS prototype on multi-department sample feeds
- ANPR + multi-location vehicle-tracking demo
- Scalability / load-test report for ~80,000 cameras
- Disaster-recovery & redundancy design
- Security architecture document

**Flow:** Statewide CCTV sources → Central ingestion layer → Central VMS platform → Storage & AI analytics → Command centre & integrations

### Hybrid / Innovative Architecture

Models 2–4 are reference points, not a menu you must pick one from. A hybrid combining elements of two or more models, or a fully custom architecture, is explicitly permitted — provided it still meets the functional, interoperability, security, scalability and analytics requirements above, and is still built on the Model 1 registry foundation.

---

## 4. Hackathon process — the 7-step journey

1. **Understand the background** — absorb the 26-department problem, the four standing challenges, and the core goal. _(§1)_
2. **Choose an integration model** — Model 1 plus one of Models 2–4, a hybrid, or a fully custom architecture. _(§3)_
3. **Build the platform** — design overall architecture, integration strategy, AI/video analytics, cybersecurity architecture, deployment architecture, infrastructure sizing, cost-benefit analysis, department-wise information requirements, scalability strategy and a future roadmap.
4. **Test on CCTV feeds** — onboard ~50 heterogeneous cameras, track a designated vehicle, generate alerts and route history, visualise on GIS. _(§5)_
5. **Prepare & submit** — solution presentation, HLD, own-feed demo, government-feed demo, output report, submission links. _(§8)_
6. **Plan for scale** — a credible path to ~80,000 cameras statewide: infra, network, storage, AI capacity, DR, rollout. _(§9)_
7. **Evaluation & recognition** — judged against seven common areas, with bonus consideration for capability beyond the mandatory bar. _(§10)_

---

## 5. Live technical test case

After registration, the Resources page exposes ~50 geographically distributed simulated-live camera feeds spanning multiple departments, technologies, formats, VMS platforms and storage mechanisms.

- Onboard the available cameras onto one integrated platform.
- Enable centralised monitoring and AI-powered video analytics.
- On the day, you receive a **vehicle registration number** — identify, trace and present that vehicle's movement across the integrated camera network, across locations and time.
- Continuously cross-reference live feeds against a representative **watchlist database** (your own) and fire automated real-time alerts on a match.

**Expected output**

- Demonstrated identification and trace of the designated vehicle by registration number
- Complete route: timestamped, location-wise movement history
- Working watchlist integration: continuous cross-referencing + automated real-time alerting on match
- Evidence of successful integration, AI analytics, interoperability, scalability and end-to-end performance

---

## 6. Sandbox integration guide

Every camera in the sandbox is a live RTP/RTSP stream: one second of video takes one second to arrive, frames carry monotonic PTS, and there is no seeking, byte-range fetching, or running ahead of real time. Treat each endpoint like a physical camera on an operational network.

| Protocol      | Endpoint                                    | Intended for                                         |
| ------------- | ------------------------------------------- | ---------------------------------------------------- |
| RTSP          | `rtsp://<host>:8554/stream/<id>`            | AI inference — OpenCV, GStreamer, FFmpeg, DeepStream |
| WebRTC (WHEP) | `http://<host>:8889/stream/<id>/whep`       | Low-latency browser preview                          |
| HLS           | `http://<host>/live/stream/<id>/index.m3u8` | Dashboards, mobile, restricted networks              |

Always start from the catalogue — camera ids and availability can change; the catalogue is the contract, the URL pattern is not.

```
curl -s http://<host>/api/ingest
→ every camera's id, location, codec, live status, stream properties, and all three URLs
```

**Minimal connection snippets**

```python
# OpenCV (Python) — force TCP transport
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
cap = cv2.VideoCapture("rtsp://<host>:8554/stream/1", cv2.CAP_FFMPEG)
pts_ms = cap.get(cv2.CAP_PROP_POS_MSEC)   # drive timing from this, not wall clock
```

```bash
# GStreamer
gst-launch-1.0 rtspsrc location=rtsp://<host>:8554/stream/1 protocols=tcp latency=200 \
 ! rtph264depay ! h264parse ! avdec_h264 ! videoconvert ! fakesink
# use rtph265depay / h265parse for H.265 streams

# FFmpeg / ffprobe
ffplay -rtsp_transport tcp rtsp://<host>:8554/stream/1
```

NVIDIA DeepStream: use `nvurisrcbin` / `uridecodebin` with `select-rtp-protocol=4` (TCP) — H.264/H.265 decode on `nvv4l2decoder`.

### Do's and don'ts

| Do                                                                                                                                                                                                     | Don't                                                                                                                                                                                                      |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Force RTSP over TCP.** UDP fails across NAT/firewalls and partial delivery looks like a model bug. If port 8554 is blocked, fall back to HLS.                                                        | **Trust the reported frame rate.** `CAP_PROP_FPS` (and equivalents) often don't match real delivery. Measure the actual rate, or use timestamps instead.                                                   |
| **Drive all timing from PTS**, not arrival time. On connect, the gateway replays a buffered GOP, so the first 1–2s can arrive faster than real time — trackers and Kalman filters must use PTS deltas. | **Assume a constant frame rate.** Intervals aren't uniform. Tolerate gaps; use actual elapsed PTS, not a fixed cadence.                                                                                    |
| **Reconnect with backoff.** Feeds are supervised and may restart. Start at ~2s, cap at ~30s — never a tight reconnect loop.                                                                            | **Treat join-time decoder warnings as fatal.** Mixed H.264/H.265; mid-stream attach can log errors until the first IDR frame. Normal and self-correcting.                                                  |
| **Expect a scene discontinuity.** Each feed loops; the cut looks like a camera reboot. Long-lived state (background models, re-id galleries, track ids) must recover from a hard cut.                  | **Assume a uniform grid.** Resolution, codec, frame rate and bitrate vary per camera — read properties from `/api/ingest` and size batching/decoders accordingly.                                          |
|                                                                                                                                                                                                        | **Plan around obtaining footage copies.** No file download exists. `/stream/<id>` is a browser-playback fallback only — curl/wget yields a partial file that looks complete. Build against a live capture. |
|                                                                                                                                                                                                        | **Publish to the gateway.** Consume only — never push streams or call the control API.                                                                                                                     |

### Pre-submission checklist

- [ ] Every client forces RTSP over TCP
- [ ] No timing logic depends on `CAP_PROP_FPS` or frame-arrival time
- [ ] Inter-frame gaps don't crash or stall the pipeline
- [ ] Reconnect-with-backoff is implemented and tested by restarting a feed
- [ ] Decoder warnings on join are logged, not fatal
- [ ] Camera list and per-camera properties are read from `/api/ingest`
- [ ] Pipeline handles mixed H.264/H.265 and mixed resolutions
- [ ] Behaviour is sane across a scene discontinuity

Support: report feed problems with camera id, exact URL, client + version, UTC timestamp and client-side error log — check the camera's live status in `/api/ingest` before reporting it down.

> **Dataset behind the sandbox:** ~12 hours of footage per camera from 30+ cameras across five departments — Health, Police, GSRTC, Panchayat, Municipal Corporation. A Python streaming middleware ingests the recordings, synchronises them on a common timeline, and serves each as a simulated live stream. This keeps every team on an identical, repeatable, fair dataset without exposing live production CCTV.

---

## 7. Tech stack matrix

All solutions must use open-source technologies. The organisers' suggested stacks per model are references, not a restriction — teams may choose their own.

| Layer                  | Suggested options                                      | Primarily seen in            |
| ---------------------- | ------------------------------------------------------ | ---------------------------- |
| GIS / mapping          | Leaflet · OpenLayers · PostGIS                         | Model 1                      |
| Backend services       | Node.js · Python (Django/FastAPI) · Java (Spring Boot) | Models 1–3                   |
| Database               | PostgreSQL · PostGIS · TimescaleDB · Redis             | All models                   |
| Frontend               | React.js                                               | Models 1–3                   |
| Live streaming / relay | WebRTC · HLS · RTSP · FFmpeg · GStreamer               | Models 2 & 4, sandbox ingest |
| Camera integration     | ONVIF · RTSP libraries · vendor SDKs                   | Models 2 & 3                 |
| Messaging / event bus  | Kafka · RabbitMQ                                       | Models 2–4                   |
| Search / indexing      | Elasticsearch                                          | Model 2                      |
| API gateway            | Kong · NGINX                                           | Model 3                      |
| AI / ML                | TensorFlow · PyTorch · ANPR (open-source or custom)    | Models 2 & 4                 |
| Bulk / scale storage   | S3-compatible object storage · Ceph                    | Model 4                      |
| Orchestration          | Kubernetes                                             | Model 4                      |
| Auth / access control  | Department-wise RBAC                                   | All models                   |

---

## 8. Submission requirements

### Documents

**1. Solution Presentation (PPT/PDF)** — chosen model with justification (Reference Model 1–5, hybrid, or custom); overview, objectives, key innovations; high-level architecture and end-to-end workflow; AI video-analytics approach; methodology for correlating feeds with watchlist databases and generating alerts; key technologies used; scalability/interoperability/security/deployment considerations; expected operational impact.

**2. Technical Proposal — High-Level Design (HLD)** — architecture diagrams and component interactions; approach for integrating heterogeneous cameras, NVRs and VMS; ingestion/processing architecture for dispersed live streams; watchlist-integration and real-time alerting approach; AI analytics (ANPR, FRS, object detection, tracking); alert generation and notification workflow; scalability/interoperability/security/performance for statewide deployment and ~80,000 cameras; technical prerequisites and information needed from departments.

### Demonstrations

**3. Demo on your own feed** — a 2–3 minute screen recording showing onboarding, AI-powered detection/analytics, correlation with a representative watchlist, and automatic real-time alerting on a match. **Must be a fully functional working solution** — mock-ups, animations, simulated interfaces or concept videos will not be accepted.

**4. Live demo on the government-provided feed** — onboard the provided feed(s), demonstrate live/recorded viewing and analytics output, and submit a screen recording plus an output report showing detected vehicles/plates with timestamps.

### How to submit

- Unlisted YouTube link (visibility set to Unlisted)
- Google Drive or OneDrive link, "Anyone with the link — Viewer"
- Optional: hosted platform URL with test login credentials for the screening committee
- Optional: GitHub / GitLab repository link with source code

---

## 9. Scaling to ~80,000 cameras

Present a strategy to scale securely and reliably to roughly 80,000 cameras statewide, covering:

- Central, regional, and edge-compute requirements
- GPU / accelerator requirements for video analytics
- Expected network bandwidth and low-bandwidth strategies
- Hot, warm and cold storage assumptions based on retention periods
- Load balancing, horizontal scaling, monitoring, logging, health checks
- High availability, backup, disaster recovery and cybersecurity controls
- Estimated implementation and operational costs

---

## 10. Evaluation & bonus consideration

All eligible submissions are first assessed against seven common areas; bonus consideration follows for capability shown beyond the mandatory bar.

| #   | Area                        | What's judged                                                                                  |
| --- | --------------------------- | ---------------------------------------------------------------------------------------------- |
| 01  | Successful test case        | Onboarding + operation on the government feed, including viewing and required analytics output |
| 02  | Solution presentation       | Clarity/completeness of the PPT/PDF — problem understanding, model justification, features     |
| 03  | Solution architecture       | Technical soundness, feasibility, security, interoperability, HLD clarity                      |
| 04  | Working platform & demo     | Maturity of the actual platform, on own feed and government feed                               |
| 05  | Video analytics output      | Quality/usefulness of ANPR, detection, timestamps, output reports                              |
| 06  | Scalability & PoC readiness | Readiness to scale toward ~80,000 cameras; on-site PoC preparedness                            |
| 07  | Submission completeness     | All documents, videos, reports, links, credentials present and consistent                      |

**Bonus consideration** _(does not offset a missed mandatory requirement)_:

- Innovative hybrid or customised architecture with clear operational value
- Advanced cross-camera vehicle tracking / multi-camera correlation
- Additional reliable analytics beyond mandatory ANPR
- Strong edge-processing, bandwidth-optimisation, low-connectivity operation
- Enhanced cybersecurity, privacy protection, auditability, RBAC
- Operational dashboards, automated alerts, health monitoring, integration-ready APIs

---

## 11. Format, eligibility & prizes

### Two phases

**Phase 1 — Sandbox Round:** integrate against the organiser's test feed, competing within your category. The six highest-ranked teams across both categories qualify for Phase 2. Phase 1 prize money also doubles as a grant toward building the Phase 2 solution.

**Phase 2 — Production Round (Grand Finale):** the six qualifiers demonstrate their solution on live camera feeds in a production-scale environment.

### Eligibility categories

- **Category 1 — Academic / Research / Startup:** students, graduates, postgraduates, doctoral scholars, academic/research teams, and DPIIT-recognised startups (valid DPIIT certificate required).
- **Category 2 — Industry / Enterprise:** companies, industry partners, system integrators, technology solution providers, LLPs, partnerships and other enterprises not eligible under Category 1.

Individual and team participation are both allowed. Knowledge partners **NFSU** and **DA-IICT** provide technical/academic guidance and support evaluation.

### Prize breakdown

**Phase 1 · Sandbox Round — ₹18,00,000**

|                | Amount                      |
| -------------- | --------------------------- |
| Category 1     | 1st ₹4L · 2nd ₹2L · 3rd ₹1L |
| Category 2     | 1st ₹5L · 2nd ₹3L · 3rd ₹2L |
| Consolation ×4 | ₹25,000 each                |

**Phase 2 · Grand Finale — ₹31,00,000**

|                    | Amount                       |
| ------------------ | ---------------------------- |
| Top 3              | 1st ₹16L · 2nd ₹8L · 3rd ₹7L |
| Consolation ×3     | ₹50,000 each                 |
| Special Jury Award | ₹50,000                      |

**Total prize pool: ₹51,00,000**

---

## 12. Dates & contacts

| Milestone                        | Date                      |
| -------------------------------- | ------------------------- |
| Registration opens               | 4 August 2026             |
| Registration & submission closes | 7 September 2026          |
| Shortlisting                     | 7 September 2026, evening |
| Event (Phase 2 Grand Finale)     | 10–11 September 2026      |
| Results                          | 11 September 2026         |

Official site: [sentinel.gujarat.gov.in](https://sentinel.gujarat.gov.in) · State Crime Records Bureau, Next to Police Bhawan, Sector-18, Gandhinagar, Gujarat 382009 · +91 95370 89982 · sentinel.hackathon@gujarat.gov.in · Helpdesk Mon–Sat, 10 AM–6 PM.

---

## 13. Team working notes

Open decisions worth settling before writing code — not official hackathon content, just a starting checklist for kickoff.

- **Which model(s)?** Model 1 is fixed; pick a partner model (2, 3, or 4) or a named hybrid, and be ready to justify it in the presentation.
- **Watchlist data model.** Design the schema for the representative watchlist now (stolen vehicles, wanted/missing persons, blacklisted vehicles) — it drives the matching-and-alert pipeline that's scored directly.
- **ANPR approach.** Open-source model vs. custom-trained — needs to run reliably on the sandbox's mixed H.264/H.265, mixed-resolution feeds.
- **Vehicle tracking across cameras.** Cross-camera re-identification/route reconstruction is the centerpiece of the live test case — prioritise it early, not as a late add-on.
- **Sandbox client resilience.** Build reconnect-with-backoff and PTS-based timing from day one (§6) — retrofitting this after a tracker is built on wall-clock time is expensive.
- **Demo discipline.** Both required demos must run on a genuinely working backend — budget real time for the government-feed demo and its output report, not just the own-feed demo.
- **Scalability story.** Even a small Phase-1 build needs a written, numbers-backed path to ~80,000 cameras (§9) — this is graded whether or not it's built.

---

_Compiled from the official Gujarat Police Innovation Hackathon 2026 pages (Problem Statement & Solution Flow, About, Integrator's Guide, FAQs) for internal team reference. Verify against [sentinel.gujarat.gov.in](https://sentinel.gujarat.gov.in) before finalising submissions, as official details take precedence._
