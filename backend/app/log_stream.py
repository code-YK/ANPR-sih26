"""In-memory log capture for the operator console's live Logs panel.

Two sources are exposed to the frontend over Server-Sent Events (see
routers/logs.py):

  * "backend"  -- this process's own logging output (uvicorn + the sentinel.*
                  loggers), captured by attaching RingBufferHandler to the
                  root logger at startup.
  * "workers"  -- the ANPR/person inference subprocesses, which write to
                  multi-object-tracking/worker_logs/camera-<id>-<mode>.log;
                  tailed from disk on demand.

Everything is in-memory and best-effort: a bounded ring buffer for backend
records, and byte-offset tailing for worker files. Nothing here is persisted
by this module, and a failure to capture a log line must never disturb the
thing being logged -- every path is guarded.

The ring buffer is thread-safe (a logging handler can emit from any thread --
uvicorn's, the event loop's, a worker pool's) and hands out entries by a
monotonic sequence number, so an SSE reader just remembers the last seq it
sent and asks for anything newer. That polling model avoids cross-thread
asyncio-queue plumbing entirely.
"""

from __future__ import annotations

import itertools
import logging
import os
import threading
import time
from collections import deque
from glob import glob
from pathlib import Path

# The Logs panel is a live tail that keeps only the last ~50 lines, so the
# server-side backlog a viewer receives on connect is capped to match --
# no point buffering (or streaming) more than the panel will ever show.
_MAX_BACKEND_LINES = 50

_lock = threading.Lock()
_seq = itertools.count(1)
_buffer: deque[dict] = deque(maxlen=_MAX_BACKEND_LINES)


class RingBufferHandler(logging.Handler):
    """Logging handler that appends formatted records to the shared ring
    buffer. Emit is wrapped so a formatting error can never propagate into
    the code that logged the record."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "seq": next(_seq),
                "ts": record.created,
                "level": record.levelname,
                "logger": record.name,
                "msg": self.format(record),
            }
            with _lock:
                _buffer.append(entry)
        except Exception:  # noqa: BLE001 - logging must never raise
            pass


def backend_entries_since(seq: int) -> list[dict]:
    """Every buffered record with a sequence number greater than `seq`,
    oldest first. `seq=0` returns the whole current buffer."""
    with _lock:
        return [e for e in _buffer if e["seq"] > seq]


def install(level: int = logging.INFO) -> None:
    """Attach the ring-buffer handler to the root logger, once. uvicorn's
    loggers propagate to root by default, so this captures access lines and
    the sentinel.* loggers together."""
    root = logging.getLogger()
    if any(isinstance(h, RingBufferHandler) for h in root.handlers):
        return
    handler = RingBufferHandler()
    # Compact: the frontend shows level/logger/time from the structured
    # fields, so the message body itself stays plain.
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.setLevel(level)
    root.addHandler(handler)
    if root.level > level or root.level == logging.NOTSET:
        root.setLevel(level)


# --------------------------------------------------------------------------
# Worker log tailing
# --------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKER_LOG_DIR = _REPO_ROOT / "multi-object-tracking" / "worker_logs"

# How much of each worker log to show as backfill when a viewer first opens
# the panel, so the panel is not blank until the next line is written. Kept
# small because the panel only shows the last ~50 lines anyway.
_WORKER_BACKFILL_BYTES = 2048


def _source_label(path: str) -> str:
    """camera-21-vehicle.log -> "cam 21 · vehicle"."""
    name = os.path.basename(path)
    stem = name[:-4] if name.endswith(".log") else name
    if stem.startswith("camera-"):
        rest = stem[len("camera-"):]
        cam, _, mode = rest.rpartition("-")
        if cam and mode:
            return f"cam {cam} · {mode}"
    return stem


def worker_initial_offsets() -> dict[str, int]:
    """Starting byte offset per worker log for a fresh viewer: a little before
    the end of each existing file, so the panel opens with recent context
    rather than empty, then tails forward from there."""
    offsets: dict[str, int] = {}
    for path in glob(str(_WORKER_LOG_DIR / "*.log")):
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        offsets[path] = max(0, size - _WORKER_BACKFILL_BYTES)
    return offsets


def worker_lines_since(offsets: dict[str, int]) -> list[dict]:
    """Read any bytes appended to each worker log since we last looked, plus
    pick up logs from workers that started after the viewer connected.

    `offsets` is mutated in place to track the new per-file positions. Each
    returned entry is {source, ts, msg}. A worker log that shrank (a fresh run
    truncated it) is re-read from the top.
    """
    out: list[dict] = []
    for path in glob(str(_WORKER_LOG_DIR / "*.log")):
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        # A file we have not seen before started after the viewer connected;
        # show it from the beginning (it is short at that point).
        start = offsets.get(path, 0)
        if size < start:  # truncated / rotated -> re-read from top
            start = 0
        if size <= start:
            offsets[path] = size
            continue
        try:
            with open(path, "rb") as fh:
                fh.seek(start)
                data = fh.read()
        except OSError:
            continue
        offsets[path] = size
        label = _source_label(path)
        now = time.time()
        for raw in data.decode("utf-8", errors="replace").splitlines():
            line = raw.rstrip("\r")
            if line.strip():
                out.append({"source": label, "ts": now, "msg": line})
    return out
