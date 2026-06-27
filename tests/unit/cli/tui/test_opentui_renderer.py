from __future__ import annotations

import pytest

from opensquilla.cli.chat.turn import UsageSummary
from opensquilla.cli.tui.backend.render_summary import summarize_args, summarize_result
from opensquilla.cli.tui.opentui.renderer import OpenTuiStreamRenderer, _format_tokens
from opensquilla.engine.usage import SessionTotalsSnapshot


def test_web_search_args_render_query_summary() -> None:
    assert summarize_args("web_search", {"query": "OpenSquilla canonical search"}) == (
        "OpenSquilla canonical search"
    )
    assert summarize_args("web_discover", {"query": "OpenSquilla discover links"}) == (
        "OpenSquilla discover links"
    )


class _RecordingHandle:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []

    async def send_message(self, message_type: str, payload: dict) -> None:
        self.sent.append((message_type, payload))


class _ToolbarRecordingHandle(_RecordingHandle):
    def __init__(self) -> None:
        super().__init__()
        self.toolbar: dict[str, object] = {}
        self.toolbar_updates: list[tuple[str, object | None]] = []
        self.invalidated = 0

    def set_toolbar(self, key: str, value: object | None) -> None:
        self.toolbar_updates.append((key, value))
        if value is None:
            self.toolbar.pop(key, None)
            return
        self.toolbar[key] = value

    def invalidate(self) -> None:
        self.invalidated += 1


@pytest.mark.asyncio
async def test_intermediate_text_is_thinking_final_text_is_answer_card() -> None:
    """Intermediate narration before a tool (presentation="intermediate") opens
    a purple thinking block; the final answer (presentation="answer") opens a
    cyan answer card. Each is the right kind from its first delta — no retype."""
    handle = _RecordingHandle()
    r = OpenTuiStreamRenderer(output_handle=handle)
    r.__enter__()
    await r.aappend_text("Let me check", presentation="intermediate")
    await r.atool_start("web_search", {"query": "x"}, "c1")
    await r.atool_finished("c1", success=True, result="result line")
    await r.aappend_text("Final answer", presentation="answer")
    await r.afinalize(None)

    assert not [t for t, _ in handle.sent if t == "block.retype"]
    begins = [
        (p["kind"], p["id"])
        for t, p in handle.sent
        if t == "block.begin" and p.get("kind") in {"thinking", "answer"}
    ]
    # intermediate -> thinking block, final -> answer card, in that order
    assert [kind for kind, _id in begins] == ["thinking", "answer"]
    tool_begins = [p for t, p in handle.sent if t == "block.begin" and p.get("kind") == "tool"]
    assert tool_begins and tool_begins[0]["meta"]["name"] == "web_search"


@pytest.mark.asyncio
async def test_final_answer_is_a_card_from_the_first_delta() -> None:
    """A pure-answer turn opens an answer card on the very first delta and
    streams into it — never a thinking block, never a retype."""
    handle = _RecordingHandle()
    r = OpenTuiStreamRenderer(output_handle=handle)
    r.__enter__()
    await r.aappend_text("The ", presentation="answer")
    await r.aappend_text("answer.", presentation="answer")
    await r.afinalize(None)

    assert not [t for t, _ in handle.sent if t == "block.retype"]
    answer_begins = [p for t, p in handle.sent if t == "block.begin" and p.get("kind") == "answer"]
    assert len(answer_begins) == 1
    assert not [
        p for t, p in handle.sent if t == "block.begin" and p.get("kind") == "thinking"
    ]


@pytest.mark.asyncio
async def test_reasoning_renders_as_collapsed_marker_not_streamed_text() -> None:
    """Reasoning (the model's extended-thinking process) must NOT be shown
    verbatim. aappend_reasoning opens a collapsed 'reasoning' marker block — a
    single 'Thinking…' affordance — and the raw reasoning text is never streamed
    onto the timeline as block.append deltas."""
    handle = _RecordingHandle()
    r = OpenTuiStreamRenderer(output_handle=handle)
    r.__enter__()
    await r.aappend_reasoning("let me think step by step about the internals")
    await r.aappend_text("the answer")
    await r.afinalize(None)

    # the reasoning block is its own kind, distinct from intermediate "thinking"
    # text and from the "answer" card
    reasoning_begins = [
        p for t, p in handle.sent if t == "block.begin" and p.get("kind") == "reasoning"
    ]
    assert len(reasoning_begins) == 1
    reasoning_id = reasoning_begins[0]["id"]
    # the verbatim reasoning text is NEVER appended to the timeline
    reasoning_appends = [
        p for t, p in handle.sent if t == "block.append" and p["id"] == reasoning_id
    ]
    assert reasoning_appends == [], "reasoning process text must not be streamed"
    assert not any(
        "step by step" in p.get("delta", "")
        for t, p in handle.sent
        if t == "block.append"
    )
    assert not [t for t, _ in handle.sent if t == "block.retype"]
    # the reasoning marker is closed before the answer block opens
    ends = [p["id"] for t, p in handle.sent if t == "block.end"]
    assert reasoning_id in ends
    answer_begins = [
        p for t, p in handle.sent if t == "block.begin" and p.get("kind") == "answer"
    ]
    assert len(answer_begins) == 1


@pytest.mark.asyncio
async def test_answer_only_turn_has_no_retype() -> None:
    handle = _RecordingHandle()
    r = OpenTuiStreamRenderer(output_handle=handle)
    r.__enter__()
    await r.aappend_text("Direct answer")
    await r.afinalize(None)
    assert not [t for t, _ in handle.sent if t == "block.retype"]
    answer_begins = [p for t, p in handle.sent if t == "block.begin" and p.get("kind") == "answer"]
    assert len(answer_begins) == 1


@pytest.mark.asyncio
async def test_renderer_marks_tool_error_and_cancel() -> None:
    handle = _RecordingHandle()
    r = OpenTuiStreamRenderer(output_handle=handle)
    r.__enter__()
    await r.atool_start("grep", {"pattern": "x"}, "c2")
    await r.atool_finished("c2", success=False, error="boom")
    await r.aerror("turn-level failure")
    await r.afinalize(None, cancelled=True)
    updates = [p for t, p in handle.sent if t == "block.update"]
    assert any(p["patch"].get("status") == "error" for p in updates)
    error_begins = [p for t, p in handle.sent if t == "block.begin" and p.get("kind") == "error"]
    assert error_begins and error_begins[0]["meta"]["text"] == "turn-level failure"
    end = [p for t, p in handle.sent if t == "turn.end"][0]
    assert end["cancelled"] is True
    # the failed tool's detail line was appended into the tool block
    appends = [p for t, p in handle.sent if t == "block.append" and p["id"] == "c2"]
    assert any("boom" in p["delta"] for p in appends)


@pytest.mark.asyncio
async def test_cancel_midtool_closes_open_tool_block() -> None:
    handle = _RecordingHandle()
    r = OpenTuiStreamRenderer(output_handle=handle)
    r.__enter__()
    await r.atool_start("grep", {"pattern": "x"}, "c9")
    # NO atool_finished — simulate cancellation
    await r.afinalize(None, cancelled=True)
    # the open tool must be force-closed: an error update + an end for its id
    updates = [p for t, p in handle.sent if t == "block.update" and p["id"] == "c9"]
    ends = [p for t, p in handle.sent if t == "block.end" and p["id"] == "c9"]
    assert updates and updates[-1]["patch"].get("status") == "error"
    assert ends, "cancelled in-flight tool block was never closed"


@pytest.mark.asyncio
async def test_usage_block_emitted_before_turn_end() -> None:
    handle = _RecordingHandle()
    r = OpenTuiStreamRenderer(output_handle=handle)
    r.__enter__()
    await r.aappend_text("done")
    await r.afinalize(None)
    types = [t for t, _ in handle.sent]
    usage_begin = next(
        i
        for i, (t, p) in enumerate(handle.sent)
        if t == "block.begin" and p.get("kind") == "usage"
    )
    turn_end = types.index("turn.end")
    assert usage_begin < turn_end, "usage block must render in the active turn, before turn.end"
    # answer card still closes (its block.end) before usage
    answer_end = next(
        i
        for i, (t, p) in enumerate(handle.sent)
        if t == "block.end" and p["id"].endswith("-b1")
    )
    assert answer_end < usage_begin


@pytest.mark.asyncio
async def test_anonymous_tools_each_close_independently() -> None:
    handle = _RecordingHandle()
    r = OpenTuiStreamRenderer(output_handle=handle)
    r.__enter__()
    await r.atool_start("a", {}, None)
    await r.atool_finished(None, success=True, result="ra")
    await r.atool_start("b", {}, None)
    await r.atool_finished(None, success=True, result="rb")
    begins = [p for t, p in handle.sent if t == "block.begin" and p.get("kind") == "tool"]
    ends = [p for t, p in handle.sent if t == "block.end"]
    assert len(begins) == 2
    # each tool block gets its own end (distinct ids), so neither overwrites
    # the other and no dangling block is left without a close.
    begin_ids = {p["id"] for p in begins}
    end_ids = {p["id"] for p in ends}
    assert len(begin_ids) == 2
    assert begin_ids <= end_ids


def test_format_tokens_abbreviates_thousands() -> None:
    assert _format_tokens(856) == "856"
    assert _format_tokens(1234) == "1.2k"
    assert _format_tokens(0) == "0"
    assert _format_tokens(None) == "0"


@pytest.mark.asyncio
async def test_afinalize_writes_usage_to_toolbar_and_invalidates() -> None:
    handle = _ToolbarRecordingHandle()
    r = OpenTuiStreamRenderer(output_handle=handle)
    r.__enter__()
    await r.aappend_text("done")
    await r.afinalize(UsageSummary(input_tokens=1234, output_tokens=856))
    assert handle.toolbar.get("router_usage") == "1.2k/856"
    assert handle.invalidated == 2


@pytest.mark.asyncio
async def test_afinalize_writes_session_input_to_toolbar() -> None:
    handle = _ToolbarRecordingHandle()
    r = OpenTuiStreamRenderer(output_handle=handle)
    r.__enter__()
    await r.aappend_text("done")
    await r.afinalize(
        UsageSummary(
            input_tokens=1,
            output_tokens=2,
            session_totals=SessionTotalsSnapshot(input_tokens=84_000),
        )
    )

    assert handle.toolbar.get("router_usage") == "1/2"
    assert handle.toolbar.get("router_session_input") == 84_000
    assert handle.invalidated == 2


@pytest.mark.asyncio
async def test_afinalize_clears_stale_session_input_when_snapshot_missing() -> None:
    handle = _ToolbarRecordingHandle()
    handle.toolbar["router_session_input"] = 84_000
    r = OpenTuiStreamRenderer(output_handle=handle)
    r.__enter__()
    await r.aappend_text("done")
    await r.afinalize(UsageSummary(input_tokens=1, output_tokens=2))

    assert handle.toolbar.get("router_usage") == "1/2"
    assert "router_session_input" not in handle.toolbar
    assert handle.invalidated == 2


@pytest.mark.asyncio
async def test_turn_begin_clears_stale_router_usage_before_finalize_writes_current_usage() -> None:
    handle = _ToolbarRecordingHandle()
    handle.toolbar["router_usage"] = "999/888"
    r = OpenTuiStreamRenderer(output_handle=handle)
    r.__enter__()
    await r.astatus("thinking")

    assert ("router_usage", None) in handle.toolbar_updates
    assert "router_usage" not in handle.toolbar
    assert handle.invalidated == 1

    await r.afinalize(UsageSummary(input_tokens=5, output_tokens=7))

    assert handle.toolbar.get("router_usage") == "5/7"
    assert handle.toolbar_updates[-1] == ("router_usage", "5/7")
    assert handle.invalidated == 2


@pytest.mark.asyncio
async def test_no_usage_turn_keeps_router_usage_cleared() -> None:
    handle = _ToolbarRecordingHandle()
    handle.toolbar["router_usage"] = "999/888"
    r = OpenTuiStreamRenderer(output_handle=handle)
    r.__enter__()
    await r.aappend_text("done")
    await r.afinalize(None)
    assert "router_usage" not in handle.toolbar
    assert handle.invalidated == 1


@pytest.mark.asyncio
async def test_afinalize_tolerates_handle_without_set_toolbar() -> None:
    # The plain recording handle has no set_toolbar/invalidate — afinalize must
    # not crash when wiring usage into the router toolbar.
    handle = _RecordingHandle()
    r = OpenTuiStreamRenderer(output_handle=handle)
    r.__enter__()
    await r.aappend_text("done")
    await r.afinalize(UsageSummary(input_tokens=5, output_tokens=7))
    assert [t for t, _ in handle.sent if t == "turn.end"]


def test_tool_result_summary_keeps_meaningful_lines_without_banners() -> None:
    summary = summarize_result(
        "exit_code=0\n"
        ".\n"
        "·\n"
        "...\n"
        "═══ 一级模块 ═══\n"
        "agents\n"
        "────────\n"
        "exit_code=1\n"
        "================\n"
        "src/opensquilla/main.py\n"
    )

    assert summary == "agents\nexit_code=1\nsrc/opensquilla/main.py"
    assert "exit_code=0" not in summary
    assert " / " not in summary
    assert "═══" not in summary


def test_tool_result_summary_stringifies_single_structured_msg_payload() -> None:
    summary = summarize_result(
        {
            "type": "msg",
            "msg": [
                {"kind": "text", "text": "first"},
                {"kind": "data", "value": {"rows": [1, 2]}},
            ],
        }
    )

    assert summary.startswith("[")
    assert '"type": "msg"' not in summary
    assert '"rows": [1, 2]' in summary


def test_tool_result_summary_stringifies_structured_msg_payloads() -> None:
    summary = summarize_result(
        [
            {"type": "msg", "msg": {"files": ["main.py"], "count": 1}},
            {"type": "msg", "msg": ["ok", {"status": "done"}]},
        ]
    )

    assert summary == (
        '{"count": 1, "files": ["main.py"]}\n'
        '["ok", {"status": "done"}]'
    )
