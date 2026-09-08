#!/usr/bin/env python3
"""Sentinel sandbox client: catalogue inspection and authorised frame diagnostics.

Examples
    python3 sentinel_client.py list
    python3 sentinel_client.py list --save catalogue.json
    python3 sentinel_client.py frame 2

Follows the Integrator's Guide: reads camera URLs from /api/ingest instead of
hardcoding the URL pattern, forces RTSP over TCP, and reconnects with backoff
on read failure. Clip-recording commands are intentionally absent: sandbox
feeds are real-time-only and must not be downloaded or retained as footage.
Frame capture is an exceptional diagnostic and requires separate approval for
the exact purpose and retention; this utility does not grant that approval.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import cv2
import requests

DEFAULT_HOST = os.environ.get("SENTINEL_HOST")
RTSP_PROBE_TIMEOUT_US = 5_000_000


def catalogue_url(host: str) -> str:
    return f"https://{host}/api/ingest"


def fetch_catalogue(host: str) -> list[dict]:
    resp = requests.get(catalogue_url(host), timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return data.get("cameras", data if isinstance(data, list) else [])


def find_camera(cameras: list[dict], camera_id: str) -> dict:
    for cam in cameras:
        if str(cam.get("id")) == str(camera_id):
            return cam
    raise SystemExit(f"Camera id {camera_id!r} not found in catalogue.")


def probe_rtsp(rtsp_url: str) -> bool:
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
        f"rtsp_transport;tcp|timeout;{RTSP_PROBE_TIMEOUT_US}"
    )
    cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
    ok = cap.isOpened() and cap.read()[0]
    cap.release()
    return ok


def resolve_url(host: str, camera: dict, protocol: str) -> tuple[str, str]:
    rtsp_url = camera.get("rtsp_url")
    hls_url = camera.get("hls_live_url")
    if hls_url and hls_url.startswith("/"):
        hls_url = f"https://{host}{hls_url}"

    if protocol == "rtsp":
        if not rtsp_url:
            raise SystemExit("Camera has no rtsp_url in the catalogue.")
        return rtsp_url, "rtsp"
    if protocol == "hls":
        if not hls_url:
            raise SystemExit("Camera has no hls_live_url in the catalogue.")
        return hls_url, "hls"

    # auto: RTSP is what the guide recommends for AI inference, so try it
    # first with a short timeout, and fall back to HLS if it's unreachable
    # (e.g. RTSP's non-standard port is blocked on this network).
    if rtsp_url:
        print("  probing RTSP...", end=" ", flush=True)
        if probe_rtsp(rtsp_url):
            print("reachable")
            return rtsp_url, "rtsp"
        print("unreachable, falling back to HLS")
    if hls_url:
        return hls_url, "hls"
    raise SystemExit("Camera has neither a reachable RTSP stream nor an HLS URL.")


def open_capture(url: str, protocol: str) -> cv2.VideoCapture:
    if protocol == "rtsp":
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|timeout;5000000"
    else:
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
            "reconnect;1|reconnect_streamed;1|reconnect_delay_max;5|timeout;10000000"
        )
    return cv2.VideoCapture(url, cv2.CAP_FFMPEG)


def cmd_list(args):
    cameras = fetch_catalogue(args.host)
    print(f"{len(cameras)} cameras in catalogue at {args.host}\n")
    for cam in cameras:
        status = "LIVE" if cam.get("live") else "down"
        res = f"{cam.get('width')}x{cam.get('height')}" if cam.get("width") else "?"
        print(
            f"  [{str(cam.get('id')):>3}] {status:4}  {cam.get('name', ''):<12} "
            f"{cam.get('location', ''):<35} codec={cam.get('codec') or '?':<5} {res}"
        )
    if args.save:
        with open(args.save, "w") as f:
            json.dump(cameras, f, indent=2)
        print(f"\nSaved full catalogue to {args.save}")


def cmd_frame(args):
    cameras = fetch_catalogue(args.host)
    camera = find_camera(cameras, args.camera)
    url, proto = resolve_url(args.host, camera, args.protocol)
    print(f"Camera {args.camera} ({camera.get('location')}) via {proto.upper()} (endpoint redacted)")

    cap = open_capture(url, proto)
    if not cap.isOpened():
        raise SystemExit(f"Could not open stream via {proto}.")
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise SystemExit("Connected but failed to read a frame.")

    os.makedirs(args.out, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(args.out, f"cam{args.camera}_{ts}.jpg")
    cv2.imwrite(out_path, frame)
    print(f"Saved frame: {out_path}  ({frame.shape[1]}x{frame.shape[0]})")


def build_parser():
    p = argparse.ArgumentParser(description="Sentinel sandbox client")
    p.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help="sandbox host (or set SENTINEL_HOST; obtain the value outside Git)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="fetch and print the camera catalogue")
    p_list.add_argument("--save", help="also save the raw catalogue JSON to this path")
    p_list.set_defaults(func=cmd_list)

    p_frame = sub.add_parser("frame", help="grab a single frame from one camera")
    p_frame.add_argument("camera", help="camera id, e.g. 2")
    p_frame.add_argument("--protocol", choices=["auto", "rtsp", "hls"], default="auto")
    p_frame.add_argument("--out", default="captures")
    p_frame.set_defaults(func=cmd_frame)

    return p


def main():
    args = build_parser().parse_args()
    if not args.host:
        raise SystemExit("Set SENTINEL_HOST or pass --host with an authorised local value.")
    args.func(args)


if __name__ == "__main__":
    main()
