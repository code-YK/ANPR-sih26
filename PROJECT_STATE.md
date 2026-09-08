# Project State

Last updated: 2026-08-31 (GIS/browser and synthetic live/reliability evidence, external audit delivery, suspicious-activity alerts, a WebRTC/WHEP MediaMTX relay, and Investigate person-photo search reconciled)

This is the smallest canonical snapshot of the project. Update it in any PR that changes priorities, architecture status, milestone status, or known risks. It should describe merged reality on `main`, not unmerged aspirations.

## Status

- Phase: Model 1 core implementation, the Model 2 vertical slice, department-scoped demo RBAC, the operator-console redesign, and an offline forensic-search feature (Investigate, vehicle/Phase 1) are merged; mandatory checkpoints remain incomplete. Registry/onboarding/GIS/reporting basics and authenticated React operator flows exist on `main`, with a slide-ready Model 1 + Model 2 evidence map; requirement-ledger gaps remain the source of truth.
- Repository branch: `main`
- Application code: `backend/` (FastAPI + Postgres/PostGIS; also spawns a local `mediamtx` relay process for WebRTC/WHEP preview — see below), `frontend-v2/` (React 19 + Vite authenticated operator console — the only served UI), `frontend/` (unserved vanilla migration reference), and `multi-object-tracking/` (YOLO11+ByteTrack+fast-alpr ANPR worker, person-counting worker, suspicious-activity worker, offline recording-ingest worker, and person-search embedding extraction, own `.venv` — worker-authenticated callbacks include `POST /api/sightings`, `POST /api/analytics/counts`, `POST /api/alerts/suspicious`, and `/api/investigate/runs/*`)
- New local system dependency: `mediamtx` (`brew install mediamtx` on macOS), used both for the WebRTC/WHEP relay below and for the Section 5 live-test fixture's synthetic camera streaming (`backend/scripts/live_test_relay.py`) -- the two were built on separate branches with the same default RTSP/API ports (8554/9997) and now need one overridden when both run at once on the same machine (see `backend/app/config.py`'s merge note). Its absence is non-fatal for WebRTC specifically -- the backend logs a warning and every camera stays previewable over HLS.
- Demo status: runnable instructions and authenticated general/RBAC smoke scripts exist. On 2026-08-31 the general non-ML API suite passed 11/11 executed checks, including deterministic offline-health and maintenance-work-order lifecycle verification, CSV manual-camera creation/update/error handling, server-enforced search/type filtering, safe CSV/JSON export/audit, and gap-analysis JSON/HTML/PDF. The project owner confirms the official catalogue sync is operational; the recorded upstream-502 skip is a historical transient recheck, not the current integration status ([historical recheck](artifacts/public/checkpoint-c3/catalogue-onboarding-recheck-2026-08-31.md)). RBAC verification covers role/grant/audit workflow, direct database-audit update/delete rejection, digest-verifiable export, and configured external archive delivery (the `/api/admin/audit-events` pagination shape the RBAC script needed to read has been current/correct on `main` since -- see the Phase 8 supporting-verification-sweep evidence). Authenticated browser GIS evidence covers map rendering, filters, health semantics, coverage rings, and unplaced cameras ([evidence](artifacts/public/checkpoint-c3/gis-coverage-layer-browser-2026-08-31.md)). Synthetic protocol-compatible and reliability runs cover feed interruption/recovery and the observation-to-alert-to-journey path ([C6 evidence](artifacts/public/checkpoint-c6/run-1/README.md), [C7 evidence](artifacts/public/checkpoint-c7/run-1/README.md)). The project owner confirmed the teammate second-machine rehearsal; this is recorded without invented run details in [the attestation](artifacts/public/checkpoint-c8/teammate-second-machine-attestation-2026-08-31.md). The Section 5 live-test plan's Phases 1-8 are complete and evidenced (`artifacts/public/checkpoint-c3` through `c9`); Phase 9 (the real government-feed rehearsal) is blocked on the sandbox catalogue's own outage, not on this project's readiness. The presentation deck is committed as `Sentinel-Gujarat-Solution-Presentation.pptx` and remains in progress. Remaining material evidence gaps are official/live demonstration recording/output, a provisioned WORM/object-lock retention destination, and ML accuracy/production security evidence.
- Official submission deadline: 2026-09-07
- Grand Finale dates: 2026-09-10 to 2026-09-11

## Current objective

Close the remaining mandatory Model 1 and reliability gaps. The next smallest Model 1 evidence work is a redacted recorded official-catalogue/live demonstration and use of the audit delivery endpoint against a provisioned WORM/object-lock retention destination.

## Architecture status

Accepted for Phase 1: Model 1 + Model 2 using an adapter boundary, a metadata-first modular monolith, and independent media/analytics workers. This decision does not waive incomplete mandatory requirements.

Decision records: [ADR 0001](docs/decisions/0001-proposed-integration-shape.md), [ADR 0002](docs/decisions/0002-phase-1-implementation-stack.md), and [ADR 0003](docs/decisions/0003-department-rbac.md).

## Open decisions

| Decision | Owner | Due | Status |
|---|---|---:|---|
| Confirm participant eligibility category and registration status | Team | 2026-08-28 | Open |
| Accept or revise the proposed integration shape | Team | 2026-08-29 | Resolved: ADR 0001 accepted 2026-08-30. |
| Select implementation stack and lock versions | Team | 2026-08-29 | Resolved for the application stack in ADR 0002. Remaining gap: native/demo-machine versions and the ML environment are not fully locked. |
| Confirm access to the authenticated sandbox catalogue and feeds | Team | 2026-08-29 | Partial: prior local runs reported an unauthenticated 30-entry catalogue, blocked RTSP from that network, and variable HLS success. No redacted access/probe artifact is merged, and participant-portal access remains unconfirmed. |
| Select ANPR baseline and representative watchlist schema | Team | 2026-08-29 | Resolved: YOLO11 + ByteTrack + fast-alpr (`multi-object-tracking/`), `watchlist_entries` table (flat, no separate `watchlists` grouping — see `docs/model2-build-spec.md`). Reproducible ML locking remains open. |
| Assign the three work lanes and reviewers | Team | 2026-08-29 | Open |
| Select repository/source-code licence before publication | Team | 2026-08-30 | Open |

## Progress

| Area | State | Evidence |
|---|---|---|
| Requirements ledger | Ready for review | `docs/requirements.md` |
| Architecture decision | Ready for review | `docs/architecture.md`, ADR 0001, ADR 0002 |
| Cross-agent context protocol | Ready for review | `docs/context-management.md` |
| Camera registry and GIS | In progress | `docs/model1-build-spec.md`, `backend/`, `frontend-v2/` — manual, catalogue, and CSV create/update onboarding; text/type filtering; department-scoped CSV/JSON export; health-oriented GIS markers and opt-in indicative coverage rings; probe-derived health history and application-append-only maintenance work-order history; committed safe synthetic data; state-change/export/read/denial audit; a database trigger rejecting application-role audit updates/deletes; SHA-256-verifiable archive download; and configured external archive delivery exist. Authenticated browser GIS evidence and synthetic live/reliability evidence are recorded. The project owner confirms official catalogue sync is operational; a real WORM/object-lock retention target and recorded official demonstration still need evidence. |
| Named catalogue-source onboarding (`GOV-CORE-004`) | In progress | A second, additive onboarding path alongside the original single-source sync (untouched): a super admin registers a named, credentialed catalogue source (`POST /api/catalogue-sources`), SSRF-hardened and adapter-validated, and triggers a read-only per-source sync with clear camera provenance (`source_id`, `src{id}-{raw_id}` ids). Backend + an Admin-panel UI section (`frontend-v2/src/views/Admin/AdminView.jsx`) both verified end to end 2026-08-31 (secret never returned, private-host rejection/override, insert-then-update idempotency, disappeared-camera detection, delete-blocked-with-cameras vs deactivate, legacy `/api/sync` unaffected). Only one adapter (`sentinel_default`) exists so far; a genuinely different catalogue schema would need a new registered adapter. |
| Stream ingestion | In progress | `multi-object-tracking/camera_feeds.py`; protocol-compatible H.264/H.265, mixed-resolution, VFR, restart/recovery, backend/database restart, bounded queue, and three-worker evidence are recorded in C7. RTSP/TCP proof, source-PTS/epoch tests, decoder-join/discontinuity policy, real-time pacing, shared-capture/bandwidth measurement, and official-feed evidence remain. |
| ANPR and observations | In progress | Worker ingestion, evidence crops/URLs, and a three-camera synthetic live run are evidenced in C6. Remaining gaps are accuracy/error limits on representative footage, official-feed output, and a reproducible ML/native environment lock. |
| Watchlist matching and alerts | In progress | CRUD, bulk import, configurable confidence threshold, deterministic normalisation/dedup policy, alert lifecycle, and synthetic live alert evidence exist. Ambiguous-match policy and representative accuracy evidence remain. |
| Cross-camera journey | In progress | Route map, timeline, evidence URLs, and JSON/CSV/HTML/PDF reconciliation across three synthetic cameras are recorded in C6. Department-wide search and explicit ambiguity handling remain. |
| Dashboard / operator console | In progress | `frontend-v2/` implements the authenticated console, GIS browser evidence, live-grid/reconnect evidence, HLS fallback, and a protocol-verified focused-camera WHEP path. A normal desktop-browser WHEP check, full operator-console walkthrough, and final submission recording remain open. |
| Suspicious-activity alerts (bonus) | In progress | A worker-token-only `POST /api/alerts/suspicious` path creates department-scoped, track-deduplicated standalone alerts for a purpose-trained suspicious-person classifier. It intentionally has no identity, watchlist, or journey linkage. Detection quality, false-positive limits, and representative evidence are not yet recorded. |
| WebRTC/WHEP low-latency preview (`GOV-ING-002`) | In progress | The Live view's focused-camera preview uses authenticated WHEP from local MediaMTX. Backend ffmpeg now prefers the registered RTSP source with TCP and uses HLS only when RTSP is absent; the browser never receives the private source URL. RTSP-only cameras can open the focused preview, while grid playback and negotiation fallback remain HLS-only. The HLS-sourced signaling and RBAC path was fully verified 2026-08-31 (offer/answer, session lifecycle, `connectionState` reaching `"connected"` with a real video track received). A real RTSP-sourced relay run and ordinary desktop-browser check remain open; in sandboxed headless Chromium the connection dropped after ~1-2s, so the UI falls back to HLS when available. The negotiated media plane is not proxied and needs same-machine reachability. The MediaMTX port collision with `live_test_relay.py` noted in `backend/app/config.py` also remains open. |
| Investigate (offline recorded-footage search) | In progress | Phase 1 (vehicle) end to end: upload → CFR-normalise → vehicle ingest → plate search (exact + fuzzy), department-scoped, audited, with an operator UI (`frontend-v2/src/views/Investigate/`) built against the redesign's certainty/token system — recordings list/upload, ingest run management, plate search results grid, and clip playback with a frame-accurate bounding-box overlay. `backend/scripts/investigate_smoke_test.py` 21/21 passing 2026-08-30; frontend walked manually end-to-end against real uploaded footage, no Playwright coverage yet. Person search by uploaded photo is now built end to end (`POST /api/investigate/search/person`): `multi-object-tracking/person_embedding.py` computes one appearance embedding per person track at ingest, and the endpoint returns department-scoped candidates ranked by cosine similarity, audited as `investigation.searched`. It uses a generic pretrained backbone, not a dedicated ReID model, and returns a ranked list rather than an asserted identity — it has no automated smoke coverage and no accuracy evidence yet. "More like this" and the subject-linking UI remain unbuilt (the link endpoint exists without a UI) — see `docs/investigate-testing.md` and `docs/api.md`'s Investigate section. |
| Scale, security, and cost narrative | Not started | - |
| Submission package | Not started | - |

Allowed states: `Not started`, `In progress`, `Blocked`, `Ready for review`, `Done`.

## Known risks

| Risk | Impact | Immediate mitigation |
|---|---|---|
| Very short delivery window | High | Build the vertical slice before parallel feature work. |
| Sandbox access or credentials unavailable | High | Confirm access immediately; maintain a local protocol-compatible test source. |
| Mixed codecs, resolutions, and variable timing | High | Treat the catalogue as the contract, force RTSP/TCP, use PTS, and test reconnects. |
| Duplicate stream consumers exhaust gateway/network capacity | High | Centralise capture ownership per active camera, cap concurrency, and measure per-client bandwidth. |
| ANPR accuracy degrades on real CCTV | High | Establish a measurable baseline early and retain confidence/evidence for review. |
| Cross-camera identity errors | High | Use plate-normalisation, confidence thresholds, deduplication, and auditable observations. |
| Scope expands toward a full statewide VMS | High | Keep Phase 1 metadata-first and document the scale path instead of overbuilding it. |
| Context diverges across machines or agents | Medium | Use repository state, ADRs, requirement IDs, and handoff packets; never rely on chat alone. |
| Secrets or government endpoints enter Git | High | Use environment variables and secret stores; redact logs and never commit credentials. |
| Demo authentication is not production identity | High | Keep credentials outside Git and the demo local/trusted; add authorised SSO/OIDC, MFA, rate limiting, CSRF hardening, and central secrets before hosting. Raw camera endpoints are no longer returned by camera responses. |
| Status claims outrun reproducible evidence | High | Keep requirements at `In progress` until dated evidence, applicable human review, and any external service proof exist; do not treat a configured archive path as proof of WORM retention. |

## Next checkpoint

C1 is partially closed: ADR 0001, the stack decision, and a safe synthetic fixture are merged, while eligibility/access, contract freeze, and team ownership remain open. The immediate implementation target is C3 - complete mandatory Model 1 gaps and create a reproducible evidence packet. Exit criteria are in [docs/checkpoints.md](docs/checkpoints.md).
