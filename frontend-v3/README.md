# Sentinel operator console

This is the active React operator console for the Sentinel Phase 1 application. It provides the registry/GIS, live viewer, watchlist, alerts, vehicle journey, and analytics controls backed by the unversioned FastAPI `/api` surface.

Its existence does not mean Module 1 is complete. Camera-type/health GIS controls, health/maintenance history, registry search/export, and read/denial audit coverage are implemented; authenticated browser GIS evidence is recorded, and the project owner confirms official catalogue sync is operational. A redacted official demonstration recording/output report, a provisioned WORM/object-lock audit-retention destination, and the remaining ledger evidence stay open in `docs/requirements.md`.

The console's visual and interaction direction is documented in [`/DESIGN.md`](../DESIGN.md): an HSL token system, self-hosted Instrument Sans + IBM Plex Mono type, and a certainty grammar (texture for how a fact is known, colour reserved for urgency) applied consistently across the video wall, tables, map, and journey timeline. All six adoption steps are merged on `main`; `DESIGN.md` §13 lists their implementation commits, the later integration fixes, and four details that remain incomplete or only partially implemented because the current API/UI boundary does not expose the required data.

## Prerequisites

- Node.js `^20.19.0` or `>=22.12.0` (required by Vite 8)
- npm (the exact dependency graph is locked in `package-lock.json`)
- the backend running at `http://127.0.0.1:8000`

## Development

```bash
# from the repository root
cd frontend-v2
npm ci
npm run dev
```

Open the URL printed by Vite. Development API requests are proxied to the local backend by `vite.config.js`.

## Verification and production build

```bash
cd frontend-v2
npm ci
npm run lint
npm run build
```

The production build is written to `frontend-v2/dist/`. Start the FastAPI backend afterward and open `http://127.0.0.1:8000/`; the backend serves that authenticated application at `/`.

Lint and build only prove that the console compiles. They do not prove live-feed availability, browser compatibility, accessibility, or any complete Module 1 checkpoint. The API-level role workflow is covered by `backend/scripts/rbac_smoke_test.py`; record separate redacted browser evidence for UI claims.

## Security boundary

The console requires an approved account. UI controls reflect the role/clearance model, but the backend remains the enforcement point. Camera responses expose only capability flags (`stream_available`, `analytics_stream_available`, and `webrtc_preview_available`), and video is fetched through authenticated, department-checked HLS or WHEP relays; raw endpoints stay server-side. The Phase 1 password/session mechanism is for a trusted local demo, not production SSO. Do not place credentials, endpoint values, observed vehicle identifiers, screenshots of government data, or footage in fixtures or committed evidence.
