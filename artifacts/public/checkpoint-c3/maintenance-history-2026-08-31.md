# C3 maintenance history verification — 2026-08-31

## Scope

`GOV-M1-005` maintenance-status evidence on the local, migrated application.
No live camera feed, source endpoint, credential, or ML worker was used.

## Commands

```bash
cd backend
.venv/bin/alembic upgrade head
DYLD_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/uvicorn app.main:app --port 8014
.venv/bin/python scripts/smoke_test.py --base-url http://127.0.0.1:8014
.venv/bin/python scripts/rbac_smoke_test.py --base-url http://127.0.0.1:8014
```

## Result

- Migration `202608311700` applied from `202608311600`.
- General smoke: 11/11 passed; catalogue sync skipped because its upstream
  returned HTTP 502.
- The deterministic metadata-only camera probe recorded an `offline` health
  observation and reason, then the suite opened, progressed, and resolved a
  maintenance work order. The returned lifecycle contained `created` and two
  `status_changed` events; the resolved record rejected a later update with
  HTTP 409.
- RBAC smoke passed: a viewer could read authorised maintenance history but
  received HTTP 403 for creation; the camera's home-department admin created
  and resolved the work order. Creation and update audit events were present.

## Remaining evidence gap

This is a synthetic, metadata-only offline transition. It is not evidence of
a live sandbox-feed health transition or a teammate reproduction.
