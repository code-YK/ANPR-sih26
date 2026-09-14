"""
Try out the fine-tuned vehicle model, separately from the production scripts
=============================================================================
A dedicated place to test `finetune/weights/*_best.pt` against a video,
entirely self-contained -- it does NOT import anything vehicle-class-related
from car_tracking.py, and does not touch it. car_tracking.py's own
VEHICLE_CLASSES stays hardcoded to COCO ids (2/3/5/7 = car/motorcycle/bus/
truck), which is correct for its default `yolo11x.pt` baseline and wrong for
this fine-tuned checkpoint -- see the note below. Swapping the fine-tuned
model into the production scripts is a separate decision this file doesn't
make; it's only for looking at what the model does first.

Why not just pass the fine-tuned model to car_tracking.py directly:
    The fine-tuned checkpoint's own class ids are 0=car, 1=motorcycle,
    2=bus, 3=truck, 4=auto_rickshaw (finetune/datasets/veh5/data.yaml) --
    different numbering from COCO. car_tracking.py's `classes=[2,3,5,7]`
    filter, read against THIS model, keeps only ids 2/3 (bus/truck; 5 and 7
    don't exist) and mislabels them using the COCO names dict (id 2 shown
    as "car" when it's actually this model's "bus", etc). That is why
    running the fine-tuned model through car_tracking.py unmodified shows
    almost nothing, and what little it shows is mislabeled. This script
    avoids that by reading the class id -> name mapping from the loaded
    model's own `model.names` at runtime instead of hardcoding it, so it
    is correct for whichever checkpoint --model points at.

Also tallies per-class detections across the whole run and prints a summary
at the end -- the quantity you actually want when *testing* a model, as
opposed to watching it live.

Relationship to the live "ANPR finetuned" feature (backend/app/routers/
analytics.py, frontend AnalyticsToggle.jsx): that feature runs the exact
same checkpoint through observation_worker.py -- for continuous, alerting
ANPR monitoring against real camera feeds -- while this script is for a
quick offline look at one video file, no backend/DB/camera registry
involved. Both read DEFAULT_FINETUNED_MODEL/_FINETUNED_VEHICLE_MODEL from
one place each; keep the two paths in sync if a new fine-tuning round
produces a different checkpoint. observation_worker.py fixes the same
class-id-mismatch problem described above the same way this script does
(model.names read at runtime, not hardcoded) -- car_tracking.py itself
remains untouched either way.

Usage:
    python test_finetuned.py                                   # ahmedabad.mp4, fine-tuned weights, display
    python test_finetuned.py --source path/to/video.mp4
    python test_finetuned.py --benchmark                        # no display, summary only
    python test_finetuned.py --save                             # writes test_finetuned_output.mp4
    python test_finetuned.py --model finetune/weights/other_best.pt   # a different checkpoint
    python test_finetuned.py --compare-baseline                 # also runs yolo11x.pt on the same video, prints both summaries
"""

import argparse
from collections import Counter, defaultdict
from pathlib import Path

import cv2
from ultralytics import YOLO

import plates as plates_mod
import tracking_common as tc

DEFAULT_FINETUNED_MODEL = "finetune/weights/yolo11x-veh5-960-20260913-232921_best.pt"
DEFAULT_SOURCE = "ahmedabad.mp4"

# Canonical vehicle class names this test script knows about, and their
# display color (BGR). Model-agnostic: works whether the loaded model's
# names come from COCO (4 of these) or a veh5 fine-tune (all 5, including
# auto_rickshaw) -- see build_vehicle_maps().
VEHICLE_COLORS_BY_NAME = {
    "car": (0, 200, 255),           # orange
    "motorcycle": (255, 100, 0),    # blue
    "bus": (0, 255, 100),           # green
    "truck": (100, 0, 255),         # purple
    "auto_rickshaw": (180, 0, 255), # magenta
}
TRAIL_COLOR = (0, 180, 255)  # warm orange


def build_vehicle_maps(model):
    """Derive {class_id: name} and {class_id: color} from a loaded model's own
    `model.names`, filtered to the vehicle classes this script knows about.

    Always call this after `YOLO(args.model)`, never hardcode ids: it is the
    only way the class filter/labels stay correct across a COCO baseline vs.
    a fine-tuned checkpoint with different class numbering (see module
    docstring for exactly how a hardcoded id mapping breaks here).
    """
    classes = {cid: name for cid, name in model.names.items() if name in VEHICLE_COLORS_BY_NAME}
    colors = {cid: VEHICLE_COLORS_BY_NAME[name] for cid, name in classes.items()}
    return classes, colors


def draw_overlays(frame, result, track_history, trail_length, vehicle_classes, vehicle_colors):
    """Draw boxes, labels and trails onto `frame` in place. Returns count."""
    boxes, track_ids, class_ids, confs = tc.unpack_tracks(result)

    for box, track_id, cls_id, conf in zip(boxes, track_ids, class_ids, confs):
        x1, y1, x2, y2 = tc.xywh_to_corners(box)
        color = vehicle_colors.get(cls_id, (255, 255, 255))
        label = f"{vehicle_classes.get(cls_id, 'vehicle')} #{track_id} {conf:.2f}"

        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        tc.draw_label(frame, x1, y1, color, label)

        track = track_history[track_id]
        track.append((float(box[0]), float(box[1])))
        tc.draw_trail(frame, track, TRAIL_COLOR)

    return len(track_ids)


def parse_args():
    parser = argparse.ArgumentParser(description="Test the fine-tuned vehicle model on a video")
    parser.add_argument(
        "--source", type=str, default=None,
        help=f"Path to video file or camera index (default: {DEFAULT_SOURCE} if present, else auto-detect)",
    )
    parser.add_argument(
        "--save", action="store_true",
        help="Save output video to test_finetuned_output.mp4",
    )
    parser.add_argument(
        "--compare-baseline", action="store_true",
        help="Also run the stock yolo11x.pt on the same video and print both summaries side by side "
             "(no display in this mode -- summary comparison only)",
    )
    plates_mod.add_plate_args(parser)
    tc.add_common_args(parser, default_model=DEFAULT_FINETUNED_MODEL)
    return parser.parse_args()


def find_source(explicit):
    if explicit:
        return explicit
    if Path(DEFAULT_SOURCE).exists():
        return DEFAULT_SOURCE
    videos = list(Path(".").glob("*.mp4"))
    return str(videos[0]) if videos else "0"


def run(model_path, source, args, device, quantize, show_window, writer_path=None):
    """One full pass over `source` with `model_path`. Returns (Counter of class -> detections,
    frames processed, mean track-confidence per class)."""
    model = YOLO(model_path)
    vehicle_classes, vehicle_colors = build_vehicle_maps(model)
    print(f"[Test] Model:   {model_path}")
    print(f"[Test] Classes: {vehicle_classes}")
    if not vehicle_classes:
        print("[Test] WARNING: none of this model's class names match car/motorcycle/bus/truck/"
              "auto_rickshaw -- check the checkpoint's model.names.")

    reader = tc.FrameReader(source, stride=args.vid_stride)
    if not reader.is_opened():
        print(f"[Test] Error: cannot open video source '{source}'")
        return Counter(), 0, {}

    w, h, fps = reader.width, reader.height, reader.fps
    print(f"[Test] Input:   {w}x{h} @ {fps:.1f} fps")

    writer = None
    if writer_path:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(writer_path, fourcc, fps, (w, h))
        print(f"[Test] Saving output to {writer_path}")

    track_history = defaultdict(lambda: tc.new_trail(args.trail_length))
    plate_reader = plates_mod.build_reader(args, device, "Test")

    window_name = f"Test Fine-tuned - {Path(model_path).name}"
    if show_window:
        tc.open_window(window_name)
        print("[Test] Press 'q' to quit")
    scale = tc.display_scale_for(w)

    class_counts = Counter()
    conf_sums = defaultdict(float)
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
                    classes=list(vehicle_classes.keys()),
                    device=device,
                    quantize=quantize,
                    imgsz=args.imgsz,
                    verbose=False,
                )
            result = results[0]

            _boxes, _track_ids, cls_ids, confs = tc.unpack_tracks(result)
            for cls_id, conf in zip(cls_ids, confs):
                name = vehicle_classes.get(cls_id, f"unmapped id {cls_id}")
                class_counts[name] += 1
                conf_sums[name] += conf

            if plate_reader is not None:
                boxes, track_ids, _, _ = tc.unpack_tracks(result)
                plate_reader.read_vehicles(frame, boxes, track_ids, timing.frames, args.plate_every)

            if args.benchmark or (not show_window and writer is None):
                if timing.frames % 50 == 0:
                    print(f"  {timing.frames} frames, {timing.infer_fps:.1f} FPS (inference), "
                          f"detections so far: {dict(class_counts)}")
                continue

            count = draw_overlays(frame, result, track_history, args.trail_length,
                                  vehicle_classes, vehicle_colors)
            hud = [f"Frame: {timing.frames} | Vehicles: {count} | {timing.fps:.1f} FPS"]
            tc.draw_hud(frame, hud)

            if writer:
                writer.write(frame)
            if show_window:
                tc.show(window_name, frame, scale)
                if tc.should_quit(window_name):
                    break
    finally:
        reader.stop()
        if writer:
            writer.release()
        if show_window:
            cv2.destroyAllWindows()

    timing.report(f"Test ({Path(model_path).name})")
    plates_mod.print_summary(plate_reader, "Test")

    mean_conf = {name: round(conf_sums[name] / n, 3) for name, n in class_counts.items()}
    return class_counts, timing.frames, mean_conf


def print_summary(title, counts, frames, mean_conf):
    print(f"\n[{title}] {frames} frames processed")
    if not counts:
        print(f"[{title}] No detections at all -- check --conf, the class mapping printed above, "
              f"and that the video actually contains these vehicle types.")
        return
    total = sum(counts.values())
    print(f"[{title}] {total} total detections:")
    for name, n in counts.most_common():
        print(f"    {name:15s} {n:6d}  ({100 * n / total:5.1f}%)  mean conf {mean_conf.get(name, 0):.3f}")


def main():
    args = parse_args()
    source = find_source(args.source)
    device = tc.resolve_device(args.device)
    quantize, half = tc.resolve_quantize(args.no_half, device)
    print(f"[Test] Source:  {source}")
    print(f"[Test] Device:  {device} (fp16={half}, imgsz={args.imgsz})")
    print("=" * 50)

    show_window = not args.benchmark and not args.compare_baseline
    writer_path = "test_finetuned_output.mp4" if args.save and not args.compare_baseline else None

    counts, frames, mean_conf = run(args.model, source, args, device, quantize, show_window, writer_path)
    print_summary(f"fine-tuned ({Path(args.model).name})", counts, frames, mean_conf)

    if args.compare_baseline:
        print("\n" + "=" * 50)
        base_counts, base_frames, base_mean_conf = run(
            "yolo11x.pt", source, args, device, quantize, show_window=False, writer_path=None)
        print_summary("baseline (yolo11x.pt)", base_counts, base_frames, base_mean_conf)

        print("\n" + "=" * 50)
        print(f"[Compare] {Path(args.model).name} vs baseline yolo11x.pt on {source}:")
        all_names = sorted(set(counts) | set(base_counts))
        for name in all_names:
            print(f"    {name:15s} fine-tuned {counts.get(name, 0):6d}   baseline {base_counts.get(name, 0):6d}")


if __name__ == "__main__":
    main()
