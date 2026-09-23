# frontend-v5 — operator console

React 19 + Vite 8 console for **SIH26127**, and **the served UI**: `backend/app/main.py` mounts `frontend-v5/dist` at `/`.

`client/` is a second console under active development on port 5174. Its build is never served. Two consoles are maintained in parallel, so **a feature added here does not appear there** — see the repository [README](../README.md#which-console-is-served) and the open decision in [PROJECT_STATE.md](../PROJECT_STATE.md).

## Run

```bash
npm --prefix frontend-v5 ci
npm --prefix frontend-v5 run dev     # port 5175, proxies /api to 127.0.0.1:8000
npm --prefix frontend-v5 run build   # produces dist/, which the backend serves
npm --prefix frontend-v5 run lint
npm --prefix frontend-v5 test
```

The port is fixed at 5175, not auto-selected: media (HLS, MJPEG, evidence) is fetched from the backend's own origin to keep it off this origin's HTTP/1.1 connection pool, so this origin must stay a known entry in the backend's CORS allowlist.

## Layout

| Path | Contents |
|---|---|
| `src/app/` | Shell, routes, top bar |
| `src/features/live/` | Camera grid, focused player, inference panel |
| `src/features/investigate/` | Recordings, plate/person search, track overlay |
| `src/features/journey/` | Cross-camera trajectory map and timeline |
| `src/features/registry/` | Camera list, GIS map, health, gap analysis |
| `src/features/watchlist/`, `alerts/` | Watchlist entries and alert triage |
| `src/features/admin/` | People, departments, sources, audit, system |
| `src/features/copilot/` | Conversational assistant panel ([ADR 0005](../docs/decisions/0005-copilot-in-process-agent.md)) |
| `src/features/workers/` | Analytics worker lifecycle and mode vocabulary |
| `src/features/logs/`, `notifications/`, `workspace/` | Log dock, toasts, pinned-worker rail |
| `src/lib/` | API client, react-query keys, zustand UI store, permissions, formatting |
| `src/styles/` | Design tokens and base styles |

State is split deliberately: server data through `@tanstack/react-query` (`src/lib/queries.js`), view state through `zustand` (`src/lib/uiStore.js`, with only viewer conveniences persisted to `localStorage`).

`src/lib/permissions.js` mirrors the backend's department/clearance rules for hiding controls. It is **not** an authorisation boundary — the API is ([ADR 0003](../docs/decisions/0003-department-rbac.md)).

## Tests

`vitest`, node environment, `src/**/*.test.js` — pure logic only (notification rules, worker state, formatting, Copilot SSE framing). There is no component or end-to-end suite; UI behaviour is verified in a browser against a running backend.

## Known gotcha

On Windows, Vite's file watcher has served a module read mid-write and then missed the final write, leaving a stale or broken module until the dev server restarts. `server.watch.awaitWriteFinish` in `vite.config.js` mitigates it. If a change does not appear, touch the file or restart the dev server before debugging the code; `vite build` is unaffected.
