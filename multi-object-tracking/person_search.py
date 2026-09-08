#!/usr/bin/env python3
"""
Computes one person_embedding.py embedding for a single query image and
prints it as JSON on stdout.

Invoked by the backend as a subprocess (backend/app/routers/investigate.py's
search_person endpoint) using this folder's own .venv interpreter -- the
backend's own .venv deliberately carries no torch/torchvision, same split
already used for every live/offline ANPR worker in this project.

Usage:
    python person_search.py --image /path/to/query.jpg
"""

import argparse
import base64
import json
import sys

import person_embedding


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()

    try:
        with open(args.image, "rb") as f:
            jpeg_bytes = f.read()
        vec = person_embedding.embed_jpeg_bytes(jpeg_bytes)
    except Exception as exc:  # noqa: BLE001 - report cleanly, never a bare traceback to the caller
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
        return 1

    print(json.dumps({
        "embedding": base64.b64encode(vec.tobytes()).decode("ascii"),
        "dim": int(vec.shape[0]),
        "model": person_embedding.MODEL_NAME,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
