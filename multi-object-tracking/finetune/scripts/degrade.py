"""
Synthetic night / IR / blur / low-quality copies for robustness
===============================================================
Adds degraded copies of a fraction of the TRAIN images (boxes unchanged: every
operation is photometric, nothing moves). The model learns to detect through
the degradation, so inference needs no enhancement pre-processing.

What it can and cannot do (be honest with yourself when reading metrics):
  * It makes the detector tolerant of low light, IR-greyscale, motion/defocus
    blur, heavy JPEG and low resolution.
  * It does not recreate real night artefacts exactly (headlight glare, IR
    bloom on reflective surfaces, rolling-shutter smear). Real night frames
    from your own cameras beat any amount of synthetic data.
  * It cannot recover information that is not in the pixels.

Modes
    python scripts/degrade.py                      # train: +30% degraded copies
    python scripts/degrade.py --eval-sets          # test_low_light, test_motion_blur, ... for evaluate.py

Re-running replaces previous degraded files, so it is idempotent.
"""

import argparse
import shutil
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

import common as C
from check_dataset import run_checks


# --------------------------------------------------------------------------
# Degradations: uint8 BGR in, uint8 BGR out, same size
# --------------------------------------------------------------------------

def _f(img):
    return img.astype(np.float32) / 255.0


def _u8(f):
    return np.clip(f * 255.0 + 0.5, 0, 255).astype(np.uint8)


def _sensor_noise(f, rng, lo, hi):
    """Signal-dependent noise: dark sensors are noisy in proportion to sqrt(signal)."""
    sigma = rng.uniform(lo, hi)
    return f + rng.standard_normal(f.shape, dtype=np.float32) * sigma * np.sqrt(np.clip(f, 0, 1) + 0.02)


def low_light(img, rng):
    f = _f(img)
    bloom = cv2.GaussianBlur(np.clip(f - 0.8, 0, None) * 5.0, (0, 0), rng.uniform(6, 16))  # lamps/headlights
    dark = np.power(f, rng.uniform(1.8, 3.0)) * rng.uniform(0.35, 0.7)
    if rng.random() < 0.6:  # sodium street light: warm
        tint = np.array([rng.uniform(0.7, 0.9), rng.uniform(0.9, 1.0), rng.uniform(1.0, 1.15)], np.float32)
    else:                   # LED / moonlight: cool
        tint = np.array([rng.uniform(1.0, 1.12), 1.0, rng.uniform(0.85, 1.0)], np.float32)
    return _u8(_sensor_noise(dark * tint + bloom * rng.uniform(0.3, 0.8), rng, 0.02, 0.06))


def ir_night(img, rng):
    g = _f(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    g = np.power(g, rng.uniform(0.7, 1.3)) * rng.uniform(0.5, 0.85) + rng.uniform(0.05, 0.2)  # washed-out IR
    g = cv2.GaussianBlur(g, (0, 0), rng.uniform(0.5, 1.2))
    return cv2.cvtColor(_u8(_sensor_noise(g, rng, 0.02, 0.05)), cv2.COLOR_GRAY2BGR)


def motion_blur(img, rng):
    k = int(rng.integers(7, 24)) | 1
    kernel = np.zeros((k, k), np.float32)
    kernel[k // 2, :] = 1.0
    rot = cv2.getRotationMatrix2D(((k - 1) / 2, (k - 1) / 2), float(rng.uniform(0, 180)), 1.0)
    kernel = cv2.warpAffine(kernel, rot, (k, k))
    return cv2.filter2D(img, -1, kernel / max(kernel.sum(), 1e-6))


def defocus(img, rng):
    return cv2.GaussianBlur(img, (0, 0), rng.uniform(1.5, 3.5))


def low_res(img, rng):
    h, w = img.shape[:2]
    s = rng.uniform(0.25, 0.5)
    small = cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


def jpeg(img, rng):
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, int(rng.integers(8, 31))])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR) if ok else img


def haze(img, rng):
    t, airlight = rng.uniform(0.45, 0.75), rng.uniform(0.7, 0.9)
    return _u8(_f(img) * t + airlight * (1 - t))


OPS = {"low_light": low_light, "ir_night": ir_night, "motion_blur": motion_blur, "defocus": defocus,
       "low_res": low_res, "jpeg": jpeg, "haze": haze}
# Night dominates because that is where CCTV detection actually fails.
TRAIN_WEIGHTS = {"low_light": 0.30, "ir_night": 0.15, "motion_blur": 0.20, "defocus": 0.10,
                 "low_res": 0.10, "jpeg": 0.10, "haze": 0.05}
SECOND_OPS = ["jpeg", "low_res", "motion_blur"]  # things that stack on top in real footage


def parse_args():
    parser = argparse.ArgumentParser(description="Create synthetic degraded copies")
    parser.add_argument("--dataset", default="datasets/veh5")
    parser.add_argument("--split", default="train")
    parser.add_argument("--fraction", type=float, default=0.25,
                        help="Fraction of degradable originals to copy (train mode)")
    parser.add_argument("--second-op-prob", type=float, default=0.4)
    parser.add_argument("--eval-sets", action="store_true",
                        help="Instead: build <eval-source>_<condition> splits for evaluate.py")
    parser.add_argument("--eval-source", default="test")
    parser.add_argument("--conditions", nargs="+", default=["low_light", "ir_night", "motion_blur", "low_res"],
                        choices=list(OPS))
    parser.add_argument("--seed", type=int, default=0)
    return parser.parse_args()


def copy_label(ds, src_split, src_stem, dst_split, dst_stem):
    src = ds / "labels" / src_split / (src_stem + ".txt")
    dst = ds / "labels" / dst_split / (dst_stem + ".txt")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.exists():
        shutil.copyfile(src, dst)
    else:
        dst.write_text("", encoding="utf-8")


def main():
    args = parse_args()
    ds = C.resolve(args.dataset)
    rng = np.random.default_rng(args.seed)
    logger, log_path, _ = C.setup_logging("degrade")
    counts = Counter()

    if not args.eval_sets:
        img_dir = ds / "images" / args.split
        for sub in ("images", "labels"):
            for path in (ds / sub / args.split).glob(f"*{C.DEGRADED_TAG}*"):
                path.unlink()
        # Sources marked `degrade: false` (real night footage) are never darkened again.
        no_degrade = {Path(r["image"]).name for r in C.read_manifest(ds) if r.get("degrade", "1") == "0"}
        originals = [p for p in C.list_images(img_dir) if C.DEGRADED_TAG not in p.stem and p.name not in no_degrade]
        if not originals:
            raise SystemExit(f"no degradable images in {img_dir}")
        if no_degrade:
            logger.info("skipping %d images from sources with degrade: false", len(no_degrade))
        picks = rng.choice(len(originals), size=int(len(originals) * args.fraction), replace=False)
        names, probs = list(TRAIN_WEIGHTS), np.array(list(TRAIN_WEIGHTS.values()))
        logger.info("degrading %d of %d %s images", len(picks), len(originals), args.split)

        for n, i in enumerate(sorted(picks), 1):
            src = originals[i]
            img = cv2.imread(str(src))
            if img is None:
                logger.warning("unreadable image skipped: %s", src)
                continue
            ops = [str(rng.choice(names, p=probs / probs.sum()))]
            if rng.random() < args.second_op_prob:
                ops.append(str(rng.choice([o for o in SECOND_OPS if o != ops[0]])))
            for op in ops:
                img = OPS[op](img, rng)
                counts[op] += 1
            stem = f"{src.stem}{C.DEGRADED_TAG}{'+'.join(ops)}"
            cv2.imwrite(str(img_dir / f"{stem}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
            copy_label(ds, args.split, src.stem, args.split, stem)
            if n % 1000 == 0:
                logger.info("  %d / %d", n, len(picks))
    else:
        originals = [p for p in C.list_images(ds / "images" / args.eval_source) if C.DEGRADED_TAG not in p.stem]
        if not originals:
            raise SystemExit(f"no images in split '{args.eval_source}'")
        for cond in args.conditions:
            split = f"{args.eval_source}_{cond}"
            for sub in ("images", "labels"):
                if (ds / sub / split).exists():
                    shutil.rmtree(ds / sub / split)
            (ds / "images" / split).mkdir(parents=True)
            for src in originals:
                img = cv2.imread(str(src))
                if img is None:
                    continue
                cv2.imwrite(str(ds / "images" / split / f"{src.stem}.jpg"), OPS[cond](img, rng),
                            [cv2.IMWRITE_JPEG_QUALITY, 95])
                copy_label(ds, args.eval_source, src.stem, split, src.stem)
                counts[cond] += 1
            logger.info("built split %s (%d images) -> evaluate with --split %s", split, len(originals), split)

    logger.info("operations applied: %s", dict(counts))
    C.save_json(ds / f"degrade_report_{'eval' if args.eval_sets else args.split}.json",
                {"log": str(log_path), "args": vars(args), "ops": dict(counts)})
    run_checks(ds, logger)


if __name__ == "__main__":
    main()
