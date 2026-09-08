#!/usr/bin/env python3
"""Offline source-order checks for LiveFrameReader.

Run from the repository root:
    multi-object-tracking/.venv/bin/python multi-object-tracking/camera_feeds_transport_test.py
"""

import camera_feeds


class FakeCapture:
    attempts = []

    def __init__(self, url, _backend):
        self.url = url
        self.released = False
        self.attempts.append(url)

    def isOpened(self):
        return not self.url.startswith("rtsp://offline")

    def release(self):
        self.released = True

    def set(self, _prop, _value):
        return True

    def get(self, prop):
        if prop == camera_feeds.cv2.CAP_PROP_FRAME_WIDTH:
            return 1280
        if prop == camera_feeds.cv2.CAP_PROP_FRAME_HEIGHT:
            return 720
        if prop == camera_feeds.cv2.CAP_PROP_FPS:
            return 25
        return 0


def main():
    original_capture = camera_feeds.cv2.VideoCapture
    camera_feeds.cv2.VideoCapture = FakeCapture
    try:
        hls = "https://example.invalid/live.m3u8"
        reader = camera_feeds.LiveFrameReader(
            "rtsp://offline/camera",
            fallback_url=hls,
            timestamp_url=hls,
        )
        cap = reader._connect()
        assert cap is not None
        assert FakeCapture.attempts == ["rtsp://offline/camera", hls]
        assert reader.transport == "hls"
        assert reader._anchor.master_url == hls

        FakeCapture.attempts.clear()
        reader = camera_feeds.LiveFrameReader(
            "rtsp://online/camera",
            fallback_url=hls,
            timestamp_url=hls,
        )
        cap = reader._connect()
        assert cap is not None
        assert FakeCapture.attempts == ["rtsp://online/camera"]
        assert reader.transport == "rtsp"
        assert reader._anchor.master_url == hls
    finally:
        camera_feeds.cv2.VideoCapture = original_capture

    print("PASS: LiveFrameReader prefers RTSP and falls back to HLS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
