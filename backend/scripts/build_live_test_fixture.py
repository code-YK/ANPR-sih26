#!/usr/bin/env python3
"""
Builds the Section 5 live-test fixture: three (plus one decoy) looping
video clips, each a real onboarding-survey still panned/zoomed exactly like
make_test_fixture.py does for Investigate -- but with a caller-controlled
plate composited onto the real, detector-located plate position first.

Why compositing, not a synthetic scene: plate OCR in this codebase only
ever runs on a crop of a YOLO-tracked *vehicle* box (see
multi-object-tracking/plates.py's PlateReader.read_vehicles and
observation_worker.py's call into it) -- a drawn shape is not a vehicle to
a real-appearance-trained detector, so the plate must live inside genuinely
YOLO-detectable vehicle imagery. Reusing a real survey still (already an
accepted, gitignored, local-only asset -- same one make_test_fixture.py
already uses successfully) keeps the vehicle real; only the plate text
becomes ours.

The four stills below were empirically checked against
detect_plate_bbox.py (this session, 2026-08-31) -- they are the ones,
out of all 27 in backend/survey/, where fast-alpr's own detector actually
finds a plate at all. Most survey stills have none detectable (too far,
too angled, too low-res), so this list is deliberately not "pick any
still" like make_test_fixture.py's generic pick_still() -- it is the
verified subset this fixture depends on.

Usage:
    ../.venv/bin/python scripts/build_live_test_fixture.py \\
        --plate GJ01TT9911 --decoy-plate GJ05ZZ4321
"""

import argparse
import json
import os
import re
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from make_test_fixture import build_pan_clip  # noqa: E402

_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_SURVEY_DIR = os.path.join(_REPO_ROOT, "backend", "survey")
_MOT_DIR = os.path.join(_REPO_ROOT, "multi-object-tracking")
_MOT_PYTHON = os.path.join(_MOT_DIR, ".venv", "bin", "python")
_OUT_DIR = os.path.join(_REPO_ROOT, "fixtures", "live-test")

# Duplicated from multi-object-tracking/plates.py's INDIAN_PLATE_RE
# (single-line constant, not worth a cross-venv import of fast_alpr/torch
# just for a regex): must be kept identical to that one, since a plate
# that fails it there will never reach `confirmed()` no matter how well
# OCR reads it.
INDIAN_PLATE_RE = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{4}$")

# still -> which of the three "same plate, three cameras" role it plays,
# or "decoy" for the off-watchlist negative control.
#
# Empirically checked against detect_plate_bbox.py (2026-08-31): of all 27
# stills in backend/survey/, only cam21/cam10/cam12/cam14 yield any plate
# detection at all -- most are too far/angled/low-res. cam14's vehicle box
# never clears PlateReader's own 285px pre-gate (its plate was already the
# smallest of the four, 44px vs 83-95px for the other three, so its
# vehicle is correspondingly more distant) even given 25s of zoom-in, so
# it never gets read regardless of what plate is composited onto it --
# confirmed by running observation_worker.py against it directly. The
# decoy camera reuses cam21.jpg (the most reliable of the three, 0.74
# detection confidence) with a different plate text instead: a different
# camera_id/database row is what the negative-control test actually needs,
# not different background imagery.
_CANDIDATES = [
    {"still": "cam21.jpg", "role": "a"},
    {"still": "cam10.jpg", "role": "b"},
    {"still": "cam12.jpg", "role": "c"},
    {"still": "cam21.jpg", "role": "decoy"},
]

# Real Indian plates are roughly 500mm x 120mm -- ~4.17:1. Rendering at a
# fixed ratio (rather than whatever aspect the detector's axis-aligned box
# happens to report) keeps the composited patch looking like a plate
# instead of a stretched or squashed one.
_PLATE_ASPECT = 500 / 120
# The detected real plate's box is often narrower than plates.py's own
# ">=110px reads reliably" guidance once cropped again downstream by the
# vehicle tracker and possibly resized for inference -- scaling the
# rendered patch up from the detected box (still centred on the same
# point, so it stays plausibly on the vehicle) buys legibility margin we
# would not have if we only matched the real plate's native size exactly.
_PATCH_SCALE = 1.6
_MIN_PATCH_WIDTH_PX = 130


def validate_plate(plate: str) -> str:
    plate = plate.strip().upper()
    if not INDIAN_PLATE_RE.match(plate):
        raise ValueError(
            f"{plate!r} does not match the Indian plate format "
            f"{INDIAN_PLATE_RE.pattern!r} (2 letters, 1-2 digits, 0-3 letters, "
            "4 digits) -- it would never reach PlateVote.confirmed() no matter "
            "how well OCR reads it. Example valid plate: GJ01TT9911"
        )
    return plate


def detect_bbox(image_path: str) -> dict:
    out_path = image_path + ".bbox.json"
    subprocess.run(
        [_MOT_PYTHON, os.path.join(_MOT_DIR, "detect_plate_bbox.py"), "--image", image_path, "--out", out_path],
        check=True, cwd=_MOT_DIR,
    )
    with open(out_path) as f:
        result = json.load(f)
    os.remove(out_path)
    return result


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                      "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        if os.path.exists(candidate):
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default(size=size)


def render_plate_patch(text: str, width: int) -> Image.Image:
    height = round(width / _PLATE_ASPECT)
    patch = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(patch)
    border = max(2, width // 60)
    draw.rectangle([0, 0, width - 1, height - 1], outline="black", width=border)

    font_size = round(height * 0.62)
    font = _load_font(font_size)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((width - text_w) / 2 - bbox[0], (height - text_h) / 2 - bbox[1]), text, fill="black", font=font)
    return patch


def composite_plate(still_path: str, bbox: list[int], text: str, out_path: str) -> None:
    still = Image.open(still_path).convert("RGB")
    x1, y1, x2, y2 = bbox
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    detected_width = max(1, x2 - x1)

    patch_width = max(_MIN_PATCH_WIDTH_PX, round(detected_width * _PATCH_SCALE))
    patch = render_plate_patch(text, patch_width)
    patch_height = patch.height

    paste_x = round(cx - patch_width / 2)
    paste_y = round(cy - patch_height / 2)
    still.paste(patch, (paste_x, paste_y))
    still.save(out_path, quality=95)


def build_camera(candidate: dict, plate: str, out_dir: str) -> dict:
    still_path = os.path.join(_SURVEY_DIR, candidate["still"])
    if not os.path.exists(still_path):
        raise FileNotFoundError(
            f"{still_path} not found -- this fixture depends on the specific "
            "empirically-verified stills listed in _CANDIDATES, not just any "
            "backend/survey/*.jpg"
        )

    print(f"[{candidate['role']}] locating real plate in {candidate['still']}...")
    detection = detect_bbox(still_path)
    if not detection.get("detected"):
        raise RuntimeError(
            f"{candidate['still']} no longer yields a plate detection -- this "
            "candidate list was verified empirically and this still was one of "
            "the working ones; something upstream (model version, image) changed."
        )
    print(f"[{candidate['role']}] real plate at {detection['bbox']} "
          f"(detection_confidence={detection['detection_confidence']:.2f}); "
          f"compositing {plate!r}")

    composited_path = os.path.join(out_dir, f"{candidate['role']}_composited.jpg")
    composite_plate(still_path, detection["bbox"], plate, composited_path)

    clip_path = os.path.join(out_dir, f"{candidate['role']}_clip.mp4")
    build_pan_clip(composited_path, clip_path)
    print(f"[{candidate['role']}] clip: {clip_path}")

    return {"role": candidate["role"], "still": candidate["still"], "plate": plate, "clip_path": clip_path}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plate", required=True, help="Plate shared by cameras a/b/c (the watchlist match)")
    parser.add_argument("--decoy-plate", default="GJ05ZZ4321", help="Off-watchlist plate for the negative-control camera")
    parser.add_argument("--out-dir", default=_OUT_DIR)
    args = parser.parse_args()

    try:
        plate = validate_plate(args.plate)
        decoy_plate = validate_plate(args.decoy_plate)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if plate == decoy_plate:
        print("error: --plate and --decoy-plate must differ", file=sys.stderr)
        return 1

    os.makedirs(args.out_dir, exist_ok=True)
    manifest = []
    for candidate in _CANDIDATES:
        camera_plate = decoy_plate if candidate["role"] == "decoy" else plate
        manifest.append(build_camera(candidate, camera_plate, args.out_dir))

    manifest_path = os.path.join(args.out_dir, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump({"plate": plate, "decoy_plate": decoy_plate, "cameras": manifest}, f, indent=2)
    print(f"\nWrote {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
