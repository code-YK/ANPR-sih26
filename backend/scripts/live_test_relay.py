#!/usr/bin/env python3
"""
Serves the Section 5 live-test fixture (build_live_test_fixture.py's
clips) as genuinely continuous, live RTSP+HLS streams -- not files a
worker could seek/download past.

Reuses the same MediaMTX pattern already built and verified for this
project's (separate, unmerged) WebRTC relay branch: generate a minimal
mediamtx.yml, spawn the binary, feed it via ffmpeg. This is new,
standalone code for this feature, not a dependency on that branch --
in particular, HLS is *enabled* here (the WebRTC relay explicitly
disabled it, since it only needed WHEP out): HLS is the transport this
project's ANPR workers and browser Live view both actually consume, and
per observation_worker.py's own time-anchoring check, sightings need
the HLS media playlist's #EXT-X-PROGRAM-DATE-TIME tag to get a real
seen_at at all.

Each camera's clip is republished on an unbounded loop
(`ffmpeg -stream_loop -1`), so PTS keeps advancing indefinitely rather than
the stream ending after one clip's duration -- required for "PTS increases
correctly" and for exercising reconnect behaviour on demand.

Usage:
    ../.venv/bin/python scripts/live_test_relay.py start
    ../.venv/bin/python scripts/live_test_relay.py status
    ../.venv/bin/python scripts/live_test_relay.py kill test-camera-a   # interruption test
    ../.venv/bin/python scripts/live_test_relay.py restart test-camera-a
    ../.venv/bin/python scripts/live_test_relay.py stop
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
_FIXTURE_DIR = os.path.join(_REPO_ROOT, "fixtures", "live-test")
_STATE_DIR = os.path.join(_FIXTURE_DIR, "relay")
_MANIFEST_PATH = os.path.join(_FIXTURE_DIR, "manifest.json")
_PID_PATH = os.path.join(_STATE_DIR, "pids.json")
_CONFIG_PATH = os.path.join(_STATE_DIR, "mediamtx.yml")

RTSP_PORT = 8554
HLS_PORT = 8888
API_PORT = 9997

# camera_id -> role, so a caller can address a camera the way the rest of
# this fixture (seed_live_test.py, run_live_test.py) already does.
_CAMERA_ID_PREFIX = "test-camera-"


def camera_id(role: str) -> str:
    return f"{_CAMERA_ID_PREFIX}{role}"


def hls_url(role: str) -> str:
    return f"http://127.0.0.1:{HLS_PORT}/{camera_id(role)}/index.m3u8"


def rtsp_url(role: str) -> str:
    return f"rtsp://127.0.0.1:{RTSP_PORT}/{camera_id(role)}"


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


def _load_manifest() -> dict:
    if not os.path.exists(_MANIFEST_PATH):
        raise SystemExit(
            f"{_MANIFEST_PATH} not found -- run build_live_test_fixture.py first"
        )
    with open(_MANIFEST_PATH) as f:
        return json.load(f)


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


def _spawn_publisher(role: str, clip_path: str) -> int:
    log_path = os.path.join(_STATE_DIR, f"ffmpeg-{role}.log")
    log_file = open(log_path, "ab")  # noqa: SIM115 - lives for the subprocess's lifetime
    proc = subprocess.Popen(
        [
            "ffmpeg", "-nostdin", "-loglevel", "warning",
            "-stream_loop", "-1", "-re", "-i", clip_path,
            "-c", "copy", "-f", "rtsp", "-rtsp_transport", "tcp",
            rtsp_url(role),
        ],
        stdout=log_file, stderr=subprocess.STDOUT,
    )
    return proc.pid


def cmd_start(_args) -> int:
    os.makedirs(_STATE_DIR, exist_ok=True)
    manifest = _load_manifest()
    pids = _load_pids()

    if "mediamtx" in pids and _alive(pids["mediamtx"]):
        print("mediamtx already running")
    else:
        with open(_CONFIG_PATH, "w") as f:
            f.write(_mediamtx_config())
        log_path = os.path.join(_STATE_DIR, "mediamtx.stdout.log")
        log_file = open(log_path, "ab")  # noqa: SIM115
        proc = subprocess.Popen(["mediamtx", _CONFIG_PATH], stdout=log_file, stderr=subprocess.STDOUT)
        pids["mediamtx"] = proc.pid
        _save_pids(pids)
        print(f"mediamtx started (pid={proc.pid})")
        _wait_for_api()

    for cam in manifest["cameras"]:
        role = cam["role"]
        if role in pids and _alive(pids[role]):
            print(f"[{role}] already publishing")
            continue
        pid = _spawn_publisher(role, cam["clip_path"])
        pids[role] = pid
        _save_pids(pids)
        print(f"[{role}] publishing {camera_id(role)} (pid={pid}) -> {hls_url(role)}")

    print("\nwaiting for all paths to go ready...")
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        statuses = {cam["role"]: _path_ready(camera_id(cam["role"])) for cam in manifest["cameras"]}
        if all(statuses.values()):
            print("all paths ready:")
            for cam in manifest["cameras"]:
                print(f"  {camera_id(cam['role'])}: {hls_url(cam['role'])}")
            return 0
        time.sleep(0.5)
    print(f"not all paths became ready in time: {statuses}", file=sys.stderr)
    return 1


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


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


def _path_ready(path_name: str) -> bool:
    try:
        resp = httpx.get(f"http://127.0.0.1:{API_PORT}/v3/paths/get/{path_name}", timeout=2.0)
        return resp.status_code == 200 and resp.json().get("ready", False)
    except httpx.HTTPError:
        return False


def cmd_status(_args) -> int:
    manifest = _load_manifest()
    pids = _load_pids()
    for cam in manifest["cameras"]:
        role = cam["role"]
        pid = pids.get(role)
        alive = pid is not None and _alive(pid)
        ready = _path_ready(camera_id(role)) if alive else False
        print(f"{camera_id(role):24s} pid={pid} alive={alive} ready={ready} plate={cam['plate']}")
    return 0


def cmd_kill(args) -> int:
    """The engineered feed interruption -- kills one camera's publisher.
    Whatever reconnects to it (the observation worker, the browser HLS
    hook) already has its own bounded-backoff recovery logic; this just
    removes the source out from under it."""
    pids = _load_pids()
    role = args.role.removeprefix(_CAMERA_ID_PREFIX)
    pid = pids.get(role)
    if not pid:
        print(f"no known publisher for role {role!r}", file=sys.stderr)
        return 1
    _kill(pid)
    print(f"killed [{role}] publisher (pid={pid}) -- source is now down")
    return 0


def cmd_restart(args) -> int:
    manifest = _load_manifest()
    pids = _load_pids()
    role = args.role.removeprefix(_CAMERA_ID_PREFIX)
    cam = next((c for c in manifest["cameras"] if c["role"] == role), None)
    if cam is None:
        print(f"no such role {role!r} in manifest", file=sys.stderr)
        return 1
    old_pid = pids.get(role)
    if old_pid and _alive(old_pid):
        _kill(old_pid)
        time.sleep(0.5)
    pid = _spawn_publisher(role, cam["clip_path"])
    pids[role] = pid
    _save_pids(pids)
    print(f"[{role}] restarted (pid={pid})")
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
    p_kill = sub.add_parser("kill")
    p_kill.add_argument("role", help="e.g. test-camera-a or just 'a'")
    p_kill.set_defaults(func=cmd_kill)
    p_restart = sub.add_parser("restart")
    p_restart.add_argument("role")
    p_restart.set_defaults(func=cmd_restart)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
