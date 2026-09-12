#!/usr/bin/env python3
"""Serves recorded government-feed footage as genuinely continuous,
live-looking RTSP+HLS streams -- the same "real transport, not a seekable
file" technique already built for the Section 5 live-test fixture
(scripts/live_test_relay.py), generalised from that fixture's fixed
four-role manifest to an arbitrary set of recordings dropped by an operator.

Discovers its own inputs at `start` time from recorded-streams/ (repo root)
-- the format multi-object-tracking/record_live_clips.py already writes:
one camera-<camera_id>-<timestamp>-<duration>s.mp4 plus a matching .json
sidecar (written only once a clip finishes, so a still-in-progress
*.partial.mp4 has none yet and is correctly skipped) holding at least
{"camera_id": ...}. The camera_id comes from that sidecar, not a filename
guess. If more than one completed recording exists for the same camera,
the most recently recorded one wins.

Runs its own MediaMTX instance on ports distinct from both the live-test
fixture's (8554 RTSP / 8888 HLS / 9997 API) and the WebRTC preview relay's
(8555 RTSP / 9998 API by convention in this repo's .env.example), so all
three can run at once on one machine: 8556 RTSP / 8890 HLS / 9999 API.

Usage:
    ../.venv/bin/python scripts/government_feed_relay.py start
    ../.venv/bin/python scripts/government_feed_relay.py status
    ../.venv/bin/python scripts/government_feed_relay.py stop
"""

import argparse
import contextlib
import json
import os
import signal
import subprocess
import sys
import time

import httpx

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_RECORDING_DIR = os.path.join(_REPO_ROOT, "recorded-streams")
_STATE_DIR = os.path.join(_RECORDING_DIR, "_relay")
_PID_PATH = os.path.join(_STATE_DIR, "pids.json")
_CONFIG_PATH = os.path.join(_STATE_DIR, "mediamtx.yml")
# Same env var app/config.py's Settings.mediamtx_bin reads (see
# webrtc_relay.py) -- this standalone script doesn't import pydantic-settings,
# so it reads the var directly rather than hardcoding "mediamtx", which is
# never on PATH on a machine that only has a project-local Windows binary.
_MEDIAMTX_BIN = os.environ.get("MEDIAMTX_BIN", "mediamtx")
# mediamtx and each ffmpeg publisher are meant to outlive this script (that's
# the whole point of PID-file tracking) and outlive whatever spawned this
# script too -- without this, Windows kills them the instant their parent
# console gets Ctrl+C or closes, since a plain Popen child shares its
# parent's console by default. CREATE_NEW_PROCESS_GROUP detaches them from
# that console's control-event delivery; explicit stop/kill (SIGTERM via
# os.kill, which Python maps to TerminateProcess on Windows) still works
# unaffected, since that targets the PID directly rather than relying on
# console signal propagation.
_DETACHED = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {}

RTSP_PORT = 8556
HLS_PORT = 8890
API_PORT = 9999

_PATH_PREFIX = "gov-camera-"


def path_name(camera_id: str) -> str:
    return f"{_PATH_PREFIX}{camera_id}"


def hls_url(camera_id: str) -> str:
    return f"http://127.0.0.1:{HLS_PORT}/{path_name(camera_id)}/index.m3u8"


def rtsp_url(camera_id: str) -> str:
    return f"rtsp://127.0.0.1:{RTSP_PORT}/{path_name(camera_id)}"


def discover_recordings() -> dict[str, str]:
    """camera_id -> absolute .mp4 path, one per camera, for every completed
    (has a .json sidecar) recording anywhere under recorded-streams/,
    including subdirectories -- an operator dropping a batch of clips into
    their own subfolder (e.g. "newly added clips/") shouldn't have to flatten
    them into the top level first. When the same camera_id has more than one,
    the sidecar's own recorded_at_utc picks the most recent -- an operator
    re-recording a bad take shouldn't have to delete the old file first."""
    if not os.path.isdir(_RECORDING_DIR):
        return {}
    best: dict[str, tuple[str, str]] = {}  # camera_id -> (recorded_at_utc, clip_path)
    for root, dirs, files in os.walk(_RECORDING_DIR):
        # Never descend into the relay's own runtime state dir (pid files,
        # generated mediamtx.yml, ffmpeg logs) looking for recordings.
        dirs[:] = [d for d in dirs if os.path.join(root, d) != _STATE_DIR]
        for entry in sorted(files):
            if not entry.endswith(".json"):
                continue
            sidecar_path = os.path.join(root, entry)
            try:
                with open(sidecar_path) as f:
                    meta = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            camera_id = meta.get("camera_id")
            if not camera_id:
                continue
            # Normally the sidecar and clip share a basename (one recording,
            # one camera). An explicit "clip_path" (a filename relative to
            # the sidecar's own directory) lets several camera_ids re-onboard
            # the *same* physical recording under different identities --
            # e.g. building a multi-stop journey demo along a real corridor
            # from one clip, without duplicating tens of MB of video per stop.
            explicit_clip = meta.get("clip_path")
            clip_path = (
                os.path.join(root, explicit_clip) if explicit_clip
                else os.path.join(root, entry[: -len(".json")] + ".mp4")
            )
            if not os.path.isfile(clip_path):
                continue
            recorded_at = meta.get("recorded_at_utc", "")
            current = best.get(camera_id)
            if current is None or recorded_at > current[0]:
                best[camera_id] = (recorded_at, clip_path)
    return {camera_id: clip_path for camera_id, (_, clip_path) in best.items()}


def _mediamtx_config() -> str:
    return f"""\
logLevel: warn
logDestinations: [file]
logFile: {os.path.join(_STATE_DIR, "mediamtx.log")}

rtsp: yes
rtspAddress: 127.0.0.1:{RTSP_PORT}
rtspTransports: [tcp]
rtmp: no
srt: no
webrtc: no
moq: no

hls: yes
hlsAddress: 127.0.0.1:{HLS_PORT}
hlsAllowOrigins: ["*"]
hlsVariant: mpegts
hlsSegmentCount: 7
hlsSegmentDuration: 1s

api: yes
apiAddress: 127.0.0.1:{API_PORT}

paths:
  all_others:
"""


def _load_pids() -> dict:
    if not os.path.exists(_PID_PATH):
        return {}
    with open(_PID_PATH) as f:
        return json.load(f)


def _save_pids(pids: dict) -> None:
    with open(_PID_PATH, "w") as f:
        json.dump(pids, f)


def _kill(pid: int) -> None:
    with contextlib.suppress(OSError):
        os.kill(pid, signal.SIGTERM)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _spawn_publisher(camera_id: str, clip_path: str) -> int:
    log_path = os.path.join(_STATE_DIR, f"ffmpeg-{camera_id}.log")
    log_file = open(log_path, "ab")  # noqa: SIM115 - lives for the subprocess's lifetime
    proc = subprocess.Popen(
        [
            "ffmpeg", "-nostdin", "-loglevel", "warning",
            "-stream_loop", "-1", "-re", "-i", clip_path,
            "-c", "copy", "-f", "rtsp", "-rtsp_transport", "tcp",
            rtsp_url(camera_id),
        ],
        stdout=log_file, stderr=subprocess.STDOUT, **_DETACHED,
    )
    return proc.pid


def _wait_for_api(timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{API_PORT}/v3/paths/list", timeout=1.0).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    raise SystemExit("mediamtx did not become ready")


def _path_ready(name: str) -> bool:
    try:
        resp = httpx.get(f"http://127.0.0.1:{API_PORT}/v3/paths/get/{name}", timeout=2.0)
        return resp.status_code == 200 and resp.json().get("ready", False)
    except httpx.HTTPError:
        return False


def cmd_start(_args) -> int:
    recordings = discover_recordings()
    if not recordings:
        print(
            f"no completed recording (an .mp4 with a matching .json sidecar) found directly "
            f"under {_RECORDING_DIR} -- nothing to serve",
            file=sys.stderr,
        )
        return 1

    os.makedirs(_STATE_DIR, exist_ok=True)
    pids = _load_pids()

    if "mediamtx" in pids and _alive(pids["mediamtx"]):
        print("mediamtx already running")
    else:
        with open(_CONFIG_PATH, "w") as f:
            f.write(_mediamtx_config())
        log_path = os.path.join(_STATE_DIR, "mediamtx.stdout.log")
        log_file = open(log_path, "ab")  # noqa: SIM115
        proc = subprocess.Popen([_MEDIAMTX_BIN, _CONFIG_PATH], stdout=log_file, stderr=subprocess.STDOUT, **_DETACHED)
        pids["mediamtx"] = proc.pid
        _save_pids(pids)
        print(f"mediamtx started (pid={proc.pid})")
        _wait_for_api()

    for camera_id, clip_path in recordings.items():
        if camera_id in pids and _alive(pids[camera_id]):
            print(f"[{camera_id}] already publishing")
            continue
        pid = _spawn_publisher(camera_id, clip_path)
        pids[camera_id] = pid
        _save_pids(pids)
        print(f"[{camera_id}] publishing {os.path.basename(clip_path)} (pid={pid}) -> {hls_url(camera_id)}")

    print("\nwaiting for all paths to go ready...")
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        statuses = {cid: _path_ready(path_name(cid)) for cid in recordings}
        if all(statuses.values()):
            print("all paths ready:")
            for cid in recordings:
                print(f"  {cid}: {hls_url(cid)}")
            return 0
        time.sleep(0.5)
    print(f"not all paths became ready in time: {statuses}", file=sys.stderr)
    return 1


def cmd_status(_args) -> int:
    recordings = discover_recordings()
    pids = _load_pids()
    for camera_id in recordings:
        pid = pids.get(camera_id)
        alive = pid is not None and _alive(pid)
        ready = _path_ready(path_name(camera_id)) if alive else False
        print(f"{camera_id:24s} pid={pid} alive={alive} ready={ready}")
    return 0


def cmd_stop(_args) -> int:
    pids = _load_pids()
    for name, pid in pids.items():
        _kill(pid)
        print(f"stopped {name} (pid={pid})")
    with contextlib.suppress(OSError):
        os.remove(_PID_PATH)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("start").set_defaults(func=cmd_start)
    sub.add_parser("status").set_defaults(func=cmd_status)
    sub.add_parser("stop").set_defaults(func=cmd_stop)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
