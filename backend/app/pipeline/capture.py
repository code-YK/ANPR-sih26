"""Stage 3 -- frame capture for ANPR-viability survey.

One still per camera, captured from the live RTSP source (falling back to
HLS), for a human to eyeball. Never transcode a recorded clip and probe
that -- it reports the local encoder's properties, not the camera's.
"""

import asyncio
import logging
import os
import subprocess

from app.config import get_settings
from app.models.camera import Camera

logger = logging.getLogger("sentinel.pipeline.capture")


async def _ffmpeg_grab(url: str, out_path: str, *, rtsp: bool, timeout_seconds: float) -> bool:
    args = ["ffmpeg", "-y"]
    if rtsp:
        args += ["-rtsp_transport", "tcp"]
    args += ["-i", url, "-frames:v", "1", out_path]

    try:
        # Same reason as probe.py: to_thread(subprocess.run), never
        # asyncio.create_subprocess_exec, which a Windows SelectorEventLoop
        # does not implement (AGENTS.md, docs/platform-notes.md).
        proc = await asyncio.to_thread(subprocess.run, args, capture_output=True, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        logger.info("ffmpeg frame capture timed out for %s transport", "RTSP" if rtsp else "HLS")
        if os.path.exists(out_path):
            os.remove(out_path)
        return False

    ok = proc.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0
    if not ok:
        logger.info(
            "ffmpeg frame capture failed for %s transport (exit %s; endpoint and stderr redacted)",
            "RTSP" if rtsp else "HLS",
            proc.returncode,
        )
    return ok


async def capture_survey_frame(camera: Camera) -> str | None:
    """Capture one still for `camera`. Returns the output path, or None on failure."""
    settings = get_settings()
    os.makedirs(settings.survey_dir, exist_ok=True)
    out_path = os.path.join(settings.survey_dir, f"cam{camera.camera_id}.jpg")

    if camera.rtsp_url:
        if await _ffmpeg_grab(
            camera.rtsp_url, out_path, rtsp=True, timeout_seconds=settings.ffmpeg_capture_timeout_seconds
        ):
            return out_path

    if camera.hls_url:
        if await _ffmpeg_grab(
            camera.hls_url, out_path, rtsp=False, timeout_seconds=settings.ffmpeg_capture_timeout_seconds
        ):
            return out_path

    return None


async def run_survey_capture(cameras: list[Camera]) -> dict[str, str | None]:
    results: dict[str, str | None] = {}
    for camera in cameras:
        results[camera.camera_id] = await capture_survey_frame(camera)
    return results
