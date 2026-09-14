"""
Turn your own camera recordings into a labelling-ready YOLO folder
==================================================================
Samples one frame every --every-sec seconds, skips near-identical frames
(static scene, no traffic), and optionally pre-labels car / motorcycle / bus /
truck with the baseline yolo11x so you only FIX boxes instead of drawing all.

The baseline calls most autos "car" or "motorcycle" -- while reviewing, change
those boxes to auto_rickshaw. That review is the whole point of this data.

Output (drop straight into raw/ and point sources.yaml at it):
    <out>/images/<video>_<frame>.jpg
    <out>/labels/<video>_<frame>.txt     (with --prelabel)
    <out>/classes.txt, <out>/data.yaml   (all 5 class names, in canonical order)

    python scripts/extract_frames.py ..\\..\\recorded-streams --out raw/own_cameras --prelabel
"""

import argparse
import re
from pathlib import Path

import cv2
import numpy as np

import common as C

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".ts", ".webm"}


def parse_args():
    parser = argparse.ArgumentParser(description="Extract frames from videos for labelling")
    parser.add_argument("videos", nargs="+", help="Video files and/or directories (searched recursively)")
    parser.add_argument("--out", default="raw/own_cameras")
    parser.add_argument("--every-sec", type=float, default=2.0)
    parser.add_argument("--min-diff", type=float, default=6.0,
                        help="Mean abs grey-level difference vs last kept frame; below = skipped as duplicate")
    parser.add_argument("--max-per-video", type=int, default=400)
    parser.add_argument("--prelabel", action="store_true")
    parser.add_argument("--baseline", default="yolo11x.pt")
    parser.add_argument("--conf", type=float, default=0.35)
    parser.add_argument("--imgsz", type=int, default=960)
    parser.add_argument("--device", default=None)
    return parser.parse_args()


def find_videos(inputs):
    for entry in inputs:
        path = Path(entry).resolve()
        if path.is_dir():
            yield from sorted(p for p in path.rglob("*") if p.suffix.lower() in VIDEO_EXTS)
        elif path.suffix.lower() in VIDEO_EXTS:
            yield path


def unique_prefix(video, taken):
    """Filename-safe, unique per video; stem_prefix grouping keys on it, so no trailing '_<digits>'."""
    base = re.sub(r"[^A-Za-z0-9-]+", "-", f"{video.parent.name}-{video.stem}").strip("-")
    prefix, n = base, 1
    while prefix in taken:
        n += 1
        prefix = f"{base}-v{n}"
    taken.add(prefix)
    return prefix


def extract(video, prefix, out_images, args, logger):
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        logger.warning("cannot open %s", video)
        return []
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(1, round(fps * args.every_sec))
    kept, last_small, idx = [], None, -1
    while len(kept) < args.max_per_video:
        if not cap.grab():
            break
        idx += 1
        if idx % step:
            continue
        ok, frame = cap.retrieve()
        if not ok:
            continue
        small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (160, 90)).astype(np.float32)
        if last_small is not None and np.abs(small - last_small).mean() < args.min_diff:
            continue
        last_small = small
        path = out_images / f"{prefix}_{idx:07d}.jpg"
        cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
        kept.append(path)
    cap.release()
    logger.info("%s: kept %d frames (every %d frames, fps %.1f)", video.name, len(kept), step, fps)
    return kept


def main():
    args = parse_args()
    classes = C.Classes()
    out = C.resolve(args.out)
    out_images, out_labels = out / "images", out / "labels"
    out_images.mkdir(parents=True, exist_ok=True)
    logger, _, file_handler = C.setup_logging("extract_frames")

    videos = list(find_videos(args.videos))
    if not videos:
        raise SystemExit("no videos found")
    taken = {p.stem.rsplit("_", 1)[0] for p in out_images.glob("*.jpg")}
    new_frames = []
    for video in videos:
        new_frames += extract(video, unique_prefix(video, taken), out_images, args, logger)

    (out / "classes.txt").write_text("\n".join(classes.names) + "\n", encoding="utf-8")
    C.save_yaml(out / "data.yaml", {"names": classes.names})

    if args.prelabel and new_frames:
        from ultralytics import YOLO

        C.attach_ultralytics_log(file_handler)
        device = C.resolve_device(args.device)
        C.guard_gpu_memory(0.80, logger)
        model = YOLO(str(C.resolve_weights(args.baseline)))
        for start in range(0, len(new_frames), 8):
            chunk = new_frames[start:start + 8]
            results = model.predict([str(p) for p in chunk], imgsz=args.imgsz, conf=args.conf,
                                    classes=sorted(classes.coco_ids.values()), device=device, verbose=False)
            for path, res in zip(chunk, results):
                C.write_labels(out_labels / (path.stem + ".txt"),
                               [(classes.coco_to_id[int(c)], *xywh)
                                for xywh, c in zip(res.boxes.xywhn.tolist(), res.boxes.cls.tolist())])
        logger.info("pre-labelled %d frames -- review them and relabel autos as auto_rickshaw", len(new_frames))

    logger.info("%d new frames in %s", len(new_frames), out)


if __name__ == "__main__":
    main()
