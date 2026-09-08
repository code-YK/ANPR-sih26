"""Local MediaMTX relay for low-latency WebRTC/WHEP preview.

The relay prefers a camera's RTSP endpoint and forces TCP; when only HLS is
available it uses that instead. FFmpeg republishes the selected source into
a local MediaMTX RTSP path, and MediaMTX serves real WHEP/WebRTC to the
focused frontend player. Raw source URLs stay inside the backend process.

Mirrors the lifecycle pattern already used twice in this codebase
(analytics.py's worker manifest/orphan-kill/supervisor tick, and
investigate.py's separate ingest manifest+supervisor) -- its own manifest
file, its own tick, deliberately not merged with either. Two kinds of
process share one manifest here: exactly one MediaMTX instance, and up to
`max_concurrent_webrtc_relays` per-camera ffmpeg relays.

Everything MediaMTX exposes (RTSP ingest, WHEP, its control API) is bound to
127.0.0.1 only. That is enough for this project's current same-machine
dev/demo topology, but it means the WebRTC *media* plane (unlike the
WHEP signaling, which the router proxies and RBAC-gates same as HLS) is not
tunnelled through the backend -- a browser on a different host could never
reach it. See docs/webrtc-relay-testing.md.
"""

import asyncio
import contextlib
import json
import logging
import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import get_settings

logger = logging.getLogger("sentinel.webrtc_relay")

_REPO_ROOT = Path(__file__).resolve().parents[3]
# Same directory analytics.py and investigate.py already use and that is
# already gitignored (multi-object-tracking/worker_logs/) -- reused here
# rather than inventing a second runtime directory with its own gitignore
# entry, even though this module has no ML dependency of its own.
_LOG_DIR = _REPO_ROOT / "multi-object-tracking" / "worker_logs"
_MANIFEST_PATH = _LOG_DIR / "webrtc_manifest.json"
_MEDIAMTX_CONFIG_PATH = _LOG_DIR / "mediamtx.yml"

SUPERVISOR_INTERVAL_SECONDS = 15.0
_SHUTDOWN_GRACE_SECONDS = 3.0


def _mediamtx_config(settings) -> str:
    return f"""\
logLevel: warn
logDestinations: [file]
logFile: {_LOG_DIR / "mediamtx.log"}

rtsp: yes
rtspAddress: 127.0.0.1:{settings.mediamtx_rtsp_port}
rtspTransports: [tcp]
rtmp: no
hls: no
srt: no
# Enabled by default and auto-generates a self-signed cert (auto.crt/
# auto.key) in the process's cwd the moment mediamtx starts, even though
# nothing here uses it -- unused surface, turned off explicitly.
moq: no

webrtc: yes
webrtcAddress: 127.0.0.1:{settings.mediamtx_webrtc_port}
# Loopback-only ICE candidate: this relay's media plane is not proxied (see
# module docstring), so it is deliberately restricted to the same-machine
# topology rather than advertising every interface IP.
webrtcLocalUDPAddress: 127.0.0.1:8189
webrtcLocalTCPAddress: ""
webrtcIPsFromInterfaces: no
webrtcAdditionalHosts: [127.0.0.1]
webrtcICEServers2: []

api: yes
apiAddress: 127.0.0.1:{settings.mediamtx_api_port}

paths:
  all_others:
"""


@dataclass
class _RelayHandle:
    camera_id: str
    proc: subprocess.Popen
    started_at: float
    last_active: float


_mediamtx_proc: subprocess.Popen | None = None
_relays: dict[str, _RelayHandle] = {}


def _save_manifest() -> None:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    entries = [{"kind": "relay", "camera_id": cid, "pid": h.proc.pid} for cid, h in _relays.items()]
    if _mediamtx_proc is not None and _mediamtx_proc.poll() is None:
        entries.append({"kind": "mediamtx", "pid": _mediamtx_proc.pid})
    _MANIFEST_PATH.write_text(json.dumps(entries))


def kill_orphans_from_previous_run() -> None:
    """Called once at startup, before this module starts anything of its own.
    Same reasoning as analytics.kill_orphans_from_previous_run: a pid
    recorded in the manifest by a prior backend process cannot be reattached
    to (Popen has no "adopt an existing pid" API), so the only safe move is
    to kill it and let this run start fresh."""
    if not _MANIFEST_PATH.exists():
        return
    try:
        entries = json.loads(_MANIFEST_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        entries = []

    for entry in entries:
        pid = entry.get("pid")
        if not pid:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            continue  # already exited, or not ours to signal
        logger.info(
            "Killed orphaned %s pid=%s (camera=%s) from a previous run",
            entry.get("kind"), pid, entry.get("camera_id"),
        )

    with contextlib.suppress(OSError):
        _MANIFEST_PATH.unlink()


async def ensure_mediamtx_running() -> None:
    """Idempotent within one process: safe to call once at lifespan
    startup. Generates the config fresh each time (cheap, and keeps it in
    sync with current settings) but only spawns a process if none is
    already tracked and alive."""
    global _mediamtx_proc
    if _mediamtx_proc is not None and _mediamtx_proc.poll() is None:
        return

    settings = get_settings()
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    _MEDIAMTX_CONFIG_PATH.write_text(_mediamtx_config(settings))

    log_path = _LOG_DIR / "mediamtx.stdout.log"
    log_file = open(log_path, "ab")  # noqa: SIM115 - lives for the subprocess's lifetime
    _mediamtx_proc = subprocess.Popen(
        [settings.mediamtx_bin, str(_MEDIAMTX_CONFIG_PATH)],
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    _save_manifest()

    deadline = time.monotonic() + settings.webrtc_relay_start_timeout_seconds
    api_url = f"http://127.0.0.1:{settings.mediamtx_api_port}/v3/paths/list"
    async with httpx.AsyncClient(timeout=2.0) as client:
        while time.monotonic() < deadline:
            if _mediamtx_proc.poll() is not None:
                raise RuntimeError(
                    f"mediamtx exited immediately (code {_mediamtx_proc.returncode}); see {log_path}"
                )
            try:
                resp = await client.get(api_url)
                if resp.status_code == 200:
                    logger.info("mediamtx running (pid=%s)", _mediamtx_proc.pid)
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.2)
    raise RuntimeError(f"mediamtx did not become ready within {settings.webrtc_relay_start_timeout_seconds}s")


def _relay_alive(camera_id: str) -> bool:
    handle = _relays.get(camera_id)
    return handle is not None and handle.proc.poll() is None


def _relay_input_args(source_url: str, source_transport: str) -> list[str]:
    """FFmpeg input arguments for one private source endpoint."""
    if source_transport == "rtsp":
        return ["-rtsp_transport", "tcp", "-i", source_url]
    if source_transport == "hls":
        return ["-re", "-i", source_url]
    raise ValueError("WebRTC relay source transport must be rtsp or hls")


def _evict(camera_id: str, reason: str) -> None:
    handle = _relays.pop(camera_id, None)
    if handle is None:
        return
    logger.info("Stopping WebRTC relay for camera %s (%s)", camera_id, reason)
    with contextlib.suppress(OSError):
        handle.proc.terminate()
    _save_manifest()


async def ensure_relay_running(camera_id: str, source_url: str, source_transport: str) -> None:
    """Ensure one ffmpeg source-to-MediaMTX relay for this camera.

    Deliberately no restart-with-backoff loop here, unlike analytics.py's
    always-on supervisor: a relay only ever exists because a browser is
    actively (right now) negotiating a WHEP session for it, and the frontend
    treats WebRTC as a one-shot attempt that falls back to HLS rather than
    retrying -- so there is no risk of this being hammered in a tight loop
    the way an always-desired analytics worker could be.
    """
    if _relay_alive(camera_id):
        _relays[camera_id].last_active = time.time()
        return
    _relays.pop(camera_id, None)  # drop a dead handle, if any

    settings = get_settings()
    if camera_id not in _relays and len(_relays) >= settings.max_concurrent_webrtc_relays:
        lru_id = min(_relays, key=lambda cid: _relays[cid].last_active)
        _evict(lru_id, "concurrency cap reached for a new camera")

    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = _LOG_DIR / f"webrtc-relay-{camera_id}.log"
    log_file = open(log_path, "ab")  # noqa: SIM115 - lives for the subprocess's lifetime
    proc = subprocess.Popen(
        [
            "ffmpeg", "-nostdin", "-loglevel", "warning",
            *_relay_input_args(source_url, source_transport),
            "-c", "copy",
            "-f", "rtsp", "-rtsp_transport", "tcp",
            f"rtsp://127.0.0.1:{settings.mediamtx_rtsp_port}/{camera_id}",
        ],
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    now = time.time()
    _relays[camera_id] = _RelayHandle(camera_id=camera_id, proc=proc, started_at=now, last_active=now)
    _save_manifest()
    logger.info(
        "Started WebRTC relay for camera %s over %s (pid=%s), log=%s",
        camera_id, source_transport, proc.pid, log_path,
    )


async def wait_path_ready(camera_id: str, timeout: float) -> None:
    """Polls mediamtx's control API until the path has a live publisher
    (the ffmpeg relay has connected), or raises -- so the router can return
    a clear 502 instead of handing the browser a WHEP negotiation that will
    silently sit there forever."""
    settings = get_settings()
    api_url = f"http://127.0.0.1:{settings.mediamtx_api_port}/v3/paths/get/{camera_id}"
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient(timeout=2.0) as client:
        while time.monotonic() < deadline:
            if camera_id in _relays and _relays[camera_id].proc.poll() is not None:
                raise RuntimeError(f"Relay for camera {camera_id} exited before the stream became ready")
            try:
                resp = await client.get(api_url)
                if resp.status_code == 200 and resp.json().get("ready"):
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.2)
    raise RuntimeError(f"Relay for camera {camera_id} did not become ready within {timeout}s")


def touch(camera_id: str) -> None:
    if camera_id in _relays:
        _relays[camera_id].last_active = time.time()


async def reap_idle_relays() -> None:
    settings = get_settings()
    now = time.time()
    for camera_id in [cid for cid, h in _relays.items() if now - h.last_active > settings.webrtc_relay_idle_timeout_seconds]:
        _evict(camera_id, "idle")


async def webrtc_supervisor_loop() -> None:
    while True:
        try:
            await reap_idle_relays()
            # A relay that crashed on its own (source stall, ffmpeg error)
            # is still worth dropping promptly rather than waiting for the
            # idle timeout, so the next WHEP attempt starts a fresh one.
            for camera_id in [cid for cid, h in _relays.items() if h.proc.poll() is not None]:
                _relays.pop(camera_id, None)
                _save_manifest()
        except Exception:  # noqa: BLE001 - the loop must survive a bad tick
            logger.exception("WebRTC relay supervisor tick failed")
        await asyncio.sleep(SUPERVISOR_INTERVAL_SECONDS)


async def shutdown_all() -> None:
    """Unlike the ANPR/ingest workers, a relay or mediamtx itself has no
    purpose once nothing is listening -- it exists only to serve an
    in-progress browser preview. Torn down on graceful shutdown rather than
    left running for the next process to reconcile."""
    global _mediamtx_proc
    procs = [h.proc for h in _relays.values()]
    if _mediamtx_proc is not None:
        procs.append(_mediamtx_proc)
    for proc in procs:
        with contextlib.suppress(OSError):
            proc.terminate()
    deadline = time.monotonic() + _SHUTDOWN_GRACE_SECONDS
    for proc in procs:
        remaining = max(0.0, deadline - time.monotonic())
        try:
            proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(OSError):
                proc.kill()
    _relays.clear()
    _mediamtx_proc = None
    with contextlib.suppress(OSError):
        _MANIFEST_PATH.unlink()
