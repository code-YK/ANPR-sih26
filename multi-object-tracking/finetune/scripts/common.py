"""
Shared machinery for the finetune scripts
=========================================
Paths, the canonical class definition, logging, manifest I/O and the small
box helpers that prepare / autolabel / degrade / evaluate all need.

Every path in configs/*.yaml is relative to the finetune/ folder unless it is
absolute, so the scripts behave the same whichever directory they run from.
"""

import csv
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

FINETUNE_ROOT = Path(__file__).resolve().parents[1]
MOT_ROOT = FINETUNE_ROOT.parent
CONFIGS = FINETUNE_ROOT / "configs"
RAW = FINETUNE_ROOT / "raw"
DATASETS = FINETUNE_ROOT / "datasets"
RUNS = FINETUNE_ROOT / "runs"
LOGS = FINETUNE_ROOT / "logs"
WEIGHTS = FINETUNE_ROOT / "weights"

IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
# Filename marker for synthetic copies made by degrade.py. Anything carrying it
# is derived data: never in the manifest, always safe to delete and rebuild.
DEGRADED_TAG = "__deg-"

MANIFEST_FIELDS = ["image", "split", "source", "group", "labelled_classes", "n_boxes", "degrade", "original"]


# --------------------------------------------------------------------------
# Paths and config
# --------------------------------------------------------------------------

def timestamp():
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def resolve(path):
    """Resolve a config/CLI path relative to finetune/ unless already absolute."""
    p = Path(path)
    return p if p.is_absolute() else FINETUNE_ROOT / p


def resolve_weights(name):
    """Find a checkpoint without re-downloading one we already have.

    Bare names such as 'yolo11x.pt' resolve to the copy that already sits in
    multi-object-tracking/. Unknown bare names are passed through so
    Ultralytics can download official weights by name.
    """
    p = Path(name)
    if p.is_absolute():
        return p
    for base in (FINETUNE_ROOT, MOT_ROOT):
        if (base / p).exists():
            return base / p
    return p


def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_yaml(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def save_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


def norm_name(name):
    """'Auto-Rickshaw', 'auto rickshaw' and 'auto_rickshaw' all become 'autorickshaw'."""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


class Classes:
    """The canonical class list from configs/classes.yaml.

    Index in `names` IS the class id in the trained model. car_tracking.py's
    own VEHICLE_CLASSES is still hardcoded to COCO ids (2/3/5/7), which does
    NOT match this fine-tune's ids (0..4) -- do not point car_tracking.py at
    a fine-tuned checkpoint without also updating that mapping, or it will
    silently filter/mislabel classes. multi-object-tracking/test_finetuned.py
    reads the mapping from the loaded model's own model.names at runtime
    instead, and is the safe way to try a fine-tuned checkpoint without
    touching car_tracking.py.
    """

    def __init__(self, path=CONFIGS / "classes.yaml"):
        cfg = load_yaml(path)
        self.names = list(cfg["names"])
        self.coco_ids = {self.id(k): int(v) for k, v in (cfg.get("coco_ids") or {}).items()}
        self.coco_to_id = {v: k for k, v in self.coco_ids.items()}
        self.aliases = {
            norm_name(raw): self.check_target(target, f"aliases.{raw}")
            for raw, target in (cfg.get("aliases") or {}).items()
        }

    def id(self, name):
        if name not in self.names:
            raise ValueError(f"unknown class '{name}', expected one of {self.names}")
        return self.names.index(name)

    def check_target(self, target, where):
        if target is not None and target not in self.names:
            raise ValueError(f"{where}: '{target}' is not a canonical class {self.names}")
        return target


# --------------------------------------------------------------------------
# Logging and provenance
# --------------------------------------------------------------------------

def setup_logging(tag):
    """Log to stdout and to logs/<tag>_<timestamp>.log. Returns (logger, log_path, file_handler)."""
    LOGS.mkdir(parents=True, exist_ok=True)
    log_path = LOGS / f"{tag}_{timestamp()}.log"
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")

    logger = logging.getLogger("finetune")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    stream_handler = logging.StreamHandler(sys.stdout)
    for handler in (file_handler, stream_handler):
        handler.setFormatter(fmt)
        logger.addHandler(handler)

    logger.info("log file: %s", log_path)
    logger.info("command: %s", " ".join(sys.argv))
    return logger, log_path, file_handler


def attach_ultralytics_log(file_handler):
    """Mirror Ultralytics' own log lines (epoch metrics, warnings) into our log file."""
    try:
        from ultralytics.utils import LOGGER
        LOGGER.addHandler(file_handler)
    except Exception:  # logging is best-effort; never fail a run over it
        pass


def git_commit():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=MOT_ROOT, text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None


def environment_info():
    import torch
    import ultralytics

    info = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "torch": torch.__version__,
        "torch_cuda_build": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
        "ultralytics": ultralytics.__version__,
        "git_commit": git_commit(),
    }
    if torch.cuda.is_available():
        props = torch.cuda.get_device_properties(0)
        info["gpu"] = props.name
        info["vram_gb"] = round(props.total_memory / 1024**3, 1)
    return info


def resolve_device(requested=None):
    import torch

    if requested is not None:
        return requested
    return 0 if torch.cuda.is_available() else "cpu"


# --------------------------------------------------------------------------
# Memory safety (Windows laptop GPUs)
# --------------------------------------------------------------------------
# On Windows the NVIDIA driver does not fail when VRAM runs out: it silently moves
# GPU allocations into shared system RAM ("sysmem fallback"). Training slows ~20x
# and, with 16 GB of RAM, Windows starts paging until the whole machine freezes
# (what happened on 2026-09-13). The cap below makes PyTorch raise a normal
# CUDA out-of-memory error instead, so a bad setting fails in seconds.

def guard_gpu_memory(fraction, logger=None):
    """Hard-cap this process's CUDA allocations at `fraction` of total VRAM. Returns the cap in GB."""
    import torch

    if not torch.cuda.is_available():
        return None
    torch.cuda.set_per_process_memory_fraction(float(fraction), 0)
    total = torch.cuda.get_device_properties(0).total_memory / 1024**3
    if logger:
        logger.info("VRAM cap: %.0f%% of %.2f GB = %.2f GB (PyTorch raises out-of-memory beyond this "
                    "instead of spilling into system RAM)", fraction * 100, total, fraction * total)
    return fraction * total


def free_gpu():
    """Release cached CUDA memory after a model is no longer referenced."""
    import gc

    import torch

    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def system_snapshot():
    """RAM and VRAM right now (VRAM free is device-wide, i.e. includes other processes)."""
    import psutil
    import torch

    vm = psutil.virtual_memory()
    snap = {"ram_total_gb": round(vm.total / 1024**3, 1), "ram_available_gb": round(vm.available / 1024**3, 2)}
    if torch.cuda.is_available():
        free, total = torch.cuda.mem_get_info()
        snap.update(vram_free_gb=round(free / 1024**3, 2), vram_total_gb=round(total / 1024**3, 2),
                    vram_reserved_by_this_process_gb=round(torch.cuda.memory_reserved() / 1024**3, 2))
    return snap


def gpu_stats():
    """nvidia-smi utilisation / memory / temperature / power; {} if unavailable."""
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,temperature.gpu,power.draw",
             "--format=csv,noheader,nounits"], text=True, timeout=5, stderr=subprocess.DEVNULL)
        util, mem, temp, power = [v.strip() for v in out.splitlines()[0].split(",")]
        return {"gpu_util_pct": float(util), "gpu_mem_used_gb": round(float(mem) / 1024, 2),
                "gpu_temp_c": float(temp), "gpu_power_w": float(power)}
    except Exception:
        return {}


# --------------------------------------------------------------------------
# Dataset files
# --------------------------------------------------------------------------

def read_manifest(ds_dir):
    path = Path(ds_dir) / "manifest.csv"
    if not path.exists():
        raise SystemExit(f"no manifest at {path} -- run scripts/prepare_dataset.py first")
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_manifest(ds_dir, rows):
    with open(Path(ds_dir) / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def label_path_for(ds_dir, image_rel, labels_dir="labels"):
    """images/<split>/<name>.jpg -> <labels_dir>/<split>/<name>.txt"""
    image_rel = Path(image_rel)
    return Path(ds_dir) / labels_dir / image_rel.parent.name / (image_rel.stem + ".txt")


def read_labels(path):
    """YOLO label file -> [(cls, cx, cy, w, h)]; missing file means no objects."""
    path = Path(path)
    if not path.exists():
        return []
    boxes = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 5:
            boxes.append((int(float(parts[0])), *map(float, parts[1:5])))
    return boxes


def write_labels(path, boxes):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{c} {x:.6f} {y:.6f} {w:.6f} {h:.6f}\n" for c, x, y, w, h in boxes),
        encoding="utf-8",
    )


def link_or_copy(src, dst):
    """Hardlink (no extra disk on the same NTFS volume), falling back to a copy."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def list_images(directory):
    directory = Path(directory)
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if p.suffix.lower() in IMG_EXTS)


# --------------------------------------------------------------------------
# Boxes (normalised YOLO cx, cy, w, h)
# --------------------------------------------------------------------------

def to_xyxy(box):
    _, cx, cy, w, h = box
    return cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2


def _intersection(a, b):
    ax1, ay1, ax2, ay2 = to_xyxy(a)
    bx1, by1, bx2, by2 = to_xyxy(b)
    return max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(0.0, min(ay2, by2) - max(ay1, by1))


def iou(a, b):
    inter = _intersection(a, b)
    union = a[3] * a[4] + b[3] * b[4] - inter
    return inter / union if union > 0 else 0.0


def inter_over_first(a, b):
    """Fraction of box a that lies inside box b."""
    area = a[3] * a[4]
    return _intersection(a, b) / area if area > 0 else 0.0
