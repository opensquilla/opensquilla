"""Unit contract for ToolStreamAccumulator's grammar operations.

Each operation maps to a provider stream grammar: ``start``/``append``/
``finish`` (identity-first, Anthropic), ``append_or_start``/``finish_all``
(identity-on-first-delta, OpenAI Chat), ``start``+``append``+
``finish_with_arguments`` (whole-call, Ollama/Responses).
"""

from __future__ import annotations

from opensquilla.provider.stream_assembly import (
    ToolStreamAccumulator,
    parse_tool_arguments,
)
from opensquilla.provider.types import (
    ToolUseDeltaEvent,
    ToolUseEndEvent,
    ToolUseStartEvent,
)


def test_parse_tool_arguments_contract() -> None:
    assert parse_tool_arguments("") == {}
    assert parse_tool_arguments('{"a": 1}') == {"a": 1}
    assert parse_tool_arguments('{"broken') == {"_raw": '{"broken'}
    assert parse_tool_arguments("[1, 2]") == {"_raw": "[1, 2]"}


def test_identity_first_grammar() -> None:
    acc = ToolStreamAccumulator()
    events = acc.start(0, tool_use_id="toolu_1", tool_name="search")
    assert [type(e) for e in events] == [ToolUseStartEvent]
    events = acc.append(0, '{"q":')
    events += acc.append(0, ' "x"}')
    assert all(isinstance(e, ToolUseDeltaEvent) for e in events)
    assert all(e.tool_use_id == "toolu_1" for e in events)
    (end,) = acc.finish(0)
    assert isinstance(end, ToolUseEndEvent)
    assert end.arguments == {"q": "x"}
    assert end.tool_name == "search"


def test_append_or_start_freezes_public_id() -> None:
    acc = ToolStreamAccumulator()
    first = acc.append_or_start(0, tool_call_id=None, tool_name="search", fragment='{"a"')
    start = first[0]
    assert isinstance(start, ToolUseStartEvent)
    synthesized = start.tool_use_id
    assert synthesized.startswith("call_")
    # Late real id: wire only, public id unchanged.
    later = acc.append_or_start(0, tool_call_id="call_real", fragment=": 1}")
    assert all(e.tool_use_id == synthesized for e in later)
    ends = list(acc.finish_all())
    assert len(ends) == 1
    assert ends[0].tool_use_id == synthesized
    assert ends[0].arguments == {"a": 1}
    # The wire id is still matchable for index resolution.
    assert acc.find_key_for_tool_call_id("call_real") == 0


def test_parallel_calls_never_mix_fragments() -> None:
    acc = ToolStreamAccumulator()
    acc.append_or_start(0, tool_call_id="call_a", tool_name="alpha", fragment='{"a"')
    acc.append_or_start(1, tool_call_id="call_b", tool_name="beta", fragment='{"b"')
    acc.append_or_start(0, fragment=": 1}")
    acc.append_or_start(1, fragment=": 2}")
    ends = {e.tool_use_id: e for e in acc.finish_all()}
    assert ends["call_a"].arguments == {"a": 1}
    assert ends["call_b"].arguments == {"b": 2}


def test_finish_is_idempotent_and_finish_all_skips_closed() -> None:
    acc = ToolStreamAccumulator()
    acc.start(0, tool_use_id="t1", tool_name="a")
    acc.start(1, tool_use_id="t2", tool_name="b")
    assert len(acc.finish(0)) == 1
    assert acc.finish(0) == []
    remaining = list(acc.finish_all())
    assert [e.tool_use_id for e in remaining] == ["t2"]
    assert list(acc.finish_all()) == []


def test_append_on_unknown_key_returns_no_events() -> None:
    acc = ToolStreamAccumulator()
    assert acc.append(7, '{"x": 1}') == []
    assert not acc.has_calls


def test_finish_with_arguments_is_authoritative() -> None:
    acc = ToolStreamAccumulator()
    acc.start("item_1", tool_use_id="call_1", tool_name="run")
    acc.append("item_1", "not json at all")
    (end,) = acc.finish_with_arguments("item_1", {"cmd": "ls"})
    assert end.arguments == {"cmd": "ls"}


def test_zero_argument_call_yields_empty_dict() -> None:
    acc = ToolStreamAccumulator()
    acc.start(0, tool_use_id="t1", tool_name="ping")
    (end,) = acc.finish(0)
    assert end.arguments == {}


def test_metadata_and_key_queries() -> None:
    acc = ToolStreamAccumulator()
    assert acc.next_int_key() == 0
    acc.append_or_start(0, tool_call_id="call_a", tool_name="a")
    acc.set_metadata(0, "thought_signature", "sig-1")
    assert acc.first_metadata("thought_signature") == "sig-1"
    assert acc.first_metadata("missing") is None
    assert acc.single_key() == 0
    assert acc.next_int_key() == 1
    acc.append_or_start(3, tool_call_id="call_b", tool_name="b")
    assert acc.single_key() is None
    assert acc.next_int_key() == 4
    assert acc.find_key_for_tool_call_id("call_b") == 3
    assert acc.find_key_for_tool_call_id("nope") is None
