"""Lifecycle tests for `interactive_session()`.

Drives the long-lived `prompt_toolkit.Application` headlessly through a
pipe-input / DummyOutput pair so the asserts run without a TTY.
"""

from __future__ import annotations

import asyncio

import pytest
from prompt_toolkit.formatted_text import to_formatted_text
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from opensquilla.cli.repl import prompt as prompt_module
from opensquilla.cli.repl.app import ChatApplication
from opensquilla.cli.repl.prompt import interactive_session


@pytest.mark.asyncio
async def test_interactive_session_yields_submitted_lines() -> None:
    """Two newline-terminated payloads on the pipe surface as two lines."""
    with create_pipe_input() as pipe:
        async with interactive_session(input=pipe, output=DummyOutput()) as handle:
            pipe.send_text("hello\n")
            first = await asyncio.wait_for(handle.next_line(), timeout=2.0)
            pipe.send_text("world\n")
            second = await asyncio.wait_for(handle.next_line(), timeout=2.0)

    assert first == "hello"
    assert second == "world"


@pytest.mark.asyncio
async def test_interactive_session_ctrl_d_returns_none() -> None:
    """Ctrl-D (\x04) surfaces as `None` from `next_line()`."""
    with create_pipe_input() as pipe:
        async with interactive_session(input=pipe, output=DummyOutput()) as handle:
            pipe.send_text("\x04")
            result = await asyncio.wait_for(handle.next_line(), timeout=2.0)

    assert result is None


@pytest.mark.asyncio
async def test_set_toolbar_mutates_shared_context() -> None:
    """`set_toolbar` writes into `_toolbar_context` and shows up in the
    assistant status header on the next call."""
    previous_status = prompt_module._toolbar_context.get("status")
    previous_model = prompt_module._toolbar_context.get("model")
    previous_suppress = prompt_module._toolbar_context.get("suppress")
    try:
        with create_pipe_input() as pipe:
            async with interactive_session(
                input=pipe,
                output=DummyOutput(),
                model="provider/some-model",
            ) as handle:
                layout_children = handle.application.application.layout.container.content.children
                assert len(layout_children) == 3
                handle.set_toolbar("status", "thinking…")
                # Sanity: shared dict carries the value the handle wrote.
                assert prompt_module._toolbar_context["status"] == "thinking…"
                # With a status set the reply header renders the waiting
                # row; the bottom toolbar stays reserved for idle metadata.
                active_html = prompt_module._bottom_toolbar()
                active_header = prompt_module._input_header_fragments()
                assert "thinking…" not in active_html.value
                assert "some-model" in active_html.value
                assert "thinking…" in active_header.value
                active_header_text = "".join(
                    fragment[1] for fragment in to_formatted_text(active_header)
                )
                assert "◢ squilla" in active_header_text
                assert len(layout_children) == 3
                # Clearing the status drops the chip and brings back the
                # idle dim line carrying the model alias.
                handle.set_toolbar("status", None)
                idle_html = prompt_module._bottom_toolbar()
                idle_header = prompt_module._input_header_fragments()
                assert "some-model" in idle_html.value
                assert idle_header.value == ""
                assert len(layout_children) == 3
    finally:
        prompt_module._toolbar_context["status"] = previous_status
        prompt_module._toolbar_context["model"] = previous_model
        prompt_module._toolbar_context["suppress"] = previous_suppress


@pytest.mark.asyncio
async def test_interactive_session_refreshes_waiting_status() -> None:
    """The long-lived Application must repaint the live waiting row."""
    with create_pipe_input() as pipe:
        async with interactive_session(input=pipe, output=DummyOutput()) as handle:
            assert handle.application.application.refresh_interval == 0.1


@pytest.mark.asyncio
async def test_chat_application_submit_iter_round_trips_lines() -> None:
    """`ChatApplication.submit_iter()` yields each submitted line in order."""
    with create_pipe_input() as pipe:
        async with interactive_session(input=pipe, output=DummyOutput()) as handle:
            inner: ChatApplication = handle.application

            async def collect() -> list[str]:
                collected: list[str] = []
                async for line in inner.submit_iter():
                    collected.append(line)
                    if len(collected) == 2:
                        return collected
                return collected

            collector = asyncio.create_task(collect())
            pipe.send_text("alpha\n")
            pipe.send_text("beta\n")
            lines = await asyncio.wait_for(collector, timeout=2.0)

    assert lines == ["alpha", "beta"]


@pytest.mark.asyncio
async def test_interactive_session_large_paste_shows_marker_but_submits_original() -> None:
    """Large bracketed paste payloads collapse in the buffer, not on submit."""
    with create_pipe_input() as pipe:
        async with interactive_session(input=pipe, output=DummyOutput()) as handle:
            inner: ChatApplication = handle.application
            pasted = "x" * 801

            inner._insert_pasted_content(inner._buffer, pasted)
            assert inner._buffer.text == "[Pasted Content #1 801 chars]"

            inner._on_accept(inner._buffer)
            submitted = await asyncio.wait_for(handle.next_line(), timeout=2.0)

    assert submitted == pasted


@pytest.mark.asyncio
async def test_interactive_session_multiple_same_size_pastes_expand_distinctly() -> None:
    with create_pipe_input() as pipe:
        async with interactive_session(input=pipe, output=DummyOutput()) as handle:
            inner: ChatApplication = handle.application
            first = "a" * 801
            second = "b" * 801

            inner._insert_pasted_content(inner._buffer, first)
            inner._buffer.insert_text(" ")
            inner._insert_pasted_content(inner._buffer, second)
            assert "[Pasted Content #1 801 chars]" in inner._buffer.text
            assert "[Pasted Content #2 801 chars]" in inner._buffer.text

            inner._on_accept(inner._buffer)
            submitted = await asyncio.wait_for(handle.next_line(), timeout=2.0)

    assert submitted == f"{first} {second}"


@pytest.mark.asyncio
async def test_custom_output_does_not_patch_stdout() -> None:
    """Headless custom-output sessions should not probe the real terminal."""
    import sys

    before = sys.stdout
    with create_pipe_input() as pipe:
        async with interactive_session(input=pipe, output=DummyOutput()):
            assert sys.stdout is before
        # After exit: original stdout restored.
        assert sys.stdout is before
