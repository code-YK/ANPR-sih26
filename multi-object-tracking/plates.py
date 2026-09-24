"""
License plate detection, OCR and per-track confirmation
=======================================================
Wraps fast-alpr (MIT) and adds the things that make plate reading work on
CCTV footage rather than on clean benchmark images:

1. A SIZE GATE. OCR is only attempted on plate crops wide enough to resolve
   characters: 100 px for a single-row plate, 55 px for a two-row plate
   (two-wheelers, autos), whose characters are about twice as tall at the same
   width. A threshold sweep over recorded footage (2026-09-22) found that
   lowering the single-row gate to 90/80/70/60 px added no correct plate, only
   cost and wrong reads, while the two-row gate recovered legible 60 px auto
   plates. Vehicles too small to carry a readable plate are skipped before the
   detector runs; two-wheelers/autos are checked down to the two-row size.

2. PADDED OCR CROPS. The plate detector's box is tight and regularly clips
   the first or last character; OCR then returns a shorter string that can
   still look like a valid plate (UP14FS3664 read as UP14F5366, a clipped
   DL1LA?5612 read as DL1LA0561). OCR therefore runs on the detector box grown
   by PLATE_PAD on every side, cut from the full frame so the margin is not
   limited by the vehicle box. Measured on recorded government-mode footage:
   +37% exactly-right reads on the same plate crops.

3. A PER-CHARACTER, MULTI-FRAME VOTE. A single frame is unreliable, and so
   are two: one systematic misread (same crop geometry, same error every
   frame) produces two matching reads easily. A track's plate is CONFIRMED
   only when at least `min_votes` independent frames agree -- first on the
   plate's length, then on every character position, each by at least
   VOTE_SHARE of the quality-weighted vote (OCR confidence x sharpness x
   width) -- and the winner is a string OCR actually produced, never a
   character-by-character composite. One vote per frame; byte-identical crops
   (a repeated or stalled frame) count once. Measured end to end on recorded
   footage against hand-labelled plates (2026-09-22): on clips held out from
   the design, confirmed plates went from 5 correct + 1 wrong to 8 correct +
   0 wrong; on the design clips from 5 + 7 wrong to 14 + 0; same speed. It
   cannot catch a misread that repeats identically in every frame -- that
   needs a better OCR model, not a better vote.

4. A STRICT INDIAN GRAMMAR, applied to the read AS IS -- no character is ever
   coerced to make a read fit. A plate is valid when it is one of:
     * <state><2-digit district><0-3 series letters><4 digits>   UP14FS3664
     * Delhi: DL<1-2 digit district><1-3 letters><4 digits>       DL2CBB4791,
       DL7CZ1908, DL10CN7685 (category letter + series)
     * Bharat series: <2-digit year>BH<4 digits><1-2 letters>     22BH1234AA
   with a known state/UT code. Only Delhi issues 1-digit district codes, so a
   1-digit district elsewhere is an OCR slip (HR29BG7381 read as HR2SBG7381),
   not a plate. Series letters never include I or O, and Delhi's category
   letter is one of its issued categories, so DL10CN7685 read as DL1OCN7685
   or DL1DCN7685 is rejected rather than confirmed.

The confusable-pair repair (0/D, 8/B, 5/S...) is still used, but only to
produce a readable TENTATIVE string for display; it never contributes to a
confirmation.
"""

import hashlib
import os
import platform
import re
from collections import defaultdict
from typing import NamedTuple

import numpy as np

DEFAULT_MIN_PLATE_WIDTH = 100   # px of plate box width before OCR is attempted (single-row plate)
DEFAULT_MIN_PLATE_WIDTH_TWO_ROW = 55   # px for a two-row plate: its glyphs are ~2x taller
TWO_ROW_ASPECT = 2.2            # plate box w/h below this = two-row plate (measured: two clusters, gap at ~2.2)
TWO_ROW_CLASSES = frozenset({"motorcycle", "auto_rickshaw"})   # vehicles checked down to the two-row gate
DISPLAY_MIN_CHARS = 5           # shorter partial reads are fragments, not information
DEFAULT_MIN_CONF = 0.55         # per-read OCR confidence needed to vote at all
DEFAULT_MIN_VOTES = 3           # independent frames that must agree
PLATE_PAD = 0.08                # OCR crop margin, as a fraction of the plate box, per side
VOTE_SHARE = 0.75               # share of the weighted vote a length/character must win
RELATIVE_WIDTH = 0.6            # reads narrower than this x the track's widest do not vote


def _resolve_onnx_providers(device):
    """Provider priority list for the plate detector, by actual hardware.

    Found via `investigate` planning: this used to be `device == "cuda"
    else CPUExecutionProvider only`, and separately `build_reader` mapped
    ANY non-"cpu" device (including "mps") to "cuda" -- so on Apple Silicon
    the plate reader was told it was on CUDA, requested a provider that does
    not exist here, and silently fell back to CPU at the ~90ms/crop this
    module already warns about. CoreMLExecutionProvider was never in the
    list despite onnxruntime having it available.

    SENTINEL_FORCE_CPU_PLATES overrides all of the above to plain CPU.
    Found 2026-08-31: a worker spawned by the backend's own
    subprocess.Popen (app/routers/analytics.py's _start_worker) crashed
    with SIGABRT a few seconds into a run -- a macOS crash report showed
    an uncaught C++ exception inside onnxruntime's CoreML execution
    provider itself, not this project's Python code. Reproducing the
    identical subprocess.Popen call (same env, same stdin redirect, same
    cwd) standalone did not crash, repeatedly -- this looks like a
    load/timing-sensitive native CoreML bug specific to how/when the
    backend actually spawns workers, not something patchable here. The
    backend sets this env var for every worker it spawns; a manual/
    interactive invocation (this module's own dev/test use) leaves it
    unset and keeps CoreML's ~10ms/crop instead of CPU's ~90ms/crop.

    Found 2026-09-10: `device` here is whatever resolve_device() returned,
    and on CUDA hardware that is the torch/YOLO device-index convention
    ("0", "1", ...), never the literal string "cuda" -- so `device ==
    "cuda"` was false on every real GPU machine and this always fell
    through to plain CPUExecutionProvider, silently, exactly like the
    MPS bug above it was supposed to fix. is_cuda below treats anything
    that isn't "cpu" or "mps" as a CUDA device index, matching
    resolve_device()'s own contract.
    """
    if os.environ.get("SENTINEL_FORCE_CPU_PLATES") == "1":
        return ["CPUExecutionProvider"]
    is_cuda = device not in ("cpu", "mps")
    if is_cuda:
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    if platform.system() == "Darwin":
        return ["CoreMLExecutionProvider", "CPUExecutionProvider"]
    return ["CPUExecutionProvider"]


def enable_onnx_cuda():
    """Make torch's bundled CUDA/cuDNN DLLs visible to onnxruntime.

    onnxruntime-gpu does not ship CUDA itself and looks for the libraries on the
    DLL search path. Without this it finds nothing, prints an error most callers
    never see, and silently falls back to CPU - which cost ~90ms per crop here
    versus a few ms on GPU. Must run before any InferenceSession is created.

    Note the CUDA major version must match: onnxruntime-gpu 1.29 wants CUDA 13,
    while torch cu128 ships CUDA 12, so onnxruntime-gpu==1.22 is the pairing
    that works with this environment.
    """
    try:
        import torch
        lib = os.path.join(os.path.dirname(torch.__file__), "lib")
        if os.path.isdir(lib):
            os.add_dll_directory(lib)
            return True
    except Exception:
        pass
    return False


# --------------------------------------------------------------------------
# Plate grammar
# --------------------------------------------------------------------------

# Structural layout shared by every state: <2 letters><1-2 digits><0-3 letters><4 digits>.
# is_valid_indian() adds the state-code, district and letter rules on top of it.
INDIAN_PLATE_RE = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{4}$")
_PLATE_PARTS_RE = re.compile(r"^([A-Z]{2})([0-9]{1,2})([A-Z]{0,3})([0-9]{4})$")
# Bharat (BH) series: <2-digit registration year>BH<4 digits><1-2 letters>.
BH_PLATE_RE = re.compile(r"^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$")

# Series letters never include I or O (they would be confused with 1 and 0),
# so a read with either in a letter position is an OCR slip, not a plate.
SERIES_EXCLUDED = frozenset("IO")
# Delhi's category letter, the first letter after its district code
# (C cars, S two-wheelers, R autos/radio taxis, L/G trucks, P buses, ...).
DELHI_CATEGORIES = frozenset("ABCEFGKLMNPQRSTUVWYZ")

# State / union-territory registration codes, including the older codes still
# on the road (OR -> OD, UA -> UK, TS -> TG; DD and DN before their merger).
STATE_CODES = frozenset({
    "AN", "AP", "AR", "AS", "BR", "CG", "CH", "DD", "DL", "DN", "GA", "GJ",
    "HP", "HR", "JH", "JK", "KA", "KL", "LA", "LD", "MH", "ML", "MN", "MP",
    "MZ", "NL", "OD", "OR", "PB", "PY", "RJ", "SK", "TG", "TN", "TR", "TS",
    "UA", "UK", "UP", "WB",
})

# OCR confusions, by which direction the fix runs (tentative display only).
# A 0 in a letter position maps to D, not O: O is never issued, and 0/D is the
# confusion actually seen on these cameras (UP16CD5633 read as UP16C05633).
# 1 has no letter mapping for the same reason (I is never issued).
TO_LETTER = {"0": "D", "2": "Z", "4": "A", "5": "S", "6": "G", "8": "B"}
TO_DIGIT = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2",
            "A": "4", "S": "5", "G": "6", "B": "8", "T": "7"}


def normalise(text):
    """Uppercase and strip anything that cannot appear in a plate."""
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def is_valid_indian(text):
    """True when `text`, exactly as read, is a registrable Indian plate."""
    s = normalise(text)
    if BH_PLATE_RE.match(s):
        return not SERIES_EXCLUDED.intersection(s[8:])
    m = _PLATE_PARTS_RE.match(s)
    if not m:
        return False
    state, district, series, _number = m.groups()
    if state not in STATE_CODES or SERIES_EXCLUDED.intersection(series):
        return False
    if state == "DL":
        # Delhi: 1-2 digit district, then a category letter (+ series)
        return len(series) >= 1 and series[0] in DELHI_CATEGORIES
    return len(district) == 2


def _coerce(chars, mapping):
    """Map each character through `mapping`, counting how many changed."""
    out, edits = [], 0
    for ch in chars:
        if ch in mapping:
            out.append(mapping[ch])
            edits += 1
        else:
            out.append(ch)
    return "".join(out), edits


def repair_indian(text):
    """Coerce a noisy read into a valid Indian plate, for DISPLAY only.

    Returns (repaired, edits) or (None, None) when the string cannot plausibly
    be a plate. `edits` is how many characters had to be changed. A repaired
    string is a guess -- it is shown as tentative and never confirmed: a
    truncated `ZZ00AA123` "repairs" to a valid-looking `ZZ00A4123`, which would
    be inventing a vehicle.

    The structure is anchored at both ends - the first two characters are always
    letters and the last four always digits - so only the district/series split
    in the middle is ambiguous. Every valid split is scored and the cheapest one
    wins.
    """
    s = normalise(text)
    if not (8 <= len(s) <= 11):
        return None, None

    best = None
    for n_district in (1, 2):
        mid_len = len(s) - 2 - 4
        n_series = mid_len - n_district
        if not (0 <= n_series <= 3):
            continue

        state, e1 = _coerce(s[:2], TO_LETTER)
        district, e2 = _coerce(s[2:2 + n_district], TO_DIGIT)
        series, e3 = _coerce(s[2 + n_district:2 + mid_len], TO_LETTER)
        number, e4 = _coerce(s[-4:], TO_DIGIT)

        candidate = state + district + series + number
        edits = e1 + e2 + e3 + e4
        if is_valid_indian(candidate) and (best is None or edits < best[1]):
            best = (candidate, edits)

    return best if best else (None, None)


# --------------------------------------------------------------------------
# Per-track vote
# --------------------------------------------------------------------------

class PlateRead(NamedTuple):
    text: str          # normalised read, or its display repair when not valid as read
    confidence: float  # mean per-character OCR confidence
    width: int         # plate box width in source pixels (unpadded)
    edits: int         # 0 = valid exactly as read; >0 = repaired for display; 99 = not a plate
    sharpness: float   # Laplacian variance of the OCR crop
    frame: object      # frame index the read came from (None when unknown)


class PlateVote:
    """Accumulated plate reads for one track, resolved by a per-character vote."""

    __slots__ = ("reads", "best_width", "_frames", "_fingerprints")

    # A live track eventually leaves frame; an offline ingest run can watch
    # one parked vehicle for the whole recording, re-reading it every `every`
    # frames forever. Capped by evicting the lowest-confidence read, which is
    # the one least likely to change the vote anyway.
    MAX_READS = 24

    def __init__(self):
        self.reads = []
        self.best_width = 0
        self._frames = set()
        self._fingerprints = set()

    def add(self, text, confidence, width, *, frame=None, sharpness=1.0, fingerprint=None):
        """Record one read. Returns False when it is not an independent
        observation (same frame, or byte-identical crop) and was ignored."""
        if frame is not None:
            if frame in self._frames:
                return False
            self._frames.add(frame)
        if fingerprint is not None:
            if fingerprint in self._fingerprints:
                return False
            self._fingerprints.add(fingerprint)
        raw = normalise(text)
        if is_valid_indian(raw):
            shown, edits = raw, 0
        else:
            repaired, edits = repair_indian(raw)
            # Keep the raw read when repair fails: shown unvalidated beats
            # discarded, and it can never be confirmed either way.
            shown, edits = (repaired, edits) if repaired else (raw, 99)
        self.reads.append(PlateRead(shown, float(confidence), int(width), edits,
                                    float(sharpness), frame))
        self.best_width = max(self.best_width, int(width))
        if len(self.reads) > self.MAX_READS:
            self.reads.remove(min(self.reads, key=lambda r: r.confidence))
        return True

    def min_edits(self, text):
        """Fewest repairs any single read needed to produce `text`."""
        costs = [r.edits for r in self.reads if r.text == text]
        return min(costs) if costs else 99

    def mean_confidence(self, text):
        """Average OCR confidence of the reads that produced `text`."""
        matching = [r.confidence for r in self.reads if r.text == text]
        return sum(matching) / len(matching) if matching else None

    def consensus(self):
        """Best-supported string, confirmed or not: (text, score, n_reads).

        For display only (the tentative "?" label, an investigator's hint).
        Votes are weighted by OCR confidence, discounted by how many characters
        had to be forced to fit the plate format, with a modest bonus for
        reads that are valid as read.
        """
        if not self.reads:
            return None, 0.0, 0
        scores = defaultdict(float)
        counts = defaultdict(int)
        for r in self.reads:
            if not r.text:
                continue
            bonus = 1.5 if r.edits == 0 else 1.0
            scores[r.text] += r.confidence * bonus / (1.0 + r.edits)
            counts[r.text] += 1
        if not scores:
            return None, 0.0, 0
        best = max(scores, key=scores.get)
        return best, scores[best], counts[best]

    def confirmed(self, min_votes=DEFAULT_MIN_VOTES):
        """The confirmed plate: (text, mean_confidence, n_agreeing_reads), or
        (None, 0.0, n_voting_reads) while the vote is not settled.

        Only reads that are valid exactly as read take part. Reads narrower
        than RELATIVE_WIDTH of the track's widest valid read drop out -- once a
        vehicle has come close, its distant reads add noise, not evidence. The
        read length is voted first, so a truncated read can neither out-vote
        nor co-exist with the full plate; then every character position must
        win VOTE_SHARE of the quality-weighted vote with support from at least
        `min_votes` frames; and the winner must be a string that was actually
        read. Anything short of that abstains.
        """
        valid = [r for r in self.reads if r.edits == 0]
        if len(valid) < min_votes:
            return None, 0.0, len(valid)
        wmax = max(r.width for r in valid)
        valid = [r for r in valid if r.width >= RELATIVE_WIDTH * wmax]
        if len(valid) < min_votes:
            return None, 0.0, len(valid)
        smax = max(r.sharpness for r in valid) or 1.0

        def quality(r):
            return r.confidence * (0.5 + 0.5 * r.sharpness / smax) * (0.5 + 0.5 * r.width / wmax)

        by_length = defaultdict(float)
        for r in valid:
            by_length[len(r.text)] += quality(r)
        length, weight = max(by_length.items(), key=lambda kv: kv[1])
        if weight < VOTE_SHARE * sum(by_length.values()):
            return None, 0.0, len(valid)
        group = [r for r in valid if len(r.text) == length]
        if len(group) < min_votes:
            return None, 0.0, len(valid)

        chars = []
        for i in range(length):
            weights, support = defaultdict(float), defaultdict(int)
            for r in group:
                weights[r.text[i]] += quality(r)
                support[r.text[i]] += 1
            ch, w = max(weights.items(), key=lambda kv: kv[1])
            if w < VOTE_SHARE * sum(weights.values()) or support[ch] < min_votes:
                return None, 0.0, len(valid)
            chars.append(ch)
        text = "".join(chars)
        agreeing = [r for r in group if r.text == text]
        if not agreeing:
            return None, 0.0, len(valid)
        return text, sum(r.confidence for r in agreeing) / len(agreeing), len(agreeing)

    def best_evidence(self):
        """(raw_text, confidence, width) of this track's single
        highest-confidence read -- for Section 5's evidence-record
        requirement (raw OCR text, distinct from the confirmed `plate` a
        sighting reports). "Raw" here means before format-repair, not before
        normalise() -- reads are stored post-normalise already; capturing the
        true pre-normalise string would need a second field threaded through
        read_crop(), deferred as out of scope for what this evidence is
        actually for (showing an operator what OCR genuinely saw, not
        exact-byte forensics)."""
        if not self.reads:
            return None, 0.0, 0
        r = max(self.reads, key=lambda r: r.confidence)
        return r.text, r.confidence, r.width


# --------------------------------------------------------------------------
# Reader
# --------------------------------------------------------------------------

class PlateReader:
    """Detect and read plates inside vehicle crops.

    Detection runs on crops rather than whole frames, which is both faster and
    more accurate: the plate detector sees a much larger relative target, and
    the result is already associated with a vehicle track. OCR then reads the
    plate box padded by PLATE_PAD, cut from the full frame when it is known.
    """

    # A plate is at most roughly this fraction of the vehicle's box width - an
    # Indian plate is ~500mm on a ~1800mm-wide car, so ~0.28, and less than that
    # at any angle. Used as a generous upper bound to reject vehicles that
    # cannot possibly carry a legible plate, before paying for the model.
    MAX_PLATE_RATIO = 0.35

    def __init__(self, detector_model="yolo-v9-s-608-license-plate-end2end",
                 ocr_model="cct-s-v2-global-model", device="cuda",
                 min_plate_width=DEFAULT_MIN_PLATE_WIDTH, min_conf=DEFAULT_MIN_CONF,
                 min_crop_width=None, min_votes=DEFAULT_MIN_VOTES, pad=PLATE_PAD,
                 min_plate_width_two_row=DEFAULT_MIN_PLATE_WIDTH_TWO_ROW,
                 two_row_classes=TWO_ROW_CLASSES):
        is_cuda = device not in ("cpu", "mps")
        if is_cuda:
            enable_onnx_cuda()
        from fast_alpr import ALPR  # imported lazily; heavy and optional

        providers = _resolve_onnx_providers(device)
        # fast-alpr's OCR stage only understands "cuda"/"cpu"/"auto" for
        # ocr_device (a Literal, not a provider list); passing "auto" here
        # makes fast_plate_ocr resolve `ort.get_available_providers()`
        # itself, which already includes CoreML on this platform -- the
        # symmetric fix to `providers` above for the detector stage.
        #
        # SENTINEL_FORCE_CPU_PLATES must override *both* independently:
        # `providers` above only ever controlled the detector session, and
        # this line's "auto" still resolved to CoreML for the OCR session
        # regardless of it -- so the SIGABRT this override exists for
        # (see _resolve_onnx_providers's docstring) kept happening even
        # with the detector forced to CPU, because the OCR stage's own
        # CoreML session was the one actually crashing.
        force_cpu = os.environ.get("SENTINEL_FORCE_CPU_PLATES") == "1"
        ocr_device = "cuda" if is_cuda else ("cpu" if force_cpu else "auto")
        self.alpr = ALPR(
            detector_model=detector_model,
            ocr_model=ocr_model,
            ocr_device=ocr_device,
            detector_providers=providers,
        )
        self.min_plate_width = min_plate_width
        self.min_conf = min_conf
        self.min_votes = min_votes
        self.pad = pad
        # Derived rather than guessed: a vehicle narrower than this cannot show
        # a plate wide enough to clear min_plate_width, so running the detector
        # on it is guaranteed wasted work.
        self.min_crop_width = (min_crop_width if min_crop_width is not None
                               else int(min_plate_width / self.MAX_PLATE_RATIO))
        # Two-wheelers and autos carry two-row plates, readable at a smaller
        # width, so they are checked down to that size (see TWO_ROW_*).
        self.min_plate_width_two_row = min(min_plate_width_two_row, min_plate_width)
        self.two_row_classes = frozenset(two_row_classes or ())
        self.min_crop_width_two_row = min(self.min_crop_width,
                                          int(self.min_plate_width_two_row / self.MAX_PLATE_RATIO))
        self.votes = defaultdict(PlateVote)
        # Display only (the detector view): where each track's plate was last
        # seen, relative to its vehicle box, and its latest read -- including
        # partial or low-confidence reads that never vote.
        self.seen = {}

        self.skipped = 0       # crops rejected by the size pre-gate
        self.attempted = 0     # crops sent to the plate detector
        self.detected = 0      # plates localised
        self.accepted = 0      # reads that passed the size and confidence gates

    def providers(self):
        """What the detector session actually bound to (not what was asked for)."""
        try:
            return self.alpr.detector.detector.model.get_providers()
        except Exception:
            return ["unknown"]

    @staticmethod
    def _mean_conf(conf):
        if conf is None:
            return 0.0
        if hasattr(conf, "__len__"):
            return float(np.mean(conf)) if len(conf) else 0.0
        return float(conf)

    def _ocr_pixels(self, crop, box, frame, origin):
        """The plate box grown by `pad` per side, from the full frame when known."""
        x1, y1, x2, y2 = box
        px, py = int((x2 - x1) * self.pad), int((y2 - y1) * self.pad)
        if frame is not None:
            ox, oy = origin
            fh, fw = frame.shape[:2]
            return frame[max(0, oy + y1 - py):min(fh, oy + y2 + py),
                         max(0, ox + x1 - px):min(fw, ox + x2 + px)]
        ch, cw = crop.shape[:2]
        return crop[max(0, y1 - py):min(ch, y2 + py), max(0, x1 - px):min(cw, x2 + px)]

    def read_crop(self, crop, track_id, frame=None, origin=(0, 0), frame_index=None,
                  two_row_vehicle=False):
        """Detect and read plates in one vehicle crop; record the best read.

        `frame`/`origin` (the crop's top-left in `frame`) let the OCR margin
        extend past the vehicle box; `frame_index` makes the vote count one
        read per frame; `two_row_vehicle` (a two-wheeler/auto) lowers the
        vehicle pre-gate to the two-row plate size. Returns (text,
        confidence, width) for an accepted read, else None.
        """
        import cv2

        h, w = crop.shape[:2]
        # A vehicle this small cannot contain a legible plate; skip before the
        # model runs rather than paying for it and rejecting the output.
        if w < (self.min_crop_width_two_row if two_row_vehicle else self.min_crop_width) or h < 16:
            self.skipped += 1
            return None

        self.attempted += 1
        try:
            detections = self.alpr.detector.predict(crop)
        except Exception:
            return None

        best = shown = None
        for det in detections:
            self.detected += 1
            b = det.bounding_box
            box = (max(b.x1, 0), max(b.y1, 0), min(b.x2, w), min(b.y2, h))
            width = b.x2 - b.x1
            if box[2] <= box[0] or box[3] <= box[1]:
                continue
            rel = (box[0] / w, box[1] / h, box[2] / w, box[3] / h)
            if shown is None or det.confidence > shown["det"]:
                shown = dict(frame=frame_index, rel=rel, text=None, conf=0.0, det=det.confidence)
            # The width gate runs before OCR: a read below it would be
            # discarded anyway, so it is not worth the OCR call. Two-row
            # plates have their own, smaller gate.
            two_row = width / max(1, b.y2 - b.y1) < TWO_ROW_ASPECT
            if width < (self.min_plate_width_two_row if two_row else self.min_plate_width):
                continue
            pixels = self._ocr_pixels(crop, box, frame, origin)
            if not pixels.size:
                continue
            try:
                ocr = self.alpr.ocr.predict(pixels)
            except Exception:
                continue
            if ocr is None or not ocr.text:
                continue
            conf = self._mean_conf(ocr.confidence)
            # Any read is kept for display (a partial read is still useful to
            # an operator); only a confident one may vote.
            if shown["text"] is None or conf > shown["conf"]:
                shown = dict(frame=frame_index, rel=rel, text=normalise(ocr.text), conf=conf,
                             det=det.confidence)
            if conf < self.min_conf:
                continue
            # Prefer a read that is a valid plate as read, then confidence.
            key = (is_valid_indian(ocr.text), conf)
            if best is None or key > best[0]:
                best = (key, ocr.text, conf, width, pixels)

        if shown is not None:
            self.seen[track_id] = shown
        if best is None:
            return None

        _key, text, conf, width, pixels = best
        self.accepted += 1
        gray = cv2.cvtColor(pixels, cv2.COLOR_BGR2GRAY) if pixels.ndim == 3 else pixels
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        fingerprint = hashlib.blake2b(np.ascontiguousarray(pixels).tobytes(), digest_size=8).digest()
        self.votes[track_id].add(text, conf, width, frame=frame_index,
                                 sharpness=sharpness, fingerprint=fingerprint)
        return text, conf, width

    def consensus(self, track_id):
        """Best-known plate for a track, or (None, 0, 0)."""
        if track_id not in self.votes:
            return None, 0.0, 0
        return self.votes[track_id].consensus()

    def confirmed(self, track_id, min_votes=None):
        """Confirmed plate for a track (per-character multi-frame vote), or (None, ...)."""
        if track_id not in self.votes:
            return None, 0.0, 0
        return self.votes[track_id].confirmed(min_votes or self.min_votes)

    def best_evidence(self, track_id):
        """(raw_text, confidence, width) of this track's best individual
        read -- see PlateVote.best_evidence's docstring."""
        if track_id not in self.votes:
            return None, 0.0, 0
        return self.votes[track_id].best_evidence()

    def display(self, track_id, vehicle_xyxy):
        """What the detector view shows for a track: dict(text, confirmed, box)
        or None. `text` is the confirmed plate, else the best tentative or
        latest partial read with a trailing "?"; `box` is where the plate was
        last seen, projected onto the vehicle's current box (frame coords)."""
        text, _s, _n = self.confirmed(track_id)
        confirmed = text is not None
        seen = self.seen.get(track_id)
        if not confirmed:
            tentative, _s, _n = self.consensus(track_id)
            partial = seen["text"] if seen else None
            best = tentative or partial
            # A two- or three-character fragment tells an operator nothing and
            # just clutters the view; the plate box alone is shown instead.
            text = f"{best}?" if best and len(best) >= DISPLAY_MIN_CHARS else None
        box = None
        if seen is not None:
            vx1, vy1, vx2, vy2 = vehicle_xyxy
            rx1, ry1, rx2, ry2 = seen["rel"]
            vw, vh = vx2 - vx1, vy2 - vy1
            box = (vx1 + rx1 * vw, vy1 + ry1 * vh, vx1 + rx2 * vw, vy1 + ry2 * vh)
        if text is None and box is None:
            return None
        return dict(text=text, confirmed=confirmed, box=box)

    def read_vehicles(self, frame, boxes, track_ids, frame_count, every, class_names=None):
        """Run plate OCR on this frame's vehicle crops.

        Sampling is staggered by track id so a given vehicle is looked at every
        `every` frames while the per-frame cost stays spread out, rather than
        every vehicle landing on the same frame. `class_names` (one per box,
        optional) lets two-wheelers/autos use the smaller two-row plate gate.
        """
        h, w = frame.shape[:2]
        # Display memory is per live track; drop tracks long gone so a worker
        # that runs for days does not accumulate it.
        if frame_count % 300 == 0 and self.seen:
            for tid in [t for t, s in self.seen.items()
                        if s["frame"] is not None and frame_count - s["frame"] > 300]:
                del self.seen[tid]
        names = class_names if class_names is not None else [None] * len(track_ids)
        for box, track_id, name in zip(boxes, track_ids, names):
            if (frame_count + int(track_id)) % every:
                continue
            # A confirmed track's reported plate cannot change (callers
            # report on first confirmation and never again -- see
            # observation_worker.py's reported_tracks set), so further reads
            # only cost detector+OCR time. Negligible for a live stream the
            # vehicle will soon leave; real on a long offline ingest
            # watching one parked vehicle for the whole file.
            if self.confirmed(track_id)[0] is not None:
                continue
            x, y, bw, bh = box
            x1, y1 = max(0, int(x - bw / 2)), max(0, int(y - bh / 2))
            x2, y2 = min(w, int(x + bw / 2)), min(h, int(y + bh / 2))
            if x2 - x1 < 2 or y2 - y1 < 2:
                continue
            self.read_crop(frame[y1:y2, x1:x2], track_id, frame=frame,
                           origin=(x1, y1), frame_index=frame_count,
                           two_row_vehicle=name in self.two_row_classes)

    def progress(self, track_ids, limit=6, min_votes=None, class_names=None):
        """How far each in-frame vehicle's plate vote has got.

        This is what the detector view needs to show the reading *in
        progress* -- the counterpart to display(), which draws one label at
        the plate. Deliberately restricted to `track_ids` and capped at
        `limit`, unlike summary(), which walks every track the run has ever
        seen: this is published several times a second for the whole life of
        a worker, so it has to cost O(vehicles in frame), not O(vehicles
        ever). A track with no read yet is absent rather than reported empty.

        Every row is a *belief*, not a fact. Only `confirmed` rows have
        passed the per-character multi-frame vote; an unconfirmed `text` is
        the same tentative consensus the frame draws with a trailing "?"
        (the caller adds the marker, so the raw string stays usable). `votes`
        is how many independent valid reads are currently voting, against
        `min_votes` needed -- which is the honest "2 of 3 frames agree so
        far" an operator wants, and it can exceed min_votes while the
        per-character vote is still split. Nothing here is ever written to
        the observation store; only confirmed() feeds a sighting.
        """
        need = min_votes or self.min_votes
        rows = []
        # `class_names`, when given, is aligned with `track_ids` (one detector
        # class per box, as read_vehicles receives it), so a row can say what
        # it is a plate *of* -- "car #41" reads, "#41" does not.
        vehicle_of = dict(zip(track_ids, class_names)) if class_names else {}
        for track_id in track_ids:
            vote = self.votes.get(track_id)
            if vote is None or not vote.reads:
                continue
            text, confidence, votes = vote.confirmed(need)
            confirmed = text is not None
            if not confirmed:
                text, _score, _n = vote.consensus()
                confidence = vote.mean_confidence(text) if text else None
            rows.append({
                "track_id": int(track_id),
                "text": text,
                "confirmed": confirmed,
                "votes": int(votes),
                "min_votes": int(need),
                "reads": len(vote.reads),
                "valid": bool(text) and is_valid_indian(text),
                "edits": vote.min_edits(text) if text else 99,
                "confidence": round(float(confidence), 3) if confidence else None,
                "best_width": int(vote.best_width),
                "vehicle": vehicle_of.get(track_id),
            })
        # Closest to settled first: a confirmed plate, then whichever has the
        # most independent reads behind it. The cap then drops the vehicles
        # the model has barely looked at, not the one about to confirm.
        rows.sort(key=lambda r: (not r["confirmed"], -r["votes"], -r["reads"]))
        return rows[:limit]

    def summary(self, min_votes=None):
        """Resolved plates for every track, best-supported first."""
        rows = []
        for tid, vote in self.votes.items():
            text, score, n = vote.consensus()
            if not text:
                continue
            confirmed_text = vote.confirmed(min_votes or self.min_votes)[0]
            rows.append({
                "track_id": tid, "plate": confirmed_text or text, "score": score,
                "votes": n, "reads": len(vote.reads),
                "best_width": vote.best_width,
                "edits": vote.min_edits(text),
                "valid": is_valid_indian(confirmed_text or text),
                "confirmed": confirmed_text is not None,
            })
        return sorted(rows, key=lambda r: (not r["confirmed"], -r["score"]))


# --------------------------------------------------------------------------
# CLI wiring, shared by the file and live trackers
# --------------------------------------------------------------------------

def add_plate_args(parser):
    """Attach the plate options every vehicle tracker shares."""
    parser.add_argument(
        "--plates", action="store_true",
        help="Read number plates on tracked vehicles (needs fast-alpr)",
    )
    parser.add_argument(
        "--plate-every", type=int, default=3,
        help="Run plate OCR every Nth frame per vehicle (default: 3)",
    )
    parser.add_argument(
        "--min-plate-width", type=int, default=DEFAULT_MIN_PLATE_WIDTH,
        help="Skip OCR below this single-row plate width in px; below ~100 "
             f"reads are confident nonsense (default: {DEFAULT_MIN_PLATE_WIDTH})",
    )
    parser.add_argument(
        "--min-plate-width-two-row", type=int, default=DEFAULT_MIN_PLATE_WIDTH_TWO_ROW,
        help="Same gate for two-row plates (two-wheelers, autos), whose "
             f"characters are ~2x taller (default: {DEFAULT_MIN_PLATE_WIDTH_TWO_ROW})",
    )
    parser.add_argument(
        "--min-plate-conf", type=float, default=DEFAULT_MIN_CONF,
        help="Minimum OCR confidence for a read to vote (default: "
             f"{DEFAULT_MIN_CONF}); confirmation itself needs the multi-frame vote",
    )
    parser.add_argument(
        "--plate-votes", type=int, default=DEFAULT_MIN_VOTES,
        help="Independent frames that must agree, character by character, "
             f"before a plate is confirmed (default: {DEFAULT_MIN_VOTES})",
    )
    return parser


def build_reader(args, device, tag):
    """Construct a PlateReader from parsed args, or None when --plates is off."""
    if not getattr(args, "plates", False):
        return None
    print(f"[{tag}] Loading plate models (first run downloads ~30MB)...")
    # Pass the resolved device through UNCHANGED. This used to collapse
    # anything that wasn't literally "cpu" to "cuda" -- so "mps" (this
    # Mac's actual device, from resolve_device()) told the plate reader it
    # was on CUDA, which requested a provider that doesn't exist here and
    # fell back to CPU. PlateReader/_resolve_onnx_providers now handle
    # "cuda" vs. everything else correctly on their own.
    reader = PlateReader(
        device=device,
        min_plate_width=args.min_plate_width,
        min_conf=args.min_plate_conf,
        min_votes=getattr(args, "plate_votes", DEFAULT_MIN_VOTES),
        min_plate_width_two_row=getattr(args, "min_plate_width_two_row", DEFAULT_MIN_PLATE_WIDTH_TWO_ROW),
    )
    print(f"[{tag}] Plates:  every {args.plate_every} frames/vehicle, "
          f"min plate {reader.min_plate_width}px (two-row {reader.min_plate_width_two_row}px), "
          f"min conf {args.min_plate_conf}, confirm on {reader.min_votes} agreeing frames")
    providers = reader.providers()
    print(f"[{tag}] Plate ONNX: {providers} "
          f"(vehicle pre-gate {reader.min_crop_width}px, two-wheelers/autos "
          f"{reader.min_crop_width_two_row}px)")
    if providers == ["CPUExecutionProvider"]:
        print(f"[{tag}] NOTE: plate models are on CPU only (~90ms/crop). "
              f"On CUDA hardware: pip install onnxruntime-gpu==1.22.0. "
              f"On Apple Silicon, CoreMLExecutionProvider should already be "
              f"in the list above -- if it isn't, onnxruntime wasn't built "
              f"with CoreML support.")
    return reader


def print_summary(reader, tag):
    """Print the end-of-run plate table."""
    if reader is None:
        return
    rows = reader.summary()
    confirmed = [r for r in rows if r["confirmed"]]
    print(f"\n{'=' * 66}")
    print(f"[{tag}] Plate results")
    print(f"{'=' * 66}")
    print(f"  crops skipped (too small): {reader.skipped}")
    print(f"  crops sent to detector   : {reader.attempted}")
    print(f"  plates localised         : {reader.detected}")
    print(f"  reads passing gates      : {reader.accepted}")
    print(f"  tracks with a plate      : {len(rows)}")
    print(f"  CONFIRMED plates         : {len(confirmed)}")
    if rows:
        print(f"\n  {'track':>6} {'plate':>12} {'votes':>6} {'reads':>6} "
              f"{'width':>6} {'fixes':>6}  status")
        print("  " + "-" * 62)
        for r in rows:
            status = ("confirmed" if r["confirmed"]
                      else "tentative" if r["valid"] else "unvalidated")
            fixes = r["edits"] if r["edits"] < 99 else "-"
            print(f"  {r['track_id']:>6} {r['plate']:>12} {r['votes']:>6} "
                  f"{r['reads']:>6} {r['best_width']:>6} {str(fixes):>6}  {status}")
        print(f"\n  'confirmed' = {reader.min_votes}+ frames agreed on the length and on")
        print("  every character of a plate that was valid exactly as read.")
        print("  Anything else stays tentative by design: a repaired or")
        print("  single-frame read can look valid while being wrong.")
    print(f"{'=' * 66}")
