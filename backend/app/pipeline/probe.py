"""Stage 2 -- stream probe.

For each camera, attempt RTSP over TCP first, then fall back to HLS.
Records which transport actually connected so downstream consumers know
whether the reported properties came from the source or a re-packaged
fallback.
"""

import asyncio
import json
import logging
import subprocess
from datetime import datetime, timezone
from fractions import Fraction

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.camera import Camera, CameraHealthObservation
from app.schemas import ProbeResult, ProbeRunResult

logger = logging.getLogger("sentinel.pipeline.probe")


def _parse_frame_rate(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        return float(Fraction(raw))
    except (ZeroDivisionError, ValueError):
        return None


async def _ffprobe(url: str, *, rtsp: bool, timeout_seconds: float) -> dict | None:
    args = ["ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,width,height,r_frame_rate,bit_rate",
            "-of", "json"]
    if rtsp:
        args += ["-rtsp_transport", "tcp", "-timeout", str(int(timeout_seconds * 1_000_000))]
    args.append(url)

    try:
        # asyncio.to_thread + a blocking subprocess.run, never
        # asyncio.create_subprocess_exec (AGENTS.md, docs/platform-notes.md):
        # on a Windows SelectorEventLoop the latter raises a bare
        # NotImplementedError, which reached operators as a message-less 500
        # from "Probe stream now". subprocess.run also kills ffprobe when the
        # timeout expires; the old wait_for timeout left the child running.
        proc = await asyncio.to_thread(
            subprocess.run, args, capture_output=True, timeout=timeout_seconds + 5
        )
    except subprocess.TimeoutExpired:
        logger.info("ffprobe timed out for %s transport", "RTSP" if rtsp else "HLS")
        return None

    if proc.returncode != 0:
        logger.info(
            "ffprobe failed for %s transport (exit %s; endpoint and stderr redacted)",
            "RTSP" if rtsp else "HLS",
            proc.returncode,
        )
        return None

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None

    streams = data.get("streams") or []
    if not streams:
        return None
    return streams[0]


async def probe_camera(camera: Camera) -> ProbeResult:
    settings = get_settings()
    timeout = settings.ffprobe_timeout_seconds

    stream = None
    transport_ok = "none"
    error = None

    if camera.rtsp_url:
        stream = await _ffprobe(camera.rtsp_url, rtsp=True, timeout_seconds=timeout)
        if stream is not None:
            transport_ok = "rtsp"

    if stream is None and camera.hls_url:
        stream = await _ffprobe(camera.hls_url, rtsp=False, timeout_seconds=timeout)
        if stream is not None:
            transport_ok = "hls"

    if stream is None:
        error = "neither RTSP nor HLS produced a usable stream within the timeout"
        return ProbeResult(
            camera_id=camera.camera_id,
            transport_ok="none",
            codec=None,
            width=None,
            height=None,
            fps=None,
            bitrate_kbps=None,
            error=error,
        )

    bitrate = stream.get("bit_rate")
    bitrate_kbps = int(int(bitrate) / 1000) if bitrate not in (None, "N/A") else None

    return ProbeResult(
        camera_id=camera.camera_id,
        transport_ok=transport_ok,
        codec=stream.get("codec_name"),
        width=stream.get("width"),
        height=stream.get("height"),
        fps=_parse_frame_rate(stream.get("r_frame_rate")),
        bitrate_kbps=bitrate_kbps,
    )


async def run_stream_probe(session: AsyncSession, camera_id: str | None = None) -> ProbeRunResult:
    settings = get_settings()
    stmt = select(Camera)
    if camera_id is not None:
        stmt = stmt.where(Camera.camera_id == camera_id)
    cameras = (await session.execute(stmt)).scalars().all()
    if camera_id is not None and not cameras:
        raise ValueError(f"Camera {camera_id!r} not found")

    semaphore = asyncio.Semaphore(settings.probe_concurrency)

    async def bounded_probe(cam: Camera) -> ProbeResult:
        async with semaphore:
            return await probe_camera(cam)

    results = await asyncio.gather(*(bounded_probe(cam) for cam in cameras))

    now = datetime.now(timezone.utc)
    cameras_by_id = {c.camera_id: c for c in cameras}
    for result in results:
        cam = cameras_by_id[result.camera_id]
        cam.transport_ok = result.transport_ok
        cam.codec = result.codec
        cam.width = result.width
        cam.height = result.height
        cam.fps = result.fps
        cam.bitrate_kbps = result.bitrate_kbps
        cam.last_surveyed_at = now
        if result.transport_ok != "none":
            cam.last_successful_connect = now
        cam.health_reason = result.error
        session.add(
            CameraHealthObservation(
                camera_id=cam.camera_id,
                observed_at=now,
                status="healthy" if result.transport_ok != "none" else "offline",
                transport_ok=result.transport_ok,
                is_live=cam.is_live,
                reason=result.error,
            )
        )

    await session.commit()

    return ProbeRunResult(probed=len(results), results=list(results))
