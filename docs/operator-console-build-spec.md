# Operator Console: UI Build Spec

> **Historical build spec.** Written during an earlier programme whose
> `Model N` vocabulary does not exist in SIH26127. Retained because it records
> *why* this slice is built the way it is - the reasoning is still current even
> where the naming is not. See [ADR 0004](decisions/0004-sih26127-rescope.md)
> for the mapping, and [requirements.md](requirements.md) for current IDs.

Status: implemented and merged. This records what was built and why, not a
forward-looking plan — see `PROJECT_STATE.md` for current status and
`docs/anpr-pipeline-build-spec.md` for the backend vertical slice this UI sits on.

## Stack

React 19 + Vite, `react-router-dom` v7, `react-leaflet` v5, `hls.js` v1.7.
No TypeScript, Tailwind, Redux, or SSR — the spec's original React 18 target
moved to 19 because Vite's current template and react-leaflet 5/react-router
7 pull it in with no conflicts. Lives at `frontend-v2/`; the vanilla
UI (`frontend/`) remains as migration reference only. It is no longer served because it has no authentication flow; `frontend-v2/` is the only application shell.

## Routes

`/live` (default), `/alerts`, `/journey` and `/journey/:plate`, `/watchlist`,
`/registry/*` (nested: camera list, GIS map, gap analysis — the ported
original UI).

## Backend prerequisites this UI depends on

- `GET /api/vehicles/{plate}/journey` — ordered stops for the Journey view
- `AlertOut` enriched with joined `plate`, `camera_name`, `location_text`,
  `department`, `reason_code`, `severity` (see `backend/app/routers/alerts.py`)
- `cameras.analytics_enabled` column + auto-start supervisor (§2.4 of
  `docs/anpr-pipeline-build-spec.md`) — the Live view's ANPR toggle sets this column
  and requests an immediate start; the supervisor reconciles that intent in
  the current session, while backend startup clears stale persisted intent
- `backend/app/routers/hls_proxy.py` — see below

## Live view

`frontend-v2/src/views/Live/`: `LiveView.jsx` (orchestrator), `CameraTile.jsx`,
`FocusedPlayer.jsx`, `AnalyticsToggle.jsx`, plus `hooks/useHlsPlayer.js` and
`hooks/useVisibility.js`.

- Grid of `CameraTile`s; clicking one promotes it to a large `FocusedPlayer`
  and demotes the rest to a strip, with a right panel (metadata badges,
  `AnalyticsToggle`, recent sightings linking into Journey).
- User-selectable concurrency cap of 1, 3, 6, or 9 concurrent `hls.js`
  instances, defaulting to 9 and shared between the focused player and the
  strip — the focused camera always gets a slot;
  remaining slots go to strip tiles currently visible in the viewport
  (`useVisibility`, an `IntersectionObserver` wrapper). Scrolling
  mounts/unmounts players as tiles enter/leave the viewport; `useHlsPlayer`
  tears down (`hls.destroy()`, never just pauses) whenever its `src` goes
  null, which is the only thing that ever unmounts a player.
- `FocusedPlayer` surfaces hls.js's own `.latency` estimate as `live −Ns`
  rather than hiding HLS's inherent 6-15s latency.
- `AnalyticsToggle`: ANPR row toggles the `analytics_enabled` operational-intent
  column via `PUT /api/cameras/:id`, requests immediate start/stop for responsive
  feedback, and leaves the supervisor to reconcile the state afterward;
  Person row does a direct start/stop against `/api/analytics/start|stop`
  since person-counting has no persistent intent column. Both rows poll
  `GET /api/analytics/status/:camera_id` every 5s for their running state.

### HLS proxy (`backend/app/routers/hls_proxy.py`)

Not in the original plan — added after live-browser testing showed the
sandbox's gateway sends a **duplicated** `Access-Control-Allow-Origin`
header (`*, *`) on every response, confirmed with `curl -v` against the raw
stream URL, not a proxy artifact. That's malformed per the CORS spec, and
every CORS-enforcing browser rejects it outright: hls.js could never load
`camera.hls_url` directly from a browser, even though the same URL works
fine for OpenCV/ffmpeg (which don't enforce CORS) in the ANPR/person
workers.

The proxy relays the m3u8 playlists and segments through the backend
(`/api/hls/{camera_id}/{viewer}/{filename}`), so the browser only ever talks
to our own origin. It holds one persistent `httpx.AsyncClient` per viewer
session so the
gateway's `cookieCheck` cookie (set on the first redirect) is still present
on later segment requests, and caches each camera's `hls_url` in memory
after the first DB lookup — the sandbox streams are low-latency HLS with
~0.3s parts, and a DB round trip on every single part request is latency
that window can't spare. `frontend-v2/src/api.js`'s `hlsProxyUrl()` is the
only thing that constructs the proxied URL; `CameraTile`/`FocusedPlayer`
never reference `camera.hls_url` directly for playback.

### Session expiry and reconnection (revised 2026-08-30)

The first version of this proxy shared one upstream client per camera and
left hls.js in low-latency mode. Both were wrong, found by watching a
player rather than trusting the initial "readyState 4" check:

- **Playback froze permanently ~15s in** (readyState 4 → 2, `currentTime`
  stuck). LL-HLS parts here have `PART-TARGET`~0.32s and frequently expired
  upstream before the relay could fetch them — those were the `502`s an
  earlier version of this document wrote off as harmless. Fixed by turning
  `lowLatencyMode` off: full ~10s segments survive the extra hop, at the
  cost of latency against footage that is recorded and looped anyway.
- **It still froze, ~40s in.** Measured against the *raw* gateway with a
  single consumer and no proxy, across nine cameras: the gateway serves a
  structurally valid but **empty** media playlist once a session expires,
  which is not an error hls.js can catch, so playback simply stops. The
  Python workers already survived this by reconnecting (their logs show
  dozens of reconnects per run); the browser had no equivalent.

So the proxy became viewer-scoped (`/api/hls/{camera}/{viewer}/{file}`,
token in the path so relative HLS URLs inherit it) and `useHlsPlayer` grew
a stall watchdog that rebuilds against a fresh session with 2s→30s backoff,
mirroring what the workers do. The proxy turns an empty playlist into a
`503` specifically so the client can distinguish it. Reconnect count and a
"reconnecting…" state are shown in the UI rather than hidden — with this
gateway a long-running player genuinely is a series of sessions, and
presenting it as one unbroken feed would misrepresent it.

**Not yet verified end-to-end.** The sandbox gateway went fully down
(every camera and the ingest API returning 502) before the reconnect path
could be observed recovering a real stall. The stall itself, the empty-
playlist behaviour, and the backoff logic were each verified; the
recovery-after-stall path was not.

## Detector view

`views/Live/DetectorView.jsx` + `/api/analytics/telemetry|snapshot|stream`.

The workers run a full YOLO track on every frame but originally reported
only their end product — a confirmed plate, or a person-count window. On
the many sandbox cameras surveyed as unable to resolve a plate, that meant
a healthy worker could run for an hour and show nothing, indistinguishable
from a broken one. Detection was happening the whole time with nowhere to
appear.

The right panel now shows the worker's own annotated frames (boxes, track
ids, and the plate reader's current belief — confirmed plates plain,
uncorroborated ones suffixed `?`) plus rolling counts. It is labelled a
detector view, not an overlay, because the worker holds its own connection
to the stream and its frames are seconds apart from the browser's player.

When a camera is tracking vehicles but reporting no plates, the panel says
so explicitly and points at the ANPR-viability survey, so "no plates here"
reads as the expected result on an unviable camera rather than a failure.

## Supervisor reconciliation

The auto-start supervisor originally only ever *started* workers, which hid
two failures: turning ANPR off left the worker running forever holding a
slot, and an ANPR-viable camera enabled later could never start because
already-running non-viable cameras held every slot (the viability ordering
applied only at cold start). It now reconciles both directions against
`analytics_enabled` each tick, and the UI distinguishes "queued behind the
concurrency cap" from "not running" — previously both rendered as an
identical grey dot.

## Scope boundary and mandatory gaps

Next.js/SSR, WebSockets/SSE, face recognition, video recording/clip export,
and past-footage playback are not Phase 1 dependencies. Department authentication,
RBAC, role-aware controls, state-change audit, database-trigger audit-row
immutability, and a digest-verifiable super-admin audit archive are implemented
under ADR 0003; immutable external retention and production identity hardening
remain gaps. Tablet/mobile
responsiveness and accessibility also lack recorded acceptance evidence.

## Verification

`backend/scripts/smoke_test.py` covers a useful API slice but not every React
interaction. Current evidence includes authenticated GIS browser verification
(`artifacts/public/checkpoint-c3/gis-coverage-layer-browser-2026-08-31.md`),
synthetic live-grid/reconnect screenshots and automated reliability results
(`artifacts/public/checkpoint-c7/run-1/README.md`), and the C6 three-camera
live pipeline/reconciliation packet. The repaired RBAC and general non-ML API
suites also pass as recorded in `artifacts/public/checkpoint-c3/`. The focused
WebRTC path has protocol/RBAC verification but still needs a normal desktop-
browser sustained-playback check; official-feed and final-recording evidence
remain separate gaps.
