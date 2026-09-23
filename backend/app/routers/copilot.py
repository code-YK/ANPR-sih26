"""Conversational agent endpoint.

Streams SSE. Holds no conversation state: the transcript arrives from the
browser on every request, which is what makes "remembers only this browser
session" true by construction rather than by a cleanup job.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.loop import run_chat
from app.agent.registry import TOOLS, ToolContext
from app.agent.schemas import ChatRequest
from app.auth_service import AuthContext, get_current_auth
from app.config import get_settings
from app.db import get_session

router = APIRouter()

# A deliberately simple in-process limiter, same posture as the analytics
# worker registry: this backend is single-process by design.
_RATE_WINDOW_SECONDS = 60.0
_RATE_MAX_REQUESTS = 20
_recent_requests: dict[int, list[float]] = {}


def _check_rate_limit(user_id: int) -> None:
    now = time.monotonic()
    window = [t for t in _recent_requests.get(user_id, []) if now - t < _RATE_WINDOW_SECONDS]
    if len(window) >= _RATE_MAX_REQUESTS:
        raise HTTPException(
            status_code=429,
            detail="Too many assistant requests in the last minute. Wait a moment and try again.",
        )
    window.append(now)
    _recent_requests[user_id] = window


@router.get("/copilot/status")
async def copilot_status(_auth: AuthContext = Depends(get_current_auth)):
    """Whether the assistant is usable, so the UI can hide the launcher
    rather than offering a button that always fails."""
    settings = get_settings()
    return {
        "available": bool(settings.openrouter_api_key),
        "model": settings.openrouter_model if settings.openrouter_api_key else None,
        "tool_count": len(TOOLS),
    }


@router.post("/copilot/chat")
async def copilot_chat(
    payload: ChatRequest,
    auth: AuthContext = Depends(get_current_auth),
    session: AsyncSession = Depends(get_session),
):
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise HTTPException(
            status_code=503,
            detail="The assistant is not configured on this server (OPENROUTER_API_KEY is unset).",
        )
    _check_rate_limit(auth.user.id)

    ctx = ToolContext(auth=auth, session=session)
    return StreamingResponse(
        run_chat(payload, ctx),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Without this an intermediary proxy may buffer the whole
            # response, which turns a streamed answer into a long pause
            # followed by everything at once.
            "X-Accel-Buffering": "no",
        },
    )
