# Operator console (frontend-v2) — reference only

> **This is not the served console.** `frontend-v3` is. The backend mounts `frontend-v3/dist` at `/`.
>
> `frontend-v2` is retained because it is the console most of the project's recorded browser evidence was captured against, and because `frontend-v3` is a strict superset of it — every view, context, and hook here exists there, plus a loading screen and GSAP reveals. Keeping it runnable makes a side-by-side comparison possible.

New work belongs in [`../frontend-v3/`](../frontend-v3/README.md).

## What is here

The same feature set as the served console: registry and GIS map, live video wall, watchlist, alerts, vehicle trajectory search, offline forensic search (Investigate), and analytics controls, backed by the FastAPI `/api` surface.

One real difference: the **city traffic analytics** work on the `new-implementations` branch (`src/views/Traffic/`) was built against *this* console, not `frontend-v3`. Merging that branch therefore includes porting one view across. See [PROJECT_STATE.md](../PROJECT_STATE.md).

## Running it alongside the served console

```bash
npm --prefix frontend-v2 ci
npm --prefix frontend-v2 run dev
```

Opens on **http://localhost:5173**, which is allow-listed in the backend's CORS configuration alongside `frontend-v3`'s 5174, so both can run at once against one backend.

```bash
npm --prefix frontend-v2 run lint
npm --prefix frontend-v2 run build
```

Building writes `frontend-v2/dist/`, which the backend **does not** serve. To serve this console instead, change `_REACT_DIST_DIR` in `backend/app/main.py`.

## Prerequisites

- Node.js `^20.19.0` or `>=22.12.0` (required by Vite 8)
- The backend running at `http://127.0.0.1:8000`

## Security boundary

Unchanged from the served console: the API, not the UI, is the enforcement point. Camera responses carry capability flags only, and video is fetched through authenticated, department-checked relays. Never commit credentials, endpoint values, observed vehicle identifiers, or footage.

See [`../frontend-v3/README.md`](../frontend-v3/README.md) for the full detail and [`/DESIGN.md`](../DESIGN.md) for the design system both consoles share.
