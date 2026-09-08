# C3 database audit immutability verification — 2026-08-31

## Scope

`GOV-NFR-003` durable audit-row protection for the application database role.
Migration `202608311800` installs `trg_audit_events_append_only`, which rejects
direct `UPDATE` and `DELETE` operations on `audit_events`.

## Commands

```bash
cd backend
.venv/bin/alembic downgrade -1
.venv/bin/alembic upgrade head
.venv/bin/python scripts/rbac_smoke_test.py --base-url http://127.0.0.1:8017
```

## Result

The migration downgrade/upgrade completed successfully and the RBAC smoke test
passed. The test creates a legitimate audit event, attempts direct SQL
`UPDATE` and `DELETE` against it through the application database connection,
and asserts that each operation fails with `audit_events are append-only`.
It then removes its synthetic accounts, confirming that the trigger permits
only the existing foreign-key cleanup that changes a deleted actor reference
to `NULL` without altering audit content.

## Boundary

This is a database control for the normal application role, not an absolute
WORM store: a database superuser or schema owner can change the trigger or
table. An external immutable audit export/retention design and teammate
reproduction remain open.
