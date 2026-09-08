# Catalogue/onboarding recheck — 2026-08-31

Base revision: `fda8fa8` (before the documentation and external-archive-delivery
change in this branch)

## Purpose

Recheck the official catalogue/onboarding path rather than inferring success
from the implemented endpoint or from historical runs. This run uses the
configured local, authorised non-secret environment; no endpoint URL, token,
camera metadata, or feed URL is included here.

## Command

```bash
cd backend
.venv/bin/python scripts/smoke_test.py --base-url http://127.0.0.1:8123
```

The backend had already been migrated to head and started locally with the same
environment.

## Result

- 11 of 11 executed non-ML checks passed.
- Manual onboarding, CSV create/update/error handling, and their audit path
  passed.
- `POST /api/sync` was attempted by the smoke suite and skipped because the
  configured official catalogue returned upstream HTTP 502.

This is **not** evidence of a successful official catalogue import. It confirms
that the application handles the upstream failure honestly and that the other
onboarding paths remain working. Re-run after the catalogue service recovers
and replace this with a redacted successful-sync result before claiming that
acceptance check.
