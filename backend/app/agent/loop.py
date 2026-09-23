"""The tool-calling agent loop, streamed over SSE.

OpenRouter speaks the OpenAI chat-completions shape, so this is a plain
httpx call rather than an SDK dependency -- httpx is already pinned for the
catalogue and geocode clients.

Events emitted (one JSON object per SSE `data:` line):
    {"type": "token",       "text": ...}
    {"type": "tool_start",  "tool": ..., "arguments": {...}}
    {"type": "tool_result", "tool": ..., "render": ..., "result": {...}}
    {"type": "error",       "message": ...}
    {"type": "done"}
"""

from __future__ import annotations

import json
import logging
from typing import AsyncIterator

import httpx

from app.agent import tools as _tools  # noqa: F401  (registers every tool)
from app.agent.prompt import build_system_prompt
from app.agent.registry import ToolContext, dispatch, openai_tools
from app.agent.schemas import ChatRequest
from app.config import get_settings

logger = logging.getLogger("sentinel.copilot")

# What one tool result is allowed to contribute to the model's context. The
# UI still receives the full payload; this cap only governs what re-enters
# the conversation, where an unbounded result would slow every later turn.
MAX_RESULT_CHARS_FOR_MODEL = 2000


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _truncate_for_model(result: dict) -> str:
    text = json.dumps(result, default=str)
    if len(text) <= MAX_RESULT_CHARS_FOR_MODEL:
        return text
    return text[:MAX_RESULT_CHARS_FOR_MODEL] + " ... [truncated; the operator sees the full result]"


def _build_messages(request: ChatRequest, system_prompt: str) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for turn in request.transcript:
        messages.append({"role": turn.role, "content": turn.content})
    messages.append({"role": "user", "content": request.message})
    return messages


async def _stream_completion(
    client: httpx.AsyncClient, messages: list[dict], *, use_tools: bool
) -> AsyncIterator[dict]:
    """One streamed completion. Yields OpenAI-shaped `delta` dicts."""
    settings = get_settings()
    body: dict = {
        "model": settings.openrouter_model,
        "messages": messages,
        "stream": True,
    }
    if use_tools:
        body["tools"] = openai_tools()
        body["tool_choice"] = "auto"

    async with client.stream(
        "POST",
        f"{settings.openrouter_base_url}/chat/completions",
        json=body,
        headers={
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type": "application/json",
            # OpenRouter attribution headers; harmless if unrecognised.
            "X-Title": "Sentinel Copilot",
        },
    ) as response:
        if response.status_code >= 400:
            detail = (await response.aread()).decode("utf-8", "replace")[:500]
            raise RuntimeError(f"OpenRouter returned {response.status_code}: {detail}")
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            chunk = line[6:].strip()
            if chunk == "[DONE]":
                return
            try:
                parsed = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            choices = parsed.get("choices") or []
            if choices:
                yield choices[0]


def _accumulate_tool_calls(buffer: dict[int, dict], deltas: list[dict]) -> None:
    """Merge streamed tool-call fragments.

    Arguments arrive character by character across chunks, and the index --
    not the id -- is what identifies a call while it is still streaming.
    """
    for delta in deltas:
        index = delta.get("index", 0)
        slot = buffer.setdefault(index, {"id": "", "name": "", "arguments": ""})
        if delta.get("id"):
            slot["id"] = delta["id"]
        function = delta.get("function") or {}
        if function.get("name"):
            slot["name"] = function["name"]
        if function.get("arguments"):
            slot["arguments"] += function["arguments"]


async def _run(request: ChatRequest, ctx: ToolContext) -> AsyncIterator[str]:
    settings = get_settings()
    messages = _build_messages(request, build_system_prompt(ctx.auth))

    try:
        async with httpx.AsyncClient(timeout=settings.copilot_request_timeout_seconds) as client:
            for iteration in range(settings.copilot_max_tool_iterations):
                # The final iteration answers in prose: without this the loop
                # could spend its whole budget calling tools and return
                # nothing the operator can read.
                last_chance = iteration == settings.copilot_max_tool_iterations - 1
                text_parts: list[str] = []
                tool_buffer: dict[int, dict] = {}

                async for choice in _stream_completion(
                    client, messages, use_tools=not last_chance
                ):
                    delta = choice.get("delta") or {}
                    if delta.get("content"):
                        text_parts.append(delta["content"])
                        yield _sse({"type": "token", "text": delta["content"]})
                    if delta.get("tool_calls"):
                        _accumulate_tool_calls(tool_buffer, delta["tool_calls"])

                if not tool_buffer:
                    return

                calls = [tool_buffer[i] for i in sorted(tool_buffer)]
                messages.append(
                    {
                        "role": "assistant",
                        "content": "".join(text_parts) or None,
                        "tool_calls": [
                            {
                                "id": call["id"] or f"call_{index}",
                                "type": "function",
                                "function": {
                                    "name": call["name"],
                                    "arguments": call["arguments"] or "{}",
                                },
                            }
                            for index, call in enumerate(calls)
                        ],
                    }
                )

                for call in calls:
                    yield _sse(
                        {
                            "type": "tool_start",
                            "tool": call["name"],
                            "arguments": _safe_args(call["arguments"]),
                        }
                    )

                # Sequential, deliberately. The obvious asyncio.gather here is
                # wrong: every tool shares this request's one AsyncSession, and
                # SQLAlchemy sessions are not safe for concurrent use -- two
                # tools committing at once raises IllegalStateChangeError and
                # can leave the session unusable mid-turn. These tools are
                # local indexed queries in the single-digit milliseconds, so
                # running them in order costs far less than handing each one
                # its own session and connection would.
                results = [
                    await dispatch(call["name"], _safe_args(call["arguments"]), ctx)
                    for call in calls
                ]

                for index, (call, result) in enumerate(zip(calls, results)):
                    yield _sse(
                        {
                            "type": "tool_result",
                            "tool": call["name"],
                            "render": result.get("render", "summary"),
                            "result": result,
                        }
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"] or f"call_{index}",
                            "name": call["name"],
                            "content": _truncate_for_model(result),
                        }
                    )
    except (httpx.HTTPError, RuntimeError) as exc:
        logger.warning("Copilot completion failed: %s", exc)
        yield _sse(
            {
                "type": "error",
                "message": "The assistant is unreachable right now. The console itself is unaffected.",
            }
        )
    except Exception:
        logger.exception("Copilot loop failed")
        yield _sse({"type": "error", "message": "Something went wrong. It has been logged."})


async def run_chat(request: ChatRequest, ctx: ToolContext) -> AsyncIterator[str]:
    """Drive the conversation to a final answer, streaming SSE frames.

    `done` is emitted here rather than in a `finally` inside the generator:
    yielding from `finally` raises if the client disconnects mid-stream and
    the generator is closed, turning a normal hang-up into an error log.
    """
    async for frame in _run(request, ctx):
        yield frame
    yield _sse({"type": "done"})


def _safe_args(raw: str) -> dict:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
