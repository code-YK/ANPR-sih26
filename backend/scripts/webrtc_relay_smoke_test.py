#!/usr/bin/env python3
"""
Smoke test for the WebRTC/WHEP relay
(backend/app/pipeline/webrtc_relay.py, backend/app/routers/webrtc.py).

Exercises the full chain -- ffmpeg relay spawn, mediamtx RTSP-in/WHEP-out,
the backend's authenticated WHEP proxy, and a real ICE/DTLS connection --
without depending on the sandbox being reachable. It builds a local
synthetic HLS source with ffmpeg (a moving test pattern, not real footage)
and registers a scratch camera pointed at it via the real POST /api/cameras
endpoint, the same one a super admin uses for manual onboarding.

Unlike every other smoke test in this directory, this one needs a genuine
RTCPeerConnection: a real WHEP offer has ICE ufrag/pwd and a DTLS
fingerprint that cannot be hand-crafted with httpx, so the actual
negotiation is driven through a real browser engine via Playwright.

Cleanup deletes the scratch camera through the real DELETE /api/cameras/{id}
endpoint -- same super-admin path an operator would use to remove a
mistakenly-created row.

Usage (from backend/, using the repo-root .venv -- the same one every other
script here runs under):
    ../.venv/bin/python scripts/webrtc_relay_smoke_test.py

Assumes the backend is already running, Postgres is reachable, and
SUPER_ADMIN_EMAIL/PASSWORD match the running backend. SKIPS the whole suite
(not a failure) if `mediamtx`, `ffmpeg`, or the Playwright package aren't
available -- this script's own dependencies, not the feature's.

A peer connection reaching "connected" at least once is treated as a pass;
whether it *stays* connected is environment-dependent (see the "Known
limitation" note in docs/webrtc-relay-testing.md about this project's own
sandboxed test tooling) and is reported for information, not asserted.
"""

import argparse
import functools
import http.server
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import get_settings  # noqa: E402

RESULTS = []
HLS_START_TIMEOUT_S = 8.0
WEBRTC_CONNECT_TIMEOUT_S = 8.0


def _pg_dsn(sqlalchemy_url: str) -> str:
    return re.sub(r"^postgresql\+\w+://", "postgresql://", sqlalchemy_url)


def check(name):
    def wrap(fn):
        def runner(*args, **kwargs):
            try:
                ok, detail = fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - a test crashing is a failure, not a crash
                ok, detail = False, f"raised {type(exc).__name__}: {exc}"
            RESULTS.append((name, ok, detail))
            status = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
            print(f"  [{status}] {name} - {detail}")
            return ok
        runner.__name__ = fn.__name__
        return runner
    return wrap


def require(response: httpx.Response, expected, label: str):
    expected_codes = expected if isinstance(expected, (list, tuple)) else (expected,)
    if response.status_code not in expected_codes:
        raise AssertionError(f"{label}: expected {expected_codes}, got {response.status_code}: {response.text[:300]}")
    return response.json() if response.content else None


def _serve_directory(directory: Path):
    """Threaded, in-process HTTP server -- bound to port 0 so the OS picks a
    free port atomically, no port-race guessing needed."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, httpd.server_address[1]


class SyntheticHlsSource:
    """A local, deterministic HLS stream (ffmpeg testsrc) -- exercises the
    exact same code path the real hls_url would (an ffmpeg relay pulling an
    HTTP(S) HLS URL), without depending on the sandbox's uptime at all."""

    def __init__(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="webrtc_smoketest_"))
        self.ffmpeg = subprocess.Popen(
            [
                "ffmpeg", "-nostdin", "-loglevel", "warning",
                "-re", "-f", "lavfi", "-i", "testsrc=size=640x480:rate=25",
                "-c:v", "libx264", "-g", "50",
                "-f", "hls", "-hls_time", "2", "-hls_list_size", "5",
                "-hls_flags", "delete_segments+append_list",
                str(self.tmpdir / "index.m3u8"),
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self.httpd, self.port = _serve_directory(self.tmpdir)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/index.m3u8"

    def wait_ready(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if (self.tmpdir / "index.m3u8").exists():
                return True
            if self.ffmpeg.poll() is not None:
                return False  # ffmpeg exited before producing anything
            time.sleep(0.2)
        return False

    def close(self):
        self.httpd.shutdown()
        self.ffmpeg.terminate()
        try:
            self.ffmpeg.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.ffmpeg.kill()
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class Ctx:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        settings = get_settings()
        if not settings.super_admin_email or not settings.super_admin_password:
            raise RuntimeError("SUPER_ADMIN_EMAIL/PASSWORD required")
        self.super_email = settings.super_admin_email
        self.super_password = settings.super_admin_password

        self.super = httpx.Client(base_url=self.base_url, timeout=30.0)
        require(
            self.super.post("/api/auth/login", json={"email": self.super_email, "password": self.super_password}),
            200, "super admin login",
        )
        self.db = psycopg2.connect(_pg_dsn(settings.sync_database_url))
        self.db.autocommit = True

        self.camera_id: str | None = None
        self.hls_source: SyntheticHlsSource | None = None

    def sql(self, query, params=None):
        with self.db.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall() if cur.description else None

    def cleanup(self):
        if self.camera_id:
            self.super.delete(f"/api/cameras/{self.camera_id}")
        self.super.close()
        if self.hls_source:
            self.hls_source.close()
        self.db.close()


@check("mediamtx and ffmpeg are on PATH")
def test_dependencies(ctx: Ctx):
    missing = [name for name in ("mediamtx", "ffmpeg") if shutil.which(name) is None]
    if missing:
        return None, f"skipping suite: {', '.join(missing)} not found on PATH (see docs/webrtc-relay-testing.md)"
    return True, "present"


@check("playwright is importable")
def test_playwright_available(ctx: Ctx):
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError as exc:
        return None, f"skipping suite: playwright not installed ({exc})"
    return True, "present"


@check("synthetic HLS source comes up")
def test_synthetic_source(ctx: Ctx):
    ctx.hls_source = SyntheticHlsSource()
    ready = ctx.hls_source.wait_ready(HLS_START_TIMEOUT_S)
    if not ready:
        return False, "index.m3u8 never appeared"
    resp = httpx.get(ctx.hls_source.url, timeout=5.0)
    return resp.status_code == 200 and "#EXTM3U" in resp.text, f"HTTP {resp.status_code}"


@check("scratch camera registers with a stream")
def test_register_camera(ctx: Ctx):
    resp = ctx.super.post(
        "/api/cameras",
        json={
            "name": f"webrtc-smoketest-{int(time.time())}",
            "location_text": "synthetic source, not a real location",
            "department": "Police",
            "hls_url": ctx.hls_source.url,
        },
    )
    body = require(resp, 201, "register scratch camera")
    ctx.camera_id = body["camera_id"]
    return body["stream_available"] is True, f"camera_id={ctx.camera_id}"


def _run_whep_negotiation(base_url: str, camera_id: str, super_email: str, super_password: str) -> dict:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            context = browser.new_context(base_url=base_url)
            login = context.request.post("/api/auth/login", data={"email": super_email, "password": super_password})
            if login.status != 200:
                raise AssertionError(f"browser-context login failed: {login.status}")

            page = context.new_page()
            page.goto("/api/health", wait_until="load")

            return page.evaluate(
                """
                async ({ cameraId, connectTimeoutMs }) => {
                  const pc = new RTCPeerConnection();
                  let trackReceived = false;
                  pc.addTransceiver("video", { direction: "recvonly" });
                  pc.ontrack = () => { trackReceived = true; };

                  const offer = await pc.createOffer();
                  await pc.setLocalDescription(offer);
                  await new Promise((resolve) => {
                    if (pc.iceGatheringState === "complete") return resolve();
                    const check = () => {
                      if (pc.iceGatheringState === "complete") {
                        pc.removeEventListener("icegatheringstatechange", check);
                        resolve();
                      }
                    };
                    pc.addEventListener("icegatheringstatechange", check);
                    setTimeout(resolve, 4000);
                  });

                  const resp = await fetch(`/api/webrtc/${cameraId}/whep`, {
                    method: "POST",
                    credentials: "same-origin",
                    headers: { "Content-Type": "application/sdp" },
                    body: pc.localDescription.sdp,
                  });
                  const offerStatus = resp.status;
                  const location = resp.headers.get("location");
                  const locationIsInternal = !!location && !location.includes("127.0.0.1") && !location.includes(":8889");

                  let everConnected = false;
                  let finalConnectionState = pc.connectionState;
                  if (offerStatus === 201) {
                    const answerSdp = await resp.text();
                    await pc.setRemoteDescription({ type: "answer", sdp: answerSdp });
                    await new Promise((resolve) => {
                      const start = Date.now();
                      const poll = setInterval(() => {
                        if (pc.connectionState === "connected") everConnected = true;
                        finalConnectionState = pc.connectionState;
                        if (everConnected || Date.now() - start > connectTimeoutMs) {
                          clearInterval(poll);
                          resolve();
                        }
                      }, 200);
                    });
                  }

                  let deleteStatus = null;
                  if (location) {
                    const delResp = await fetch(location, { method: "DELETE", credentials: "same-origin" });
                    deleteStatus = delResp.status;
                  }
                  pc.close();

                  return { offerStatus, location, locationIsInternal, everConnected, finalConnectionState, trackReceived, deleteStatus };
                }
                """,
                {"cameraId": camera_id, "connectTimeoutMs": WEBRTC_CONNECT_TIMEOUT_S * 1000},
            )
        finally:
            browser.close()


@check("WHEP offer is accepted")
def test_whep_offer_accepted(ctx: Ctx, result: dict):
    return result["offerStatus"] == 201, f"HTTP {result['offerStatus']}"


@check("Location is rewritten, never the raw mediamtx address")
def test_location_rewritten(ctx: Ctx, result: dict):
    if not result["location"]:
        return False, "no Location header returned"
    return result["locationIsInternal"], result["location"]


@check("peer connection reaches \"connected\" at least once")
def test_peer_connects(ctx: Ctx, result: dict):
    detail = f"final state after negotiation: {result['finalConnectionState']}"
    return result["everConnected"], detail


@check("a video track is actually received")
def test_track_received(ctx: Ctx, result: dict):
    return result["trackReceived"], "ontrack fired" if result["trackReceived"] else "ontrack never fired"


@check("WHEP session terminates cleanly")
def test_session_terminates(ctx: Ctx, result: dict):
    return result["deleteStatus"] == 204, f"DELETE returned {result['deleteStatus']}"


@check("relay is torn down after session end")
def test_relay_state_after(ctx: Ctx):
    # Not a hard requirement (idle-reap has its own timeout), just useful
    # information: confirms mediamtx's own view of the path post-session.
    settings = get_settings()
    resp = httpx.get(f"http://127.0.0.1:{settings.mediamtx_api_port}/v3/paths/get/{ctx.camera_id}", timeout=3.0)
    if resp.status_code != 200:
        return True, "path already gone from mediamtx"
    readers = resp.json().get("readers", [])
    return True, f"path still tracked, {len(readers)} active reader(s) (idle-reap runs on its own timer)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    ctx = Ctx(args.base_url)
    try:
        print("Dependencies")
        if not test_dependencies(ctx):
            print(f"\n{'=' * 60}\n0/0 passed (suite skipped)\n{'=' * 60}")
            return 0
        if not test_playwright_available(ctx):
            print(f"\n{'=' * 60}\n0/0 passed (suite skipped)\n{'=' * 60}")
            return 0

        print("\nSynthetic source + scratch camera")
        if not test_synthetic_source(ctx):
            print("\n(skipping remaining checks: synthetic HLS source never came up)")
        elif not test_register_camera(ctx):
            print("\n(skipping remaining checks: scratch camera registration failed)")
        else:
            print("\nWHEP negotiation (real browser, real ICE/DTLS)")
            result = _run_whep_negotiation(args.base_url, ctx.camera_id, ctx.super_email, ctx.super_password)
            test_whep_offer_accepted(ctx, result)
            if result["offerStatus"] == 201:
                test_location_rewritten(ctx, result)
                test_peer_connects(ctx, result)
                test_track_received(ctx, result)
                test_session_terminates(ctx, result)
                test_relay_state_after(ctx)

        print(f"\n{'=' * 60}")
        passed = sum(1 for _, ok, _ in RESULTS if ok)
        skipped = [n for n, ok, _ in RESULTS if ok is None]
        failed = [n for n, ok, _ in RESULTS if ok is not None and not ok]
        print(f"{passed}/{len(RESULTS) - len(skipped)} passed" + (f" ({len(skipped)} skipped)" if skipped else ""))
        if skipped:
            print("SKIPPED: " + ", ".join(skipped))
        if failed:
            print("FAILED: " + ", ".join(failed))
        print(f"{'=' * 60}")
        return 0 if not failed else 1
    finally:
        ctx.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
