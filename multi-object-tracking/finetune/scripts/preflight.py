"""
Pre-flight checklist before a long training run
================================================
Run it right before `train.py`. It changes nothing on the system; it only reports:

  GREEN   every check passed -> start training
  AMBER   no blockers, but read the warnings (e.g. on battery, sleep enabled)
  RED     at least one blocker -> fix it first

Checks: CUDA build and GPU, no other GPU/training jobs, free VRAM, free system RAM,
free disk, power source, Windows sleep timeout, train.yaml sanity (fixed batch,
workers, weights present), dataset files, and a live test that the VRAM cap really
turns an oversized allocation into an out-of-memory error instead of spilling into
system RAM.

    python scripts/preflight.py
"""

import argparse
import re
import subprocess

import common as C

# Measured peak for yolo11x @ 960 @ batch 2 (decision.md): the cap test proves this fits.
EXPECTED_PEAK_GB = 4.93


def parse_args():
    parser = argparse.ArgumentParser(description="Pre-flight checks before training")
    parser.add_argument("--config", default="configs/train.yaml")
    parser.add_argument("--min-ram-gb", type=float, default=6.0, help="Free system RAM needed to start")
    parser.add_argument("--min-disk-gb", type=float, default=15.0)
    return parser.parse_args()


def sleep_timeout_ac_minutes():
    """Windows AC sleep timeout in minutes (0 = never), or None if unknown."""
    try:
        out = subprocess.check_output(["powercfg", "/query", "SCHEME_CURRENT", "SUB_SLEEP", "STANDBYIDLE"],
                                      text=True, timeout=10, stderr=subprocess.DEVNULL)
        match = re.search(r"Current AC Power Setting Index:\s*0x([0-9a-fA-F]+)", out)
        return int(match.group(1), 16) // 60 if match else None
    except Exception:
        return None


def main():
    args = parse_args()
    logger, log_path, _ = C.setup_logging("preflight")
    results = []

    def check(name, status, detail):
        results.append((name, status, detail))
        (logger.info if status == "PASS" else logger.warning if status == "WARN" else logger.error)(
            "%-5s %-26s %s", status, name, detail)

    import psutil
    import torch

    # ---- GPU / CUDA
    env = C.environment_info()
    if not env["cuda_available"]:
        check("CUDA", "FAIL", "torch cannot see a CUDA GPU (CPU-only wheel?)")
    else:
        ok = env["torch_cuda_build"] and tuple(map(int, env["torch_cuda_build"].split(".")[:2])) >= (12, 8)
        check("CUDA", "PASS" if ok else "FAIL",
              f"{env['gpu']} {env['vram_gb']} GB, torch {env['torch']} (CUDA {env['torch_cuda_build']}), "
              f"ultralytics {env['ultralytics']}" + ("" if ok else " -- RTX 50-series needs CUDA >= 12.8"))

    # ---- other jobs
    me = psutil.Process().pid
    others = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmd = " ".join(proc.info["cmdline"] or [])
            if proc.info["pid"] != me and "python" in (proc.info["name"] or "").lower() and re.search(
                    r"train\.py|evaluate\.py|benchmark_train\.py|autolabel\.py|degrade\.py|yolo\s", cmd):
                others.append(f"{proc.info['pid']}: {cmd[:80]}")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    check("other ML jobs", "FAIL" if others else "PASS",
          "; ".join(others) if others else "none running (one GPU job at a time)")

    gpu = C.gpu_stats()
    if gpu:
        used = gpu["gpu_mem_used_gb"]
        check("VRAM in use by others", "PASS" if used <= 1.5 else "WARN" if used <= 2.5 else "FAIL",
              f"{used:.2f} GB used before start (desktop/browser/overlays); util {gpu['gpu_util_pct']:.0f}%, "
              f"{gpu['gpu_temp_c']:.0f} C")

    # ---- system RAM
    vm = psutil.virtual_memory()
    avail = vm.available / 1024**3
    top = sorted(((p.info["memory_info"].rss / 1024**3, p.info["name"]) for p in
                  psutil.process_iter(["name", "memory_info"]) if p.info["memory_info"]), reverse=True)[:5]
    hint = ", ".join(f"{n} {g:.1f} GB" for g, n in top)
    status = "PASS" if avail >= args.min_ram_gb else "WARN" if avail >= args.min_ram_gb - 2 else "FAIL"
    check("free system RAM", status, f"{avail:.1f} of {vm.total / 1024**3:.1f} GB free (need >= {args.min_ram_gb}); "
                                     f"largest: {hint}")

    # ---- disk
    disk = psutil.disk_usage(str(C.FINETUNE_ROOT))
    free_gb = disk.free / 1024**3
    check("free disk", "PASS" if free_gb >= args.min_disk_gb else "FAIL",
          f"{free_gb:.0f} GB free on the finetune drive (checkpoints ~0.1 GB each, plots, logs)")

    # ---- power
    battery = psutil.sensors_battery()
    if battery is not None:
        check("power", "PASS" if battery.power_plugged else "WARN",
              f"{'plugged in' if battery.power_plugged else 'ON BATTERY -- plug in'} ({battery.percent:.0f}%)")
    sleep = sleep_timeout_ac_minutes()
    if sleep is not None:
        check("sleep on AC", "PASS" if sleep == 0 else "WARN",
              "never" if sleep == 0 else f"after {sleep} min -- set 'When plugged in, put my device to sleep after' "
                                         f"to Never (Settings > System > Power), or the run pauses")

    # ---- config
    cfg = C.load_yaml(C.resolve(args.config))
    batch, workers = cfg.get("batch"), cfg.get("workers", 8)
    check("config batch", "PASS" if isinstance(batch, int) and batch >= 1 else "FAIL",
          f"batch={batch!r}" + ("" if isinstance(batch, int) and batch >= 1 else " -- must be a fixed integer"))
    check("config workers", "PASS" if workers <= 1 else "WARN" if workers <= 2 else "FAIL",
          f"workers={workers} (on this 16 GB laptop every worker adds train + val loader processes, "
          f"~1.2 GB RAM each; 1 is measured-optimal, decision.md D7)")
    weights = C.resolve_weights(cfg.get("model", ""))
    check("start weights", "PASS" if weights.exists() else "FAIL", str(weights))
    safety = cfg.get("safety") or {}
    check("safety block", "PASS" if safety.get("max_vram_fraction") else "WARN",
          f"{safety}" if safety else "no safety block in train.yaml -- defaults will be used")

    # ---- dataset
    data_yaml = C.resolve(cfg.get("data", ""))
    if not data_yaml.exists():
        check("dataset", "FAIL", f"{data_yaml} missing -- run prepare_dataset.py")
    else:
        data = C.load_yaml(data_yaml)
        root = C.resolve(data["path"])
        problems, counts = [], {}
        for split in ("train", "val"):
            images = C.list_images(root / data[split])
            labels = root / "labels" / split
            missing = sum(1 for p in images if not (labels / (p.stem + ".txt")).exists())
            counts[split] = len(images)
            if not images or missing:
                problems.append(f"{split}: {len(images)} images, {missing} without labels")
        names_ok = [data["names"][i] for i in sorted(data["names"])] == C.Classes().names
        if not names_ok:
            problems.append("class names differ from configs/classes.yaml")
        check("dataset", "FAIL" if problems else "PASS", "; ".join(problems) if problems else
              f"{counts} images, every image has a label file, 5 classes match")

    # ---- live VRAM cap test
    if env["cuda_available"]:
        fraction = float(safety.get("max_vram_fraction", 0.8))
        cap = C.guard_gpu_memory(fraction)
        blocked = fits = False
        try:
            probe = torch.empty(int((cap + 0.5) * 1024**3), dtype=torch.uint8, device=0)
            del probe
        except torch.cuda.OutOfMemoryError:
            blocked = True
        C.free_gpu()
        try:
            probe = torch.empty(int(EXPECTED_PEAK_GB * 1024**3), dtype=torch.uint8, device=0)
            del probe
            fits = True
        except torch.cuda.OutOfMemoryError:
            fits = False
        C.free_gpu()
        check("VRAM cap enforced", "PASS" if blocked else "FAIL",
              f"allocating {cap + 0.5:.1f} GB > cap {cap:.2f} GB {'raised out-of-memory (good)' if blocked else 'was ALLOWED -- cap not working'}")
        check("training peak fits", "PASS" if fits else "FAIL",
              f"{EXPECTED_PEAK_GB} GB (measured yolo11x @ 960 @ batch 2) {'allocated under the cap' if fits else 'did NOT fit'}")

    fails = [r for r in results if r[1] == "FAIL"]
    warns = [r for r in results if r[1] == "WARN"]
    verdict = "RED" if fails else "AMBER" if warns else "GREEN"
    logger.info("=" * 70)
    logger.info("PREFLIGHT %s: %d pass, %d warn, %d fail", verdict, len(results) - len(fails) - len(warns),
                len(warns), len(fails))
    for name, _, detail in fails + warns:
        logger.info("  fix: %s -- %s", name, detail)
    C.save_json(C.LOGS / "preflight_last.json", {"verdict": verdict, "checks": results, "log": str(log_path)})
    raise SystemExit(1 if fails else 0)


if __name__ == "__main__":
    main()
