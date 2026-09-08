"""
Compare Car Tracking side-by-side using Ultralytics YOLO
======================================================
Tracks cars in two different videos simultaneously and displays them
side-by-side for comparison.

Usage:
    python compare_car_tracking.py --source1 video1.mp4 --source2 video2.mp4
"""

import argparse
from collections import defaultdict

import cv2
from ultralytics import YOLO

import tracking_common as tc
from car_tracking import VEHICLE_CLASSES, VEHICLE_COLORS, TRAIL_COLOR

# Each pane is scaled to this height before concatenation, so a 2556x1292 and a
# 848x480 source produce a window that actually fits on screen.
PANE_HEIGHT = 620


def parse_args():
    parser = argparse.ArgumentParser(description="Side-by-side vehicle tracking comparison")
    parser.add_argument("--source1", type=str, required=True, help="Path to first video file")
    parser.add_argument("--source2", type=str, required=True, help="Path to second video file")
    parser.add_argument(
        "--save", action="store_true",
        help="Save output video to compare_tracking_output.mp4",
    )
    tc.add_common_args(parser)
    return parser.parse_args()


def annotate(frame, result, track_history, frame_count, title):
    """Annotate a single pane in place. Returns the frame."""
    boxes, track_ids, class_ids, confs = tc.unpack_tracks(result)

    for box, track_id, cls_id, conf in zip(boxes, track_ids, class_ids, confs):
        x1, y1, x2, y2 = tc.xywh_to_corners(box)
        color = VEHICLE_COLORS.get(cls_id, (255, 255, 255))
        label = f"{VEHICLE_CLASSES.get(cls_id, 'vehicle')} #{track_id} {conf:.2f}"

        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        tc.draw_label(frame, x1, y1, color, label)

        track = track_history[track_id]
        track.append((float(box[0]), float(box[1])))
        tc.draw_trail(frame, track, TRAIL_COLOR)

    tc.draw_hud(frame, [f"[{title}] Frame: {frame_count} | Vehicles: {len(track_ids)}"])
    return frame


def to_pane(frame, height=PANE_HEIGHT):
    """Scale a frame to a fixed height, preserving aspect ratio."""
    h, w = frame.shape[:2]
    if h == height:
        return frame
    return cv2.resize(frame, (int(w * height / h), height),
                      interpolation=cv2.INTER_AREA)


def main():
    args = parse_args()

    device = tc.resolve_device(args.device)
    quantize, half = tc.resolve_quantize(args.no_half, device)

    print(f"[Compare Tracking] Source 1: {args.source1}")
    print(f"[Compare Tracking] Source 2: {args.source2}")
    print(f"[Compare Tracking] Model:    {args.model}")
    print(f"[Compare Tracking] Device:   {device} (fp16={half}, imgsz={args.imgsz})")

    # Two model instances keep the tracker states isolated; sharing one would
    # mix track IDs between the videos.
    model1 = YOLO(args.model)
    model2 = YOLO(args.model)

    reader1 = tc.FrameReader(args.source1, stride=args.vid_stride)
    reader2 = tc.FrameReader(args.source2, stride=args.vid_stride)

    if not reader1.is_opened():
        print(f"Error: Cannot open video 1 '{args.source1}'")
        return
    if not reader2.is_opened():
        print(f"Error: Cannot open video 2 '{args.source2}'")
        return

    fps = reader1.fps
    track_history1 = defaultdict(lambda: tc.new_trail(args.trail_length))
    track_history2 = defaultdict(lambda: tc.new_trail(args.trail_length))

    show = not args.benchmark
    window_name = "Side-by-Side Car Tracking Comparison"
    if show:
        tc.open_window(window_name, 1920, 720)
        print("[Compare Tracking] Press 'q' to quit")

    reader1.start()
    reader2.start()
    print("-" * 50)

    writer = None
    timing = tc.Timing()

    track_kwargs = dict(
        persist=True, tracker=args.tracker, conf=args.conf,
        classes=list(VEHICLE_CLASSES.keys()),
        device=device, quantize=quantize, imgsz=args.imgsz, verbose=False,
    )

    try:
        while True:
            frame1 = reader1.read()
            frame2 = reader2.read()
            if frame1 is None or frame2 is None:
                print("Reached end of one or both videos.")
                break
            timing.tick()

            with timing:
                result1 = model1.track(frame1, **track_kwargs)[0]
                result2 = model2.track(frame2, **track_kwargs)[0]

            if args.benchmark:
                if timing.frames % 50 == 0:
                    print(f"  {timing.frames} frames, {timing.infer_fps:.1f} FPS (inference)")
                continue

            annotate(frame1, result1, track_history1, timing.frames, "Video 1")
            annotate(frame2, result2, track_history2, timing.frames, "Video 2")

            # Scale to a common height only for display; inference saw full res.
            pane1 = to_pane(frame1)
            pane2 = to_pane(frame2)
            combined = cv2.hconcat([pane1, pane2])
            cv2.line(combined, (pane1.shape[1], 0),
                     (pane1.shape[1], combined.shape[0]), (255, 255, 255), 2)

            if args.save:
                if writer is None:
                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                    writer = cv2.VideoWriter(
                        "compare_tracking_output.mp4", fourcc, fps,
                        (combined.shape[1], combined.shape[0]),
                    )
                    print("[Compare Tracking] Saving to compare_tracking_output.mp4")
                writer.write(combined)

            cv2.imshow(window_name, combined)

            if tc.should_quit(window_name):
                break
    finally:
        reader1.stop()
        reader2.stop()
        if writer:
            writer.release()
        if show:
            cv2.destroyAllWindows()

    timing.report("Compare Tracking")


if __name__ == "__main__":
    main()
