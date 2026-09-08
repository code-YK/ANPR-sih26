# Contributing

## Branch model

`main` is the only long-lived branch. Use short-lived branches:

- `feat/<outcome>` for product work
- `fix/<defect>` for corrections
- `docs/<artifact>` for documentation
- `chore/<maintenance>` for tooling and repository maintenance
- `spike/<question>` for time-boxed experiments that may be discarded

Keep branches small enough to review quickly. Rebase or merge the latest `main` before final review according to the team's chosen Git policy.

## Issue/task contract

Every task must state:

- objective and non-goals;
- requirement IDs;
- acceptance criteria;
- dependencies and affected contracts;
- expected evidence;
- owner and reviewer.

Use [docs/task-template.md](docs/task-template.md).

## Pull requests

A PR into `main` must:

- address one coherent outcome;
- link its issue/task and requirement IDs;
- explain what changed and why;
- list verification commands and actual results;
- include screenshots, logs, API examples, or demo evidence where useful;
- call out security, privacy, performance, and migration impact;
- update documentation and traceability in the same PR; and
- preserve the shared demo.

At least one teammate should review. The author resolves review findings or records a deliberate decision before merge.

## Commit guidance

Use imperative, scoped messages such as:

```text
feat(ingest): discover streams from catalogue
fix(alerts): deduplicate repeated plate matches
docs(requirements): link GOV-DEMO-004 evidence
```

Do not commit generated media, credentials, private feed URLs, large datasets, model weights without an explicit storage decision, or machine-specific configuration.

## Stable tags

Tags identify demo-safe points, not every merge:

```text
v0.1-camera-ingestion
v0.2-alerting
v0.3-vehicle-journey
v0.9-submission-candidate
v1.0-submission
```

Create a tag only when the corresponding checkpoint exit criteria pass.
