# Training decisions: model, resolution, batch, workers, safety (and how to change them)

This records **why** `configs/train.yaml` has the values it has, with the measurements behind them, and how to retune on different hardware (a bigger GPU, Colab, a workstation). Every number here was measured on this machine; none is a rule of thumb.

---

## Machine

| | |
|---|---|
| GPU | NVIDIA GeForce RTX 5060 Laptop, **7.96 GB** VRAM, driver 591.91 |
| System RAM | **15.4 GB** (≈ 7 GB free with normal apps open), pagefile 21 GB |
| Software | Windows 11, Python 3.11.9, torch 2.11.0+cu128, ultralytics 8.4.149 |
| Dataset | `datasets/veh5`: 7,937 train / 1,075 val images |
| Date | 2026-09-13 |

## Current settings

| key | value | decision |
|---|---|---|
| `model` | yolo11x.pt | D1 |
| `imgsz` | 960 | D1 |
| `batch` | 2 | D2 |
| `nbs` | 64 | D3 |
| `workers` | 1 | D7 |
| `epochs` / `patience` | 50 / 12 | D4 |
| `safety` | VRAM cap 80%, RAM ≥ 1.5 GB, slow-step watchdog | D7 |

---

## Measurements

### Model × resolution × batch (`scripts/benchmark_train.py`, workers 4)
~40 real training steps each: real data loader, augmentation, AMP, loss, backward.

| model | imgsz | batch | peak VRAM (GB) | img/s | train epoch (min) | 50 epochs (h) | outcome |
|---|---:|---:|---:|---:|---:|---:|---|
| yolo11x | 960 | 4 | **8.88** | 0.47 | 281.5 | 245 | ❌ exceeds VRAM → spills to system RAM, 17× slower |
| yolo11x | 960 | 3 | 7.04 | 6.63 | 20.0 | 17.4 | ❌ slower than batch 2 (memory pressure) |
| **yolo11x** | **960** | **2** | **4.93** | **8.23** | **16.1** | **14.0** | ✅ **chosen** |
| yolo11x | 800 | 4 | 6.35 | 12.42 | 10.7 | 9.3 | lower resolution |
| yolo11x | 640 | 8 | 7.77 | 5.41 | 24.5 | 21.3 | ❌ at the VRAM limit |
| yolo11l | 960 | 4 | 5.99 | 14.81 | 8.9 | 7.8 | faster, smaller model |
| yolo11l | 960 | 5 | 7.15 | 14.12 | 9.4 | 8.2 | no faster |

### Data-loader workers for yolo11x · 960 · batch 2 (each in a fresh process)

| workers | img/s | min free system RAM | Python processes | 50 epochs (h) |
|---:|---:|---:|---:|---:|
| 0 | 7.01 | 4.28 GB | 1 | 16.4 |
| **1** | **8.17** | **2.92 GB** | 5 | **14.1** |
| 2 | 8.26 | 1.71 GB | 8 | 13.9 |

Raw results: `runs/benchmark_train.json`, `runs/benchmark_train_round2.json`, `runs/benchmark_workers{0,1,2}.json`.

---

## Decisions

### D1: yolo11x at `imgsz: 960` (quality first)
- **The owner's requirement is maximum accuracy; training time is acceptable.** YOLO11x is the most accurate YOLO11 size (Ultralytics COCO val mAP50-95: 54.7 for x vs 53.4 for l). Extra capacity matters most for the rare, visually similar classes here (bus vs truck, auto_rickshaw vs motorcycle/car).
- **Resolution stays at 960** because distant autos and bikes are small objects. It's also the tracker's inference size, so training and deployment see objects at the same scale.
- The earlier yolo11l choice was a speed trade-off (7.8 h vs 14 h). It's still the documented fallback if a single night is a hard limit.

### D2: fixed `batch: 2`, never AutoBatch on this machine
- Batch 4 at 960 needs 8.88 GB, more than the card has. Batch 3 fits (7.04 GB) but is *slower* than batch 2, because the allocator is fighting fragmentation at the edge of memory.
- `batch: 0.70` / `-1` (AutoBatch) failed on this laptop. The probe returned 0 → default 16 → out of memory → retry at 8 → the Windows driver spilled into system RAM: GPU 2% busy, 20 GB of virtual memory used, no error.
- `train.py` now refuses a non-integer batch.

**Does batch 2 lower accuracy, or only cost time?** Mostly time, with one real, small caveat:
- **The optimizer is unaffected** because of gradient accumulation (D3): it steps once per 64 images, just as with a large batch.
- **BatchNorm is affected.** BN computes mean and variance over the images in one forward pass, and over 2 images those estimates are noisy. With fine-tuning from COCO weights, whose BN statistics are already well trained and change slowly (momentum), the effect is small. It's the reason a bigger GPU with batch ≥ 16 is worth retrying (see the tuning guide). Choosing x at batch 2 over l at batch 4 is a bet that model capacity outweighs slightly noisier BN, which matches common fine-tuning experience. Verify it on a bigger GPU if you get one.

### D3: `nbs: 64` (gradient accumulation)
Ultralytics sums gradients until `nbs` images have been processed (32 batches of 2), then takes one optimizer step, and scales weight decay to match. The learning rate therefore needs no manual scaling for the small batch.

### D4: `epochs: 50`, `patience: 12`
- Measured ≈ 16 min training + ≈ 1.5 min validation per epoch, so 50 epochs ≈ **14–15 h**. Early stopping usually ends fine-tuning earlier; the per-epoch log line prints a live ETA.
- **Don't cut `epochs` to "finish faster".** The cosine learning-rate schedule is planned over `epochs`: fewer epochs means a steeper decay, not the same training stopped early. If time is short, stop the run and resume it the next night (`--resume` restores the schedule exactly).

### D5: other settings kept
| key | value | reason |
|---|---|---|
| `amp` | true | FP16 halves activation memory; every number above assumes it |
| `cache` | false | RAM caching can't fit in 15.4 GB; disk caching (~20 GB) isn't needed at 8 img/s |
| `close_mosaic` | 10 | last 10 epochs on un-mosaicked images, for better real-image calibration |
| `save_period` | 10 | snapshots every 10 epochs (~110 MB each) in addition to `last.pt` / `best.pt` |
| `cos_lr`, `optimizer: auto` | defaults | Ultralytics picks SGD/AdamW from the iteration count |

### D6: smoke test = 3 epochs × 30% of train, with a PASS/FAIL gate
A 1-epoch × 10% smoke run once showed NaN val loss and mAP 0 on a healthy pipeline. The newly initialised 5-class output layer hadn't left the 3-epoch learning-rate warmup, so its random logits overflowed FP16. Evidence:
- zero non-finite weights on disk
- weights changed by at most 0.004 versus COCO
- class scores of 0.6 on pure noise input
- FP16 forward pass NaN while FP32 was finite
- validation mAP 0 in both FP16 and FP32

With 3 epochs × 30% the yolo11l check reached mAP50 0.218 → 0.208 → 0.414 with finite losses. `train.py --smoke` prints **SMOKE PASS** only when the best epoch has finite val losses and mAP50 > 0.01.

### D7: memory safety, after the 2026-09-13 laptop freeze
**What happened** (Windows event log + our logs):

| time | event |
|---|---|
| 16:56 | Windows "low virtual memory": the AutoBatch yolo11x run's Python processes used 20.2 GB + 14.6 GB of virtual memory |
| 17:52:06 | `evaluate.py` validates the fine-tuned model, then loads the **yolo11x baseline at batch 8** while the first model is still on the GPU |
| 17:52:25 | last log line |
| 18:17:47 | unexpected shutdown (Kernel-Power 41): the machine had been frozen and was hard-reset |

**Root cause:** on Windows the NVIDIA driver doesn't raise an out-of-memory error when VRAM is full. It silently moves GPU memory into shared system RAM. On a 15.4 GB machine that pushes Windows into heavy paging, and the whole system stops responding instead of Python crashing.

**Second finding, measured with a 5-second RAM/VRAM sampler:** during yolo11x training with `workers: 2` there were **8 Python processes** (main + 2 training + 4 validation loader workers, which stay alive all run). Committed memory went from 11.5 → 26.7 GB and free RAM fell to 1.7 GB. On Windows each loader worker is a separate process that re-imports PyTorch and the CUDA libraries (~1.2 GB each). Linux shares that memory between processes; Windows can't.

**Safety layers now in place:**

| layer | where | what it does | tested |
|---|---|---|---|
| VRAM hard cap 80% (6.37 GB) | `common.guard_gpu_memory`, called by train / evaluate / autolabel / extract_frames / benchmark | PyTorch raises a normal out-of-memory error instead of spilling into system RAM | `preflight.py`: a 6.9 GB allocation was refused; the 4.93 GB training peak was allowed |
| Fixed batch 2, no AutoBatch | `train.yaml`, `train.py` refuses non-integer batch | removes the probe → 16 → 8 → spill chain | benchmark |
| `workers: 1` | `train.yaml` | 5 instead of 8 processes, +1.2 GB free RAM for 1% speed | worker benchmark above |
| RAM watchdog | `train.py` `ResourceWatchdog` | stops cleanly (resumable) if free RAM stays < 1.5 GB for 30 steps | forced trip (threshold 999 GB): stopped at step 30, exit code 3, 0 processes left, VRAM back to 741 MiB |
| Slow-step watchdog | same | stops cleanly if 20 consecutive steps are > 4× the running median step time (the signature of memory spilling) | logic shares the tested stop path |
| One model on the GPU at a time | `evaluate.py` frees the fine-tuned model before loading the baseline; defaults batch 2, workers 2, same VRAM cap | removes the exact freeze scenario | verification below |
| Resource log | `runs/<name>/resources.csv` + one line per epoch in the log | step time, img/s, VRAM peak, free RAM, GPU util/temp/power, ETA | smoke run |
| Pre-flight checklist | `scripts/preflight.py` | GPU, other jobs, free VRAM/RAM/disk, power, sleep, config, dataset, live VRAM-cap test → GREEN / AMBER / RED | GREEN, 14/14 |

**Things only you can do (system settings; the scripts deliberately don't change them):**
- **NVIDIA App → Graphics → Global settings → "CUDA - Sysmem Fallback Policy" → "Prefer No Sysmem Fallback".** This is the driver-level version of the VRAM cap and a good second line of defence.
- Close memory-heavy apps before the run (Teams, browsers, download managers, a local MySQL server). Every GB freed is margin.
- Keep the laptop plugged in and on a hard surface; GPU temperature is logged per epoch.

---

## How to retune for different hardware

### Step 1: always measure first
```powershell
$py scripts\preflight.py
$py scripts\benchmark_train.py --candidates yolo11x.pt:960:8 yolo11x.pt:960:16 --workers 4
```
Accept a candidate only if:
- `status` is `ok` (not `OOM -> fell back`, not `too slow`)
- peak VRAM ≤ card VRAM − 0.6 GB, `min_free_ram_gb` ≥ ~3 GB
- img/s rises when batch rises. If it falls, you're at the memory edge.
- the 50-epoch estimate fits your time window. Colab sessions are limited; plan to `--resume`.

### Step 2: spend extra resources in this order (largest accuracy gain first)

| priority | change | why | cost |
|---|---|---|---|
| 1 | **batch 2 → 16+** (keep `nbs: 64`) | removes the BatchNorm caveat of D2; cleaner gradients per step | VRAM; usually faster |
| 2 | **more data**: `max_images.train` in `sources.yaml` 6000 → 12000–20000 (IDD has ~33k train-pool images) | more drive diversity; usually worth more than epochs | epoch time grows linearly |
| 3 | **real night data** (README future scope 1–3) | the main known gap | data work |
| 4 | **epochs 50 → 100, patience 12 → 20** | only if val mAP was still rising at the end | time |
| 5 | **imgsz 960 → 1280** | smaller distant vehicles | ~1.8× VRAM per image; **only if the tracker also runs at 1280** |
| 6 | `workers` 4–8, `cache: ram` | only when GPU utilisation stays below ~90% and RAM allows (Linux or ≥ 32 GB RAM) | RAM |

### Step 3: starting points by hardware (confirm with Step 1)
VRAM per image at 960 is ≈ 2.1 GB for yolo11x and ≈ 1.2 GB for yolo11l (training, AMP), plus ~0.7–1.3 GB base. It scales roughly with imgsz².

| hardware | model · imgsz · batch · workers | est. peak VRAM | notes |
|---|---|---:|---|
| 8 GB laptop, 16 GB RAM (this) | **yolo11x · 960 · 2 · 1** | 4.9 GB | measured |
| 12 GB GPU, 32 GB RAM | yolo11x · 960 · 4 · 2 | ~9.1 GB | |
| 16 GB (e.g. Colab T4) | yolo11x · 960 · 6 · 2 | ~13.3 GB | T4 is slower than a 5060; resume across sessions |
| 24 GB | **yolo11x · 960 · 10 · 4** | ~21.7 GB | good all-round target |
| 40 GB | yolo11x · 960 · 16 · 8 | ~34 GB | |
| 80 GB | yolo11x · 960 · 32 · 8, or 1280 · 16 | ~68 / ~60 GB | 1280 only with 1280 inference |

On Linux, raise `workers` more freely (loader processes share memory there). When batch exceeds 64, set `nbs` equal to the batch. On a GPU with plenty of headroom you can raise `safety.max_vram_fraction` to 0.9.

### Step 4: every key you might touch in `configs/train.yaml`

| key | what it does | when to change | typical values |
|---|---|---|---|
| `model` | starting checkpoint | per Step 2/3; or `weights\<run>_best.pt` to continue from a previous round on a new data mix | yolo11l/x.pt |
| `imgsz` | training resolution (letterboxed square) | keep equal to tracker `--imgsz` | 640 / 960 / 1280 |
| `batch` | images per forward pass | per benchmark; integer only | 2–64 |
| `nbs` | images per optimizer step | only when batch > 64 | 64 |
| `workers` | data-loader processes | per benchmark; RAM-bound on Windows | 1–8 |
| `epochs` | length of the LR schedule | when curves still rise at the end; don't cut it to save time (D4) | 50–150 |
| `patience` | early-stop window on val mAP50-95 | ~20–25% of epochs | 10–25 |
| `cache` | pre-decoded images | GPU starved and RAM/disk available | false / disk / ram |
| `amp` | mixed precision | keep true | true |
| `optimizer`, `lr0`, `lrf` | optimizer and LR schedule | leave `auto` unless an ablation says otherwise | auto |
| `close_mosaic` | last N epochs without mosaic | ~10–20% of epochs | 10–15 |
| `mosaic`, `scale`, `translate`, `fliplr`, `hsv_*` | augmentation | reduce `scale` if tiny objects vanish; keep `flipud: 0` | defaults |
| `box`, `cls`, `dfl` | loss gains | only with an ablation; slightly higher `cls` if auto/motorcycle confusion dominates while localisation is good | 7.5 / 0.5 / 1.5 |
| `save_period` | snapshot interval | larger runs: 10–25 | 10 |
| `fraction` | train on part of the data | quick experiments only | 1.0 |
| `seed`, `deterministic` | reproducibility | keep fixed when comparing changes | 0 / true |
| `safety.max_vram_fraction` | VRAM hard cap | 0.9 on a dedicated GPU with no display attached | 0.8 |
| `safety.min_free_ram_gb` | RAM watchdog threshold | ~10% of system RAM | 1.5–4 |
| `safety.slow_step_*` | slow-step watchdog | loosen (factor 6) only if disk I/O is known to be bursty | 4.0 / 20 |

Related knobs outside `train.yaml`:
- `configs/sources.yaml`: `max_images` (more data), enabling new sources after `inspect_source.py`.
- `degrade.py --fraction`: share of synthetic night/blur copies (0.25 now; ~0.4 if `bench_night` recall is weak and there's still no real night data).

### Step 5: prove a change helped
1. Change **one** thing at a time; keep `seed` and the dataset fixed.
2. Evaluate both runs on the same splits (`evaluate.py`, plus `--split bench_night --recall-only`).
3. Accept it only if the headline (test mAP50-95, auto_rickshaw mAP50) improves by more than ~0.005, no class drops by more than ~0.01, and bench_night recall doesn't fall.
4. Add a row to the decision log.

---

## Verification before the first overnight run (2026-09-13, final config)

Every test ran one GPU job at a time, with a 5-second RAM/VRAM sampler running throughout.

| test | what it proves | result |
|---|---|---|
| `preflight.py` | environment, config, dataset, VRAM cap really enforced | **GREEN 14/14**; a 6.9 GB allocation refused, the 4.93 GB training peak allowed |
| RAM watchdog forced trip (`--min-free-ram-gb 999`) | a resource problem stops training instead of freezing Windows | stopped at step 30, exit code 3, 0 Python processes left, VRAM back to 741 MiB |
| Worker benchmark (0/1/2) | RAM vs speed trade-off | workers 1: 8.17 img/s, min free RAM 2.92 GB (table above) |
| Smoke run yolo11x · 960 · 2 · workers 1 (3 epochs × 30%) | real training works end to end | **SMOKE PASS**: val mAP50 0.053 → 0.155 → 0.260, all val losses finite and falling (box 2.18 → 1.94 → 1.67, cls 3.40 → 2.73 → 2.08) |
| Simulated crash: process tree killed 90 s into epoch 2 | an overnight crash loses at most the current epoch | 0 processes left, VRAM freed, `last.pt` intact |
| `--resume` | training continues correctly | "Resuming … from epoch 2 to 3", same LR schedule, finished with SMOKE PASS |
| `evaluate.py` fine-tuned + yolo11x baseline (DAWN test), then `--recall-only` bench_night with baseline: the exact scenario that froze the laptop | evaluation is safe now | both exit 0, 0 processes left; peak GPU memory 4.98 GB, min free RAM 4.47 GB, max 4 Python processes (verdict FAIL is expected for a 3-epoch smoke model) |
| Resources during training | measured headroom | 7.8–8.0 img/s; VRAM peak 5.52 GB (validation phase) under the 6.37 GB cap; free RAM min 2.24 GB above the 1.5 GB watchdog; GPU 74–83 °C at 85–89 W |

**On the smoke mAP:** yolo11x reached 0.26 mAP50 after 3 short epochs, versus 0.41 for yolo11l in its smoke test. That's expected and says nothing about final accuracy:
- These epochs sit entirely inside the learning-rate warmup.
- A model twice the size adapts more slowly at first.
- Epoch 2 here was restarted by the crash test.

The smoke test gates pipeline health, not model quality.

---

## Decision log

| date | hardware | change | evidence | result |
|---|---|---|---|---|
| 2026-09-13 | RTX 5060 Laptop 8 GB | yolo11l · 960 · 4 | first benchmark | superseded: owner prioritises accuracy |
| 2026-09-13 | RTX 5060 Laptop 8 GB / 15.4 GB RAM | yolo11x · 960 · batch 2 · nbs 64 · workers 1 · safety layers | benchmarks, freeze analysis, tests | chosen for the first overnight run |
