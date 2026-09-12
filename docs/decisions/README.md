# Architecture Decision Records

ADRs capture decisions that are expensive to rediscover or reverse. They do not restate requirements.

Statuses:

- `Proposed`
- `Accepted`
- `Superseded by ADR NNNN`
- `Rejected`

Create records as `NNNN-short-title.md` with:

```text
# ADR NNNN: Title
Status:
Date:
Owners:

## Context
## Decision
## Consequences
## Alternatives considered
## Validation / revisit trigger
```

An agent may propose an ADR. A human/team decision is required to mark a cross-cutting or hard-to-reverse ADR accepted.

## Records

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-integration-shape.md) | Registry/GIS control plane plus direct feed integration, behind adapter boundaries | Accepted |
| [0002](0002-implementation-stack.md) | Implementation stack and pinned versions | Accepted |
| [0003](0003-department-rbac.md) | Department-scoped role model | Accepted |
| [0004](0004-sih26127-rescope.md) | Re-scope the platform to SIH26127 | Accepted |
