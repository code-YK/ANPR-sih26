# Vehicle model fine-tuning (adds `auto_rickshaw`)

This fine-tunes the COCO-pretrained `yolo11x.pt` into a **5-class Indian-road vehicle model**:

| id | class |
|---:|---|
| 0 | car |
| 1 | motorcycle |
| 2 | bus |
| 3 | truck |
| 4 | auto_rickshaw |

The tracker, fast-alpr and the workers stay the same. Swapping the model in takes three changes (see [Swap-in](#10-swap-in)).
The person / suspicious-activity workers keep using the original `yolo11x.pt`, because they need COCO's `person` class.

`scripts/`, `configs/` and this README are committed. `raw/`, `datasets/`, `runs/`, `weights/`, `logs/` and every `*.zip` under this folder are git-ignored (root `.gitignore`).

```
finetune/
├── README.md        this guide
├── decision.md      why model/imgsz/batch are what they are + retuning guide for other GPUs
├── configs/
│   ├── classes.yaml     canonical classes + raw-name aliases (the class-id contract)
│   ├── sources.yaml     every dataset: accept/reject decision + audit evidence, split strategy, caps
│   └── train.yaml       hyper-parameters (batch/imgsz from the benchmark), loss gains, checkpoints
├── scripts/
│   ├── inspect_source.py   audit a raw dataset: counts, contact sheets, teacher label audit, Roboflow flags
│   ├── prepare_dataset.py  raw/ -> datasets/veh5 (convert, remap, dedupe, stratified group split)
│   ├── autolabel.py        fill non-exhaustive classes with the baseline yolo11x
│   ├── degrade.py          synthetic night / IR / blur / low-quality copies
│   ├── check_dataset.py    counts, invalid labels, split leakage
│   ├── benchmark_train.py  measured img/s + peak VRAM per model/imgsz/batch -> run-time estimate
│   ├── train.py            training + per-epoch summary + model card + weights export
│   ├── evaluate.py         vs baseline: mAP/P/R/F1/IoU, size buckets, gates; recall-only benchmarks
│   └── extract_frames.py   your recordings -> frames (+ pre-labels)  [future scope]
├── raw/        extracted datasets
├── datasets/   veh5 (generated, safe to rebuild)
├── runs/       training runs, runs/eval/ reports, runs/inspect/ dataset audits, benchmark_train.json
├── weights/    final <run>_best.pt + <run>_best.json model cards
└── logs/       one timestamped log per script invocation
```

Run everything from this folder with the tracking venv:

```powershell
cd E:\vatsal\ANPR-sih26\multi-object-tracking\finetune
$py = "..\.venv\Scripts\python.exe"
```

---

## 0. Status and checklist

- [x] Datasets extracted into `raw/` and audited (section 1)
- [x] `datasets/veh5` built: prepare → autolabel → degrade (train)
- [x] `$py scripts\degrade.py --eval-sets`: `test_low_light`, `test_ir_night`, `test_motion_blur`, `test_low_res` (3,075 images each)
- [x] Benchmarks → **yolo11x · 960 · batch 2 · workers 1** in `configs/train.yaml` (section 5, [decision.md](decision.md))
- [x] Safety layers after the 2026-09-13 laptop freeze: VRAM cap, RAM + slow-step watchdog, one model at a time in `evaluate.py`, `preflight.py` (decision.md D7)
- [ ] `$py scripts\preflight.py` → must say **GREEN** (or AMBER with understood warnings)
- [ ] **Overnight** `$py scripts\train.py` (section 6): ≈ 14–15 h for 50 epochs, often less with early stopping; resume across nights is safe
- [ ] Evaluate: test split, per-source subsets, synthetic splits, `bench_night` recall (section 8)
- [ ] Swap in if the verdict is PASS (section 10)

Rebuild from scratch at any time (splits are deterministic):
```powershell
$py scripts\prepare_dataset.py --dry-run
$py scripts\prepare_dataset.py --force
$py scripts\autolabel.py --conf 0.5
$py scripts\degrade.py
$py scripts\degrade.py --eval-sets
```

---

## 1. Data: what was accepted, rejected and why

Every dataset was audited with `scripts/inspect_source.py` (reports and contact sheets in `runs/inspect/<name>/`). The audit runs the baseline yolo11x as a "teacher" on a random sample and measures:
- a **raw-class × teacher-class matrix**, which decodes what labels mean
- **likely-unlabelled vehicles**: confident teacher detections with no GT box under them, per 100 GT boxes
- **box tightness**: mean IoU of matched GT/teacher pairs
- **Roboflow export flags**: augmented copies, stretching, box-level augmentation

IDD is the quality reference. The teacher is weak at night, so night-set numbers are lower bounds on missing labels. Contact sheets and crops were inspected by eye as well.

| dataset | role | evidence | decision |
|---|---|---|---|
| **IDD Detection** (Kaggle YOLOv11), CC BY-NC-SA 4.0 | train / val / test | unlabelled cars **0.4**/100, tightness **0.849**, 42k images | ✅ Reference quality. Re-split by drive (section 2) |
| **DAWN** Fog + Rain (Mendeley), CC BY-NC 3.0 | train / val / test | 500 images, car/bus/truck/motorcycle | ✅ Real adverse weather |
| **vehicle detection from cctv (night) v4** (Roboflow Thammasat), CC BY 4.0 | **benchmark only** (`bench_night`) | real night CCTV incl. IR; motorbikes partially labelled (e.g. 2 of ~8 boxed); `heavy vehicle` = bus+truck, 85/302 unresolvable by the teacher | ⚠️ Not trained on (partial labels teach "vehicle = background"). **Recall-only** scoring is still valid |
| **Vehicle Detection Night time v5** (Roboflow duong-tran), CC BY 4.0 | rejected (for this version) | real overhead night CCTV (14 scenes), but **bounding-box-level rotation ±15° + blur**: every vehicle's pixels are rotated inside its box, leaving a **dashed seam rectangle**. Between the two copies of 120 originals, outside-box pixels are identical (mean diff 0.07) and inside-box pixels differ (18.4) in **120/120**; seams visible in **both** copies; 10.2 unlabelled cars/100 | ❌ An outline around every object is a trivially learnable shortcut. Fixable only by downloading an **unaugmented version** (future scope). Config kept, `enabled: false` |
| **Nighttime Vehicle detection v1** (Roboflow RVCE Bangalore), CC BY 4.0 | rejected | mostly daytime catalogue/web car photos, stretched to 416×416, 2.4 sheared/flipped copies per original, no bus/truck/auto labels, tightness **0.732** | ❌ Off-domain and noisy |

**Why a class missing from a dataset is not the problem:** DAWN has no `auto_rickshaw`, but also no autos in its images. A dataset that *shows* autos without labelling them would be harmful; that's one reason RVCE (Bangalore) is out.

**Why small datasets don't overfit the model:** each image is seen once per epoch (no oversampling) and `best.pt` is selected on val. The real risks are **label noise, partial labels, conflicting conventions and artefacts**, which is what the audit screens for. duong v5 shows why the visual checks matter: its numbers alone (tightness 0.840) looked fine.

---

## 2. Splits

| source | method | why | result (images) |
|---|---|---|---|
| IDD | **pooled + stratified group split** by drive sequence, 80/10/10, then sampled | IDD's own 8:1:1 split puts frames of the same drive in train/val/test (~2/3 of val/test share a drive with train, ~60 frames apart), which inflates val/test | pool 80.0/10.0/10.0 images, autos 80.2/9.9/9.9 → train 6,000 · val 1,000 · test 3,000 |
| DAWN fog, rain | stratified by image, 70/15/15 | no native split; 15% test so weather is measured | 350 · 75 · 75 |
| night_thammasat | fixed → `bench_night` | incomplete labels: evaluation only, recall only | 444 |

**The stratified group split** places whole groups, largest first, so every split fills at the same pace in image count and in boxes of every class. No drive is shared across splits.

**Why these sizes:**
- **Train** is cut because it drives epoch time.
- **Val** runs every epoch, so it stays small but has hundreds of boxes per class.
- **Test** runs once but needs stable per-class numbers.

Built dataset (`check_dataset.py`):

| split | images | car | motorcycle | bus | truck | auto_rickshaw |
|---|---:|---:|---:|---:|---:|---:|
| train (real) | 6,350 | 14,914 | 14,858 | 2,714 | 4,234 | 4,696 |
| train (+ synthetic copies) | +1,587 | | | | | |
| val | 1,075 | 2,557 | 2,194 | 457 | 720 | 734 |
| test | 3,075 | 6,821 | 7,087 | 1,404 | 2,032 | 2,280 |
| bench_night | 444 | 490 | 438 | bus+truck: 302 | | 0 |

About 8% of images contain none of the 5 classes after mapping (e.g. only pedestrians or signs). They stay in as background images, which reduces false positives.

---

## 3. Build details

- `prepare_dataset.py`: conversion, class mapping, dedupe, per-group sampling, splits. `--dry-run` first, always. `--disable <source>` builds ablation variants from the same config.
- `autolabel.py --conf 0.5`: for sources whose `labelled_classes` isn't `all` (none in the current mix). Adds a teacher detection only if it doesn't overlap an existing box. Review images go to `datasets/veh5/review_autolabel/`.
- `degrade.py`: 25% synthetic copies of degradable train images (`degrade: false` sources skipped). `--eval-sets` builds `test_low_light`, `test_ir_night`, `test_motion_blur`, `test_low_res`.

## 4. Auditing a new dataset

```powershell
$py scripts\inspect_source.py raw\<folder> --name <name> --sample 300
```

Reject or restrict it if:
- unlabelled vehicles per 100 boxes are far above IDD's 0.4, or tightness is well below ~0.84
- contact sheets show off-domain images, or autos appear unlabelled
- the log warns **BOUNDING-BOX-LEVEL augmentation**: then look at box crops for seams, and prefer an unaugmented download

**To test whether a new source helps**, use a pilot ablation with a small model on the same test images:
```powershell
$py scripts\prepare_dataset.py --force --disable <new_source> --out datasets/veh5_A
$py scripts\train.py --model yolo11s.pt --imgsz 640 --epochs 15 --batch 16 --name pilot-A --data datasets/veh5_A/data.yaml
$py scripts\train.py --model yolo11s.pt --imgsz 640 --epochs 15 --batch 16 --name pilot-B
# evaluate both against datasets/veh5 (the superset) with --sources idd, --sources <new_source>, --split bench_night --recall-only
```

Keep the source if its target metrics improve **and** IDD auto_rickshaw / car mAP50-95 drop by ≤ 0.01. Judge on **clean** benchmarks (IDD test, bench_night), not on the new source's own test split.

---

## 5. Choose training settings from measurements

Settings come from measurements on this laptop (RTX 5060 8 GB, 15.4 GB RAM), never from AutoBatch, which froze this machine (decision.md D2, D7). Full reasoning and a retuning guide for bigger GPUs: **[decision.md](decision.md)**.

```powershell
$py scripts\benchmark_train.py --candidates yolo11x.pt:960:2 --workers 1   # img/s, peak VRAM, min free RAM, run time
```

| model · imgsz · batch | peak VRAM | img/s | 50 epochs | |
|---|---:|---:|---:|---|
| yolo11x · 960 · 4 | 8.88 GB | 0.47 | 245 h | ❌ exceeds VRAM, spills into RAM |
| yolo11x · 960 · 3 | 7.04 GB | 6.63 | 17.4 h | ❌ slower than batch 2 |
| **yolo11x · 960 · 2** | **4.93 GB** | **8.2** | **~14 h** | ✅ **chosen**: best accuracy that fits |
| yolo11l · 960 · 4 | 5.99 GB | 14.81 | 7.8 h | fallback if one night is a hard limit |

| workers (yolo11x · 960 · 2) | img/s | min free RAM | |
|---:|---:|---:|---|
| 0 | 7.01 | 4.28 GB | 15% slower |
| **1** | **8.17** | **2.92 GB** | ✅ **chosen** |
| 2 | 8.26 | 1.71 GB | ❌ too little RAM left on Windows |

The deliverable is a **YOLO11x** checkpoint: the same architecture as production, so swap-in is a drop-in file change.

## 6. Train

```powershell
$py scripts\preflight.py                                        # GREEN / AMBER / RED checklist, changes nothing
$py scripts\train.py --smoke                                    # 3 epochs on 30% (~25 min for yolo11x): must print SMOKE PASS
$py scripts\train.py                                            # overnight (~14-15 h max, early stopping may end it sooner)
$py scripts\train.py --resume runs\<name>\weights\last.pt       # after a watchdog stop, crash, reboot, or to continue next night
```

**Before starting:**
- Plug in, keep sleep on AC set to Never (preflight checks both), and put the laptop on a hard surface.
- Close Teams, browsers, download managers and local database servers. Free RAM is the tight resource, not VRAM.
- Recommended once: NVIDIA App → Graphics → Global settings → **CUDA - Sysmem Fallback Policy → Prefer No Sysmem Fallback**.
- Run only this one GPU job. No evaluation, games or video while training.

**While it runs**, the log prints one line per epoch, for example:
`resources epoch 3/50: 17.6 min (train+val), 8.0 img/s, VRAM peak 5.5 GB, RAM free 2.3 GB (min seen 2.2), GPU 72 C | ETA if no early stop: 13.8 h`
Full detail every 100 steps is in `runs/<name>/resources.csv`.

**Safety:**
- **VRAM cap (80%):** an oversized setting fails with an out-of-memory error instead of freezing Windows.
- **Watchdogs:** they stop training cleanly (exit code 3, message `WATCHDOG STOP`) if free RAM stays below 1.5 GB, or if steps suddenly become 4× slower (memory spilling).
- **Nothing is lost:** resume from the printed `last.pt`.

### Checkpoints
| file (`runs/<name>/weights/`) | when |
|---|---|
| `last.pt` | every epoch; `--resume` continues from it (optimizer and LR schedule included) |
| `best.pt` | overwritten whenever **val mAP50-95** improves (Ultralytics 8.4 fitness) |
| `epoch10.pt`, `epoch20.pt`, … | snapshots (`save_period: 10`) |
| `weights/<name>_best.pt` | copy of `best.pt` + `<name>_best.json` model card; the deliverable |

### Loss (YOLO11 defaults, correct for this task)
| term | what it optimises | gain |
|---|---|---:|
| box, **CIoU loss** | overlap, centre distance, aspect ratio | 7.5 |
| cls, **BCE with logits** | per-class confidence | 0.5 |
| **DFL**, Distribution Focal Loss | precise box edges | 1.5 |

Predictions are assigned by the task-aligned assigner. The gains are written out in `train.yaml`; only change them with an ablation.

### What each run records
- `results.csv` + `metrics_per_epoch.csv` (adds **F1**): train/val box/cls/DFL loss, P, R, F1, mAP50, mAP50-95, LR
- `training_summary.png`: loss curves, P/R/F1, mAP, LR, best epoch marked
- PR, F1, P and R curves; confusion matrix (raw + normalised); label distribution; batch previews
- `model_card.json`: best epoch, metrics, config, dataset reports, environment, git commit
- `logs/train_<name>_*.log`

**Reading the curves:** val loss rising while train loss falls means overfitting. `best.pt` already stops at the right epoch; the fix is more data, not more epochs.

## 7. Metrics: which to present

| metric | definition | use it for |
|---|---|---|
| **mAP50-95** | mean AP over IoU 0.50…0.95 (COCO primary) | **headline**; model selection |
| **mAP50** / **mAP75** | AP at IoU 0.50 / 0.75 | detection / strict localisation |
| **Precision** | TP / (TP + FP) | false alarms |
| **Recall** | TP / (TP + FN) | missed vehicles, i.e. missed plates |
| **F1** | harmonic mean of P and R | balanced number at a threshold |
| **mean IoU** (true positives) | overlap of matched boxes | crop quality for the plate reader |
| **Size-bucket P/R** | COCO small < 32², medium < 96², large | distant vs near vehicles |
| **Confusion matrix** | predicted vs true class | autos confused with motorcycle/car |
| **Speed** | ms per image | real-time budget |

Two views of P/R/F1:
- **Threshold-free:** at the confidence maximising mean F1. Use it for comparing models.
- **Operating point:** at `--op-conf 0.30`, the tracker's `--conf`. Use it for production behaviour.

For a report or deck: mAP50-95 and mAP50 (overall + auto_rickshaw), operating-point F1, bench_night recall (night + IR, colour vs IR), and the auto_rickshaw confusion row, each with the baseline alongside.

## 8. Evaluate

```powershell
$py scripts\evaluate.py --model weights\<name>_best.pt                                   # full test split
$py scripts\evaluate.py --model weights\<name>_best.pt --sources idd                     # Indian roads
$py scripts\evaluate.py --model weights\<name>_best.pt --sources dawn_fog dawn_rain      # real fog/rain
$py scripts\evaluate.py --model weights\<name>_best.pt --split bench_night --recall-only # real night CCTV + IR
$py scripts\evaluate.py --model weights\<name>_best.pt --split test_low_light            # synthetic, relative only
```

**Gates (defaults):**
- car / motorcycle / bus / truck mAP50-95 not worse than baseline (±0.01)
- auto_rickshaw mAP50 ≥ 0.60. IDD's test set is full of tiny, distant, occluded autos; recalibrate from the size-bucket table after the first run.

**bench_night:** recall with the right class group and with any class, split into colour vs IR frames, for the new model and the baseline. It's the only measurement on **real night CCTV the model never trained on**, so report it even when the gates pass.

## 9. Blur, night and IR: what this does and does not do

**In training:**
- Real fog/rain (DAWN)
- Synthetic low light / IR / motion + defocus blur / JPEG / low resolution (`degrade.py`) on 25% extra copies

No enhancement preprocessing at inference.

**Measured, but not trained on:** real night + IR CCTV (`bench_night`, recall-only).

**Not covered:**
- **No real night training data yet:** the only large candidate (duong v5) is corrupted by box-level augmentation. If bench_night recall is weak, real night data is the fix (future scope 1–3).
- **Plate reading** (fast-alpr's own detector + OCR).
- **Detail that isn't in the image** (heavy blur, tiny vehicles).

## 10. Swap-in

Once `evaluate.py` passes:
1. Copy `weights/<name>_best.pt` to `multi-object-tracking/yolo11x-veh5.pt`.
2. In `backend/app/routers/analytics.py`, point the `"vehicle"` model at `yolo11x-veh5.pt`.
3. In `car_tracking.py`, set `VEHICLE_CLASSES = {0: "car", 1: "motorcycle", 2: "bus", 3: "truck", 4: "auto_rickshaw"}` and add a colour for id 4 in `VEHICLE_COLORS`.

Keep `yolo11x.pt` in place for the person workers.

## 11. Future scope

Deferred for time; in priority order.

1. **Clean night CCTV data from duong-tran's project.** On its Roboflow Universe page, download a version with **no box-level augmentation** (image-level only, or none). Replace the two raw folders, re-run `inspect_source.py`, set `dedupe_augmented: false` and `enabled: true` (everything else in `sources.yaml` is already configured: class decoding, ≤ 200 frames per scene, scene-level split, car autolabel). Validate with the pilot ablation (section 4). This is the fastest route to real night training data.
2. **Own-camera test set.** Label ~150–200 frames from the deployed cameras (half day, half night incl. IR) and make them the swap-in gate.
   ```powershell
   $py scripts\extract_frames.py D:\clips --out raw/own_cameras --prelabel --every-sec 5 --max-per-video 40
   ```
   Review locally in **X-AnyLabeling** (GitHub `CVHub520/X-AnyLabeling`): relabel autos, fix and add boxes, export YOLO. 20–40 s per frame. Keep the footage local.
3. **Own-camera night training data.** Pre-label night clips with the round-1 model (`extract_frames.py` needs a small change to accept a 5-class model), audit, add as a source, and retrain on the **full mix** from round-1 weights (`--model weights\<round1>_best.pt`). Never train on new data alone.
4. **Relabel Thammasat properly** (complete motorbikes, split heavy vehicle): 444 real night + IR CCTV images, a few hours of work; it would then move from benchmark to training.
5. **More IDD** (`max_images.train` 12k–20k) when a longer run or bigger GPU is available.
6. **Plate robustness:** separate fine-tune of fast-alpr's plate detector / OCR on night and blurred crops.
7. **Deployment speed:** TensorRT FP16 export (`yolo export format=engine half=True`), re-checked with `evaluate.py`.
8. **Other datasets, after licence review:** DriveIndia/TiAND (EULA forbids vehicle identification, which conflicts with ANPR); IIIT-H Autorickshaw Detection Challenge.

## Troubleshooting

| symptom | fix |
|---|---|
| `CUDA not available` | CPU-only torch wheel; reinstall from the cu128 index (see `../requirements.txt`) |
| GPU utilisation a few %, VRAM nearly full, epoch never ends | system-RAM fallback after OOM; stop, lower `batch` (re-run `benchmark_train.py`) |
| DataLoader worker crash on Windows | `--workers 2` or `0` |
| slow epochs, GPU busy only in bursts | disk-bound data loading; `cache: disk` in `train.yaml` (~2–3 MB per image) |
| large `missing_image` / `no_label_file` in dry run | folder layout changed; check `sources.yaml` paths |
| car recall dropped vs baseline | a source wrongly marked `labelled_classes: all`; audit it with `inspect_source.py` |
| autos detected as motorcycle | check the confusion section; more auto data or larger `max_images.train` |
| `UNMAPPED` vehicle names in dry run | add to `classes.yaml` aliases or the source's `class_map` |
| val loss rises while train loss falls | overfitting; `best.pt` is still correct; add data, not epochs |
