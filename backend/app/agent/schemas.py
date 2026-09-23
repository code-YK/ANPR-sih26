"""Wire types for the Copilot chat endpoint."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# The transcript lives in the browser and is replayed on every request, so
# the backend holds no conversation state at all. Bounded here because an
# unbounded transcript is both a cost problem and a trivially abusable one.
MAX_TRANSCRIPT_TURNS = 40


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    transcript: list[ChatTurn] = Field(
        default_factory=list, max_length=MAX_TRANSCRIPT_TURNS,
        description="Prior turns from this browser session, oldest first.",
    )
