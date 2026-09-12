# Synthetic demo dataset

`synthetic_registry.json` is the repository's safe, deterministic
registry demo dataset. It contains five explicitly synthetic camera metadata records,
three departments, and two clearly non-real watchlist values. It has no source
URL, credential, footage, real person, or observed vehicle identifier.

Load it from a migrated local database with:

```bash
cd backend
.venv/bin/python scripts/seed_synthetic_demo.py            # Linux
.venv\Scripts\python.exe scripts\seed_synthetic_demo.py    # Windows
```

The command is idempotent for the `demo-cam-*` camera namespace and updates or
adds only watchlist entries whose source is `sentinel-synthetic-demo-v1`. It
does not call any external catalogue or start a media/ML worker. Use `--reset` to remove
only those managed fixture rows after a demo.

The records deliberately cover live/offline/unknown health, fixed/PTZ/IP/analog
types, three departments, four placed districts plus an unplaced asset, and
both ANPR-viable and capability-gap states. They are suitable for the registry,
GIS, gap-analysis, role-scope, and synthetic watchlist demonstrations; they do
not emulate a media protocol or prove a live feed integration.

## `government_cameras.json`

The **real government camera nodes** the recorded feeds came from: 16 rows
(`cam02`-`cam13` plus the `cam11b`-`cam11e` corridor aliases) carrying real
names, districts, and coordinates.

Five of them - `cam11`, `cam11b`, `cam11c`, `cam11d`, `cam11e` - sit at
`exact`-geocoded points along a real ~2.5 km corridor on Ahmedabad's SG
Highway. That is deliberate: trajectory reconstruction and corridor analytics
both suppress direction and speed unless **both** endpoint cameras are
`exact`-geocoded, so this chain is what gives those features genuine geometry
to work against.

```bash
.venv/bin/python scripts/seed_government_cameras.py           # load / refresh
.venv/bin/python scripts/seed_government_cameras.py --verify  # report presence
.venv/bin/python scripts/seed_government_cameras.py --reset   # remove
```

Every row declares a `department`. That is enforced by the loader, because a
camera with a NULL department is invisible to every non-super-admin user and
would silently present an empty registry to an ordinary operator.

Re-running is safe: it updates metadata but **never** writes the
stream-endpoint columns on an existing row, so re-seeding while government
mode is active cannot pull its relay URLs out from under it. `--reset` refuses
to delete a camera that already has sightings, alerts, or counts.
