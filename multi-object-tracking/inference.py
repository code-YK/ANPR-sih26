#!/usr/bin/env python3
"""Run YOLO11 inference with clear English display labels."""

from __future__ import annotations

import argparse
from pathlib import Path
import torch

from ultralytics import YOLO


ENGLISH_LABELS = {
    0: "normal_person",
    1: "potentially_dangerous_person",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the trained two-class YOLO11 detector."
    )
    parser.add_argument("--model", default="best.pt", help="Path to a trained .pt file.")
    parser.add_argument("--source", required=True, help="Image, video, directory, or stream source.")
    parser.add_argument("--confidence", type=float, default=0.35, help="Confidence threshold in [0, 1].")
    parser.add_argument("--project", default="runs/predict", help="Output parent directory.")
    parser.add_argument("--name", default="demo", help="Output run name.")
    parser.add_argument("--device", default=None, help="Ultralytics device value, such as cpu, 0, or 0,1.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 0.0 <= args.confidence <= 1.0:
        raise ValueError("--confidence must be between 0 and 1.")

    # Auto-select GPU if available and device is not explicitly set
    if args.device is None:
        if torch.cuda.is_available():
            args.device = "0"
            print("--- CUDA is available! Using GPU (device 0) ---")
        else:
            args.device = "cpu"
            print("--- CUDA is NOT available. Falling back to CPU ---")
    else:
        print(f"--- Using explicitly specified device: {args.device} ---")

    model_path = Path(args.model)
    if not model_path.is_file():
        raise FileNotFoundError(f"Model file not found: {model_path}")

    model = YOLO(str(model_path))
    model.model.names = ENGLISH_LABELS
    model.predict(
        source=args.source,
        conf=args.confidence,
        save=False,
        show=True,
        project=args.project,
        name=args.name,
        exist_ok=True,
        device=args.device,
    )
    print("Inference completed. Video was shown live.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
