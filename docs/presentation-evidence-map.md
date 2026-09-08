# Model 1 + Model 2 presentation evidence map

Status: source material for an in-progress local presentation deck. This is a slide/HLD source, not a claim that
all submission requirements are complete.

## One-sentence model choice

Sentinel uses **Model 1 as the department-scoped registry, GIS, health, and
governance control plane**, plus **Model 2 for read-only direct processing of
authorised feeds**; it centralises metadata and workflow, not all source video.

The decision is accepted in [ADR 0001](decisions/0001-proposed-integration-shape.md).
The control plane is the FastAPI/PostgreSQL/PostGIS application and active React
console; the media/ANPR workers remain independent processes behind the source
connector boundary. See [architecture.md](architecture.md).

## Claim discipline for the presentation

| Label | Meaning in a slide/demo |
|---|---|
| **Built + verified** | Merged code has current, reproducible synthetic evidence. |
| **Built; live evidence pending** | Code exists but must not be presented as a completed government-feed result. |
| **Proposed statewide evolution** | HLD direction only; not a Phase 1 implementation claim. |

Never show a synthetic fixture as a government camera, a planning radius as a
measured field of view, or a prior local observation as a reproducible live
ANPR result. Do not display endpoints, credentials, footage, or observed
identifiers.

## Model 1 requirement-to-evidence map

| Requirement | Presentation claim | Evidence / honest boundary |
|---|---|---|
| `GOV-M1-001` | Mandatory Model 1 is combined with Model 2, rather than replaced by it. | **Built + verified architecture decision.** ADR 0001 selects the combination; this document is the presentation mapping. |
| `GOV-M1-002` | One governed registry holds camera metadata, ownership, department, location, type, health, and storage-related fields. | **Built + synthetic verified.** PostGIS schema/API and five safe fixture records; second-machine completion is project-owner confirmed. |
| `GOV-M1-003` | Operators can manually add cameras, bulk CSV-create/update records, or synchronise the authorised catalogue. | **Built + verified operational path.** Manual/CSV verification is committed and the project owner confirms official catalogue sync is working. The 2026-08-31 upstream-502 record is a transient historical observation; include a redacted successful run in the final evidence packet. |
| `GOV-M1-004` | The GIS map supports department/type/ANPR/live filters, health markers, unplaced assets, and clearly-labelled planning rings. | **Built + browser verified.** Authenticated evidence is recorded; the planning rings remain indicative, not measured fields of view. |
| `GOV-M1-005` | Health reasons/history and maintenance lifecycle give operators visible failure context. | **Built + synthetic/protocol-fixture verified** for offline/lifecycle/role-boundary and interruption/recovery cases. Successful official-live evidence remains pending. |
| `GOV-M1-006` | JSON, HTML, and PDF reports identify capability, coverage, unplaced, and health gaps. | **Built + synthetic verified** in [gap-analysis-synthetic-2026-08-31.md](../artifacts/public/checkpoint-c3/gap-analysis-synthetic-2026-08-31.md). It is not statewide coverage evidence. |
| `GOV-M1-007` | Role-scoped search/export and access/change audit protect registry governance. | **Built + synthetic verified.** Includes read/denial audit, application-role audit-row immutability, SHA-256 archive export, and explicit delivery to a configured external mount. A provisioned WORM/object-lock destination and database-superuser boundary remain open. |
| `GOV-M1-008` | Registry/control-plane metadata stays separate from media processing and source-video storage. | **Built + verified architecture.** Raw source endpoints remain server-side and Phase 1 does not centrally record source video. |

## Model 2 relationship and demonstration path

| Layer | Role | Current presentation claim |
|---|---|---|
| Source connector | Reads the catalogue and authorised streams; does not publish or control cameras. | **Built; live evidence pending.** First connector targets the Sentinel catalogue. |
| Media/ANPR worker | Consumes a selected feed, preserves source-time/provenance policy, and posts observations. | **Built; reproducible redacted live evidence pending.** |
| Watchlist/alert workflow | Normalises plates, matches active representative entries, deduplicates alerts, and records lifecycle audit. | **Built + synthetic verified.** |
| Journey view | Orders observations by event/source time and enriches them with registry coordinates. | **Built; multi-camera evaluator fixture and evidence references remain pending.** |
| Statewide evolution | Regional connectors/workers feed a central metadata, alert, and registry layer. | **Proposed statewide evolution.** Capacity, cost, HA/DR, and deployment evidence remain open. |

## Suggested presentation flow

1. Problem: fragmented departmental CCTV estates need governance without
   replacing existing VMS/storage.
2. Model choice: Model 1 control plane + Model 2 read-only direct integration.
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
  statewide evolution evidence before claiming submission readiness.
