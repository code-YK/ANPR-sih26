"""
Measure real training throughput and peak VRAM for candidate settings
=====================================================================
AutoBatch is unreliable on 8 GB laptop GPUs: its probe can fail, Ultralytics then
retries smaller batches after an OOM, and on Windows the NVIDIA driver may silently
spill into system RAM ("sysmem fallback") -- training does not crash, it crawls.

This runs a few dozen real training steps (real data loader, augmentation, AMP, loss,
backward) per candidate and records images/s and peak reserved VRAM, then estimates
epoch and full-run time for the dataset. Pick the fastest candidate whose peak VRAM
stays clearly below the card's memory, and put it in configs/train.yaml.

    python scripts/benchmark_train.py
    python scripts/benchmark_train.py --candidates yolo11x.pt:960:4 yolo11l.pt:960:6
"""

import argparse
import shutil
import time

import common as C

DEFAULT_CANDIDATES = ["yolo11x.pt:960:4", "yolo11x.pt:960:2", "yolo11x.pt:800:4", "yolo11x.pt:640:8",
                      "yolo11l.pt:960:4"]


class StopBenchmark(Exception):
    pass


def parse_args():
    parser = argparse.ArgumentParser(description="Benchmark training speed / VRAM")
    parser.add_argument("--data", default="datasets/veh5/data.yaml")
    parser.add_argument("--candidates", nargs="+", default=DEFAULT_CANDIDATES, help="model:imgsz:batch")
    parser.add_argument("--steps", type=int, default=40, help="Measured steps after warm-up")
    parser.add_argument("--warmup", type=int, default=8)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--epochs-planned", type=int, default=50)
    parser.add_argument("--safety-gb", type=float, default=0.6, help="Required VRAM headroom")
    parser.add_argument("--max-step-s", type=float, default=30.0, help="Abort a candidate if one step is slower")
    parser.add_argument("--max-vram-fraction", type=float, default=0.80, help="Same VRAM cap as train.py")
    return parser.parse_args()


def count_train_images(data_yaml):
    cfg = C.load_yaml(data_yaml)
    root = C.resolve(cfg["path"])
    train = len(C.list_images(root / cfg["train"]))
    val = len(C.list_images(root / cfg["val"]))
    return train, val


def run_candidate(spec, args, data_yaml, logger):
    import psutil
    import torch
    from ultralytics import YOLO

    model_name, imgsz, batch = spec.split(":")
    imgsz, batch = int(imgsz), int(batch)
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    stamps, used_batch, ram_free = [], [], []

    def on_batch_end(trainer):
        now = time.perf_counter()
        ram_free.append(psutil.virtual_memory().available / 1024**3)
        # Ultralytics silently halves the batch after an OOM -- record what really ran
        used_batch.append(int(trainer.batch_size))
        if stamps and now - stamps[-1] > args.max_step_s:
            stamps.append(now)
            raise StopBenchmark("slow")
        stamps.append(now)
        if len(stamps) >= args.warmup + args.steps:
            raise StopBenchmark("done")

    model = YOLO(str(C.resolve_weights(model_name)))
    model.add_callback("on_train_batch_end", on_batch_end)
    name = f"_bench_{model_name.split('.')[0]}_{imgsz}_{batch}"
    status = "ok"
    try:
        model.train(data=str(data_yaml), imgsz=imgsz, batch=batch, epochs=1, workers=args.workers, amp=True,
                    cache=False, val=False, plots=False, project=str(C.RUNS), name=name, exist_ok=True,
                    verbose=False, warmup_epochs=0)
    except StopBenchmark as stop:
        if str(stop) == "slow":
            status = f"too slow (a step took > {args.max_step_s}s: system-RAM fallback or OOM retries)"
    except torch.cuda.OutOfMemoryError:
        status = "OOM"
    except RuntimeError as exc:
        status = "OOM" if "out of memory" in str(exc).lower() else f"error: {exc}"
    finally:
        shutil.rmtree(C.RUNS / name, ignore_errors=True)

    total_gb = torch.cuda.get_device_properties(0).total_memory / 1024**3
    peak_gb = torch.cuda.max_memory_reserved() / 1024**3
    real_batch = used_batch[-1] if used_batch else batch
    result = {"model": model_name, "imgsz": imgsz, "batch": batch, "workers": args.workers, "status": status,
              "peak_reserved_gb": round(peak_gb, 2), "vram_gb": round(total_gb, 2),
              "min_free_ram_gb": round(min(ram_free), 2) if ram_free else None,
              "median_free_ram_gb": round(sorted(ram_free)[len(ram_free) // 2], 2) if ram_free else None}
    if real_batch != batch:
        result["status"] = f"OOM -> Ultralytics fell back to batch {real_batch}"
        status = result["status"]
    measured = stamps[args.warmup:]
    if status == "ok" and len(measured) >= 2:
        sec_per_step = (measured[-1] - measured[0]) / (len(measured) - 1)
        result["images_per_s"] = round(batch / sec_per_step, 2)
        result["sec_per_step"] = round(sec_per_step, 3)
    elif status == "ok":
        result["status"] = "too few steps (dataset too small?)"
    if peak_gb > total_gb - args.safety_gb:
        result["warning"] = "peak VRAM within safety margin -- risk of OOM or silent system-RAM fallback"
    logger.info("%s", result)
    del model
    torch.cuda.empty_cache()
    return result


def main():
    args = parse_args()
    data_yaml = C.resolve(args.data)
    logger, log_path, file_handler = C.setup_logging("benchmark_train")
    C.attach_ultralytics_log(file_handler)
    env = C.environment_info()
    if not env["cuda_available"]:
        raise SystemExit("CUDA not available")
    C.guard_gpu_memory(args.max_vram_fraction, logger)
    train_imgs, val_imgs = count_train_images(data_yaml)
    logger.info("dataset: %d train / %d val images | %s", train_imgs, val_imgs, env)

    results = [run_candidate(spec, args, data_yaml, logger) for spec in args.candidates]

    lines = ["| model | imgsz | batch | status | img/s | peak VRAM GB | train epoch (min) | "
             f"{args.epochs_planned} epochs (h, incl. ~val) |", "|---|---:|---:|---|---:|---:|---:|---:|"]
    for r in results:
        if "images_per_s" in r:
            epoch_min = train_imgs / r["images_per_s"] / 60
            # validation runs forward-only at ~3x training throughput
            val_min = val_imgs / (3 * r["images_per_s"]) / 60
            total_h = args.epochs_planned * (epoch_min + val_min) / 60
            lines.append(f"| {r['model']} | {r['imgsz']} | {r['batch']} | {r['status']}{' ⚠' if 'warning' in r else ''} | "
                         f"{r['images_per_s']} | {r['peak_reserved_gb']} | {epoch_min:.1f} | {total_h:.1f} |")
            r.update(epoch_min=round(epoch_min, 1), run_hours=round(total_h, 1))
        else:
            lines.append(f"| {r['model']} | {r['imgsz']} | {r['batch']} | {r['status']} | - | "
                         f"{r['peak_reserved_gb']} | - | - |")
    for line in lines:
        logger.info(line)
    C.save_json(C.RUNS / "benchmark_train.json", {"dataset": str(data_yaml), "train_images": train_imgs,
                                                  "val_images": val_imgs, "results": results, "log": str(log_path)})
    logger.info("saved %s", C.RUNS / "benchmark_train.json")


if __name__ == "__main__":
    main()
