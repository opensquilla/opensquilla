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
async def test_renderer_emits_turn_lifecycle_and_blocks() -> None:
    handle = _RecordingHandle()
    renderer = OpenTuiStreamRenderer(title="squilla", output_handle=handle)

    renderer.__enter__()
    await renderer.astatus("先扫描结构")
    await renderer.atool_start("read_file", {"path": "main.py"}, "c1")
    await renderer.atool_finished("c1", success=True)
    await renderer.aappend_text("架构分四层")
    answer_texts = [p.get("text") for t, p in handle.sent if t == "answer.text"]
    assert "".join(answer_texts) == "架构分四层"
    await renderer.afinalize(None, cancelled=False)
    renderer.__exit__(None, None, None)

    types = [t for t, _ in handle.sent]
    assert types[0] == "turn.begin"
    assert "turn.status" in types
    assert "model.text" in types
    assert "tool.call" in types
    assert "answer.text" in types
    assert "usage" in types
    assert "turn.end" in types
    tool_calls = [p for t, p in handle.sent if t == "tool.call"]
    assert [p.get("status") for p in tool_calls] == ["running", "ok"]
    assert all(p.get("id") == "c1" for p in tool_calls)
    assert tool_calls[0]["name"] == "read_file"
    assert tool_calls[0]["summary"]  # arg summary is preserved on the finish line
    assert any(t == "turn.status" and p.get("phase") == "tool" for t, p in handle.sent)
    assert any(t == "turn.status" and p.get("phase") == "output" for t, p in handle.sent)
    # composer is disabled when the turn begins and re-enabled when it ends
    composer_disabled = [p.get("disabled") for t, p in handle.sent if t == "composer.set"]
    assert composer_disabled == [True, False]


@pytest.mark.asyncio
async def test_renderer_marks_tool_error_and_cancel() -> None:
    handle = _RecordingHandle()
    renderer = OpenTuiStreamRenderer(output_handle=handle)
    renderer.__enter__()
    await renderer.atool_start("grep", {"pattern": "x"}, "c2")
    await renderer.atool_finished("c2", success=False, error="boom")
    await renderer.afinalize(None, cancelled=True)

    tool_states = [p.get("status") for t, p in handle.sent if t == "tool.call"]
    assert "error" in tool_states
    end = [p for t, p in handle.sent if t == "turn.end"][0]
    assert end["cancelled"] is True


def test_tool_result_summary_keeps_meaningful_lines_without_banners() -> None:
    summary = _summarize_result(
        "exit_code=0\n"
        "═══ 一级模块 ═══\n"
        "agents\n"
        "────────\n"
        "memory\n"
        "================\n"
        "tools\n"
    )

    assert summary == "exit_code=0\nagents\nmemory"
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
