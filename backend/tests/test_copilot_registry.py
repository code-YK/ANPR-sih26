"""Registry contract tests.

The first class here is the one that matters most: it guards the invariant
that a tool cannot take its scope from the conversation. If that regresses,
a user can be talked into reading another department's data, and nothing
else in the system would notice.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import BaseModel

from app.agent import tools as _tools  # noqa: F401  registers everything
from app.agent.registry import (
    _FORBIDDEN_FIELDS,
    TOOLS,
    Tool,
    ToolContext,
    dispatch,
    openai_tools,
    tool,
)


class TestScopeInvariant:
    def test_no_registered_tool_exposes_a_scope_parameter(self):
        for name, spec in TOOLS.items():
            leaked = _FORBIDDEN_FIELDS & set(spec.params.model_fields)
            assert not leaked, f"{name} exposes scope parameter(s) {sorted(leaked)} to the model"

    def test_generated_schemas_contain_no_scope_parameter(self):
        for schema in openai_tools():
            properties = schema["function"]["parameters"].get("properties", {})
            leaked = _FORBIDDEN_FIELDS & set(properties)
            assert not leaked, f"{schema['function']['name']} leaks {sorted(leaked)} into its schema"

    def test_registering_a_scoped_parameter_is_rejected(self):
        class Bad(BaseModel):
            department: str

        with pytest.raises(ValueError, match="scope parameter"):
            tool(name="bad_tool", description="x", params=Bad)(lambda p, c: None)

    def test_duplicate_registration_is_rejected(self):
        class Params(BaseModel):
            pass

        with pytest.raises(ValueError, match="already registered"):
            tool(name="list_workers", description="x", params=Params)(lambda p, c: None)


class TestSchemaGeneration:
    def test_every_tool_generates_a_valid_function_schema(self):
        for schema in openai_tools():
            assert schema["type"] == "function"
            function = schema["function"]
            assert function["name"] and function["description"]
            assert function["parameters"]["type"] == "object"

    def test_envelope_titles_are_stripped(self):
        """Titles are redundant with the function name and are re-sent every
        turn, so they are pure time-to-first-token cost."""
        for schema in openai_tools():
            parameters = schema["function"]["parameters"]
            assert "title" not in parameters
            for field in parameters.get("properties", {}).values():
                assert "title" not in field

    def test_descriptions_are_substantial(self):
        """A one-line description is the usual cause of a model picking the
        wrong tool, so hold a floor on it."""
        for name, spec in TOOLS.items():
            assert len(spec.description) > 60, f"{name} has too thin a description"


class TestDispatch:
    async def test_unknown_tool_is_an_outcome_not_an_exception(self, ctx):
        result = await dispatch("no_such_tool", {}, ctx)
        assert result["ok"] is False
        assert "No such tool" in result["error"]

    async def test_invalid_arguments_return_a_readable_error(self, ctx):
        result = await dispatch("get_camera", {}, ctx)
        assert result["ok"] is False
        assert "Invalid arguments" in result["error"]

    async def test_http_exception_becomes_a_result(self, ctx):
        """A 403 must reach the model as something it can explain, not as a
        crashed turn."""
        result = await dispatch("navigate_to", {"page": "live_camera"}, ctx)
        assert result["ok"] is False
        assert result["status"] == 422

    async def test_successful_call_carries_its_render_hint(self, ctx):
        result = await dispatch("navigate_to", {"page": "watchlist"}, ctx)
        assert result["ok"] is True
        assert result["render"] == "navigate"
        assert result["data"]["path"] == "/watchlist"

    async def test_every_call_is_audited_and_committed(self, ctx, session):
        await dispatch("navigate_to", {"page": "alerts"}, ctx)
        assert "copilot.tool_invoked" in session.audit_actions
        assert session.commits >= 1

    async def test_failed_calls_are_audited_too(self, ctx, session):
        await dispatch("navigate_to", {"page": "live_camera"}, ctx)
        assert "copilot.tool_invoked" in session.audit_actions

    async def test_unexpected_errors_do_not_leak_internals(self, ctx, monkeypatch):
        async def boom(_params, _ctx):
            raise RuntimeError("connection string postgres://secret@host/db")

        monkeypatch.setitem(
            TOOLS,
            "navigate_to",
            Tool(
                name="navigate_to",
                description=TOOLS["navigate_to"].description,
                params=TOOLS["navigate_to"].params,
                handler=boom,
                mutating=False,
                render="navigate",
            ),
        )
        result = await dispatch("navigate_to", {"page": "alerts"}, ctx)
        assert result["ok"] is False
        assert "secret" not in result["error"]
        assert "postgres" not in result["error"]


class TestMutatingClassification:
    """Safety in v1 comes from omission, not confirmation -- so the set of
    mutating tools is itself part of the contract."""

    EXPECTED_MUTATING = {
        "start_anpr",
        "stop_anpr",
        "start_worker",
        "stop_worker",
        "add_to_watchlist",
        "acknowledge_alert",
        "resolve_alert",
    }

    def test_mutating_set_is_exactly_as_designed(self):
        actual = {name for name, spec in TOOLS.items() if spec.mutating}
        assert actual == self.EXPECTED_MUTATING

    @pytest.mark.parametrize(
        "forbidden",
        [
            "delete_camera",
            "remove_from_watchlist",
            "delete_watchlist_entry",
            "delete_recording",
            "create_camera",
            "bulk_import_cameras",
            "toggle_demo_mode",
            "toggle_government_mode",
            "approve_registration",
            "create_user",
        ],
    )
    def test_irreversible_operations_are_not_reachable(self, forbidden):
        assert forbidden not in TOOLS
