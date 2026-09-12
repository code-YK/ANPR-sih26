# Presentation evidence map

Status: source material for the submission deck. This is slide/HLD source, **not**
a claim that all submission requirements are complete.

> **Re-scoped 2026-09-12.** This file was written for an earlier programme and
> its structure still reflects that. The *claim discipline* below is the part
> worth keeping and is unchanged. The mapping of claims to slides needs
> rebuilding around SIH26127's four expected components before the deck is
> written -- tracked as `SIH-SUB-002`. See
> [ADR 0004](decisions/0004-sih26127-rescope.md).

## One-sentence architecture summary

Sentinel is a **camera registry, GIS, health, and governance control plane**
plus **read-only direct processing of authorised feeds**. It centralises
metadata and workflow, never all source video.

The decision is accepted in [ADR 0001](decisions/0001-integration-shape.md).
The control plane is the FastAPI/PostgreSQL/PostGIS application and the served
React console; the media/ANPR workers remain independent processes behind the
source connector boundary. See [architecture.md](architecture.md) and
[hld.md](hld.md).

## What the deck must cover for SIH26127

One section per expected component, each stating what is demonstrated and what
is not:

| # | Component | Honest headline |
|---|---|---|
| 1 | High-Precision OCR Module | Works on real footage at high per-read confidence. **Accuracy against ground truth is unmeasured** -- do not put a >90% number on a slide |
| 2 | Trajectory Reconstruction Engine | Fully demonstrable end to end: query, chronological stops, route on map, export |
| 3 | City Traffic Analytics Dashboard | Built but **unmerged**; heatmap layer not built. Present only what is on `main` at deck time |
| 4 | Alert System | Blacklist alerting fully demonstrable. **Route-anomaly alerts are not yet wired into the alert queue** |

Anything demonstrated under government mode must be labelled as **recorded
government footage replayed through the real pipeline** -- a genuine
demonstration of the pipeline, not of live city-scale deployment.

## Claim discipline for the presentation

| Label | Meaning in a slide/demo |
|---|---|
| **Built + verified** | Merged code has current, reproducible synthetic evidence. |
| **Built; live evidence pending** | Code exists but must not be presented as a completed government-feed result. |
| **Proposed city-wide evolution** | HLD direction only; not a Phase 1 implementation claim. |

Never show a synthetic fixture as a government camera, a planning radius as a
measured field of view, or a prior local observation as a reproducible live
ANPR result. Do not display endpoints, credentials, footage, or observed
identifiers.

## registry/GIS requirement-to-evidence map

| Requirement | Presentation claim | Evidence / honest boundary |
|---|---|---|
| `SIH-M1-001` | Mandatory registry/GIS is combined with direct feed integration, rather than replaced by it. | **Built + verified architecture decision.** ADR 0001 selects the combination; this document is the presentation mapping. |
| `SIH-M1-002` | One governed registry holds camera metadata, ownership, department, location, type, health, and storage-related fields. | **Built + synthetic verified.** PostGIS schema/API and five safe fixture records; second-machine completion is project-owner confirmed. |
| `SIH-M1-003` | Operators can manually add cameras, bulk CSV-create/update records, or synchronise the authorised catalogue. | **Built + verified operational path.** Manual/CSV verification is committed and the project owner confirms official catalogue sync is working. The 2026-08-31 upstream-502 record is a transient historical observation; include a redacted successful run in the final evidence packet. |
| `SIH-M1-004` | The GIS map supports department/type/ANPR/live filters, health markers, unplaced assets, and clearly-labelled planning rings. | **Built + browser verified.** Authenticated evidence is recorded; the planning rings remain indicative, not measured fields of view. |
| `SIH-M1-005` | Health reasons/history and maintenance lifecycle give operators visible failure context. | **Built + synthetic/protocol-fixture verified** for offline/lifecycle/role-boundary and interruption/recovery cases. Successful official-live evidence remains pending. |
| `SIH-M1-006` | JSON, HTML, and PDF reports identify capability, coverage, unplaced, and health gaps. | **Built + synthetic verified** in [gap-analysis-synthetic-2026-08-31.md](../artifacts/public/checkpoint-c3/gap-analysis-synthetic-2026-08-31.md). It is not city-wide coverage evidence. |
| `SIH-M1-007` | Role-scoped search/export and access/change audit protect registry governance. | **Built + synthetic verified.** Includes read/denial audit, application-role audit-row immutability, SHA-256 archive export, and explicit delivery to a configured external mount. A provisioned WORM/object-lock destination and database-superuser boundary remain open. |
| `SIH-M1-008` | Registry/control-plane metadata stays separate from media processing and source-video storage. | **Built + verified architecture.** Raw source endpoints remain server-side and Phase 1 does not centrally record source video. |

## direct feed integration relationship and demonstration path

| Layer | Role | Current presentation claim |
|---|---|---|
| Source connector | Reads the catalogue and authorised streams; does not publish or control cameras. | **Built; live evidence pending.** First connector targets the Sentinel catalogue. |
| Media/ANPR worker | Consumes a selected feed, preserves source-time/provenance policy, and posts observations. | **Built; reproducible redacted live evidence pending.** |
| Watchlist/alert workflow | Normalises plates, matches active representative entries, deduplicates alerts, and records lifecycle audit. | **Built + synthetic verified.** |
| Journey view | Orders observations by event/source time and enriches them with registry coordinates. | **Built; multi-camera evaluator fixture and evidence references remain pending.** |
| City-wide evolution | Regional connectors/workers feed a central metadata, alert, and registry layer. | **Proposed city-wide evolution.** Capacity, cost, HA/DR, and deployment evidence remain open. |

## Suggested presentation flow

1. Problem: fragmented departmental CCTV estates need governance without
   replacing existing VMS/storage.
2. Model choice: registry/GIS control plane + direct feed integration read-only direct integration.
3. Workflow: catalogue/registry → authorised worker → observation → watchlist
   decision → deduplicated alert → journey/GIS.
4. Demonstrate only verified synthetic registry, health, report, RBAC, and
   audit/archive flows until authorised live evidence is recorded.
5. State the remaining official-live, WORM-retention, scale, and ML
   review gaps plainly.

## Review checklist

- [ ] A teammate confirms each slide claim maps to this document or a linked
  requirement-ledger artifact.
- [x] The project owner confirms teammate second-machine completion; the
  attestation is linked from the requirements ledger.
- [ ] The final presentation distinguishes built, synthetic, live, and proposed
  content using the labels above.
- [ ] The final HLD adds the required scale/cost, security, deployment, and
  city-wide evolution evidence before claiming submission readiness.
