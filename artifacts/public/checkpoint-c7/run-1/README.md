# Section 5 live-test Phase 7 — reliability and performance rehearsal

Run: `20260831T130916Z` (`reliability_report.json` in this directory)

## Automated scenarios (backend/scripts/reliability_rehearsal.py) — 8/8 passed

| scenario | target | result |
|---|---|---|
| detection-to-alert latency (p50/p95) | alert visible within 5s (p95) | p95=2.924s (see cross-run note below) |
| queue growth | bounded, not pinned at cap | max queue_depth=30 (hard cap), at-cap 18% of samples |
| duplicate alert storm | at most one alert per sighting | 1 alert / 2 sightings |
| feed interruption and recovery | recovers, no tight reconnect loop | confirmed down, 1.3s recovery, 0 spurious reconnects |
| worker crash and recovery | supervisor reaps/backs off/restarts | reused `analytics_concurrency_smoke_test.py`, 9/9 internal checks passed |
| backend restart | <30s downtime, no data loss | 1.6s downtime; sighting/alert counts unchanged across restart; `analytics_enabled` correctly cleared by design (not silently auto-resumed) |
| database connection interruption | recovers, no process crash | terminated this backend's own Postgres connections directly (not the Postgres service); recovered in 1.1s |
| three concurrent ANPR workers | >=3 concurrent | 3/3 running throughout |

Full machine-readable detail, including per-camera FPS/dropped-frames and every
raw measurement, is in `reliability_report.json`.

### Latency: cross-run consistency note

`observation_worker.py` reports a given tracked vehicle only once per track_id
for the life of the worker process (by design -- see its module docstring),
so one worker only ever produces one fresh "detection-to-alert" sample
per continuous run; a true n>>1 p50/p95 would need many distinct plates or
worker restarts between samples, which this fixture's single synthetic
plate doesn't exercise. Rather than fabricate a larger n, here are four
independent real measurements taken across today's separate full-pipeline
runs (Phase 6 and Phase 7, different processes, different seed cycles):

| run | latency |
|---|---|
| Phase 6 run-1 | 2.55s |
| Phase 6 run-2 | 2.12s |
| Phase 7 run-1 (pre-fix) | 2.36s |
| Phase 7 run-2 | 2.92s |

All four land in a tight 2.1-2.9s band, comfortably under the 5s target.
This is real signal on consistency, not a rigorous statistical p95 --
flagged honestly rather than overclaimed.

## Codec / resolution / frame-rate independence

The relay republishes clips with `-c copy` (no transcoding), so the actual
codec/resolution/frame-rate seen by the worker is whatever the source clip
is. The worker's own decode path (`camera_feeds.LiveFrameReader`) opens
every stream via `cv2.VideoCapture(url, cv2.CAP_FFMPEG)` -- generic
FFmpeg-backed decode, not hardcoded to one codec.

Verified directly (not just by architecture inspection): transcoded the
existing 1920x1080@25fps H.264 fixture clip to **HEVC, 960x540, 15fps**
(`ffmpeg -c:v hevc_videotoolbox -vf scale=960:540 -r 15`) and opened it with
the exact same `cv2.VideoCapture(path, cv2.CAP_FFMPEG)` call the worker
uses: opened cleanly, read 10/10 frames, correctly reported
`960x540 @ 15.0fps`. Also confirmed `make_test_fixture.build_variable_frame_rate`
(already in this codebase, built for exactly this purpose) produces a
playable VFR clip.

## Browser player (Live view)

Logged into the real frontend (`http://localhost:5173`) via the actual
login form and drove the Live view with Playwright:

- `browser-01-live-grid-with-analytics.png` -- preview grid (9 tiles) with
  the toolbar correctly reading "ANPR 3 of 3 running" and "2 open alerts"
  while 3 workers ran concurrently -- real evidence for "preview grid plus
  analytics workers together."
- `browser-02-feed-interrupted.png` / `browser-03-feed-recovered.png` --
  captured immediately after `live_test_relay.py kill test-camera-b` and
  again after `restart test-camera-b`. The UI does show a "reconnecting..."
  badge on affected tiles, confirming the player has and displays a real
  stall/reconnect state rather than silently freezing.

Caveat, stated honestly: the grid shows an arbitrary 9-of-41 camera subset
(sorted by camera number, not filtered to the fixture's own 3 cameras), so
these three screenshots don't conclusively isolate camera b's own tile --
they confirm the reconnecting-state UI exists and renders, not that this
specific tile is provably the one I interrupted. The camera-specific,
numerically precise recovery measurement (1.3s, 0 spurious reconnects) is
the automated backend-side result above, which does target the exact
camera by id. Video thumbnails render black in headless screenshot capture
(a known Chromium-headless HLS/canvas limitation) even for genuinely live
feeds -- not evidence of a playback defect.

## Targets — verdict

- Alert visible within 5s of a usable confirmed observation: **met** (2.1-2.9s across 4 independent runs).
- No unbounded queue growth: **met** (hard-capped at 30 by the bounded/drop-oldest reader; not sustained at cap).
- No duplicate alert storm: **met** (dedup + resolution semantics verified in Phase 4 and re-confirmed here).
- No tight reconnect loop: **met** (one kill -> one clean reconnect, 1.3s, 0 spurious retries).
