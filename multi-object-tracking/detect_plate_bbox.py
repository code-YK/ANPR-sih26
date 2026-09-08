#!/usr/bin/env python3
"""
Standalone plate-bbox locator for backend/scripts/build_live_test_fixture.py
(the live-test fixture builder, Section 5 live-test Phase 1).

The fixture needs to paste a synthetic, caller-controlled plate onto a real
onboarding-survey still at exactly the location a real plate would be, so
YOLO still sees a genuine vehicle (see plates.py's docstring on why a drawn
shape is not a vehicle to a real-appearance-trained detector) while the OCR
that later reads it sees our chosen text. This script finds that location
by running the exact same detector plates.py uses at runtime, rather than
guessing coordinates by hand.

Deliberately calls `PlateReader.alpr.predict()` directly instead of
`PlateReader.read_crop()`: read_crop() reports width only (enough for its
own vote-gating), not the bounding box this fixture-builder needs. This
duplicates a small amount of read_crop()'s "pick the best detection" logic
-- ranked by detection confidence here, not OCR confidence, since only the
box location matters, not what text (if any) the real plate actually reads.

Must run under multi-object-tracking's own .venv (torch/onnxruntime/
fast_alpr live there, not in the backend's light venv):
    .venv/bin/python detect_plate_bbox.py --image <path> --out <json path>
"""

import argparse
import json
import sys

import cv2

from plates import PlateReader
from tracking_common import resolve_device


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--device", default=None, help="Override auto-resolved device")
    args = parser.parse_args()

    image = cv2.imread(args.image)
    if image is None:
        print(f"could not read {args.image}", file=sys.stderr)
        return 1

    device = resolve_device(args.device)
    # min_plate_width/min_conf are read_crop()'s own gates -- irrelevant
    # here since we call predict() directly and want the raw detection
    # regardless of how legible the real plate's text turns out to be.
    reader = PlateReader(device=device, min_plate_width=0, min_conf=0.0)
    results = reader.alpr.predict(image)

    best = None
    for r in results:
        if r.detection is None:
            continue
        if best is None or r.detection.confidence > best.detection.confidence:
            best = r

    if best is None:
        with open(args.out, "w") as f:
            json.dump({"detected": False}, f)
        print("no plate detected in image")
        return 0

    box = best.detection.bounding_box
    raw_text = best.ocr.text if best.ocr else None
    with open(args.out, "w") as f:
        json.dump(
            {
                "detected": True,
                "bbox": [box.x1, box.y1, box.x2, box.y2],
                "detection_confidence": best.detection.confidence,
                "raw_text": raw_text,
            },
            f,
        )
    print(f"plate bbox {[box.x1, box.y1, box.x2, box.y2]} "
          f"detection_confidence={best.detection.confidence:.2f} raw_text={raw_text!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
