# C8 — Section 5 live-test Phase 8: supporting verification sweep — 2026-08-31

Pre-Phase-9 checklist from the live-test plan, each item run for real against
the current `main` (through `3f45b2b`, the Phase 7 commit).

## `rbac_smoke_test.py` reads `response["events"]` from the paginated audit endpoint

Already correct in the current code
(`scripts/rbac_smoke_test.py:242-274`, e.g.
`audit_page["events"][:new_event_count]`) — nothing to fix. Confirmed by
inspection and by the test passing below.

## Rerun general smoke tests

```
backend/scripts/smoke_test.py: 11/11 passed (1 skipped: catalogue sync,
sandbox catalogue API unavailable — an external dependency, not a defect)
```

## Rerun RBAC tests

```
backend/scripts/rbac_smoke_test.py:
PASS: authentication, approvals, home/cross-department scope, camera
maintenance controls, read/denial audit, scoped exports, and
database-immutable audit
```

## Verify evidence access restrictions

Covered directly by `backend/scripts/journey_export_test.py`'s fourth case
(re-run clean, 4/4 passing): a real department-scoped account, created
through the actual registration/approval flow, sees a cross-department
sighting counted as a restricted stop but not listed, and a direct
`GET /api/sightings/{id}/evidence` for that sighting's id returns 403 for
that account. Not a mock — a real second account, real login, real request.

## Run frontend lint/build

```
npm run lint  -> exit 0 (only pre-existing warnings: react-hooks
                 exhaustive-deps, set-state-in-effect, unused catch params
                 — no errors)
npm run build -> succeeds (one non-blocking chunk-size advisory, no errors)
```

## Run migrations from a clean database

Created a throwaway database (`sentinel_migration_check`), ran
`alembic upgrade head` against it from empty, and dropped it afterward:

```
Running upgrade  -> 202608282221, initial schema: cameras + sightings
... (13 migrations total) ...
Running upgrade 202608311800 -> 202608311900, evidence fields on sightings
```

All 13 migrations applied cleanly in order with no manual intervention;
`alembic current` reported head; `\dt` showed all 21 expected tables
(including `spatial_ref_sys`/PostGIS, created by the initial migration
itself, not assumed pre-installed).

## Verify no secrets, observed plates, or unauthorised footage in artifacts

- Secret-pattern scan (AWS keys, PEM private keys, common API-token
  prefixes, and a broader `password\s*[:=]` sweep) across every
  git-tracked file: no matches other than the login form's own
  `type="password"` input field.
- `backend/.env` (the only file with real credentials) is gitignored and
  was never committed; `backend/.env.example` holds only placeholder
  values (`replace-with-a-long-demo-secret`, `admin@example.invalid`).
- Every tracked image (`git ls-files | grep -iE '\.(jpg|jpeg|png|mp4)$'`)
  is one of the three Phase 7 browser screenshots — UI chrome only, no
  video frame content rendered (a known headless-Chromium capture
  limitation, not a leak).
- The plate appearing throughout the committed evidence bundles
  (`GJ01TT9911`) is the Section 5 live-test fixture's own deliberately
  synthetic plate, composited onto a real vehicle stock photo by
  `build_live_test_fixture.py` specifically so it's safe to generate,
  observe, and publish — not a plate observed from real traffic.
  `backend/evidence/` (real per-sighting crops) and `/fixtures/live-test/`
  (the composited stills/clips) are both gitignored and neither has ever
  been committed.

## Result

All six items verified for real; no defects found requiring a code
change in this phase.
