"""
Headless ANPR observation worker
=================================
Runs vehicle detection+tracking (car_tracking.py) and plate reading (plates.py)
against one live camera, with no display, and POSTs a sighting to the registry
backend the first time a track's plate becomes CONFIRMED (plates.PlateReader's
own corroborated, unrepaired-format-match bar -- see plates.py's docstring).

Deliberately reports only on first confirmation, not every accepted read or
every frame: PlateVote already does the consensus/voting work, so reporting
every intermediate read would let unvalidated OCR output masquerade as a
settled fact in the registry -- exactly what plates.py's confirmed/tentative
split exists to prevent.

seen_at/frame_pts_ms/epoch_id come from camera_feeds.LiveFrameReader's
ProgramDateTimeAnchor (see camera_feeds.py for why this is anchored PTS, not
datetime.now()). If a stream is never successfully anchored (every playlist
fetch failed), seen_at is sent as null and the backend rejects the sighting
rather than inventing a timestamp.

Alongside sightings this also POSTs a periodic vehicle count to
/api/analytics/counts with mode="vehicle", exactly as
person_observation_worker.py does for people. The two report different
things and both are needed: a sighting fires once per track and only on a
CONFIRMED plate, so sightings systematically undercount traffic -- every
vehicle whose plate was never readable (angle, glare, dirt, motorcycle at
distance) is invisible in that stream. The count is every tracked vehicle
regardless of plate readability. Holding both lets the backend report the
per-camera read yield (sightings/unique_tracks) instead of presenting a
plate-conditioned undercount as though it were traffic volume.

Usage:
    python observation_worker.py --camera-id 21 --report-to http://127.0.0.1:8000
    python observation_worker.py --camera-id 21 --report-to http://127.0.0.1:8000 --duration 300
"""

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

import cv2
from ultralytics import YOLO

import camera_feeds as feeds
import plates as plates_mod
import tracking_common as tc
from car_tracking import VEHICLE_CLASSES, VEHICLE_COLORS
from worker_telemetry import TelemetryWriter


def parse_args():
    parser = argparse.ArgumentParser(description="Headless ANPR observation worker")
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
    parser.add_argument("--duration", type=float, default=0.0,
                        help="Stop after this many seconds (0 = run until killed)")
    parser.add_argument("--window-seconds", type=float, default=30.0,
                        help="Aggregation window before posting a vehicle count "
                             "(default: 30). Matches person_observation_worker.")
    parser.add_argument("--open-timeout", type=float, default=60.0,
                        help="Seconds to wait for the stream to open (default: 60)")
    parser.add_argument("--no-reconnect", action="store_true",
                        help="Exit on stream drop instead of reconnecting")
    parser.add_argument("--buffer", type=int, default=30,
                        help="Frames to hold before dropping (default: 30)")
    parser.add_argument("--telemetry-dir", type=str, default="worker_logs",
                        help="Where to publish detector status/snapshot files "
                             "(default: worker_logs)")
    parser.add_argument("--evidence-dir", type=str, default=None,
                        help="Absolute path to write per-sighting evidence crops "
                             "under (Section 5 Phase 3). Omit to skip evidence "
                             "capture entirely -- a sighting still reports fine "
                             "with no evidence_path.")
    plates_mod.add_plate_args(parser)
    tc.add_common_args(parser)
    args = parser.parse_args()
    args.plates = True  # this worker exists to read plates; always on
    return args


def _post_json(report_to, path, payload, tag):
    """POST one payload to the backend. Returns the parsed response dict, or
    None on failure (logged, never raised -- a dropped report should not kill
    a worker that is otherwise tracking fine)."""
    data = json.dumps(payload).encode("utf-8")
    worker_token = os.environ.get("SENTINEL_WORKER_API_TOKEN")
    headers = {"Content-Type": "application/json"}
    if worker_token:
        headers["X-Sentinel-Worker-Token"] = worker_token
    req = urllib.request.Request(
        report_to.rstrip("/") + path,
        data=data,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"  [{tag}] POST rejected: {e.code} {body[:300]}")
    except Exception as e:
        print(f"  [{tag}] POST failed: {e}")
    return None


def post_sighting(report_to, payload):
    """POST one confirmed-plate sighting."""
    return _post_json(report_to, "/api/sightings", payload, "sightings")


def post_count(report_to, payload):
    """POST one window's vehicle-count aggregate."""
    return _post_json(report_to, "/api/analytics/counts", payload, "counts")


def confirmed_confidence(plate_reader, track_id, text):
    """Average OCR confidence across the reads that contributed to `text`.

    PlateVote.consensus()'s own score is a confidence-weighted, edit-discounted
    sum across votes (not bounded to [0, 1]), so it is not a meaningful
    confidence value on its own -- this averages the raw per-read OCR
    confidences instead, which is what the sightings.confidence column means
    elsewhere in this registry.
    """
    vote = plate_reader.votes.get(track_id)
    if vote is None:
        return None
    matching = [conf for t, conf, _w, _e in vote.reads if t == text]
    return sum(matching) / len(matching) if matching else None


def box_to_bbox_and_crop(frame, box):
    """xywh box -> (bbox dict in pixel coords, cropped ndarray or None).

    Same xywh->xyxy clamp as PlateReader.read_vehicles -- kept separate
    since that method only returns the crop, not the coordinates the
    evidence record also needs.
    """
    h, w = frame.shape[:2]
    x, y, bw, bh = box
    x1, y1 = max(0, int(x - bw / 2)), max(0, int(y - bh / 2))
    x2, y2 = min(w, int(x + bw / 2)), min(h, int(y + bh / 2))
    bbox = {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "frame_width": w, "frame_height": h}
    if x2 - x1 < 2 or y2 - y1 < 2:
        return bbox, None
    return bbox, frame[y1:y2, x1:x2]


def write_evidence_crop(evidence_dir, camera_id, track_id, seen_at, crop):
    """Write one evidence crop to <evidence_dir>/<camera_id>/....jpg.

    Returns the path relative to evidence_dir (what the backend stores as
    sightings.evidence_path), or None if there's nowhere to write it or
    nothing worth writing.
    """
    if evidence_dir is None or crop is None:
        return None
    rel_name = f"{camera_id}/track-{track_id}-{int(seen_at.timestamp() * 1000)}.jpg"
    out_path = Path(evidence_dir) / rel_name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(out_path), crop):
        return None
    return rel_name


def main():
    args = parse_args()
    feeds.quiet_ffmpeg()

    if args.url:
        url, camera = args.url, None
        print("[Worker] Stream: explicitly supplied endpoint (redacted)")
    else:
        try:
            url, camera = feeds.resolve_source(args.camera_id)
        except LookupError as e:
            print(f"Error: {e}")
            return
        except Exception as e:
            print(f"Error: could not reach the ingest API ({e})")
            return
        print(f"[Worker] {feeds.describe_camera(camera)}")
        print("[Worker] Stream: catalogue endpoint resolved (redacted)")

    device = tc.resolve_device(args.device)
    quantize, half = tc.resolve_quantize(args.no_half, device)
    print(f"[Worker] Camera:  {args.camera_id}")
    print(f"[Worker] Model:   {args.model}")
    print(f"[Worker] Tracker: {args.tracker}")
    print(f"[Worker] Device:  {device} (fp16={half}, imgsz={args.imgsz})")
    print(f"[Worker] Window:  {args.window_seconds:.0f}s")
    print(f"[Worker] Report:  {args.report_to}/api/sightings")
    print(f"[Worker] Counts:  {args.report_to}/api/analytics/counts (mode=vehicle)")

    model = YOLO(args.model)

    print(f"[Worker] Connecting (up to {args.open_timeout:.0f}s)...")
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

    print(f"[Worker] Connected over {reader.transport}: {reader.width}x{reader.height} @ {reader.fps:.1f} fps")

    plate_reader = plates_mod.build_reader(args, device, "Worker")
    reported_tracks = set()  # track_ids already POSTed, so a track reports once

    telemetry = TelemetryWriter(
        args.camera_id, "vehicle", args.telemetry_dir,
        class_names=VEHICLE_CLASSES, class_colors=VEHICLE_COLORS,
    )

    timing = tc.Timing()
    stall_since = None
    deadline = time.time() + args.duration if args.duration > 0 else None
    accepted_alerts = 0

    window_track_ids = set()
    window_peak = 0
    window_start_seen_at = None
    next_flush_at = time.time() + args.window_seconds
    windows_posted = 0

    def flush(end_seen_at):
        nonlocal window_track_ids, window_peak, window_start_seen_at, windows_posted
        # A window with zero vehicles is a real measurement (the camera was
        # watched and the road was empty), not a gap -- post it. Only skip
        # when the window never got a valid time anchor, i.e. the stream
        # never delivered an anchored frame in this window.
        if window_start_seen_at is None or end_seen_at is None:
            window_track_ids, window_peak, window_start_seen_at = set(), 0, None
            return
        payload = {
            "camera_id": args.camera_id,
            "mode": "vehicle",
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
                print("[Worker] Duration reached, stopping.")
                break

            status, frame = reader.poll()

            if status == "eos":
                print("[Worker] Stream ended.")
                break

            if status == "waiting":
                if stall_since is None:
                    stall_since = time.time()
                elif time.time() - stall_since > reader.stall_timeout:
                    print("[Worker] Stream stalled; giving up.")
                    break
                # Keep posting windows through a stall so a gap in the count
                # series means "camera not watched", not "worker busy".
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
            pts_ms, epoch_id, seen_at = reader.last_pts_ms, reader.last_epoch_id, reader.last_seen_at

            with timing:
                results = model.track(
                    frame, persist=True, tracker=args.tracker, conf=args.conf,
                    classes=list(VEHICLE_CLASSES.keys()), device=device,
                    quantize=quantize, imgsz=args.imgsz, verbose=False,
                )
            result = results[0]
            boxes, track_ids, class_ids, confs = tc.unpack_tracks(result)

            # Count every tracked vehicle, before any plate gate -- this is
            # the denominator the sighting count is measured against.
            if window_start_seen_at is None and seen_at is not None:
                window_start_seen_at = seen_at
            window_track_ids.update(track_ids)
            window_peak = max(window_peak, len(track_ids))

            if time.time() >= next_flush_at:
                flush(seen_at)
                next_flush_at = time.time() + args.window_seconds

            plate_reader.read_vehicles(frame, boxes, track_ids, timing.frames, args.plate_every)

            # Show whatever the plate reader currently believes, marked by
            # status: a confirmed read is a settled fact, a tentative one is
            # explicitly suffixed "?" so the detector view can never make an
            # uncorroborated OCR guess look like an identification.
            plate_labels = {}
            for track_id in track_ids:
                text, _score, _votes = plate_reader.confirmed(track_id)
                if text is not None:
                    plate_labels[track_id] = text
                    continue
                tentative, _tscore, _tvotes = plate_reader.consensus(track_id)
                if tentative:
                    plate_labels[track_id] = f"{tentative}?"

            telemetry.update(
                frame, boxes, track_ids, class_ids, confs,
                sublabels=plate_labels,
                extra={
                    "fps": round(timing.infer_fps, 1),
                    "dropped_frames": reader.dropped,
                    "reconnects": reader.reconnects,
                    # Reconnects specifically to get back to the live edge,
                    # rather than because the stream dropped -- distinguishes
                    # "this camera is flaky" from "this camera outruns us".
                    "resyncs": reader.resyncs,
                    "plates_reported": len(reported_tracks),
                    "alerts_raised": accepted_alerts,
                    "windows_posted": windows_posted,
                    "window_unique_tracks": len(window_track_ids),
                    "window_peak": window_peak,
                    "time_anchored": seen_at is not None,
                    "source_transport": reader.transport,
                    # How many already-decoded frames are queued waiting for
                    # inference right now -- the honest "how far behind live
                    # is this worker" number. Rises during a catch-up burst
                    # after a stream stall; a sustained near-full queue means
                    # decode/inference genuinely can't keep up with this
                    # camera's rate, not just absorbing a transient stall.
                    "queue_depth": reader.queue.qsize(),
                    "queue_capacity": args.buffer,
                    # How far behind real time the frame just processed is,
                    # measured the same way the browser player measures
                    # itself (hls.js `.latency`): distance from the live
                    # edge. seen_at comes from the stream's own
                    # EXT-X-PROGRAM-DATE-TIME anchor, so this is the
                    # stream's clock, not a guess. Comparing this against
                    # the player's "live -Ns" badge is what tells you
                    # whether the detector is behind because inference is
                    # slow or because its *reader* has drifted off the live
                    # edge -- two completely different problems.
                    "stream_lag_seconds": (
                        round(time.time() - seen_at.timestamp(), 1) if seen_at else None
                    ),
                },
            )

            for box, track_id, cls_id in zip(boxes, track_ids, class_ids):
                if track_id in reported_tracks:
                    continue
                text, _score, votes = plate_reader.confirmed(track_id)
                if text is None:
                    continue

                if seen_at is None:
                    print(f"  [track {track_id}] plate {text} confirmed but stream "
                          f"is not yet time-anchored; skipping report")
                    continue

                # Do not mark the track reported until the source timestamp
                # exists. At HLS startup a plate can be confirmed before the
                # first program-date-time fetch succeeds; marking it first
                # meant the worker silently lost the only report for that
                # vehicle even though later frames were correctly anchored.
                reported_tracks.add(track_id)

                raw_text, _raw_conf, _raw_width = plate_reader.best_evidence(track_id)
                bbox, crop = box_to_bbox_and_crop(frame, box)
                evidence_path = write_evidence_crop(args.evidence_dir, args.camera_id, track_id, seen_at, crop)

                payload = {
                    "camera_id": args.camera_id,
                    "plate": text,
                    "vehicle_type": VEHICLE_CLASSES.get(cls_id),
                    "confidence": confirmed_confidence(plate_reader, track_id, text),
                    "seen_at": seen_at.isoformat(),
                    "frame_pts_ms": int(pts_ms) if pts_ms is not None else None,
                    "epoch_id": epoch_id,
                    "raw_ocr_text": raw_text,
                    "bbox": bbox,
                    "model_version": args.model,
                    "evidence_path": evidence_path,
                }
                response = post_sighting(args.report_to, payload)
                if response is not None:
                    tag = "ALERT" if response.get("alert_id") else "ok"
                    if response.get("alert_id"):
                        accepted_alerts += 1
                    print(f"  [track {track_id}] plate {text} (votes={votes}) -> "
                          f"sighting {response.get('sighting_id')} [{tag}]")

            if timing.frames % 100 == 0:
                print(f"  {timing.frames} frames, {timing.infer_fps:.1f} FPS, "
                      f"{reader.dropped} dropped, {reader.reconnects} reconnects, "
                      f"{len(reported_tracks)} plates reported, {accepted_alerts} alerts")
    except KeyboardInterrupt:
        print("\n[Worker] Interrupted.")
    finally:
        flush(reader.last_seen_at)
        reader.stop()
        # A snapshot left behind by a dead worker would show a stopped
        # detector as if it were still watching.
        telemetry.cleanup()

    timing.report("Worker")
    print(f"  Plates reported: {len(reported_tracks)}")
    print(f"  Alerts raised:   {accepted_alerts}")
    print(f"  Windows posted:  {windows_posted}")


if __name__ == "__main__":
    main()
