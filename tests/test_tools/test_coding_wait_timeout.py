"""Coding mode: process(wait) default timeout is 90 minutes; off stays 10 min."""
from opensquilla.tools.builtin import shell
from opensquilla.tools.types import CallerKind, ToolContext


def _with_ctx(ctx):
    return shell.current_tool_context.set(ctx)


def test_default_600_when_coding_off():
    tok = _with_ctx(ToolContext(caller_kind=CallerKind.AGENT, coding_mode=False))
    try:
        assert shell._resolve_process_wait_timeout(None) == 600.0
    finally:
        shell.current_tool_context.reset(tok)


def test_default_5400_when_coding_on():
    tok = _with_ctx(ToolContext(caller_kind=CallerKind.AGENT, coding_mode=True))
    try:
        assert shell._resolve_process_wait_timeout(None) == 5400.0
    finally:
        shell.current_tool_context.reset(tok)


def test_explicit_timeout_honored_and_clamped_in_coding_mode():
    tok = _with_ctx(ToolContext(caller_kind=CallerKind.AGENT, coding_mode=True))
    try:
        assert shell._resolve_process_wait_timeout(120) == 120.0
        assert shell._resolve_process_wait_timeout(99999) == 5400.0  # clamp to max
    finally:
        shell.current_tool_context.reset(tok)
