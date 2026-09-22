# Analytics workers

The GPU-side of SIH26127. This directory holds a **separate Python environment**
from `backend/.venv` on purpose: the backend spawns a worker as a subprocess and
receives observations or aggregate counts back over HTTP with a service token,
so the workers never hold a database credential.

Everything here runs **locally**, on the machine with the GPU. Only the database
is remote. Video never leaves the host; only derived metadata is persisted.

Use the backend's analytics endpoints for normal operation. They select the
registered stream source, force RTSP/TCP when RTSP is used, and keep worker
lifecycle, logs, and the bounded concurrency limit visible to the operator
console.

## What each worker does

| Script | Role |
|---|---|
| `observation_worker.py` | **ANPR.** YOLO11 detect -> ByteTrack -> fast-alpr OCR -> vote -> `POST /api/sightings` |
| `person_observation_worker.py` | Person counting; posts aggregate windows, never identities |
| `suspicious_observation_worker.py` | Purpose-trained suspicious-activity classifier -> standalone alerts |
| `recording_ingest_worker.py` | **Offline forensic ingest** of an uploaded recording (Investigate) |
| `person_embedding.py` | One appearance embedding per person track, for photo search |
| `person_search.py` | Embeds a single query photo for ranked candidate search |
| `plates.py` | Plate detection, OCR, and the per-track vote that decides a confirmed read |
| `camera_feeds.py` | Live capture, PTS/program-date-time anchoring, reconnect/backoff |
| `tracking_common.py` | Shared device resolution, tracker config, drawing helpers |
| `record_live_clips.py` | Records live feeds into `recorded-streams/` for government mode |

## Prerequisites

- The backend is running and its migrations have been applied.
- The target camera exists in the registry.
- `WORKER_API_TOKEN` is configured in `backend/.env`; the backend passes it to
  subprocesses as `SENTINEL_WORKER_API_TOKEN` so ingestion cannot reuse a human
  browser session.
- **Python 3.11** and `ffmpeg` on `PATH`.
- An NVIDIA GPU with CUDA 12.8+ (mandatory on RTX 50-series / Blackwell, sm_120).

Do not put catalogue URLs, stream URLs, tokens, or observed identifiers in this
README, in commands copied into Git, or in worker logs.

## Setup

**Install PyTorch from the CUDA index first.** A plain `pip install torch` on
Windows silently installs a CPU-only wheel - roughly 15x slower, with no error.

```bash
# Linux
python3.11 -m venv multi-object-tracking/.venv
multi-object-tracking/.venv/bin/pip install --index-url https://download.pytorch.org/whl/cu128 torch torchvision
multi-object-tracking/.venv/bin/pip install -r multi-object-tracking/requirements.txt
```

```powershell
# Windows
py -3.11 -m venv multi-object-tracking\.venv
multi-object-tracking\.venv\Scripts\pip.exe install --index-url https://download.pytorch.org/whl/cu128 torch torchvision
multi-object-tracking\.venv\Scripts\pip.exe install -r multi-object-tracking\requirements.txt
```

### Verify the GPU is really being used

`torch.cuda.is_available()` alone is not enough - check the architecture is in
the compiled arch list and that a kernel actually launches:

```bash
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_capability(0), torch.cuda.get_arch_list())"
```

Expected on an RTX 5060: `2.11.0+cu128 True (12, 0) [... 'sm_120']`.

Then confirm ANPR itself landed on CUDA rather than silently falling back:

```bash
python -c "import plates; print(plates.PlateReader(device='0').providers())"
```

Expected: `['CUDAExecutionProvider', 'CPUExecutionProvider']`. If you see only
`CPUExecutionProvider`, read [../docs/platform-notes.md](../docs/platform-notes.md) -
a device-convention bug used to cause exactly that, at roughly 9x the cost per crop.

### Verify OpenCV kept its GUI build

`fast-alpr` pulls in `opencv-python-headless`, which shares the same `cv2/`
directory as `opencv-python`. Whichever pip writes last wins, so `cv2.imshow`
can break silently:

```bash
python -c "import cv2; cv2.namedWindow('t'); cv2.destroyAllWindows(); print('GUI OK')"
```

Fix if needed:

```bash
pip uninstall -y opencv-python-headless
pip install --force-reinstall --no-deps opencv-python
```

## Model weights

`yolo11x.pt` and `yolo11n.pt` download automatically on first use. **`best.pt`
does not** - it is the purpose-trained suspicious-activity classifier and must be
obtained from the project owner. All weights are git-ignored; see
[../SETUP.md](../SETUP.md#external-assets-not-in-git).

The first worker start can download model weights, so it takes longer than
later starts.

## Start and monitor one ANPR worker

Use a camera ID already present in the registry. Every worker opens its own
copy of the live stream, so the backend enforces a bounded concurrency limit.
The default is **3 concurrent ANPR workers**; configure `MAX_CONCURRENT_VEHICLE_WORKERS`
in `backend/.env` to set a different bounded limit that your infrastructure can handle.
When enabled ANPR cameras exceed this limit, additional ones queue and start
automatically when a worker slot frees. Do not treat this as an unbounded setting.

To enable ANPR for a camera:
1. Use the authenticated Live view and toggle the ANPR switch for that camera
2. The toggle immediately enables the worker (or queues it if at capacity)
3. The backend supervisor handles concurrent start/stop and reconciles the persistent intent

Monitor a running worker's activity locally:

```zsh
tail -f worker_logs/camera-YOUR_CAMERA_ID-vehicle.log
```

If ANPR fails to start, the error appears in the UI and the enabled flag is
automatically reverted. Queued cameras show queue position and any reported failures.

The vehicle worker performs detection, tracking, and corroborated plate
reading. It reports only confirmed plates to `POST /api/sightings`; a matching
active watchlist entry can then create an alert.

### How a plate is read and confirmed

1. **Size gate.** Vehicles too small to carry a readable plate are skipped
   before the plate detector runs. A plate box narrower than
   `--min-plate-width` (100 px) is never sent to OCR — except a **two-row**
   plate (two-wheelers, autos), which is read down to
   `--min-plate-width-two-row` (55 px) because its characters are about twice
   as tall at the same width. Two-wheelers and autos are therefore checked
   down to the smaller vehicle size; everything else keeps the 100 px gate.
   These numbers come from a sweep over recorded footage: lowering the
   single-row gate to 90/80/70/60 px added no correct plate, only cost and
   wrong reads, while the two-row gate recovered legible 60 px auto plates.
2. **Padded OCR crop.** OCR reads the plate box grown by 8% on every side,
   cut from the full frame. The detector's box is tight and often clips the
   first or last character, and a truncated read can still look like a valid
   plate.
3. **Grammar, as read.** A read can vote only if it is a valid Indian plate
   exactly as OCR produced it; no character is coerced to fit:

   | Layout | Example |
   |---|---|
   | State, 2-digit district, 0–3 series letters, 4 digits | `UP14FS3664`, `GJ21W3884` |
   | Delhi: `DL`, 1–2 digit district, category letter (+ series), 4 digits | `DL2CBB4791`, `DL7CZ1908`, `DL10CN7685` |
   | Bharat series: year, `BH`, 4 digits, 1–2 letters | `22BH1234AA` |

   The state code must be a real state/UT code. Series letters never use
   I or O. Delhi's category letter must be one Delhi issues.
4. **Multi-frame vote.** A plate is **confirmed** when at least
   `--plate-votes` (3) independent frames agree:
   - first on the plate's length, then on every character, each by at least
     75% of the vote, where each read is weighted by OCR confidence,
     sharpness and plate width;
   - the result must be a string OCR actually read;
   - reads below `--min-plate-conf` (0.55) don't vote;
   - one read counts per frame, and byte-identical crops count once.

   Anything short of that stays **tentative**: it is shown with a `?` in the
   detector view and in Investigate, and is never reported as a sighting.

### What the detector view shows

Each read is drawn at the plate itself, on the snapshot the console displays:

- the plate's own box is outlined, so the number is attributable to a plate
  rather than to a vehicle;
- a **green** chip is a confirmed plate; an **amber** chip ending in `?` is a
  tentative or partial read, drawn smaller and softer, and never recorded as
  a sighting;
- the chip is sized from its plate and sits just above it, so a distant
  vehicle gets a small label on its own bodywork rather than a large one over
  its neighbours; a read under 26 px on screen keeps its box but gets no
  label, since it would be illegible;
- labels are drawn after the snapshot is scaled down, so they stay the same
  readable size on any camera resolution.

A camera whose plates never confirm (too small, too blurred) therefore still
shows what OCR is reading, instead of looking like nothing is happening. The
worker also publishes `plates_reading` — vehicles being read right now but not
confirmed — which both consoles show next to the confirmed count.

### Stream transport and timestamp behaviour

**RTSP/TCP inference with HLS fallback:**

- The analytics supervisor prefers a registered RTSP endpoint and forces TCP
  through OpenCV's FFmpeg backend. This applies to catalogue and manually
  registered streams; workers never fall back to hard-coded camera discovery.
- When the same camera also has HLS, a failed RTSP open falls back to HLS. The
  HLS media playlist remains the authoritative
  `EXT-X-PROGRAM-DATE-TIME` anchor even while frames are decoded from RTSP.
- A manually registered RTSP-only stream can still publish detector telemetry,
  but cannot create timestamped sightings or alerts until an authoritative
  source-time mapping is available. The worker preserves packet timing and
  does not substitute frame-arrival time.

**Browser playback:**

- A browser cannot play raw RTSP. The focused Live player asks the authenticated
  backend for WHEP/WebRTC; FFmpeg pulls RTSP over TCP (or HLS if RTSP is absent),
  republishes it into local MediaMTX, and MediaMTX serves WebRTC to the browser.
- Grid tiles and the focused player's fallback remain HLS-based. An RTSP-only
  camera is therefore focusable but has no grid playback or HLS fallback if
  WebRTC negotiation fails.

**Live-state semantics:**

- The tile's "live" flag reflects the catalogue's `is_live` metadata and stored
  URL availability, **not** whether the player has actually buffered media.
- The UI displays `connected` only after the HLS player buffers a fragment.
- `Reconnecting` means the relay is retrying a failed or expired session.

### Stopping ANPR

Use the authenticated Live view's ANPR toggle to disable the worker.
Disabled workers do not queue; you can re-enable them anytime to start immediately
(if capacity is available) or queue them if at the limit.

## Person-counting worker

The optional person mode records periodic aggregate counts. It does not
identify people, create sightings, match watchlists, or create alerts.

Select Person mode in the authenticated Live view. The same role boundary
applies: a viewer may inspect status and detector output, while an operator
grant is required to start or stop the worker.

## Common failures

- **Worker not found:** create this directory's `.venv`; the backend resolves
  the worker interpreter from `multi-object-tracking/.venv`.
- **Catalogue unavailable:** confirm the authorised `SANDBOX_CATALOGUE_URL`
  in `backend/.env`, restart the backend, and re-run the registry sync.
- **`torch.cuda.is_available()` is `False`:** the worker will run on CPU and
  will not keep up with a live feed. Reinstall torch from the cu128 index --
  a plain `pip install torch` on Windows installs a CPU-only wheel silently.
  Do not compensate by opening multiple workers.
- **Plate ONNX reports only `CPUExecutionProvider`:** ANPR is running about 9x
  slower than it should (~90ms/crop instead of ~10ms), which on short looping
  clips also starves tracks of the frames they need to confirm a plate. See
  [../docs/platform-notes.md](../docs/platform-notes.md).
- **No sightings or alerts:** the worker may be healthy but have no confirmed
  readable plate yet, or the stream may lack an authoritative time anchor. A
  worker logging `confirmed but stream is not yet time-anchored; skipping
  report` is refusing to invent a timestamp, which is correct behaviour -- the
  fix is to give it an HLS source carrying program-date-time, not to relax the
  check. Check its log and telemetry before treating this as a failure.
- **Live tile says reconnecting:** the catalogue's `live` flag and a stored
  HLS URL are not proof of current browser playback. The Live view labels an
  active tile `connected` only after it buffers a media fragment; reconnecting
  means the relay is retrying a failed or expired stream session.

For the event semantics, timestamp anchoring, and known limitations, see
[`docs/anpr-pipeline-build-spec.md`](../docs/anpr-pipeline-build-spec.md).
