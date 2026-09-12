# Documentation index

Everything in this directory describes **SIH26127** — *City-Wide AI Engine for Multi-Camera ANPR Trajectory Tracking and Urban Traffic Analytics*, Bharat Electronics Limited, Smart India Hackathon 2026.

## Read in this order

| # | Document | What it answers |
|---|---|---|
| 1 | [../SETUP.md](../SETUP.md) | How do I run this on Windows or Linux? |
| 2 | [../PROJECT_STATE.md](../PROJECT_STATE.md) | What actually works right now, and what doesn't? |
| 3 | [requirements.md](requirements.md) | What must be built, and what is the evidence for each item? |
| 4 | [hld.md](hld.md) | What is the system, in one document, with diagrams? |
| 5 | [architecture.md](architecture.md) | What is each component responsible for? |
| 6 | [decisions/](decisions/) | Why is it built this way? |

## Reference

### Design and contracts

| Document | Contents |
|---|---|
| [hld.md](hld.md) | High-Level Design: problem framing, system context, data flow, the four expected components, deployment, explicit non-goals. Mermaid diagrams throughout. This is the `SIH-SUB-003` deliverable |
| [architecture.md](architecture.md) | Component responsibilities, transport invariants, failure behaviour, security boundaries |
| [api.md](api.md) | HTTP API surface: registry, sightings, watchlist, alerts, journeys, analytics, Investigate |
| [../DESIGN.md](../DESIGN.md) | Operator-console visual system: tokens, type, the certainty grammar |

### Build specifications

These describe how a slice was built and why. They were renamed in [ADR 0004](decisions/0004-sih26127-rescope.md) to drop an inherited `Model N` vocabulary that does not exist in SIH26127.

| Document | Covers |
|---|---|
| [registry-gis-build-spec.md](registry-gis-build-spec.md) | Camera registry, onboarding paths, PostGIS layer, gap analysis |
| [anpr-pipeline-build-spec.md](anpr-pipeline-build-spec.md) | Observation → watchlist match → alert → journey pipeline |
| [operator-console-build-spec.md](operator-console-build-spec.md) | Operator console views and their API contracts |
| [frontend-v3-design.md](frontend-v3-design.md) | The served console's design direction |

### Operations and testing

| Document | Covers |
|---|---|
| [demo-and-government-modes.md](demo-and-government-modes.md) | The two demonstration toggles, sidecar format, drift detection |
| [platform-notes.md](platform-notes.md) | **Windows/Linux defects and the rules that prevent them.** Read before touching subprocesses, temp files, or device strings |
| [investigate-testing.md](investigate-testing.md) | Offline forensic search: upload, ingest, plate and person search |
| [webrtc-relay-testing.md](webrtc-relay-testing.md) | WHEP low-latency preview and its same-machine media-plane limitation |
| [sandbox-access.md](sandbox-access.md) | The inherited camera-catalogue connector. **Not an SIH26127 requirement** — retained as one source adapter |

### Process

| Document | Covers |
|---|---|
| [approach.md](approach.md) | Execution plan and work lanes |
| [checkpoints.md](checkpoints.md) | Milestones and exit criteria |
| [context-management.md](context-management.md) | Cross-machine and cross-agent collaboration protocol |
| [source-register.md](source-register.md) | Where each requirement came from, and what is still ambiguous |
| [task-template.md](task-template.md) | How to restate a task before starting it |
| [handoffs/](handoffs/) | Work-in-progress handoff packets |
| [presentation-evidence-map.md](presentation-evidence-map.md) | Claim-to-evidence mapping for the deck |

## Decision records

| ADR | Decision |
|---|---|
| [0001](decisions/0001-integration-shape.md) | Registry/GIS control plane + direct feed integration behind adapter boundaries |
| [0002](decisions/0002-implementation-stack.md) | Implementation stack and pinned versions |
| [0003](decisions/0003-department-rbac.md) | Department-scoped role model |
| [0004](decisions/0004-sih26127-rescope.md) | **Re-scope from the earlier programme to SIH26127** |

## Conventions

- **Requirement IDs** are stable. Reference them (`SIH-OCR-002`) rather than restating a requirement.
- **Status words** mean specific things — see [requirements.md](requirements.md). `Unmerged` is distinct from `Ready for review`, and a quantitative claim needs a measurement.
- **Do not duplicate a contract across files.** Link to the canonical location.
- **`artifacts/` is history.** Those dated evidence packets are not edited to match current framing; they record what was verified and when.
