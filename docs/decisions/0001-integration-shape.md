# ADR 0001: Registry/GIS control plane plus direct feed integration, behind adapter boundaries

Status: Accepted

Date: 2026-08-28; accepted 2026-08-30

Owners: Team

## Context

> **Re-scope note (2026-09-12).** This ADR was written for a different programme, whose vocabulary of "Model 1" (registry/GIS) and "Model 2" (direct feed integration) does not exist in SIH26127. The *decision* it records is unchanged and still correct; only its naming has been updated. See [ADR 0004](0004-sih26127-rescope.md).

A central camera registry with GIS is the foundation everything else needs: trajectory reconstruction and traffic analytics are both meaningless without knowing where each camera is. The team is small and the window is short. Camera sources expose direct RTSP/WebRTC/HLS endpoints through a catalogue. A complete central VMS or general-purpose multi-vendor federation product would create substantial infrastructure scope before the ANPR, alerting, trajectory, and demonstration paths are proven.

## Decision

Implement:

- a **camera registry and GIS control plane** as the foundation;
- **direct feed integration** with camera sources, rather than an intermediate federation layer;
- a canonical connector interface separating source discovery and stream access from analytics;
- metadata-first upstream processing with selective evidence retention; and
- a documented evolution path to federation middleware and regional/edge deployment.

Use a modular monolith for registry, watchlists, alerts, trajectories, RBAC, and API, with independently scalable media/ANPR workers.

## Consequences

Positive:

- fastest route to a working end-to-end feed;
- the registry/GIS foundation that trajectory and analytics both depend on exists first;
- fewer distributed-system failure modes in the demonstration;
- the connector boundary supports vendor neutrality; and
- the scale story can move inference toward regional/edge nodes without redesign.

Negative:

- no federation middleware is demonstrated;
- direct source integration logic must stay disciplined behind adapters; and
- some production VMS functions remain roadmap items.

## Alternatives considered

- **Federation middleware first:** stronger multi-vendor integration story, materially slower route to a working ANPR and trajectory demonstration.
- **A central VMS:** comprehensive, but far too broad and infrastructure-heavy for the team and window, and not what this problem statement asks for.
- **Analytics without a registry foundation:** rejected. Trajectory reconstruction plots stops on a map and traffic analytics aggregates per node; both are impossible without authoritative camera geometry.

## Validation and revisit triggers

- Catalogue/HLS consumption paths exist in merged code; prior local use was reported, but a redacted reproducible evidence packet is still required.
- The observation-to-alert-to-journey vertical slice exists in merged code.
- Core department RBAC, application-level state-change/read/denial audit, health/maintenance history, registry search/export, bulk creation, a safe metadata-only fixture, authenticated browser GIS evidence, and protocol-compatible interruption/recovery evidence are now implemented. The project owner confirms the official catalogue path is operational. Remaining registry/GIS gaps—especially provisioned database-external immutable retention and a redacted official demonstration record—remain implementation work and are not waived by this decision.
- Add a protocol-compatible connector fixture before claiming replacement without core changes.
- Revisit the integration shape if the organiser requires federation middleware, if the direct connector cannot support the supplied feeds, or if a quantified city-wide capacity model shows the current boundary cannot evolve safely.
