"""Lifecycle tests for `interactive_session()`.

Drives the long-lived `prompt_toolkit.Application` headlessly through a
pipe-input / DummyOutput pair so the asserts run without a TTY.
"""

from __future__ import annotations

import asyncio

import pytest
from prompt_toolkit.application.current import create_app_session
from prompt_toolkit.formatted_text import to_formatted_text
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.input.base import DummyInput
from prompt_toolkit.output import DummyOutput

from opensquilla.cli.repl import prompt as prompt_module
from opensquilla.cli.repl.app import ChatApplication
from opensquilla.cli.repl.prompt import interactive_session
from opensquilla.engine.commands import Surface


def _fresh_chat_app(*, pipe_input=None) -> ChatApplication:
    return ChatApplication(
        surface=Surface.CLI_GATEWAY,
        toolbar_context=prompt_module._toolbar_context,
        bottom_toolbar=prompt_module._bottom_toolbar,
        style=None,
        input=pipe_input or DummyInput(),
        output=DummyOutput(),
        input_header=prompt_module._input_header_fragments,
    )


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
async def test_cached_chat_application_can_emit_eof_after_reentry() -> None:
    """A cached production ChatApplication must not keep EOF latched forever."""
    prompt_module._chat_applications.clear()
    try:
        with create_app_session(input=DummyInput(), output=DummyOutput()):
            app1 = prompt_module._get_or_create_chat_app(Surface.CLI_GATEWAY)
            app1._emit_eof()
            first = await asyncio.wait_for(app1.next_line(), timeout=0.2)

            app2 = prompt_module._get_or_create_chat_app(Surface.CLI_GATEWAY)
            same_cached_app = app1 is app2
            app2._emit_eof()
            second = await asyncio.wait_for(app2.next_line(), timeout=0.2)
    finally:
        prompt_module._chat_applications.clear()

    assert first is None
    assert same_cached_app is True
    assert second is None


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
                assert not hasattr(handle, "application")
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
                # Clearing the status drops the chip and brings back the
                # idle dim line carrying the model alias.
                handle.set_toolbar("status", None)
                idle_html = prompt_module._bottom_toolbar()
                idle_header = prompt_module._input_header_fragments()
                assert "some-model" in idle_html.value
                assert idle_header.value == ""
    finally:
        prompt_module._toolbar_context["status"] = previous_status
        prompt_module._toolbar_context["model"] = previous_model
        prompt_module._toolbar_context["suppress"] = previous_suppress


def test_chat_application_refreshes_waiting_status() -> None:
    """The long-lived Application must repaint the live waiting row."""
    chat_app = _fresh_chat_app()

    assert chat_app.application.refresh_interval == 0.1


@pytest.mark.asyncio
async def test_chat_application_submit_iter_round_trips_lines() -> None:
    """`ChatApplication.submit_iter()` yields each submitted line in order."""
    with create_pipe_input() as pipe:
        chat_app = _fresh_chat_app(pipe_input=pipe)
        app_task = asyncio.create_task(chat_app.application.run_async())

        async def collect() -> list[str]:
            collected: list[str] = []
            async for line in chat_app.submit_iter():
                collected.append(line)
                if len(collected) == 2:
                    return collected
            return collected

        collector = asyncio.create_task(collect())
        await asyncio.sleep(0.05)
        pipe.send_text("alpha\n")
        pipe.send_text("beta\n")
        lines = await asyncio.wait_for(collector, timeout=2.0)
        chat_app.application.exit()
        try:
            await asyncio.wait_for(app_task, timeout=1.0)
        except (TimeoutError, asyncio.CancelledError):
            app_task.cancel()

    assert lines == ["alpha", "beta"]


@pytest.mark.asyncio
async def test_interactive_session_large_paste_shows_marker_but_submits_original() -> None:
    """Large bracketed paste payloads collapse in the buffer, not on submit."""
    chat_app = _fresh_chat_app()
    pasted = "x" * 801

    chat_app._insert_pasted_content(chat_app._buffer, pasted)
    assert chat_app._buffer.text == "[Pasted Content #1 801 chars]"

    chat_app._on_accept(chat_app._buffer)
    submitted = await asyncio.wait_for(chat_app.next_line(), timeout=2.0)

    assert submitted == pasted


@pytest.mark.asyncio
async def test_interactive_session_multiple_same_size_pastes_expand_distinctly() -> None:
    chat_app = _fresh_chat_app()
    first = "a" * 801
    second = "b" * 801

    chat_app._insert_pasted_content(chat_app._buffer, first)
    chat_app._buffer.insert_text(" ")
    chat_app._insert_pasted_content(chat_app._buffer, second)
    assert "[Pasted Content #1 801 chars]" in chat_app._buffer.text
    assert "[Pasted Content #2 801 chars]" in chat_app._buffer.text

    chat_app._on_accept(chat_app._buffer)
    submitted = await asyncio.wait_for(chat_app.next_line(), timeout=2.0)

    assert submitted == f"{first} {second}"


@pytest.mark.asyncio
async def test_cached_session_reset_drops_unsubmitted_paste_marker() -> None:
    chat_app = _fresh_chat_app()
    pasted = "x" * 801

    chat_app._insert_pasted_content(chat_app._buffer, pasted)
    assert chat_app._buffer.text == "[Pasted Content #1 801 chars]"

    chat_app.reset_session_state()
    assert chat_app._buffer.text == ""
    assert chat_app._pasted_content == {}

    chat_app._buffer.insert_text("fresh input")
    chat_app._on_accept(chat_app._buffer)
    submitted = await asyncio.wait_for(chat_app.next_line(), timeout=2.0)

    assert submitted == "fresh input"


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
