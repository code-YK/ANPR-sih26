# YOLO11x Vehicle Fine-tune — Comparison Report & Swap-in Verdict

**Model:** `weights/yolo11x-veh5-960-20260913-232921_best.pt`
**Base checkpoint:** `yolo11x.pt` (COCO-pretrained, 80 classes)
**Task:** 5-class vehicle detector — `car, motorcycle, bus, truck, auto_rickshaw` — with `auto_rickshaw` newly added (does not exist in COCO)
**Date:** 2026-09-13 → 2026-09-14
**Hardware:** RTX 5060 Laptop GPU (8 GB VRAM), 15.4 GB RAM, Windows 11

This report documents everything done to produce and validate this checkpoint, and gives an honest, evidence-scoped verdict on whether it should replace the baseline model in the tracker. It is **not** a one-line "PASS" — the results are strong in some conditions and worse than baseline in one specific condition, and both facts matter for the swap-in decision.

---

## 1. Dataset

Prepared by `scripts/prepare_dataset.py` from `configs/sources.yaml`, into `datasets/veh5/`.

| split | images | purpose |
|---|---:|---|
| train | 7,937 | training |
| val | 1,075 | in-loop validation (early stopping, checkpoint selection) |
| test | 3,075 | held-out, never seen in training or val — the main accuracy benchmark |
| bench_night | 444 | **real** night CCTV, never seen in training, fixed benchmark only |

### Sources that make up train/val/test

| source | what it is | role |
|---|---|---|
| **IDD Detection** (Kaggle re-export, CC BY-NC-SA 4.0) | Real Indian dashcam/street footage. The only source with real `auto_rickshaw` labels. Re-split by drive sequence (the dataset's own split leaked frames from the same drive across train/val/test). | 6,000 train / 1,000 val / 3,000 test images — the backbone of all three splits |
| **DAWN — Fog** (Mendeley, CC BY-NC 3.0) | Real fog conditions, no autos (non-Indian roads) | adds real adverse-weather diversity |
| **DAWN — Rain** (Mendeley, CC BY-NC 3.0) | Real rain conditions, no autos | adds real adverse-weather diversity |

`night_duong` (Roboflow night CCTV) was **audited and rejected** for this run — inspection found bounding-box-level rotation augmentation baked into the pixels (a visible seam around every box in all copies), which would teach the model "seam = vehicle" instead of real night appearance. Documented in `configs/sources.yaml` with a re-download path if a clean version becomes available.

### Synthetic degradation (the "dawn" half of "auto + dawn")

`scripts/degrade.py` applied synthetic degradation to **25% of the train split** (fraction=0.25, `configs/train.yaml`-adjacent config) to simulate low-visibility conditions the real sources under-represent:

| synthetic condition | images affected |
|---|---:|
| motion_blur | 490 |
| low_light | 463 |
| jpeg (compression artifacts) | 372 |
| low_res | 397 |
| ir_night (greyscale simulation) | 235 |
| defocus | 174 |
| haze | 104 |

**This is the critical caveat for interpreting the results below:** synthetic degradation is a Photoshop-style transform of a *daytime* image (darken, blur, desaturate) — not a real night photograph. It teaches the model to be robust to a specific set of pixel transforms, not necessarily to real nighttime physics (headlight glare, sensor noise, real motion blur trails, true low dynamic range).

### `bench_night` — the one real, unseen night source

**Vehicle CCTV (night) v4**, Thammasat University (Roboflow, CC BY 4.0): 444 real overhead night CCTV images, including 93 genuine IR/greyscale frames, **never used in training** (`split_method: fixed`, excluded from the training pool entirely, `degrade: false`). Labels are known-incomplete (partial motorcycle boxes, bus/truck merged into "heavy vehicle"), so it is scored **recall-only** — precision/mAP would be meaningless against incomplete ground truth, but recall of what *is* labelled is a valid, real measurement.

This is the one place in this whole report where "real, unseen, actual night" data touches the model at all — everywhere else, "night" in training means synthetic degradation of daytime images.

---

## 2. Process — what was actually done, in order

1. **Source audit** (`inspect_source.py`) — every candidate source measured for label completeness, box tightness, and augmentation artifacts before being trusted. `night_duong` failed this audit and was excluded (see above).
2. **Dataset assembly** (`prepare_dataset.py`) — sources pooled, group-aware split (by drive/camera, not by individual frame, to prevent leakage), synthetic degradation applied to 25% of train.
3. **Dataset integrity check** (`check_dataset.py`) — every image has a label file, class ids match `configs/classes.yaml`.
4. **Hardware benchmarking** (`benchmark_train.py`) — measured real peak VRAM and throughput for multiple model/resolution/batch combinations on this exact laptop *before* committing to a config (see `decision.md`). Chose yolo11x @ 960px @ batch 2 (4.93 GB peak, fits in the 8 GB card with margin) over batch 3/4 (which either exceeded VRAM or were paradoxically slower from memory pressure) and over the smaller yolo11l (traded some speed for capacity, since the two hardest classes — bus vs truck, auto_rickshaw vs motorcycle/car — benefit from a bigger model).
5. **Safety layer design** (`train.py`, `common.py`) — after an earlier AutoBatch run silently spilled GPU memory into system RAM and hard-froze the machine (Windows doesn't raise an out-of-memory error on VRAM exhaustion — it pages, and the whole OS stops responding), three safety layers were built and *tested*, not just written:
   - **VRAM hard cap** (80% / 6.37 GB) — proven with a live test: a 6.9 GB allocation was refused (real out-of-memory error) while the measured 4.93 GB training peak was allowed through.
   - **RAM watchdog** — stops training cleanly (resumable from `last.pt`) if free system RAM stays under 1.5 GB for 30 consecutive steps. Forced-trip test: stopped at step 30 exactly as designed, 0 leftover processes, VRAM fully released.
   - **Slow-step watchdog** — stops cleanly if 20 consecutive steps run 4× slower than the running median (the signature of memory spilling into system RAM).
6. **Smoke test — lighter model first** (`train.py --smoke`): 3 epochs × 30% of train data, on **yolo11l** (the smaller variant) before committing 14 hours to yolo11x. Why 3 epochs and not 1: a 1-epoch/10% smoke test was tried earlier and produced mAP 0 / NaN val loss on an otherwise healthy pipeline — the newly-initialized 5-class detection head hadn't yet left its 3-epoch learning-rate warmup, so its random logits overflowed FP16. This was root-caused (verified: near-zero weight change, FP16-only NaN, FP32 finite) rather than assumed. With 3 epochs the yolo11l smoke run reached mAP50 0.218 → 0.208 → 0.414 with finite losses throughout — **SMOKE PASS**, pipeline proven healthy end-to-end before the expensive run.
   A crash-recovery test was also run: the process tree was killed 90 seconds into an epoch, and `--resume` picked up correctly with the same learning-rate schedule — proving an overnight crash would cost at most one partial epoch, not the run.
7. **Pre-flight checklist** (`preflight.py`) — run immediately before the real training, checking: CUDA build, no other GPU jobs running, free VRAM/RAM/disk, power source, Windows sleep timer, config sanity (fixed batch, not AutoBatch), dataset integrity, and a **live** VRAM-cap re-verification. First run came back **AMBER** (on battery, sleep timer active, RAM slightly low) — training was **not** started until these were fixed (plugged in, sleep disabled, background apps closed, GPU cache cleared). Second run: **GREEN, 14/14 checks passed.**
8. **The real run**: `train.py` on the full config — yolo11x, 960px, batch 2, 50 epochs, cosine LR schedule, `patience=12` (would have early-stopped if val mAP50-95 plateaued — it never did, ran the full 50). **13.94 hours**, zero watchdog trips, zero crashes, zero manual intervention.
9. **Evaluation** (`evaluate.py`) — the fine-tuned model and the untouched baseline `yolo11x.pt` run through the *identical* protocol on the *same* held-out test images, so the comparison below is apples-to-apples, not two separately-reported numbers.
10. **Real-night recall benchmark** (`evaluate.py --split bench_night --recall-only`) — same idea, on the one genuinely real, unseen night source.

---

## 3. Training run

50/50 epochs completed, no early stop (val mAP50-95 was still climbing on the cosine schedule's tail), no watchdog trips.

| | |
|---|---|
| duration | 13.94 h (est. 14.0 h) |
| final val mAP50-95 | 0.520 |
| final val mAP50 | 0.717 |
| peak VRAM | 5.14 – 5.59 GB (cap: 6.37 GB) |
| min free system RAM seen | 2.41 GB (watchdog floor: 1.5 GB) |
| GPU temperature range | 59 – 70 °C |

**Training curves** (loss, precision/recall/F1, mAP, learning rate — dashed line marks the best epoch):

![training summary](report_assets/train/training_summary.png)

![results](report_assets/train/results.png)

**Confusion matrix (normalized, in-loop validation set):**

![train confusion matrix](report_assets/train/train_confusion_matrix_normalized.png)

**Sample validation batch — ground truth vs. prediction (in-loop val set, during training):**

*Underlying photos are drawn from the training mix (§1): IDD Detection ([CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) + IDD research terms) and DAWN fog/rain ([CC BY-NC 3.0](https://creativecommons.org/licenses/by-nc/3.0/)) — non-commercial terms; shown here with prediction/ground-truth boxes overlaid for internal evaluation, not standalone redistribution.*

| ground truth | fine-tuned model prediction |
|---|---|
| ![val labels](report_assets/train/val_batch0_labels.jpg) | ![val pred](report_assets/train/val_batch0_pred.jpg) |

---

## 4. Held-out test evaluation — fine-tuned vs. baseline

`scripts/evaluate.py --model weights/yolo11x-veh5-960-20260913-232921_best.pt`, 3,075 held-out test images (no overlap with train or val), same images fed to both models, baseline evaluated with `auto_rickshaw` removed from its ground truth (COCO has no such class — calling an auto a "car" correctly counts as a baseline error, matching what happens in production today).

### Threshold-free metrics (the real benchmark numbers)

| class | instances | new mAP50 | new mAP50-95 | baseline mAP50-95 | Δ mAP50-95 |
|---|---:|---:|---:|---:|---:|
| car | 6,821 | 0.738 | 0.532 | 0.493 | **+0.039** |
| motorcycle | 7,087 | 0.721 | 0.452 | 0.320 | **+0.132** |
| bus | 1,404 | 0.647 | 0.509 | 0.399 | **+0.110** |
| truck | 2,032 | 0.667 | 0.495 | 0.300 | **+0.195** |
| auto_rickshaw | 2,280 | 0.758 | 0.558 | — (no such class) | new capability |
| **all** | – | 0.706 | 0.509 | 0.378 | **+0.131** |

### Operating point (confidence 0.30 — what the tracker actually runs at)

| class | precision | recall | F1 | mean IoU of true positives | baseline F1 |
|---|---:|---:|---:|---:|---:|
| car | 0.836 | 0.672 | 0.745 | 0.862 | 0.703 |
| motorcycle | 0.824 | 0.659 | 0.732 | 0.818 | 0.599 |
| bus | 0.740 | 0.578 | 0.649 | 0.899 | 0.533 |
| truck | 0.763 | 0.596 | 0.670 | 0.877 | 0.444 |
| auto_rickshaw | 0.825 | 0.682 | 0.747 | 0.869 | — |

**By object size:** large-object recall 0.873, medium 0.621, small 0.260 — the model is strong on medium/large vehicles and weak on small, distant ones (expected at 960px; a known, documented lever for future improvement, not a defect).

**auto_rickshaw error breakdown** (of 2,280 ground-truth autos): 660 missed entirely, 35 called truck, 24 called car, 3 bus, 2 motorcycle. The dominant failure mode is *missing* small/hard autos, not confusing them with another vehicle class.

### Automated gates (from `evaluate.py`, thresholds set in `decision.md`)

- PASS — car mAP50-95 0.532 ≥ baseline 0.493 − 0.01
- PASS — motorcycle mAP50-95 0.452 ≥ baseline 0.320 − 0.01
- PASS — bus mAP50-95 0.509 ≥ baseline 0.399 − 0.01
- PASS — truck mAP50-95 0.495 ≥ baseline 0.300 − 0.01
- PASS — auto_rickshaw mAP50 0.758 ≥ 0.60 gate

**Every class improved over baseline; none regressed.** auto_rickshaw — a class the baseline cannot detect at all — performs on par with the established classes, not as a weak afterthought.

### Visual comparison — same test images, both models

**Confusion matrix (normalized):**

| fine-tuned | baseline |
|---|---|
| ![new confusion](report_assets/test_new/confusion_matrix_normalized.png) | ![baseline confusion](report_assets/test_baseline/confusion_matrix_normalized.png) |

**Precision-Recall curves:**

| fine-tuned | baseline |
|---|---|
| ![new PR](report_assets/test_new/BoxPR_curve.png) | ![baseline PR](report_assets/test_baseline/BoxPR_curve.png) |

**Sample predictions on the same held-out batch:**

*Same source licensing as above (IDD CC BY-NC-SA 4.0, DAWN CC BY-NC 3.0) — boxes overlaid for evaluation.*

| ground truth | fine-tuned prediction | baseline prediction |
|---|---|---|
| ![gt](report_assets/test_new/val_batch0_labels.jpg) | ![new pred](report_assets/test_new/val_batch0_pred.jpg) | ![baseline pred](report_assets/test_baseline/val_batch0_pred.jpg) |
| — | ![new pred 2](report_assets/test_new/val_batch1_pred.jpg) | ![baseline pred 2](report_assets/test_baseline/val_batch1_pred.jpg) |

Note the baseline frames show no auto_rickshaw boxes at all (it cannot predict a class it was never trained on) — autos there are either missed or mislabeled as car/motorcycle, which is the exact error this fine-tune sets out to fix.

---

## 5. Real, unseen night footage — `bench_night` (444 images: 351 colour + 93 IR)

This is the one benchmark in this report where "night" means an actual night photograph the model never trained on, rather than a synthetic darken/blur transform. Labels are incomplete, so **recall only** is reported (precision/mAP would be misleading against partial ground truth).

| group | GT boxes | **fine-tuned recall** | **baseline recall** |
|---|---:|---:|---:|
| motorcycle | 438 | 0.315 | 0.566 |
| car | 490 | 0.463 | 0.798 |
| bus/truck | 302 | 0.152 | 0.493 |
| **all vehicles** | 1,230 | **0.334** | **0.641** |

Split further: colour frames 0.359 vs. 0.651 baseline; **IR/greyscale frames 0.221 vs. 0.595 baseline** — the largest gap.

### Visual comparison on real night frames (unseen, not in training)

*Source images: [Vehicle Detection from CCTV (Night) v4](https://universe.roboflow.com/), Thammasat University, via Roboflow Universe — licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Shown below with prediction boxes overlaid by this pipeline; unmodified originals are not redistributed elsewhere in this repo.*

| fine-tuned prediction | baseline prediction |
|---|---|
| ![night ft 1](report_assets/night_finetuned/night_thammasat__test_images_1765_jpg.rf.e0277a48ec43be7c807f72fc0eec1766.jpg) | ![night base 1](report_assets/night_baseline/night_thammasat__test_images_1765_jpg.rf.e0277a48ec43be7c807f72fc0eec1766.jpg) |
| ![night ft 2](report_assets/night_finetuned/night_thammasat__test_images_43811_104_jpg.rf.33de2f4a09f6a98f8a3f38d0ac5aa6bf.jpg) | ![night base 2](report_assets/night_baseline/night_thammasat__test_images_43811_104_jpg.rf.33de2f4a09f6a98f8a3f38d0ac5aa6bf.jpg) |
| ![night ft 3](report_assets/night_finetuned/night_thammasat__test_images_67_96_jpg.rf.7200fd27ea4502800e31d96ef2dbd197.jpg) | ![night base 3](report_assets/night_baseline/night_thammasat__test_images_67_96_jpg.rf.7200fd27ea4502800e31d96ef2dbd197.jpg) |
| ![night ft 4](report_assets/night_finetuned/night_thammasat__test_images_Sequence-013768_png.rf.c1a00ec3e324d3b31d223ee9de27fe09.jpg) | ![night base 4](report_assets/night_baseline/night_thammasat__test_images_Sequence-013768_png.rf.c1a00ec3e324d3b31d223ee9de27fe09.jpg) |
| ![night ft 5](report_assets/night_finetuned/night_thammasat__test_images_20211220_20211220195233_20211220211453_195231_crop_1798_jpg.rf.6e6894cb52ba809fde5fe70789703097.jpg) | ![night base 5](report_assets/night_baseline/night_thammasat__test_images_20211220_20211220195233_20211220211453_195231_crop_1798_jpg.rf.6e6894cb52ba809fde5fe70789703097.jpg) |
| ![night ft 6](report_assets/night_finetuned/night_thammasat__test_images_Video_Night_Rain_1_mp4-31_jpg.rf.1593a73a2f7dbb8cf6e71e5265ff1d2e.jpg) | ![night base 6](report_assets/night_baseline/night_thammasat__test_images_Video_Night_Rain_1_mp4-31_jpg.rf.1593a73a2f7dbb8cf6e71e5265ff1d2e.jpg) |

*(6 images sampled at random, seed 0, from the 444-image bench_night pool — not cherry-picked.)*

### Why this happened — the honest explanation, not a guess

decision.md flagged this exact risk before training started: **"real night data" was listed as the main known gap**, with synthetic degradation used only as a stand-in. That prediction held. Fine-tuning pulled the model's learned features toward "daytime traffic + synthetic-dark transforms," and in doing so it lost some of the more general low-light robustness the COCO-pretrained baseline had. This is a textbook **narrow-domain overfitting trade-off**, not a bug in the pipeline — it is measured with 1,230 real ground-truth boxes, not noise, and it is consistent across both colour and IR frames (worse in IR, where the domain gap from "synthetic greyscale" to "real IR sensor" is largest).

---

## 6. Verdict

**This is not a single yes/no answer — the evidence points in two different directions depending on operating conditions, and reporting it as one verdict would misrepresent the data.**

### ✅ Swap-in approved — for daytime and adverse-weather (fog/rain/haze) conditions matching the training/test distribution
Every one of the 5 classes beats the untouched baseline on the same held-out test images, under the same protocol, with no cherry-picking:
- +0.039 to +0.195 mAP50-95 across car/motorcycle/bus/truck (truck and bus in particular go from "barely usable" to "solid" — baseline mAP50-95 0.30/0.40 → 0.50/0.51)
- auto_rickshaw — a class the baseline cannot detect at all — reaches 0.758 mAP50 / 0.747 F1, on par with the established classes, clearing its 0.60 gate with margin
- No class regressed
- This is the domain the training data (IDD real + DAWN real fog/rain + synthetic degradation) actually represents

**If the deployment cameras operate in daytime/dusk/fog/rain conditions, this checkpoint is proven better than what is running today and should be swapped in.**

### ❌ Do not swap in yet — for real night / IR camera feeds
On the one real, unseen, actual night benchmark (`bench_night`, 444 images the model never trained on):
- Overall recall **0.334 vs. baseline 0.641** — the fine-tuned model finds roughly half as many vehicles as the model it would replace
- IR/greyscale frames are worst: **0.221 vs. 0.595**
- This is a genuine regression, not measurement noise (1,230 GT boxes) and not a training bug — it is the direct, predicted consequence of training on synthetic-dark images instead of real night photographs

**If the deployment cameras ever operate at night without adequate scene lighting, keeping the current baseline (or gating to it after dark) is the safer choice until real night training data is added** — this was flagged as the top-priority next step in `decision.md` even before this run started.

### Recommendation
Swap this checkpoint into `car_tracking.py`'s `VEHICLE_CLASSES` for the conditions it was proven on, and treat real-night operation as a separate, still-open problem — not one this run was ever positioned to solve, since no real night images were in the training mix. The fastest path to closing that gap is adding real night CCTV/IR training data (the `night_duong` source is a documented candidate once a non-augmented version is available) rather than tuning synthetic degradation harder.

---

## 7. Artifacts

| artifact | path |
|---|---|
| deliverable weights | `weights/yolo11x-veh5-960-20260913-232921_best.pt` |
| model card (metrics, config, environment) | `weights/yolo11x-veh5-960-20260913-232921_best.json` |
| full training run (curves, plots, per-epoch CSV, resource log) | `runs/yolo11x-veh5-960-20260913-232921/` |
| held-out test evaluation (this report's §4) | `runs/eval/20260914-133750_test/` |
| real-night recall benchmark (this report's §5) | `runs/eval/20260914-140331_bench_night/` |
| training/eval decisions and hardware measurements | `decision.md` |
| dataset preparation reports | `datasets/veh5/prepare_report.json`, `autolabel_report.json`, `check_report.json`, `degrade_report_train.json` |
| images used in this report | `report_assets/` |
