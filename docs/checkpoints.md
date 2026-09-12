# Checkpoints and Acceptance Criteria

Dates are aggressive because the official submission deadline is 2026-09-30. Adjust owners, not exit criteria, when work moves. A checkpoint is complete only when its evidence is on `main` and another teammate can reproduce it.

## Checkpoint summary

| ID | Target | Outcome | Suggested tag |
|---|---:|---|---|
| `C0` | 2026-08-28 | Documentation and source-of-truth baseline | - |
| `C1` | 2026-08-29 | Architecture, stack, schemas, and team lanes frozen | `v0.1-contracts` |
| `C2` | 2026-08-30 | Resilient catalogue-driven camera ingestion | `v0.2-camera-ingestion` |
| `C3` | 2026-08-31 | registry/GIS registry, GIS, health, and onboarding | `v0.3-registry-gis` |
| `C4` | 2026-09-02 | ANPR, watchlist matching, and real-time alerts | `v0.4-alerting` |
| `C5` | 2026-09-03 | Cross-camera vehicle journey and searchable evidence | `v0.5-vehicle-journey` |
| `C6` | 2026-09-04 | Integrated government-feed rehearsal and reliability | `v0.6-integrated-demo` |
| `C7` | 2026-09-05 | HLD, scale/cost plan, presentation, and reports | `v0.9-submission-candidate` |
| `C8` | 2026-09-06 | Clean-machine dress rehearsal and submission audit | `v1.0-submission` |
| `C9` | 2026-09-30 | Submission completed and receipt retained | - |

## C0 - Documentation baseline

- [x] `main` exists as the only long-lived branch.
- [x] README, requirements, approach, architecture, checkpoints, API, context protocol, and agent instructions exist.
- [x] Official sources and the secondary playbook are distinguished.
- [x] No files are staged or committed until the human reviews the baseline.

## C1 - Architecture and contract freeze

- [ ] Eligibility category, registration owner, and camera source-access status are confirmed.
- [x] ADR 0001 is accepted or replaced.
- [x] Application stack and canonical package sources are chosen in ADR 0002; native/demo-machine and ML lock evidence remains a C8 gap.
- [ ] Camera, Observation, WatchlistEntry, Alert, and Journey contracts are agreed.
- [ ] CameraSource and stream-epoch/discontinuity contracts are agreed.
- [ ] API v1 skeleton is agreed.
- [x] Local setup/start/test commands are defined and a same-host clean-clone rehearsal passes; the project owner has confirmed the second-machine teammate rehearsal ([attestation](../artifacts/public/checkpoint-c8/teammate-second-machine-attestation-2026-08-31.md)).
- [ ] Three work lanes have primary owners and separate reviewers.
- [ ] One synthetic/protocol-compatible sample feed can be used without committing footage.

## C2 - Resilient ingestion

Linked requirements: `GOV-ING-001` through `GOV-ING-015`.

- [ ] Cameras are discovered from a catalogue fixture and, when available, the official `/api/ingest` endpoint.
- [ ] RTSP capture forces TCP; HLS fallback is documented.
- [ ] H.264 and H.265 plus mixed resolutions are exercised.
- [ ] PTS, not arrival time or reported FPS, drives timing.
- [ ] Real-time-only behaviour is exercised: no seeking, complete-file download, or running ahead of the stream.
- [ ] Feed restart recovers with bounded exponential backoff.
- [ ] Join warnings, gaps, and scene discontinuity do not crash the pipeline.
- [ ] Worker concurrency is bounded, duplicate client fan-out is measured, and inactive captures close.
- [ ] Health and redacted diagnostic output are available; the private support procedure preserves the exact URL.

## C3 - Registry and GIS

Linked requirements: `GOV-M1-001` through `GOV-M1-008`.

Current state: implementation exists for the registry, manual/catalogue onboarding, CSV create/update onboarding, text/type filtering, department-scoped CSV/JSON export, GIS type/health filters with optional indicative coverage rings, probe-derived health reason/history, application-append-only maintenance work-order lifecycle history, current health fields, gap-report generation, a committed safe synthetic registry/watchlist fixture, and department RBAC/state-change/export/read/denial audit. Migration `202608311800` rejects application-role audit-event updates/deletes, except the required account-deletion foreign-key actor-reference cleanup. A super-admin-only canonical NDJSON archive supports SHA-256-verifiable download and once-only external-mount delivery. A same-host clean clone passed its migration/fixture/build/non-ML verification, and the project owner has confirmed the teammate second-machine rehearsal. The project owner also confirms that official catalogue sync is operational; the referenced 502 is a historical transient recheck. Current evidence includes `artifacts/public/checkpoint-c3/gis-coverage-layer-browser-2026-08-31.md`, `artifacts/public/checkpoint-c3/catalogue-onboarding-recheck-2026-08-31.md`, the linked C3 evidence files, `artifacts/public/checkpoint-c6/run-1/README.md`, and `artifacts/public/checkpoint-c7/run-1/README.md`. C3 remains open because a redacted official demonstration record and an approved WORM/object-lock destination still need to be evidenced.

- [x] Registry schema and migrations cover mandatory metadata.
- [x] Bulk, manual, and API onboarding work with validation; official catalogue sync is project-owner confirmed operational, while redacted demo evidence remains open.
- [x] Authenticated browser evidence demonstrates map rendering and department/type/status filtering, coverage rings, and unplaced assets; see `artifacts/public/checkpoint-c3/gis-coverage-layer-browser-2026-08-31.md`.
- [x] Probe-derived health reason/history, last-successful transport state, and application-append-only maintenance work-order history are visible; synthetic offline/lifecycle/role-boundary verification and protocol-compatible interruption/recovery evidence pass. Official-live evidence remains open.
- [x] Text/type search and filtered CSV/JSON export work; synthetic super-admin and viewer/cross-department-grant verification passes.
- [x] A committed metadata-only camera and watchlist fixture can be seeded and verified without camera source, media, or ML access.
- [x] Audit events identify actor, action, target, and result for implemented security/state-change/read/denial actions; current synthetic verification passes, the application database role cannot update/delete audit rows, and a super admin can download or deliver a digest-verifiable audit archive. Provisioning/testing an immutable retention destination and database-superuser bypass controls remain `GOV-NFR-003` gaps.
- [x] A synthetic coverage/ageing gap report is generated in JSON, HTML, and PDF; it contains only committed safe fixture data. Live/city-wide report evidence remains open.

## C4 - ANPR, watchlist, and alerts

Linked requirements: `GOV-FUN-003` through `GOV-FUN-007` and `GOV-NFR-001` through `GOV-NFR-006`.

- [x] ANPR emits normalised plate, confidence, camera, source-anchored time, and an authorised evidence URL in the C6 synthetic live packet; official-feed output remains open.
- [x] Synthetic watchlist import/search works.
- [x] Match thresholds and normalisation have deterministic tests; explicit ambiguity handling remains open.
- [x] A live-simulated observation creates an automatic alert.
- [x] Duplicate observations do not create an alert storm.
- [x] Alert acknowledge/resolve actions require operator clearance and append actor/target/department/result audit events; current synthetic verification passes.
- [ ] Representative accuracy/error limits are recorded. C7 records sub-five-second synthetic alert timing but does not substitute for accuracy evaluation.

## C5 - Vehicle journey

Linked requirements: `GOV-FUN-008` through `GOV-FUN-010`.

- [x] Evaluator-provided plate can be queried without redeployment; C6 supplies a safe synthetic designated plate.
- [x] Observations from multiple cameras produce an ordered journey.
- [x] C6 route exports show camera/location, source time, confidence, and authorised evidence URLs; a browser Journey walkthrough remains open.
- [ ] Search by plate, time, camera, and department works.
- [x] JSON/CSV/HTML/PDF journey exports reconcile in C6; a redacted UI walkthrough remains open.
- [ ] Ambiguous/low-confidence observations are visibly distinguished.

## C6 - Integrated rehearsal

- [ ] Approximately 50 catalogue entries can be onboarded without hard-coded IDs.
- [x] A configured synthetic active-feed subset runs with recorded queue/FPS/resource metrics; official-feed sizing remains open.
- [ ] Official government feed onboarding/viewing/analytics path is recorded when access permits.
- [x] Synthetic feed interruption, database restart, and worker restart recovery/degradation are recorded in C7.
- [ ] Own-feed and government-feed demo scripts pass twice.
- [x] C3/C6/C7 public evidence is synthetic/redacted and excludes credentials, personal data, and unauthorised footage.
- [ ] All mandatory runtime requirements are `Done` or have an explicit owner and recovery plan.

## C7 - Submission package

- [ ] Presentation draft covers every item in `GOV-SUB-001`.
- [ ] HLD covers every item in `GOV-SUB-002`.
- [ ] Scale plan includes compute, GPU, bandwidth, storage, HA/DR, security, rollout, and cost.
- [ ] Own-feed video is 2-3 minutes and shows functioning software.
- [ ] Government-feed video and timestamped output report reconcile.
- [ ] Demo narration distinguishes built, measured, simulated, and proposed capabilities.
- [ ] Requirement ledger links every claim to evidence.

## C8 - Dress rehearsal and audit

- [x] A teammate performs setup from a clean clone on a second machine (project-owner confirmation recorded in the C8 attestation).
- [ ] Pinned dependencies and environment example are complete.
- [ ] Demo runs without developer-only manual database edits.
- [ ] Backup demo path and stable tag are available.
- [ ] All links are tested in a signed-out/private session.
- [ ] Credentials are least-privilege and shared outside Git.
- [ ] Two-person submission-manifest review passes.
- [ ] Official pages and portal announcements are rechecked for changes.

## C9 - Submission

- [ ] Human owner performs the external submission.
- [ ] Submission receipt/time and final artifact checksums are retained outside Git.
- [ ] `PROJECT_STATE.md` records completion without exposing private submission data.
- [ ] Team preserves the exact submitted tag and artifacts.

## Evidence packet convention

Each checkpoint should have a small, non-sensitive evidence index:

```text
artifacts/public/checkpoint-cN/
  README.md          # what was tested and requirement IDs
  results.json       # machine-readable measurements
  screenshots/       # redacted UI evidence
  logs/              # redacted, bounded logs
```

Large videos, private feeds, model weights, and sensitive artifacts belong in approved external storage; the repository stores checksums and access instructions, not credentials.
