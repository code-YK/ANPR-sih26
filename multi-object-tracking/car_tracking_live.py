"""
Live Car Tracking from HLS camera feeds
=======================================
Runs the vehicle tracker directly against a live camera from the corp8 ingest
API. No download step: OpenCV/FFmpeg decodes the HLS stream in place.

Usage:
    python car_tracking_live.py                       # default camera
    python car_tracking_live.py --camera-id 14
    python car_tracking_live.py --url https://.../index.m3u8
    python car_tracking_live.py --list                # show available cameras
    python car_tracking_live.py --camera-id 16 --save

Notes:
    Live streams run at their own pace. If inference is slower than the feed,
    frames are dropped rather than queued, so the view stays current instead of
    drifting minutes behind. Watch the "dropped" counter in the HUD.

    Not every camera decodes; availability is intermittent. Use
    `python camera_feeds.py --probe` to find working ids.
"""

import argparse
import time
from collections import defaultdict

import cv2
from ultralytics import YOLO

import camera_feeds as feeds
import plates as plates_mod
import tracking_common as tc
from car_tracking import VEHICLE_CLASSES, draw_overlays

# Stream throughput varies wildly between cameras (3 FPS to 22 FPS measured on
# the same network). Use `camera_feeds.py --probe` to pick a healthy one.
DEFAULT_CAMERA = "4"


def parse_args():
    parser = argparse.ArgumentParser(description="Live vehicle tracking from HLS feeds")
    parser.add_argument("--camera-id", type=str, default=DEFAULT_CAMERA,
                        help=f"Camera id from the ingest API (default: {DEFAULT_CAMERA})")
    parser.add_argument("--url", type=str, default=None,
                        help="Stream URL to use directly, bypassing the API")
    parser.add_argument("--list", action="store_true",
                        help="List available cameras and exit")
    parser.add_argument("--save", action="store_true",
                        help="Save annotated output to car_live_output.mp4")
    parser.add_argument("--open-timeout", type=float, default=60.0,
                        help="Seconds to wait for the stream to open (default: 60)")
    parser.add_argument("--no-reconnect", action="store_true",
                        help="Exit on stream drop instead of reconnecting")
    parser.add_argument("--buffer", type=int, default=30,
                        help="Frames to hold before dropping. Frames arrive in "
                             "10s bursts, so a deeper buffer smooths the gap "
                             "between them at the cost of latency and RAM "
                             "(default: 30)")
    plates_mod.add_plate_args(parser)
    tc.add_common_args(parser)
    return parser.parse_args()


def main():
    args = parse_args()
    feeds.quiet_ffmpeg()

    if args.list:
        for c in feeds.fetch_cameras():
            print(feeds.describe_camera(c))
        return

    # Resolve the stream ------------------------------------------------
    if args.url:
        url, camera = args.url, None
        print("[Car Live] Stream: explicitly supplied endpoint (redacted)")
    else:
        try:
            url, camera = feeds.resolve_source(args.camera_id)
        except LookupError as e:
            print(f"Error: {e}")
            return
        except Exception as e:
            print(f"Error: could not reach the ingest API ({e})")
            return
        print(f"[Car Live] {feeds.describe_camera(camera)}")
        print("[Car Live] Stream: catalogue endpoint resolved (redacted)")

    device = tc.resolve_device(args.device)
    quantize, half = tc.resolve_quantize(args.no_half, device)
    print(f"[Car Live] Model:   {args.model}")
    print(f"[Car Live] Tracker: {args.tracker}")
    print(f"[Car Live] Device:  {device} (fp16={half}, imgsz={args.imgsz})")

    model = YOLO(args.model)

    print(f"[Car Live] Connecting (up to {args.open_timeout:.0f}s)...")
    reader = feeds.LiveFrameReader(url, buffer=args.buffer,
                                   reconnect=not args.no_reconnect)
    try:
        reader.open(timeout=args.open_timeout)
    except TimeoutError as e:
        print(f"Error: {e}")
        print("       This camera may be offline. Try: python camera_feeds.py --probe")
        return

    w, h = reader.width, reader.height
    print(f"[Car Live] Connected: {w}x{h} @ {reader.fps:.1f} fps")
    print(f"[Car Live] Buffer:    {args.buffer} frames "
          f"({feeds.buffer_advice(w, h, args.buffer)})")

    writer = None
    if args.save:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter("car_live_output.mp4", fourcc,
                                 reader.fps or 25.0, (w, h))
        print("[Car Live] Saving to car_live_output.mp4")

    track_history = defaultdict(lambda: tc.new_trail(args.trail_length))

    plate_reader = plates_mod.build_reader(args, device, "Car Live")

    show = not args.benchmark
    window_name = "Live Car Tracking - YOLO"
    if show:
        tc.open_window(window_name)
        print("[Car Live] Press 'q' to quit")

    scale = tc.display_scale_for(w)
    print("-" * 50)

    timing = tc.Timing()
    stall_since = None
    try:
        while True:
            status, frame = reader.poll()

            if status == "eos":
                print("Stream ended.")
                break

            if status == "waiting":
                # Keep the window alive through the stall so 'q' and the close
                # button still work; a stalled HLS segment can take 30s.
                if stall_since is None:
                    stall_since = time.time()
                if show:
                    if tc.should_quit(window_name):
                        break
                elif time.time() - stall_since > reader.stall_timeout:
                    print("Stream stalled; giving up.")
                    break
                continue

            if stall_since is not None:
                waited = time.time() - stall_since
                if waited > 2.0:
                    print(f"  ...stream stalled {waited:.0f}s, resumed")
                stall_since = None

            timing.tick()

            with timing:
                results = model.track(
                    frame,
                    persist=True,
                    tracker=args.tracker,
                    conf=args.conf,
                    classes=list(VEHICLE_CLASSES.keys()),
                    device=device,
                    quantize=quantize,
                    imgsz=args.imgsz,
                    verbose=False,
                )
            result = results[0]

            if plate_reader is not None:
                boxes, track_ids, _, _ = tc.unpack_tracks(result)
                # Read before drawing so this frame shows the updated consensus.
                plate_reader.read_vehicles(frame, boxes, track_ids,
                                           timing.frames, args.plate_every)

            if args.benchmark:
                if timing.frames % 50 == 0:
                    msg = (f"  {timing.frames} frames, {timing.infer_fps:.1f} FPS, "
                           f"{reader.dropped} dropped, {reader.reconnects} reconnects")
                    if plate_reader is not None:
                        msg += (f", plates {plate_reader.accepted} ok"
                                f"/{plate_reader.attempted} run"
                                f"/{plate_reader.skipped} skipped")
                    print(msg)
                continue

            count = draw_overlays(frame, result, track_history, args.trail_length,
                                  plate_reader)
            hud = [
                f"Frame: {timing.frames} | Vehicles: {count}",
                f"{timing.fps:.1f} FPS | dropped: {reader.dropped}",
                f"reconnects: {reader.reconnects}",
            ]
            if plate_reader is not None:
                nconf = sum(1 for r in plate_reader.summary() if r["confirmed"])
                hud.append(f"Plates: {nconf} confirmed | {plate_reader.accepted} reads")
            tc.draw_hud(frame, hud, translucent=True)

            if writer:
                writer.write(frame)
            tc.show(window_name, frame, scale)

            if tc.should_quit(window_name):
                break
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        reader.stop()
        if writer:
            writer.release()
        if show:
            cv2.destroyAllWindows()

    timing.report("Car Live")
    print(f"  Frames dropped:  {reader.dropped} (inference behind the stream)")
    print(f"  Reconnects:      {reader.reconnects}")
    plates_mod.print_summary(plate_reader, "Car Live")


if __name__ == "__main__":
    main()
