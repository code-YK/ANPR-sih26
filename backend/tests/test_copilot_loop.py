"""Agent-loop and SSE protocol tests.

The model itself is faked. What is under test is the loop's own behaviour:
that streamed tool-call fragments reassemble correctly, that results are
bounded before re-entering the context, that the iteration cap holds, and
that a failing model degrades into a readable message instead of a broken
stream.
"""

from __future__ import annotations

import json

import pytest

from app.agent import loop as loop_module
from app.agent.loop import _accumulate_tool_calls, _safe_args, _truncate_for_model, run_chat
from app.agent.registry import ToolContext
from app.agent.schemas import ChatRequest, ChatTurn
from tests.conftest import make_auth


def text_chunk(text: str) -> dict:
    return {"delta": {"content": text}}


def tool_chunk(index: int, *, call_id=None, name=None, arguments=None) -> dict:
    fragment: dict = {"index": index}
    if call_id:
        fragment["id"] = call_id
    function = {}
    if name:
        function["name"] = name
    if arguments is not None:
        function["arguments"] = arguments
    if function:
        fragment["function"] = function
    return {"delta": {"tool_calls": [fragment]}}


def fake_model(scripted_turns: list[list[dict]]):
    """Return a _stream_completion replacement that plays back turns."""
    turns = iter(scripted_turns)

    async def _stream(_client, _messages, *, use_tools):  # noqa: ARG001
        for chunk in next(turns, []):
            yield chunk

    return _stream


async def collect(request, ctx) -> list[dict]:
    events = []
    async for frame in run_chat(request, ctx):
        assert frame.startswith("data: ")
        events.append(json.loads(frame[6:].strip()))
    return events


@pytest.fixture
def chat_ctx(session):
    return ToolContext(auth=make_auth(role="super_admin"), session=session)


class TestToolCallAccumulation:
    def test_fragments_merge_by_index(self):
        """Arguments arrive a few characters at a time; the index, not the
        id, identifies a call while it is still streaming."""
        buffer: dict[int, dict] = {}
        _accumulate_tool_calls(buffer, [{"index": 0, "id": "call_1", "function": {"name": "trace_vehicle"}}])
        _accumulate_tool_calls(buffer, [{"index": 0, "function": {"arguments": '{"pla'}}])
        _accumulate_tool_calls(buffer, [{"index": 0, "function": {"arguments": 'te":"GJ01"}'}}])
        assert buffer[0] == {"id": "call_1", "name": "trace_vehicle", "arguments": '{"plate":"GJ01"}'}

    def test_parallel_calls_stay_separate(self):
        buffer: dict[int, dict] = {}
        _accumulate_tool_calls(
            buffer,
            [
                {"index": 0, "id": "a", "function": {"name": "trace_vehicle", "arguments": "{}"}},
                {"index": 1, "id": "b", "function": {"name": "navigate_to", "arguments": "{}"}},
            ],
        )
        assert buffer[0]["name"] == "trace_vehicle"
        assert buffer[1]["name"] == "navigate_to"

    def test_missing_index_defaults_to_zero(self):
        buffer: dict[int, dict] = {}
        _accumulate_tool_calls(buffer, [{"function": {"name": "list_workers"}}])
        assert buffer[0]["name"] == "list_workers"


class TestArgumentParsing:
    @pytest.mark.parametrize("raw", ["", "{}", "not json", "[1,2,3]", "null"])
    def test_malformed_arguments_degrade_to_empty_dict(self, raw):
        """A truncated stream must not crash the turn -- the tool's own
        validation will produce a readable error instead."""
        assert _safe_args(raw) == {}

    def test_valid_arguments_parse(self):
        assert _safe_args('{"plate":"GJ01AB1234"}') == {"plate": "GJ01AB1234"}


class TestResultTruncation:
    def test_small_results_pass_through_whole(self):
        result = {"ok": True, "data": {"count": 2}}
        assert json.loads(_truncate_for_model(result)) == result

    def test_large_results_are_bounded(self):
        """An unbounded result would dominate the context and slow every
        later turn in the conversation."""
        result = {"ok": True, "data": {"cameras": [{"id": f"cam{i:03d}"} for i in range(2000)]}}
        truncated = _truncate_for_model(result)
        assert len(truncated) < loop_module.MAX_RESULT_CHARS_FOR_MODEL + 100
        assert "truncated" in truncated

    def test_non_serialisable_values_do_not_raise(self):
        from datetime import datetime

        assert "2026" in _truncate_for_model({"seen_at": datetime(2026, 9, 23)})


class TestStreaming:
    async def test_plain_answer_streams_tokens_then_done(self, chat_ctx, monkeypatch):
        monkeypatch.setattr(
            loop_module, "_stream_completion", fake_model([[text_chunk("Hello"), text_chunk(" there")]])
        )
        events = await collect(ChatRequest(message="hi"), chat_ctx)
        assert [e["type"] for e in events] == ["token", "token", "done"]
        assert "".join(e["text"] for e in events if e["type"] == "token") == "Hello there"

    async def test_tool_call_emits_start_then_result(self, chat_ctx, monkeypatch):
        monkeypatch.setattr(
            loop_module,
            "_stream_completion",
            fake_model(
                [
                    [tool_chunk(0, call_id="c1", name="navigate_to", arguments='{"page":"watchlist"}')],
                    [text_chunk("Opened the watchlist.")],
                ]
            ),
        )
        events = await collect(ChatRequest(message="open watchlist"), chat_ctx)
        types = [e["type"] for e in events]
        assert types == ["tool_start", "tool_result", "token", "done"]
        assert events[0]["tool"] == "navigate_to"
        assert events[1]["render"] == "navigate"
        assert events[1]["result"]["data"]["path"] == "/watchlist"

    async def test_multiple_tool_calls_never_overlap_on_the_session(self, chat_ctx, monkeypatch):
        """Regression: the first implementation used asyncio.gather here.

        Every tool shares one AsyncSession, and SQLAlchemy raises
        IllegalStateChangeError if two of them commit concurrently -- which
        only showed up once a real model asked for two tools in one turn.
        This asserts no dispatch starts before the previous one finishes.
        """
        from app.agent import registry as registry_module

        overlap = 0
        active = 0
        real_dispatch = registry_module.dispatch

        async def tracking_dispatch(name, raw_args, ctx):
            nonlocal overlap, active
            active += 1
            if active > 1:
                overlap += 1
            try:
                import asyncio

                await asyncio.sleep(0)  # a real yield point, as a DB call would be
                return await real_dispatch(name, raw_args, ctx)
            finally:
                active -= 1

        monkeypatch.setattr(loop_module, "dispatch", tracking_dispatch)
        monkeypatch.setattr(
            loop_module,
            "_stream_completion",
            fake_model(
                [
                    [
                        tool_chunk(0, call_id="c1", name="get_capacity", arguments="{}"),
                        tool_chunk(1, call_id="c2", name="navigate_to", arguments='{"page":"live"}'),
                        tool_chunk(2, call_id="c3", name="get_capacity", arguments="{}"),
                    ],
                    [text_chunk("Done.")],
                ]
            ),
        )
        events = await collect(ChatRequest(message="status"), chat_ctx)
        assert len([e for e in events if e["type"] == "tool_result"]) == 3
        assert overlap == 0, "tool calls overlapped on a shared AsyncSession"

    async def test_parallel_tool_calls_both_execute(self, chat_ctx, monkeypatch):
        monkeypatch.setattr(
            loop_module,
            "_stream_completion",
            fake_model(
                [
                    [
                        tool_chunk(0, call_id="c1", name="get_capacity", arguments="{}"),
                        tool_chunk(1, call_id="c2", name="navigate_to", arguments='{"page":"live"}'),
                    ],
                    [text_chunk("Done.")],
                ]
            ),
        )
        events = await collect(ChatRequest(message="status"), chat_ctx)
        called = [e["tool"] for e in events if e["type"] == "tool_start"]
        assert called == ["get_capacity", "navigate_to"]

    async def test_iteration_cap_terminates_a_looping_model(self, chat_ctx, monkeypatch):
        """A model that only ever calls tools must still end the turn."""
        monkeypatch.setattr(
            loop_module,
            "_stream_completion",
            fake_model([[tool_chunk(0, call_id=f"c{i}", name="get_capacity", arguments="{}")] for i in range(20)]),
        )
        events = await collect(ChatRequest(message="loop"), chat_ctx)
        starts = [e for e in events if e["type"] == "tool_start"]
        from app.config import get_settings

        assert len(starts) <= get_settings().copilot_max_tool_iterations
        assert events[-1]["type"] == "done"

    async def test_model_failure_becomes_a_readable_error(self, chat_ctx, monkeypatch):
        async def _boom(_client, _messages, *, use_tools):  # noqa: ARG001
            raise RuntimeError("OpenRouter returned 502: upstream error")
            yield  # pragma: no cover

        monkeypatch.setattr(loop_module, "_stream_completion", _boom)
        events = await collect(ChatRequest(message="hi"), chat_ctx)
        assert events[0]["type"] == "error"
        assert "console itself is unaffected" in events[0]["message"]
        assert events[-1]["type"] == "done"

    async def test_a_failing_tool_does_not_end_the_stream(self, chat_ctx, monkeypatch):
        monkeypatch.setattr(
            loop_module,
            "_stream_completion",
            fake_model(
                [
                    [tool_chunk(0, call_id="c1", name="navigate_to", arguments='{"page":"live_camera"}')],
                    [text_chunk("I need the camera id.")],
                ]
            ),
        )
        events = await collect(ChatRequest(message="open camera"), chat_ctx)
        result = next(e for e in events if e["type"] == "tool_result")
        assert result["result"]["ok"] is False
        assert events[-1]["type"] == "done"


class TestMessageAssembly:
    def test_transcript_is_replayed_before_the_new_message(self):
        request = ChatRequest(
            message="and the second one?",
            transcript=[
                ChatTurn(role="user", content="list cameras"),
                ChatTurn(role="assistant", content="Found 3."),
            ],
        )
        messages = loop_module._build_messages(request, "SYSTEM")
        assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
        assert messages[-1]["content"] == "and the second one?"

    def test_transcript_length_is_bounded_by_the_schema(self):
        from pydantic import ValidationError

        from app.agent.schemas import MAX_TRANSCRIPT_TURNS

        turns = [ChatTurn(role="user", content="x")] * (MAX_TRANSCRIPT_TURNS + 1)
        with pytest.raises(ValidationError):
            ChatRequest(message="hi", transcript=turns)
