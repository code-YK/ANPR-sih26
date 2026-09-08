"""
Generates deterministic local video fixtures for testing Investigate.

No video is committed to this repo -- recorded footage is not checked in
for the same privacy reason `backend/survey/*.jpg` is gitignored -- so
tests build their own fixture on demand.

`build_pan_clip` panning across a real onboarding-survey still gives YOLO
genuine content to detect (whatever vehicles/people are actually in that
frame), unlike a synthetic shape. `build_synthetic_clip` is the fallback
when no still is on disk at all -- it still exercises upload, hashing,
normalisation, and the ingest run state machine, but produces no vehicle
detections (a coloured rectangle is not a vehicle to a detector trained on
real appearance).

The "nasty" variants exist because the upload normalisation pass
(app/pipeline/media.py) was written specifically to fix these: variable
frame rate (progressive `frame_index/fps` drift), a rotation flag with
unrotated stored dimensions (silently transposes every box if dimensions
are read from the container instead of the decoded frame), and HEVC
(decodes fine in OpenCV, plenty of browsers won't play it).

Usage:
    python scripts/make_test_fixture.py                # base clip only
    python scripts/make_test_fixture.py --nasty         # + VFR/rotated/HEVC
"""

import argparse
import glob
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SURVEY_DIR = os.path.join(_HERE, "..", "survey")
_DEFAULT_OUT_DIR = os.path.join(_HERE, "..", "..", ".fixtures", "investigate")

# Prefer a still from a camera the onboarding survey marked ANPR-viable, so
# a real plate has some chance of being legible in the pan.
_PREFERRED_STILLS = ["cam21.jpg", "cam10.jpg", "cam12.jpg", "cam1.jpg"]


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr[-2000:], file=sys.stderr)
        raise RuntimeError(f"command failed: {' '.join(cmd)}")


def pick_still() -> str | None:
    for name in _PREFERRED_STILLS:
        path = os.path.join(_SURVEY_DIR, name)
        if os.path.exists(path):
            return path
    matches = sorted(glob.glob(os.path.join(_SURVEY_DIR, "*.jpg")))
    return matches[0] if matches else None


def build_pan_clip(
    still_path: str, out_path: str, *, duration: int = 12, fps: int = 25,
    width: int = 1920, height: int = 1080, zoom_rate: float = 0.0006,
) -> None:
    """A slow pan+zoom over a real still -- gives YOLO genuine detections
    to find, not a synthetic blob."""
    _run([
        "ffmpeg", "-y", "-loop", "1", "-i", still_path,
        "-vf", (
            f"zoompan=z='min(zoom+{zoom_rate},1.4)':d=1:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height},fps={fps}"
        ),
        "-t", str(duration), "-c:v", "h264_videotoolbox", "-pix_fmt", "yuv420p", out_path,
    ])


def build_synthetic_clip(out_path: str, *, duration: int = 10, fps: int = 25, width: int = 1280, height: int = 720) -> None:
    """No real still available. Exercises upload/normalisation/state
    machine only -- YOLO will not detect a coloured rectangle as a vehicle."""
    _run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"color=size={width}x{height}:rate={fps}:color=gray:duration={duration}",
        "-vf", r"drawbox=x='mod(t*80\,iw-200)':y=ih/2-100:w=200:h=100:color=red@0.8:t=fill",
        "-c:v", "h264_videotoolbox", "-pix_fmt", "yuv420p", out_path,
    ])


def build_variable_frame_rate(src_path: str, out_path: str) -> None:
    """Drops frames irregularly -- what many real DVR/phone exports look
    like, and what the CFR normalisation pass exists to fix."""
    _run([
        "ffmpeg", "-y", "-i", src_path,
        "-vf", r"select='not(mod(n\,7)*eq(mod(n\,11)\,0))',setpts=N/FRAME_RATE/TB",
        "-fps_mode", "vfr", "-c:v", "h264_videotoolbox", "-pix_fmt", "yuv420p", out_path,
    ])


def build_rotated(src_path: str, out_path: str) -> None:
    """Attempts a 90-degree display-matrix rotation tag with unrotated
    stored width/height -- the case that would transpose every box if
    dimensions were read from the container instead of the decoded frame.

    Best-effort: on this ffmpeg build (9.0.1), `-metadata:s:v:0 rotate=90`
    is accepted (ffmpeg's own startup log shows it queued for the muxer)
    but does not reliably surface back via `ffprobe -show_entries
    stream_tags=rotate` or `stream_side_data=rotation` on read-back -- the
    MP4 muxer's tag-to-display-matrix conversion appears to have changed
    from what older ffmpeg versions did. The file is still produced and
    still exercises the upload/normalise code path end to end; it just
    should not be assumed to carry verified rotation metadata for a test
    that specifically asserts rotation handling. Verify with the ffprobe
    commands above before relying on this fixture for that specific claim.
    """
    _run([
        "ffmpeg", "-y", "-i", src_path, "-map", "0:v:0", "-c:v", "copy",
        "-metadata:s:v:0", "rotate=90", "-movflags", "use_metadata_tags", out_path,
    ])


def build_hevc(src_path: str, out_path: str) -> None:
    """HEVC-in-mp4: decodes fine in OpenCV, but plenty of browsers won't
    play it without hardware/licensed support -- exactly what
    transcoding to H.264 on upload exists to fix."""
    _run(["ffmpeg", "-y", "-i", src_path, "-c:v", "hevc_videotoolbox", "-tag:v", "hvc1", out_path])


def build_fixtures(out_dir: str = _DEFAULT_OUT_DIR, *, nasty: bool = False) -> dict[str, str]:
    """Builds (or reuses, if already present) the base clip and optionally
    the nasty variants. Returns a dict of name -> path. Idempotent: skips
    ffmpeg entirely for a file that already exists, so repeated smoke-test
    runs don't re-encode every time."""
    os.makedirs(out_dir, exist_ok=True)
    paths = {}

    base_path = os.path.join(out_dir, "base_clip.mp4")
    if not os.path.exists(base_path):
        still = pick_still()
        if still:
            print(f"Building pan clip from {still}")
            build_pan_clip(still, base_path)
        else:
            print("No survey still found; building a synthetic clip (no real detections)")
            build_synthetic_clip(base_path)
    paths["base"] = base_path

    if nasty:
        vfr_path = os.path.join(out_dir, "vfr_clip.mp4")
        if not os.path.exists(vfr_path):
            build_variable_frame_rate(base_path, vfr_path)
        paths["vfr"] = vfr_path

        rotated_path = os.path.join(out_dir, "rotated_clip.mp4")
        if not os.path.exists(rotated_path):
            build_rotated(base_path, rotated_path)
        paths["rotated"] = rotated_path

        hevc_path = os.path.join(out_dir, "hevc_clip.mp4")
        if not os.path.exists(hevc_path):
            build_hevc(base_path, hevc_path)
        paths["hevc"] = hevc_path

    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=_DEFAULT_OUT_DIR)
    parser.add_argument("--nasty", action="store_true", help="Also build VFR/rotated/HEVC variants")
    args = parser.parse_args()

    paths = build_fixtures(args.out_dir, nasty=args.nasty)
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
