# Investigate: manual testing reference

Investigate is the offline forensic-search feature: upload a recording,
process it for vehicles or people, then search by plate -- or by uploading a
person photo, which ranks person tracks by appearance similarity ("more like
this" and the subject-linking UI are still not wired up). The frontend
(`frontend-v2/src/views/Investigate/`) is in place: Recordings list +
upload, per-recording ingest run management,
plate Search with a results grid grouped by recording, and clip playback
with a frame-accurate bounding-box overlay drawn on a `<canvas>` over the
video (`TrackOverlayPlayer.jsx`) -- the app's first non-HLS video player,
possible here specifically because a recorded file has exact frame timing
that a live stream doesn't. Photo search is in place too (`SearchView.jsx` posts to
`/investigate/search/person`), backed by one appearance embedding per person
track computed at ingest -- a generic pretrained backbone, not a dedicated
ReID model, so it ranks candidates and never asserts an identity. Subject
linking has an endpoint
(`POST /investigate/runs/{run_id}/tracks/{track_ref}/link`) but no UI yet.

Automated coverage: `backend/scripts/investigate_smoke_test.py` (21/21
passing as of 2026-08-30, and it predates photo search -- that path has no
automated coverage yet), which builds its own fixture via
`backend/scripts/make_test_fixture.py` rather than relying on committed
footage (none is committed, for the same privacy reason
`backend/survey/*.jpg` is gitignored). This document is the manual/`curl`
companion -- useful for debugging a single step without running the whole
suite, and for exercising the worker standalone. The frontend has been
walked manually end-to-end (upload -> ingest -> search -> deep-linked clip
with the box overlay correctly aligned) but has no Playwright coverage yet.

**Rebased onto `feat/operator-console-redesign` (merged 2026-08-30, PR #3)
after this feature was first built.** The whole surface was re-verified
against the new dark design system rather than assumed compatible: the
plate confirmed/tentative distinction now renders through `CertaintyMark`
(`components/Badge.jsx`) instead of the retired `.badge-confirmed`/
`.badge-inferred` classes -- this is the one place in the console a
genuinely *tentative* (uncorroborated) plate is shown at all, since the
live pipeline only ever reports confirmed reads. The search results grid's
exact/fuzzy match chips moved off colour (`badge-ok`/`badge-warn`) onto the
same certainty texture, per DESIGN.md §4's "colour never encodes
confidence" rule -- that was a real instance of the exact collision the
redesign exists to fix, not a hypothetical one. Re-tested against real
uploaded footage (not just the synthetic fixture) end to end: upload,
normalise, ingest, real vehicle detections and thumbnails, and the canvas
box overlay tracking correctly through a real clip.

## Setup

```bash
cd backend
../.venv/bin/python scripts/make_test_fixture.py --nasty   # builds .fixtures/investigate/*.mp4
```

Log in and keep a cookie jar:

```bash
COOKIES=/tmp/sentinel-cookies.txt
PW=$(grep SUPER_ADMIN_PASSWORD .env | cut -d= -f2-)
curl -s -c $COOKIES -X POST http://127.0.0.1:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"admin@sentinel.local\",\"password\":\"${PW}\"}"
```

Every call below assumes `-b $COOKIES` for an authenticated browser-style
call, or `-H "X-Sentinel-Worker-Token: $TOKEN"` (from `.env`'s
`WORKER_API_TOKEN`) for a worker-style call -- never both on the same
endpoint; see the access table below.

## Endpoints and who can call them

| Endpoint | Auth | Notes |
|---|---|---|
| `POST /api/investigate/recordings` | operator clearance on `department` | multipart: `file` + query params `department`, `camera_id?`, `location_text?`, `recorded_at?` |
| `GET /api/investigate/recordings` | any clearance | department-scoped, `?status=` |
| `GET /api/investigate/recordings/{id}` | viewer | |
| `DELETE /api/investigate/recordings/{id}` | department admin (home dept) or super admin | cascades runs/tracks, removes files |
| `GET /api/investigate/recordings/{id}/media` | viewer | Range-capable (`206`), same-origin only |
| `POST /api/investigate/recordings/{id}/runs` | operator | body `{"kind": "vehicle"}` |
| `GET /api/investigate/runs/{id}` | viewer | includes `queue_position` while queued |
| `POST /api/investigate/runs/{id}/cancel` | operator | |
| `GET /api/investigate/runs/{id}/tracks` | viewer | never includes `boxes`/`embedding` |
| `GET /api/investigate/runs/{id}/tracks/{track_ref}/boxes` | viewer | fixed 10Hz timeline |
| `GET /api/investigate/runs/{id}/tracks/{track_ref}/thumb` | viewer | JPEG |
| `POST /api/investigate/runs/{id}/tracks/{track_ref}/link` | operator | body `{"subject_id": N}` |
| `POST /api/investigate/subjects` | any authenticated user | |
| `POST /api/investigate/search/plate` | any clearance | department-scoped results only |
| `POST /api/investigate/runs/{id}/chunk` | **worker token**, not a cookie | |
| `POST /api/investigate/runs/{id}/heartbeat` | **worker token** | |
| `POST /api/investigate/runs/{id}/complete` | **worker token** | |

## Upload → normalise → ingest → search, end to end

```bash
# 1. Upload
curl -s -b $COOKIES -X POST "http://127.0.0.1:8000/api/investigate/recordings?department=Police" \
  -F "file=@.fixtures/investigate/base_clip.mp4;type=video/mp4"
# -> {"id": N, "status": "ready", "content_sha256": "...", "fps_num": 25, ...}
# status is "ready" (normalised, playable) or "rejected" (see reject_reason) --
# never a 500 for a bad upload; ffprobe/ffmpeg failures are caught.

# 2. Enqueue a vehicle ingest run
curl -s -b $COOKIES -X POST http://127.0.0.1:8000/api/investigate/recordings/N/runs \
  -H "Content-Type: application/json" -d '{"kind":"vehicle"}'
# -> {"id": RUN_ID, "status": "queued", "queue_position": 1, ...}

# 3. Poll until terminal
watch -n2 "curl -s -b $COOKIES http://127.0.0.1:8000/api/investigate/runs/RUN_ID"
# queued -> running -> completed | completed_partial | failed | stalled | cancelled

# 4. List tracks, fetch one's timeline and thumbnail
curl -s -b $COOKIES http://127.0.0.1:8000/api/investigate/runs/RUN_ID/tracks
curl -s -b $COOKIES http://127.0.0.1:8000/api/investigate/runs/RUN_ID/tracks/1/boxes
curl -s -b $COOKIES http://127.0.0.1:8000/api/investigate/runs/RUN_ID/tracks/1/thumb -o thumb.jpg

# 5. Search by plate (exact or fuzzy -- fuzzy tolerates ~1-2 char OCR errors via pg_trgm)
curl -s -b $COOKIES -X POST http://127.0.0.1:8000/api/investigate/search/plate \
  -H "Content-Type: application/json" -d '{"plate":"GJ01AB1234","fuzzy":true}'

# 6. Seek within the recording (confirms Range/206 support)
curl -s -b $COOKIES -H "Range: bytes=0-1023" http://127.0.0.1:8000/api/investigate/recordings/N/media -D -
```

## Running the ingest worker standalone (no backend in the loop)

Useful for debugging tracking/plate behaviour without the chunk/heartbeat
machinery in the way -- point `--report-to` at nothing reachable and read
the worker's own stdout:

```bash
cd multi-object-tracking
.venv/bin/python recording_ingest_worker.py \
  --run-id 0 --video-path ../.fixtures/investigate/base_clip.mp4 \
  --report-to http://127.0.0.1:1 \
  --kind vehicle --model yolo11x.pt --tracker trackers/fast.yaml \
  --imgsz 960 --frame-stride 1
```

It will print device/provider info, per-100-frame progress, and a final
summary; chunk/heartbeat/complete POSTs will fail loudly (expected, nothing
is listening) but the worker keeps running and finishes normally --
proving those POST failures never abort an ingest, only get logged.

## Inspecting state directly (`psql`)

```sql
-- Recent recordings and their normalised metadata
SELECT id, original_filename, status, fps_num, fps_den, width, height, department
FROM recordings ORDER BY id DESC LIMIT 10;

-- Run state machine in progress
SELECT id, recording_id, status, frames_processed, frames_expected, track_count,
       chunk_count_received, chunk_count_expected, error
FROM ingest_runs ORDER BY id DESC LIMIT 10;

-- Tracks for one run, without pulling the (deferred, potentially large) boxes column
SELECT run_id, track_ref, occurrence_index, first_ms, last_ms, best_conf,
       plate_confirmed, plate_tentative, thumb_path
FROM tracks WHERE run_id = RUN_ID ORDER BY first_ms;

-- Occurrence merge sanity check: same occurrence_index across a tracker
-- lose/reacquire gap under 5s, different across a genuine second visit
SELECT track_ref, occurrence_index, first_ms, last_ms FROM tracks
WHERE run_id = RUN_ID ORDER BY first_ms;

-- Audit trail for a search
SELECT actor_email, action, details, occurred_at FROM audit_events
WHERE action = 'investigation.searched' ORDER BY id DESC LIMIT 5;
```

## Design notes worth knowing before debugging something that looks wrong

- **Frame stride defaults to 1, deliberately -- do not "fix" this to be
  faster.** TRACKTRACK hard-gates association on IoU
  (`cost[~supported] = 1.0` for iou<0.10) *after* the appearance term, so a
  strided run's larger inter-frame displacement can make fast-moving
  objects unmatchable regardless of ReID. Get throughput from `imgsz`/model
  size instead. If stride is ever reintroduced, `track_buffer` must be
  re-derived per run (`recording_ingest_worker.derive_tracker_yaml`) --
  the tracker counts `track_buffer` in **tracker updates, not source
  frames or seconds**, so passing a static tuned config through unchanged
  at any stride other than the one it was measured at is already wrong.
- **A `deferred()` column on an async-loaded object cannot be lazily
  read.** `Track.boxes`/`Track.embedding` are `deferred()` specifically so
  a track list never drags a timeline along -- but touching the attribute
  on an object fetched via `session.get()`/`select(Track)` raises
  `MissingGreenlet` under `AsyncSession` (no implicit IO context to run
  the lazy load in). Always select the column explicitly
  (`select(Track.boxes).where(...)`) instead.
- **A subprocess worker's relative paths resolve against `cwd=
  multi-object-tracking/`, not the backend's own directory.** Any path
  handed to `_spawn_ingest_worker` must be `.resolve()`d to absolute first.
- **The chunk/heartbeat/complete endpoints intentionally no-op (or,
  chunk-wise, silently succeed-but-drop) once a run has left `queued`/
  `running`.** If a manual test reuses a `completed` run's id to POST a
  synthetic chunk, nothing happens and no error is raised -- always start
  a fresh run (or heartbeat a queued one into `running`) for that kind of
  test rather than reusing one that already finished.
- **CFR normalisation on upload is not an optimisation -- it removes a
  whole bug class.** OpenCV auto-rotates frames per the container's
  display matrix but reports *unrotated* `CAP_PROP_FRAME_WIDTH/HEIGHT`;
  variable frame rate makes `frame_index/fps` drift, worst at the end of a
  clip; a non-zero start PTS offsets `video.currentTime` from
  `frame_index/fps` by a constant. One ffmpeg pass to CFR H.264/yuv420p
  with baked-in rotation and zero start PTS fixes all three, and is
  required for browser playback anyway.
- **The ONNX provider bug fixed in `plates.py` also affects this path.**
  `build_reader`/`PlateReader` previously mapped any non-`"cpu"` device
  (including `"mps"`) to `"cuda"`, so on Apple Silicon the plate reader
  believed it was on CUDA, requested a provider that doesn't exist, and
  silently fell back to CPU at ~90ms/crop. Now resolved via
  `_resolve_onnx_providers()` (CoreML on Darwin) and `ocr_device="auto"`
  (lets `fast_plate_ocr` call `ort.get_available_providers()` itself) --
  measured ~10ms/crop on this hardware afterward.
