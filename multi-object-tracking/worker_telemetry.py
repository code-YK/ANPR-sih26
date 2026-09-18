"""
Worker telemetry: what is this detector actually seeing, right now?
===================================================================
Both observation workers run a full YOLO track() on every frame, but until
this module existed they only ever reported their *end product* -- a
confirmed plate, or a 30s person-count window. On a camera surveyed as
unable to resolve plates (most of the sandbox at night), that meant a
worker could run perfectly for an hour and emit nothing at all, which is
indistinguishable from a worker that is broken or not running.

This closes that gap by publishing two things per worker:

  camera-<id>-<mode>.status.json   rolling detection counts + stream health
  camera-<id>-<mode>.jpg           latest annotated frame, boxes drawn

Both are written to the same worker_logs/ directory the backend already
owns, and the backend serves them (see backend/app/routers/analytics.py).
Disk rather than HTTP POST on purpose: the worker is always a subprocess
of the backend on the same machine (subprocess.Popen in analytics.py), so
a file is cheaper than a network round trip several times a second, and
it disappears with the worker instead of accumulating rows.

Nothing here is a claim about a vehicle's identity -- the annotated frame
is a *detector view*, showing what the model found, and the counts are
detections and tracks, not plates. A plate only ever becomes a fact via
the confirmed/voted path in plates.py.
"""

import json
import os
import tempfile
import threading
import time

import cv2

import tracking_common as tc


class TelemetryWriter:
    """Accumulates per-frame detection stats and periodically publishes a
    status file plus an annotated snapshot.

    `snapshot_every` was originally 2.0s on the assumption that encoding
    cost would dominate. Measured, it doesn't: a 960x540 q70 encode is
    ~2.3ms. At 0.5 fps the view read as a slideshow of stills and looked
    several seconds staler than it was, which made a healthy detector look
    broken; 0.1s (10 fps) read as video, and 0.04s (25 fps) reads as smooth
    video -- the operator console now gives this view as much screen as the
    live player, where 10 fps visibly stutters.

    Publishing happens on one background thread, never in the inference
    loop. Copying a full-resolution frame, drawing, downscaling and encoding
    is a few milliseconds per snapshot, and the atomic rename can briefly
    retry on Windows while the backend is reading the previous file; at 25
    publishes a second both would otherwise be charged to every tracked
    frame. The thread holds a single "latest" slot: if it is still busy when
    the next snapshot is due, the older pending one is replaced rather than
    queued, so the view can drop a frame but can never fall behind the
    detector.

    Still not a second video stream: it stays capped at `max_width` and is
    labelled a detector view, because the worker's frames are independent of
    the browser player's by construction.
    """

    def __init__(self, camera_id, mode, out_dir, class_names, class_colors,
                 snapshot_every=0.04, status_every=0.3, jpeg_quality=70,
                 max_width=960, trail_length=50, trail_ttl_frames=150):
        self.camera_id = str(camera_id)
        self.mode = mode
        self.out_dir = out_dir
        self.class_names = class_names
        self.class_colors = class_colors
        self.snapshot_every = snapshot_every
        self.status_every = status_every
        self.jpeg_quality = jpeg_quality
        self.max_width = max_width

        os.makedirs(out_dir, exist_ok=True)
        stem = f"camera-{self.camera_id}-{mode}"
        self.status_path = os.path.join(out_dir, f"{stem}.status.json")
        self.snapshot_path = os.path.join(out_dir, f"{stem}.jpg")

        self.started_at = time.time()
        self.seen_track_ids = set()
        self.current_count = 0
        self.peak_count = 0
        self.frames = 0
        self.last_detection_at = None

        self._last_snapshot = 0.0
        self._last_status = 0.0

        # Motion trails, the same ones car_tracking_live.py draws -- the
        # headless workers were tracking paths all along and simply had
        # nowhere to show them, so the detector view rendered boxes with no
        # sense of direction. Kept here rather than in each worker so vehicle
        # and person modes get identical behaviour from one implementation.
        #
        # Unlike the interactive scripts (which run for a video's length and
        # can leak track history harmlessly), a worker runs for days, so
        # trails are pruned: `trail_ttl_frames` after a track was last seen
        # its history is dropped, bounding memory on a busy junction where
        # ids accumulate continuously.
        self.trail_length = trail_length
        self.trail_ttl_frames = trail_ttl_frames
        self._trails = {}        # track_id -> deque of (x, y) centres
        self._trail_last_seen = {}  # track_id -> self.frames when last updated

        # Background publisher (see class docstring). One pending slot per
        # output kind; the thread is started lazily on first use.
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._pending_snapshot = None
        self._pending_status = None
        self._stopping = False
        self._thread = None

    # -- per-frame ---------------------------------------------------------

    def update(self, frame, boxes, track_ids, class_ids, confs=None,
               sublabels=None, extra=None):
        """Call once per processed frame, after track(). Cheap on every
        frame: drawing, encoding and file writes run on the publisher
        thread when their timers are due.

        `sublabels` optionally maps track_id -> str (the ANPR worker uses it
        to show a tentative plate read under the box, clearly marked as
        tentative rather than confirmed).
        """
        self.frames += 1
        self.current_count = len(track_ids)
        self.peak_count = max(self.peak_count, self.current_count)
        if track_ids:
            self.seen_track_ids.update(track_ids)
            self.last_detection_at = time.time()

        # Every frame, not just the ones that get published: a trail sampled
        # only at the snapshot interval would be a handful of scattered
        # points rather than a path.
        self._update_trails(boxes, track_ids)

        now = time.time()
        if now - self._last_snapshot >= self.snapshot_every:
            self._submit_snapshot(frame, boxes, track_ids, class_ids, confs, sublabels)
            self._last_snapshot = now
        if now - self._last_status >= self.status_every:
            self.write_status(extra)
            self._last_status = now

    def _update_trails(self, boxes, track_ids):
        """Append each track's current centre to its trail, and drop the
        history of tracks that have left the scene."""
        for box, track_id in zip(boxes, track_ids):
            trail = self._trails.get(track_id)
            if trail is None:
                trail = tc.new_trail(self.trail_length)
                self._trails[track_id] = trail
            # Ultralytics boxes are xywh in centre form, so (x, y) is already
            # the point we want to trace.
            trail.append((float(box[0]), float(box[1])))
            self._trail_last_seen[track_id] = self.frames

        # Pruning is the difference between this and the interactive scripts'
        # defaultdict, which never forgets a track. Swept periodically rather
        # than every frame: it is bookkeeping, not per-frame work.
        if self.frames % 60 == 0 and self._trail_last_seen:
            cutoff = self.frames - self.trail_ttl_frames
            for track_id in [t for t, seen in self._trail_last_seen.items() if seen < cutoff]:
                self._trails.pop(track_id, None)
                self._trail_last_seen.pop(track_id, None)

    # -- publishing --------------------------------------------------------

    def _submit_snapshot(self, frame, boxes, track_ids, class_ids, confs, sublabels):
        """Hand the publisher everything it needs to draw this frame.

        Only immutable-by-construction data crosses the thread boundary:
        the frame and box arrays are fresh per processed frame, and trails
        (which this thread keeps mutating) are copied to plain lists here.
        """
        job = {
            "frame": frame,
            "boxes": [tuple(float(v) for v in box) for box in boxes],
            "track_ids": list(track_ids),
            "class_ids": list(class_ids),
            "confs": list(confs) if confs is not None else None,
            "sublabels": dict(sublabels) if sublabels else None,
            "trails": {
                track_id: list(self._trails[track_id])
                for track_id in track_ids
                if track_id in self._trails and len(self._trails[track_id]) > 1
            },
            "hud": [
                f"cam {self.camera_id} | {self.mode}",
                f"tracked now: {self.current_count}",
                f"unique tracks: {len(self.seen_track_ids)}",
            ],
        }
        with self._lock:
            self._pending_snapshot = job
        self._ensure_thread()
        self._wake.set()

    def _ensure_thread(self):
        if self._thread is None and not self._stopping:
            self._thread = threading.Thread(
                target=self._publish_loop, name=f"telemetry-{self.camera_id}-{self.mode}", daemon=True,
            )
            self._thread.start()

    def _publish_loop(self):
        while True:
            self._wake.wait()
            with self._lock:
                self._wake.clear()
                snapshot, self._pending_snapshot = self._pending_snapshot, None
                status, self._pending_status = self._pending_status, None
                stopping = self._stopping
            if stopping:
                return
            if snapshot is not None:
                try:
                    self._render_snapshot(snapshot)
                except Exception:
                    pass  # observability must not break the detector
            if status is not None:
                self._atomic_write(self.status_path, status, "w")

    def _render_snapshot(self, job):
        annotated = job["frame"].copy()
        track_ids = job["track_ids"]
        class_ids = job["class_ids"]
        confs = job["confs"] if job["confs"] is not None else [None] * len(track_ids)
        sublabels = job["sublabels"]

        # Trails first, so boxes and labels stay legible on top of them.
        # Drawn in each track's own class colour so a path is attributable to
        # the object that made it rather than being one anonymous colour.
        for track_id, cls_id in zip(track_ids, class_ids):
            trail = job["trails"].get(track_id)
            if trail is not None:
                tc.draw_trail(annotated, trail, self.class_colors.get(cls_id, (0, 200, 255)))

        for box, track_id, cls_id, conf in zip(job["boxes"], track_ids, class_ids, confs):
            x1, y1, x2, y2 = tc.xywh_to_corners(box)
            color = self.class_colors.get(cls_id, (0, 200, 255))
            name = self.class_names.get(cls_id, "object")
            label = f"{name} #{track_id}" + (f" {conf:.2f}" if conf is not None else "")
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            sub = sublabels.get(track_id) if sublabels else None
            tc.draw_label(annotated, x1, y1, color, label, sub)

        # Scale down before encoding: this is a status view shown beside a
        # live player, not evidence, and a 2560x1440 JPEG many times a
        # second is pure waste.
        h, w = annotated.shape[:2]
        if w > self.max_width:
            scale = self.max_width / w
            annotated = cv2.resize(annotated, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

        tc.draw_hud(annotated, job["hud"], translucent=True)

        ok, buf = cv2.imencode(".jpg", annotated,
                               [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])
        if ok:
            self._atomic_write(self.snapshot_path, buf.tobytes(), "wb")

    def write_status(self, extra=None):
        payload = {
            "camera_id": self.camera_id,
            "mode": self.mode,
            "updated_at": time.time(),
            "uptime_seconds": round(time.time() - self.started_at, 1),
            "frames_processed": self.frames,
            "tracked_now": self.current_count,
            "peak_tracked": self.peak_count,
            "unique_tracks": len(self.seen_track_ids),
            "last_detection_at": self.last_detection_at,
            "has_snapshot": os.path.exists(self.snapshot_path),
            "snapshot_interval_seconds": self.snapshot_every,
        }
        if extra:
            payload.update(extra)
        with self._lock:
            self._pending_status = json.dumps(payload)
        self._ensure_thread()
        self._wake.set()

    @staticmethod
    def _atomic_write(path, data, mode, attempts=5, retry_delay=0.01):
        """Write via a temp file + rename so the backend never serves a
        half-written JPEG or a truncated JSON document.

        The rename is retried, and failure is swallowed rather than raised.
        Both matter on Windows: os.replace() there fails with
        PermissionError(WinError 5) if any other process has the destination
        open, and the backend is reading exactly these files to serve the
        detector view. POSIX rename has no such restriction, so this only
        shows up once the publish rate is high enough to collide. The retry
        sleeps run on the publisher thread, never in the inference loop.

        Telemetry is best-effort observability. A dropped write costs one
        frame of a view that refreshes many times a second; taking down a
        detector that is otherwise tracking correctly is not a trade worth
        making, so this never raises to the caller.
        """
        directory = os.path.dirname(path)
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, mode) as fh:
                fh.write(data)
            for attempt in range(attempts):
                try:
                    os.replace(tmp, path)
                    return
                except PermissionError:
                    # Reader holds it open; it will be gone in microseconds.
                    if attempt == attempts - 1:
                        raise
                    time.sleep(retry_delay)
        except Exception:
            pass  # see docstring: observability must not break the detector
        finally:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    def cleanup(self):
        """Stop the publisher, then remove published artefacts on a clean
        exit -- a stale snapshot from a worker that is no longer running
        would misrepresent a dead detector as a live one. The thread is
        stopped first so it cannot re-publish a file after it was removed."""
        with self._lock:
            self._stopping = True
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        for path in (self.status_path, self.snapshot_path):
            try:
                os.unlink(path)
            except OSError:
                pass
