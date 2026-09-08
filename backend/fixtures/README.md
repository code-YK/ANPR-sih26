# Synthetic demo dataset

`synthetic_registry.json` is the repository's safe, deterministic Model 1
demo dataset. It contains five explicitly synthetic camera metadata records,
three departments, and two clearly non-real watchlist values. It has no source
URL, credential, footage, real person, or observed vehicle identifier.

Load it from a migrated local database with:

```bash
cd backend
.venv/bin/python scripts/seed_synthetic_demo.py
.venv/bin/python scripts/seed_synthetic_demo.py --verify
```

The command is idempotent for the `demo-cam-*` camera namespace and updates or
adds only watchlist entries whose source is `sentinel-synthetic-demo-v1`. It
does not call the sandbox or start a media/ML worker. Use `--reset` to remove
only those managed fixture rows after a demo.

The records deliberately cover live/offline/unknown health, fixed/PTZ/IP/analog
types, three departments, four placed districts plus an unplaced asset, and
both ANPR-viable and capability-gap states. They are suitable for the registry,
GIS, gap-analysis, role-scope, and synthetic watchlist demonstrations; they do
not emulate a media protocol or prove a live feed integration.
