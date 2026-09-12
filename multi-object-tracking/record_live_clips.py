#!/usr/bin/env python3
"""Record short, explicitly authorised clips from currently available HLS feeds.

This is a local capture utility, not an analytics input path.  It discovers
camera URLs from the configured ingest catalogue every time it checks and keeps
both endpoint values and video files out of the repository.

Examples (run from ``multi-object-tracking/``):

  export SANDBOX_CATALOGUE_URL='https://.../api/ingest'
  export SANDBOX_BROWSER_BASE_URL='https://...'
  python record_live_clips.py --authorised-recording
  python record_live_clips.py --authorised-recording --minutes 5 --all

By default the monitor checks Camera 6 every five minutes and records a
three-minute clip only when its HLS manifest is usable.  ``--all`` is opt-in:
it records Camera 6 first, then each other catalogue camera sequentially.  The
latter can keep a stream client open for a long time, so do not use it unless
that load is authorised.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


USER_AGENT = "Mozilla/5.0"
DEFAULT_OUTPUT_DIR = Path.home() / "Desktop" / "recorded streams"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--authorised-recording",
        action="store_true",
        help="required acknowledgement before the script will persist video",
    )
    parser.add_argument(
        "--minutes",
        type=int,
        default=3,
        choices=range(1, 6),
        metavar="{1,2,3,4,5}",
        help="clip duration (default: 3; permitted range: 1-5)",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=300,
        help="seconds to wait before the next catalogue/manifest check (default: 300)",
    )
    parser.add_argument(
        "--camera",
        action="append",
        default=[],
        metavar="ID",
        help="camera ID to monitor; repeatable (default: Camera 6)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="after the selected cameras, try every other camera in the catalogue once per cycle",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="check and record at most one cycle, then exit",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"local recording directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(message: str) -> None:
    print(f"{utc_now()} {message}", flush=True)


def configured_url(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required; set it locally and never commit it")
    return value


def get_json(url: str, *, timeout: int = 20) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise RuntimeError("catalogue returned an unexpected JSON document")
    return payload


def hls_url(camera: dict[str, Any], browser_base_url: str) -> str | None:
    value = camera.get("hls_live_url")
    if not isinstance(value, str) or not value.strip():
        return None
    if value.startswith(("https://", "http://")):
        return value
    return urllib.parse.urljoin(f"{browser_base_url.rstrip('/')}/", value.lstrip("/"))


def is_hls_manifest(url: str) -> bool:
    """Return whether a bounded request is an HLS manifest; never log its URL."""
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Range": "bytes=0-1023"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            sample = response.read(1024).decode("utf-8", errors="replace")
    except Exception as exc:
        log(f"HLS probe unavailable ({type(exc).__name__}; endpoint redacted)")
        return False
    if sample.lstrip().startswith("#EXTM3U"):
        return True
    log("HLS probe returned a non-playlist response (endpoint redacted)")
    return False


def ffprobe_duration(path: Path) -> float | None:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration,size",
            "-of", "json", str(path),
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if result.returncode != 0:
        return None
    try:
        value = json.loads(result.stdout)["format"]["duration"]
        return float(value)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def record_clip(camera_id: str, source_url: str, output_dir: Path, seconds: int) -> bool:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = output_dir / f"camera-{camera_id}-{timestamp}-{seconds}s.mp4"
    partial = target.with_suffix(".partial.mp4")
    if partial.exists() or target.exists():
        log(f"camera {camera_id}: skipped because this capture filename already exists")
        return False
    command = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "warning",
        "-rw_timeout", "60000000", "-i", source_url, "-t", str(seconds),
        "-map", "0:v:0", "-an", "-c:v", "libx264", "-preset", "veryfast",
        "-movflags", "+faststart", "-n", str(partial),
    ]
    log(f"camera {camera_id}: recording up to {seconds}s")
    try:
        result = subprocess.run(command, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        log(f"camera {camera_id}: could not start ffmpeg ({exc.strerror})")
        return False
    if result.returncode != 0 or not partial.exists() or partial.stat().st_size == 0:
        partial.unlink(missing_ok=True)
        log(f"camera {camera_id}: recording failed (ffmpeg exit {result.returncode}; endpoint redacted)")
        return False

    duration = ffprobe_duration(partial)
    if duration is None or duration < seconds * 0.5:
        partial.unlink(missing_ok=True)
        measured = "unreadable" if duration is None else f"{duration:.1f}s"
        log(f"camera {camera_id}: rejected incomplete clip ({measured})")
        return False

    partial.replace(target)
    sidecar = target.with_suffix(".json")
    sidecar.write_text(
        json.dumps(
            {
                "camera_id": str(camera_id),
                "recorded_at_utc": utc_now(),
                "requested_duration_seconds": seconds,
                "measured_duration_seconds": round(duration, 3),
                "bytes": target.stat().st_size,
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    log(f"camera {camera_id}: saved {target.name} ({duration:.1f}s)")
    return True


def camera_order(cameras: list[dict[str, Any]], selected: list[str], include_all: bool) -> list[dict[str, Any]]:
    by_id = {str(camera.get("id")): camera for camera in cameras if camera.get("id") is not None}
    wanted = selected or ["6"]
    ordered: list[dict[str, Any]] = []
    for camera_id in wanted:
        camera = by_id.get(str(camera_id))
        if camera is None:
            log(f"camera {camera_id}: not present in the current catalogue")
        elif camera not in ordered:
            ordered.append(camera)
    if include_all:
        ordered.extend(camera for camera in cameras if camera not in ordered and camera.get("id") is not None)
    return ordered


def run_cycle(args: argparse.Namespace) -> None:
    try:
        catalogue_url = configured_url("SANDBOX_CATALOGUE_URL")
        browser_base_url = configured_url("SANDBOX_BROWSER_BASE_URL")
        catalogue = get_json(catalogue_url)
        cameras = catalogue.get("cameras")
        if not isinstance(cameras, list):
            raise RuntimeError("catalogue does not contain a cameras list")
    except Exception as exc:
        log(f"catalogue unavailable ({type(exc).__name__}; endpoint redacted)")
        return

    for camera in camera_order(cameras, args.camera, args.all):
        camera_id = str(camera["id"])
        source_url = hls_url(camera, browser_base_url)
        if source_url is None:
            log(f"camera {camera_id}: no HLS URL in the current catalogue")
            continue
        if not is_hls_manifest(source_url):
            log(f"camera {camera_id}: unavailable; no clip recorded")
            continue
        record_clip(camera_id, source_url, args.output_dir, args.minutes * 60)


def main() -> int:
    args = parse_args()
    if not args.authorised_recording:
        print("Refusing to record without --authorised-recording.", file=sys.stderr)
        return 2
    if args.interval_seconds < 1:
        print("--interval-seconds must be at least 1", file=sys.stderr)
        return 2
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        print("ffmpeg and ffprobe must be installed and on PATH", file=sys.stderr)
        return 2

    args.output_dir.mkdir(parents=True, exist_ok=True)
    log(f"recordings stay local in {args.output_dir}")
    while True:
        run_cycle(args)
        if args.once:
            return 0
        log(f"next check in {args.interval_seconds}s")
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
