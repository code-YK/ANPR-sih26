# Sandbox Access Runbook

> **Scope note (2026-09-12).** SIH26127 supplies **no dataset and no sandbox** -
> the problem-statement listing records `Dataset Link: N/A`. This document
> describes the HTTP camera-catalogue connector inherited from a previous
> programme, which survives as **one source adapter among several**, alongside
> manual onboarding, CSV bulk import, and the recorded-feed relay used by
> government mode. Nothing here is an SIH26127 requirement. See
> [ADR 0004](decisions/0004-sih26127-rescope.md).

Status: local access observations recorded 2026-08-28; security review updated 2026-08-30; sandbox access model replaced 2026-09-01 (see bottom section — the catalogue transport gap below is now resolved).

This is a redacted development runbook for the current sandbox. It records what a team member observed from a local network; it is not an official protocol specification or proof of portal entitlement. The official resource guide remains authoritative. See [source-register.md](source-register.md).

## Security boundary

Obtain the catalogue, dashboard, and per-camera endpoint values only through the approved team channel or participant portal. Never commit service hosts, RTSP/WebRTC/HLS URLs, token-bearing URLs, copied catalogue responses, or downloaded footage.

Set local values without Markdown brackets or link syntax:

```bash
export SENTINEL_CATALOGUE_URL='https://provided-outside-git.invalid/api/ingest'
export SENTINEL_BROWSER_BASE_URL='https://provided-outside-git.invalid'
```

The literal syntax is `https://host/path`, not `[https://host/path](https://host/path)`.

## Confirmed working checks

### Read redacted catalogue structure

This direct catalogue request succeeded without a bearer token during the 2026-08-28 check. It returned 30 camera entries at that time. This does not establish participant-portal access or guarantee that the policy will remain unchanged.

```bash
curl --fail-with-body --silent --show-error \
  "${SENTINEL_CATALOGUE_URL}" |
jq '{
  camera_count: (.cameras | length),
  camera_fields: (.cameras[0] | keys)
}'
```

Expected fields include camera identity/location, reported media properties, and `rtsp_url`, `webrtc_url`, and `hls_live_url`. Do not print or persist endpoint values in routine logs.

### Browser preview over HTTPS

The browser dashboard and per-camera page were reachable through HTTPS. Use the page below for operator preview, replacing `1` with the catalogue camera ID:

```text
${SENTINEL_BROWSER_BASE_URL}/camera/1
```

The camera page uses an HTTPS `/stream/<id>` browser fallback. This bounded request checks its response without saving media:

```bash
curl --silent --show-error \
  --dump-header - \
  --output /dev/null \
  --range 0-0 \
  --max-time 10 \
  "${SENTINEL_BROWSER_BASE_URL}/stream/1"
```

The observed response was `206 Partial Content` with `Content-Type: video/mp4` and `Accept-Ranges: bytes`.

### Resolve and verify the HLS playlist

The observed `hls_live_url` value for Camera 1 was a relative playlist path, not a complete URL. Resolve it against the public HTTPS browser base before use. This is a candidate fallback and is not yet confirmed as a worker-facing transport.

```bash
CAMERA_ID='1'

HLS_PATH="$(
  curl --fail-with-body --silent --show-error "${SENTINEL_CATALOGUE_URL}" |
  jq -er --arg camera_id "${CAMERA_ID}" \
    '.cameras[] | select(.id == $camera_id) | .hls_live_url'
)"

case "${HLS_PATH}" in
  http://*|https://*) HLS_URL="${HLS_PATH}" ;;
  *) HLS_URL="${SENTINEL_BROWSER_BASE_URL}${HLS_PATH}" ;;
esac

curl --silent --show-error \
  --range 0-1023 \
  --max-time 10 \
  "${HLS_URL}" |
head -n 1
```

Proceed only when the command prints `#EXTM3U`. A timeout, HTML response, empty response, or another content type is a failed HLS verification and must be surfaced as degraded health rather than silently replaced with a download path.

## Evidence boundary

Do not download or record sandbox footage. Routine diagnostics may inspect bounded response headers or an HLS manifest without persisting media, as shown above. Build repeatable decoder and failure tests with a synthetic or explicitly approved representative stream. Any exceptional frame capture requires separate human approval for its exact purpose and retention; this runbook does not grant it.

## Confirmed limitations

| Path | Result from the 2026-08-28 local check | Implication |
|---|---|---|
| RTSP endpoint from the catalogue | TCP connection timed out before RTSP negotiation or authentication. | Cannot yet use RTSP/TCP for inference from that network. |
| `webrtc_url` from the catalogue | HTTP connection timed out before SDP/WebRTC negotiation. | Cannot yet use low-latency WebRTC preview from that network. |
| `hls_live_url` from the catalogue | Camera 1 returned a relative playlist path; no successful manifest retrieval has been recorded yet. | Resolve it against the HTTPS browser base and verify `#EXTM3U` before any use. |
| HTTPS `/stream/<id>` with `curl -O` | The server returned an 8 MiB partial MP4 response, not the complete object. | Never use it as a media-download or analytics path. |
| `ffprobe` on that 8 MiB file | `moov atom not found`. | The partial MP4 lacks the index metadata and cannot yield reliable media properties. |

The HTTPS fallback is suitable for a browser player, whose range requests can obtain the MP4 index and the portions needed for viewing. It is not an approved substitute for real-time worker ingestion. `SIH-ING-010` and `SIH-ING-015` prohibit a download-then-analyse design.

## Safe endpoint extraction for diagnostics

Use these only in a local terminal. Do not echo their values into shared logs or commit them to fixtures.

```bash
RTSP_URL="$(
  curl --fail-with-body --silent --show-error "${SENTINEL_CATALOGUE_URL}" |
  jq -er '.cameras[] | select(.id == "1") | .rtsp_url'
)"

WEBRTC_URL="$(
  curl --fail-with-body --silent --show-error "${SENTINEL_CATALOGUE_URL}" |
  jq -er '.cameras[] | select(.id == "1") | .webrtc_url'
)"
```

## Next required action

Obtain an authorised, reachable worker-facing transport: RTSP over TCP, verified WHEP/WebRTC, or HLS. The source owner must expose the required port or provide an HTTPS-native endpoint. Until then, use a local protocol-compatible synthetic stream for worker development and keep the official HTTPS path limited to browser-preview validation.

## WebRTC/WHEP browser preview (2026-08-31)

The two rows above are still true: the catalogue's own `webrtc_url` and raw RTSP both time out before protocol negotiation from this network. Rather than wait on that, the Live view's low-latency preview is served by a **local MediaMTX relay** instead: ffmpeg pulls the one transport that does work (the same `hls_live_url` the ANPR/person workers already consume directly) and republishes it into a locally-run MediaMTX instance over RTSP, which then serves real WHEP back out. See `docs/webrtc-relay-testing.md` for setup and verification, and `backend/app/pipeline/webrtc_relay.py`'s module docstring for the implementation.

This is not a substitute for the still-open catalogue transport gap above — it is a same-machine workaround. Everything MediaMTX exposes (its RTSP ingest, WHEP, and control API) is bound to `127.0.0.1` only, and the WebRTC *media* plane (unlike the SDP signaling, which the backend proxies and RBAC-gates the same as HLS) is never tunnelled through the backend — it flows directly between the viewing browser and MediaMTX's WebRTC listener. That is sufficient for this project's current same-machine dev/demo topology (backend, MediaMTX, and the browser all on one host) but would need a reachable host/IP and ICE/NAT handling to serve a browser on a different machine — a real limitation, not something this design solves.

## 2026-09-01 sandbox update — direct-media access now working

The source owner issued an updated integrator's guide and access credentials through the approved team channel. The catalogue transport gap recorded above (RTSP/WHEP timing out before negotiation) is resolved under this new model — it was a network/access-model issue on the old sandbox, not a protocol limitation on our side. Set local values the same way as above, without Markdown link syntax, and never commit them:

```bash
export SANDBOX_CATALOGUE_URL='https://provided-outside-git.invalid/cameras.json'
export SANDBOX_BROWSER_BASE_URL='https://provided-outside-git.invalid'
export SANDBOX_ACCESS_PASSWORD='provided-outside-git'
export SANDBOX_STREAM_HOST='provided-outside-git'
```

**What changed:**

- **Auth model.** The catalogue and HLS host now sit behind a password-gated session, not the old no-auth/bearer-header model. `POST {SANDBOX_ACCESS_PASSWORD}` to `{SANDBOX_BROWSER_BASE_URL}/auth/login` for a session cookie; reuse that cookie/client for the catalogue fetch and every HLS request. Implemented in `sandbox_login()` in `backend/app/pipeline/catalogue.py`; the HLS proxy (`backend/app/routers/hls_proxy.py`) logs in once per fresh upstream client.
- **Catalogue shape.** Each entry is now only `{"id": "cam01", "name": "..."}` — no per-camera media URLs, no reliable sequential `number` field. `camera_number` is derived from the id's own numeric suffix (`cam01` → `1`); RTSP and WHEP URLs are built from the fixed templates the guide documents, keyed on that id. See `parse_gov_feed_catalogue()` in `catalogue.py`.
- **RTSP/WHEP are unauthenticated and reachable.** Served directly off a public IP (`SANDBOX_STREAM_HOST`), separate from the CDN/browser host — confirmed with a real, unauthenticated `ffprobe`/RTSP probe against multiple cameras (h264, 1920x1080 or 1280x720/960, 25-50 fps depending on camera). HLS stays on the password-gated CDN/browser host.
- **HLS segments are AES-128 encrypted**, confirmed live (`#EXT-X-KEY:METHOD=AES-128,URI="/enc.key"`). The key URI is an *absolute* path, which an HLS player resolves against the player's own page origin per spec, not the playlist's directory — it would never reach our authenticated proxy from a real browser. `hls_proxy.py` rewrites any absolute-path `URI="..."` attribute in the m3u8 to route through the same per-camera-viewer proxy path (`_rewrite_absolute_uris`), and resolves the rewritten request against the upstream's own scheme+host root rather than the camera's segment directory. Verified: the decrypted segment probes as valid H.264 with `ffprobe`, and real video renders in-browser for multiple cameras.
- **Streaming guidance from the guide** (worth keeping in mind for anything reading these streams directly, not just the proxy): force RTSP over TCP, drive timing from PTS rather than frame arrival time, reconnect with backoff, tolerate scene discontinuities at stream loop points, never assume a constant frame rate, and don't trust `CAP_PROP_FPS`.

**Current status:** all 30 cameras (`cam01`..`cam30`) synced via `POST /api/sync`, all report `stream_available` and `analytics_stream_available`. RTSP probe spot-checked across the full id range (`cam02`, `cam10`, `cam15`, `cam20`, `cam25`, `cam30`, plus `cam01`/`cam03`/`cam04`/`cam05`) — all reachable over real RTSP. HLS playback (including the AES-128 key fetch and decrypt) verified end-to-end in a real browser for multiple cameras. Live ANPR/analytics has not yet been enabled against this feed — that is a deliberate, separate decision (it processes real people and vehicles), pending explicit sign-off, not a technical blocker.
