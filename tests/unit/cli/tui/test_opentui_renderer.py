from __future__ import annotations

import pytest

from opensquilla.cli.tui.opentui.renderer import OpenTuiStreamRenderer
from opensquilla.cli.tui.terminal.stream import _summarize_result


class _RecordingHandle:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []

    async def send_message(self, message_type: str, payload: dict) -> None:
        self.sent.append((message_type, payload))


@pytest.mark.asyncio
async def test_text_then_tool_becomes_thinking_block() -> None:
    handle = _RecordingHandle()
    r = OpenTuiStreamRenderer(output_handle=handle)
    r.__enter__()
    await r.aappend_text("Let me check")
    await r.atool_start("web_search", {"query": "x"}, "c1")
    await r.atool_finished("c1", success=True, result="result line")
    await r.aappend_text("Final answer")
    await r.afinalize(None)
    retypes = [p for t, p in handle.sent if t == "block.retype"]
    assert retypes and retypes[0]["kind"] == "thinking"
    tool_begins = [p for t, p in handle.sent if t == "block.begin" and p.get("kind") == "tool"]
    assert tool_begins and tool_begins[0]["meta"]["name"] == "web_search"
    answer_begins = [p for t, p in handle.sent if t == "block.begin" and p.get("kind") == "answer"]
    assert len(answer_begins) == 2
    ends = [t for t, _ in handle.sent if t == "block.end"]
    assert ends


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


def test_tool_result_summary_keeps_meaningful_lines_without_banners() -> None:
    summary = _summarize_result(
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
    summary = _summarize_result(
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
    summary = _summarize_result(
        [
            {"type": "msg", "msg": {"files": ["main.py"], "count": 1}},
            {"type": "msg", "msg": ["ok", {"status": "done"}]},
        ]
    )

    assert summary == (
        '{"count": 1, "files": ["main.py"]}\n'
        '["ok", {"status": "done"}]'
    )
