"""
Headless person-counting observation worker
=============================================
Runs person detection+tracking (person_tracking.py's PERSON_CLASS_ID) against
one live camera, with no display, and POSTs a periodic aggregate to the
registry backend: how many distinct people were tracked in the window, and
the peak number seen in a single frame.

Deliberately does NOT write to /api/sightings. A person detection carries no
identifier -- no face recognition, explicitly out of scope -- so it cannot
match a watchlist, cannot correlate across cameras, and cannot appear in a
journey. Forcing it into the plate-keyed sightings table would misrepresent
what was actually observed. This is GOV-FUN-013 (bonus) and must never
degrade the mandatory ANPR path -- enforced by the backend's shared
concurrency cap across both modes, not by anything in this script.

Usage:
    python person_observation_worker.py --camera-id 26 --report-to http://127.0.0.1:8000
    python person_observation_worker.py --camera-id 26 --report-to http://127.0.0.1:8000 --window-seconds 60
"""

import argparse
import json
import os
import time
import urllib.error
import urllib.request

from ultralytics import YOLO

import camera_feeds as feeds
import tracking_common as tc
from person_tracking import PERSON_CLASS_ID
from worker_telemetry import TelemetryWriter


def parse_args():
    parser = argparse.ArgumentParser(description="Headless person-counting observation worker")
    parser.add_argument("--camera-id", type=str, required=True,
                        help="Camera id from the ingest API")
    parser.add_argument("--url", type=str, default=None,
                        help="Stream URL to use directly, bypassing the API")
    parser.add_argument("--fallback-url", type=str, default=None,
                        help="Fallback stream endpoint if the primary cannot open")
    parser.add_argument("--timestamp-url", type=str, default=None,
                        help="HLS endpoint used only for program-date-time anchoring")
    parser.add_argument("--report-to", type=str, required=True,
                        help="Backend base URL, e.g. http://127.0.0.1:8000")
    parser.add_argument("--window-seconds", type=float, default=30.0,
                        help="Aggregation window before posting a count (default: 30)")
    parser.add_argument("--duration", type=float, default=0.0,
                        help="Stop after this many seconds (0 = run until killed)")
    parser.add_argument("--open-timeout", type=float, default=60.0,
                        help="Seconds to wait for the stream to open (default: 60)")
    parser.add_argument("--no-reconnect", action="store_true",
                        help="Exit on stream drop instead of reconnecting")
    parser.add_argument("--telemetry-dir", type=str, default="worker_logs",
                        help="Where to publish detector status/snapshot files "
                             "(default: worker_logs)")
    parser.add_argument("--buffer", type=int, default=30,
                        help="Frames to hold before dropping (default: 30)")
    tc.add_common_args(parser)
    return parser.parse_args()


def post_count(report_to, payload):
    """POST one window's aggregate to the backend. Returns the parsed
    response dict, or None on failure (logged, never raised)."""
    data = json.dumps(payload).encode("utf-8")
    worker_token = os.environ.get("SENTINEL_WORKER_API_TOKEN")
    headers = {"Content-Type": "application/json"}
    if worker_token:
        headers["X-Sentinel-Worker-Token"] = worker_token
    req = urllib.request.Request(
        report_to.rstrip("/") + "/api/analytics/counts",
        data=data,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"  [counts] POST rejected: {e.code} {body[:300]}")
    except Exception as e:
        print(f"  [counts] POST failed: {e}")
    return None


def main():
    args = parse_args()
    feeds.quiet_ffmpeg()

    if args.url:
        url, camera = args.url, None
        print("[PersonWorker] Stream: explicitly supplied endpoint (redacted)")
    else:
        try:
            url, camera = feeds.resolve_source(args.camera_id)
        except LookupError as e:
            print(f"Error: {e}")
            return
        except Exception as e:
            print(f"Error: could not reach the ingest API ({e})")
            return
        print(f"[PersonWorker] {feeds.describe_camera(camera)}")
        print("[PersonWorker] Stream: catalogue endpoint resolved (redacted)")

    device = tc.resolve_device(args.device)
    quantize, half = tc.resolve_quantize(args.no_half, device)
    print(f"[PersonWorker] Camera:  {args.camera_id}")
    print(f"[PersonWorker] Model:   {args.model}")
    print(f"[PersonWorker] Tracker: {args.tracker}")
    print(f"[PersonWorker] Device:  {device} (fp16={half}, imgsz={args.imgsz})")
    print(f"[PersonWorker] Window:  {args.window_seconds:.0f}s")
    print(f"[PersonWorker] Report:  {args.report_to}/api/analytics/counts")

    model = YOLO(args.model)

    print(f"[PersonWorker] Connecting (up to {args.open_timeout:.0f}s)...")
    reader = feeds.LiveFrameReader(
        url,
        buffer=args.buffer,
        reconnect=not args.no_reconnect,
        fallback_url=args.fallback_url,
        timestamp_url=args.timestamp_url,
    )
    try:
        reader.open(timeout=args.open_timeout)
    except TimeoutError as e:
        print(f"Error: {e}")
        print("       This camera may be offline. Try: python camera_feeds.py --probe")
        return

    print(f"[PersonWorker] Connected over {reader.transport}: {reader.width}x{reader.height} @ {reader.fps:.1f} fps")

    # Person detection is a single class, so every box is a "person"; colour
    # comes from person_tracking's per-track palette instead of a class map.
    telemetry = TelemetryWriter(
        args.camera_id, "person", args.telemetry_dir,
        class_names={PERSON_CLASS_ID: "person"},
        class_colors={PERSON_CLASS_ID: (0, 220, 255)},
    )

    timing = tc.Timing()
    stall_since = None
    deadline = time.time() + args.duration if args.duration > 0 else None

    window_track_ids = set()
    window_peak = 0
    window_start_seen_at = None
    next_flush_at = time.time() + args.window_seconds
    windows_posted = 0

    def flush(end_seen_at):
        nonlocal window_track_ids, window_peak, window_start_seen_at, windows_posted
        # A window with zero people is a real measurement (the camera was
        # watched and nobody was there), not a gap -- post it. Only skip when
        # the window never got a valid time anchor at all, i.e. the stream
        # never actually delivered a frame in this window.
        if window_start_seen_at is None or end_seen_at is None:
            window_track_ids, window_peak, window_start_seen_at = set(), 0, None
            return
        payload = {
            "camera_id": args.camera_id,
            "mode": "person",
            "window_start": window_start_seen_at.isoformat(),
            "window_end": end_seen_at.isoformat(),
            "unique_tracks": len(window_track_ids),
            "peak_concurrent": window_peak,
        }
        response = post_count(args.report_to, payload)
        if response is not None:
            windows_posted += 1
            print(f"  [window] {len(window_track_ids)} unique, {window_peak} peak -> counts {response.get('id')}")
        window_track_ids, window_peak, window_start_seen_at = set(), 0, None

    print("-" * 50)
    try:
        while True:
            if deadline is not None and time.time() >= deadline:
                print("[PersonWorker] Duration reached, stopping.")
                break

            status, frame = reader.poll()

            if status == "eos":
                print("[PersonWorker] Stream ended.")
                break

            if status == "waiting":
                if stall_since is None:
                    stall_since = time.time()
                elif time.time() - stall_since > reader.stall_timeout:
                    print("[PersonWorker] Stream stalled; giving up.")
                    break
                if time.time() >= next_flush_at:
                    flush(reader.last_seen_at)
                    next_flush_at = time.time() + args.window_seconds
                continue

            if stall_since is not None:
                waited = time.time() - stall_since
                if waited > 2.0:
                    print(f"  ...stream stalled {waited:.0f}s, resumed")
                stall_since = None

            timing.tick()

            with timing:
                results = model.track(
                    frame, persist=True, tracker=args.tracker, conf=args.conf,
                    classes=[PERSON_CLASS_ID], device=device,
                    quantize=quantize, imgsz=args.imgsz, verbose=False,
                )
            result = results[0]
            boxes, track_ids, class_ids, confs = tc.unpack_tracks(result)

            if window_start_seen_at is None and reader.last_seen_at is not None:
                window_start_seen_at = reader.last_seen_at
            window_track_ids.update(track_ids)
            window_peak = max(window_peak, len(track_ids))

            if time.time() >= next_flush_at:
                flush(reader.last_seen_at)
                next_flush_at = time.time() + args.window_seconds

            telemetry.update(
                frame, boxes, track_ids, class_ids, confs,
                extra={
                    "source_transport": reader.transport,
                    "fps": round(timing.infer_fps, 1),
                    "dropped_frames": reader.dropped,
                    "reconnects": reader.reconnects,
                    # See observation_worker.py: reconnects made to return to
                    # the live edge, as opposed to ones forced by a drop.
                    "resyncs": reader.resyncs,
                    "windows_posted": windows_posted,
                    "window_unique_tracks": len(window_track_ids),
                    "window_peak": window_peak,
                    "time_anchored": reader.last_seen_at is not None,
                },
            )

            if timing.frames % 100 == 0:
                print(f"  {timing.frames} frames, {timing.infer_fps:.1f} FPS, "
                      f"{reader.dropped} dropped, {reader.reconnects} reconnects, "
                      f"{windows_posted} windows posted")
    except KeyboardInterrupt:
        print("\n[PersonWorker] Interrupted.")
    finally:
        flush(reader.last_seen_at)
        reader.stop()
        telemetry.cleanup()

    timing.report("PersonWorker")
    print(f"  Windows posted: {windows_posted}")


if __name__ == "__main__":
    main()
