"""Server-Sent Events endpoints backing the operator console's Logs panel.

Two live streams, both for any authenticated user (the panel is a shared
debugging aid, not privileged data beyond what the console already shows):

  GET /api/logs/backend  -- this process's own log output
  GET /api/logs/workers  -- the ANPR/person inference subprocess logs

Each streams `text/event-stream`. A client (EventSource) receives a backlog
of recent lines on connect, then new lines as they happen. The generators
poll the in-memory buffers (see log_stream.py) on a short interval rather
than being pushed to, which keeps them robust across the several threads
that can emit a log record, and they end cleanly when the client goes away
(StreamingResponse cancels the generator on disconnect).
"""

import asyncio
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app import log_stream
from app.auth_service import AuthContext, get_current_auth

router = APIRouter()

# How often each stream checks its buffer for new lines. Fast enough to feel
# live, slow enough that an idle panel is nearly free.
_POLL_SECONDS = 0.5
# A comment line every so often so proxies (and the Vite dev proxy) keep the
# connection open through quiet periods.
_KEEPALIVE_SECONDS = 15.0


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@router.get("/logs/backend")
async def stream_backend_logs(_auth: AuthContext = Depends(get_current_auth)):
    async def gen():
        last_seq = 0
        # Backlog first, so the panel opens populated.
        backlog = log_stream.backend_entries_since(0)
        if backlog:
            last_seq = backlog[-1]["seq"]
            for entry in backlog:
                yield _sse(entry)
        idle = 0.0
        while True:
            await asyncio.sleep(_POLL_SECONDS)
            entries = log_stream.backend_entries_since(last_seq)
            if entries:
                last_seq = entries[-1]["seq"]
                for entry in entries:
                    yield _sse(entry)
                idle = 0.0
            else:
                idle += _POLL_SECONDS
                if idle >= _KEEPALIVE_SECONDS:
                    idle = 0.0
                    yield ": keepalive\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/logs/workers")
async def stream_worker_logs(_auth: AuthContext = Depends(get_current_auth)):
    async def gen():
        offsets = log_stream.worker_initial_offsets()
        # Emit the initial backfill immediately.
        for entry in log_stream.worker_lines_since(offsets):
            yield _sse(entry)
        idle = 0.0
        while True:
            await asyncio.sleep(_POLL_SECONDS)
            entries = log_stream.worker_lines_since(offsets)
            if entries:
                for entry in entries:
                    yield _sse(entry)
                idle = 0.0
            else:
                idle += _POLL_SECONDS
                if idle >= _KEEPALIVE_SECONDS:
                    idle = 0.0
                    yield ": keepalive\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
