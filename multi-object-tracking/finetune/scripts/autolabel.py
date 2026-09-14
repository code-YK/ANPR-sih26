"""
Fill in classes a source does not label, using the baseline yolo11x
===================================================================
A dataset that only boxes auto-rickshaws still contains cars, bikes, buses and
trucks. Left unboxed, training treats them as background and car recall drops.
For every manifest row whose labelled_classes is not "all", this adds baseline
COCO detections for the MISSING classes only, then:

  * skips a prediction that overlaps an existing box (IoU > --iou-skip): it is
    a duplicate, or COCO calling a labelled auto a "car"
  * skips a prediction that sits mostly inside a labelled auto
    (> --contain-skip of its area): COCO calling part of an auto a "motorcycle"

Idempotent: labels/ is always rebuilt from the untouched labels_src/, so
re-running with a different --conf is safe. Degraded copies (degrade.py) are
removed because their labels would go stale -- re-run degrade.py afterwards.

Spot-check the images it writes to datasets/veh5/review_autolabel/
(green = original labels, orange = added).

    python scripts/autolabel.py
"""

import argparse
import random
import shutil
from collections import Counter, defaultdict

import cv2

import common as C
from check_dataset import run_checks

GREEN, ORANGE = (60, 200, 60), (0, 140, 255)


def parse_args():
    parser = argparse.ArgumentParser(description="Auto-label missing vehicle classes with the baseline model")
    parser.add_argument("--dataset", default="datasets/veh5")
    parser.add_argument("--baseline", default="yolo11x.pt")
    parser.add_argument("--imgsz", type=int, default=960)
    parser.add_argument("--conf", type=float, default=0.40,
                        help="Higher = fewer wrong boxes but more missed vehicles (default 0.40)")
    parser.add_argument("--iou-skip", type=float, default=0.5)
    parser.add_argument("--contain-skip", type=float, default=0.7)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--review", type=int, default=60, help="Number of review images to draw")
    parser.add_argument("--device", default=None)
    return parser.parse_args()


def draw_review(ds, out_dir, samples, classes):
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    for image_rel, existing, added in samples:
        img = cv2.imread(str(ds / image_rel))
        if img is None:
            continue
        h, w = img.shape[:2]
        for boxes, color in ((existing, GREEN), (added, ORANGE)):
            for box in boxes:
                x1, y1, x2, y2 = C.to_xyxy(box)
                p1, p2 = (int(x1 * w), int(y1 * h)), (int(x2 * w), int(y2 * h))
                cv2.rectangle(img, p1, p2, color, 2)
                cv2.putText(img, classes.names[box[0]], (p1[0], max(p1[1] - 4, 12)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
        cv2.imwrite(str(out_dir / (image_rel.split("/")[-1].rsplit(".", 1)[0] + ".jpg")), img)


def main():
    args = parse_args()
    ds = C.resolve(args.dataset)
    classes = C.Classes()
    auto_id = classes.id("auto_rickshaw")
    rows = C.read_manifest(ds)
    logger, log_path, file_handler = C.setup_logging("autolabel")

    # Degraded copies carry labels derived from the current labels/ -- they'd go stale.
    removed = 0
    for sub in ("images", "labels"):
        for path in (ds / sub).rglob(f"*{C.DEGRADED_TAG}*"):
            path.unlink()
            removed += 1
    if removed:
        logger.info("removed %d degraded files; re-run scripts/degrade.py after this", removed)

    # Reset every label file from the pristine conversion.
    for r in rows:
        dst = C.label_path_for(ds, r["image"])
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(C.label_path_for(ds, r["image"], "labels_src"), dst)

    todo = defaultdict(list)
    for r in rows:
        if r["labelled_classes"] != "all":
            labelled = {classes.id(n) for n in r["labelled_classes"].split("|") if n}
            todo[tuple(i for i in range(len(classes.names)) if i not in labelled)].append(r)

    report = {"log": str(log_path), "args": vars(args), "images_processed": 0, "added_boxes": Counter(),
              "skipped_duplicate": 0, "skipped_inside_auto": 0}
    if not todo:
        logger.info("every source is labelled 'all' -- nothing to auto-label")
    else:
        from ultralytics import YOLO

        C.attach_ultralytics_log(file_handler)
        device = C.resolve_device(args.device)
        C.guard_gpu_memory(0.80, logger)
        model = YOLO(str(C.resolve_weights(args.baseline)))
        rng = random.Random(0)
        samples, seen_with_additions = [], 0

        for missing, group_rows in todo.items():
            coco = [classes.coco_ids[i] for i in missing if i in classes.coco_ids]
            logger.info("%d images missing %s -> predicting COCO ids %s",
                        len(group_rows), [classes.names[i] for i in missing], coco)
            if auto_id in missing:
                logger.warning("auto_rickshaw is missing for these images and cannot be auto-labelled")
            if not coco:
                continue

            for start in range(0, len(group_rows), args.batch):
                chunk = group_rows[start:start + args.batch]
                results = model.predict([str(ds / r["image"]) for r in chunk], imgsz=args.imgsz, conf=args.conf,
                                        classes=coco, device=device, verbose=False)
                for r, res in zip(chunk, results):
                    existing = C.read_labels(C.label_path_for(ds, r["image"], "labels_src"))
                    added = []
                    for (cx, cy, w, h), c in zip(res.boxes.xywhn.tolist(), res.boxes.cls.tolist()):
                        box = (classes.coco_to_id[int(c)], cx, cy, w, h)
                        if any(C.iou(box, e) > args.iou_skip for e in existing + added):
                            report["skipped_duplicate"] += 1
                        elif any(e[0] == auto_id and C.inter_over_first(box, e) > args.contain_skip
                                 for e in existing):
                            report["skipped_inside_auto"] += 1
                        else:
                            added.append(box)
                            report["added_boxes"][classes.names[box[0]]] += 1
                    C.write_labels(C.label_path_for(ds, r["image"]), existing + added)

                    report["images_processed"] += 1
                    if added:  # reservoir sample for the review folder
                        seen_with_additions += 1
                        if len(samples) < args.review:
                            samples.append((r["image"], existing, added))
                        elif (j := rng.randrange(seen_with_additions)) < args.review:
                            samples[j] = (r["image"], existing, added)
                if report["images_processed"] % 500 < args.batch:
                    logger.info("  %d images processed", report["images_processed"])

        draw_review(ds, ds / "review_autolabel", samples, classes)
        logger.info("added boxes %s | skipped duplicates %d | skipped inside autos %d",
                    dict(report["added_boxes"]), report["skipped_duplicate"], report["skipped_inside_auto"])
        logger.info("review %d samples in %s (green=original, orange=added)", len(samples), ds / "review_autolabel")

    report["added_boxes"] = dict(report["added_boxes"])
    C.save_json(ds / "autolabel_report.json", report)
    run_checks(ds, logger)
    logger.info("next: python scripts/degrade.py   (synthetic night/blur/IR copies of train)")


if __name__ == "__main__":
    main()
