# ANPR Pipeline Vertical Slice: Build Notes

> **Historical build spec.** Written during an earlier programme whose
> `Model N` vocabulary does not exist in SIH26127. Retained because it records
> *why* this slice is built the way it is - the reasoning is still current even
> where the naming is not. See [ADR 0004](decisions/0004-sih26127-rescope.md)
> for the mapping, and [requirements.md](requirements.md) for current IDs.

Status: Core implementation merged; requirement and evidence gaps remain (reviewed 2026-08-30)

Covers the observation-ingestion → watchlist → alert path: live camera → ANPR
detection/tracking → confirmed plate → `POST /api/sightings` → watchlist
match → deduplicated alert. Builds directly on `docs/registry-gis-build-spec.md`'s
registry (`cameras`, `sightings` tables) and reuses a teammate's existing
`multi-object-tracking/` detection/tracking/ANPR code rather than
reimplementing it.

## 1. Two codebases, two dependency footprints

`backend/` (FastAPI, no ML deps) and `multi-object-tracking/` (torch,
ultralytics, fast-alpr — its own `.venv`) stay separate. The worker is a
subprocess the backend launches and talks to over HTTP, not a library the
backend imports:

```
multi-object-tracking/ (heavy venv)                    backend/ (light venv)
┌────────────────────────────────────────────┐         ┌───────────────────────────────┐
│ observation_worker.py --camera-id 21         │         │ POST /api/analytics/start      │
│   camera_feeds.LiveFrameReader               │ Popen   │   camera_id=21                 │
│     + ProgramDateTimeAnchor                  │◀────────│   spawns worker, tracks PID    │
│   YOLO + ByteTrack (car_tracking.py)         │         │ GET  /api/analytics/status     │
│   plates.PlateReader (existing voting)       │         │ POST /api/analytics/stop       │
│   on first confirmed() per track:            │         │                                │
│     POST /api/sightings ────────────────────┼────────▶│ POST /api/sightings            │
└────────────────────────────────────────────┘         │   normalise plate               │
                                                          │   insert sighting               │
                                                          │   match watchlist_entries       │
                                                          │   create Alert (deduped)        │
                                                          │                                 │
                                                          │ GET/POST/PUT/DELETE /api/watchlist
                                                          │ POST /api/watchlist/bulk        │
                                                          │ GET /api/alerts, .../acknowledge│
                                                          │ .../resolve                     │
                                                          └───────────────────────────────┘
```

One sighting per **confirmed** plate-per-track, not per accepted read or per
frame: `plates.PlateVote` confirms a plate only when at least three
independent frames agree on its length and on every character, over reads
that are valid Indian plates exactly as read (see
`multi-object-tracking/plates.py`'s own docstring for the grammar and the
vote).
Reporting every intermediate read would let unvalidated OCR output reach the
registry as if it were settled fact — the same honesty principle already
applied to `anpr_viable`, `geocode_confidence`, and `metadata_confidence` in
the camera registry.

## 2. Timestamp anchoring (`seen_at` must never be `datetime.now()`)

Checked two things against the live sandbox before designing this:

1. `ffprobe -show_frames` and OpenCV's `CAP_PROP_POS_MSEC` both report exactly
   `frame_index / declared_fps` (40ms/frame on a 25fps stream) — a synthetic,
   connection-relative counter, not real decoder PTS. Nothing better is
   available from either layer here.
2. The HLS **media** playlist (one indirection past the catalogue's
   `hls_live_url`, and past a `cookieCheck` redirect) **does** carry
   `#EXT-X-PROGRAM-DATE-TIME` — an absolute UTC timestamp refreshed roughly
   every segment (~10s target duration). Real signal.

Design (`camera_feeds.ProgramDateTimeAnchor`): on connect, and every ~30s
after, fetch the media playlist and take the anchor pair
`(anchor_wall, anchor_pts_ms)` from the last `PROGRAM-DATE-TIME` tag and the
concurrent `CAP_PROP_POS_MSEC` reading. Every frame in between:

```
seen_at = anchor_wall + (frame_pts_ms - anchor_pts_ms) / 1000
```

`frame_pts_ms` is stored as-is (the raw, fps-derived OpenCV value) — never
claimed to be more than a debug breadcrumb, matching the schema's own comment.

A new `epoch_id` integer column on `sightings` (not a discontinuity table)
is incremented, and the anchor immediately re-fetched, on: a stream
reconnect, or `frame_pts_ms` moving backwards (the sandbox's simulated-live
loop restarting). `frame_pts_ms` is only comparable to another row's within
the same `(camera_id, epoch_id)`.

**Accepted, documented limitation**: absolute accuracy is bounded to roughly
one segment duration (~10s) plus however stale the anchor has drifted since
its last refresh — a constant-ish per-camera offset, not corrected further.
This preserves per-camera ordering and internal consistency, which is what
route reconstruction needs, without claiming frame-perfect absolute time.

**Roadmap, not built**: the sandbox burns a timestamp overlay into the video
itself (visible on stills, e.g. `14-06-2026 03:13:02`). OCR'ing that would
give true recording time independent of HLS playlist metadata. Out of scope
for this pass.

## 3. Alert dedup

`Alert.dedup_key = f"{normalised_plate}:{watchlist_entry_id}"`. A new sighting
matching an active watchlist entry only creates a new alert if no **open**
alert with the same dedup key exists within the last 15 minutes
(`ALERT_DEDUP_WINDOW` in `backend/app/routers/sightings.py`) — an
acknowledged or resolved alert never suppresses a new one, so a plate seen
again long after review still raises fresh attention. The window is a
reasonable default, not specified anywhere else in the project; easy to
retune in one place.

## 4. Analytics worker lifecycle

`POST /api/analytics/start?camera_id=&mode=` launches the vehicle ANPR or
person-counting worker as a subprocess using `multi-object-tracking/`'s own
`.venv`/`venv` interpreter, resolved relative to the repository root, with
`--report-to` pointed at this backend. State is in-memory only, keyed by
`(camera_id, mode)`: restarting the backend cannot reattach to a prior worker,
so startup kills worker PIDs recorded in the local manifest and clears stale
`analytics_enabled` intent before accepting new operator focus.

Concurrency is mode-specific and configurable:
- `max_concurrent_vehicle_workers` defaults to **3** for the accurate `yolo11x.pt` ANPR path
- `max_concurrent_person_workers` defaults to 3 for the lighter `yolo11n.pt` bonus path
- `max_concurrent_suspicious_workers` defaults to 3 for the potential-threat classification path

Configure these via `MAX_CONCURRENT_VEHICLE_WORKERS`, `MAX_CONCURRENT_PERSON_WORKERS`, and
`MAX_CONCURRENT_SUSPICIOUS_WORKERS` environment variables (or in `.env`). The defaults assume
a typical local-demo GPU; production deployments should size these from measured GPU,
decoder, and gateway capacity. When the limit is reached, additional worker requests queue
and start when capacity frees. These are the pacing controls for `GOV-ING-012`, not a durable
scheduler/queue. Worker stdout/stderr goes to
`multi-object-tracking/worker_logs/camera-<id>-<mode>.log` (gitignored).

## 5. Current follow-up scope

The journey endpoint and the React Watchlist, Alerts, and Journey views now
exist. Department RBAC and actor-aware state-change audit are now implemented
under ADR 0003. Audit rows are protected from application-role mutation by the
database trigger, and a super admin can produce a digest-verifiable archive;
placement in immutable external retention remains open. Remaining work is
tracked in `docs/requirements.md`; evidence references on sightings/journey
stops, configurable confidence gating, deterministic matching-policy tests,
and protocol-compatible timing/failure fixtures are now recorded in C6/C7.
Key gaps are an explicit ambiguous-match policy, representative ANPR
accuracy/error limits, official-feed evidence, and a locked ML/demo-machine
environment. CoreML acceleration is optional optimisation and must not displace
these mandatory gaps.

## 6. Done criteria (this pass)

- [x] Live camera → confirmed plate → `sightings` row with anchored `seen_at`
- [x] `epoch_id` bumps on reconnect / PTS discontinuity, not on ordinary frames
- [x] Watchlist CRUD + bulk CSV import, synthetic severities/reason codes
- [x] A sighting matching an active watchlist entry creates exactly one
      `Alert`; a repeat sighting within the dedup window does not duplicate it
- [x] Alert acknowledge/resolve lifecycle
- [x] `POST /api/analytics/start|stop`, `GET /api/analytics/status` manage the
      worker without a terminal
- [x] A dated, redacted, reproducible synthetic live packet is recorded in
      `artifacts/public/checkpoint-c6/run-1/`; it includes three cameras,
      evidence URLs, alerts, journey, export reconciliation, checksums, and
      environment metadata. A real official-feed packet remains open.
