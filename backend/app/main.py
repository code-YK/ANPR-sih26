import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import log_stream
from app.config import get_settings
from app.audit_middleware import append_access_audit
from app.auth_service import AuthContext, ensure_seed_super_admin, get_current_auth
from app.pipeline import webrtc_relay
from app.services import government_mode as government_mode_service
from app.routers import (
    alerts,
    analytics,
    auth,
    cameras,
    catalogue_sources,
    copilot,
    demo_mode,
    gap_analysis,
    government_mode,
    hls_proxy,
    investigate,
    logs,
    pipeline,
    sightings,
    watchlist,
    webrtc,
)

logging.basicConfig(level=logging.INFO)
# Mirror this process's log output into an in-memory ring buffer so the
# operator console's Logs panel can stream it live (see log_stream.py and
# routers/logs.py). Installed at import time, before uvicorn emits anything.
log_stream.install()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Any worker pid left over from a previous backend process is an orphan
    # by definition (this process's in-memory _workers dict starts empty) --
    # kill it rather than trying to reattach, then let the supervisor start
    # fresh ones for analytics_enabled cameras.
    analytics.kill_orphans_from_previous_run()
    webrtc_relay.kill_orphans_from_previous_run()
    await ensure_seed_super_admin()
    # Say so at startup. The console hides the Copilot launcher when this is
    # unset, which is right for an operator but leaves a developer hunting
    # for a button that was never rendered.
    if get_settings().openrouter_api_key:
        logging.getLogger("sentinel.copilot").info(
            "Copilot enabled (model: %s)", get_settings().openrouter_model
        )
    else:
        logging.getLogger("sentinel.copilot").warning(
            "Copilot disabled: OPENROUTER_API_KEY is not set in backend/.env. "
            "The console will not show its launcher."
        )
    # Monitoring requires an explicit operator action after every backend
    # restart, so no prior persisted intent may auto-start workers here --
    # see clear_persisted_intent.
    await analytics.clear_persisted_intent()
    await investigate.reap_stuck_normalising_on_startup()
    await investigate.reconcile_ingest_on_startup()
    try:
        await webrtc_relay.ensure_mediamtx_running()
    except (RuntimeError, OSError) as exc:
        # WebRTC preview is an enhancement over HLS, never a hard dependency
        # -- a machine without `mediamtx` installed (see
        # docs/webrtc-relay-testing.md) must still serve the rest of the
        # app. The frontend's transport selection already falls back to HLS
        # on any WHEP failure, so every camera stays previewable either way.
        logging.getLogger("sentinel.webrtc_relay").warning(
            "mediamtx unavailable, WebRTC preview disabled for this process: %s", exc
        )
    try:
        await government_mode_service.repair_on_startup()
    except Exception as exc:  # never block startup on the recorded-footage relay
        logging.getLogger("sentinel.government_mode").warning(
            "Government mode could not be repaired at startup; toggle it in Admin > System: %s", exc
        )
    supervisor_task = asyncio.create_task(analytics.supervisor_loop())
    ingest_supervisor_task = asyncio.create_task(investigate.ingest_supervisor_loop())
    evidence_retention_task = asyncio.create_task(sightings.evidence_retention_loop())
    webrtc_supervisor_task = asyncio.create_task(webrtc_relay.webrtc_supervisor_loop())
    try:
        yield
    finally:
        supervisor_task.cancel()
        ingest_supervisor_task.cancel()
        evidence_retention_task.cancel()
        webrtc_supervisor_task.cancel()
        # Unlike the ANPR/ingest workers, a relay or mediamtx itself has no
        # purpose once nothing is listening -- torn down here rather than
        # left for the next startup's orphan-reaper to clean up.
        await webrtc_relay.shutdown_all()


app = FastAPI(
    title="Sentinel Camera Registry",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# Dev-only, and specifically for connection-pool sharding rather than for
# general cross-origin access. A browser allows only ~6 concurrent
# connections per origin on HTTP/1.1, and the Live view can hold nine HLS
# players open; against this sandbox's slow gateway each segment fetch holds
# its connection for seconds, so everything else on the same origin queues
# behind them (measured: a 400-byte telemetry poll taking 22s while the
# detector reported 24 fps). Serving video from 127.0.0.1:8000 while the app
# runs on localhost:5173 makes them separate origins to the browser, so each
# gets its own connection pool -- the classic HTTP/1.1 sharding workaround.
#
# Origins are listed explicitly (never "*") and are loopback only. In
# production the app is served from this same origin by StaticFiles below,
# so no cross-origin request happens and this middleware simply never fires.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5174", "http://127.0.0.1:5174",  # client dev server (fixed port, see its vite.config.js)
        "http://localhost:5175", "http://127.0.0.1:5175",  # frontend-v5 dev server (fixed port, see its vite.config.js)
        "http://localhost:8000", "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def audit_authenticated_access(request, call_next):
    response = await call_next(request)
    await append_access_audit(request, response.status_code)
    return response

app.include_router(logs.router, prefix="/api", tags=["logs"])
app.include_router(cameras.router, prefix="/api", tags=["cameras"])
app.include_router(catalogue_sources.router, prefix="/api", tags=["catalogue-sources"])
app.include_router(auth.router, prefix="/api", tags=["authentication", "authorisation"])
app.include_router(pipeline.router, prefix="/api", tags=["pipeline"])
app.include_router(gap_analysis.router, prefix="/api", tags=["gap-analysis"])
app.include_router(sightings.router, prefix="/api", tags=["sightings"])
app.include_router(watchlist.router, prefix="/api", tags=["watchlist"])
app.include_router(alerts.router, prefix="/api", tags=["alerts"])
app.include_router(analytics.router, prefix="/api", tags=["analytics"])
app.include_router(hls_proxy.router, prefix="/api", tags=["hls-proxy"])
app.include_router(webrtc.router, prefix="/api", tags=["webrtc"])
app.include_router(investigate.router, prefix="/api", tags=["investigate"])
app.include_router(demo_mode.router, prefix="/api", tags=["demo-mode"])
app.include_router(government_mode.router, prefix="/api", tags=["government-mode"])
app.include_router(copilot.router, prefix="/api", tags=["copilot"])


@app.get("/api/health")
async def health(_auth: AuthContext = Depends(get_current_auth)):
    return {"status": "ok"}


@app.get("/openapi.json", include_in_schema=False)
async def protected_openapi(_auth: AuthContext = Depends(get_current_auth)):
    return JSONResponse(app.openapi())


@app.get("/docs", include_in_schema=False)
async def protected_docs(_auth: AuthContext = Depends(get_current_auth)):
    return get_swagger_ui_html(openapi_url="/openapi.json", title=f"{app.title} - API docs")


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
# frontend-v5 is the only built/served console. Its dist/ must exist (run its
# build) for the root route to serve anything.
_REACT_DIST_DIR = os.path.join(_REPO_ROOT, "frontend-v5", "dist")

# Static assets are public so the login page can load; all data/media APIs
# called by the React application enforce authentication.
#
# frontend-v5 is the served console once built (see _REACT_DIST_DIR above);
# client/ is a second console developed against its own dev server and is
# never mounted here (see README#which-console-is-served).


class _SpaStaticFiles(StaticFiles):
    """Serve index.html for client-side routes (e.g. /cameras/cam11) so a
    reload or a shared deep link opens the app instead of a bare 404. API
    paths are registered as routes before this mount and never reach it; an
    unknown /api path still 404s rather than returning the app shell."""

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            # A missing file (anything with an extension, e.g. a stale
            # hashed asset) must stay a 404, not silently become HTML.
            if exc.status_code != 404 or path.startswith("api") or "." in path.rsplit("/", 1)[-1]:
                raise
            return await super().get_response("index.html", scope)


if os.path.isdir(_REACT_DIST_DIR):
    app.mount("/", _SpaStaticFiles(directory=_REACT_DIST_DIR, html=True), name="frontend")
