#!/usr/bin/env python3
"""Fast offline checks for analytics and preview transport selection.

Run from the repository root:
    backend/.venv/bin/python backend/scripts/analytics_source_selection_test.py

No database, source endpoint, model, or worker subprocess is required. The
test keeps the custom-stream regression covered: inference prefers RTSP/TCP,
retains HLS as a bounded fallback/time anchor, and focused browser preview
selects an RTSP/TCP-to-WHEP relay without exposing the raw endpoint.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.camera import Camera  # noqa: E402
from app.pipeline.webrtc_relay import _relay_input_args  # noqa: E402
from app.routers.analytics import (  # noqa: E402
    _analytics_source,
    _analytics_worker_source_args,
    _rtsp_capture_options,
)
from app.routers.webrtc import _preview_source  # noqa: E402
from app.schemas import CameraOut  # noqa: E402


def camera(camera_id: str, *, hls_url: str | None = None, rtsp_url: str | None = None) -> Camera:
    return Camera(
        camera_id=camera_id,
        camera_number=1,
        name="Analytics source test",
        location_text="Synthetic test source",
        hls_url=hls_url,
        rtsp_url=rtsp_url,
        analytics_enabled=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def main() -> int:
    both = camera("both", hls_url="https://example.invalid/live.m3u8", rtsp_url="rtsp://example.invalid/also")
    assert _analytics_source(both) == (both.rtsp_url, "rtsp"), "inference must prefer RTSP"
    source_args, transport = _analytics_worker_source_args(both)
    assert transport == "rtsp"
    assert source_args == [
        "--url", both.rtsp_url,
        "--fallback-url", both.hls_url,
        "--timestamp-url", both.hls_url,
    ]
    assert _preview_source(both) == (both.rtsp_url, "rtsp"), "focused preview must prefer RTSP"

    rtsp = camera("rtsp", rtsp_url="rtsp://example.invalid/custom")
    url, transport = _analytics_source(rtsp)
    assert transport == "rtsp" and url == rtsp.rtsp_url, "RTSP-only camera must use its registry endpoint"
    assert CameraOut.model_validate(rtsp).analytics_stream_available is True
    assert CameraOut.model_validate(rtsp).stream_available is False, "RTSP is not browser-playable"
    assert CameraOut.model_validate(rtsp).webrtc_preview_available is True
    assert _analytics_worker_source_args(rtsp)[0] == ["--url", rtsp.rtsp_url]

    try:
        _analytics_source(camera("none"))
    except RuntimeError as exc:
        assert "no HLS or RTSP" in str(exc)
    else:
        raise AssertionError("a camera without an analytics source must fail before worker launch")

    options = _rtsp_capture_options("timeout;60000000|rw_timeout;60000000")
    assert "timeout;60000000" in options and "rtsp_transport;tcp" in options
    assert _rtsp_capture_options(options).count("rtsp_transport;tcp") == 1
    assert _relay_input_args(rtsp.rtsp_url, "rtsp") == [
        "-rtsp_transport", "tcp", "-i", rtsp.rtsp_url,
    ]
    assert _relay_input_args(both.hls_url, "hls") == ["-re", "-i", both.hls_url]
    print("PASS: RTSP-first inference/WHEP selection, HLS fallback, and TCP enforcement")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
