# Sentinel analytics workers

This directory contains the heavy, separate Python environment for the live
analytics workers. It is intentionally separate from `backend/.venv`: the
backend starts a worker as a subprocess and receives observations or aggregate
counts over HTTP.

Use the backend's analytics endpoints for normal operation. They select the
registered stream source, force RTSP/TCP when RTSP is used, and keep worker
lifecycle, logs, and the bounded concurrency limit visible to the operator
console.

## Prerequisites

- The backend is running and its database migrations have been applied.
- The authorised sandbox catalogue URL is configured in `backend/.env`, and
  the desired camera has been synchronised into the registry.
- `WORKER_API_TOKEN` is configured in `backend/.env`; the backend passes it
  to subprocesses as `SENTINEL_WORKER_API_TOKEN` so ingestion cannot reuse a
  human browser session.
- Python 3.13 and `ffmpeg` are available on `PATH`.

Do not put catalogue URLs, stream URLs, tokens, or observed identifiers in
this README, commands copied into Git, or worker logs.

## macOS / Apple Silicon setup

Create the worker environment from the repository root:

```zsh
cd multi-object-tracking
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install torch torchvision ultralytics opencv-python numpy fast-alpr onnxruntime
```

The checked-in `requirements.txt` includes CUDA packages for NVIDIA/Windows
development. Do not install it unchanged on macOS. PyTorch automatically uses
Apple Metal (`mps`) when it is available; `onnxruntime` is the portable OCR
runtime for this setup.

Verify the environment:

```zsh
python -c "import torch; print(torch.__version__); print('MPS available:', torch.backends.mps.is_available())"
```

The first worker start can download the YOLO model weights, so it may take
longer than later starts.

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
- **`MPS available: False`:** the worker will run on CPU and may not keep up
  with a live feed. Do not compensate by opening multiple workers.
- **No sightings or alerts:** the worker may be healthy but have no confirmed
  readable plate yet, or the stream may lack an authoritative time anchor.
  Check its log and telemetry before treating this as a failure.
- **Live tile says reconnecting:** the catalogue's `live` flag and a stored
  HLS URL are not proof of current browser playback. The Live view labels an
  active tile `connected` only after it buffers a media fragment; reconnecting
  means the relay is retrying a failed or expired stream session.

For the event semantics, timestamp anchoring, and known limitations, see
[`docs/model2-build-spec.md`](../docs/model2-build-spec.md).
