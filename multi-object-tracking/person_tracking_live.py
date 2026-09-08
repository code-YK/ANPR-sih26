"""
Live Person Tracking from HLS camera feeds
==========================================
Runs the person tracker directly against a live camera from the corp8 ingest
API. No download step: OpenCV/FFmpeg decodes the HLS stream in place.

Usage:
    python person_tracking_live.py                    # default camera
    python person_tracking_live.py --camera-id 14
    python person_tracking_live.py --url https://.../index.m3u8
    python person_tracking_live.py --list             # show available cameras
    python person_tracking_live.py --camera-id 16 --tracker botsort.yaml

Notes:
    Live streams run at their own pace. If inference is slower than the feed,
    frames are dropped rather than queued, so the view stays current instead of
    drifting minutes behind. Watch the "dropped" counter in the HUD.

    ID counts on live CCTV are optimistic: ByteTrack fragments identities badly
    on moving or crowded scenes. `--tracker botsort.yaml` fragments less at a
    speed cost; stable cross-camera identity needs a ReID stage.
"""

import argparse
import time
from collections import defaultdict

import cv2
from ultralytics import YOLO

import camera_feeds as feeds
import tracking_common as tc
from person_tracking import PERSON_CLASS_ID, draw_overlays

# Stream throughput varies wildly between cameras (3 FPS to 22 FPS measured on
# the same network). Use `camera_feeds.py --probe` to pick a healthy one.
DEFAULT_CAMERA = "26"


def parse_args():
    parser = argparse.ArgumentParser(description="Live person tracking from HLS feeds")
    parser.add_argument("--camera-id", type=str, default=DEFAULT_CAMERA,
                        help=f"Camera id from the ingest API (default: {DEFAULT_CAMERA})")
    parser.add_argument("--url", type=str, default=None,
                        help="Stream URL to use directly, bypassing the API")
    parser.add_argument("--list", action="store_true",
                        help="List available cameras and exit")
    parser.add_argument("--save", action="store_true",
                        help="Save annotated output to person_live_output.mp4")
    parser.add_argument("--open-timeout", type=float, default=60.0,
                        help="Seconds to wait for the stream to open (default: 60)")
    parser.add_argument("--no-reconnect", action="store_true",
                        help="Exit on stream drop instead of reconnecting")
    parser.add_argument("--buffer", type=int, default=30,
                        help="Frames to hold before dropping. Frames arrive in "
                             "10s bursts, so a deeper buffer smooths the gap "
                             "between them at the cost of latency and RAM "
                             "(default: 30)")
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
        print("[Person Live] Stream: explicitly supplied endpoint (redacted)")
    else:
        try:
            url, camera = feeds.resolve_source(args.camera_id)
        except LookupError as e:
            print(f"Error: {e}")
            return
        except Exception as e:
            print(f"Error: could not reach the ingest API ({e})")
            return
        print(f"[Person Live] {feeds.describe_camera(camera)}")
        print("[Person Live] Stream: catalogue endpoint resolved (redacted)")

    device = tc.resolve_device(args.device)
    quantize, half = tc.resolve_quantize(args.no_half, device)
    print(f"[Person Live] Model:   {args.model}")
    print(f"[Person Live] Tracker: {args.tracker}")
    print(f"[Person Live] Device:  {device} (fp16={half}, imgsz={args.imgsz})")

    model = YOLO(args.model)

    print(f"[Person Live] Connecting (up to {args.open_timeout:.0f}s)...")
    reader = feeds.LiveFrameReader(url, buffer=args.buffer,
                                   reconnect=not args.no_reconnect)
    try:
        reader.open(timeout=args.open_timeout)
    except TimeoutError as e:
        print(f"Error: {e}")
        print("       This camera may be offline. Try: python camera_feeds.py --probe")
        return

    w, h = reader.width, reader.height
    fps = reader.fps or 25.0
    print(f"[Person Live] Connected: {w}x{h} @ {fps:.1f} fps")
    print(f"[Person Live] Buffer:    {args.buffer} frames "
          f"({feeds.buffer_advice(w, h, args.buffer)})")

    writer = None
    if args.save:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter("person_live_output.mp4", fourcc, fps, (w, h))
        print("[Person Live] Saving to person_live_output.mp4")

    track_history = defaultdict(lambda: tc.new_trail(args.trail_length))
    track_first_seen = {}

    show = not args.benchmark
    window_name = "Live Person Tracking - YOLO"
    if show:
        tc.open_window(window_name)
        print("[Person Live] Press 'q' to quit")

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
                    classes=[PERSON_CLASS_ID],
                    device=device,
                    quantize=quantize,
                    imgsz=args.imgsz,
                    verbose=False,
                )
            result = results[0]

            if args.benchmark:
                if timing.frames % 50 == 0:
                    print(f"  {timing.frames} frames, {timing.infer_fps:.1f} FPS, "
                          f"{reader.dropped} dropped, {reader.reconnects} reconnects")
                continue

            person_count = draw_overlays(
                frame, result, track_history, track_first_seen, timing.frames, fps
            )
            tc.draw_hud(frame, [
                f"Frame: {timing.frames}",
                f"People in frame: {person_count}",
                f"Total tracked: {len(track_first_seen)}",
                f"{timing.fps:.1f} FPS | dropped: {reader.dropped}",
                f"reconnects: {reader.reconnects}",
            ], translucent=True)

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

    timing.report("Person Live")
    print(f"  Unique people:   {len(track_first_seen)}")
    print(f"  Frames dropped:  {reader.dropped} (inference behind the stream)")
    print(f"  Reconnects:      {reader.reconnects}")


if __name__ == "__main__":
    main()
