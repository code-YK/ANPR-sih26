// Ported from frontend/app.js's api() helper -- same base path, same error
// shape (HTTP status + parsed `detail` when present), same content-type
// sniffing so a plain-text/PDF response doesn't get force-parsed as JSON.
export const API = "/api";

// --------------------------------------------------------------------------
// Client-side API-call log, for the Logs panel's "FE" tab.
//
// Every call through api() records one entry (method, path, status, ms, and
// any error) into a bounded ring buffer. This is the frontend's own view of
// its traffic -- the counterpart to the backend/worker streams the panel
// shows in its other tabs -- and it is captured here, at the single choke
// point every request already passes through, rather than by patching fetch
// globally. Buffer only; nothing is sent anywhere.
// --------------------------------------------------------------------------
const FE_LOG_MAX = 500;
const _feLogs = [];
const _feSubs = new Set();
let _feSeq = 0;

function recordFeLog(entry) {
  const row = { seq: ++_feSeq, ts: Date.now() / 1000, ...entry };
  _feLogs.push(row);
  if (_feLogs.length > FE_LOG_MAX) _feLogs.shift();
  for (const cb of _feSubs) {
    try {
      cb(row);
    } catch {
      // a bad subscriber must not break request logging
    }
  }
}

export function getFeLogs() {
  return _feLogs.slice();
}

export function subscribeFeLogs(cb) {
  _feSubs.add(cb);
  return () => _feSubs.delete(cb);
}

export async function api(path, opts = {}) {
  const method = (opts.method || "GET").toUpperCase();
  const started = performance.now();
  let resp;
  try {
    resp = await fetch(API + path, { credentials: "same-origin", ...opts });
  } catch (err) {
    // A request cancelled because its view unmounted (usePolling's signal) is
    // housekeeping, not a failure; logging it as status 0 would fill the FE tab
    // with false network errors every time an operator changes camera.
    if (err?.name !== "AbortError") {
      // Network-level failure (server down, connection reset) -- never reached
      // the status line, so log it distinctly as status 0.
      recordFeLog({ method, path, status: 0, ms: Math.round(performance.now() - started), error: String(err) });
    }
    throw err;
  }
  const ms = Math.round(performance.now() - started);
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = JSON.stringify(body.detail ?? body);
    } catch {
      // response wasn't JSON; keep statusText
    }
    recordFeLog({ method, path, status: resp.status, ms, error: detail });
    if (resp.status === 401 && path !== "/auth/login") {
      window.dispatchEvent(new CustomEvent("sentinel:unauthorised"));
    }
    throw new Error(`${resp.status}: ${detail}`);
  }
  recordFeLog({ method, path, status: resp.status, ms });
  const ct = resp.headers.get("content-type") || "";
  if (resp.status === 204) return null;
  return ct.includes("application/json") ? resp.json() : resp.text();
}

// The gateway's edge sends a malformed, duplicated Access-Control-Allow-Origin
// header (confirmed with `curl -v` against the raw stream URL) that every
// CORS-enforcing browser rejects outright -- so hls.js can never load
// a raw camera URL directly from here. The backend's /hls proxy (see
// app/routers/hls_proxy.py) relays the same playlist/segments same-origin,
// sidestepping the browser's CORS check entirely.
// `viewer` is an opaque per-player token. It scopes the backend's upstream
// connection so two players never share one gateway session (they would
// fight over its playback position), and changing it is how a stalled
// player asks for a genuinely fresh session on reconnect.
// Video is fetched from a DIFFERENT ORIGIN than the rest of the API in dev,
// and that is deliberate. A browser allows only ~6 concurrent connections
// per origin on HTTP/1.1. The Live view can hold nine HLS players open, and
// against this sandbox's slow gateway each segment fetch occupies its
// connection for seconds -- so on a single origin every other request
// (detector frames, telemetry, alerts) queues behind video. Measured with
// the grid streaming: a 58KB detector frame took 2.0s and a 400-byte
// telemetry poll 22s, while the detector itself was running at 24 fps. The
// frames were never late; they could not get through the connection queue.
//
// localhost:5173 and 127.0.0.1:8000 are distinct origins to the browser, so
// each gets its own connection pool: video can saturate its own without
// starving the API. This is the standard HTTP/1.1 sharding workaround; the
// real fix is HTTP/2 multiplexing, which needs TLS and an HTTP/2-capable
// server (uvicorn is HTTP/1.1 only).
//
// In a production build the app is served by FastAPI from this same origin,
// so MEDIA_ORIGIN is empty and these stay same-origin relative URLs exactly
// as before -- no CORS request is made.
const MEDIA_ORIGIN = import.meta.env.DEV
  ? `${window.location.protocol}//${window.location.hostname}:8000`
  : "";

export function hlsProxyUrl(camera, viewer = "default") {
  return camera?.stream_available
    ? `${MEDIA_ORIGIN}${API}/hls/${camera.camera_id}/${viewer}/index.m3u8`
    : null;
}

// WHEP signaling only (see backend/app/routers/webrtc.py) -- a fetch() POST,
// not a <video src>, so this never needs the MEDIA_ORIGIN dev-sharding
// applied to hlsProxyUrl above (that exists purely to spread HTTP/1.1's
// per-origin connection cap across many concurrent segment fetches; a
// single SDP offer/answer exchange has no such contention).
export function webrtcWhepUrl(camera) {
  return camera?.webrtc_preview_available ? `${API}/webrtc/${camera.camera_id}/whep` : null;
}

// Same cross-origin-in-dev reasoning as hlsProxyUrl -- a plain <video src>
// or <img src> is a browser-issued subresource fetch, not a fetch() call,
// so api()'s credentials option never applies to it. The session cookie
// still rides along because localhost:5173 and localhost:8000 are same-site
// (SameSite only cares about the registrable domain, not the port).
export function recordingMediaUrl(recordingId) {
  return `${MEDIA_ORIGIN}${API}/investigate/recordings/${recordingId}/media`;
}

export function trackThumbUrl(runId, trackRef) {
  return `${MEDIA_ORIGIN}${API}/investigate/runs/${runId}/tracks/${trackRef}/thumb`;
}

// The detector's annotated frames, as one long-lived MJPEG stream -- on the
// media origin, never the app origin. This is not a style preference: the
// stream does not end while a worker runs, and on the app origin each open
// one permanently holds one of the browser's ~6 HTTP/1.1 connections to it.
// Measured on this console: with the stream on /api, a handful of revisits to
// a camera left /api/auth/me unable to get a connection at all (aborted at 8s)
// while the backend answered the same request from the shell in 0.3s -- every
// poll queued, the detector sat on "checking", and even a page navigation
// hung waiting for a socket. frontend-v5 has always served it from here.
// `key` only forces a fresh connection (a new run, or a retry).
export function mjpegUrl(cameraId, mode, key) {
  return `${MEDIA_ORIGIN}${API}/analytics/stream/${encodeURIComponent(cameraId)}?mode=${mode}&k=${encodeURIComponent(key)}`;
}

// The evidence crop stored for a confirmed sighting. Same cross-origin-in-dev
// reasoning as trackThumbUrl above: a plain <img src> is a browser-issued
// subresource fetch, so api()'s credentials option never applies to it, and
// the session cookie rides along because the two dev hosts are same-site.
// Authorisation is rechecked server-side per request (see
// sightings.py's /sightings/{id}/evidence), and the endpoint 404s once the
// retention window has actually deleted the file -- so a thumbnail that fails
// to load is a real answer, not a bug to paper over.
export function evidenceUrl(sightingId) {
  return `${MEDIA_ORIGIN}${API}/sightings/${sightingId}/evidence`;
}
