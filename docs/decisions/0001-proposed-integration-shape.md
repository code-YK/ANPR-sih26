# ADR 0001: Model 1 plus direct sandbox integration with adapter boundaries

Status: Accepted

Date: 2026-08-28; accepted 2026-08-30

Owners: Team

## Context

Model 1 is mandatory. The team has three people and roughly ten days before submission. The Phase 1 sandbox exposes direct RTSP/WebRTC/HLS endpoints through a catalogue. A complete central VMS or general-purpose multi-vendor federation product would create substantial infrastructure scope before the mandatory ANPR, alerting, journey, and demo paths are proven.

## Decision

Implement:

- Model 1 registry and GIS as the control-plane foundation;
- Model 2-style direct integration for the Sentinel sandbox;
- a canonical connector interface separating source discovery/stream access from analytics;
- metadata-first upstream processing and selective evidence retention; and
- a documented evolution path to Model 3-style federation and regional/edge deployment.

Use a modular monolith for registry, watchlists, alerts, journeys, RBAC, and API, with independently scalable media/ANPR workers.

## Consequences

Positive:

- fastest route to the official test feed;
- clear Model 1 compliance;
- fewer distributed-system failure modes in the demo;
- connector boundary supports vendor neutrality; and
- scale story can move inference toward regional/edge nodes.

Negative:

- Phase 1 will not demonstrate a full federation middleware;
- direct source integration logic must remain disciplined behind adapters; and
- some production VMS functions remain roadmap items.

## Alternatives considered

- Model 3 federation first: stronger enterprise integration story, slower mandatory demo path.
- Model 4 central VMS: comprehensive but too broad and infrastructure-heavy for the current team/window.
- Custom architecture without Model 2 framing: permitted, but harder to communicate and justify succinctly.

## Validation and revisit triggers

- Catalogue/HLS consumption paths exist in merged code; prior local use was reported, but a redacted reproducible evidence packet is still required.
- The observation-to-alert-to-journey vertical slice exists in merged code.
- Core department RBAC, application-level state-change/read/denial audit, health/maintenance history, registry search/export, bulk creation, a safe metadata-only fixture, authenticated browser GIS evidence, and protocol-compatible interruption/recovery evidence are now implemented. The project owner confirms the official catalogue path is operational. Mandatory Model 1 gaps—especially provisioned database-external immutable retention and a redacted official demonstration record—remain implementation work and are not waived by this decision.
- Add a protocol-compatible connector fixture before claiming replacement without core changes.
- Revisit the integration shape if the organiser requires federation middleware in Phase 1, if the direct connector cannot support the official feeds, or if the quantified statewide plan shows that the current boundary cannot evolve safely.
