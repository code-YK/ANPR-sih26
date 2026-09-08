"""
Shared machinery for the tracking scripts
=========================================
Device resolution, threaded video decode, drawing primitives and timing.

Kept deliberately small: these are the pieces that were duplicated (and
independently wrong) across car_tracking.py, person_tracking.py and
compare_car_tracking.py.
"""

import queue
import threading
import time
from collections import deque

import cv2
import torch

# Largest edge of the display window; frames are downscaled to this for imshow
# only, so inference always sees the full-resolution frame.
DISPLAY_MAX_WIDTH = 1280


# --------------------------------------------------------------------------
# Arguments
# --------------------------------------------------------------------------

def add_common_args(parser, default_model="yolo11x.pt", default_trail=50):
    """Attach the arguments every tracking script shares."""
    parser.add_argument(
        "--model", type=str, default=default_model,
        help=f"YOLO model checkpoint (default: {default_model})",
    )
    parser.add_argument(
        "--tracker", type=str, default="bytetrack.yaml",
        help="Tracker config file (default: bytetrack.yaml)",
    )
    parser.add_argument(
        "--conf", type=float, default=0.3,
        help="Detection confidence threshold (default: 0.3)",
    )
    parser.add_argument(
        "--imgsz", type=int, default=960,
        help="Inference resolution; frames are letterboxed to this (default: 960)",
    )
    parser.add_argument(
        "--device", type=str, default=None,
        help="Inference device, e.g. 0 or cpu (default: cuda if available)",
    )
    parser.add_argument(
        "--no-half", action="store_true",
        help="Disable FP16 inference (FP16 is on by default on CUDA)",
    )
    parser.add_argument(
        "--vid-stride", type=int, default=1,
        help="Process every Nth frame (default: 1)",
    )
    parser.add_argument(
        "--trail-length", type=int, default=default_trail,
        help=f"Number of trail points to draw (default: {default_trail})",
    )
    parser.add_argument(
        "--benchmark", action="store_true",
        help="Skip display and drawing, report pure inference throughput",
    )
    return parser


# --------------------------------------------------------------------------
# Device
# --------------------------------------------------------------------------

def resolve_device(requested=None):
    """Pick the inference device and warn loudly if CUDA is unavailable.

    A CPU-only torch wheel is silent at import time and only shows up as
    mysteriously slow inference, so it is called out explicitly here.
    """
    if requested is not None:
        return requested
    if torch.cuda.is_available():
        return "0"
    if torch.backends.mps.is_available():
        return "mps"
    print("!" * 62)
    print("! WARNING: CUDA is not available - running on CPU.")
    print(f"!          torch build: {torch.__version__}")
    if "+cpu" in torch.__version__:
        print("!          This is a CPU-only wheel. Reinstall with:")
        print("!            pip install --force-reinstall --index-url \\")
        print("!              https://download.pytorch.org/whl/cu128 torch torchvision")
    print("!" * 62)
    return "cpu"


def resolve_quantize(no_half, device):
    """Return the Ultralytics `quantize` scheme: 16 for FP16, None for FP32.

    Ultralytics 8.4 deprecated the `half` flag in favour of a unified
    `quantize` value, and warns once per call if the old one is used.
    """
    half = (not no_half) and device != "cpu"
    return (16 if half else None), half


def describe(tag, source, args, device, half):
    print(f"[{tag}] Source:  {source}")
    print(f"[{tag}] Model:   {args.model}")
    print(f"[{tag}] Tracker: {args.tracker}")
    print(f"[{tag}] Device:  {device} (fp16={half}, imgsz={args.imgsz})")


# --------------------------------------------------------------------------
# Video input
# --------------------------------------------------------------------------

class FrameReader:
    """Decode frames on a worker thread so decoding overlaps with inference.

    OpenCV's read() is blocking and costs real time on high-resolution video.
    Running it alongside inference rather than in front of it keeps the GPU fed.
    """

    def __init__(self, source, queue_size=8, stride=1):
        if isinstance(source, str) and source.isdigit():
            source = int(source)
        self.cap = cv2.VideoCapture(source)
        self.queue = queue.Queue(maxsize=queue_size)
        self.stride = max(1, stride)
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._reader, daemon=True)

    def is_opened(self):
        return self.cap.isOpened()

    @property
    def width(self):
        return int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))

    @property
    def height(self):
        return int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    @property
    def fps(self):
        return self.cap.get(cv2.CAP_PROP_FPS) or 30.0

    def start(self):
        self.thread.start()
        return self

    def _reader(self):
        index = -1
        while not self.stopped.is_set():
            success, frame = self.cap.read()
            if not success:
                break
            index += 1
            if index % self.stride:
                continue
            # Block rather than drop: for file sources every frame matters.
            while not self.stopped.is_set():
                try:
                    self.queue.put(frame, timeout=0.1)
                    break
                except queue.Full:
                    continue
        self.queue.put(None)  # sentinel

    def read(self):
        """Return the next frame, or None once the source is exhausted."""
        return self.queue.get()

    def stop(self):
        self.stopped.set()
        # Drain so the reader thread is not parked on a full queue.
        try:
            while True:
                self.queue.get_nowait()
        except queue.Empty:
            pass
        self.thread.join(timeout=1.0)
        self.cap.release()


def new_trail(maxlen):
    """A trail buffer that discards old points for free."""
    return deque(maxlen=maxlen)


# --------------------------------------------------------------------------
# Drawing
# --------------------------------------------------------------------------

def draw_label(frame, x1, y1, color, label, sublabel=None):
    """Draw a filled label block anchored above (x1, y1)."""
    (tw1, th1), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
    if sublabel is None:
        cv2.rectangle(frame, (x1, y1 - th1 - 10), (x1 + tw1, y1), color, -1)
        cv2.putText(frame, label, (x1, y1 - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1, cv2.LINE_AA)
        return

    (tw2, th2), _ = cv2.getTextSize(sublabel, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
    max_tw = max(tw1, tw2)
    total_th = th1 + th2 + 15
    cv2.rectangle(frame, (x1, y1 - total_th), (x1 + max_tw + 10, y1), color, -1)
    cv2.putText(frame, label, (x1 + 5, y1 - th2 - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.putText(frame, sublabel, (x1 + 5, y1 - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (30, 30, 30), 1, cv2.LINE_AA)


def draw_trail(frame, track, color):
    """Draw a fading trail through `track`.

    LINE_8 rather than LINE_AA: antialiasing every segment for every object is
    a measurable cost at high resolution and is not visible at these widths.
    """
    n = len(track)
    for i in range(1, n):
        alpha = i / n
        thickness = int(2 + 3 * alpha)
        faded = (int(color[0] * alpha), int(color[1] * alpha), int(color[2] * alpha))
        pt1 = (int(track[i - 1][0]), int(track[i - 1][1]))
        pt2 = (int(track[i][0]), int(track[i][1]))
        cv2.line(frame, pt1, pt2, faded, thickness, cv2.LINE_8)


def xywh_to_corners(box):
    """Ultralytics xywh (centre form) -> integer (x1, y1, x2, y2)."""
    x, y, bw, bh = box
    return (int(x - bw / 2), int(y - bh / 2), int(x + bw / 2), int(y + bh / 2))


def unpack_tracks(result):
    """Pull boxes/ids/classes/confs off a result, or return empty lists.

    Ultralytics keeps these on-device; pulling them once here avoids repeated
    host syncs in the caller's loop.
    """
    if not result.boxes or result.boxes.id is None:
        return [], [], [], []
    return (
        result.boxes.xywh.cpu().numpy(),
        result.boxes.id.int().cpu().tolist(),
        result.boxes.cls.int().cpu().tolist(),
        result.boxes.conf.cpu().tolist(),
    )


def display_scale_for(width):
    """Scale factor to fit `width` inside the display window."""
    return min(1.0, DISPLAY_MAX_WIDTH / width) if width else 1.0


def show(window_name, frame, scale):
    if scale < 1.0:
        frame = cv2.resize(frame, None, fx=scale, fy=scale,
                           interpolation=cv2.INTER_NEAREST)
    cv2.imshow(window_name, frame)


def open_window(name, width=1280, height=720):
    cv2.namedWindow(name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(name, width, height)


def window_closed(name):
    """True once the user has dismissed the window with its close button.

    waitKey never reports the close button, so a loop that only checks for 'q'
    keeps running against a window that is no longer there.
    """
    try:
        return cv2.getWindowProperty(name, cv2.WND_PROP_VISIBLE) < 1
    except cv2.error:
        return True


def should_quit(window_name, delay=1, keys=("q",)):
    """Pump the UI event loop and report whether the user asked to stop.

    Must be called even on frames that produced nothing to draw: it is what
    keeps the window responsive during a stalled stream.
    """
    key = cv2.waitKey(delay) & 0xFF
    if key != 255 and chr(key) in keys:
        return True
    if key == 27:  # Esc
        return True
    return window_closed(window_name)


def draw_hud(frame, lines, translucent=False):
    """Draw HUD text lines at the top-left."""
    if translucent:
        overlay = frame.copy()
        cv2.rectangle(overlay, (5, 5), (320, 10 + 30 * len(lines)), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)
    for i, line in enumerate(lines):
        cv2.putText(frame, line, (15, 30 + 30 * i),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2, cv2.LINE_AA)


# --------------------------------------------------------------------------
# Timing
# --------------------------------------------------------------------------

class Timing:
    """Tracks wall-clock and inference-only throughput."""

    def __init__(self):
        self.frames = 0
        self.infer = 0.0
        self.start = time.perf_counter()
        self._t0 = None

    def __enter__(self):
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.infer += time.perf_counter() - self._t0
        return False

    def tick(self):
        self.frames += 1

    @property
    def elapsed(self):
        return time.perf_counter() - self.start

    @property
    def fps(self):
        e = self.elapsed
        return self.frames / e if e else 0.0

    @property
    def infer_fps(self):
        return self.frames / self.infer if self.infer else 0.0

    def report(self, tag):
        print(f"\n[{tag}] Done - {self.frames} frames in {self.elapsed:.1f}s")
        if self.frames:
            print(f"  End-to-end:      {self.fps:.1f} FPS")
            print(f"  Inference only:  {self.infer_fps:.1f} FPS "
                  f"({self.infer / self.frames * 1000:.1f} ms/frame)")
