"""
License plate detection, OCR and per-track consensus
====================================================
Wraps fast-alpr (MIT) and adds the three things that make plate reading work on
CCTV footage rather than on clean benchmark images:

1. A SIZE GATE. OCR is only attempted on plate crops wide enough to resolve
   characters. Measured on an approved local representative sample: plates
   >=110px read at 0.96-1.00 confidence and were correct, while plates <100px
   read at 0.38-0.65 and were garbage. Running OCR below the gate does not just
   waste time, it actively pollutes the vote with confident-looking nonsense.

2. PER-TRACK VOTING. A single frame is unreliable; a track is not. The same
   vehicle produced several one-character variations and truncations across
   five frames. Accumulating reads per track ID and taking a confidence-weighted
   vote recovers a stable answer from noisy parts.

3. FORMAT VALIDATION AND REPAIR. Indian plates have a rigid structure, so most
   OCR errors are provably impossible and the confusable pairs (0/O, 1/I, 6/G,
   8/B, 5/S) can be resolved by position without another model.
"""

import os
import platform
import re
from collections import defaultdict

import numpy as np


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

# Indian plate: <2 state letters><1-2 district digits><0-3 series letters><4 digits>
# Synthetic format examples: ZZ00A1234, YY01AB5678, XX9ABC0001
INDIAN_PLATE_RE = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{4}$")

# OCR confusions, by which direction the fix runs.
TO_LETTER = {"0": "O", "1": "I", "2": "Z", "4": "A", "5": "S", "6": "G", "8": "B"}
TO_DIGIT = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2",
            "A": "4", "S": "5", "G": "6", "B": "8", "T": "7"}


def normalise(text):
    """Uppercase and strip anything that cannot appear in a plate."""
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


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
    """Coerce a noisy read into the Indian plate format.

    Returns (repaired, edits) or (None, None) when the string cannot plausibly
    be a plate. `edits` is how many characters had to be changed, which the
    voter uses to prefer reads that needed less forcing.

    The structure is anchored at both ends - the first two characters are always
    letters and the last four always digits - so only the district/series split
    in the middle is ambiguous. Every valid split is scored and the cheapest one
    wins.
    """
    s = normalise(text)
    if not (8 <= len(s) <= 10):
        return None, None

    best = None
    # district digits take 1-2 characters; the series letters take the rest.
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
        if INDIAN_PLATE_RE.match(candidate) and (best is None or edits < best[1]):
            best = (candidate, edits)

    return best if best else (None, None)


def is_valid_indian(text):
    return bool(INDIAN_PLATE_RE.match(normalise(text)))


class PlateVote:
    """Accumulated plate reads for one track, resolved by weighted consensus."""

    __slots__ = ("reads", "best_width")

    # A live track eventually leaves frame; an offline ingest run can watch
    # one parked vehicle for the whole recording, re-reading it every `every`
    # frames forever. consensus()/confirmed() are O(len(reads)) and called
    # every frame per track, so an unbounded list is a real cost on a long
    # file. Capped by evicting the lowest-confidence read, which is the one
    # least likely to change consensus() anyway.
    MAX_READS = 20

    def __init__(self):
        self.reads = []          # (text, confidence, plate_width, edits)
        self.best_width = 0

    def add(self, text, confidence, width):
        raw = normalise(text)
        # A read that already matches the format needs no repair at all; that
        # distinction matters, because only unrepaired reads can be confirmed.
        if INDIAN_PLATE_RE.match(raw):
            repaired, edits = raw, 0
        else:
            repaired, edits = repair_indian(raw)
        # Keep the raw read when repair fails: a plate from another state format
        # would fail the Indian pattern, and discarding it entirely is worse
        # than reporting it unvalidated.
        self.reads.append((repaired or raw, confidence, width,
                           edits if repaired else 99))
        self.best_width = max(self.best_width, width)
        if len(self.reads) > self.MAX_READS:
            self.reads.remove(min(self.reads, key=lambda r: r[1]))

    def min_edits(self, text):
        """Fewest repairs any single read needed to produce `text`."""
        costs = [e for t, _, _, e in self.reads if t == text]
        return min(costs) if costs else 99

    def consensus(self):
        """Return (text, score, n_votes) or (None, 0, 0).

        Votes are weighted by OCR confidence, discounted by how many characters
        had to be forced to fit the plate format, and given a modest bonus for
        being format-valid.

        The bonus is deliberately a bonus and not an absolute preference. A hard
        "any valid read beats any invalid one" rule lets a single mis-repaired
        read win outright: synthetic `ZZ00AA123` is a truncated read that
        repairs to the valid-looking `ZZ00A4123` with one edit, and reporting it
        would be inventing a vehicle. Weighting instead means a wrong repair has
        to actually out-vote the alternatives.
        """
        if not self.reads:
            return None, 0.0, 0

        scores = defaultdict(float)
        counts = defaultdict(int)
        for text, conf, width, edits in self.reads:
            if not text:
                continue
            bonus = 1.5 if is_valid_indian(text) else 1.0
            scores[text] += conf * bonus / (1.0 + edits)
            counts[text] += 1

        if not scores:
            return None, 0.0, 0

        best = max(scores, key=scores.get)
        return best, scores[best], counts[best]

    def confirmed(self, min_votes=2):
        """Consensus corroborated by an UNREPAIRED, format-valid read.

        Requiring zero edits is the important part. Verified against ground
        truth on an approved representative sample: a synthetic ground-truth
        label `ZZ00AA1234` was read as `ZZ00AA123` (the OCR truncated the last
        digit) and then "repaired" into `ZZ00A4123` by flipping A->4. It
        collected five votes,
        because the truncation is systematic - the same crop geometry produces
        the same wrong read every frame - so corroboration alone cannot detect
        it. Only an exact, unforced format match should ever be reported as a
        fact; anything that needed coercion stays tentative.
        """
        text, score, votes = self.consensus()
        if (text and is_valid_indian(text) and votes >= min_votes
                and self.min_edits(text) == 0):
            return text, score, votes
        return None, score, votes

    def best_evidence(self):
        """(raw_text, confidence, width) of this track's single
        highest-confidence read -- for Section 5's evidence-record
        requirement (raw OCR text, distinct from the normalised/repaired
        `plate` a sighting reports). "Raw" here means before format-repair,
        not before normalise() -- reads are stored post-normalise already;
        capturing the true pre-normalise string would need a second field
        threaded through read_crop(), deferred as out of scope for what
        this evidence is actually for (showing an operator what OCR
        genuinely saw, not exact-byte forensics)."""
        if not self.reads:
            return None, 0.0, 0
        text, conf, width, _edits = max(self.reads, key=lambda r: r[1])
        return text, conf, width


class PlateReader:
    """Detect and read plates inside vehicle crops.

    Running on crops rather than whole frames is both faster and more accurate:
    the plate detector sees a much larger relative target, and the result is
    already associated with a vehicle track.
    """

    # A plate is at most roughly this fraction of the vehicle's box width - an
    # Indian plate is ~500mm on a ~1800mm-wide car, so ~0.28, and less than that
    # at any angle. Used as a generous upper bound to reject vehicles that
    # cannot possibly carry a legible plate, before paying for the model.
    MAX_PLATE_RATIO = 0.35

    def __init__(self, detector_model="yolo-v9-s-608-license-plate-end2end",
                 ocr_model="cct-s-v2-global-model", device="cuda",
                 min_plate_width=100, min_conf=0.80, min_crop_width=None):
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
        # Derived rather than guessed: a vehicle narrower than this cannot show
        # a plate wide enough to clear min_plate_width, so running the detector
        # on it is guaranteed wasted work.
        self.min_crop_width = (min_crop_width if min_crop_width is not None
                               else int(min_plate_width / self.MAX_PLATE_RATIO))
        self.votes = defaultdict(PlateVote)

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

    def read_crop(self, crop, track_id):
        """Run detection+OCR on one vehicle crop and record any accepted read.

        Returns (text, confidence, width) for an accepted read, else None.
        """
        h, w = crop.shape[:2]
        # A vehicle this small cannot contain a legible plate; skip before the
        # model runs rather than paying for it and rejecting the output.
        if w < self.min_crop_width or h < 16:
            self.skipped += 1
            return None

        self.attempted += 1
        try:
            results = self.alpr.predict(crop)
        except Exception:
            return None

        best = None
        for r in results:
            if r.detection is None:
                continue
            self.detected += 1
            box = r.detection.bounding_box
            width = box.x2 - box.x1
            ocr = r.ocr
            if ocr is None or not ocr.text:
                continue
            conf = self._mean_conf(ocr.confidence)

            # The two gates that keep nonsense out of the vote.
            if width < self.min_plate_width or conf < self.min_conf:
                continue
            if best is None or conf > best[1]:
                best = (ocr.text, conf, width)

        if best is None:
            return None

        self.accepted += 1
        self.votes[track_id].add(*best)
        return best

    def consensus(self, track_id):
        """Best-known plate for a track, or (None, 0, 0)."""
        if track_id not in self.votes:
            return None, 0.0, 0
        return self.votes[track_id].consensus()

    def confirmed(self, track_id, min_votes=2):
        """Corroborated, format-valid plate for a track, or (None, ...)."""
        if track_id not in self.votes:
            return None, 0.0, 0
        return self.votes[track_id].confirmed(min_votes)

    def best_evidence(self, track_id):
        """(raw_text, confidence, width) of this track's best individual
        read -- see PlateVote.best_evidence's docstring."""
        if track_id not in self.votes:
            return None, 0.0, 0
        return self.votes[track_id].best_evidence()

    def read_vehicles(self, frame, boxes, track_ids, frame_count, every):
        """Run plate OCR on this frame's vehicle crops.

        Sampling is staggered by track id so a given vehicle is looked at every
        `every` frames while the per-frame cost stays spread out, rather than
        every vehicle landing on the same frame.
        """
        h, w = frame.shape[:2]
        for box, track_id in zip(boxes, track_ids):
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
            self.read_crop(frame[y1:y2, x1:x2], track_id)

    def summary(self, min_votes=2):
        """Resolved plates for every track, best-supported first."""
        rows = []
        for tid, vote in self.votes.items():
            text, score, n = vote.consensus()
            if not text:
                continue
            edits = vote.min_edits(text)
            rows.append({
                "track_id": tid, "plate": text, "score": score,
                "votes": n, "reads": len(vote.reads),
                "best_width": vote.best_width,
                "edits": edits,
                "valid": is_valid_indian(text),
                "confirmed": bool(is_valid_indian(text) and n >= min_votes
                                  and edits == 0),
            })
        return sorted(rows, key=lambda r: -r["score"])


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
        "--min-plate-width", type=int, default=100,
        help="Skip OCR below this plate width in px; below ~100 reads are "
             "confident nonsense (default: 100)",
    )
    parser.add_argument(
        "--min-plate-conf", type=float, default=0.80,
        help="Minimum OCR confidence to count a read (default: 0.80)",
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
    )
    print(f"[{tag}] Plates:  every {args.plate_every} frames/vehicle, "
          f"min plate {args.min_plate_width}px, min conf {args.min_plate_conf}")
    providers = reader.providers()
    print(f"[{tag}] Plate ONNX: {providers} "
          f"(vehicle pre-gate {reader.min_crop_width}px)")
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
        print("\n  'confirmed' = unrepaired format match, seen 2+ times.")
        print("  Anything needing character fixes stays tentative by design:")
        print("  a repaired read can look valid while being wrong.")
    print(f"{'=' * 66}")
