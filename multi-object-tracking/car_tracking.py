"""
Car Tracking using Ultralytics YOLO
====================================
Tracks cars (and other vehicles) in a video using YOLO object detection
and multi-object tracking. Only COCO vehicle classes are visualized.

COCO vehicle class IDs:
    2  - car
    3  - motorcycle
    5  - bus
    7  - truck

Note: COCO has no auto-rickshaw class, so rickshaws are typically reported as
`bus` or `car`. Fine-tuning is the only fix if that matters.

Usage:
    python car_tracking.py                          # uses default video
    python car_tracking.py --source path/to/video.mp4
    python car_tracking.py --source 0               # webcam
    python car_tracking.py --tracker botsort.yaml   # switch tracker
    python car_tracking.py --benchmark              # no display, measure speed
"""

import argparse
from collections import defaultdict
from pathlib import Path

import cv2
from ultralytics import YOLO

import plates as plates_mod
import tracking_common as tc

# COCO class IDs for vehicles
VEHICLE_CLASSES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

# Distinct colors for each vehicle type (BGR)
VEHICLE_COLORS = {
    2: (0, 200, 255),   # car - orange
    3: (255, 100, 0),   # motorcycle - blue
    5: (0, 255, 100),   # bus - green
    7: (100, 0, 255),   # truck - purple
}

TRAIL_COLOR = (0, 180, 255)  # warm orange


def parse_args():
    parser = argparse.ArgumentParser(description="Car/Vehicle tracking with YOLO")
    parser.add_argument(
        "--source", type=str, default=None,
        help="Path to video file or camera index (default: auto-detect mp4 in current dir)",
    )
    parser.add_argument(
        "--save", action="store_true",
        help="Save output video to car_tracking_output.mp4",
    )
    plates_mod.add_plate_args(parser)
    tc.add_common_args(parser)
    return parser.parse_args()


def find_default_video():
    """Find the first .mp4 file in the current directory."""
    videos = list(Path(".").glob("*.mp4"))
    return str(videos[0]) if videos else "0"


PLATE_COLOR = (60, 230, 255)  # amber, distinct from the vehicle box colours


def draw_overlays(frame, result, track_history, trail_length, plate_reader=None):
    """Draw boxes, labels and trails onto `frame` in place. Returns count."""
    boxes, track_ids, class_ids, confs = tc.unpack_tracks(result)

    for box, track_id, cls_id, conf in zip(boxes, track_ids, class_ids, confs):
        x1, y1, x2, y2 = tc.xywh_to_corners(box)
        color = VEHICLE_COLORS.get(cls_id, (255, 255, 255))
        label = f"{VEHICLE_CLASSES.get(cls_id, 'vehicle')} #{track_id} {conf:.2f}"

        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        tc.draw_label(frame, x1, y1, color, label)

        if plate_reader is not None:
            plate, _, votes = plate_reader.consensus(track_id)
            if plate:
                # Confirmed plates are filled; tentative ones outlined with a
                # '?', so an unverified read never looks like established fact.
                confirmed = plate_reader.confirmed(track_id)[0] is not None
                tag = plate if confirmed else f"{plate}?"
                (tw, th), _ = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
                py = min(frame.shape[0] - 4, y2 + th + 8)
                cv2.rectangle(frame, (x1, py - th - 6), (x1 + tw + 8, py + 4),
                              PLATE_COLOR, -1 if confirmed else 1)
                cv2.putText(frame, tag, (x1 + 4, py),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                            (0, 0, 0) if confirmed else PLATE_COLOR, 2, cv2.LINE_AA)

        track = track_history[track_id]
        track.append((float(box[0]), float(box[1])))
        tc.draw_trail(frame, track, TRAIL_COLOR)

    return len(track_ids)


def main():
    args = parse_args()

    source = args.source if args.source else find_default_video()
    device = tc.resolve_device(args.device)
    quantize, half = tc.resolve_quantize(args.no_half, device)
    tc.describe("Car Tracking", source, args, device, half)

    model = YOLO(args.model)

    reader = tc.FrameReader(source, stride=args.vid_stride)
    if not reader.is_opened():
        print(f"Error: Cannot open video source '{source}'")
        return

    w, h, fps = reader.width, reader.height, reader.fps
    print(f"[Car Tracking] Input:   {w}x{h} @ {fps:.1f} fps")

    writer = None
    if args.save:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter("car_tracking_output.mp4", fourcc, fps, (w, h))
        print("[Car Tracking] Saving output to car_tracking_output.mp4")

    track_history = defaultdict(lambda: tc.new_trail(args.trail_length))

    plate_reader = plates_mod.build_reader(args, device, "Car Tracking")

    show = not args.benchmark
    window_name = "Car Tracking - YOLO"
    if show:
        tc.open_window(window_name)
        print("[Car Tracking] Press 'q' to quit")

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
                    classes=list(VEHICLE_CLASSES.keys()),
                    device=device,
                    quantize=quantize,
                    imgsz=args.imgsz,
                    verbose=False,
                )
            result = results[0]

            if plate_reader is not None:
                boxes, track_ids, _, _ = tc.unpack_tracks(result)
                # Plates are read before drawing so this frame's boxes can show
                # the updated consensus.
                plate_reader.read_vehicles(frame, boxes, track_ids,
                                           timing.frames, args.plate_every)

            if args.benchmark:
                if timing.frames % 50 == 0:
                    msg = f"  {timing.frames} frames, {timing.infer_fps:.1f} FPS (inference)"
                    if plate_reader is not None:
                        msg += (f", plates {plate_reader.accepted} ok"
                                f"/{plate_reader.attempted} run"
                                f"/{plate_reader.skipped} skipped")
                    print(msg)
                continue

            # Drawn in place; a full-resolution copy per frame bought nothing.
            count = draw_overlays(frame, result, track_history, args.trail_length,
                                  plate_reader)
            hud = [f"Frame: {timing.frames} | Vehicles: {count} | {timing.fps:.1f} FPS"]
            if plate_reader is not None:
                confirmed = sum(1 for r in plate_reader.summary() if r["confirmed"])
                hud.append(f"Plates: {confirmed} confirmed | "
                           f"{plate_reader.accepted} reads")
            tc.draw_hud(frame, hud, translucent=len(hud) > 1)

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

    timing.report("Car Tracking")

    plates_mod.print_summary(plate_reader, "Car Tracking")


if __name__ == "__main__":
    main()
