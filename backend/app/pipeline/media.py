"""Recording ingestion: hashing, ffprobe metadata, and the CFR normalisation
pass every uploaded recording goes through before the ingest worker or a
browser ever touches it.

The normalisation pass is not an optimisation -- it eliminates a whole class
of bugs that only show up on real-world CCTV exports and would otherwise
corrupt the very thing this feature promises (frame-accurate bbox overlay):

  - Variable frame rate makes `frame_index / fps` drift, worst at the end of
    a clip -- the most confusing possible failure.
  - OpenCV's FFMPEG backend auto-rotates frames via the container's display
    matrix, but reports UNROTATED width/height, so any box computed against
    those dimensions is silently transposed.
  - A non-zero start PTS or an edit list offsets `video.currentTime` from
    frame_index/fps by a constant the browser and the worker would each
    compute differently.
  - Plenty of real CCTV/DVR exports are HEVC-in-mp4, MJPEG-in-AVI, or
    vendor-specific containers OpenCV decodes happily and no browser plays.

One ffmpeg pass to constant-frame-rate H.264/yuv420p with baked-in rotation
fixes all four at once, and is required for browser playback anyway.
"""

import asyncio
import hashlib
import json
import logging
import platform
from fractions import Fraction
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger("sentinel.pipeline.media")

# ffprobe/ffmpeg exit non-zero, or write nothing usable, in ways worth
# distinguishing so a rejected upload gets an honest reason.
class MediaError(Exception):
    pass


async def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    """Streaming hash so an upload never needs the whole file in memory
    twice. Runs in a thread since hashlib releases the GIL on large
    updates but file I/O here is otherwise blocking."""

    def _hash() -> str:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            while chunk := fh.read(chunk_size):
                h.update(chunk)
        return h.hexdigest()

    return await asyncio.to_thread(_hash)


async def probe_local_file(path: Path, *, timeout_seconds: float) -> dict:
    """ffprobe a LOCAL file (no RTSP/HLS transport flags -- see
    app/pipeline/probe.py for the live-camera prober this deliberately does
    not share code with, since local files need no transport negotiation).

    Returns the raw first-video-stream dict plus top-level `duration` and
    `nb_frames` folded in from `format`/`stream`. Raises MediaError with a
    reason suitable for `recordings.reject_reason` on any failure -- an
    unreadable upload is a normal occurrence (wrong file type, corrupt
    download), not a server bug.
    """
    args = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,r_frame_rate,nb_frames:format=duration",
        "-of", "json", str(path),
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        raise MediaError("ffprobe timed out reading this file") from exc

    if proc.returncode != 0:
        raise MediaError(f"ffprobe could not read this file: {stderr.decode(errors='replace')[:300]}")

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise MediaError("ffprobe returned unparseable output") from exc

    streams = data.get("streams") or []
    if not streams:
        raise MediaError("no video stream found in this file")
    stream = streams[0]

    fmt = data.get("format") or {}
    duration = fmt.get("duration")
    try:
        duration_seconds = float(duration) if duration is not None else None
    except ValueError:
        duration_seconds = None

    return {
        "codec_name": stream.get("codec_name"),
        "width": stream.get("width"),
        "height": stream.get("height"),
        "r_frame_rate": stream.get("r_frame_rate"),
        "nb_frames": stream.get("nb_frames"),
        "duration_seconds": duration_seconds,
    }


def parse_frame_rate_fraction(raw: str | None) -> Fraction | None:
    """Exact numerator/denominator, not a lossy float -- `frame_index/fps`
    must be reproducible identically by the worker and by anything that
    later re-derives timing, which a rounded float cannot guarantee."""
    if not raw:
        return None
    try:
        frac = Fraction(raw)
    except (ZeroDivisionError, ValueError):
        return None
    # NaN/inf never reach here via Fraction(str), but a zero-valued rate
    # (some corrupt files report "0/0" -> ZeroDivisionError already caught,
    # or "0/1") is still meaningless as a frame rate.
    if frac <= 0:
        return None
    return frac


def _default_encoder() -> str:
    # VideoToolbox is hardware-accelerated on Apple Silicon and is a small
    # fraction of the inference job's cost; libx264 is the portable
    # fallback everywhere else (including the team's CUDA box, where the
    # GPU is better spent on inference than on encoding this one pass).
    return "h264_videotoolbox" if platform.system() == "Darwin" else "libx264"


async def normalise_video(
    input_path: Path,
    output_path: Path,
    *,
    target_fps: Fraction,
    timeout_seconds: float,
) -> None:
    """One ffmpeg pass to constant frame rate, yuv420p, baked-in rotation,
    zero start PTS, H.264, +faststart. See module docstring for why each of
    these matters. Raises MediaError on failure or timeout."""
    encoder = _default_encoder()
    fps_str = f"{target_fps.numerator}/{target_fps.denominator}"
    args = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-map", "0:v:0",
        "-c:v", encoder,
        "-fps_mode", "cfr", "-r", fps_str,
        # Explicit tv (limited) range: a still-image-derived source (JPEG is
        # full-range by convention) otherwise carries that tag through and
        # h264_videotoolbox labels the output yuvj420p instead of yuv420p --
        # same pixel format, but some browsers/players are pickier about the
        # "j" variant, so pin it to the standard broadcast-range tag.
        "-color_range", "tv",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-an",
        str(output_path),
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        raise MediaError("ffmpeg normalisation timed out") from exc

    if proc.returncode != 0 or not output_path.exists():
        raise MediaError(f"ffmpeg normalisation failed: {stderr.decode(errors='replace')[:500]}")
