"""
Build the unified 5-class YOLO dataset from everything in raw/
==============================================================
Reads configs/sources.yaml, converts each source (Pascal VOC XML or YOLO txt)
to the canonical classes in configs/classes.yaml, splits it and writes:

    datasets/veh5/images/{split}/        hardlinks to raw images (no extra disk on NTFS)
    datasets/veh5/labels_src/{split}/    labels exactly as converted -- never edited
    datasets/veh5/labels/{split}/        what training reads (autolabel.py rewrites these)
    datasets/veh5/manifest.csv           one row per image: split, source, group, ...
    datasets/veh5/data.yaml              Ultralytics dataset file
    datasets/veh5/prepare_report.json    raw class names, mapping, per-split counts per source

Per-source options (see configs/sources.yaml for the full reference):
    split_method      balanced | native | hash | fixed
    dedupe_augmented  keep one copy of each Roboflow-augmented original
    max_per_group     evenly spaced frames per group (video/camera) before splitting
    max_images        random cap on the pool (int) or on each split (mapping)
    degrade           false = degrade.py never makes synthetic copies of this source

Always start with --dry-run: it prints every raw class name and what it maps
to, plus the per-split image and box counts, and writes nothing.

    python scripts/prepare_dataset.py --dry-run
    python scripts/prepare_dataset.py --force
    python scripts/prepare_dataset.py --force --disable night_duong --out datasets/veh5_A   # ablation variant
"""

import argparse
import hashlib
import random
import re
import shutil
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image

import common as C
from check_dataset import run_checks

SPLITS = ("train", "val", "test")
NATIVE_SPLIT_NAMES = {"train": "train", "training": "train", "val": "val", "valid": "val",
                      "validation": "val", "test": "test", "testing": "test"}
RF_SUFFIX = re.compile(r"_(?:jpe?g|png|bmp|webp)\.rf\.[0-9a-f]+$", re.IGNORECASE)
MIN_BOX_PX = 4         # VOC boxes thinner than this are annotation noise
MIN_BOX_NORM = 0.002   # same idea for normalised YOLO boxes


@dataclass
class Item:
    image: Path
    rel: Path      # image path relative to the source root
    boxes: list


def parse_args():
    parser = argparse.ArgumentParser(description="Merge raw datasets into one 5-class YOLO dataset")
    parser.add_argument("--sources", default="configs/sources.yaml")
    parser.add_argument("--out", default="datasets/veh5")
    parser.add_argument("--disable", nargs="*", default=[], help="Source names to leave out (ablation variants)")
    parser.add_argument("--seed", default="0", help="Split/sampling seed; changing it reshuffles")
    parser.add_argument("--dry-run", action="store_true", help="Scan and report only, write nothing")
    parser.add_argument("--force", action="store_true", help="Delete and rebuild an existing --out")
    return parser.parse_args()


# --------------------------------------------------------------------------
# Class mapping
# --------------------------------------------------------------------------

def map_class(raw, source_map, classes):
    """Return (class_id or None, known). known=False means the name is unmapped."""
    key = C.norm_name(raw)
    if key in source_map:
        target = source_map[key]
    elif key in classes.aliases:
        target = classes.aliases[key]
    else:
        return None, False
    return (None if target is None else classes.id(target)), True


def describe_mapping(raw, source_map, classes):
    cls, known = map_class(raw, source_map, classes)
    if not known:
        return "UNMAPPED (dropped)"
    return "(dropped)" if cls is None else classes.names[cls]


def new_stats():
    return {"raw_names": Counter(), "unknown_names": Counter(), "dropped_tiny": 0, "missing_image": 0,
            "bad_annotation": 0, "no_label_file": 0}


# --------------------------------------------------------------------------
# Scanners
# --------------------------------------------------------------------------

def find_image(base):
    for ext in C.IMG_EXTS:
        for candidate in (base.parent / (base.name + ext), base.parent / (base.name + ext.upper())):
            if candidate.exists():
                return candidate
    return None


def stem_index(root, suffixes, exclude=()):
    """stem -> path for every matching file under root; stems seen twice map to None (ambiguous).

    Fallback for datasets that keep labels in a sibling folder instead of a
    mirrored tree (e.g. DAWN's Fog/*.jpg next to Fog/Fog_PASCAL_VOC/*.xml).
    """
    index = {}
    for path in root.rglob("*"):
        if path.suffix.lower() in suffixes and path.stem not in exclude:
            index[path.stem] = None if path.stem in index else path
    return index


def scan_voc(src, classes, source_map, stats):
    img_root, ann_root = C.resolve(src["images"]), C.resolve(src["annotations"])
    for d in (img_root, ann_root):
        if not d.is_dir():
            raise SystemExit(f"[{src['name']}] directory not found: {d}")
    xml_files = sorted(ann_root.rglob("*.xml"))
    if not xml_files:
        raise SystemExit(f"[{src['name']}] no .xml files under {ann_root} -- if the dataset has .txt labels "
                         f"and a classes.txt/data.yaml, use format: yolo with root: instead")
    images_by_stem = None

    for xml_path in xml_files:
        try:
            root = ET.parse(xml_path).getroot()
        except ET.ParseError:
            stats["bad_annotation"] += 1
            continue
        rel = xml_path.relative_to(ann_root).with_suffix("")
        image = find_image(img_root / rel)
        if image is None:
            if images_by_stem is None:
                images_by_stem = stem_index(img_root, C.IMG_EXTS)
            image = images_by_stem.get(xml_path.stem) or images_by_stem.get(Path(root.findtext("filename") or "").stem)
        if image is None:
            stats["missing_image"] += 1
            continue

        try:
            w, h = int(float(root.findtext("size/width"))), int(float(root.findtext("size/height")))
        except (TypeError, ValueError):
            w = h = 0
        if not w or not h:
            with Image.open(image) as im:
                w, h = im.size

        boxes = []
        for obj in root.iter("object"):
            bb = obj.find("bndbox")
            if bb is None:
                continue
            raw = (obj.findtext("name") or "").strip()
            stats["raw_names"][raw] += 1
            cls, known = map_class(raw, source_map, classes)
            if not known:
                stats["unknown_names"][raw] += 1
            if cls is None:
                continue
            x1, y1, x2, y2 = (float(bb.findtext(k) or 0) for k in ("xmin", "ymin", "xmax", "ymax"))
            x1, x2 = sorted((min(max(x1, 0), w), min(max(x2, 0), w)))
            y1, y2 = sorted((min(max(y1, 0), h), min(max(y2, 0), h)))
            if x2 - x1 < MIN_BOX_PX or y2 - y1 < MIN_BOX_PX:
                stats["dropped_tiny"] += 1
                continue
            boxes.append((cls, (x1 + x2) / 2 / w, (y1 + y2) / 2 / h, (x2 - x1) / w, (y2 - y1) / h))
        yield Item(image, image.relative_to(img_root), boxes)


def load_yolo_names(root):
    candidates = [root / "data.yaml", *sorted(root.rglob("data.yaml")),
                  root / "classes.txt", *sorted(root.rglob("classes.txt"))]
    for path in candidates:
        if not path.exists():
            continue
        if path.suffix == ".yaml":
            names = C.load_yaml(path).get("names")
            if isinstance(names, dict):
                names = [names[k] for k in sorted(names, key=int)]
        else:
            names = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if names:
            return [str(n) for n in names], path
    raise SystemExit(f"no data.yaml / classes.txt with class names under {root}")


def yolo_label_path(root, rel):
    """Mirror Ultralytics: the last 'images' folder in the path becomes 'labels'."""
    parts = list(rel.parts)
    dirs = parts[:-1]
    if "images" in dirs:
        parts[max(i for i, p in enumerate(dirs) if p == "images")] = "labels"
    return root.joinpath(*parts).with_suffix(".txt")


def scan_yolo(src, classes, source_map, stats):
    """`root` may be a list: one dataset unpacked into several folders (labels may sit in another root)."""
    roots = [C.resolve(r) for r in (src["root"] if isinstance(src["root"], list) else [src["root"]])]
    for root in roots:
        if not root.is_dir():
            raise SystemExit(f"[{src['name']}] directory not found: {root}")
    names = names_file = None
    for root in roots:
        try:
            names, names_file = load_yolo_names(root)
            break
        except SystemExit:
            continue
    if names is None:
        raise SystemExit(f"[{src['name']}] no data.yaml / classes.txt with class names under {roots}")
    stats["names_file"] = str(names_file)
    labels_by_stem = None

    for root, image in sorted((r, p) for r in roots for p in r.rglob("*") if p.suffix.lower() in C.IMG_EXTS):
        rel = image.relative_to(root)
        label = yolo_label_path(root, rel)
        if not label.exists():
            if labels_by_stem is None:
                labels_by_stem = {}
                for r in roots:
                    for stem, path in stem_index(r, {".txt"}, exclude={"classes", "README", "readme", "notes"}).items():
                        labels_by_stem[stem] = None if stem in labels_by_stem else path
            label = labels_by_stem.get(image.stem) or label
        boxes = []
        if not label.exists():
            stats["no_label_file"] += 1
        else:
            for line in label.read_text(encoding="utf-8").splitlines():
                vals = line.split()
                if len(vals) < 5:
                    continue
                idx, coords = int(float(vals[0])), [float(v) for v in vals[1:]]
                raw = names[idx] if 0 <= idx < len(names) else f"<class index {idx}>"
                stats["raw_names"][raw] += 1
                cls, known = map_class(raw, source_map, classes)
                if not known:
                    stats["unknown_names"][raw] += 1
                if cls is None:
                    continue
                if len(coords) == 4:
                    cx, cy, bw, bh = coords
                    x1, y1, x2, y2 = cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2
                else:  # segmentation polygon export -> enclosing box
                    xs, ys = coords[0::2], coords[1::2]
                    x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
                x1, x2 = max(x1, 0.0), min(x2, 1.0)
                y1, y2 = max(y1, 0.0), min(y2, 1.0)
                if x2 - x1 < MIN_BOX_NORM or y2 - y1 < MIN_BOX_NORM:
                    stats["dropped_tiny"] += 1
                    continue
                boxes.append((cls, (x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1))
        yield Item(image, rel, boxes)


# --------------------------------------------------------------------------
# Grouping, reduction, splitting, sampling
# --------------------------------------------------------------------------

def original_stem(item):
    return RF_SUFFIX.sub("", item.image.stem)


def group_key(item, mode):
    stem = original_stem(item)
    if mode == "parent":
        return item.rel.parent.as_posix()
    if mode == "stem_prefix":
        return stem.rsplit("_", 1)[0]
    return stem


def natural_key(text):
    """'frame-2' < 'frame-10' -- temporal order for unpadded frame numbers."""
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", text)]


def stable_hash(text):
    return int(hashlib.md5(text.encode()).hexdigest()[:8], 16) / 2**32


def dedupe_augmented(items):
    """One copy per Roboflow original (the augmented copies are near-duplicates); deterministic pick."""
    best = {}
    for item in items:
        key = (item.rel.parent.as_posix(), original_stem(item))
        if key not in best or stable_hash(item.image.name) < stable_hash(best[key].image.name):
            best[key] = item
    return sorted(best.values(), key=lambda it: natural_key(str(it.rel)))


def evenly_per_group(items, limit, mode):
    """Keep at most `limit` evenly spaced frames of every group (video / fixed camera).

    Consecutive frames of one camera are near-duplicates; evenly spacing them keeps
    the scene's variety (traffic, lighting over time) at a fraction of the images.
    """
    groups = defaultdict(list)
    for item in items:
        groups[group_key(item, mode)].append(item)
    kept = []
    for members in groups.values():
        members.sort(key=lambda it: natural_key(original_stem(it)))
        if len(members) <= limit:
            kept.extend(members)
        else:
            step = len(members) / limit
            kept.extend(members[int(i * step)] for i in range(limit))
    return kept


def native_split(item):
    for part in reversed(item.rel.parts[:-1]):
        if part.lower() in NATIVE_SPLIT_NAMES:
            return NATIVE_SPLIT_NAMES[part.lower()]
    return None


def hash_split(key, ratios, seed):
    u, edge, total = stable_hash(f"{seed}:{key}"), 0.0, sum(ratios)
    for split, ratio in zip(SPLITS, ratios):
        edge += ratio / total
        if u < edge:
            return split
    return SPLITS[-1]


def balanced_split(groups, ratios, n_classes, seed):
    """Greedy group assignment hitting the ratios in images and in boxes of every class.

    Every split should fill at the same pace in every dimension (images and
    boxes per class): fill = achieved share / target share. Largest groups are
    placed first (they are the hard ones); each goes to the split that leaves
    the fills of the dimensions it touches most equal across splits (lowest
    variance). Deterministic for a given seed.
    """
    total_ratio = sum(ratios)
    targets = [r / total_ratio for r in ratios]
    sizes = {g: [len(items)] + [sum(b[0] == c for it in items for b in it.boxes) for c in range(n_classes)]
             for g, items in groups.items()}
    totals = [max(sum(s[k] for s in sizes.values()), 1) for k in range(n_classes + 1)]
    current = [[0] * (n_classes + 1) for _ in SPLITS]
    assignment = {}
    order = sorted(groups, key=lambda g: (-sizes[g][0], -sum(sizes[g][1:]), stable_hash(f"{seed}:{g}")))
    active = [s for s, t in enumerate(targets) if t > 0]
    for g in order:
        dims = [k for k in range(n_classes + 1) if sizes[g][k] > 0]
        best, best_score = None, None
        for s in active:
            score = 0.0
            for k in dims:
                fills = [(current[j][k] + (sizes[g][k] if j == s else 0)) / (totals[k] * targets[j]) for j in active]
                mean = sum(fills) / len(fills)
                score += sum((f - mean) ** 2 for f in fills)
            if best_score is None or score < best_score:
                best, best_score = s, score
        assignment[g] = SPLITS[best]
        for k in range(n_classes + 1):
            current[best][k] += sizes[g][k]
    return assignment


def sample(entries, cap, rng):
    """Random subset of Items or (Item, group) pairs, returned in a stable order."""
    if cap is None or len(entries) <= cap:
        return entries
    item_of = lambda e: e[0] if isinstance(e, tuple) else e
    return sorted(rng.sample(entries, cap), key=lambda e: str(item_of(e).rel))


def validate_source(src, classes):
    name = src.get("name")
    if not name or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise SystemExit(f"source name must be [A-Za-z0-9_-]+, got {name!r}")
    if src.get("format") not in ("voc", "yolo"):
        raise SystemExit(f"[{name}] format must be voc or yolo")
    method = src.get("split_method", "balanced")
    if method not in ("balanced", "native", "hash", "fixed"):
        raise SystemExit(f"[{name}] split_method must be balanced, native, hash or fixed")
    if method == "fixed" and not re.fullmatch(r"[a-z][a-z0-9_]*", str(src.get("fixed_split", ""))):
        raise SystemExit(f"[{name}] split_method fixed needs fixed_split: <folder name>, e.g. bench_night")
    ratios = src.get("split", [0.8, 0.1, 0.1])
    if method in ("balanced", "hash") and (len(ratios) != 3 or sum(ratios) <= 0 or min(ratios) < 0):
        raise SystemExit(f"[{name}] split must be three non-negative ratios")
    mode = src.get("group_by", "image")
    if mode not in ("image", "parent", "stem_prefix"):
        raise SystemExit(f"[{name}] group_by must be image, parent or stem_prefix")
    cap = src.get("max_images")
    if not (cap is None or isinstance(cap, int) or
            (isinstance(cap, dict) and set(cap) <= set(SPLITS))):
        raise SystemExit(f"[{name}] max_images must be an int or a mapping of train/val/test -> int")
    per_group = src.get("max_per_group")
    if not (per_group is None or (isinstance(per_group, int) and per_group > 0)):
        raise SystemExit(f"[{name}] max_per_group must be a positive int")

    labelled = src.get("labelled_classes")
    if labelled == "all":
        labelled_str = "all"
    elif isinstance(labelled, list) and labelled:
        ids = sorted({classes.id(n) for n in labelled})
        labelled_str = "all" if len(ids) == len(classes.names) else "|".join(classes.names[i] for i in ids)
    else:
        raise SystemExit(f"[{name}] labelled_classes must be 'all' or a list of class names")

    source_map = {C.norm_name(k): classes.check_target(v, f"{name}.class_map.{k}")
                  for k, v in (src.get("class_map") or {}).items()}
    return source_map, labelled_str, method, ratios, mode, cap, per_group


def split_items(items, method, ratios, mode, seed, name, n_classes, logger, fixed_split=None):
    """-> {split: [(item, group)]}"""
    out = defaultdict(list)
    if method == "fixed":
        out[fixed_split] = [(it, group_key(it, mode)) for it in items]
        return out
    if method == "native":
        unknown = 0
        for item in items:
            split = native_split(item)
            if split is None:
                unknown += 1
                continue
            out[split].append((item, group_key(item, mode)))
        if unknown:
            logger.warning("[%s] %d images not under a train/val/test folder were skipped", name, unknown)
        return out

    groups = defaultdict(list)
    for item in items:
        groups[group_key(item, mode)].append(item)
    if method == "hash":
        assignment = {g: hash_split(f"{name}:{g}", ratios, seed) for g in groups}
    else:
        assignment = balanced_split(groups, ratios, n_classes, f"{seed}:{name}")
    for g, members in groups.items():
        out[assignment[g]].extend((it, g) for it in members)
    return out


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def out_name(source, item):
    stem = item.rel.with_suffix("").as_posix().replace("/", "_")
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem)
    return f"{source}__{stem}{item.image.suffix.lower()}"


def main():
    args = parse_args()
    classes = C.Classes()
    n_classes = len(classes.names)
    auto_id = classes.id("auto_rickshaw")
    sources_path = C.resolve(args.sources)
    all_sources = C.load_yaml(sources_path).get("sources", [])
    unknown = set(args.disable) - {s.get("name") for s in all_sources}
    if unknown:
        raise SystemExit(f"--disable: unknown source names {sorted(unknown)}")
    sources = [s for s in all_sources if s.get("enabled", True) and s.get("name") not in args.disable]
    out = C.resolve(args.out)

    logger, log_path, _ = C.setup_logging("prepare_dryrun" if args.dry_run else "prepare")
    if not sources:
        raise SystemExit(f"no enabled sources in {sources_path} -- set enabled: true on the ones you downloaded")
    if args.disable:
        logger.info("disabled for this build: %s", args.disable)

    if not args.dry_run:
        if out.exists():
            if not args.force:
                raise SystemExit(f"{out} exists; pass --force to rebuild it (it is fully regenerated)")
            logger.info("removing previous build %s", out)
            shutil.rmtree(out)
        out.mkdir(parents=True)

    report = {"created": datetime.now().isoformat(timespec="seconds"), "sources_file": str(sources_path),
              "disabled": args.disable, "seed": args.seed, "classes": classes.names, "log": str(log_path),
              "sources": {}}
    rows = []
    totals = defaultdict(Counter)

    for src in sources:
        name = src["name"]
        source_map, labelled, method, ratios, mode, cap, per_group = validate_source(src, classes)
        stats = new_stats()
        scanner = scan_voc if src["format"] == "voc" else scan_yolo
        logger.info("[%s] scanning (%s, labelled_classes=%s, split_method=%s%s, group_by=%s)", name, src["format"],
                    labelled, method, f" {ratios}" if method in ("balanced", "hash") else "", mode)
        items = list(scanner(src, classes, source_map, stats))
        scanned = len(items)
        rng = random.Random(f"{args.seed}:{name}")
        reduction = {"scanned": scanned}

        if src.get("dedupe_augmented"):
            items = dedupe_augmented(items)
            reduction["after_dedupe_augmented"] = len(items)
        if per_group:
            items = evenly_per_group(items, per_group, mode)
            reduction[f"after_max_per_group_{per_group}"] = len(items)
        if isinstance(cap, int):      # sample the pool first, then split it
            items = sample(items, cap, rng)
            reduction[f"after_max_images_{cap}"] = len(items)
        if len(reduction) > 1:
            logger.info("[%s] image reduction: %s", name, reduction)

        per_split = split_items(items, method, ratios, mode, args.seed, name, n_classes, logger,
                                src.get("fixed_split"))
        split_names = [src["fixed_split"]] if method == "fixed" else list(SPLITS)
        split_groups = {s: len({g for _, g in per_split.get(s, [])}) for s in split_names}
        if method in ("balanced", "hash", "native"):
            pool_imgs = sum(len(per_split.get(s, [])) for s in split_names) or 1
            pool_autos = sum(b[0] == auto_id for s in split_names for it, _ in per_split.get(s, [])
                             for b in it.boxes)
            logger.info("[%s] split of the pool before caps -- images %s | auto_rickshaw boxes %s", name,
                        {s: f"{len(per_split.get(s, [])) / pool_imgs:.1%}" for s in split_names},
                        {s: f"{sum(b[0] == auto_id for it, _ in per_split.get(s, []) for b in it.boxes) / pool_autos:.1%}"
                         for s in split_names} if pool_autos else "none")
        if isinstance(cap, dict):     # split the whole pool, then cap each split
            for split, limit in cap.items():
                if split in per_split:
                    per_split[split] = sample(per_split[split], limit, rng)

        # ---- per-source summary
        logger.info("[%s] %d images scanned", name, scanned)
        logger.info("[%s] raw class names -> canonical:", name)
        for raw, n in stats["raw_names"].most_common():
            logger.info("    %-28s %7d  -> %s", raw, n, describe_mapping(raw, source_map, classes))
        if stats["unknown_names"]:
            logger.warning("[%s] UNMAPPED names %s were dropped. If any is a vehicle, add it to "
                           "classes.yaml aliases or this source's class_map.", name, dict(stats["unknown_names"]))
        for key in ("missing_image", "bad_annotation", "no_label_file", "dropped_tiny"):
            if stats[key]:
                logger.info("[%s] %s: %d", name, key, stats[key])
        if labelled != "all" and "auto_rickshaw" not in labelled.split("|"):
            logger.warning("[%s] does not label auto_rickshaw and autolabel cannot add it: any auto in these "
                           "images is taught as background. Only OK for datasets with no autos in them.", name)

        logger.info("[%s] %-12s %7s %8s" + " %13s" * n_classes, name, "split", "groups", "images",
                    *[n[:13] for n in classes.names])
        source_counts = {}
        for split in split_names:
            members = per_split.get(split, [])
            boxes = Counter(classes.names[b[0]] for it, _ in members for b in it.boxes)
            source_counts[split] = {"images": len(members), "groups": split_groups[split], "boxes": dict(boxes)}
            logger.info("[%s] %-12s %7d %8d" + " %13d" * n_classes, name, split, split_groups[split], len(members),
                        *[boxes[n] for n in classes.names])
            if method in ("balanced", "hash") and ratios[SPLITS.index(split)] > 0 and not members:
                logger.warning("[%s] split '%s' got 0 images", name, split)
            totals[split]["images"] += len(members)
            totals[split].update(boxes)

            if args.dry_run:
                continue
            for item, group in members:
                fname = out_name(name, item)
                C.link_or_copy(item.image, out / "images" / split / fname)
                label_name = Path(fname).stem + ".txt"
                C.write_labels(out / "labels_src" / split / label_name, item.boxes)
                C.write_labels(out / "labels" / split / label_name, item.boxes)
                rows.append({"image": f"images/{split}/{fname}", "split": split, "source": name, "group": group,
                             "labelled_classes": labelled, "n_boxes": len(item.boxes),
                             "degrade": int(bool(src.get("degrade", True))), "original": str(item.image)})

        report["sources"][name] = {
            "config": src, "reduction": reduction, "splits": source_counts,
            "raw_names": dict(stats["raw_names"]), "unknown_names": dict(stats["unknown_names"]),
            **{k: stats[k] for k in ("dropped_tiny", "missing_image", "bad_annotation", "no_label_file")},
        }

    ordered = list(SPLITS) + sorted(s for s in totals if s not in SPLITS)
    logger.info("TOTAL  %-12s %8s" + " %13s" * n_classes, "split", "images", *[n[:13] for n in classes.names])
    for split in ordered:
        logger.info("TOTAL  %-12s %8d" + " %13d" * n_classes, split, totals[split]["images"],
                    *[totals[split][n] for n in classes.names])
    grand = sum(totals[s]["images"] for s in SPLITS) or 1
    logger.info("TOTAL  share of train/val/test images: %s", {s: f"{totals[s]['images'] / grand:.1%}" for s in SPLITS})

    if args.dry_run:
        logger.info("dry run complete -- nothing written. Fix any UNMAPPED vehicle names, then run with --force.")
        return

    if not totals["train"]["images"] or not totals["val"]["images"]:
        raise SystemExit(f"need images in both train and val, got { {s: totals[s]['images'] for s in ordered} }")

    C.write_manifest(out, rows)
    data = {"path": str(out), "train": "images/train", "val": "images/val"}
    if totals["test"]["images"]:
        data["test"] = "images/test"
    data["names"] = dict(enumerate(classes.names))
    C.save_yaml(out / "data.yaml", data)
    report["totals"] = {s: dict(totals[s]) for s in ordered}
    C.save_json(out / "prepare_report.json", report)
    logger.info("wrote %s", out)

    run_checks(out, logger)
    logger.info("next: python scripts/autolabel.py")


if __name__ == "__main__":
    main()
