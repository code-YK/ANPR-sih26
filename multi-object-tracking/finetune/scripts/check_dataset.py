"""
Sanity-check a prepared dataset
===============================
Per-split image and box counts per class, empty/missing/invalid label files,
and group leakage across splits. Called automatically at the end of
prepare_dataset.py, autolabel.py and degrade.py; run it by hand any time:

    python scripts/check_dataset.py
"""

import argparse
from collections import Counter, defaultdict

import common as C

# Below these, per-class metrics are too noisy to trust.
MIN_TRAIN_BOXES = 1000
MIN_EVAL_BOXES = 150


def run_checks(ds_dir, logger):
    classes = C.Classes()
    ds_dir = C.resolve(ds_dir)
    rows = C.read_manifest(ds_dir)

    group_splits = defaultdict(set)
    for r in rows:
        group_splits[(r["source"], r["group"])].add(r["split"])
    leaks = sorted(f"{s}:{g} -> {sorted(sp)}" for (s, g), sp in group_splits.items() if len(sp) > 1)

    stats = {}
    for split_dir in sorted(p for p in (ds_dir / "images").iterdir() if p.is_dir()):
        split = split_dir.name
        s = {"images": 0, "degraded": 0, "empty": 0, "missing_label": 0, "invalid_lines": 0,
             "boxes": Counter()}
        for image in C.list_images(split_dir):
            s["images"] += 1
            s["degraded"] += C.DEGRADED_TAG in image.stem
            label = ds_dir / "labels" / split / (image.stem + ".txt")
            if not label.exists():
                s["missing_label"] += 1
                continue
            lines = [ln.split() for ln in label.read_text(encoding="utf-8").splitlines() if ln.strip()]
            if not lines:
                s["empty"] += 1
            for vals in lines:
                try:
                    cls, cx, cy, w, h = int(vals[0]), *map(float, vals[1:5])
                    ok = (len(vals) == 5 and 0 <= cls < len(classes.names) and w > 0 and h > 0
                          and cx - w / 2 >= -1e-3 and cx + w / 2 <= 1 + 1e-3
                          and cy - h / 2 >= -1e-3 and cy + h / 2 <= 1 + 1e-3)
                except (ValueError, IndexError):
                    ok = False
                if ok:
                    s["boxes"][classes.names[cls]] += 1
                else:
                    s["invalid_lines"] += 1
        stats[split] = s

    header = f"{'split':<18}{'images':>8}{'synth':>7}{'empty':>7}" + "".join(f"{n[:12]:>14}" for n in classes.names)
    logger.info("dataset check: %s", ds_dir)
    logger.info(header)
    for split, s in stats.items():
        logger.info(f"{split:<18}{s['images']:>8}{s['degraded']:>7}{s['empty']:>7}"
                    + "".join(f"{s['boxes'][n]:>14}" for n in classes.names))

    problems = 0
    for split, s in stats.items():
        if s["missing_label"] or s["invalid_lines"]:
            problems += 1
            logger.warning("%s: %d images without a label file, %d invalid label lines",
                           split, s["missing_label"], s["invalid_lines"])
        floor = MIN_TRAIN_BOXES if split == "train" else MIN_EVAL_BOXES
        if split in ("train", "val", "test") and s["images"]:
            thin = [n for n in classes.names if s["boxes"][n] < floor]
            if thin:
                logger.warning("%s: fewer than %d boxes for %s -- metrics/learning for these will be weak",
                               split, floor, thin)
    if leaks:
        problems += 1
        logger.warning("%d groups appear in more than one split (leakage), e.g. %s", len(leaks), leaks[:3])
    if not problems:
        logger.info("no structural problems found")

    C.save_json(ds_dir / "check_report.json",
                {"splits": {k: {**v, "boxes": dict(v["boxes"])} for k, v in stats.items()},
                 "group_leaks": leaks})
    return stats


def main():
    parser = argparse.ArgumentParser(description="Sanity-check a prepared dataset")
    parser.add_argument("--dataset", default="datasets/veh5")
    args = parser.parse_args()
    logger, _, _ = C.setup_logging("check")
    run_checks(args.dataset, logger)


if __name__ == "__main__":
    main()
