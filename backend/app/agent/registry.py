"""Tool registry for the Copilot agent.

Tools are plain async functions with a Pydantic input model. The registry
generates each one's JSON Schema for the model's tool-calling API and
dispatches calls back to the handler.

The security invariant this module exists to enforce: a tool's *parameters*
come from the language model, but its *scope* never does. `AuthContext` and
the database session are injected by `dispatch`, and `_FORBIDDEN_FIELDS`
below is asserted at registration time so a parameter named `department` or
`user_id` cannot be added by accident later. Without that, the model could be
talked into reading another department's cameras by simply filling in a
field.

Deliberately not MCP: the tools must run under the caller's AuthContext, and
an out-of-process MCP server would need a service token instead, which would
give every chat user that service account's visibility. See
docs/decisions/0005-copilot-in-process-agent.md.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from fastapi import HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_service import AuthContext, add_audit_event

logger = logging.getLogger("sentinel.copilot")

# A parameter with any of these names would let the model choose its own
# scope. Scope comes from AuthContext, never from the conversation.
_FORBIDDEN_FIELDS = frozenset({"auth", "session", "department", "user_id", "role", "clearance"})

# Rendering hints the frontend maps to a component. Anything else is prose.
RENDER_SUMMARY = "summary"
RENDER_WORKER_LIST = "worker_list"
RENDER_CAMERA_PICKER = "camera_picker"
RENDER_NAVIGATE = "navigate"


@dataclass(frozen=True)
class ToolContext:
    """Everything a handler needs that the model is not allowed to supply."""

    auth: AuthContext
    session: AsyncSession


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    params: type[BaseModel]
    handler: Callable[[Any, ToolContext], Awaitable[Any]]
    mutating: bool
    render: str

    def json_schema(self) -> dict:
        """OpenAI/OpenRouter tool-schema form.

        `title` and `description` keys that Pydantic emits per-field are kept
        (the model reads them) but the envelope's own title is dropped: it is
        redundant with the function name and every token here is re-sent on
        each turn, which shows up directly in time-to-first-token.
        """
        schema = self.params.model_json_schema()
        schema.pop("title", None)
        for field in schema.get("properties", {}).values():
            field.pop("title", None)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": schema,
            },
        }


TOOLS: dict[str, Tool] = {}


def tool(
    *,
    name: str,
    description: str,
    params: type[BaseModel],
    mutating: bool = False,
    render: str = RENDER_SUMMARY,
):
    """Register one tool. Raises at import time on an unsafe parameter."""

    leaked = _FORBIDDEN_FIELDS & set(params.model_fields)
    if leaked:
        raise ValueError(
            f"Tool {name!r} exposes scope parameter(s) {sorted(leaked)} to the model. "
            "Scope must come from AuthContext, not from the conversation."
        )
    if name in TOOLS:
        raise ValueError(f"Tool {name!r} is already registered")

    def decorator(handler: Callable[[Any, ToolContext], Awaitable[Any]]):
        TOOLS[name] = Tool(
            name=name,
            description=description,
            params=params,
            handler=handler,
            mutating=mutating,
            render=render,
        )
        return handler

    return decorator


def openai_tools() -> list[dict]:
    return [spec.json_schema() for spec in TOOLS.values()]


async def dispatch(name: str, raw_args: dict, ctx: ToolContext) -> dict:
    """Run one tool call and return a result envelope.

    Never raises for an expected failure. A bad argument, a permission
    denial, a missing camera and a capacity rejection are all *outcomes* the
    model should read and respond to conversationally -- raising here would
    kill the turn and show the operator a stack trace instead of a sentence.
    """
    spec = TOOLS.get(name)
    if spec is None:
        return {"ok": False, "error": f"No such tool: {name}"}

    try:
        parsed = spec.params.model_validate(raw_args or {})
    except ValidationError as exc:
        return {"ok": False, "error": f"Invalid arguments: {exc.errors(include_url=False)}"}

    try:
        data = await spec.handler(parsed, ctx)
        outcome = {"ok": True, "render": spec.render, "data": data}
        audit_result = "success"
    except HTTPException as exc:
        outcome = {"ok": False, "status": exc.status_code, "error": exc.detail}
        audit_result = "denied" if exc.status_code in (401, 403) else "error"
    except Exception:
        # An unexpected fault must not leak internals into a chat transcript.
        logger.exception("Copilot tool %s failed", name)
        outcome = {"ok": False, "error": "This action failed unexpectedly. It has been logged."}
        audit_result = "error"

    add_audit_event(
        ctx.session,
        actor=ctx.auth.user,
        action="copilot.tool_invoked",
        target_type="copilot_tool",
        target_id=name,
        result=audit_result,
        details={"arguments": parsed.model_dump(mode="json"), "mutating": spec.mutating},
    )
    await ctx.session.commit()
    return outcome
