"""
Generic appearance-embedding extractor, for the Investigate "search by
person photo" feature.

This is deliberately NOT a specialised person re-identification model --
it's a pretrained-ImageNet MobileNetV3-Large backbone with its
classification head removed, used as a general appearance-similarity
feature extractor (a common, cheap baseline before reaching for a
dedicated ReID network). That's an honest scoping choice, not a corner
cut: Track's own docstring already sets the epistemic bar this whole
subsystem holds appearance similarity to -- "evidence, not
identification" -- see Track.subject_id's docstring in
app/models/track.py. A dedicated ReID model would sharpen the ranking,
not change what a match is allowed to mean. Swap MODEL_NAME/_build() for
one later without touching any caller -- every embedding row already
records which model produced it.

Used from two places with the same weights, so the query image and every
stored track's crop are directly comparable:
  - recording_ingest_worker.py, at track-finalisation time (person tracks
    only) -- computed once per track, stored in Track.embedding.
  - person_search.py (invoked by the backend as a subprocess, since the
    backend's own .venv deliberately carries no torch/torchvision --
    same split as every other worker in this project) -- computed once
    per query image.
"""

import io

import numpy as np
import torch
import torchvision
from PIL import Image

MODEL_NAME = "mobilenet_v3_large_imagenet_avgpool_v1"
EMBEDDING_DIM = 960

_model = None
_transform = None
_device = None


def _resolve_device() -> str:
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def _to_torch_device(device: str) -> str:
    """Translate tracking_common.resolve_device()'s value into a torch one.

    That function returns YOLO's device convention -- a bare index string
    ("0", "1", ...) for CUDA -- because that is what ultralytics expects, and
    every caller here passes its result straight through. torch does not
    accept it: `backbone.to("0")` raises `Invalid device string: '0'`.

    Same convention mismatch plates.py's _resolve_onnx_providers documents,
    but with a louder failure mode: there it silently fell back to CPU, here
    it crashed the process, so every *person* ingest run died at startup with
    exit code 1 while vehicle runs (which never load this model) were fine.
    """
    # str() first: torch itself accepts a bare int index (`.to(0)`), so a
    # caller passing one is reasonable and must not crash on .startswith().
    device = str(device)
    if device in ("cpu", "mps") or device.startswith("cuda"):
        return device
    # resolve_device()'s only other contract is a CUDA device index.
    return f"cuda:{device}" if device.isdigit() else device


def load(device: str | None = None):
    """Load (once; cached in module globals) and return the embedder.
    Safe to call repeatedly -- only the first call does any work."""
    global _model, _transform, _device
    if _model is not None:
        return _model
    # `is not None`, not truthiness: device index 0 is the common CUDA case
    # and is falsy, so `if device` would silently ignore it and auto-resolve.
    _device = _to_torch_device(device) if device is not None else _resolve_device()
    weights = torchvision.models.MobileNet_V3_Large_Weights.IMAGENET1K_V2
    backbone = torchvision.models.mobilenet_v3_large(weights=weights)
    backbone.classifier = torch.nn.Identity()  # keep the pooled 960-d feature, drop the 1000-way head
    backbone.eval()
    _model = backbone.to(_device)
    _transform = weights.transforms()
    return _model


def embed_image(image: Image.Image) -> np.ndarray:
    """RGB PIL image -> L2-normalised float32 embedding, EMBEDDING_DIM long."""
    load()
    tensor = _transform(image.convert("RGB")).unsqueeze(0).to(_device)
    with torch.no_grad():
        features = _model(tensor)
    vec = features.squeeze(0).to("cpu").numpy().astype(np.float32)
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


def embed_jpeg_bytes(jpeg_bytes: bytes) -> np.ndarray:
    return embed_image(Image.open(io.BytesIO(jpeg_bytes)))
