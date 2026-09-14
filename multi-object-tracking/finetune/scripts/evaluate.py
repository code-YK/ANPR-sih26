"""
Evaluate a fine-tuned model against the baseline yolo11x on held-out data
=========================================================================
Two families of metrics, per class and overall, for both models:

  Threshold-free (standard benchmark numbers, from Ultralytics val at conf=0.001)
    precision, recall, F1   at the confidence that maximises mean F1
    mAP50                   PASCAL-VOC style AP at IoU 0.50
    mAP75                   strict localisation, IoU 0.75
    mAP50-95                COCO primary metric, mean AP over IoU 0.50:0.05:0.95
    confusion matrix        plots + raw counts in report.json

  Operating point (what the tracker actually sees at --op-conf, default 0.30 = tracker --conf)
    TP / FP / FN, precision, recall, F1
    mean IoU of true positives (localisation quality)
    recall / precision by object size (COCO buckets: small < 32^2 px, medium < 96^2, large)
    auto_rickshaw confusion: what the model calls the autos it gets wrong

  Speed: preprocess / inference / postprocess ms per image.

Baseline fairness: the COCO model has no auto_rickshaw class, so autos are removed
from its ground truth. If it calls an auto a "car" that is a false positive -- the
error the tracker logs today.

Outputs runs/eval/<timestamp>_<split>[_<sources>]/ report.md, report.json, new/ and baseline/ plots.

    python scripts/evaluate.py --model weights/<run>_best.pt
    python scripts/evaluate.py --model weights/<run>_best.pt --sources dawn_fog dawn_rain   # weather subset
    python scripts/evaluate.py --model weights/<run>_best.pt --split test_low_light          # synthetic
    python scripts/evaluate.py --model weights/<run>_best.pt --split bench_night --recall-only
                                                           # real night CCTV + IR, incomplete labels

--recall-only is for benchmarks whose labels are known to be INCOMPLETE (bench_night):
unlabelled vehicles would count as false positives, so precision / mAP / F1 are
meaningless there, but recall of the vehicles that ARE labelled is still valid.
bus and truck are scored as one group (the source only labels "heavy vehicle"),
and results are broken down into IR (greyscale) vs colour frames.
"""

import argparse
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

import common as C

SIZE_BUCKETS = (("small", 0, 32**2), ("medium", 32**2, 96**2), ("large", 96**2, float("inf")))
RECALL_GROUPS = {"car": {"car"}, "motorcycle": {"motorcycle"}, "bus/truck": {"bus", "truck"},
                 "auto_rickshaw": {"auto_rickshaw"}}


def parse_args():
    parser = argparse.ArgumentParser(description="Evaluate fine-tuned vs baseline model")
    parser.add_argument("--model", help="Fine-tuned weights (default: newest file in weights/)")
    parser.add_argument("--baseline", default="yolo11x.pt")
    parser.add_argument("--no-baseline", action="store_true")
    parser.add_argument("--dataset", default="datasets/veh5")
    parser.add_argument("--split", default="test", help="Any folder under images/, e.g. test, val, test_low_light")
    parser.add_argument("--sources", nargs="+", help="Only images from these manifest sources, e.g. idd dawn_fog")
    parser.add_argument("--imgsz", type=int, default=960)
    parser.add_argument("--batch", type=int, default=2, help="2 is safe on the 8 GB laptop with yolo11x (decision.md D7)")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--max-vram-fraction", type=float, default=0.80)
    parser.add_argument("--device", default=None)
    parser.add_argument("--op-conf", type=float, default=0.30, help="Operating confidence (tracker --conf)")
    parser.add_argument("--match-iou", type=float, default=0.50, help="IoU for a TP at the operating point")
    parser.add_argument("--auto-gate", type=float, default=0.60,
                        help="Min auto_rickshaw mAP50; IDD has many tiny distant autos, see README")
    parser.add_argument("--tolerance", type=float, default=0.01)
    parser.add_argument("--recall-only", action="store_true",
                        help="Benchmark with incomplete labels: report recall only (bus+truck merged, IR vs colour)")
    return parser.parse_args()


# --------------------------------------------------------------------------
# Recall-only benchmark (incompletely labelled data)
# --------------------------------------------------------------------------

def is_greyscale(path):
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        return False
    small = cv2.resize(img, (64, 36), interpolation=cv2.INTER_AREA).astype(np.int16)
    return float(np.abs(small[..., 0] - small[..., 1]).mean() + np.abs(small[..., 1] - small[..., 2]).mean()) < 4.0


def recall_benchmark(model, images, ds, split, class_names, args, device, coco_classes=None):
    """Recall of labelled vehicles, class-aware (bus/truck merged) and class-agnostic, per IR / colour."""
    group_of = {c: g for g, members in RECALL_GROUPS.items() for c in members}
    stats = {kind: defaultdict(lambda: {"gt": 0, "found_right_class": 0, "found_any_class": 0})
             for kind in ("all", "ir", "colour")}
    frames = Counter()
    for start in range(0, len(images), args.batch):
        chunk = images[start:start + args.batch]
        results = model.predict([str(p) for p in chunk], imgsz=args.imgsz, conf=args.op_conf, iou=0.7,
                                classes=coco_classes, device=device, verbose=False)
        for img, res in zip(chunk, results):
            kind = "ir" if is_greyscale(img) else "colour"
            frames[kind] += 1
            preds = sorted(((model.names[int(c)], (0, *xywh), conf) for xywh, c, conf in
                            zip(res.boxes.xywhn.tolist(), res.boxes.cls.tolist(), res.boxes.conf.tolist())),
                           key=lambda p: -p[2])
            used_class, used_any = set(), set()
            for gt in C.read_labels(ds / "labels" / split / (img.stem + ".txt")):
                group = group_of[class_names[gt[0]]]
                box = (0, *gt[1:])
                right = next((i for i, p in enumerate(preds) if i not in used_class
                              and group_of.get(p[0]) == group and C.iou(p[1], box) >= args.match_iou), None)
                anyc = next((i for i, p in enumerate(preds) if i not in used_any
                             and C.iou(p[1], box) >= args.match_iou), None)
                for k in ("all", kind):
                    s = stats[k][group]
                    s["gt"] += 1
                    s["found_right_class"] += right is not None
                    s["found_any_class"] += anyc is not None
                if right is not None:
                    used_class.add(right)
                if anyc is not None:
                    used_any.add(anyc)
    out = {"frames": dict(frames)}
    for kind, groups in stats.items():
        out[kind] = {}
        total = {"gt": 0, "found_right_class": 0, "found_any_class": 0}
        for g, s in groups.items():
            out[kind][g] = {**s, "recall": s["found_right_class"] / s["gt"] if s["gt"] else None,
                            "recall_any_class": s["found_any_class"] / s["gt"] if s["gt"] else None}
            for k in total:
                total[k] += s[k]
        if total["gt"]:
            out[kind]["all vehicles"] = {**total, "recall": total["found_right_class"] / total["gt"],
                                         "recall_any_class": total["found_any_class"] / total["gt"]}
    return out


def run_recall_only(args, model_path, images, ds, classes, device, out, logger, log_path):
    from ultralytics import YOLO

    logger.info("recall-only benchmark (labels incomplete: precision/mAP not computed)")
    model = YOLO(str(model_path))
    result = {"model": str(model_path), "split": args.split, "images": len(images), "op_conf": args.op_conf,
              "match_iou": args.match_iou, "log": str(log_path),
              "new": recall_benchmark(model, images, ds, args.split, classes.names, args, device)}
    del model
    C.free_gpu()  # one model on the GPU at a time
    if not args.no_baseline:
        baseline = YOLO(str(C.resolve_weights(args.baseline)))
        result["baseline"] = recall_benchmark(baseline, images, ds, args.split, classes.names, args, device,
                                              coco_classes=sorted(classes.coco_ids.values()))
        del baseline
        C.free_gpu()

    L = [f"# Recall benchmark: `{model_path.name}` on `{args.split}`", "",
         f"{len(images)} images ({result['new']['frames']}). Operating conf {args.op_conf}, IoU ≥ {args.match_iou}.",
         "Labels in this benchmark are **incomplete**, so only recall is meaningful. bus and truck are one group.",
         "`recall` = found with the right class group; `any class` = found, whatever class was predicted.", ""]
    for kind in ("all", "colour", "ir"):
        rows = result["new"].get(kind, {})
        if not rows:
            continue
        L += [f"## {kind} frames", "", "| group | GT | recall | any class | base recall | base any class |",
              "|---|---:|---:|---:|---:|---:|"]
        for g, s in rows.items():
            b = result.get("baseline", {}).get(kind, {}).get(g, {})
            fmt_r = lambda v: "-" if v is None else f"{v:.3f}"
            L.append(f"| {g} | {s['gt']} | {fmt_r(s['recall'])} | {fmt_r(s['recall_any_class'])} | "
                     f"{fmt_r(b.get('recall'))} | {fmt_r(b.get('recall_any_class'))} |")
        L.append("")
    (out / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    C.save_json(out / "report.json", result)
    for line in L:
        logger.info(line)
    logger.info("report: %s", out / "report.md")


# --------------------------------------------------------------------------
# Evaluation views (hardlinked images + labels in the id space of each model)
# --------------------------------------------------------------------------

def select_images(ds, split, sources):
    images = C.list_images(ds / "images" / split)
    if not sources:
        return images
    # synthetic splits (test_low_light) keep the original stems, so map by stem
    source_of = {Path(r["image"]).stem: r["source"] for r in C.read_manifest(ds)}
    unknown = set(sources) - set(source_of.values())
    if unknown:
        raise SystemExit(f"unknown sources {sorted(unknown)}; manifest has {sorted(set(source_of.values()))}")
    return [p for p in images if source_of.get(p.stem.split(C.DEGRADED_TAG)[0]) in sources]


def build_view(view, images, ds, split, convert):
    """view/images/eval + view/labels/eval, labels passed through convert(boxes)."""
    for img in images:
        C.link_or_copy(img, view / "images" / "eval" / img.name)
        boxes = C.read_labels(ds / "labels" / split / (img.stem + ".txt"))
        C.write_labels(view / "labels" / "eval" / (img.stem + ".txt"), convert(boxes))
    C.save_yaml(view / "data.yaml", {"path": str(view), "train": "images/eval", "val": "images/eval"})
    return view


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------

def threshold_free(metrics, key_of):
    """Ultralytics DetMetrics -> {class: {...}, "all": {...}} with P, R, F1, mAP50, mAP75, mAP50-95."""
    box, rows = metrics.box, {}
    nt = getattr(metrics, "nt_per_class", None)
    for i, c in enumerate(box.ap_class_index):
        key = key_of(int(c))
        if key is None:
            continue
        p, r, ap50, ap = box.class_result(i)
        rows[key] = {"instances": int(nt[int(c)]) if nt is not None else None, "precision": float(p),
                     "recall": float(r), "F1": float(box.f1[i]), "mAP50": float(ap50),
                     "mAP75": float(box.all_ap[i][5]), "mAP50-95": float(ap)}
    if rows:
        rows["all"] = {k: sum(v[k] for v in rows.values()) / len(rows)
                       for k in ("precision", "recall", "F1", "mAP50", "mAP75", "mAP50-95")}
    return rows


def match_image(gts, preds, iou_thr):
    """Greedy class-aware matching. gts [(cls,cx,cy,w,h)], preds [(cls,cx,cy,w,h,conf)] -> (tps, fps, fns)."""
    used, tps, fps = set(), [], []
    for pred in sorted(preds, key=lambda p: -p[5]):
        best, best_iou = None, iou_thr
        for j, gt in enumerate(gts):
            if j not in used and gt[0] == pred[0]:
                v = C.iou(pred[:5], gt)
                if v >= best_iou:
                    best, best_iou = j, v
        if best is None:
            fps.append(pred)
        else:
            used.add(best)
            tps.append((gts[best], pred, best_iou))
    fns = [gt for j, gt in enumerate(gts) if j not in used]
    return tps, fps, fns


def bucket(box, shape):
    area = box[3] * shape[1] * box[4] * shape[0]
    return next(name for name, lo, hi in SIZE_BUCKETS if lo <= area < hi)


def operating_point(model, view, class_names, pred_map, args, device, auto_id=None):
    """Predict at --op-conf and score TP/FP/FN, P/R/F1, mean IoU, size buckets, auto confusion."""
    per = defaultdict(lambda: {"TP": 0, "FP": 0, "FN": 0, "iou_sum": 0.0})
    size = defaultdict(lambda: {"TP": 0, "FN": 0, "FP": 0})
    auto_confusion = Counter()
    images = C.list_images(view / "images" / "eval")
    coco_classes = sorted(pred_map) if pred_map else None
    for start in range(0, len(images), args.batch):
        chunk = images[start:start + args.batch]
        results = model.predict([str(p) for p in chunk], imgsz=args.imgsz, conf=args.op_conf, iou=0.7,
                                classes=coco_classes, device=device, verbose=False)
        for img, res in zip(chunk, results):
            shape = res.orig_shape
            gts = C.read_labels(view / "labels" / "eval" / (img.stem + ".txt"))
            preds = []
            for xywh, c, conf in zip(res.boxes.xywhn.tolist(), res.boxes.cls.tolist(), res.boxes.conf.tolist()):
                cls = pred_map[int(c)] if pred_map else int(c)
                preds.append((cls, *xywh, conf))
            tps, fps, fns = match_image(gts, preds, args.match_iou)
            for gt, _, v in tps:
                per[gt[0]]["TP"] += 1
                per[gt[0]]["iou_sum"] += v
                size[bucket(gt, shape)]["TP"] += 1
            for p in fps:
                per[p[0]]["FP"] += 1
                size[bucket(p, shape)]["FP"] += 1
            for gt in fns:
                per[gt[0]]["FN"] += 1
                size[bucket(gt, shape)]["FN"] += 1
                if auto_id is not None and gt[0] == auto_id:
                    hit = max(fps, key=lambda p: C.iou(p[:5], gt), default=None)
                    label = (class_names[hit[0]] if hit is not None and C.iou(hit[:5], gt) >= args.match_iou
                             else "missed (no box)")
                    auto_confusion[label] += 1

    def prf(tp, fp, fn):
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        return p, r, (2 * p * r / (p + r) if p + r else 0.0)

    rows, total = {}, {"TP": 0, "FP": 0, "FN": 0, "iou_sum": 0.0}
    for cls in sorted(per):
        s = per[cls]
        p, r, f1 = prf(s["TP"], s["FP"], s["FN"])
        rows[class_names[cls]] = {"TP": s["TP"], "FP": s["FP"], "FN": s["FN"], "precision": p, "recall": r,
                                  "F1": f1, "mean_IoU": s["iou_sum"] / s["TP"] if s["TP"] else 0.0}
        for k in total:
            total[k] += s[k]
    p, r, f1 = prf(total["TP"], total["FP"], total["FN"])
    rows["all (micro)"] = {"TP": total["TP"], "FP": total["FP"], "FN": total["FN"], "precision": p, "recall": r,
                           "F1": f1, "mean_IoU": total["iou_sum"] / total["TP"] if total["TP"] else 0.0}
    sizes = {}
    for name, _, _ in SIZE_BUCKETS:
        s = size[name]
        sp, sr, sf = prf(s["TP"], s["FP"], s["FN"])
        sizes[name] = {"gt": s["TP"] + s["FN"], "recall": sr, "precision": sp, "F1": sf}
    return {"classes": rows, "sizes": sizes, "auto_confusion": dict(auto_confusion)}


def confusion_counts(metrics, names):
    try:
        matrix = metrics.confusion_matrix.matrix
        labels = [names[i] for i in sorted(names)] + ["background"]
        # Ultralytics: rows = predicted, columns = true
        return {"rows_predicted_cols_true": labels, "matrix": [[int(v) for v in row] for row in matrix]}
    except Exception:
        return None


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------

def fmt(v, digits=3):
    return "-" if v is None else f"{v:.{digits}f}"


def main():
    args = parse_args()
    ds = C.resolve(args.dataset)
    classes = C.Classes()
    auto_id = classes.id("auto_rickshaw")
    images = select_images(ds, args.split, args.sources)
    if not images:
        raise SystemExit(f"no images for split '{args.split}' sources={args.sources}")

    if args.model:
        model_path = C.resolve(args.model)
    else:
        candidates = sorted(C.WEIGHTS.glob("*.pt"), key=lambda p: p.stat().st_mtime)
        if not candidates:
            raise SystemExit("no --model given and weights/ is empty")
        model_path = candidates[-1]

    tag = args.split + ("_" + "-".join(args.sources) if args.sources else "")
    out = C.RUNS / "eval" / f"{C.timestamp()}_{tag}"
    out.mkdir(parents=True)
    logger, log_path, file_handler = C.setup_logging(f"eval_{tag}")
    C.attach_ultralytics_log(file_handler)
    device = C.resolve_device(args.device)
    C.guard_gpu_memory(args.max_vram_fraction, logger)
    logger.info("system: %s %s", C.system_snapshot(), C.gpu_stats())

    from ultralytics import YOLO

    logger.info("model %s | split %s | sources %s | %d images", model_path, args.split, args.sources or "all",
                len(images))
    val_kw = dict(split="val", imgsz=args.imgsz, batch=args.batch, conf=0.001, iou=0.7, device=device,
                  workers=args.workers, project=str(out), plots=True, verbose=False)
    result = {"model": str(model_path), "split": args.split, "sources": args.sources, "images": len(images),
              "op_conf": args.op_conf, "match_iou": args.match_iou, "log": str(log_path)}

    # ---- fine-tuned model
    model = YOLO(str(model_path))
    if [model.names[i] for i in sorted(model.names)] != classes.names:
        logger.error("model classes %s do not match configs/classes.yaml %s", model.names, classes.names)
        sys.exit(2)
    if args.recall_only:
        del model
        C.free_gpu()
        run_recall_only(args, model_path, images, ds, classes, device, out, logger, log_path)
        return
    view = build_view(out / "view_new", images, ds, args.split, lambda b: b)
    C.save_yaml(view / "data.yaml", {**C.load_yaml(view / "data.yaml"), "names": dict(enumerate(classes.names))})
    res = model.val(data=str(view / "data.yaml"), name="new", **val_kw)
    result["new"] = {"threshold_free": threshold_free(res, lambda c: classes.names[c]),
                     "operating_point": operating_point(model, view, classes.names, None, args, device, auto_id),
                     "speed_ms_per_image": dict(res.speed), "confusion": confusion_counts(res, model.names)}
    # Only one model on the GPU at a time: the 2026-09-13 freeze happened with the fine-tuned
    # model still loaded while the yolo11x baseline started validating at batch 8.
    del model, res
    C.free_gpu()

    # ---- baseline (COCO ids, autos removed from GT)
    if not args.no_baseline:
        baseline = YOLO(str(C.resolve_weights(args.baseline)))
        bview = build_view(out / "view_baseline", images, ds, args.split,
                           lambda boxes: [(classes.coco_ids[c], *b) for c, *b in boxes if c != auto_id])
        C.save_yaml(bview / "data.yaml", {**C.load_yaml(bview / "data.yaml"), "names": baseline.names})
        bres = baseline.val(data=str(bview / "data.yaml"), name="baseline",
                            classes=sorted(classes.coco_ids.values()), **val_kw)
        # operating point in canonical ids: convert GT back, map COCO predictions
        cview = build_view(out / "view_baseline_canon", images, ds, args.split,
                           lambda boxes: [b for b in boxes if b[0] != auto_id])
        result["baseline"] = {
            "weights": args.baseline,
            "threshold_free": threshold_free(
                bres, lambda c: classes.names[classes.coco_to_id[c]] if c in classes.coco_to_id else None),
            "operating_point": operating_point(baseline, cview, classes.names, classes.coco_to_id, args, device),
            "speed_ms_per_image": dict(bres.speed)}
    for v in out.glob("view_*"):
        shutil.rmtree(v / "images", ignore_errors=True)  # hardlinks only; labels kept for inspection

    # ---- gates
    new_tf, base_tf = result["new"]["threshold_free"], result.get("baseline", {}).get("threshold_free", {})
    gates = []
    for name in classes.names:
        n, b = new_tf.get(name), base_tf.get(name)
        if n is None:
            continue
        if name == "auto_rickshaw":
            gates.append((f"auto_rickshaw mAP50 {n['mAP50']:.3f} >= {args.auto_gate}", n["mAP50"] >= args.auto_gate))
        elif b:
            gates.append((f"{name} mAP50-95 {n['mAP50-95']:.3f} >= baseline {b['mAP50-95']:.3f} - {args.tolerance}",
                          n["mAP50-95"] >= b["mAP50-95"] - args.tolerance))
    result["gates"] = [{"check": t, "pass": ok} for t, ok in gates]
    result["verdict"] = bool(gates) and all(ok for _, ok in gates)

    # ---- markdown
    L = [f"# Evaluation: `{model_path.name}`", "",
         f"Split `{args.split}`, sources `{args.sources or 'all'}`, {len(images)} images. "
         f"Baseline `{args.baseline if base_tf else 'skipped'}` (autos removed from its ground truth).", "",
         "## 1. Threshold-free metrics (benchmark numbers)", "",
         "P/R/F1 at the confidence maximising mean F1. mAP50-95 is the headline (COCO) metric.", "",
         "| class | inst | P | R | F1 | mAP50 | mAP75 | mAP50-95 | base F1 | base mAP50 | base mAP50-95 | Δ mAP50-95 |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name in [*classes.names, "all"]:
        n, b = new_tf.get(name), base_tf.get(name, {})
        if n is None:
            continue
        delta = f"{n['mAP50-95'] - b['mAP50-95']:+.3f}" if b else "-"
        L.append(f"| {name} | {n.get('instances') or '-'} | {fmt(n['precision'])} | {fmt(n['recall'])} | "
                 f"{fmt(n['F1'])} | {fmt(n['mAP50'])} | {fmt(n['mAP75'])} | {fmt(n['mAP50-95'])} | "
                 f"{fmt(b.get('F1'))} | {fmt(b.get('mAP50'))} | {fmt(b.get('mAP50-95'))} | {delta} |")
    L.append("\n`all` for the baseline averages 4 classes; for the new model 5 (auto_rickshaw included).")

    new_op = result["new"]["operating_point"]
    base_op = result.get("baseline", {}).get("operating_point", {"classes": {}})
    L += ["", f"## 2. Operating point (conf {args.op_conf}, TP at IoU ≥ {args.match_iou})", "",
          "| class | TP | FP | FN | P | R | F1 | mean IoU | base P | base R | base F1 |",
          "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, n in new_op["classes"].items():
        b = base_op["classes"].get(name, {})
        L.append(f"| {name} | {n['TP']} | {n['FP']} | {n['FN']} | {fmt(n['precision'])} | {fmt(n['recall'])} | "
                 f"{fmt(n['F1'])} | {fmt(n['mean_IoU'])} | {fmt(b.get('precision'))} | {fmt(b.get('recall'))} | "
                 f"{fmt(b.get('F1'))} |")
    L += ["", "### By object size (new model)", "", "| size | GT boxes | recall | precision | F1 |",
          "|---|---:|---:|---:|---:|"]
    for name, s in new_op["sizes"].items():
        L.append(f"| {name} | {s['gt']} | {fmt(s['recall'])} | {fmt(s['precision'])} | {fmt(s['F1'])} |")
    if new_op["auto_confusion"]:
        L += ["", "### auto_rickshaw ground truth the model got wrong", ""]
        L += [f"- {k}: {v}" for k, v in sorted(new_op["auto_confusion"].items(), key=lambda kv: -kv[1])]

    sp = result["new"]["speed_ms_per_image"]
    L += ["", "## 3. Speed (ms / image, validation batch)", "",
          f"new: preprocess {sp.get('preprocess', 0):.1f}, inference {sp.get('inference', 0):.1f}, "
          f"postprocess {sp.get('postprocess', 0):.1f}"]
    if "baseline" in result:
        bs = result["baseline"]["speed_ms_per_image"]
        L.append(f"\nbaseline: preprocess {bs.get('preprocess', 0):.1f}, inference {bs.get('inference', 0):.1f}, "
                 f"postprocess {bs.get('postprocess', 0):.1f}")

    L += ["", "## 4. Gates", ""] + [f"- {'PASS' if ok else 'FAIL'}: {t}" for t, ok in gates]
    L += ["", f"**Verdict: {'PASS -- candidate for swap-in' if result['verdict'] else 'FAIL -- do not swap in'}**",
          "", "Plots (PR / F1 / P / R curves, confusion matrices): `new/` and `baseline/` next to this file."]
    if args.split != "test" and args.split.startswith("test_"):
        L.append("Synthetic split: measures relative robustness only.")

    (out / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    C.save_json(out / "report.json", result)
    for line in L:
        logger.info(line)
    logger.info("report: %s", out / "report.md")


if __name__ == "__main__":
    main()
