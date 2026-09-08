# WebRTC/WHEP relay: manual testing reference

The Live view's low-latency preview path. A browser cannot render raw RTSP,
so an ffmpeg subprocess pulls the registered RTSP endpoint over TCP and
republishes it into a locally-run **MediaMTX** instance, which serves real
WHEP/WebRTC to the browser. When a camera has no RTSP endpoint, the relay can
pull its HLS endpoint instead. Raw source URLs remain server-side.

The official catalogue's RTSP endpoints timed out on the network used for the
2026-08-31 test (see `docs/sandbox-access.md`), so the existing end-to-end WHEP
evidence exercised the HLS input fallback. The RTSP-to-WHEP selection and TCP
arguments have offline coverage; a real RTSP-sourced relay run remains open.

`FocusedPlayer.jsx` tries WebRTC first for the camera an operator has
focused; a one-shot negotiation failure falls back to the existing HLS
player, unchanged. The strip/grid tiles never attempt WebRTC -- only the
focused camera does. Analytics has a separate worker concurrency budget and
does not start or stop when focus changes.

## Setup

A local `mediamtx` binary is required (not bundled, not a Python
dependency):

```bash
brew install mediamtx     # macOS; see https://mediamtx.org for other platforms
which mediamtx             # confirm it's on PATH -- the backend spawns it by name
```

If it's missing, the backend logs a warning at startup and continues without
it. Cameras with HLS still fall back to HLS; an RTSP-only camera has no browser
fallback because browsers cannot render RTSP directly (see `main.py`'s
lifespan `try`/`except` around `webrtc_relay.ensure_mediamtx_running()`).

`ffmpeg` is already a dependency of this backend (normalisation, capture) --
nothing extra needed there.

## What starts, and when

- **mediamtx**: started once, at backend startup (`ensure_mediamtx_running`
  in `app/pipeline/webrtc_relay.py`), config generated to
  `multi-object-tracking/worker_logs/mediamtx.yml`. RTSP ingest, WHEP, and
  its control API are all bound to `127.0.0.1` only.
- **a per-camera ffmpeg relay**: started on demand, the first time a browser
  POSTs a WHEP offer for that camera (`ensure_relay_running`). Capped at
  `max_concurrent_webrtc_relays` (default 2) since only the focused camera
  in each operator view needs one; idle relays are reaped after
  `webrtc_relay_idle_timeout_seconds` (default 120s).
- Both are torn down cleanly on backend shutdown (a relay's only purpose is
  serving an in-progress browser preview) and any orphan left by a crashed
  previous run is killed at the next startup, via the module's own
  manifest (`multi-object-tracking/worker_logs/webrtc_manifest.json`) --
  same pattern as `analytics.py` and `investigate.py`, deliberately not
  merged with either.

## Endpoints and who can call them

| Endpoint | Auth | Notes |
|---|---|---|
| `POST /api/webrtc/{camera_id}/whep` | viewer clearance | body: raw SDP offer, `Content-Type: application/sdp`. Spawns/confirms the relay, waits for mediamtx to report the path ready, forwards the offer. Returns the SDP answer plus a `Location` pointing back through this same proxy (never mediamtx's raw address) -- `201`. |
| `DELETE /api/webrtc/{camera_id}/whep/{session_id}` | viewer clearance | proper WHEP session termination; idempotent (unknown/expired `session_id` still returns `204`). |

No audit event on either -- routine stream viewing isn't audited today
either (`hls_proxy.py` has none), so this stays consistent with that
existing precedent.

## Automated check: `backend/scripts/webrtc_relay_smoke_test.py`

Runs the HLS-input fallback chain end to end without depending on the sandbox
at all -- it builds a synthetic HLS source and registers/cleans up a scratch
camera itself:

```bash
cd backend
../.venv/bin/python scripts/webrtc_relay_smoke_test.py
```

SKIPs the whole suite (not a failure) if `mediamtx`, `ffmpeg`, or Playwright
aren't available. Reaching `"connected"` at least once is a pass; whether
the connection then holds is reported for information only, not asserted --
see "Known limitation" below for why.

## Verifying the relay mechanism directly (no browser, no backend)

Useful for isolating "is mediamtx/ffmpeg working at all" from "is the
backend proxy working":

```bash
mediamtx multi-object-tracking/worker_logs/mediamtx.yml &

# Any RTSP source works for this check -- a synthetic pattern avoids
# depending on the sandbox being up.
ffmpeg -re -f lavfi -i testsrc=size=640x480:rate=25 -c:v libx264 \
  -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:8554/testcam &

sleep 2
curl -s http://127.0.0.1:9997/v3/paths/get/testcam | jq .ready
# -> true
```

## Debugging a single negotiation by hand

For poking at one failure rather than running the whole suite above -- the
WHEP offer must be a real, complete SDP (ICE ufrag/pwd, DTLS fingerprint),
so this still has to go through a real browser context, e.g. with
Playwright:

```python
# in a page already logged in (cookie jar carries the session)
result = page.evaluate("""
  async (camera_id) => {
    const pc = new RTCPeerConnection();
    pc.addTransceiver("video", { direction: "recvonly" });
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    await new Promise((resolve) => {
      if (pc.iceGatheringState === "complete") return resolve();
      pc.addEventListener("icegatheringstatechange", () => {
        if (pc.iceGatheringState === "complete") resolve();
      });
      setTimeout(resolve, 4000);
    });
    const resp = await fetch(`/api/webrtc/${camera_id}/whep`, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/sdp" },
      body: pc.localDescription.sdp,
    });
    const location = resp.headers.get("location");
    await pc.setRemoteDescription({ type: "answer", sdp: await resp.text() });
    return { status: resp.status, location, connectionState: pc.connectionState };
  }
""", camera_id)
```

This is exactly what `webrtc_relay_smoke_test.py` above automates end to
end. Confirm with mediamtx's own API that a session shows up and disappears
cleanly:

```bash
curl -s http://127.0.0.1:9997/v3/paths/get/<camera_id> | jq '.readers'
```

**Open item, not yet resolved:** driving this same check through the actual
`frontend-v2` Live view under headless Chromium (Playwright, in this
project's own sandboxed shell tool) reproduced `connectionState` reaching
`"connected"` -- with `ontrack` firing and real media briefly flowing -- and
then dropping to `"disconnected"` roughly 1-2s later, consistently, across
repeated runs. The ICE candidates involved are UDP-only host candidates in
both cases (Chromium does not offer a TCP host candidate from page script,
so toggling mediamtx's `webrtcLocalTCPAddress` had no effect on this). This
looks like a loopback-UDP restriction specific to that headless/sandboxed
execution environment rather than a defect in the relay or proxy -- the
protocol exchange itself (offer, answer, ICE, DTLS) is demonstrably correct,
it is the *sustained* UDP flow that drops. `useWebRtcPlayer.js` now treats a
sustained `"disconnected"` (past a short grace period, in case it
self-recovers) the same as `"failed"` and falls back to HLS, so this
environment's flakiness degrades gracefully rather than freezing the
preview -- confirmed by observing the transport chip switch to
`"hls (fallback)"` after the grace window. **What's still open:** this has
not yet been confirmed to reproduce (or not) in an ordinary, non-sandboxed
desktop browser -- do that check before treating the low-latency path as
demo-proven, not just protocol-proven.

## Known limitation: the media plane is not proxied

The backend proxies and RBAC-gates only the WHEP *signaling* (the SDP
offer/answer, plain HTTP). The actual media -- RTP over ICE/DTLS/SRTP --
flows **directly** between the viewing browser and mediamtx's WebRTC
listener once negotiation finishes; it cannot be tunnelled through the
backend's HTTP proxy. Binding that listener to `127.0.0.1` is correct and
sufficient for this project's current same-machine dev/demo topology
(backend, mediamtx, and the browser all on one host). It would need a
reachable host/IP and ICE/NAT handling to serve a browser on a separate
machine -- a real constraint to design around in a future deployment, not
something this relay solves.
