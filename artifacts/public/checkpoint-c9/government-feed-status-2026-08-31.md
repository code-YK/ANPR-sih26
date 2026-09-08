# C9 — Section 5 live-test Phase 9: official government-feed rehearsal — status as of 2026-08-31

## Status: blocked on upstream sandbox availability, not on this project's own readiness

The official sandbox catalogue (`SANDBOX_CATALOGUE_URL`) has returned
`502 Bad Gateway` every time this project has called it today, across every
phase's smoke testing:

```
curl (this check, 2026-08-31, post-login) ->
  POST /api/sync -> HTTP 502
  {"detail":"Sandbox catalogue API unavailable: Server error '502 Bad
  Gateway' for url 'https://live.corp8.cloud/api/ingest' ..."}
```

`backend/scripts/smoke_test.py`'s "catalogue sync (idempotent)" check has
reported the identical upstream 502 on every run today (Phases 3 through
8), each logged as `SKIPPED: catalogue sync (idempotent)` rather than a
project defect — this backend's own error handling already treats an
upstream outage as a 502 pass-through with a clear message, not an opaque
500 (see `app/routers/pipeline.py`'s comment on exactly this point), so
the failure mode itself is handled correctly; the sandbox simply isn't up.

This matches the live-test plan's own explicit contingency for this exact
situation:

> If the official feed is unavailable: record the upstream failure
> honestly. Use the protocol-compatible synthetic fixture as the backup
> demonstration. Clearly label it as synthetic; do not present it as
> government-feed evidence.

## What's already done and ready to run the moment the sandbox is back

Nothing about Phase 9 requires new code. `backend/scripts/run_live_test.py`
(Phase 6) already handles both camera-id shapes:

- Fixture roles (`test-camera-a,b,c`) -- fully exercised, twice, evidence
  committed at `artifacts/public/checkpoint-c6/run-1/`.
- Real registry `camera_id`s -- the exact path Phase 9 needs. Once
  `POST /api/sync` (or the equivalent catalogue-onboarding flow) succeeds,
  the command is:

  ```
  ../.venv/bin/python scripts/run_live_test.py \
      --plate <plate supplied at runtime> \
      --camera-ids <catalogue camera_ids, comma-separated> \
      --output ../artifacts/public/checkpoint-c9/run-1
  ```

  run twice (per the plan), with `--output .../run-2` for the second pass.
  No `--camera-ids test-camera-*` prefix means the runner skips the
  synthetic-fixture lifecycle entirely and goes straight to "verify these
  real cameras exist and are reachable" (Phase 9 items 1-4 -- catalogue
  fetch/count/onboard/probe -- are handled by the existing onboarding
  and gap-analysis endpoints already exercised in every earlier phase,
  not something Phase 9 needs to build fresh).

## Backup demonstration on record (synthetic, clearly labeled)

Per the plan's own instruction, the synthetic-fixture runs already stand
as the backup demonstration -- explicitly labeled synthetic here and in
every artifact that produced them:

- `artifacts/public/checkpoint-c6/run-1/` -- full `run_live_test.py` pass,
  synthetic fixture, plate `GJ01TT9911` (fictional, composited onto a real
  vehicle stock photo -- never a real observed plate).
- `artifacts/public/checkpoint-c7/run-1/` -- reliability/performance
  rehearsal against the same synthetic fixture.

These are **not** government-feed evidence and are not presented as such
anywhere in this repository.

## Recommendation

The recommended schedule places this phase on Sep 7, with today being
Aug 31 -- there is time before the deadline to retry. Recheck sandbox
availability closer to the submission date; if it comes up, the command
above runs Phase 9 with zero additional engineering work. If it stays
down through submission, this document plus the synthetic backup evidence
already committed is the honest record the plan itself asks for.
