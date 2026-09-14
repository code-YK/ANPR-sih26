"""
Audit a raw YOLO-format dataset before it is allowed into the training mix
==========================================================================
Answers, with numbers, the questions that decide whether a dataset helps or hurts:

  * What is really in it?     image/label counts, raw class counts, boxes per image,
                              image resolutions, Roboflow augmentation copies per original
  * What do its classes mean? baseline yolo11x "teacher" run on a random sample; a
                              raw-class x teacher-class matrix shows e.g. that class '5' is buses
  * Is it fully labelled?     teacher detections (conf >= --conf) that no ground-truth box
                              covers = likely unlabelled vehicles (rate per 100 GT boxes)
  * Are boxes tight?          mean IoU of matched ground-truth / teacher pairs
  * What does it look like?   contact sheets with the raw labels drawn

The teacher is a COCO model, so treat its numbers as estimates and run the same audit on
a trusted dataset (IDD) as the reference point. Outputs go to runs/inspect/<name>/.

    python scripts/inspect_source.py raw/night_thammasat --name thammasat
    python scripts/inspect_source.py raw/IDDDetectionsYOLODataset --name idd_reference --sample 300
"""

import argparse
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

import common as C
from prepare_dataset import RF_SUFFIX, load_yolo_names, stem_index, yolo_label_path

COCO_VEHICLES = {1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
PALETTE = [(60, 200, 60), (0, 140, 255), (255, 80, 80), (200, 60, 200), (0, 220, 220), (240, 240, 60),
           (120, 120, 255), (255, 160, 200)]


def parse_args():
    parser = argparse.ArgumentParser(description="Audit a raw YOLO dataset")
    parser.add_argument("roots", nargs="+", help="One or more folders holding the same dataset")
    parser.add_argument("--name", required=True)
    parser.add_argument("--sample", type=int, default=200, help="Images for the teacher audit")
    parser.add_argument("--teacher", default="yolo11x.pt")
    parser.add_argument("--imgsz", type=int, default=960)
    parser.add_argument("--conf", type=float, default=0.5)
    parser.add_argument("--sheets", type=int, default=2, help="Contact sheets of 3x3 labelled images")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--device", default=None)
    return parser.parse_args()


def collect(roots):
    """-> names, [(image, label_path_or_None)]; tolerates labels in mirrored, sibling or other roots."""
    names = None
    pairs = []
    label_index = {}
    for root in roots:
        try:
            names = names or load_yolo_names(root)[0]
        except SystemExit:
            pass
        label_index.update({k: v for k, v in stem_index(root, {".txt"}, exclude={"classes", "README"}).items()
                            if v is not None and not k.startswith("README")})
    if names is None:
        raise SystemExit("no data.yaml / classes.txt found in any root")
    for root in roots:
        for image in sorted(p for p in root.rglob("*") if p.suffix.lower() in C.IMG_EXTS):
            label = yolo_label_path(root, image.relative_to(root))
            pairs.append((image, label if label.exists() else label_index.get(image.stem)))
    return names, pairs


def read_raw(label, names):
    boxes = []
    if label is None:
        return boxes
    for line in Path(label).read_text(encoding="utf-8").splitlines():
        v = line.split()
        if len(v) < 5:
            continue
        idx, coords = int(float(v[0])), [float(x) for x in v[1:]]
        if len(coords) > 4:  # polygon
            xs, ys = coords[0::2], coords[1::2]
            coords = [(min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, max(xs) - min(xs), max(ys) - min(ys)]
        boxes.append((names[idx] if 0 <= idx < len(names) else f"idx{idx}", *coords[:4]))
    return boxes


def contact_sheet(pairs, names, path, rng):
    tiles = []
    for image, label in rng.sample(pairs, min(9, len(pairs))):
        img = cv2.imread(str(image))
        if img is None:
            continue
        h, w = img.shape[:2]
        for raw, cx, cy, bw, bh in read_raw(label, names):
            color = PALETTE[names.index(raw) % len(PALETTE)] if raw in names else (255, 255, 255)
            p1 = (int((cx - bw / 2) * w), int((cy - bh / 2) * h))
            p2 = (int((cx + bw / 2) * w), int((cy + bh / 2) * h))
            cv2.rectangle(img, p1, p2, color, max(1, w // 400))
            cv2.putText(img, str(raw), (p1[0], max(p1[1] - 3, 10)), cv2.FONT_HERSHEY_SIMPLEX,
                        max(0.4, w / 1600), color, max(1, w // 800), cv2.LINE_AA)
        tiles.append(cv2.resize(img, (640, 400)))
    while len(tiles) < 9:
        tiles.append(np.zeros((400, 640, 3), np.uint8))
    rows = [np.hstack(tiles[i:i + 3]) for i in range(0, 9, 3)]
    cv2.imwrite(str(path), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 85])


def main():
    args = parse_args()
    roots = [C.resolve(r) for r in args.roots]
    out = C.RUNS / "inspect" / args.name
    out.mkdir(parents=True, exist_ok=True)
    logger, log_path, file_handler = C.setup_logging(f"inspect_{args.name}")
    rng = random.Random(args.seed)

    names, pairs = collect(roots)
    missing = sum(1 for _, lbl in pairs if lbl is None)
    class_counts, per_image, empty = Counter(), [], 0
    originals = Counter(RF_SUFFIX.sub("", img.stem) for img, _ in pairs)
    for _, lbl in pairs:
        boxes = read_raw(lbl, names)
        per_image.append(len(boxes))
        empty += not boxes
        class_counts.update(b[0] for b in boxes)
    sizes = Counter()
    for image, _ in rng.sample(pairs, min(300, len(pairs))):
        with Image.open(image) as im:
            sizes[f"{im.size[0]}x{im.size[1]}"] += 1

    # Roboflow exports describe their augmentation; box-level transforms alter the object pixels
    # themselves (rotated/blurred patches with seams) and must be treated as a red flag.
    roboflow_notes = []
    for root in roots:
        for readme in root.rglob("README.roboflow.txt"):
            text = readme.read_text(encoding="utf-8", errors="ignore")
            if re.search(r"applied to the bounding boxes", text, re.IGNORECASE):
                roboflow_notes.append("BOUNDING-BOX-LEVEL augmentation (object pixels altered) -- inspect crops; "
                                      "usually reject or re-download an unaugmented version")
            if re.search(r"augmentation was applied to create (\d+) versions", text, re.IGNORECASE):
                roboflow_notes.append("image-level augmented copies -- use dedupe_augmented: true")
            if re.search(r"Resize to \d+x\d+ \(Stretch\)", text, re.IGNORECASE):
                roboflow_notes.append("images stretched to a fixed size (aspect ratio distorted)")
    for note in roboflow_notes:
        logger.warning("roboflow export: %s", note)

    report = {"roboflow_warnings": roboflow_notes,
              "roots": [str(r) for r in roots], "names": names, "images": len(pairs), "images_without_label": missing,
              "empty_label_images": empty, "class_counts": dict(class_counts),
              "boxes_per_image_mean": float(np.mean(per_image)) if per_image else 0.0,
              "unique_originals": len(originals),
              "copies_per_original": round(len(pairs) / max(len(originals), 1), 2),
              "resolutions_sample": dict(sizes.most_common(5))}
    logger.info("names %s", names)
    for k, v in report.items():
        if k not in ("roots", "names"):
            logger.info("%-22s %s", k, v)

    for i in range(args.sheets):
        contact_sheet(pairs, names, out / f"sheet_{i + 1}.jpg", rng)
    logger.info("contact sheets in %s", out)

    # ---- teacher audit
    if args.sample > 0:
        from ultralytics import YOLO

        C.attach_ultralytics_log(file_handler)
        teacher = YOLO(str(C.resolve_weights(args.teacher)))
        device = C.resolve_device(args.device)
        sample = rng.sample(pairs, min(args.sample, len(pairs)))
        matrix = defaultdict(Counter)     # raw GT class -> teacher class (or "none")
        unlabelled = Counter()            # teacher class -> detections with no GT under them
        teacher_total, gt_total, ious = Counter(), 0, []
        size_buckets = Counter()
        for start in range(0, len(sample), 8):
            chunk = sample[start:start + 8]
            results = teacher.predict([str(p[0]) for p in chunk], imgsz=args.imgsz, conf=args.conf,
                                      classes=sorted(COCO_VEHICLES), device=device, verbose=False)
            for (image, lbl), res in zip(chunk, results):
                h, w = res.orig_shape
                gts = read_raw(lbl, names)
                gt_total += len(gts)
                for g in gts:
                    area = g[3] * w * g[4] * h
                    size_buckets["small" if area < 32**2 else "medium" if area < 96**2 else "large"] += 1
                preds = [(COCO_VEHICLES[int(c)], *xywh) for xywh, c in
                         zip(res.boxes.xywhn.tolist(), res.boxes.cls.tolist())]
                # GT -> best teacher box
                for g in gts:
                    best = max(preds, key=lambda p: C.iou((0, *p[1:]), (0, *g[1:])), default=None)
                    v = C.iou((0, *best[1:]), (0, *g[1:])) if best else 0.0
                    if v >= 0.5:
                        matrix[g[0]][best[0]] += 1
                        ious.append(v)
                    else:
                        matrix[g[0]]["none"] += 1
                # teacher -> any GT
                for p in preds:
                    teacher_total[p[0]] += 1
                    cover = max((C.iou((0, *p[1:]), (0, *g[1:])) for g in gts), default=0.0)
                    inside = max((C.inter_over_first((0, *p[1:]), (0, *g[1:])) for g in gts), default=0.0)
                    if cover < 0.3 and inside < 0.6:
                        unlabelled[p[0]] += 1

        teacher_cols = ["car", "motorcycle", "bus", "truck", "bicycle", "none"]
        logger.info("teacher audit on %d images (conf >= %.2f), %d GT boxes", len(sample), args.conf, gt_total)
        logger.info("  GT class -> teacher class (IoU>=0.5); rows sum to that class's GT boxes in the sample")
        logger.info("  %-16s" + "%11s" * len(teacher_cols), "", *teacher_cols)
        for raw in sorted(matrix):
            logger.info("  %-16s" + "%11d" * len(teacher_cols), raw, *[matrix[raw][c] for c in teacher_cols])
        rate = {c: round(100 * unlabelled[c] / max(gt_total, 1), 1) for c in teacher_total}
        logger.info("  confident teacher detections with NO GT box under them (likely unlabelled): %s",
                    dict(unlabelled))
        logger.info("  ... per 100 GT boxes: %s", rate)
        logger.info("  mean IoU of matched GT/teacher pairs (box tightness): %.3f", float(np.mean(ious)) if ious else 0)
        logger.info("  GT size buckets: %s", dict(size_buckets))
        report["teacher_audit"] = {"sample_images": len(sample), "conf": args.conf, "gt_boxes": gt_total,
                                   "gt_to_teacher": {k: dict(v) for k, v in matrix.items()},
                                   "unlabelled_teacher_detections": dict(unlabelled),
                                   "unlabelled_per_100_gt": rate,
                                   "matched_mean_iou": float(np.mean(ious)) if ious else None,
                                   "gt_size_buckets": dict(size_buckets)}

    report["log"] = str(log_path)
    C.save_json(out / "inspect_report.json", report)
    logger.info("report %s", out / "inspect_report.json")


if __name__ == "__main__":
    main()
