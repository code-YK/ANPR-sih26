# C3 synthetic fixture verification — 2026-08-31

## Scope

`GOV-M1-002` and `GOV-FUN-011` representative-data evidence. The fixture is
committed at `backend/fixtures/synthetic_registry.json`; it contains no
endpoint, credential, footage, real person, or observed vehicle identifier.

## Commands

```bash
cd backend
.venv/bin/python scripts/seed_synthetic_demo.py --reset
.venv/bin/python scripts/seed_synthetic_demo.py
.venv/bin/python scripts/seed_synthetic_demo.py
.venv/bin/python scripts/seed_synthetic_demo.py --verify
```

## Result

- Reset completed with no pre-existing fixture rows.
- Two consecutive seed runs each reported five synthetic cameras, three
  departments, and two synthetic watchlist entries.
- Verification confirmed exactly those five `demo-cam-*` cameras and two
  `SYNTH-TEST-*` values, with no RTSP, HLS, or WebRTC endpoint stored.

## Coverage and limits

The five camera records cover three departments, fixed/PTZ/IP/analog types,
live/offline/unknown health, placed and unplaced assets, ANPR viability, and
gap-report capability states. This is metadata-only data: it does not prove a
catalogue adapter, protocol-compatible stream fixture, live-feed health
transition, browser rendering, or ML accuracy.
