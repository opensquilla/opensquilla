"""Tests for _ToolCallStrip coalescing logic in stream.py."""

from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from rich.console import Console

from opensquilla.cli.repl.stream import StreamingRenderer, _summarize_args


# ---------------------------------------------------------------------------
# _summarize_args unit tests
# ---------------------------------------------------------------------------


def test_summarize_exec_command() -> None:
    result = _summarize_args("exec_command", {"command": "ls -la /tmp"})
    assert result == "ls -la /tmp"


def test_summarize_background_process() -> None:
    result = _summarize_args("background_process", {"command": "sleep 10"})
    assert result == "sleep 10"


def test_summarize_execute_code_first_line() -> None:
    result = _summarize_args("execute_code", {"code": "print('hello')\nprint('world')"})
    assert result == "print('hello')"


def test_summarize_read_file() -> None:
    result = _summarize_args("read_file", {"path": "/tmp/test.txt"})
    assert result == "/tmp/test.txt"


def test_summarize_web_search() -> None:
    result = _summarize_args("web_search", {"query": "python asyncio"})
    assert result == "python asyncio"


def test_summarize_web_fetch() -> None:
    result = _summarize_args("web_fetch", {"url": "https://example.com"})
    assert result == "https://example.com"


def test_summarize_unknown_tool() -> None:
    result = _summarize_args("unknown_tool", {"anything": "value"})
    assert result == ""


def test_summarize_no_args() -> None:
    result = _summarize_args("exec_command", None)
    assert result == ""


# ---------------------------------------------------------------------------
# ToolCallStrip coalescing via StreamingRenderer
# ---------------------------------------------------------------------------


def _make_renderer_with_capture() -> tuple[StreamingRenderer, StringIO]:
    """Return a renderer that prints to a captured buffer."""
    buf = StringIO()
    capture_console = Console(file=buf, highlight=False, force_terminal=False)
    renderer = StreamingRenderer()
    # Patch the module-level console used by _ToolCallStrip
    renderer._strip._flush_run  # access to confirm strip exists
    return renderer, buf


def _captured_tool_lines(calls: list[tuple[str, str | None]]) -> list[str]:
    """Run a sequence of tool_start calls through a strip and return printed lines."""
    buf = StringIO()
    capture = Console(file=buf, highlight=False, force_terminal=False, no_color=True)

    from opensquilla.cli.repl import stream as stream_mod

    original = stream_mod.console
    stream_mod.console = capture  # type: ignore[assignment]
    try:
        renderer = StreamingRenderer()
        for name, tid in calls:
            renderer.tool_start(name, None, tid)
        renderer._strip.flush()
    finally:
        stream_mod.console = original

    return [line for line in buf.getvalue().splitlines() if line.strip()]


def test_one_call_prints_one_line() -> None:
    lines = _captured_tool_lines([("exec_command", "id-1")])
    assert len(lines) == 1
    assert "exec_command" in lines[0]


def test_two_calls_same_name_print_two_lines() -> None:
    lines = _captured_tool_lines([("exec_command", "id-1"), ("exec_command", "id-2")])
    assert len(lines) == 2
    for line in lines:
        assert "exec_command" in line


def test_third_call_prints_cumulative_line() -> None:
    lines = _captured_tool_lines(
        [("exec_command", "id-1"), ("exec_command", "id-2"), ("exec_command", "id-3")]
    )
    # Row 1, row 2, ×3 (cumulative); flush() at end emits "×3 total Xs"
    assert any("×3" in line and "cumulative" in line for line in lines), lines
    # The cumulative line must appear before any total line
    cumulative_idx = next(i for i, l in enumerate(lines) if "cumulative" in l)
    assert cumulative_idx == 2


def test_fourth_call_same_name_suppressed() -> None:
    lines = _captured_tool_lines(
        [
            ("exec_command", "id-1"),
            ("exec_command", "id-2"),
            ("exec_command", "id-3"),
            ("exec_command", "id-4"),
        ]
    )
    # Row 1, row 2, ×3 cumulative — row 4 suppressed, flush emits total
    # No 4th normal row printed — only the coalesced cumulative on row 3
    cumulative_lines = [l for l in lines if "cumulative" in l]
    assert len(cumulative_lines) == 1, f"Expected exactly 1 cumulative line, got: {lines}"
    # The ×N total line (from flush) mentions ×4
    total_lines = [l for l in lines if "total" in l]
    assert len(total_lines) == 1
    assert "×4" in total_lines[0]


def test_name_change_after_run_of_3_flushes_total_line() -> None:
    lines = _captured_tool_lines(
        [
            ("exec_command", "id-1"),
            ("exec_command", "id-2"),
            ("exec_command", "id-3"),
            ("read_file", "id-4"),  # name change triggers flush
        ]
    )
    # row1, row2, ×3 cumulative, ×3 total Xs, then read_file row
    assert any("×3" in line and "total" in line for line in lines), lines
    assert any("read_file" in line for line in lines)


def test_error_on_finish_prints_error_row() -> None:
    buf = StringIO()
    capture = Console(file=buf, highlight=False, force_terminal=False, no_color=True)

    from opensquilla.cli.repl import stream as stream_mod

    original = stream_mod.console
    stream_mod.console = capture  # type: ignore[assignment]
    try:
        renderer = StreamingRenderer()
        renderer.tool_start("exec_command", None, "id-1")
        renderer.tool_start("exec_command", None, "id-2")
        renderer.tool_start("exec_command", None, "id-3")
        renderer.tool_finished("id-3", success=False, error="permission denied")
    finally:
        stream_mod.console = original

    lines = [line for line in buf.getvalue().splitlines() if line.strip()]
    assert any("permission denied" in line for line in lines)
