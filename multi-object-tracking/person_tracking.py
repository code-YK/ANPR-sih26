"""
Person Tracking using Ultralytics YOLO
========================================
Tracks people in a video using YOLO object detection and multi-object
tracking. Only COCO class 0 (person) is visualized.

Usage:
    python person_tracking.py                          # uses default video
    python person_tracking.py --source path/to/video.mp4
    python person_tracking.py --source 0               # webcam
    python person_tracking.py --tracker botsort.yaml   # switch tracker
    python person_tracking.py --benchmark              # no display, measure speed
"""

import argparse
from collections import defaultdict
from pathlib import Path

import cv2
from ultralytics import YOLO

import tracking_common as tc

# COCO class ID for person
PERSON_CLASS_ID = 0

# Color palette for different track IDs (BGR)
TRACK_COLORS = [
    (255, 100, 100),   # light blue
    (100, 255, 100),   # green
    (100, 100, 255),   # red
    (255, 255, 100),   # cyan
    (255, 100, 255),   # magenta
    (100, 255, 255),   # yellow
    (200, 150, 50),    # teal
    (50, 150, 200),    # orange-ish
    (180, 100, 220),   # purple
    (100, 220, 180),   # mint
]


def get_track_color(track_id: int) -> tuple:
    """Return a consistent color for a given track ID."""
    return TRACK_COLORS[track_id % len(TRACK_COLORS)]


def parse_args():
    parser = argparse.ArgumentParser(description="Person tracking with YOLO")
    parser.add_argument(
        "--source", type=str, default=None,
        help="Path to video file or camera index (default: auto-detect mp4 in current dir)",
    )
    parser.add_argument(
        "--save", action="store_true",
        help="Save output video to person_tracking_output.mp4",
    )
    tc.add_common_args(parser)
    return parser.parse_args()


def find_default_video():
    """Find the first .mp4 file in the current directory."""
    videos = list(Path(".").glob("*.mp4"))
    return str(videos[0]) if videos else "0"


def draw_overlays(frame, result, track_history, track_first_seen, frame_count, fps):
    """Draw boxes, labels and trails onto `frame` in place. Returns count."""
    boxes, track_ids, _, confs = tc.unpack_tracks(result)

    for box, track_id, conf in zip(boxes, track_ids, confs):
        cx, cy = float(box[0]), float(box[1])
        x1, y1, x2, y2 = tc.xywh_to_corners(box)

        if track_id not in track_first_seen:
            track_first_seen[track_id] = frame_count

        color = get_track_color(track_id)
        duration_sec = (frame_count - track_first_seen[track_id]) / fps
        label = f"Person #{track_id}"
        sublabel = f"{conf:.0%} | {duration_sec:.1f}s"

        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        tc.draw_label(frame, x1, y1, color, label, sublabel)
        cv2.circle(frame, (int(cx), int(cy)), 4, color, -1)

        track = track_history[track_id]
        track.append((cx, cy))
        tc.draw_trail(frame, track, color)

    return len(track_ids)


def main():
    args = parse_args()

    source = args.source if args.source else find_default_video()
    device = tc.resolve_device(args.device)
    quantize, half = tc.resolve_quantize(args.no_half, device)
    tc.describe("Person Tracking", source, args, device, half)

    model = YOLO(args.model)

    reader = tc.FrameReader(source, stride=args.vid_stride)
    if not reader.is_opened():
        print(f"Error: Cannot open video source '{source}'")
        return

    w, h, fps = reader.width, reader.height, reader.fps
    print(f"[Person Tracking] Input:   {w}x{h} @ {fps:.1f} fps")

    writer = None
    if args.save:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter("person_tracking_output.mp4", fourcc, fps, (w, h))
        print("[Person Tracking] Saving output to person_tracking_output.mp4")

    track_history = defaultdict(lambda: tc.new_trail(args.trail_length))
    track_first_seen = {}

    show = not args.benchmark
    window_name = "Person Tracking - YOLO"
    if show:
        tc.open_window(window_name)
        print("[Person Tracking] Press 'q' to quit")

    scale = tc.display_scale_for(w)
    reader.start()
    print("-" * 50)

    timing = tc.Timing()
    try:
        while True:
            frame = reader.read()
            if frame is None:
                break
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
                    print(f"  {timing.frames} frames, {timing.infer_fps:.1f} FPS (inference)")
                continue

            person_count = draw_overlays(
                frame, result, track_history, track_first_seen, timing.frames, fps
            )
            tc.draw_hud(frame, [
                f"Frame: {timing.frames}",
                f"People in frame: {person_count}",
                f"Total tracked: {len(track_first_seen)}",
                f"{timing.fps:.1f} FPS",
            ], translucent=True)

            if writer:
                writer.write(frame)
            tc.show(window_name, frame, scale)

            if tc.should_quit(window_name):
                break
    finally:
        reader.stop()
        if writer:
            writer.release()
        if show:
            cv2.destroyAllWindows()

    timing.report("Person Tracking")
    print(f"\n{'=' * 50}")
    print("[Person Tracking] Summary")
    print(f"{'=' * 50}")
    print(f"  Total frames processed: {timing.frames}")
    print(f"  Total unique people tracked: {len(track_first_seen)}")
    for tid, first_frame in sorted(track_first_seen.items()):
        duration = (timing.frames - first_frame) / fps
        print(f"    Person #{tid}: tracked for {duration:.1f}s")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
