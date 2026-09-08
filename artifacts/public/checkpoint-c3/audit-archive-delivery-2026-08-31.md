# External audit-archive delivery verification — 2026-08-31

Base revision: documentation/external-archive-delivery branch based on `fda8fa8`.

## Scope and safety boundary

The service was configured with an empty, disposable directory outside the
repository and database. This demonstrates the application delivery contract;
the directory was **not** a WORM/object-lock service and therefore is not
evidence of immutable retention.

## Command

```bash
cd backend
AUDIT_ARCHIVE_DIR=/private/tmp/sentinel-audit-archive-20260831 \
  .venv/bin/uvicorn app.main:app --port 8123

# Separate terminal, with the backend running:
.venv/bin/python scripts/rbac_smoke_test.py --base-url http://127.0.0.1:8123
```

## Result

- RBAC smoke test passed.
- The super-admin delivery endpoint returned HTTP 201.
- It created one canonical `.ndjson` snapshot and a matching detached
  `.ndjson.sha256` file by exclusive creation.
- The archive-delivery audit action was verified by the smoke test.

To close immutable-retention acceptance, repeat this against an approved
administrator-managed WORM/object-lock destination and retain the platform
policy/evidence outside Git.
