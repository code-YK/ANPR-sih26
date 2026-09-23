# Operator console (client)

A second operator console for SIH26127, under active development. It provides the registry and GIS map, the live video wall, watchlist, alerts, vehicle trajectory search, offline forensic search (Investigate), and the analytics controls, all backed by the FastAPI `/api` surface.

**This console is not served.** `frontend-v5/` is the served operator console — FastAPI mounts its production build at `/`. `client/` is developed against its own dev server (see below) and proxies `/api` to the backend; its build is never mounted. See the repository [README](../README.md#which-console-is-served) for which console is canonical.

## Directory map

| Path | Contents |
|---|---|
| `src/views/Live/` | Video wall, focused player, per-camera analytics toggles, detector view |
| `src/views/Registry/` | Camera list, GIS map, gap analysis, health and maintenance history, create/edit modals |
| `src/views/Journey/` | **Trajectory reconstruction** — plate search, chronological timeline, numbered route map |
| `src/views/Alerts/` | Alert queue with acknowledge/resolve |
| `src/views/Watchlist/` | Blacklist CRUD and bulk import |
| `src/views/Investigate/` | Recording upload, ingest runs, plate and person search, bbox overlay player |
| `src/views/Admin/` | Access administration, catalogue sources, **demo and government mode toggles** |
| `src/views/Auth/` | Sign-in and registration request |
| `src/context/` | Auth, cameras, alerts, departments — shared state |
| `src/hooks/` | HLS and WebRTC players, polling, visibility, GSAP reveals |
| `src/components/` | Map tiles, status marks, modals, toasts, lightbox, log panel |

## Prerequisites

- Node.js `^20.19.0` or `>=22.12.0` (required by Vite 8). Verified on 24.19.0
- npm — the exact dependency graph is locked in `package-lock.json`
- The backend running at `http://127.0.0.1:8000`

## Development

```bash
npm --prefix client ci
npm --prefix client run dev
```

Opens on **http://localhost:5174**. API requests are proxied to the local backend by `vite.config.js`.

### Why the port is fixed

`vite.config.js` sets `port: 5174` with `strictPort: true`. This is deliberate, not a preference. `hlsProxyUrl` and `recordingMediaUrl` in `src/api.js` fetch video **cross-origin from the backend even in development**, so this origin has to be a known, stable entry in the backend's CORS allowlist (`backend/app/main.py`). If Vite were allowed to auto-increment to the next free port — which it would do whenever `frontend-v5`'s dev server on 5175 was already running — every video fetch would fail with an opaque CORS error.

## Verification and production build

```bash
npm --prefix client ci
npm --prefix client run lint
npm --prefix client run build
```

The build is written to `client/dist/`, but it is **never mounted** by the backend (see above) — this only verifies the console compiles.

Lint and build only prove the console compiles. They do not prove live-feed availability, browser compatibility, or accessibility. Record separate browser evidence for any UI claim.

## Security boundary

The console requires an approved account. UI controls reflect the role and clearance model, **but the backend is the enforcement point** — never rely on a hidden control for access control.

Camera responses expose only capability flags (`stream_available`, `analytics_stream_available`, `webrtc_preview_available`). Video is fetched through authenticated, department-checked HLS or WHEP relays; raw camera endpoints never reach the browser.

The current password/session mechanism is for a trusted demo, not production SSO. Do not place credentials, endpoint values, observed vehicle identifiers, screenshots of government data, or footage into fixtures or committed evidence.

## Design system

The visual and interaction direction is documented in [`/DESIGN.md`](../DESIGN.md): an HSL token system, self-hosted Instrument Sans + IBM Plex Mono, and a **certainty grammar** — texture encodes how a fact is known, colour is reserved for urgency — applied consistently across the video wall, tables, map, and trajectory timeline.

One consequence worth knowing when editing: thumbnails in the Investigate results grid use `object-fit: contain`, not `cover`. A track crop is already cut tight to its detection box, so `cover` would crop it a second time and a tall subject would lose its head and wheels.
