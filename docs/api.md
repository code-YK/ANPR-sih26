# API and Event Contracts

Status: Current unversioned surface documented; target `/api/v1` contract remains draft

This document records the implemented unversioned surface and the provider-neutral target contract. The stack is fixed by ADR 0002, but the target versioned contract has not been implemented or frozen.

## Implemented API (current)

The unversioned implementation below includes registry/onboarding/reporting plus a partial observation, watchlist, alert, analytics, and trajectory slice. It is not the same as the target `/api/v1` contract later in this file, and neither surface is complete against the requirement ledger.

```
GET  /api/cameras                 list + filter (q, department, camera_type, anpr_viable, is_live)
GET  /api/cameras/export          filtered, department-scoped CSV/JSON registry download (?format=csv|json)
POST /api/cameras                 manual onboarding -- register a camera not in the sandbox catalogue
GET  /api/cameras/:id             single camera
GET  /api/cameras/:id/health-history bounded, department-scoped probe observation history (?limit=1..500)
PUT  /api/cameras/:id             operator field updates
POST /api/cameras/bulk            validated CSV create/update import
POST /api/sync                    re-run catalogue sync (Stage 1)
POST /api/catalogue-sources       register a named, credentialed camera source -- see note below
GET  /api/catalogue-sources       list registered sources (super admin, no secrets)
GET  /api/catalogue-sources/:id   single source (super admin, no secrets)
PUT  /api/catalogue-sources/:id   partial update; omitted auth_secret leaves it unchanged
DELETE /api/catalogue-sources/:id 409 if any camera still references it -- deactivate instead
POST /api/catalogue-sources/:id/sync  read-only per-source sync, see note below
POST /api/probe                   re-run stream probe (Stage 2; all or one via ?camera_id=)
POST /api/geocode                 re-run geocoding (Stage 4; all or one via ?camera_id=, ?force=)
GET  /api/geocode/search          authenticated free-text place search used by the registry map picker (?q=)
POST /api/survey/capture          re-run frame capture (Stage 3; all or one via ?camera_id=)
GET  /api/survey/:id/frame        fetch the captured survey still for a camera
GET  /api/gap-analysis            report data as JSON
GET  /api/gap-analysis/export     HTML/PDF (?format=html|pdf)

POST /api/sightings                observation ingestion from the analytics worker; matches watchlist, creates a deduped Alert
GET  /api/sightings                search (?plate=, ?camera_id=, ?since=, ?until=)
GET  /api/watchlist                list (?active=, ?plate=)
POST /api/watchlist                create one entry
PUT  /api/watchlist/:id            update
DELETE /api/watchlist/:id          delete
POST /api/watchlist/bulk           CSV import (always inserts; no update-by-key like cameras/bulk)
GET  /api/alerts                   list (?status=, ?camera_id=)
POST /api/alerts/suspicious        worker-token-only suspicious-person alert; no identity, watchlist, or journey link
POST /api/alerts/:id/acknowledge
POST /api/alerts/:id/resolve
POST /api/analytics/start          launch a worker subprocess for ?camera_id=, ?mode=vehicle|person|suspicious (default vehicle); workers prefer RTSP/TCP, use HLS as a bounded fallback/time anchor when available, and are also launched by the supervisor after an operator enables cameras.analytics_enabled in the current backend session
POST /api/analytics/stop           stop it (?camera_id=, ?mode=)
GET  /api/analytics/status         list running workers, all cameras/modes (or /status/:camera_id for one camera's modes)
POST /api/analytics/counts         periodic aggregate from a non-ANPR worker (person mode); never writes to sightings
GET  /api/analytics/counts         list posted aggregates (?camera_id=)
GET  /api/vehicles/:plate/journey  ordered, camera-joined movement history for one plate (empty journey if never seen, not a 404)

POST /api/investigate/recordings                        upload (multipart, operator clearance); normalises + hashes; dedups by content
GET  /api/investigate/recordings                         department-scoped list (?status=)
GET  /api/investigate/recordings/:id                     detail
DELETE /api/investigate/recordings/:id                   department admin / super admin; cascades runs/tracks, removes files
GET  /api/investigate/recordings/:id/media               Range-capable (206) playable file
POST /api/investigate/recordings/:id/runs                enqueue an ingest run ({"kind": "vehicle"|"person"})
GET  /api/investigate/recordings/:id/runs                list runs for a recording, newest first (lets a reloaded page recover in-progress state)
GET  /api/investigate/runs/:id                           status + progress (queue_position while queued)
POST /api/investigate/runs/:id/cancel
GET  /api/investigate/runs/:id/tracks                    never includes boxes/embedding (deferred columns)
GET  /api/investigate/runs/:id/tracks/:track_ref/boxes   fixed 10Hz timeline, normalised 0..1000
GET  /api/investigate/runs/:id/tracks/:track_ref/thumb   best-confidence crop, JPEG
POST /api/investigate/runs/:id/tracks/:track_ref/link    operator confirms track -> subject
POST /api/investigate/subjects                           create a person/vehicle of interest
POST /api/investigate/search/plate                       exact + pg_trgm fuzzy, department-scoped
POST /api/investigate/search/person                      multipart photo in; person tracks ranked by appearance similarity, department-scoped

POST /api/investigate/runs/:id/chunk                     worker-token only, seq-idempotent finalised-track batch
POST /api/investigate/runs/:id/heartbeat                 worker-token only, keeps a quiet run from looking stalled
POST /api/investigate/runs/:id/complete                  worker-token only, chunk-count reconciliation

GET  /api/analytics/telemetry/:camera_id   what the detector is seeing now (?mode=vehicle|person)
GET  /api/analytics/snapshot/:camera_id    latest annotated frame, boxes drawn (?mode=)
GET  /api/analytics/stream/:camera_id      continuous MJPEG detector view from worker snapshots (?mode=)
GET  /api/hls/:camera_id/:viewer/:filename same-origin HLS relay for browser playback -- see note below
POST /api/webrtc/:camera_id/whep           WHEP offer -- negotiates the local low-latency relay, see note below
DELETE /api/webrtc/:camera_id/whep/:session_id  WHEP session teardown

POST /api/auth/login                       create an HttpOnly browser session
POST /api/auth/logout                      revoke the current session
GET  /api/auth/me                          current identity, role, and department grants
GET  /api/auth/registration-options        public active-department list for registration
POST /api/registration-requests            public employee/department-admin access request
GET  /api/departments                      active departments visible to the current user
POST /api/admin/departments                create department (super admin)
GET  /api/admin/registration-requests      list requests within the current admin's authority
POST /api/admin/registration-requests/:id/approve
POST /api/admin/registration-requests/:id/reject
GET  /api/admin/users                      users within the current admin's authority
PUT  /api/admin/users/:id/status           enable/disable account
PUT  /api/admin/users/:id/grants/:department
DELETE /api/admin/users/:id/grants/:department
GET  /api/admin/audit-events               role-scoped, offset-paginated access/change audit (?limit=1..1000, ?offset>=0)
GET  /api/admin/audit-events/export        super-admin-only canonical NDJSON audit archive with SHA-256 response header
POST /api/admin/audit-events/archive       super-admin-only delivery of canonical NDJSON + detached SHA-256 to configured external retention mount

GET  /api/copilot/status                   whether the assistant is configured on this server
POST /api/copilot/chat                     conversational turn; streams Server-Sent Events
```

The surface is authenticated and department-scoped according to ADR 0003, but still diverges from the target contract's resource names, error shape, pagination, and `/api/v1` base path. Login, registration submission/options, and static login assets are public. Health, OpenAPI/Swagger, application data, media relays, and administration require authentication. A live OpenAPI document is served at `/docs` and `/openapi.json` after login. Successful authenticated metadata `GET` calls and authentication/authorisation denials append an audit event using the route template only; query values and raw path parameters are never recorded. HLS/media and high-frequency telemetry *successful reads* are excluded from per-request read audit to avoid unbounded audit volume; their denials are retained. Database migration `202608311800` rejects application-role updates and deletes of `audit_events` (except the existing account-deletion foreign-key actor-reference cleanup); a database superuser can still bypass database controls. External archive delivery is implemented, but immutable retention exists only when `AUDIT_ARCHIVE_DIR` is an approved WORM/object-lock mount or service.

### Copilot (conversational assistant)

`POST /api/copilot/chat` takes `{"message": str, "transcript": [{"role": "user"|"assistant", "content": str}]}` and returns `text/event-stream`. The backend holds **no conversation state**: the transcript is replayed by the browser on each request (capped at 40 turns, 4000 characters per message), so a conversation ends with the page load. A `system` role is not accepted in `transcript` and is rejected with 422, so a client cannot inject instructions ahead of the server's own system prompt.

Each SSE frame is one JSON object: `{"type":"token","text":...}`, `{"type":"tool_start","tool":...,"arguments":{...}}`, `{"type":"tool_result","tool":...,"render":...,"result":{...}}`, `{"type":"error","message":...}`, `{"type":"done"}`. `render` is a hint (`summary`, `worker_list`, `camera_picker`, `navigate`) telling the client which component to draw; `navigate` carries an in-app path the client pushes to its router.

The assistant calls the same service layer as the routes above, under the caller's own `AuthContext`, so ADR 0003 scoping and clearance apply unchanged and no tool accepts a department or user parameter from the model. It can read cameras, sightings, journeys, workers, watchlist and alerts, and can start/stop analytics, add a watchlist entry, and acknowledge/resolve alerts — each subject to the same permission as the equivalent route. It cannot delete anything, administer cameras or users, or change system modes; those operations are absent from its tool registry rather than merely refused. Every invocation appends a `copilot.tool_invoked` audit event. Rate limit: 20 requests per minute per user; at most 8 tool iterations per turn. `GET /api/copilot/status` returns `{"available": bool, "model": str|null, "tool_count": int}`; when `OPENROUTER_API_KEY` is unset, `available` is `false` and `POST /api/copilot/chat` returns 503. See [ADR 0005](decisions/0005-copilot-in-process-agent.md) and `backend/README.md`.

`CameraOut` does not return RTSP/HLS/WebRTC values. It exposes `stream_available` for browser-safe HLS preview, `analytics_stream_available` for a worker-safe RTSP-or-HLS capability, and `webrtc_preview_available` when the backend can relay either source to authenticated WHEP. An authorised browser requests media through `/api/hls/...` or `/api/webrtc/...`; both routes recheck its department grant before resolving a private source endpoint. Camera creation may accept endpoint values from a super admin, but response serialization never echoes them. RTSP-only analytics can publish detector telemetry, but needs an authoritative source-time mapping before it can create timestamped sightings; the worker never substitutes frame-arrival time.

### Current access matrix

| Capability | Viewer grant | Operator grant | Department admin | Super admin | Worker token |
|---|---:|---:|---:|---:|---:|
| Read/export camera; read live/sighting/alert/analytics/journey/report data in granted department | Yes | Yes | Home department | All | No |
| Start/stop per-camera analytics; acknowledge/resolve alerts | No | Granted department | Home department | All | No |
| Edit camera metadata | No | No | Home department | All | No |
| Approve department users and set home clearance | No | No | Home department | All | No |
| Create departments, approve department admins, manage cross-department grants | No | No | No | Yes | No |
| Manage global watchlist and catalogue-wide operations | No | No | No | Yes | No |
| Post sightings/person-count aggregates | No | No | No | No | Yes |

The registration password hash is transferred to the approved user and removed from the reviewed request. Disabled accounts have all sessions revoked. Department grants are evaluated on every request, so a grant or clearance change applies without requiring a new login.

`GET /api/admin/audit-events` returns an object, not a bare event list:
`{"total": <visible-count>, "limit": <page-size>, "offset": <page-start>,
"events": [...]}`. `total` is calculated after the caller's role/department
scope is applied, so it does not disclose the number of hidden events.

`GET /api/admin/audit-events/export` is intentionally super-admin-only: it
returns the complete cross-department history as canonical oldest-first NDJSON,
with `X-Sentinel-Audit-Event-Count` and `X-Sentinel-Audit-SHA256` headers. It
sets `Cache-Control: no-store` and emits an `audit.exported` event *after* the
snapshot is materialised, so its digest/count describe the exact downloaded
archive. The operator must store the archive and digest in an approved external
immutable destination; download alone is not immutable retention.

`POST /api/admin/audit-events/archive` is also super-admin-only. It materialises
the same canonical oldest-first snapshot and its detached `<archive>.sha256`
file in `AUDIT_ARCHIVE_DIR`, using exclusive file creation so this process never
overwrites an existing archive. It returns only archive name, count, and digest,
then appends `audit.archive_delivered`. The directory must be outside the
repository and must be a platform-administered WORM/object-lock retention mount;
an ordinary writable folder, including a local test folder, is delivery testing
only and does not meet immutable-retention acceptance.

**Manual onboarding (`POST /api/cameras`).** camera_id and camera_number are assigned server-side, never supplied by the caller: camera_id is `manual-<n>`, guaranteed disjoint from any catalogue-sourced id so a later `POST /api/sync` can never collide with or silently overwrite a manually-registered row (Stage 1's disappeared-camera check also explicitly excludes `manual-*` ids for the same reason). `rtsp_url`/`hls_url`/`webrtc_url` are nullable on this table specifically to allow metadata-only registration -- a camera can be onboarded before its stream is wired up, and Stage 2/3 already skip cameras with no URL safely.

**Bulk onboarding (`POST /api/cameras/bulk`).** The upload must be UTF-8 CSV and
include a `camera_id` column. A known, nonblank `camera_id` updates the allowed
operator metadata fields. A blank `camera_id` creates a metadata-first camera
with a server-assigned `manual-<n>` id; such rows must include `name` and
`location_text`. A supplied unknown ID is rejected rather than becoming a new
catalogue-looking ID: leave it blank to create a manual record. Rows are
validated independently, so a partial import commits valid rows and returns
`total_rows`, `created`, `updated`, `failed`, and a per-row result. The current
endpoint is super-admin-only and records a `camera.bulk_updated` audit event
with those totals.

**Registry search and export.** `GET /api/cameras` accepts case-insensitive
`q` matching camera ID, name, location text, or department, in addition to
`department`, `camera_type`, `anpr_viable`, and `is_live`. `GET
/api/cameras/export` accepts the same filters and returns only matching cameras
already visible to the caller under ADR 0003; it never exports RTSP/HLS/WebRTC
source endpoints. The export records a `camera_registry.exported` audit event
with the filter values, row count, and `format`. CSV is the default; set
`format=json` for a downloadable JSON array using the same public field
allowlist. The request itself also receives the central metadata-read audit event.

**Probe health history.** Each completed `POST /api/probe` writes an
append-only `camera_health_observations` row for every probed camera. It records
the UTC observation time, `healthy` or `offline` result, actual transport,
catalogue `is_live` value, and a redacted operator-readable failure reason when
the probe could not connect. The latest failure is also exposed as
`CameraOut.health_reason`; a later successful probe clears it while retaining
the history. `GET /api/cameras/{camera_id}/health-history` is viewer-scoped by
department and returns newest observations first.

**Maintenance work orders.** `GET /api/cameras/{camera_id}/maintenance-work-orders`
is viewer-scoped by department and returns current work-order state together
with its oldest-first, application-append-only lifecycle events. A super admin or the
camera's home-department admin may open one with `POST` and progress it with
`PATCH /api/cameras/{camera_id}/maintenance-work-orders/{work_order_id}`.
Valid states are `open`, `in_progress`, `resolved`, and `cancelled`; resolved
and cancelled records are immutable. Creation and each accepted update append
`camera_maintenance.created` or `camera_maintenance.updated` audit events.

**Named catalogue sources (`/api/catalogue-sources`).** The original single-source sync above (`POST /api/sync`, against `settings.sandbox_catalogue_url`) is untouched -- it's the one thing GOV-ING-001 actually requires, so nothing here risks it. This is a separate, additive path for onboarding an arbitrary *second* named catalogue (e.g. a department's own feed) without touching that env-configured source. Registering a source and triggering its sync are both super-admin-only; `auth_secret` is accepted on create/update but never returned by any response, and the request is SSRF-hardened -- the hostname is resolved and a loopback/private/link-local address is rejected unless the source's own `allow_private_host` opts in (needed for local/test catalogues). Each source declares an `adapter` validated against a small registry (`app/pipeline/catalogue_sources.py`; only `sentinel_default` -- the one catalogue shape this project has actually seen -- exists today). Cameras synced from a source are namespaced `src{source.id}-{raw_id}` (two different customer catalogues could easily reuse the same small integers) and carry `source_id` for provenance (`NULL` means the original sync or manual onboarding, unchanged); the disappeared-camera check is scoped per source so one source's absence list can never mention another's. A source with cameras still attached can't be deleted (`409`, matching the "registry is durable" philosophy Stage 1 already follows) -- deactivate it instead.

**ANPR pipeline slice (`sightings`/`watchlist`/`alerts`/`analytics`).** See `docs/anpr-pipeline-build-spec.md` for the full design: why `seen_at` is anchored to the HLS playlist's `EXT-X-PROGRAM-DATE-TIME` rather than wall-clock-at-processing, the `epoch_id` discontinuity counter, why a sighting is only reported once a track's plate is `confirmed` (not per accepted OCR read), and the alert dedup window. `POST /api/sightings` is meant to be called by `multi-object-tracking/observation_worker.py`, not by browser clients.

**Suspicious-activity alerts (`POST /api/alerts/suspicious`).** The separate
`suspicious` worker mode may post a purpose-trained classifier's confirmed
potentially-dangerous-person signal using only the worker token. The backend
creates an `alert_type: "suspicious"` alert, deduplicated per camera/track for
15 minutes. Because this signal does not identify a person, it deliberately
does not create a sighting, watchlist match, or journey stop. It is a bonus
operator-assistance feature, not evidence of face recognition or an identity
claim; false-positive/accuracy evidence remains required before demo use.

**HLS proxy (`GET /api/hls/:camera_id/:viewer/:filename`).** Relays a camera's m3u8 playlists and segments through the backend for browser playback (client's Live view). Exists because the sandbox gateway's edge sends a duplicated `Access-Control-Allow-Origin` header that every CORS-enforcing browser rejects outright -- confirmed with `curl -v` against the raw stream URL, not a proxy artifact. Routing through this same-origin endpoint means the browser never evaluates that header.

`:viewer` is an opaque per-player token, in the path rather than the query so HLS's relative child-playlist and segment URLs inherit it automatically. It scopes the backend's upstream connection: the gateway tracks a live playback position per session, so two players sharing one session fight over it, and changing the token is how a stalled player obtains a genuinely fresh session. Idle upstream clients are closed after 120s so a closed player stops consuming a stream copy (GOV-ING-012). An empty upstream playlist -- how this gateway signals an expired session -- is returned as `503` rather than passed through as a structurally-valid-but-empty playlist, so the client can tell "reconnect" apart from "fetched fine". See `backend/app/routers/hls_proxy.py` and `docs/operator-console-build-spec.md`.

**WebRTC/WHEP relay (`POST /api/webrtc/:camera_id/whep`, `DELETE .../whep/:session_id`).** A local-only low-latency alternative to the HLS proxy above, tried first by client's `FocusedPlayer.jsx` and falling back to HLS on any failure. The browser never receives raw RTSP. An ffmpeg subprocess prefers the camera's RTSP endpoint with `-rtsp_transport tcp`, or uses HLS when RTSP is absent, and republishes it into locally-run MediaMTX; MediaMTX then serves real WHEP/WebRTC (`backend/app/pipeline/webrtc_relay.py`). Only the WHEP *signaling* (a plain-HTTP SDP offer/answer) is proxied and RBAC-gated here the same way HLS segments are; the negotiated media (RTP/ICE/DTLS) flows directly between the browser and MediaMTX afterward, which is why everything MediaMTX exposes is bound to `127.0.0.1` -- sufficient for this project's same-machine dev/demo topology, not for a separately-hosted one. RTSP-only cameras are available in the focused player but cannot fall back to HLS when negotiation fails; grid tiles remain HLS-only to preserve the preview-connection budget. See `docs/webrtc-relay-testing.md`.

**Detector telemetry (`/api/analytics/telemetry|snapshot|stream`).** Published by the worker itself as files beside its log (`multi-object-tracking/worker_telemetry.py`), read back by the backend. Exists because a worker previously reported only its end product -- a confirmed plate, or a person-count window -- so on a camera surveyed as unable to resolve plates it could run correctly for an hour and emit nothing at all, which is indistinguishable from being broken. `telemetry` carries rolling detection counts and stream health, and reports `stale: true` rather than presenting an old reading from a dead worker as live. `snapshot` returns the latest JPEG and `stream` pushes those snapshots as MJPEG. Both are detector views, explicitly not synced overlays: the worker holds its own connection to the stream, so its frames are seconds apart from the browser's player by construction.

**Analytics intent and restart behaviour.** `analytics_enabled` is stored on the camera so the supervisor can reconcile the operator's current choice, but backend startup clears every enabled flag before the supervisor starts. This prevents an orphaned or unattended YOLO worker from restarting merely because the prior process stopped while a camera was focused. Vehicle analytics therefore auto-starts after an operator enables it in the current session, not from persisted intent across backend restarts.

**Investigate (`/api/investigate/*`).** Offline forensic search over uploaded recordings: upload → CFR-normalise (fixes VFR drift, unrotated-dimension boxes, and non-browser-playable codecs in one ffmpeg pass) → an ingest run tracks vehicles or people → search by plate, or by uploading a person photo. `tracks.boxes`/`embedding` are `deferred()` so a track list never drags a timeline along; fetch a timeline via its own `/boxes` endpoint, which returns a fixed-10Hz, 0..1000-normalised encoding regardless of source fps. Ingest results arrive as small worker-token-only chunks (`/chunk`, idempotent on `seq`) rather than one terminal document -- a 10-minute recording is tens of thousands of box samples, and constructing that as one payload would block the backend's single async process for seconds. Frame stride defaults to **1**, not higher, because TRACKTRACK (the tuned tracker) hard-gates association on IoU after the appearance term, so a strided run's larger inter-frame displacement can make fast-moving vehicles unmatchable regardless of ReID; get throughput from `imgsz`/model size instead. Run state (`queued|running|completed|completed_partial|failed|stalled|cancelled`) lives in Postgres, not an in-memory dict, and ingest workers are deliberately **not** registered in the live analytics workers' manifest -- doing so would mean a long ingest gets killed by `kill_orphans_from_previous_run` on every `uvicorn --reload`. The operator UI (`client/src/views/Investigate/`) covers recordings/upload, ingest run management, plate search with a results grid, and clip playback with a frame-accurate canvas box overlay -- the console's first non-HLS video player, possible because a recorded file (unlike a live stream) has exact frame timing. See `docs/investigate-testing.md` for the full endpoint/RBAC table, manual test recipes, and `backend/scripts/investigate_smoke_test.py` for automated coverage (21/21 passing).

## Target `/api/v1` contract rules

- Base path: `/api/v1`.
- JSON field names: `snake_case`.
- IDs: opaque strings; UUIDs are recommended.
- Times exchanged between services: UTC ISO-8601 with timezone.
- Video events preserve source PTS in milliseconds plus a stream epoch/session identifier; PTS is monotonic only within that epoch.
- Pagination: cursor-based for event-scale collections.
- Errors use a stable `code`, human `message`, and optional `details` object.
- Sensitive URLs and credentials are never returned to unauthorised clients or logs.
- Contract changes require tests, this document, and an ADR if breaking.

## Core resources

### CameraSource - internal connector contract

`CameraSource` is an internal, security-sensitive contract created from the current `/api/ingest` catalogue. It is not returned unchanged to ordinary browser clients.

```json
{
  "external_id": "source-owned-id",
  "source_system": "sentinel_sandbox",
  "catalogue_observed_at": "2026-08-28T10:00:00Z",
  "source_name": "source-provided camera name",
  "source_location_label": "source-provided human-readable location",
  "location": {"latitude": 23.2156, "longitude": 72.6369},
  "codec": "h264",
  "width": 1920,
  "height": 1080,
  "reported_fps": 25.0,
  "bitrate_bps": 2500000,
  "live": true,
  "endpoints": {
    "rtsp": "secret-or-opaque-reference",
    "whep": "secret-or-opaque-reference",
    "hls": "secret-or-opaque-reference"
  }
}
```

Rules:

- Refresh from the catalogue; do not construct URLs from a pattern.
- Preserve all available protocols and current source properties.
- Treat empty strings and zero-valued media properties as unknown until a successful stream probe supplies authoritative values.
- Preserve a source location label separately from registry coordinates. The observed catalogue supplies a location label, not latitude/longitude; enrich coordinates through an authorised registry workflow and do not silently invent them.
- Treat endpoint values as secrets when they contain credentials, tokens, private hosts, or other sensitive material.
- Select RTSP/TCP for inference, WHEP for low-latency preview, and HLS for compatible fallback/viewing use cases.
- A field named `webrtc_url` is not by itself proof that the endpoint implements WHEP; validate the endpoint protocol before treating it as a WHEP preview URL.
- Do not expose publish or gateway-control capabilities.

### Observed catalogue mapping

The following is a redacted, non-authoritative mapping observed in a team catalogue request on 2026-08-28. It documents the parser boundary only; URL values and catalogue host are intentionally not retained in Git.

| Catalogue field | CameraSource handling |
|---|---|
| `id` | `external_id` |
| `number`, `name` | Preserve as source provenance; use `name` for `source_name` when present. |
| `location` | Store as `source_location_label`; registry coordinates remain a separate enrichment step. |
| `codec`, `width`, `height`, `fps` | Preserve when non-empty/non-zero; otherwise mark as unknown. `fps` never drives video timing. |
| `bitrate_kbps` | Convert to `bitrate_bps` by multiplying by 1,000 when present. |
| `live` | Preserve as catalogue-reported state, not proof of successful capture. |
| `rtsp_url` | Store only as the sensitive RTSP endpoint reference; inference must force TCP. |
| `webrtc_url` | Store as a sensitive low-latency preview reference; verify whether it is WHEP before WHEP use. |
| `hls_live_url` | Store only as the sensitive HLS endpoint reference. |

### Camera

```json
{
  "id": "cam_opaque",
  "external_id": "source-owned-id",
  "source_system": "sentinel_sandbox",
  "department_id": "dept_opaque",
  "name": "Camera 12",
  "camera_type": "ip",
  "latitude": 23.2156,
  "longitude": 72.6369,
  "codec": "h264",
  "width": 1920,
  "height": 1080,
  "reported_fps": 25.0,
  "connectivity_status": "online",
  "health_reason": null,
  "last_seen_at": "2026-08-28T10:00:00Z",
  "storage": {"mode": "source_managed", "retention_days": null},
  "capabilities": ["rtsp", "hls", "whep"],
  "created_at": "2026-08-28T09:00:00Z",
  "updated_at": "2026-08-28T10:00:00Z"
}
```

`reported_fps` is metadata only and must not drive timing.

### Observation

The plate values below are synthetic contract examples, not observed vehicle identifiers.

```json
{
  "id": "obs_opaque",
  "camera_id": "cam_opaque",
  "analytic_type": "anpr",
  "model": {"name": "model-name", "version": "version"},
  "stream_epoch_id": "epoch_opaque",
  "discontinuity_sequence": 0,
  "source_pts_ms": 1234567,
  "event_time": "2026-08-28T10:00:01.250Z",
  "processed_at": "2026-08-28T10:00:02.100Z",
  "raw_value": "GJ 01 AB 1234",
  "normalised_value": "GJ01AB1234",
  "confidence": 0.94,
  "quality_flags": [],
  "bounding_box": {"x": 0.2, "y": 0.4, "width": 0.25, "height": 0.12},
  "evidence_ref": null,
  "trace_id": "trace_opaque"
}
```

### WatchlistEntry

```json
{
  "id": "wl_entry_opaque",
  "watchlist_id": "wl_opaque",
  "entity_type": "vehicle_plate",
  "raw_value": "GJ 01 AB 1234",
  "normalised_value": "GJ01AB1234",
  "reason_code": "stolen_vehicle",
  "severity": "high",
  "valid_from": "2026-08-01T00:00:00Z",
  "valid_until": null,
  "source": "synthetic_demo",
  "active": true,
  "metadata": {}
}
```

### Alert

```json
{
  "id": "alert_opaque",
  "observation_id": "obs_opaque",
  "watchlist_entry_id": "wl_entry_opaque",
  "camera_id": "cam_opaque",
  "event_time": "2026-08-28T10:00:01.250Z",
  "created_at": "2026-08-28T10:00:02.300Z",
  "match_confidence": 0.94,
  "severity": "high",
  "status": "open",
  "deduplication_key": "opaque-policy-derived-key",
  "assigned_to": null,
  "acknowledged_at": null,
  "resolved_at": null
}
```

## Initial endpoints

### Registry and health

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/cameras` | Search/filter cameras by department, type, status, and map bounds. |
| `POST` | `/cameras` | Manual onboarding. |
| `POST` | `/cameras/bulk` | Validated bulk onboarding. |
| `GET` | `/cameras/{camera_id}` | Camera metadata and current health. |
| `PATCH` | `/cameras/{camera_id}` | Authorised camera metadata update. |
| `GET` | `/cameras/{camera_id}/health-history` | Health transitions. |
| `GET`, `POST` | `/cameras/{camera_id}/maintenance-work-orders` | Viewer-scoped history; home-department/super-admin creation. |
| `PATCH` | `/cameras/{camera_id}/maintenance-work-orders/{work_order_id}` | Progress an open work order and append a lifecycle event. |
| `POST` | `/sources/sentinel/refresh` | Authorised read-only catalogue refresh. |
| `GET` | `/coverage/gaps` | Sample coverage/ageing gap report. |

### Watchlists and matching

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/watchlists` | List authorised watchlists. |
| `POST` | `/watchlists` | Create a representative watchlist. |
| `POST` | `/watchlists/{watchlist_id}/entries/bulk` | Bulk import with validation. |
| `GET` | `/watchlist-entries` | Search entries. |
| `PATCH` | `/watchlist-entries/{entry_id}` | Update/disable an entry with audit. |

### Observations, alerts, and journeys

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/observations` | Search by plate/entity, time, camera, department, confidence. |
| `GET` | `/alerts` | Alert queue/search. |
| `POST` | `/alerts/{alert_id}/acknowledge` | Authorised acknowledgement. |
| `POST` | `/alerts/{alert_id}/resolve` | Authorised resolution. |
| `GET` | `/vehicles/{normalised_plate}/journey` | Ordered, GIS-ready movement history. |
| `GET` | `/vehicles/{normalised_plate}/journey/export` | Reconciled report export. |

### Operations

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health/live` | Process liveness. |
| `GET` | `/health/ready` | Dependency readiness. |
| `GET` | `/operations/summary` | Authorised catalogue/feed/inference/database/alert health. |
| `GET` | `/operations/cameras/{camera_id}/diagnostics` | Authorised, redacted diagnostic summary; exact source URL is reserved for the private support workflow. |

## Error shape

```json
{
  "error": {
    "code": "camera_source_unavailable",
    "message": "Camera source is temporarily unavailable.",
    "details": {"camera_id": "cam_opaque", "retryable": true},
    "trace_id": "trace_opaque"
  }
}
```

## Open contract decisions

- Final ID format.
- Production identity provider and MFA/session-hardening mechanism (the Phase 1 mechanism is fixed by ADR 0003).
- Event transport and delivery semantics.
- Stream epoch creation and source-PTS-to-UTC event-time anchoring.
- Evidence storage and signed-access policy.
- Plate normalisation rules for Indian registration formats.
- Alert deduplication window and policy dimensions.
- Journey pagination/export format.
