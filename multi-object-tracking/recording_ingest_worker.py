"""
Offline recording ingest worker (Investigate, Phase 1: vehicle/plate)
======================================================================
Reads one already-normalised (constant-frame-rate) local video file,
tracks vehicles or people through it, and reports finalised tracks back to
the backend in small chunks -- never one giant terminal payload (a 10-minute
file can produce tens of thousands of box samples; POSTing that as one
document would block the backend's single-process event loop for seconds
while pydantic constructs it).

Deliberately does NOT use `tracking_common.FrameReader` or
`camera_feeds.LiveFrameReader`. Ultralytics' own `model.track(source=path,
stream=True)` already handles local-file decoding (including `vid_stride`
via `cap.grab()`, cheaper than decode-then-discard) and yields one already-
tracked `Results` per frame in order -- there is nothing left for a custom
reader to do here, and it sidesteps two latent bugs in `FrameReader`
(no try/except around the decode thread, and "break on first read failure")
that would otherwise need fixing for this to be reliable on real CCTV
exports with occasional bad frames.

Stride and tracker-buffer correctness
--------------------------------------
TRACKTRACK hard-gates association on IoU AFTER the appearance term
(`cost[~supported] = 1.0` for iou<0.10, in `track_tracker.py`), so a strided
run's larger inter-frame displacement can make fast-moving objects
unmatchable regardless of ReID -- this is why Investigate defaults to
stride 1 (see docs/investigate-testing.md). Independently, `track_buffer`
is counted in TRACKER UPDATES, not source frames or seconds (no fps scaling
exists in the tracker despite its own docstring claiming otherwise), so the
tuned "90" only means the intended ~3 seconds at the ~30fps footage it was
measured on. This worker derives the actual buffer from the source video's
real fps and stride: `track_buffer = round(3.0 * fps / stride)`, written to
a per-run tracker YAML rather than passed through unchanged.

Usage:
    python recording_ingest_worker.py --run-id 1 --video-path /path/to/normalised.mp4 \\
        --report-to http://127.0.0.1:8000 --kind vehicle --model yolo11x.pt \\
        --tracker trackers/fast.yaml --imgsz 960 --frame-stride 1
"""

import argparse
import base64
import json
import math
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

import cv2
import yaml
from ultralytics import YOLO

import person_embedding
import plates as plates_mod
import tracking_common as tc
from car_tracking import VEHICLE_CLASSES
from person_tracking import PERSON_CLASS_ID

_LOG_DIR = Path(__file__).resolve().parent / "worker_logs"

# Whichever of these three is hit first triggers a flush -- keeps a single
# chunk small even on a recording with an unusually long-lived track, and
# keeps latency to "operator sees progress" bounded even on a quiet stretch.
_CHUNK_MAX_TRACKS = 200
_CHUNK_MAX_BYTES = 512 * 1024
_CHUNK_MAX_SECONDS = 15.0
_HEARTBEAT_INTERVAL_SECONDS = 15.0
_BOX_SAMPLE_HZ = 10  # fixed-rate timeline stored/served to the browser
# Context kept around a track's detection box when its thumbnail is cut, as a
# fraction of the box's own width/height per side. See maybe_capture_crop().
_CROP_PAD_FRAC = 0.10
# Thumbnails are small crops shown at 2x on a HiDPI display, so JPEG ringing
# around plate glyphs and number edges is disproportionately visible; the extra
# bytes are irrelevant next to the recording itself.
_CROP_JPEG_QUALITY = 92


def parse_args():
    p = argparse.ArgumentParser(description="Offline recording ingest worker")
    p.add_argument("--run-id", type=int, required=True)
    p.add_argument("--video-path", type=str, required=True)
    p.add_argument("--report-to", type=str, required=True)
    p.add_argument("--kind", choices=("vehicle", "person"), required=True)
    p.add_argument("--model", type=str, required=True)
    p.add_argument("--tracker", type=str, required=True, help="Base tracker YAML, relative to this directory")
    p.add_argument("--imgsz", type=int, default=960)
    p.add_argument("--frame-stride", type=int, default=1)
    p.add_argument("--conf", type=float, default=0.1)
    p.add_argument("--plate-every", type=int, default=3)
    p.add_argument("--min-plate-width", type=int, default=plates_mod.DEFAULT_MIN_PLATE_WIDTH)
    p.add_argument("--min-plate-width-two-row", type=int, default=plates_mod.DEFAULT_MIN_PLATE_WIDTH_TWO_ROW)
    p.add_argument("--min-plate-conf", type=float, default=plates_mod.DEFAULT_MIN_CONF)
    p.add_argument("--plate-votes", type=int, default=plates_mod.DEFAULT_MIN_VOTES)
    return p.parse_args()


def _worker_token() -> str | None:
    return os.environ.get("SENTINEL_WORKER_API_TOKEN")


def _post_json(url: str, payload: dict, timeout: float = 15.0) -> dict | None:
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    token = _worker_token()
    if token:
        headers["X-Sentinel-Worker-Token"] = token
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        return json.loads(body) if body else None


def get_video_fps(path: str) -> float:
    """The video was already CFR-normalised on upload, so this is reliable --
    but guarded anyway: CAP_PROP_FPS can return 0 or NaN on a still-odd file,
    and `0 or 30.0`/`nan or 30.0` behave differently (the latter stays NaN,
    which would poison every timestamp and then fail JSONB insertion at the
    very end of a long ingest)."""
    cap = cv2.VideoCapture(path)
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    finally:
        cap.release()
    if not math.isfinite(fps) or fps <= 0:
        fps = 25.0
    frames_expected = int(frame_count) if math.isfinite(frame_count) and frame_count > 0 else None
    return fps, frames_expected


def derive_tracker_yaml(base_tracker_path: str, fps: float, stride: int) -> tuple[str, dict]:
    """Write a per-run tracker config with track_buffer scaled for the
    actual source fps and stride, rather than passing the tuned static file
    through unchanged. See module docstring."""
    base = yaml.safe_load(open(base_tracker_path))
    original_buffer = base.get("track_buffer", 30)
    # The tuned files assume ~30fps and were written as "90 frames ~= 3s";
    # generalise that as "3 seconds of REAL time", scaled by this video's
    # actual fps and by how many source frames each processed step covers.
    effective_buffer = max(1, round(3.0 * fps / stride))
    base["track_buffer"] = effective_buffer

    out_path = _LOG_DIR / f"tracker-run-derived.yaml"
    _LOG_DIR.mkdir(exist_ok=True)
    with open(out_path, "w") as fh:
        yaml.safe_dump(base, fh)

    return str(out_path), {
        "base_tracker": base_tracker_path,
        "source_fps": fps,
        "frame_stride": stride,
        "track_buffer_original": original_buffer,
        "track_buffer_effective": effective_buffer,
    }


class ChunkSender:
    """POSTs finalised-track chunks, spooling to disk on failure and
    retrying on the next flush. A run must never lose tracks to a transient
    network hiccup between this subprocess and the backend."""

    def __init__(self, report_to: str, run_id: int):
        self.base = report_to.rstrip("/")
        self.run_id = run_id
        self.spool_dir = _LOG_DIR / f"ingest-{run_id}-pending"
        self.spool_dir.mkdir(parents=True, exist_ok=True)
        self.next_seq = 0
        self.total_tracks_sent = 0

    def _chunk_url(self) -> str:
        return f"{self.base}/api/investigate/runs/{self.run_id}/chunk"

    def _flush_spool(self) -> None:
        for f in sorted(self.spool_dir.glob("*.json"), key=lambda p: int(p.stem)):
            try:
                payload = json.loads(f.read_text())
                _post_json(self._chunk_url(), payload)
                f.unlink()
            except Exception as exc:
                print(f"  [chunk] spool retry failed for seq {f.stem}: {exc}")
                break  # preserve order; stop and try the rest next time

    def send(self, tracks: list[dict]) -> None:
        if not tracks:
            return
        seq = self.next_seq
        self.next_seq += 1
        payload = {"seq": seq, "tracks": tracks}
        self._flush_spool()
        try:
            _post_json(self._chunk_url(), payload)
            self.total_tracks_sent += len(tracks)
        except Exception as exc:
            print(f"  [chunk {seq}] POST failed ({exc}); spooling to disk")
            (self.spool_dir / f"{seq}.json").write_text(json.dumps(payload))
            self.total_tracks_sent += len(tracks)  # counted once spooled; retried, never duplicated (seq-keyed)

    def heartbeat(self, frames_processed: int, frames_expected: int | None, track_count: int) -> None:
        try:
            _post_json(
                f"{self.base}/api/investigate/runs/{self.run_id}/heartbeat",
                {"frames_processed": frames_processed, "frames_expected": frames_expected, "track_count": track_count},
                timeout=10,
            )
        except Exception as exc:
            print(f"  [heartbeat] failed (non-fatal): {exc}")

    def complete(self, frames_processed: int, track_count: int, error: str | None = None) -> None:
        self._flush_spool()
        try:
            _post_json(
                f"{self.base}/api/investigate/runs/{self.run_id}/complete",
                {
                    "frames_processed": frames_processed,
                    "track_count": track_count,
                    "chunk_count": self.next_seq,
                    "error": error,
                },
                timeout=20,
            )
        except Exception as exc:
            print(f"  [complete] POST failed: {exc} -- the stall reaper will eventually mark this run stalled")


class ChunkBatcher:
    def __init__(self, sender: ChunkSender):
        self.sender = sender
        self.buffer: list[dict] = []
        self.buffer_bytes = 0
        self.last_flush = time.time()

    def add(self, track_payload: dict) -> None:
        encoded_len = len(json.dumps(track_payload))
        self.buffer.append(track_payload)
        self.buffer_bytes += encoded_len
        if (
            len(self.buffer) >= _CHUNK_MAX_TRACKS
            or self.buffer_bytes >= _CHUNK_MAX_BYTES
            or time.time() - self.last_flush >= _CHUNK_MAX_SECONDS
        ):
            self.flush()

    def maybe_flush_on_time(self) -> None:
        if self.buffer and time.time() - self.last_flush >= _CHUNK_MAX_SECONDS:
            self.flush()

    def flush(self) -> None:
        if self.buffer:
            self.sender.send(self.buffer)
        self.buffer = []
        self.buffer_bytes = 0
        self.last_flush = time.time()


class TrackAccum:
    """Accumulates one track's raw (high-rate) box samples until it is
    finalised, then downsamples to the fixed-rate encoding the boxes
    endpoint serves. Raw samples are pixel-space (cx, cy, w, h); the encoded
    payload normalises to 0..1000 against the frame size.

    Also holds this track's best crop as already-encoded JPEG bytes, updated
    in place whenever a detection scores higher on maybe_capture_crop()'s
    size-and-confidence rule -- never the raw frame, which would be one
    full-resolution image retained per active track for the life of a long
    recording."""

    __slots__ = ("track_ref", "kind", "first_frame", "last_frame", "first_ms",
                 "last_ms", "frame_count", "best_conf", "raw", "best_crop_jpeg",
                 "best_crop_score")

    def __init__(self, track_ref, kind, frame_idx, ms, box, conf):
        self.track_ref = int(track_ref)
        self.kind = kind
        self.first_frame = frame_idx
        self.last_frame = frame_idx
        self.first_ms = ms
        self.last_ms = ms
        self.frame_count = 1
        self.best_conf = float(conf)
        self.raw = [(ms, *box)]
        self.best_crop_jpeg = None
        self.best_crop_score = 0.0

    def update(self, frame_idx, ms, box, conf):
        self.last_frame = frame_idx
        self.last_ms = ms
        self.frame_count += 1
        self.best_conf = max(self.best_conf, float(conf))
        self.raw.append((ms, *box))

    def maybe_capture_crop(self, frame, box, conf) -> None:
        """Keep the crop that will actually be *legible* in the results grid,
        not merely the most confident one.

        Selecting on confidence alone (the previous rule) is what made these
        thumbnails blurry: confidence does not correlate with how many pixels
        the subject occupies, so a distant, small, very-confident car beat the
        same car's close-up a second later. Measured over 315 real thumbnails
        from an earlier ingest, the median crop's short side was 50px and 57%
        were under 64px -- every one of those is upscaled by the 100x64 CSS
        box (200x128 on a 2x display) into visible mush.

        Scoring on `short_side * conf` fixes the cause rather than the symptom:
        short side is exactly what the display box upscales from, and the
        confidence factor still keeps a crisp-but-doubtful box from winning
        over a solid detection of similar size.
        """
        cx, cy, w, h = box
        # A little context around the subject. A crop cut exactly on the box
        # reads as "zoomed in" because the subject is jammed against all four
        # edges; this is also what `object-fit: cover` in the results grid
        # then trims into, so the tight version lost content twice over.
        #
        # Person crops stay tight on purpose: this same JPEG is what
        # person_embedding sees (see to_payload below), and every embedding
        # already stored in `tracks` was computed from an unpadded crop.
        # Padding only these would silently change the framing on one side of
        # a cosine comparison that ranks old and new runs together, so the
        # thumbnail gain is not worth making the search inconsistent.
        pad = _CROP_PAD_FRAC if self.kind != "person" else 0.0
        pad_x, pad_y = w * pad, h * pad
        x1, y1 = max(0, int(cx - w / 2 - pad_x)), max(0, int(cy - h / 2 - pad_y))
        x2 = min(frame.shape[1], int(cx + w / 2 + pad_x))
        y2 = min(frame.shape[0], int(cy + h / 2 + pad_y))
        if x2 - x1 < 2 or y2 - y1 < 2:
            return
        score = min(x2 - x1, y2 - y1) * float(conf)
        if self.best_crop_jpeg is not None and score <= self.best_crop_score:
            return
        ok, buf = cv2.imencode(".jpg", frame[y1:y2, x1:x2],
                               [int(cv2.IMWRITE_JPEG_QUALITY), _CROP_JPEG_QUALITY])
        if ok:
            self.best_crop_jpeg = buf.tobytes()
            self.best_crop_score = score

    def write_thumb(self, thumbs_dir) -> str | None:
        if self.best_crop_jpeg is None:
            return None
        thumbs_dir.mkdir(parents=True, exist_ok=True)
        name = f"track-{self.track_ref}.jpg"
        (thumbs_dir / name).write_bytes(self.best_crop_jpeg)
        return name

    def _encode_boxes(self, frame_w: int, frame_h: int) -> dict:
        dt_ms = round(1000 / _BOX_SAMPLE_HZ)
        t0 = self.raw[0][0]
        buckets: dict[int, tuple] = {}
        for ms, cx, cy, w, h in self.raw:
            idx = round((ms - t0) / dt_ms)
            buckets[idx] = (cx, cy, w, h)
        max_idx = max(buckets)
        samples = []
        last = None
        for i in range(max_idx + 1):
            if i in buckets:
                last = buckets[i]
            if last is None:
                continue
            cx, cy, w, h = last
            samples.append([
                int(round(cx / frame_w * 1000)),
                int(round(cy / frame_h * 1000)),
                int(round(w / frame_w * 1000)),
                int(round(h / frame_h * 1000)),
            ])
        return {"t0_ms": int(t0), "dt_ms": dt_ms, "w": frame_w, "h": frame_h, "b": samples}

    def to_payload(self, frame_w: int, frame_h: int, plate_reader, thumbs_dir=None, thumb_rel_prefix="",
                    embed_persons: bool = False) -> dict:
        thumb_name = self.write_thumb(thumbs_dir) if thumbs_dir is not None else None
        payload = {
            "track_ref": self.track_ref,
            "kind": self.kind,
            "first_frame": self.first_frame,
            "last_frame": self.last_frame,
            "first_ms": self.first_ms,
            "last_ms": self.last_ms,
            "frame_count": self.frame_count,
            "best_conf": self.best_conf,
            "boxes": self._encode_boxes(frame_w, frame_h),
            "thumb_path": f"{thumb_rel_prefix}/{thumb_name}" if thumb_name else None,
        }
        if plate_reader is not None:
            confirmed_text, confirmed_score, confirmed_votes = plate_reader.confirmed(self.track_ref)
            tentative_text, tentative_score, tentative_votes = plate_reader.consensus(self.track_ref)
            payload["plate_confirmed"] = confirmed_text
            payload["plate_tentative"] = tentative_text
            payload["plate_confidence"] = float(confirmed_score or tentative_score) or None
            payload["plate_votes"] = confirmed_votes or tentative_votes or None
        # best_crop_jpeg is already this track's best crop by
        # maybe_capture_crop()'s size-and-confidence rule -- the same image
        # write_thumb() just persisted -- so the embedding and the thumbnail
        # an operator sees are guaranteed to be the same frame, never two
        # different moments of the same track. That crop is unpadded for
        # person tracks specifically so this embedding stays framed the way
        # every previously stored one was.
        if embed_persons and self.kind == "person" and self.best_crop_jpeg is not None:
            try:
                vec = person_embedding.embed_jpeg_bytes(self.best_crop_jpeg)
                payload["embedding"] = base64.b64encode(vec.tobytes()).decode("ascii")
                payload["embedding_dim"] = int(vec.shape[0])
                payload["embedding_model"] = person_embedding.MODEL_NAME
            except Exception as exc:  # noqa: BLE001 - an embedding hiccup must never fail ingest
                print(f"  [embedding] track {self.track_ref}: {type(exc).__name__}: {exc}")
        return payload


def main():
    args = parse_args()

    # Thumbnails live beside the recording itself
    # (recordings/<sha256>/thumbs/track-N.jpg), so `thumb_path` reported to
    # the backend needs only the "<sha256>/thumbs/..." portion -- the same
    # convention the backend already uses for `normalised_path`.
    video_path = Path(args.video_path)
    content_dir = video_path.parent
    thumbs_dir = content_dir / "thumbs" / f"run-{args.run_id}"
    thumb_rel_prefix = f"{content_dir.name}/thumbs/run-{args.run_id}"

    fps, frames_expected = get_video_fps(args.video_path)
    tracker_path, effective_settings = derive_tracker_yaml(args.tracker, fps, args.frame_stride)
    print(f"[IngestWorker] run={args.run_id} kind={args.kind} fps={fps:.2f} "
          f"frames_expected={frames_expected} tracker={effective_settings}")

    device = tc.resolve_device()
    quantize, half = tc.resolve_quantize(False, device)
    print(f"[IngestWorker] Device: {device} (fp16={half}, imgsz={args.imgsz})")

    model = YOLO(args.model)
    plate_reader = None
    embed_persons = False
    if args.kind == "vehicle":
        plate_reader = plates_mod.PlateReader(
            device=device, min_plate_width=args.min_plate_width, min_conf=args.min_plate_conf,
            min_votes=args.plate_votes, min_plate_width_two_row=args.min_plate_width_two_row,
        )
        print(f"[IngestWorker] Plate ONNX providers: {plate_reader.providers()}")
    else:
        person_embedding.load(device)
        embed_persons = True
        print(f"[IngestWorker] Person embedding model: {person_embedding.MODEL_NAME} "
              f"({person_embedding.EMBEDDING_DIM}-d)")

    classes = list(VEHICLE_CLASSES.keys()) if args.kind == "vehicle" else [PERSON_CLASS_ID]

    sender = ChunkSender(args.report_to, args.run_id)
    batcher = ChunkBatcher(sender)

    active: dict[int, TrackAccum] = {}
    frame_w = frame_h = None
    processed = 0
    last_heartbeat = 0.0
    error: str | None = None

    # Buffer window, converted from tracker-updates back to real milliseconds
    # of source video (each processed step already covers `frame_stride`
    # source frames).
    buffer_ms = effective_settings["track_buffer_effective"] * args.frame_stride / fps * 1000.0

    try:
        results_iter = model.track(
            source=args.video_path, stream=True, persist=True,
            tracker=tracker_path, conf=args.conf, classes=classes,
            device=device, quantize=quantize, imgsz=args.imgsz,
            vid_stride=args.frame_stride, verbose=False,
        )
        for result in results_iter:
            if frame_w is None:
                frame_h, frame_w = result.orig_shape[:2]

            source_frame_idx = processed * args.frame_stride
            ms = int(round(source_frame_idx / fps * 1000))
            boxes, track_ids, class_ids, confs = tc.unpack_tracks(result)

            seen_now = set()
            for box, track_id, _cls_id, conf in zip(boxes, track_ids, class_ids, confs):
                seen_now.add(track_id)
                box_t = tuple(float(v) for v in box)
                if track_id in active:
                    active[track_id].update(source_frame_idx, ms, box_t, conf)
                else:
                    active[track_id] = TrackAccum(track_id, args.kind, source_frame_idx, ms, box_t, conf)
                active[track_id].maybe_capture_crop(result.orig_img, box_t, conf)

            if plate_reader is not None:
                plate_reader.read_vehicles(result.orig_img, boxes, track_ids, processed, args.plate_every,
                                           class_names=[model.names.get(int(c)) for c in class_ids])

            for track_id in [tid for tid in active if tid not in seen_now]:
                track = active[track_id]
                if ms - track.last_ms > buffer_ms:
                    batcher.add(track.to_payload(frame_w, frame_h, plate_reader, thumbs_dir, thumb_rel_prefix,
                                                  embed_persons))
                    del active[track_id]

            processed += 1
            batcher.maybe_flush_on_time()

            now = time.time()
            if now - last_heartbeat > _HEARTBEAT_INTERVAL_SECONDS:
                sender.heartbeat(processed, frames_expected, len(active))
                last_heartbeat = now

            if processed % 100 == 0:
                print(f"  {processed} frames, {len(active)} active tracks, "
                      f"{sender.total_tracks_sent} tracks sent so far")

        # Stream ended normally: every still-active track is final, not lost.
        for track in active.values():
            batcher.add(track.to_payload(frame_w or 1, frame_h or 1, plate_reader, thumbs_dir, thumb_rel_prefix,
                                          embed_persons))
        active.clear()
        batcher.flush()

    except Exception as exc:  # noqa: BLE001 - always report, never leave the run to time out silently
        error = f"{type(exc).__name__}: {exc}"
        print(f"[IngestWorker] FAILED: {error}")
        batcher.flush()

    print(f"[IngestWorker] Done - {processed} frames, {sender.total_tracks_sent} tracks reported, "
          f"{sender.next_seq} chunks, error={error}")
    sender.complete(processed, sender.total_tracks_sent, error=error)


if __name__ == "__main__":
    main()
