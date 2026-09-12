# Handoff: DOC-M1-STATUS-STACK

> **Historical handoff.** Recorded under an earlier programme's framing and
> requirement IDs. Left unedited as a record of that work. See
> [ADR 0004](../decisions/0004-sih26127-rescope.md).

Status: Superseded after integration into `main` in commit `f3108eb`.

- Branch: `docs/module1-status-stack`
- Base commit: `3a28d3a`
- Last updated: 2026-08-30
- Previous owner/agent: Codex
- Next owner/agent: Team reviewer

## Objective and requirement IDs

Reconcile Module 1 documentation with merged implementation reality, record the accepted Phase 1 architecture and stack, remove unsupported completion claims, and make local setup/security guidance reproducible without running the ML models.

Primary traceability: `GOV-M1-001` through `GOV-M1-008`, with related corrections to selected Model 2, functional, ingestion, security, and reproducibility rows.

## Completed

- Accepted ADR 0001 after reconciling it with the implemented architecture.
- Added accepted ADR 0002 for the Phase 1 implementation stack and explicit ML/native locking gap.
- Reclassified Module 1 status from complete to core implementation in progress.
- Corrected stale README, project-state, architecture, API, checkpoint, build-spec, UI-spec, and requirement claims.
- Added active React setup/build documentation and clarified the smoke test's real scope.
- Removed the tracked sandbox host and previously observed vehicle identifiers from examples.
- Made sandbox endpoint defaults non-routable/config-driven and passed backend configuration to worker subprocesses.
- Redacted stream endpoints from probe/capture and worker diagnostics.
- Removed clip-recording commands from the sandbox helper; frame capture remains exceptional and separately authorised.

## Changed files

See `git diff --stat`. Durable status/decision files are `PROJECT_STATE.md`, `docs/requirements.md`, `docs/architecture.md`, `docs/api.md`, `docs/checkpoints.md`, ADR 0001, and ADR 0002. Setup guidance is in `README.md`, `backend/README.md`, and `frontend-v2/README.md`. The remaining source edits are the narrow security/configuration companions described above.

## Verification performed

| Command | Result |
|---|---|
| `git pull --ff-only` on `main` | Passed; already up to date before branch creation. |
| `npm ci` in `frontend-v2/` | Passed; 75 packages installed, 0 reported vulnerabilities. |
| `npm run lint` in `frontend-v2/` | Exit 0; existing React/Oxlint warnings remain. |
| `npm run build` in `frontend-v2/` | Passed; Vite warned that the main JavaScript chunk exceeds 500 kB. |
| Python AST parse across `backend/`, `multi-object-tracking/`, and `sandbox-test/` | Passed for 48 Python files. |
| `python3 sandbox-test/sentinel_client.py --help` | Not run successfully in the host Python: `cv2` is not installed. Syntax parsing passed. |
| `git diff --check` | Passed. |

## Current failure or blocker

The full backend/API smoke run was not attempted because this host lacks the documented Python 3.13 environment, project `.venv`, and a verified PostgreSQL 17/PostGIS service. The live sandbox and ML/YOLO paths were deliberately not run. Therefore no Module 1 checkpoint was promoted to `Done`.

## Next smallest action

Review this diff, then reproduce backend setup and the non-ML smoke checks on the accepted Python/PostgreSQL toolchain using a test database and redacted results artifact. After that, implement the first mandatory Module 1 gap: authentication/RBAC plus immutable audit events, or split it into an accepted smaller task.

## Decisions made

- [ADR 0001](../decisions/0001-integration-shape.md): accepted Model 1 + direct Model 2 Phase 1 shape.
- [ADR 0002](../decisions/0002-implementation-stack.md): accepted Phase 1 stack and deferred distributed infrastructure.

## Decisions still open

- Tested lock/environment manifest for the ML workers and native demo-machine dependencies.
- Eligibility/portal access ownership, team work-lane reviewers, and source-code licence.
- Target `/api/v1` migration/versioning plan.

## Local state to recreate

`npm ci` created ignored `frontend-v2/node_modules/`; `npm run build` created ignored `frontend-v2/dist/`. No endpoint values, credentials, live data, or ML model artifacts were created.

## Evidence

This branch contains documentation and static/build verification only. It intentionally does not contain a live-feed, ML-accuracy, database smoke, screenshot, or checkpoint results artifact.
