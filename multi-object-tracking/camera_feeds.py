"""
Live camera feed discovery and streaming
========================================
Talks to the configured ingest API, resolves HLS URLs, and provides a frame reader
built for live sources rather than files.

The important difference from the file reader in tracking_common: a live stream
cannot be slowed down. If inference is slower than the stream, buffering frames
just accumulates latency until the display is minutes behind reality. This
reader drops stale frames instead, so what you see is always current.

CLI:
    python camera_feeds.py --list           # list cameras from the API
    python camera_feeds.py --probe          # test which ones actually decode
    python camera_feeds.py --probe --id 13  # test one
"""

import argparse
import http.cookiejar
import json
import os
import queue
import re
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

# These feeds are LL-HLS with 10-SECOND segments. FFmpeg ignores the sub-second
# EXT-X-PART entries and only consumes whole segments, so it decodes a 10s chunk
# in a burst and then legitimately waits ~10s for the next one to be published.
#
# A short read timeout mistakes that normal wait for a dead connection, tears the
# stream down and reconnects - which costs far more than waiting would have.
# Measured on camera 29: a 15s timeout gave 7.6 FPS with 30s gaps, while a 60s
# timeout gave 33.9 FPS with gaps capped at one segment (10s). Counter-intuitive
# but consistent: for segmented live HLS the timeout must exceed the segment
# duration by a wide margin.
# live_start_index: where in the live playlist a fresh connection begins.
# FFmpeg's HLS default is -3 -- three segments back from the live edge, which
# at this sandbox's ~10s segments starts the worker up to half a minute
# behind live and keeps it there, since nothing ever catches up afterwards.
# -1 starts on the newest complete segment instead, which is what closes most
# of the gap between the detector view and the browser player (hls.js makes
# the same trade with liveSyncDurationCount). If a camera ever fails to open
# because its newest segment is still being written, the reader's existing
# reconnect path retries; raise this toward -3 to trade latency for margin.
# rtsp_transport;tcp: the sandbox's own integrator's guide requires this
# ("force RTSP over TCP"). FFmpeg's RTSP default is UDP, which on the real
# WAN path to the sandbox drops/reorders packets -- confirmed live: the
# detector view showed heavy macroblock smearing (missing reference-frame
# data corrupting everything until the next keyframe) while the tracker
# itself kept running fine underneath. Harmless for the HLS candidate: an
# option a demuxer doesn't recognise is just ignored (any resulting log
# line is already silenced by quiet_ffmpeg()).
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp|timeout;60000000|rw_timeout;60000000|live_start_index;-1",
)

import cv2  # noqa: E402  (must follow the env var above)


def quiet_ffmpeg():
    """Silence FFmpeg's per-frame chatter on flaky streams.

    cv2.setLogLevel moved under cv2.utils.logging in OpenCV 5.
    """
    try:
        import cv2.utils.logging as cvlog
        cvlog.setLogLevel(0)
    except Exception:
        try:
            cv2.setLogLevel(0)
        except Exception:
            pass


API_URL = os.environ.get("SANDBOX_CATALOGUE_URL")
BASE_URL = os.environ.get("SANDBOX_BROWSER_BASE_URL")

# Distinct end-of-stream marker. A plain None cannot be used because an empty
# queue and a finished stream must not look the same to the consumer.
_EOS = object()

# The API rejects urllib's default User-Agent with 403.
UA = "Mozilla/5.0"


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------

def fetch_cameras(timeout=20):
    """Return the camera list from the ingest API."""
    if not API_URL:
        raise RuntimeError(
            "SANDBOX_CATALOGUE_URL is required; obtain it outside Git and export it locally"
        )
    req = urllib.request.Request(API_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)["cameras"]


def hls_url(camera):
    """Absolute HLS URL for a camera record."""
    value = camera["hls_live_url"]
    if value.startswith(("http://", "https://")):
        return value
    if not BASE_URL:
        raise RuntimeError(
            "SANDBOX_BROWSER_BASE_URL is required to resolve relative HLS paths"
        )
    return urllib.parse.urljoin(f"{BASE_URL.rstrip('/')}/", value.lstrip("/"))


def resolve_source(camera_id, cameras=None):
    """Resolve a camera id to a playable HLS URL.

    Raises LookupError if the id is not in the API listing.
    """
    cameras = cameras if cameras is not None else fetch_cameras()
    for c in cameras:
        if str(c["id"]) == str(camera_id):
            return hls_url(c), c
    known = ", ".join(str(c["id"]) for c in cameras)
    raise LookupError(f"camera id {camera_id!r} not found. Available: {known}")


def describe_camera(c):
    dims = f"{c.get('width')}x{c.get('height')}" if c.get("width") else "unknown"
    return (f"cam {c['id']} | {c.get('location', '')} | "
            f"{c.get('codec') or 'codec?'} {dims} @{c.get('fps') or '?'}")


# --------------------------------------------------------------------------
# Absolute time anchoring
# --------------------------------------------------------------------------

class ProgramDateTimeAnchor:
    """Maps a connection-relative frame PTS to an absolute UTC timestamp.

    OpenCV's CAP_PROP_POS_MSEC on these streams is just frame_index / declared
    fps (verified: exactly 40ms/frame regardless of real arrival rate) -
    monotonic and fixed-per-frame, but reset to 0 on every connection and with
    no relation to real-world time. ffprobe's own pkt_pts_time shows the same
    fps-derived pattern, so there is no better per-frame PTS to be had from the
    decoder here.

    The HLS media playlist itself does carry #EXT-X-PROGRAM-DATE-TIME, an
    absolute UTC timestamp refreshed roughly every segment (~10s here). That is
    real signal: anchor the connection-relative PTS to it once per connection
    and periodically thereafter, then interpolate between anchors with PTS
    deltas. This does not require correlating individual frames to specific
    segments/parts - the achievable accuracy is bounded to roughly one segment
    duration plus however stale the anchor has drifted, which is an accepted,
    documented limitation (see docs/model2-build-spec.md): it preserves
    ordering and per-camera internal consistency, which is what route
    reconstruction needs, without claiming frame-perfect absolute time.
    """

    REFRESH_INTERVAL_S = 30.0
    _PDT_RE = re.compile(r"#EXT-X-PROGRAM-DATE-TIME:(\S+)")

    def __init__(self, master_url):
        self.master_url = master_url
        # Program-date-time is HLS playlist metadata. An RTSP-only source is
        # still a valid detector input, but asking urllib to fetch it as a
        # playlist on every decoded frame wastes the worker's entire budget.
        # Keep its source PTS/epoch for diagnostics and leave `seen_at` null
        # rather than inventing an absolute timestamp from frame arrival.
        self.supports_program_date_time = urllib.parse.urlparse(master_url).scheme in {"http", "https"}
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        self._variant_url = None
        self.anchor_wall = None      # datetime (UTC) or None if never anchored
        self.anchor_pts_ms = None
        self._last_refresh_at = 0.0  # time.monotonic()
        # Seconds this connection has fallen behind the live edge, summed
        # across refreshes. See refresh() for how it is derived and why it
        # is immune to our own system clock being wrong.
        self.drift_since_connect = 0.0

    def _fetch(self, url):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with self._opener.open(req, timeout=15) as resp:
            return resp.geturl(), resp.read().decode("utf-8", errors="replace")

    def _resolve_variant_url(self):
        """The catalogue's hls_live_url is a master playlist one indirection
        away from the media playlist that actually carries PROGRAM-DATE-TIME."""
        final_url, text = self._fetch(self.master_url)
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return urllib.parse.urljoin(final_url, line)
        return final_url  # already a media playlist; handled defensively

    @classmethod
    def _parse_program_date_time(cls, text):
        matches = cls._PDT_RE.findall(text)
        if not matches:
            return None
        # Python 3.11+ fromisoformat accepts the trailing 'Z'.
        return datetime.fromisoformat(matches[-1])

    def refresh(self, current_pts_ms, force=False):
        """Re-anchor from the live playlist. Cheap enough to call often; only
        does real work every REFRESH_INTERVAL_S unless force=True (reconnect).

        Returns True if the anchor was updated, False if skipped or a fetch
        failed - a failed refresh just means the previous anchor keeps being
        extrapolated a bit longer, never a crash.
        """
        if not self.supports_program_date_time:
            return False
        now = time.monotonic()
        if not force and (now - self._last_refresh_at) < self.REFRESH_INTERVAL_S:
            return False
        try:
            if self._variant_url is None:
                self._variant_url = self._resolve_variant_url()
            _, text = self._fetch(self._variant_url)
            wall = self._parse_program_date_time(text)
        except Exception:
            return False
        if wall is None:
            return False

        # How far we slipped behind live since the previous anchor. `wall` is
        # the playlist's newest PROGRAM-DATE-TIME (the live edge); the old
        # anchor extrapolated to the current PTS says where our decode
        # position believes it is. Decoding slower than real time advances
        # PTS slower than the live edge advances, so the difference is the
        # slippage. Both sides come from the stream's own clock, so a skewed
        # local clock cancels out -- which matters here, where the sandbox's
        # PDT runs several seconds ahead of this machine.
        predicted = self.seen_at(current_pts_ms)
        if predicted is not None:
            self.drift_since_connect += (wall - predicted).total_seconds()

        self.anchor_wall = wall
        self.anchor_pts_ms = current_pts_ms
        self._last_refresh_at = now
        return True

    def reset(self):
        """Drop the anchor (used on reconnect/epoch bump so a stale anchor is
        never extrapolated across a discontinuity)."""
        self.anchor_wall = None
        self.anchor_pts_ms = None
        self._last_refresh_at = 0.0
        # A reconnect re-enters at the live edge, so accumulated slippage
        # from the previous connection no longer describes where we are.
        self.drift_since_connect = 0.0

    def seen_at(self, pts_ms):
        """Best-known absolute UTC datetime for a frame at this pts_ms, or
        None if never successfully anchored (e.g. every playlist fetch failed)."""
        if self.anchor_wall is None:
            return None
        delta_s = (pts_ms - self.anchor_pts_ms) / 1000.0
        return self.anchor_wall + timedelta(seconds=delta_s)


# --------------------------------------------------------------------------
# Live frame reader
# --------------------------------------------------------------------------

class LiveFrameReader:
    """Read a live stream on a worker thread, always yielding the newest frame.

    Unlike the file reader, a full queue here means inference is behind the
    stream. The oldest frame is discarded rather than blocking the reader,
    which keeps latency bounded instead of letting it grow without limit.

    Reconnects automatically: live streams drop, and a tracker that dies on the
    first hiccup is useless for a camera that runs for days.
    """

    def __init__(self, url, buffer=2, reconnect=True, max_retries=0, name="live",
                 max_drift_seconds=6.0, fallback_url=None, timestamp_url=None):
        self.url = url
        self.fallback_url = fallback_url if fallback_url and fallback_url != url else None
        self.timestamp_url = timestamp_url or url
        self.queue = queue.Queue(maxsize=max(1, buffer))
        self.reconnect = reconnect
        self.max_retries = max_retries  # 0 = unlimited
        self.name = name
        # Reconnect once this connection has fallen this far behind the live
        # edge, so the detector keeps showing roughly what the operator is
        # watching rather than drifting further behind for the whole run.
        # Dropping the connection is the only way back to live: FFmpeg has
        # no seek on a live HLS playlist, and a fresh open re-enters at
        # live_start_index. 0 disables the check. Bounded by the anchor's
        # refresh interval, so a resync lands within ~30s of the threshold
        # being crossed, and never mid-stall (drift is only sampled on a
        # successful playlist fetch).
        self.max_drift_seconds = max_drift_seconds
        self.resyncs = 0

        self.stopped = threading.Event()
        self.connected = threading.Event()
        self.finished = threading.Event()
        self.stall_timeout = 180.0  # give up only after a long silence
        self.dropped = 0
        self.reconnects = 0
        self.last_frame_at = None
        self.width = 0
        self.height = 0
        self.fps = 0.0
        self.transport = None
        self._error = None
        self.thread = threading.Thread(target=self._reader, daemon=True)

        # -- absolute time anchoring (see ProgramDateTimeAnchor) --
        # Frames may come from RTSP while absolute time comes from the same
        # camera's HLS program-date-time metadata. The pairing is refreshed
        # against the current frame PTS and reset on every reconnect/transport
        # switch; frame-arrival wall time is never substituted.
        self._anchor = ProgramDateTimeAnchor(self.timestamp_url)
        self.epoch_id = 0
        self._last_pts_ms = None  # last raw pts seen, to detect a discontinuity
        # Set by poll()/read() to describe the frame just returned.
        self.last_pts_ms = None
        self.last_epoch_id = None
        self.last_seen_at = None

    # -- lifecycle ---------------------------------------------------------

    def open(self, timeout=40):
        """Start the reader and block until the first connection succeeds."""
        self.thread.start()
        if not self.connected.wait(timeout=timeout):
            self.stop()
            raise TimeoutError(
                f"could not open stream within {timeout}s (endpoint redacted)"
                + (f" ({self._error})" if self._error else "")
            )
        return self

    def _connect(self):
        candidates = [self.url]
        if self.fallback_url:
            candidates.append(self.fallback_url)
        for candidate in candidates:
            cap = cv2.VideoCapture(candidate, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                cap.release()
                continue
            # Keep OpenCV's own buffer shallow; our queue handles staleness.
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self.fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            scheme = urllib.parse.urlparse(candidate).scheme.lower()
            self.transport = "rtsp" if scheme in {"rtsp", "rtsps"} else "hls"
            return cap
        return None

    def _reader(self):
        attempt = 0
        first_connection = True
        while not self.stopped.is_set():
            cap = self._connect()
            if cap is None:
                attempt += 1
                self._error = "stream did not open"
                if not self.reconnect or (self.max_retries and attempt >= self.max_retries):
                    break
                # Back off, but stay responsive to stop().
                if self.stopped.wait(min(2 * attempt, 15)):
                    break
                self.reconnects += 1
                continue

            attempt = 0
            self.connected.set()

            if not first_connection:
                # A reconnect is a new stream epoch: prior PTS values are not
                # comparable to what comes next (GOV-ING-009 discontinuity).
                self.epoch_id += 1
            first_connection = False
            self._anchor.reset()
            self._last_pts_ms = None
            anchored = False

            while not self.stopped.is_set():
                success, frame = cap.read()
                if not success:
                    break  # stream dropped; fall through to reconnect

                pts_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
                if self._last_pts_ms is not None and pts_ms < self._last_pts_ms:
                    # PTS went backwards: the sandbox's simulated-live loop
                    # restarting mid-connection. New epoch, fresh anchor.
                    self.epoch_id += 1
                    self._anchor.reset()
                    anchored = False
                self._last_pts_ms = pts_ms

                if self._anchor.refresh(pts_ms, force=not anchored):
                    anchored = True
                    # Fell too far behind live: drop this connection so the
                    # loop below reopens at the live edge. Deliberately reuses
                    # the ordinary reconnect path (epoch bump, anchor reset,
                    # counters) rather than adding a second way to restart a
                    # stream -- a resync IS a discontinuity, and consumers
                    # already handle epochs correctly.
                    # Guarded on self.reconnect: under --no-reconnect there is
                    # nothing to reopen with, so breaking here would end the
                    # stream outright instead of resyncing it.
                    if (self.reconnect and self.max_drift_seconds
                            and self._anchor.drift_since_connect > self.max_drift_seconds):
                        self.resyncs += 1
                        break

                self._push((frame, pts_ms, self.epoch_id))

            cap.release()
            if not self.reconnect or self.stopped.is_set():
                break
            self.reconnects += 1

        self.connected.set()  # unblock open() even on failure
        self.finished.set()
        self.queue.put(_EOS)

    def _push(self, item):
        """Enqueue a (frame, pts_ms, epoch_id) item, discarding the oldest if
        we are behind."""
        try:
            self.queue.put_nowait(item)
        except queue.Full:
            try:
                self.queue.get_nowait()
                self.dropped += 1
            except queue.Empty:
                pass
            try:
                self.queue.put_nowait(item)
            except queue.Full:
                pass

    def poll(self, timeout=0.05):
        """Non-blocking-ish read. Returns (status, frame).

        status is one of:
            "frame"   - a frame is available
            "waiting" - nothing yet; the stream is mid-stall or reconnecting
            "eos"     - the stream is genuinely finished

        Callers must keep pumping their UI on "waiting". A stalled HLS segment
        can take 30s to time out, and a loop that blocks through that leaves the
        window unresponsive - keypresses and the close button included.

        On "frame", last_pts_ms/last_epoch_id/last_seen_at describe that same
        frame (last_seen_at is the best-known absolute UTC datetime, or None
        if the stream has never been successfully anchored yet).
        """
        try:
            item = self.queue.get(timeout=timeout)
        except queue.Empty:
            if self.stopped.is_set() or self.finished.is_set():
                return "eos", None
            return "waiting", None
        if item is _EOS:
            return "eos", None
        frame, pts_ms, epoch_id = item
        self.last_frame_at = time.time()
        self.last_pts_ms = pts_ms
        self.last_epoch_id = epoch_id
        self.last_seen_at = self._anchor.seen_at(pts_ms)
        return "frame", frame

    def read(self, timeout=None):
        """Blocking read. Returns the newest frame, or None when finished.

        An empty queue is not the end of the stream: a reconnect can legitimately
        take a minute. Waiting is only abandoned after `stall_timeout` of total
        silence, or once the reader thread has actually given up.
        """
        deadline = time.time() + (timeout if timeout is not None else self.stall_timeout)
        while True:
            status, frame = self.poll(timeout=1.0)
            if status == "frame":
                return frame
            if status == "eos":
                return None
            if time.time() >= deadline:
                self._error = "stream stalled"
                return None

    @property
    def waiting(self):
        """True when the reader is between connections."""
        return not self.finished.is_set() and self.queue.empty()

    def stop(self):
        self.stopped.set()
        try:
            while True:
                self.queue.get_nowait()
        except queue.Empty:
            pass
        self.thread.join(timeout=3.0)


def buffer_advice(width, height, buffer, infer_fps=20.0, segment_s=10.0):
    """Describe what a given buffer depth costs and covers.

    Frames arrive in 10s bursts and then stop. A buffer only smooths that gap if
    it holds enough frames to keep the consumer fed through it, and full-res
    frames are not cheap: 1280x960x3 is 3.7 MB each.
    """
    per_frame = width * height * 3 / 1e6  # MB
    needed = int(infer_fps * segment_s)
    return (f"~{per_frame * buffer:.0f} MB, covers {buffer / infer_fps:.1f}s "
            f"of the ~{segment_s:.0f}s segment gap (~{needed} frames covers it fully)")


# --------------------------------------------------------------------------
# Probing
# --------------------------------------------------------------------------

def probe(camera, seconds=0.0):
    """Check whether a camera's HLS stream opens and decodes.

    With `seconds > 0` the stream is sampled for that long and the delivered
    frame rate is measured. Throughput is what actually decides whether a camera
    is usable: streams on this network range from ~3 to ~22 FPS, and the slow
    ones stall for up to 30s at a time regardless of how fast inference is.
    """
    url = hls_url(camera)
    t0 = time.time()
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    open_s = time.time() - t0
    base = {"id": camera["id"], "seconds": open_s, "shape": None,
            "fps": None, "stalls": 0}

    if not cap.isOpened():
        cap.release()
        return {**base, "ok": False, "reason": "open failed"}

    success, frame = cap.read()
    if not success:
        cap.release()
        return {**base, "ok": False, "reason": "opened but no frame"}
    base["shape"] = frame.shape

    if seconds > 0:
        n, stalls = 1, 0
        start = last = time.time()
        while time.time() - start < seconds:
            success, _ = cap.read()
            now = time.time()
            if not success:
                break
            if now - last > 1.0:
                stalls += 1
            last = now
            n += 1
        elapsed = time.time() - start
        base["fps"] = n / elapsed if elapsed else 0.0
        base["stalls"] = stalls

    cap.release()
    return {**base, "ok": True, "reason": ""}


def probe_all(cameras, workers=8, seconds=0.0):
    import concurrent.futures as cf
    # Measuring throughput in parallel makes the streams compete for bandwidth
    # and understates every one of them, so timed probes run serially.
    if seconds > 0:
        return [probe(c, seconds) for c in cameras]
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(probe, cameras))


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Camera feed discovery")
    parser.add_argument("--list", action="store_true", help="List cameras from the API")
    parser.add_argument("--probe", action="store_true",
                        help="Test which cameras actually decode (slow)")
    parser.add_argument("--id", type=str, default=None, help="Restrict to one camera id")
    parser.add_argument("--seconds", type=float, default=0.0,
                        help="With --probe, sample each stream this long to "
                             "measure delivered FPS (e.g. 15). Runs serially.")
    args = parser.parse_args()

    if not (args.list or args.probe):
        args.list = True

    quiet_ffmpeg()
    cameras = fetch_cameras()
    if args.id:
        cameras = [c for c in cameras if str(c["id"]) == str(args.id)]
        if not cameras:
            print(f"No camera with id {args.id}")
            return

    if args.list:
        print(f"{len(cameras)} cameras\n")
        print(f"{'id':>4}  {'codec':6} {'resolution':12} {'fps':>6}  location")
        print("-" * 78)
        for c in cameras:
            dims = f"{c.get('width')}x{c.get('height')}" if c.get("width") else "-"
            print(f"{c['id']:>4}  {c.get('codec') or '-':6} {dims:12} "
                  f"{c.get('fps') or 0:>6.1f}  {c.get('location', '')[:38]}")

    if args.probe:
        mode = f", sampling {args.seconds:.0f}s each" if args.seconds else ""
        print(f"\nProbing {len(cameras)} streams{mode} (this takes a while)...\n")
        results = probe_all(cameras, seconds=args.seconds)
        by_id = {str(c["id"]): c for c in cameras}
        working = [r for r in results if r["ok"]]

        header = f"{'id':>4}  {'status':6} {'codec':6} {'decoded':12} {'open':>5}"
        if args.seconds:
            header += f" {'fps':>6} {'stalls':>7}"
        print(header + "  location")
        print("-" * (92 if args.seconds else 78))

        for r in sorted(results, key=lambda r: int(r["id"])):
            c = by_id[str(r["id"])]
            shape = f"{r['shape'][1]}x{r['shape'][0]}" if r["shape"] else r["reason"]
            line = (f"{r['id']:>4}  {'OK' if r['ok'] else 'FAIL':6} "
                    f"{c.get('codec') or '-':6} {shape:12} {r['seconds']:>5.1f}")
            if args.seconds:
                fps = f"{r['fps']:.1f}" if r["fps"] is not None else "-"
                line += f" {fps:>6} {r['stalls']:>7}"
            print(line + f"  {c.get('location', '')[:30]}")

        print(f"\n{len(working)}/{len(results)} streams decoded.")
        if working:
            ranked = sorted(working, key=lambda r: int(r["id"]))
            print("Working ids: " + " ".join(str(r["id"]) for r in ranked))
            if args.seconds:
                best = sorted((r for r in working if r["fps"]),
                              key=lambda r: -r["fps"])[:5]
                if best:
                    print("Fastest:     " + ", ".join(
                        f"{r['id']} ({r['fps']:.1f} fps)" for r in best))


if __name__ == "__main__":
    main()
