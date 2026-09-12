# Source Register

Last verified: 2026-09-12

Where every requirement in [requirements.md](requirements.md) comes from, and what remains ambiguous.

## Authority order

1. The official SIH 2026 problem-statement listing for **SIH26127**.
2. The supplied BEL requirements document.
3. Official organiser announcements or direct written clarification.
4. Accepted repository ADRs and merged contracts.
5. Chat history, agent memory, and unmerged local notes — lowest.

When a lower source conflicts with a higher one, quote the conflict briefly, follow the higher source, and record the ambiguity in the table at the bottom of this file.

## Official sources

| Code | Source | Scope | Verification |
|---|---|---|---|
| `PS` | SIH 2026 problem-statement listing, SIH26127 (`sih.gov.in/sih2026PS`) | Background, the three core functionalities, the four expected components, category, theme, deadline | Reviewed 2026-09-12 |
| `BEL` | Supplied BEL requirements document (`requirements from sih 127.pdf`) | Same problem statement in document form; the authoritative wording the team was given | Reviewed 2026-09-12 |

### Recorded problem-statement metadata

| Field | Value |
|---|---|
| S.No. | 127 |
| PS number | SIH26127 |
| Organisation | Bharat Electronics Limited |
| Department | Bharat Electronics Limited |
| Category | Software |
| Theme | Transportation & Logistics |
| Idea submission deadline | 2026-09-30 |
| Dataset link | **N/A — none supplied** |
| Contact info | N/A |
| YouTube link | N/A |

The listing carries a `CC-BY-4.0` licence note and was scraped 2026-08-21.

## What the problem statement actually requires

Quoted so requirement rows can be traced to a sentence rather than to an interpretation.

**Three core functionalities:**

1. *"a High-Accuracy ANPR and OCR Engine, which utilizes an advanced Optical Character Recognition model capable of achieving greater than 90% accuracy across diverse real-world conditions such as varying lighting, poor weather, angled shots, motion blur, and dirty or damaged license plates"* → `SIH-OCR-*`
2. *"a Single Plate Trajectory Tracking module to build a spatial-temporal tracking system capable of reconstructing the complete travel trajectory of any specific vehicle plate across the entire city network… mapping a vehicle's movement history, timestamps, direction, and route on a GIS map"* → `SIH-TRAJ-*`
3. *"Macro Traffic Flow and Movement Analytics… measuring traffic density, identifying origin-destination patterns, detecting congestion bottlenecks, and providing real-time heatmaps of city traffic movement"* → `SIH-ANLY-*`

**Four expected components:**

1. *"a High-Precision OCR Module powered by a deep-learning model exceeding 90% recognition accuracy for license plates in multi-lane traffic streams"* → `SIH-OCR-*`
2. *"a Trajectory Reconstruction Engine providing a query-based tracking interface that plots a vehicle's historical path chronologically across the city map with accurate timestamps and camera locations"* → `SIH-TRAJ-*`
3. *"a City Traffic Analytics Dashboard to serve as a centralized, GIS-integrated web platform displaying heatmaps, average vehicle speeds, route densities, and traffic flow trends across all camera nodes"* → `SIH-ANLY-*`
4. *"an Alert System capable of flagging blacklisted vehicles and suspicious route anomalies in real time"* → `SIH-ALERT-*`

Requirements prefixed `SIH-PLAT`, `SIH-NFR`, and `SIH-SUB` are **derived**, not quoted. They cover what a *"scalable, enterprise-grade software platform"* processing *"multi-camera feeds across a city-wide ANPR network"* must have in order for the four components to exist at all. Each is marked `Mandatory` where the problem statement implies it and `Selected` where it is a team choice.

## Retired sources

This repository was previously built for a Gujarat CCTV integration challenge. Those sources — its problem page, integrator resource guide, FAQ, phases, and participant portal — are **no longer authoritative** and have been removed from the authority order. See [ADR 0004](decisions/0004-sih26127-rescope.md).

Prior-programme material retained in the repository for reference only, and not as SIH26127 deliverables:

| File | Status |
|---|---|
| `sentinel-playbook.md` | Prior-programme secondary summary |
| `Sentinel-Gujarat-Solution-Presentation*.pptx` | Prior-programme decks; **must be replaced** for this submission (`SIH-SUB-002`) |
| `artifacts/` | Dated evidence packets. Left unedited on purpose — they record what was verified and when, under the framing of the time |

## Known ambiguities

| # | Ambiguity | Current handling |
|---|---|---|
| 1 | **No dataset is supplied.** The listing records `Dataset Link: N/A`, so there is no organiser-provided footage, camera catalogue, or ground truth | The team supplies its own: recorded government feeds for demonstration (government mode) and a synthetic fixture for rehearsal. **This is why `SIH-OCR-002` cannot currently be evidenced** — measuring >90 % accuracy needs labelled ground truth nobody has provided |
| 2 | **">90 % accuracy" is not defined.** Character-level or plate-level? Over what distribution of the listed adverse conditions? With what confidence threshold? | Treated as **plate-level exact match** over a set deliberately balanced across the five named conditions. Stated explicitly whenever a figure is eventually published, so the basis is never ambiguous |
| 3 | **"Average vehicle speeds" is listed but cameras are uncalibrated** in any realistic deployment | Corridor speed is published as a straight-line **lower bound** between two `exact`-geocoded cameras, never as a speed *at* a camera, and never as a speeding finding. The limitation is stated in the API, the HLD, and `SIH-ANLY-006` |
| 4 | **"Real-time" is unquantified** for both heatmaps and alerts | Alert visibility is targeted within a few seconds of a confirmed observation; analytics windows are bounded and labelled with their own recency. No figure is claimed without measurement |
| 5 | **"Suspicious route anomalies" is not enumerated** | Interpreted as dwell, looping, and implausible transit — the three that are derivable from plate observations without calibration. Recorded under `SIH-ALERT-006` |
| 6 | **Scale is "city-wide" but unquantified** — no camera count is given | The architecture is metadata-first and partitions by zone so the count is not load-bearing on the design. A numbers-backed capacity model is `SIH-PLAT-010`, still unwritten |

Raise a new row here rather than resolving an ambiguity silently in code.
