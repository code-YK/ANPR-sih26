"""
Fine-tune the 5-class vehicle model
===================================
Wraps Ultralytics training with the bookkeeping a result needs to be trusted
later, and with the safety layers a 16 GB Windows laptop needs overnight:

    runs/<name>/                    Ultralytics output: weights/best.pt, last.pt, results.csv,
                                    PR/F1 curves, confusion matrix, val batch previews
    runs/<name>/metrics_per_epoch.csv  losses + P/R/F1/mAP per epoch
    runs/<name>/training_summary.png   loss / metric curves, best epoch marked
    runs/<name>/resources.csv       step time, img/s, VRAM, RAM, GPU temp/power every 100 steps
    runs/<name>/train_config.yaml   the exact config used (after CLI overrides)
    runs/<name>/dataset/            copies of data.yaml + prepare/autolabel/check reports
    runs/<name>/model_card.json     metrics, class names, environment, git commit
    weights/<name>_best.pt          the deliverable, plus <name>_best.json (model card)
    logs/train_<name>_*.log         full log incl. per-epoch metrics and resource lines

Safety (configs/train.yaml `safety`, decision.md D7):
    * VRAM hard cap  -> a too-large setting raises out-of-memory instead of freezing Windows
    * RAM watchdog   -> stops cleanly when free system RAM stays too low
    * speed watchdog -> stops cleanly when steps suddenly get much slower (memory spilling)
    A watchdog stop never corrupts anything: resume from the last completed epoch.

    python scripts/preflight.py                     # always first: GREEN / RED checklist
    python scripts/train.py --smoke                 # 3 epochs on 30% of data: must print SMOKE PASS
    python scripts/train.py                         # the real run (configs/train.yaml)
    python scripts/train.py --resume runs/<name>/weights/last.pt
"""

import argparse
import csv
import shutil
import statistics
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import common as C

# results.csv column -> short name. Ultralytics adds/renames columns between versions,
# so every lookup below tolerates a missing column.
EPOCH_COLUMNS = {
    "train/box_loss": "train_box_loss", "train/cls_loss": "train_cls_loss", "train/dfl_loss": "train_dfl_loss",
    "val/box_loss": "val_box_loss", "val/cls_loss": "val_cls_loss", "val/dfl_loss": "val_dfl_loss",
    "metrics/precision(B)": "precision", "metrics/recall(B)": "recall",
    "metrics/mAP50(B)": "mAP50", "metrics/mAP50-95(B)": "mAP50-95", "lr/pg0": "lr",
}
SAFETY_DEFAULTS = {"max_vram_fraction": 0.80, "min_free_ram_gb": 1.5, "slow_step_factor": 4.0,
                   "slow_step_patience": 20}


def parse_args():
    parser = argparse.ArgumentParser(description="Fine-tune YOLO on the prepared vehicle dataset")
    parser.add_argument("--config", default="configs/train.yaml")
    parser.add_argument("--name", help="Run name (default: <model>-veh5-<imgsz>-<timestamp>)")
    parser.add_argument("--model", help="Override starting weights, e.g. yolo11l.pt")
    parser.add_argument("--data")
    parser.add_argument("--epochs", type=int)
    parser.add_argument("--imgsz", type=int)
    parser.add_argument("--batch", type=int, help="Fixed batch size (AutoBatch is refused, decision.md D2)")
    parser.add_argument("--workers", type=int)
    parser.add_argument("--device", default=None)
    parser.add_argument("--fraction", type=float, help="Train on this fraction of the train split (quick experiments)")
    parser.add_argument("--resume", help="Path to runs/<name>/weights/last.pt to continue an interrupted run")
    parser.add_argument("--smoke", action="store_true",
                        help="3 epochs on 30%% of train data: must end with finite val loss and mAP50 > 0 (decision.md D6)")
    parser.add_argument("--min-free-ram-gb", type=float, help="Override safety.min_free_ram_gb")
    parser.add_argument("--max-vram-fraction", type=float, help="Override safety.max_vram_fraction")
    return parser.parse_args()


def build_config(args):
    cfg = C.load_yaml(C.resolve(args.config))
    for key in ("model", "data", "epochs", "imgsz", "workers", "fraction", "batch"):
        if getattr(args, key) is not None:
            cfg[key] = getattr(args, key)
    if args.device is not None:
        cfg["device"] = args.device
    if args.smoke:
        # The 5-class head is newly initialised and warmup lasts 3 epochs: a 1-epoch / 10% smoke run
        # never leaves near-zero LR, so it always shows mAP 0 (and can show NaN val loss) even when
        # the pipeline is healthy. 3 epochs x 30% gives the head a few hundred optimizer steps.
        cfg.update(epochs=3, fraction=0.3, patience=3, close_mosaic=0, save_period=-1)
    safety = {**SAFETY_DEFAULTS, **(cfg.pop("safety", None) or {})}
    if args.min_free_ram_gb is not None:
        safety["min_free_ram_gb"] = args.min_free_ram_gb
    if args.max_vram_fraction is not None:
        safety["max_vram_fraction"] = args.max_vram_fraction
    return cfg, safety


# --------------------------------------------------------------------------
# Watchdog
# --------------------------------------------------------------------------

class WatchdogAbort(Exception):
    pass


class ResourceWatchdog:
    """Stops training cleanly before Windows runs out of memory or the GPU spills into system RAM.

    Both failure modes freeze a laptop instead of raising an error, so they are detected
    from the outside: free system RAM (psutil) and step time relative to the running median.
    Also writes runs/<name>/resources.csv and a one-line resource summary per epoch.
    """

    def __init__(self, logger, safety, log_every=100, warmup_steps=30):
        self.logger = logger
        self.min_free_ram_gb = float(safety["min_free_ram_gb"])
        self.slow_factor = float(safety["slow_step_factor"])
        self.slow_patience = int(safety["slow_step_patience"])
        self.log_every, self.warmup_steps = log_every, warmup_steps
        self.times = deque(maxlen=300)
        self.last = self.csv_path = self.epoch_t0 = None
        self.step = self.epoch_steps = self.low_ram = self.slow = 0
        self.min_ram_seen = float("inf")

    def attach(self, model):
        model.add_callback("on_train_epoch_start", self.on_epoch_start)
        model.add_callback("on_train_batch_end", self.on_batch_end)
        model.add_callback("on_fit_epoch_end", self.on_fit_epoch_end)

    def on_epoch_start(self, trainer):
        import torch

        self.last, self.epoch_steps, self.slow = None, 0, 0
        self.epoch_t0 = time.perf_counter()
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
        if self.csv_path is None:
            self.csv_path = Path(trainer.save_dir) / "resources.csv"

    def on_batch_end(self, trainer):
        import psutil

        now = time.perf_counter()
        dt = None if self.last is None else now - self.last
        self.last = now
        self.step += 1
        self.epoch_steps += 1

        if self.step % 10 == 0:
            avail = psutil.virtual_memory().available / 1024**3
            self.min_ram_seen = min(self.min_ram_seen, avail)
            self.low_ram = self.low_ram + 1 if avail < self.min_free_ram_gb else 0
            if self.low_ram >= 3:
                raise WatchdogAbort(f"free system RAM {avail:.2f} GB stayed below {self.min_free_ram_gb} GB "
                                    f"for 30 steps -- close other applications or lower workers/batch")

        if dt is not None and self.epoch_steps > self.warmup_steps:
            if len(self.times) >= 50:
                median = statistics.median(self.times)
                self.slow = self.slow + 1 if dt > self.slow_factor * median else 0
                if self.slow >= self.slow_patience:
                    raise WatchdogAbort(f"{self.slow} consecutive steps slower than {self.slow_factor}x the median "
                                        f"({dt:.2f}s vs {median:.2f}s) -- GPU memory is likely spilling into system "
                                        f"RAM; lower batch or imgsz")
            if self.slow == 0:
                self.times.append(dt)

        if self.step % self.log_every == 0:
            self.write_row(trainer)

    def snapshot(self, trainer):
        import torch

        median = statistics.median(self.times) if self.times else None
        row = {"time": datetime.now().isoformat(timespec="seconds"), "epoch": trainer.epoch + 1, "step": self.step,
               "sec_per_step": round(median, 3) if median else None,
               "img_per_s": round(trainer.batch_size / median, 2) if median else None,
               **C.system_snapshot(), **C.gpu_stats()}
        if torch.cuda.is_available():
            row["vram_peak_this_epoch_gb"] = round(torch.cuda.max_memory_reserved() / 1024**3, 2)
        return row

    def write_row(self, trainer):
        row = self.snapshot(trainer)
        new = not self.csv_path.exists()
        with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(row))
            if new:
                writer.writeheader()
            writer.writerow(row)

    def on_fit_epoch_end(self, trainer):
        if trainer.epoch + 1 > trainer.epochs:  # Ultralytics' final best.pt validation, not a training epoch
            return
        row = self.snapshot(trainer)
        epoch_min = (time.perf_counter() - self.epoch_t0) / 60 if self.epoch_t0 else 0
        remaining = trainer.epochs - trainer.epoch - 1
        self.logger.info(
            "resources epoch %d/%d: %.1f min (train+val), %s img/s, VRAM peak %s GB, RAM free %s GB (min seen %.2f), "
            "GPU %s C | ETA if no early stop: %.1f h  (GPU utilisation per step: resources.csv)",
            trainer.epoch + 1, trainer.epochs, epoch_min, row.get("img_per_s"), row.get("vram_peak_this_epoch_gb"),
            row.get("ram_available_gb"), self.min_ram_seen, row.get("gpu_temp_c"), remaining * epoch_min / 60)


# --------------------------------------------------------------------------
# Post-training summary
# --------------------------------------------------------------------------

def summarize_epochs(save_dir, logger):
    """results.csv -> metrics_per_epoch.csv (+F1) and training_summary.png. Returns the best-epoch row."""
    src = save_dir / "results.csv"
    if not src.exists():
        return None
    with open(src, newline="", encoding="utf-8") as f:
        raw_rows = [{k.strip(): v.strip() for k, v in r.items() if k} for r in csv.DictReader(f)]
    rows = []
    for r in raw_rows:
        row = {"epoch": int(float(r.get("epoch", len(rows) + 1)))}
        for col, short in EPOCH_COLUMNS.items():
            if r.get(col) not in (None, ""):
                row[short] = float(r[col])
        p, rec = row.get("precision"), row.get("recall")
        if p is not None and rec is not None:
            row["F1"] = 2 * p * rec / (p + rec) if p + rec > 0 else 0.0
        rows.append(row)
    if not rows:
        return None

    fields = ["epoch"] + [k for k in [*EPOCH_COLUMNS.values(), "F1"] if any(k in r for r in rows)]
    with open(save_dir / "metrics_per_epoch.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    best = max(rows, key=lambda r: r.get("mAP50-95", -1))
    logger.info("best epoch %d (selection metric mAP50-95): %s", best["epoch"],
                {k: round(v, 4) for k, v in best.items() if k != "epoch"})

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        epochs = [r["epoch"] for r in rows]
        panels = [("box loss (CIoU)", ["train_box_loss", "val_box_loss"]),
                  ("cls loss (BCE)", ["train_cls_loss", "val_cls_loss"]),
                  ("DFL loss", ["train_dfl_loss", "val_dfl_loss"]),
                  ("precision / recall / F1", ["precision", "recall", "F1"]),
                  ("mAP", ["mAP50", "mAP50-95"]),
                  ("learning rate", ["lr"])]
        fig, axes = plt.subplots(2, 3, figsize=(15, 8))
        for ax, (title, keys) in zip(axes.flat, panels):
            for key in keys:
                if any(key in r for r in rows):
                    ax.plot(epochs, [r.get(key) for r in rows], label=key, marker=".")
            ax.axvline(best["epoch"], color="grey", linestyle="--", linewidth=1)
            ax.set_title(title)
            ax.set_xlabel("epoch")
            ax.grid(alpha=0.3)
            ax.legend(fontsize=8)
        fig.suptitle(f"{save_dir.name} -- dashed line = best epoch {best['epoch']}")
        fig.tight_layout()
        fig.savefig(save_dir / "training_summary.png", dpi=120)
        plt.close(fig)
    except Exception as exc:  # plotting must never fail a finished training run
        logger.warning("could not draw training_summary.png: %s", exc)
    return best


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    args = parse_args()
    cfg, safety = build_config(args)
    stamp = C.timestamp()
    name = args.name or f"{Path(cfg['model']).stem}-veh5-{cfg['imgsz']}-{stamp}{'-smoke' if args.smoke else ''}"
    logger, log_path, file_handler = C.setup_logging(f"train_{name}")
    C.attach_ultralytics_log(file_handler)

    env = C.environment_info()
    logger.info("environment: %s", env)
    if not env["cuda_available"] and str(cfg.get("device", "")) != "cpu":
        logger.error("CUDA not available (CPU-only torch wheel?). See multi-object-tracking/requirements.txt. "
                     "Pass --device cpu only if you really mean it.")
        sys.exit(2)
    batch = cfg.get("batch")
    if not args.resume and not (isinstance(batch, int) and batch >= 1):
        logger.error("batch must be a fixed integer, got %r. AutoBatch (-1 or a fraction) failed on this "
                     "laptop and froze it -- see decision.md D2.", batch)
        sys.exit(2)

    C.guard_gpu_memory(safety["max_vram_fraction"], logger)
    logger.info("safety: %s", safety)
    logger.info("system before training: %s %s", C.system_snapshot(), C.gpu_stats())

    from ultralytics import YOLO

    watchdog = ResourceWatchdog(logger, safety)
    try:
        if args.resume:
            last = C.resolve(args.resume)
            logger.info("resuming %s", last)
            model = YOLO(str(last))
            watchdog.attach(model)
            model.train(resume=True)
        else:
            data = C.resolve(cfg.pop("data"))
            if not data.exists():
                raise SystemExit(f"{data} not found -- run scripts/prepare_dataset.py first")
            weights = C.resolve_weights(cfg.pop("model"))
            logger.info("starting weights: %s", weights)
            logger.info("dataset: %s", data)
            logger.info("train args: %s", cfg)
            model = YOLO(str(weights))
            watchdog.attach(model)
            model.train(data=str(data), project=str(C.RUNS), name=name, exist_ok=False, **cfg)
            cfg.update(model=str(weights), data=str(data))
    except WatchdogAbort as exc:
        trainer = getattr(locals().get("model"), "trainer", None)
        last = Path(getattr(trainer, "last", "")) if trainer is not None else None
        logger.error("WATCHDOG STOP: %s", exc)
        if last and last.exists():
            logger.error("Nothing is corrupted. After fixing the cause, continue with:\n"
                         "    python scripts/train.py --resume %s", last)
        else:
            logger.error("No epoch had finished yet, so there is no checkpoint; fix the cause and start again.")
        sys.exit(3)

    trainer = model.trainer
    save_dir, best = Path(trainer.save_dir), Path(trainer.best)
    if not best.exists():
        logger.error("training finished without %s", best)
        sys.exit(1)

    if not args.resume:
        C.save_yaml(save_dir / "train_config.yaml", {**cfg, "safety": safety})
        data_dir = Path(cfg["data"]).parent
        for fname in ("data.yaml", "prepare_report.json", "autolabel_report.json", "check_report.json",
                      "degrade_report_train.json"):
            if (data_dir / fname).exists():
                (save_dir / "dataset").mkdir(exist_ok=True)
                shutil.copyfile(data_dir / fname, save_dir / "dataset" / fname)

    C.WEIGHTS.mkdir(parents=True, exist_ok=True)
    deliverable = C.WEIGHTS / f"{save_dir.name}_best.pt"
    shutil.copyfile(best, deliverable)

    metrics = {k: round(float(v), 5) for k, v in (trainer.metrics or {}).items()}
    best_epoch = summarize_epochs(save_dir, logger)
    card = {
        "name": save_dir.name,
        "created": datetime.now().isoformat(timespec="seconds"),
        "weights": str(deliverable),
        "class_names": dict(model.names) if hasattr(model, "names") else None,
        "selection_metric": "val mAP50-95 (Ultralytics fitness)",
        "best_epoch": best_epoch,
        "val_metrics_final": metrics,
        "train_config": cfg if not args.resume else "resumed; see args.yaml",
        "safety": safety,
        "min_free_ram_seen_gb": round(watchdog.min_ram_seen, 2) if watchdog.min_ram_seen != float("inf") else None,
        "environment": env,
        "log": str(log_path),
        "swap_in": "set VEHICLE_CLASSES in car_tracking.py to these class_names (id -> name) before "
                   "pointing car_tracking.py at this checkpoint -- it still hardcodes COCO ids "
                   "(2/3/5/7), which do not match this model's ids. "
                   "multi-object-tracking/test_finetuned.py reads model.names at runtime instead "
                   "and needs no such edit.",
    }
    C.save_json(save_dir / "model_card.json", card)
    C.save_json(deliverable.with_suffix(".json"), card)
    logger.info("best weights -> %s", deliverable)
    logger.info("val metrics: %s", metrics)
    if args.smoke:
        vloss = [best_epoch.get(k) for k in ("val_box_loss", "val_cls_loss", "val_dfl_loss")] if best_epoch else []
        healthy = bool(best_epoch) and all(v is not None and v == v for v in vloss) and best_epoch.get("mAP50", 0) > 0.01
        (logger.info if healthy else logger.error)(
            "SMOKE %s: best epoch mAP50=%.4f, val losses=%s", "PASS" if healthy else "FAIL -- do not start the long run",
            best_epoch.get("mAP50", 0) if best_epoch else 0, vloss)
    logger.info("next: python scripts/evaluate.py --model %s", deliverable)


if __name__ == "__main__":
    main()
