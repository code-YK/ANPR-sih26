# Camera Registry and Onboarding: Build Spec

> **Historical build spec.** Written during an earlier programme whose
> `Model N` vocabulary does not exist in SIH26127. Retained because it records
> *why* this slice is built the way it is - the reasoning is still current even
> where the naming is not. See [ADR 0004](decisions/0004-sih26127-rescope.md)
> for the mapping, and [requirements.md](requirements.md) for current IDs.

Status: Accepted implementation plan; incomplete against `GOV-M1-001` through `GOV-M1-008`

This spec covers **only** the camera registry and onboarding. ANPR, sightings ingestion, watchlist matching and the unified viewer are separate later stages — this document deliberately stops before them, but the schema anticipates them.

Target: working by **Aug 31**. Single Python process + PostgreSQL. No microservices, no message queue, no orchestration.

---

## 1. Context the implementer needs

The sandbox exposes ~30 simulated-live cameras via a catalogue API. The catalogue is the contract — camera IDs and availability change, so never hardcode or reconstruct stream URLs.

Obtain the catalogue and browser base URLs through the approved team channel and set them through local environment variables. Do not retain the current host or per-camera endpoints in Git.

Returns `{"cameras": [...]}`. Each entry:
```json
{
  "id": "26", "number": 26, "name": "Camera 26",
  "location": "35 TANKAL",
  "codec": "hevc", "live": true,
  "width": 2560, "height": 1440, "fps": 13.35,
  "bitrate_kbps": 2411, "bits_per_pixel": 0.049,
  "rtsp_url":  "secret-or-approved-endpoint-reference",
  "webrtc_url":"secret-or-approved-endpoint-reference",
  "hls_live_url": "/live/stream/26/index.m3u8"
}
```

**Two known facts about this data:**

1. Roughly two-thirds of cameras return `codec: ""`, `width: 0`, `height: 0`, `fps: 0.0` despite `live: true`. Stream properties are therefore **not reliably available from the API** and must be probed independently.
2. `location` is a place-name string (`"01 Chiman bhai Bridge"`), not coordinates. GIS display requires forward geocoding.
3. `hls_live_url` may be a relative path. Resolve it against the locally supplied browser base URL.

**Network caveat:** RTSP port 8554 may be blocked on some networks; HLS works as a fallback. Probing must attempt RTSP first and fall back to HLS, recording which transport succeeded.

---

## 2. Database schema

PostgreSQL + PostGIS. Two tables in scope now; `sightings` is included because the registry's foreign key must exist before the ingestion stage is built.

### `cameras`

Deliberately denormalised — `department`, `ownership`, `camera_type` are constrained text/enum rather than FK lookups. At 30 cameras this saves joins and migrations; production scale would normalise these into lookup tables (state this in the HLD).

| Column | Type | Null | Source |
|---|---|---|---|
| `camera_id` | text PK | no | API `id` |
| `camera_number` | int | no | API `number` |
| `name` | text | no | API `name` |
| `location_text` | text | no | API `location` — retained after geocoding as provenance |
| `rtsp_url` | text | no | API — store verbatim, never reconstruct |
| `hls_url` | text | no | API path + host prefix |
| `webrtc_url` | text | no | API |
| `codec` | text | yes | ffprobe |
| `width` | int | yes | ffprobe |
| `height` | int | yes | ffprobe |
| `fps` | numeric | yes | ffprobe — reference only, never used for timing |
| `bitrate_kbps` | int | yes | ffprobe / API |
| `transport_ok` | text | yes | `rtsp` \| `hls` \| `none` — which transport actually connected |
| `anpr_viable` | bool | yes | Manual survey verdict |
| `anpr_notes` | text | yes | Why not viable: night / distance / angle / resolution |
| `last_surveyed_at` | timestamptz | yes | Probe run time |
| `latitude` | numeric(9,6) | yes | Geocoding |
| `longitude` | numeric(9,6) | yes | Geocoding |
| `geocode_confidence` | text | yes | `exact` \| `approximate` \| `failed` |
| `department` | text | yes | Operator — one of: Health, Police, GSRTC, Panchayat, Municipal |
| `ownership` | text | yes | Operator — `government` \| `private` |
| `camera_type` | text | yes | Operator — `fixed` \| `ptz` \| `analog` \| `ip` |
| `connectivity` | text | yes | Operator — unavailable in sandbox, present for HLD completeness |
| `storage_location` | text | yes | Operator — where footage actually lives (registry metadata, not central recording) |
| `retention_days` | int | yes | Operator — real range is 7 to 15+ |
| `metadata_confidence` | text | yes | `confirmed` \| `inferred` — see §5 |
| `is_live` | bool | yes | API `live` |
| `last_successful_connect` | timestamptz | yes | Written by probe/pipeline — this **is** camera health |
| `health_reason` | text | yes | Latest failed probe reason; cleared on a successful probe |
| `created_at` / `updated_at` | timestamptz | no | |

Indexes: `camera_id` (PK), `department`, `anpr_viable`, and a PostGIS geography index on `(longitude, latitude)`.

### `sightings` (originally schema-only; now populated by the ANPR pipeline)

| Column | Type | Notes |
|---|---|---|
| `id` | bigserial PK | |
| `camera_id` | text FK → cameras | |
| `seen_at` | timestamptz | Derived from PTS anchoring, never `datetime.now()` at processing time |
| `plate` | text | Nullable — many detections yield no plate |
| `vehicle_type` | text | Nullable |
| `vehicle_colour` | text | Nullable |
| `confidence` | numeric | ANPR confidence |
| `frame_pts_ms` | bigint | Raw PTS for debugging |

**One row per detection, not per frame.** Index on `plate` and on `(camera_id, seen_at)`. Route reconstruction is `SELECT ... WHERE plate = ? ORDER BY seen_at` — no graph traversal, no proximity search.

---

## 3. Onboarding pipeline

Four stages, each independently re-runnable and idempotent on `camera_id`.

### Stage 1 — Catalogue sync
Fetch `/api/ingest`, upsert every camera. Populate the never-null columns plus `is_live`. Log cameras that disappeared from the catalogue rather than deleting rows.

### Stage 2 — Stream probe
For each camera, attempt in order:
```bash
# RTSP first, TCP forced
ffprobe -v error -rtsp_transport tcp -select_streams v:0 \
  -show_entries stream=codec_name,width,height,r_frame_rate,bit_rate \
  -of json -timeout 10000000 "<rtsp_url>"

# HLS fallback if RTSP fails
ffprobe -v error -select_streams v:0 \
  -show_entries stream=codec_name,width,height,r_frame_rate,bit_rate \
  -of json "<approved-browser-base><hls_live_url>"
```
Write `codec`, `width`, `height`, `fps`, `bitrate_kbps`, `transport_ok`, `last_surveyed_at`, `last_successful_connect`, and `health_reason`. Each run also appends one `camera_health_observations` row per camera, preserving the UTC outcome (`healthy`/`offline`), transport, catalogue-live claim, and failure reason without treating source `live` as proof of a successful connection.

Note: HLS is a re-packaged fallback, so properties read there may differ from the RTSP source. Record which transport produced the values.

### Stage 3 — Frame capture for survey
One still per camera, for human review:
```bash
ffmpeg -rtsp_transport tcp -i "<rtsp_url>" -frames:v 1 -y survey/cam<id>.jpg
```
Do **not** transcode a clip and probe that — it reports the local encoder's properties, not the camera's.

Review the 30 stills by eye and set `anpr_viable` + `anpr_notes`. Known failure modes already observed in this sandbox: night IR with motion blur, PTZ wide-angle at distance, and well-lit intersections where plates are still too few pixels to resolve. This is a judgement call per camera and cannot be automated in the time available.

### Stage 4 — Geocoding
Forward-geocode `location_text` → lat/lng **once at onboarding**, store the result. Never geocode on map load.

Use Nominatim (free, no key) with `format=json&countrycodes=in` and a bias toward Gujarat. Respect its 1 req/sec limit. Set `geocode_confidence` from the result quality; on failure set `failed` and leave lat/lng null so the map honestly shows the camera as unplaced.

Strings like `"38 bilimora"` and `"35 TANKAL"` will geocode poorly. The onboarding UI must allow manual lat/lng correction, which sets `geocode_confidence = 'exact'`.

---

## 4. Onboarding UI

Minimal. React or server-rendered — whichever is faster to build.

- **Camera list** — all cameras, with live status, ANPR viability, and geocode status visible at a glance.
- **Edit form** — the operator-supplied columns (`department`, `ownership`, `camera_type`, `connectivity`, `storage_location`, `retention_days`, `metadata_confidence`) plus manual lat/lng override. Department and ownership as fixed dropdowns, not free text.
- **Bulk import** — the CSV endpoint updates operator columns when `camera_id` names an existing row. A blank `camera_id` creates a metadata-first, server-assigned `manual-<n>` camera and requires `name` and `location_text`; a supplied unknown ID is rejected so an operator cannot accidentally claim a current or future catalogue ID. Row-level validation returns created, updated, and failed totals.
- **GIS map** — React Leaflet, OpenStreetMap tiles, one marker per geocoded camera, department/type/ANPR/live filters, and an explicit unplaced list. Marker colour is current health (live, offline/unreachable, unknown). An operator can opt into 100/250/500 m rings around only live, geocoded cameras for planning; the UI explicitly labels them as indicative radii, never measured fields of view. Authenticated browser verification is recorded in `artifacts/public/checkpoint-c3/gis-coverage-layer-browser-2026-08-31.md`.
- **Health and maintenance history** — any authorised viewer can select an authorised camera and see its bounded, newest-first probe observations, current source-live state, latest successful transport time, latest failure reason, and work-order history. A super admin or the camera's home-department admin can open and progress a work order; each accepted change appends an application-level lifecycle event and terminal (`resolved`/`cancelled`) records are immutable through the API.

---

## 5. Provenance rule

The system records what it knows **and how well it knows it**. It never lets an inference appear as a fact.

`"17 Rajkot Bus Port CCTV"` is probably GSRTC and `"KHAPARIA GRAM PANCHAYAT..."` is probably Panchayat, but neither is stated in the data. Any operator-supplied value derived from a place-name guess is stored with `metadata_confidence = 'inferred'`. Values with a real source are `confirmed`.

The UI must display this distinction — a badge, muted styling, anything visible. Same principle applies later to `geocode_confidence` and to candidate vehicle matches in the tracking stage.

---

## 6. Gap analysis report

A registry deliverable. Three sections; the second is the strongest and should lead.

**Capability gaps (lead with this).** Cameras that exist but cannot read plates — `anpr_viable = false`. Output per camera: location, department, reason (night/angle/distance/resolution), and a flag for replacement priority. Framed as a procurement recommendation: *"these N junctions are covered by a camera but not by ANPR capability; prioritise upgrade here."*

**Coverage gaps.** Cameras per district/region derived from geocoded coordinates. Identifies clustering (e.g. multiple cameras in Junagadh) against districts with none.

**Health / ageing gaps.** Cameras where `is_live = false`, `last_successful_connect` is stale, or resolution/bitrate falls below a usable threshold. Include `transport_ok = 'none'`.

Export as HTML and PDF. Runs on: `latitude`, `longitude`, `anpr_viable`, `width`/`height`/`fps`/`codec`, `is_live`, `last_successful_connect`, `department`. Requires nothing from `connectivity`, `storage_location`, or `retention_days` — those can stay sparse.

---

## 7. API surface

```
GET  /api/cameras                 list + filter (q, department, camera_type, anpr_viable, is_live)
GET  /api/cameras/export          filtered, department-scoped CSV/JSON export (?format=csv|json)
POST /api/cameras                 manual metadata-first onboarding
GET  /api/cameras/:id             single camera
PUT  /api/cameras/:id             operator field updates
POST /api/cameras/bulk            validated CSV create/update onboarding
POST /api/sync                    re-run catalogue sync
POST /api/probe                   re-run stream probe (all or one)
POST /api/survey/capture          capture one authorised survey still (all or one)
GET  /api/survey/:id/frame        retrieve an existing authorised survey still
POST /api/geocode                 geocode unresolved cameras (all or one)
GET  /api/geocode/search          authenticated free-text place search for the map picker
GET  /api/gap-analysis            report data as JSON
GET  /api/gap-analysis/export     HTML/PDF
```

Documented API is itself a registry deliverable — keep an OpenAPI spec or equivalent alongside.

---

## 8. Explicitly out of scope

Do not build the following speculative infrastructure for this increment:

- Kafka, RabbitMQ, Kubernetes, microservice split
- Separate `departments` / `camera_types` lookup tables
- Vehicle re-identification or appearance embeddings
- Central video storage or recording (out of scope; this build is metadata-first)

Department authentication/RBAC, registry text/type filtering, department-scoped CSV/JSON exports, health-oriented GIS markers, optional indicative coverage planning rings, probe-health and maintenance work-order history, and state-change/export/read/denial audit events are implemented under ADR 0003. Database migration `202608311800` also rejects application-role audit-row updates and deletes, except the required account-deletion FK cleanup. A super-admin-only canonical NDJSON audit archive can be downloaded or delivered once-only to an administrator-configured external mount with a SHA-256 digest. Authenticated browser GIS and protocol-compatible health-recovery evidence are recorded, and the project owner confirms official catalogue sync is operational. Provisioning/testing an approved WORM/object-lock retention destination and a redacted official demonstration record remain open registry/GIS work (`SIH-NFR-002`); they cannot be deferred solely by this build spec.

---

## 9a. Amendment (2026-08-29): manual onboarding + map picker

The spec's schema table marks `rtsp_url`/`hls_url`/`webrtc_url` as never-null, sourced verbatim from the catalogue. That's still true for catalogue-synced cameras. A gap surfaced once §4's manual-entry onboarding path was built: a camera outside the sandbox catalogue needed a metadata-first path. The form and CSV onboarding now share that safe manual namespace:

- `POST /api/cameras` registers a camera that isn't in the catalogue. `POST /api/cameras/bulk` does the same when its `camera_id` cell is blank, while retaining update-by-known-ID behaviour for populated cells. `camera_id`/`camera_number` are assigned server-side (`manual-<n>`) so a manual row can never collide with a future catalogue id; a supplied unknown CSV ID is rejected rather than being created.
- `rtsp_url`/`hls_url`/`webrtc_url` are now nullable on the table, so a camera can be registered metadata-only (name, location, department, etc.) before its stream is wired up. This only relaxes the constraint -- catalogue-synced cameras still always get real values from the API, verbatim, as originally specified.
- §4's edit form (and the new manual-entry form) got an interactive Leaflet map below the lat/lng fields: click or drag a pin to set coordinates instead of typing them, wired bidirectionally with the manual-override inputs. Setting both fields (by map or by hand) still marks `geocode_confidence = 'exact'`, unchanged from the original spec.

See `docs/api.md` for the endpoint contract and `backend/migrations/versions/202608290104_nullable_stream_urls.py` for the schema change.

## 9. Current implementation status

Code inspection confirms:

- [x] Catalogue sync is implemented as an idempotent upsert.
- [x] Probe, survey-capture, and geocoding stages are implemented and independently callable.
- [x] Failed geocodes remain visibly unplaced.
- [x] The active map renders geocoded cameras with department, ANPR, and live filters.
- [x] CSV creation of metadata-first manual rows and updates of existing operator rows are implemented with row-level validation; the current smoke evidence covers success and independent invalid-row failures.
- [x] Text/type registry filtering and department-scoped CSV/JSON export are implemented; neither format contains source endpoints and both create format-specific export audit events.
- [x] Map camera-type filtering, health-oriented marker semantics, and opt-in indicative coverage rings are implemented. The rings use only live/geocoded rows and are labelled as planning approximations, not camera field-of-view measurements.
- [x] Probe outcomes persist as append-only, department-scoped health history; a metadata-only synthetic camera verifies an offline observation and failure reason without contacting a live stream.
- [x] Gap-analysis JSON/HTML/PDF generation is implemented.
- [x] `metadata_confidence` badges are implemented.

Checkpoint completion still requires:

- [ ] A dated, redacted result proving catalogue counts and per-camera probe/survey/geocode outcomes.
- [x] A committed, metadata-only synthetic camera and watchlist fixture is seeded by `backend/scripts/seed_synthetic_demo.py`; it deliberately does not emulate a media protocol.
- [x] Authenticated browser/reproduction evidence for the type/health/coverage GIS controls is recorded in `artifacts/public/checkpoint-c3/gis-coverage-layer-browser-2026-08-31.md`.
- [x] Maintenance state/history. Health reason/history and a deterministic offline-probe transition are implemented; application-append-only work-order lifecycle history is visible and role-scoped. Protocol-compatible interruption/recovery evidence is recorded; a redacted official-live transition demonstration remains open.
- [ ] Database-level immutable audit retention. Department RBAC, text/type filtering, CSV/JSON export, and state-change/export/read/denial audit are implemented under ADR 0003; application-role immutability, digest-verifiable download, and once-only external delivery are implemented. A real WORM/object-lock target still needs to be provisioned and tested; database-superuser control is a deployment-governance requirement.
- [x] Clean-clone reproduction and teammate review are complete by project-owner attestation (`artifacts/public/checkpoint-c8/teammate-second-machine-attestation-2026-08-31.md`).
