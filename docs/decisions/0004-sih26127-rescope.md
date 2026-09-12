# ADR 0004: Re-scope the platform to SIH26127

Status: Accepted

Date: 2026-09-12

Owners: Team

## Context

This codebase was built for a Gujarat CCTV integration challenge. That programme framed its problem around four prescribed integration architectures it called **Model 1** (central camera registry and GIS), **Model 2** (direct feed integration), **Model 3** (federation middleware), and **Model 4** (a central VMS), and required an approximately 80,000-camera statewide narrative, integration-readiness with state systems such as VAHAN and eGujCop, and an official sandbox camera catalogue.

The team is now entering **Smart India Hackathon 2026, problem statement SIH26127**, proposed by **Bharat Electronics Limited**: *City-Wide AI Engine for Multi-Camera ANPR Trajectory Tracking and Urban Traffic Analytics*, idea submission due **2026-09-30**.

The two are related but not the same problem:

- SIH26127 has **no model taxonomy**. Nothing in it corresponds to "Model 1" or "Model 2".
- SIH26127 names **three core functionalities** and **four expected components**, and is judged on those.
- SIH26127 puts **OCR accuracy (>90 %)**, **single-plate trajectory reconstruction**, and **macro traffic analytics** at the centre. The earlier programme treated ANPR as one analytic among many and put registry/GIS integration at the centre.
- SIH26127 supplies **no dataset and no sandbox**. The earlier programme's catalogue and feeds were the integration contract.

Leaving the documentation as it was would have meant a repository whose README, requirement IDs, and status tables all described a different competition — actively misleading to a new teammate and useless as submission material.

## Decision

Re-scope the documentation, requirement ledger, and framing to SIH26127, while keeping the engineering.

Specifically:

1. **Restructure the requirement ledger around the four expected components.** New ID prefixes `SIH-OCR`, `SIH-TRAJ`, `SIH-ANLY`, `SIH-ALERT`, plus `SIH-PLAT` for the platform foundations they stand on, `SIH-NFR`, and `SIH-SUB`. The old `GOV-*` IDs are retired.

2. **Remove the Model 1/2/3/4 vocabulary from all current documentation.** Where prior work is still the evidence for a requirement, describe it by what it *is* — "camera registry and GIS control plane", "direct feed integration" — not by a model number. Rename `docs/model1-build-spec.md`, `model2-build-spec.md`, and `model2-ui-build-spec.md` to `registry-gis-build-spec.md`, `anpr-pipeline-build-spec.md`, and `operator-console-build-spec.md`.

3. **Keep the code and the architecture.** The registry, PostGIS layer, RBAC, audit trail, watchlist, alerting, media ingestion, and operator console are all directly reusable and map cleanly onto SIH26127's platform needs. Nothing is deleted to make the rebrand look tidier.

4. **Leave `artifacts/` untouched.** Those are dated evidence packets recording what was verified, on what date, under the earlier programme's framing. Rewriting historical evidence to match a new narrative would be dishonest. They stay as-is, and their model-era vocabulary stands as a record of when they were produced.

5. **Retain prior-programme material as clearly-labelled reference**, not as deliverables: `sentinel-playbook.md` and `Sentinel-Gujarat-Solution-Presentation*.pptx`.

6. **Re-centre the honest gaps on what SIH26127 actually judges.** The headline gap is no longer "official sandbox demonstration evidence"; it is **measured OCR accuracy against ground truth** (`SIH-OCR-002`), because >90 % is the problem statement's own stated bar and this repository cannot currently evidence it.

## Consequences

Positive:

- The documentation describes the competition the team is actually entering.
- The ledger is structured the way the solution will be judged, so a gap in the ledger is a gap in the submission.
- Substantial prior engineering carries over with its evidence intact.
- The re-scope forced an honest re-read of what is proven: it surfaced that the >90 % accuracy claim has never been measured, and that the traffic-analytics component is unmerged.

Negative:

- Requirement IDs referenced in older commit messages, handoffs, and `artifacts/` no longer resolve against the current ledger. This ADR is the mapping of record.
- Some inherited requirements no longer have a home. Statewide 80,000-camera sizing, VAHAN/eGujCop integration-readiness, and sandbox protocol conformance are **not** SIH26127 requirements. The generic engineering underneath them (bounded reconnect, PTS-anchored timing, mixed-codec handling) is retained under `SIH-PLAT-*`; the programme-specific obligations are dropped.
- The committed presentation decks are now invalid and must be replaced.

## Alternatives considered

- **Start a clean repository.** Rejected — it would discard a working vertical slice, a verified GPU pipeline, RBAC, audit, and GIS for a cosmetic gain, with under three weeks to the deadline.
- **Keep the `GOV-*` IDs and add SIH IDs alongside.** Rejected — two parallel ledgers for one codebase invites drift and makes "is this done?" ambiguous.
- **Keep the Model vocabulary as internal shorthand.** Rejected — it is shorthand for a taxonomy that does not exist in this problem statement, so it would confuse every reader who had not worked on the previous programme.

## Validation / revisit trigger

- Every requirement in `docs/requirements.md` traces to a sentence in the SIH26127 problem statement or is explicitly marked `Selected` as a team decision.
- No current documentation file references Model 1/2/3/4 except this ADR and `PROJECT_STATE.md`'s inherited-work note, both of which do so to explain the change.
- Revisit if BEL or the organisers publish additional requirements, a dataset, or an evaluation rubric that contradicts the structure adopted here.
