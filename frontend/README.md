# Original vanilla console — historical, not served

Plain HTML/CSS/JS. The first operator UI this project had, kept as migration history.

**It is not served and must not be.** It has **no authentication flow**, so mounting it would present an unauthenticated application shell over an authenticated API — a misleading surface that looks like access it does not have.

`backend/app/main.py` mounts `frontend-v3/dist` at `/` and never this directory.

## Why it still exists

It documents the shape the console started from, before the React rewrite and the design system in [`/DESIGN.md`](../DESIGN.md). Occasionally useful when tracing why an API response has the shape it does — several endpoints were designed against this UI first.

## Where to work instead

| Console | Path | Status |
|---|---|---|
| `frontend-v3` | [`../frontend-v3/`](../frontend-v3/README.md) | **Served.** All new work goes here |
| `frontend-v2` | [`../frontend-v2/`](../frontend-v2/README.md) | Reference; holds the unmerged Traffic view |
| `frontend` | this directory | Historical only |

## If you are considering deleting it

That is a reasonable call — but make it deliberately, in a PR that says so, rather than as a side effect of another change. The API contracts it exercised are not fully documented anywhere else.
