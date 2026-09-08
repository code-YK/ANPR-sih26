"""
Headless suspicious-activity observation worker
===============================================
Runs the purpose-trained two-class person detector (best.pt: class 0
"normal_person", class 1 "potentially_dangerous_person") + tracking against
one live camera, with no display. Does two things:

  1. Publishes the same detector telemetry the other workers do (annotated
     frame + rolling counts) so the Live view's detector panel works for
     this mode exactly as it does for vehicle/person.
  2. Raises a standalone ALERT the first time a tracked person is classified
     as potentially dangerous for DANGER_CONFIRM_FRAMES consecutive frames
     -- POSTed to /api/alerts/suspicious (worker-token auth), deduplicated
     backend-side per (camera, track).

Modelled on person_observation_worker.py, and shares the same deliberate
scope limit: a person detection carries no identifier (no face recognition,
out of scope), so this never writes to /api/sightings, never matches a
watchlist, and never appears in a journey. It is a live suspicious-activity
signal for immediate operator review, nothing more.

The DANGER_CONFIRM_FRAMES gate exists so a single-frame misclassification on
one noisy frame cannot raise an alert: the tracker has to agree the same
person looks dangerous across a few frames first. It is the alerting analogue
of the ANPR path's confirmed/tentative plate split -- an uncorroborated
one-frame guess must never masquerade as a settled fact.

Usage:
    python suspicious_observation_worker.py --camera-id 26 --report-to http://127.0.0.1:8000
    python suspicious_observation_worker.py --camera-id 26 --report-to http://127.0.0.1:8000 --window-seconds 60
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
from worker_telemetry import TelemetryWriter

# best.pt's two classes. The checkpoint ships numeric ids only; these are the
# clear English display labels (same mapping as inference.py).
NORMAL_CLASS_ID = 0
DANGEROUS_CLASS_ID = 1
ENGLISH_LABELS = {
    NORMAL_CLASS_ID: "normal_person",
    DANGEROUS_CLASS_ID: "potentially_dangerous_person",
}
# Shorter labels for the on-frame detector view (drawn next to every box).
TELEMETRY_LABELS = {
    NORMAL_CLASS_ID: "person",
    DANGEROUS_CLASS_ID: "DANGER",
}
# BGR (OpenCV): normal green, dangerous red.
TELEMETRY_COLORS = {
    NORMAL_CLASS_ID: (0, 200, 0),
    DANGEROUS_CLASS_ID: (0, 0, 255),
}

# How many consecutive frames a track must be classified dangerous before it
# raises an alert. See the module docstring: this is the anti-false-positive
# gate, the alerting analogue of the plate confirmed/tentative split.
DANGER_CONFIRM_FRAMES = 3


def parse_args():
    parser = argparse.ArgumentParser(description="Headless suspicious-activity observation worker")
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
    tc.add_common_args(parser, default_model="best.pt")
    return parser.parse_args()


def _post_json(url, payload, tag):
    """POST one JSON body to the backend. Returns the parsed response dict,
    or None on failure (logged, never raised -- a dropped report must not
    kill a worker that is otherwise tracking fine)."""
    data = json.dumps(payload).encode("utf-8")
    worker_token = os.environ.get("SENTINEL_WORKER_API_TOKEN")
    headers = {"Content-Type": "application/json"}
    if worker_token:
        headers["X-Sentinel-Worker-Token"] = worker_token
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"  [{tag}] POST rejected: {e.code} {body[:300]}")
    except Exception as e:
        print(f"  [{tag}] POST failed: {e}")
    return None


def post_count(report_to, payload):
    return _post_json(report_to.rstrip("/") + "/api/analytics/counts", payload, "counts")


def post_suspicious_alert(report_to, payload):
    return _post_json(report_to.rstrip("/") + "/api/alerts/suspicious", payload, "alert")


def main():
    args = parse_args()
    feeds.quiet_ffmpeg()

    if args.url:
        url, camera = args.url, None
        print("[SuspiciousWorker] Stream: explicitly supplied endpoint (redacted)")
    else:
        try:
            url, camera = feeds.resolve_source(args.camera_id)
        except LookupError as e:
            print(f"Error: {e}")
            return
        except Exception as e:
            print(f"Error: could not reach the ingest API ({e})")
            return
        print(f"[SuspiciousWorker] {feeds.describe_camera(camera)}")
        print("[SuspiciousWorker] Stream: catalogue endpoint resolved (redacted)")

    device = tc.resolve_device(args.device)
    quantize, half = tc.resolve_quantize(args.no_half, device)
    print(f"[SuspiciousWorker] Camera:  {args.camera_id}")
    print(f"[SuspiciousWorker] Model:   {args.model}")
    print(f"[SuspiciousWorker] Tracker: {args.tracker}")
    print(f"[SuspiciousWorker] Device:  {device} (fp16={half}, imgsz={args.imgsz})")
    print(f"[SuspiciousWorker] Window:  {args.window_seconds:.0f}s")
    print(f"[SuspiciousWorker] Report:  {args.report_to}/api/analytics/counts + /api/alerts/suspicious")

    model = YOLO(args.model)
    # The checkpoint carries numeric ids; give it clear English names so any
    # native logging/plotting reads sensibly. Tracking still keys off the
    # numeric class ids (result.boxes.cls) regardless.
    model.model.names = ENGLISH_LABELS

    print(f"[SuspiciousWorker] Connecting (up to {args.open_timeout:.0f}s)...")
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

    print(f"[SuspiciousWorker] Connected over {reader.transport}: {reader.width}x{reader.height} @ {reader.fps:.1f} fps")

    telemetry = TelemetryWriter(
        args.camera_id, "suspicious", args.telemetry_dir,
        class_names=TELEMETRY_LABELS,
        class_colors=TELEMETRY_COLORS,
    )

    timing = tc.Timing()
    stall_since = None
    deadline = time.time() + args.duration if args.duration > 0 else None

    # Count window (all tracked people, same aggregate as person mode).
    window_track_ids = set()
    window_peak = 0
    window_start_seen_at = None
    next_flush_at = time.time() + args.window_seconds
    windows_posted = 0

    # Alerting state: how many consecutive frames each track has looked
    # dangerous, and which tracks have already raised an alert (so a track
    # alerts once, not once per frame).
    danger_streak = {}
    alerted_tracks = set()
    alerts_raised = 0

    def flush(end_seen_at):
        nonlocal window_track_ids, window_peak, window_start_seen_at, windows_posted
        # A window with zero people is a real measurement, not a gap -- post
        # it. Only skip when the window never got a valid time anchor at all.
        if window_start_seen_at is None or end_seen_at is None:
            window_track_ids, window_peak, window_start_seen_at = set(), 0, None
            return
        payload = {
            "camera_id": args.camera_id,
            "mode": "suspicious",
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
                print("[SuspiciousWorker] Duration reached, stopping.")
                break

            status, frame = reader.poll()

            if status == "eos":
                print("[SuspiciousWorker] Stream ended.")
                break

            if status == "waiting":
                if stall_since is None:
                    stall_since = time.time()
                elif time.time() - stall_since > reader.stall_timeout:
                    print("[SuspiciousWorker] Stream stalled; giving up.")
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
                    device=device, quantize=quantize, imgsz=args.imgsz, verbose=False,
                )
            result = results[0]
            boxes, track_ids, class_ids, confs = tc.unpack_tracks(result)

            if window_start_seen_at is None and reader.last_seen_at is not None:
                window_start_seen_at = reader.last_seen_at
            window_track_ids.update(track_ids)
            window_peak = max(window_peak, len(track_ids))

            # Update per-track dangerous streaks and raise alerts. A track
            # classified dangerous this frame extends its streak; anything
            # else (classified normal, or absent) resets it, so the streak
            # means "dangerous for the last N consecutive frames it appeared".
            dangerous_now = 0
            seen_this_frame = set()
            for track_id, cls_id, conf in zip(track_ids, class_ids, confs):
                seen_this_frame.add(track_id)
                if cls_id == DANGEROUS_CLASS_ID:
                    dangerous_now += 1
                    danger_streak[track_id] = danger_streak.get(track_id, 0) + 1
                    if (danger_streak[track_id] >= DANGER_CONFIRM_FRAMES
                            and track_id not in alerted_tracks):
                        seen_at = reader.last_seen_at
                        payload = {
                            "camera_id": args.camera_id,
                            "track_id": int(track_id),
                            "confidence": float(conf) if conf is not None else None,
                            "label": "Potentially dangerous person",
                            "severity": "high",
                        }
                        if seen_at is not None:
                            payload["event_time"] = seen_at.isoformat()
                        response = post_suspicious_alert(args.report_to, payload)
                        # Mark reported regardless of the POST outcome: the
                        # backend dedups too, and retrying every frame on a
                        # transient failure would spam it.
                        alerted_tracks.add(track_id)
                        if response is not None:
                            alerts_raised += 1
                            print(f"  [track {track_id}] DANGEROUS (conf={conf:.2f}) -> "
                                  f"alert {response.get('id')} [{response.get('status')}]")
                else:
                    danger_streak[track_id] = 0

            # Drop streak state for tracks that have left the scene so it does
            # not grow without bound on a busy junction.
            for gone in [t for t in danger_streak if t not in seen_this_frame]:
                danger_streak.pop(gone, None)

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
                    "resyncs": reader.resyncs,
                    "windows_posted": windows_posted,
                    "window_unique_tracks": len(window_track_ids),
                    "window_peak": window_peak,
                    # The suspicious-mode specials, surfaced in the detector
                    # view: how many are flagged dangerous right now, and how
                    # many alerts this worker has raised.
                    "dangerous_now": dangerous_now,
                    "alerts_raised": alerts_raised,
                    "time_anchored": reader.last_seen_at is not None,
                },
            )

            if timing.frames % 100 == 0:
                print(f"  {timing.frames} frames, {timing.infer_fps:.1f} FPS, "
                      f"{reader.dropped} dropped, {reader.reconnects} reconnects, "
                      f"{windows_posted} windows posted, {alerts_raised} alerts")
    except KeyboardInterrupt:
        print("\n[SuspiciousWorker] Interrupted.")
    finally:
        flush(reader.last_seen_at)
        reader.stop()
        telemetry.cleanup()

    timing.report("SuspiciousWorker")
    print(f"  Windows posted: {windows_posted}")
    print(f"  Alerts raised:  {alerts_raised}")


if __name__ == "__main__":
    main()
