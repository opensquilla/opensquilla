"""Inline approval via suspend → fresh PromptSession → resume.

The legacy `prompt_approval` re-entered the long-lived cached `PromptSession`
via `prompt_user(chrome=False)`, which can deadlock or corrupt the in-flight
input buffer when the outer Application is concurrent.
The inline path replaces that behavior with `prompt_approval_inline`: suspend the outer
`ChatApplication`, construct a fresh one-shot `PromptSession`, then resume.

These tests pin:
  - the cached `PromptSession.prompt_async` is NOT re-entered;
  - decision letters (o/a/b/d) round-trip through the inline session;
  - Ctrl-C / EOF inside the approval prompt translates to "d" (deny);
  - the typed buffer on the outer Application survives the suspend window;
  - the `_approval_in_flight` Event toggles as expected;
  - the assistant status header renders "thinking…" only when set;
  - `Live(` has been excised from `stream.py` so stream rendering does not
    own the prompt surface during approval.
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from unittest.mock import patch

import pytest
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.input.base import DummyInput
from prompt_toolkit.output import DummyOutput

from opensquilla.cli.repl import prompt as prompt_mod
from opensquilla.cli.repl.app import ChatApplication
from opensquilla.cli.repl.prompt import (
    _chat_applications,
    _toolbar_context,
    prompt_approval,
    prompt_approval_inline,
)
from opensquilla.engine.commands import Surface

# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _fresh_chat_app(*, pipe_input=None) -> ChatApplication:
    """Build a ChatApplication wired to DummyInput/DummyOutput.

    Tests never want the cached global app — they need a fresh instance per
    case so suspend/resume side effects can be observed in isolation.
    """
    return ChatApplication(
        surface=Surface.CLI_GATEWAY,
        toolbar_context={
            "model": None,
            "session_id": None,
            "suppress": None,
            "status": None,
        },
        bottom_toolbar=lambda: "",
        style=None,
        input=pipe_input if pipe_input is not None else DummyInput(),
        output=DummyOutput(),
    )


@pytest.fixture
def restore_chat_apps():
    """Snapshot / restore the global `_chat_applications` map per test."""
    saved = dict(_chat_applications)
    _chat_applications.clear()
    try:
        yield _chat_applications
    finally:
        _chat_applications.clear()
        _chat_applications.update(saved)


@pytest.fixture
def restore_toolbar_status():
    """Snapshot / restore `_toolbar_context['status']` per test."""
    previous = _toolbar_context.get("status")
    try:
        yield
    finally:
        _toolbar_context["status"] = previous


# --------------------------------------------------------------------------- #
# Tests                                                                       #
# --------------------------------------------------------------------------- #


def test_approval_does_not_reenter_cached_prompt_async(restore_chat_apps) -> None:
    """`prompt_approval_inline` MUST NOT call `prompt_user` (cached path).

    Two-pronged check:
      1. Source inspection — the function body does not reference
         `prompt_user(` or `_prompt_session(` (the legacy cached re-entry
         points).
      2. Behavioral — patch `prompt_user` and `_prompt_session`; assert
         neither is invoked when the fresh-session fallback path runs.
    """
    src = inspect.getsource(prompt_approval_inline)
    assert "prompt_user(" not in src, (
        "prompt_approval_inline must not re-enter prompt_user "
        "(legacy cached PromptSession path)"
    )
    assert "_prompt_session(" not in src, (
        "prompt_approval_inline must not re-enter the cached "
        "_prompt_session helper"
    )

    # Behavioral: fallback path (no ChatApplication registered) — patch
    # `prompt_user` and `_prompt_session`, drive the fresh PromptSession via
    # a pipe input, and assert the cached helpers are never called.
    async def _drive() -> str:
        with create_pipe_input() as pipe:
            with patch.object(
                prompt_mod, "PromptSession", autospec=False
            ) as ps_cls:
                instance = ps_cls.return_value

                async def _fake_prompt_async() -> str:
                    return "o"

                instance.prompt_async = _fake_prompt_async
                with patch.object(
                    prompt_mod, "prompt_user"
                ) as mock_prompt_user, patch.object(
                    prompt_mod, "_prompt_session"
                ) as mock_prompt_session:
                    result = await prompt_approval_inline(
                        surface=Surface.CLI_GATEWAY,
                        approval_panel="Decide: ",
                    )
                    assert not mock_prompt_user.called
                    assert not mock_prompt_session.called
                    # Suppress unused-pipe warning from prompt-toolkit.
                    _ = pipe
        return result

    assert asyncio.run(_drive()) == "o"


@pytest.mark.parametrize("letter", ["o", "a", "b", "d"])
def test_approval_decision_propagates(letter: str, restore_chat_apps) -> None:
    """Each of o/a/b/d round-trips through the inline session as lowercase."""

    async def _drive() -> str:
        with patch.object(prompt_mod, "PromptSession", autospec=False) as ps_cls:
            instance = ps_cls.return_value

            async def _fake_prompt_async() -> str:
                return letter

            instance.prompt_async = _fake_prompt_async
            return await prompt_approval_inline(
                surface=Surface.CLI_GATEWAY,
                approval_panel="Decision: ",
            )

    assert asyncio.run(_drive()) == letter


def test_approval_ctrl_c_denies(restore_chat_apps) -> None:
    """`KeyboardInterrupt` / `EOFError` inside the approval session → 'd'."""

    async def _drive(exc: type[BaseException]) -> str:
        with patch.object(prompt_mod, "PromptSession", autospec=False) as ps_cls:
            instance = ps_cls.return_value

            async def _raise() -> str:
                raise exc

            instance.prompt_async = _raise
            return await prompt_approval_inline(
                surface=Surface.CLI_GATEWAY,
                approval_panel="Decision: ",
            )

    assert asyncio.run(_drive(KeyboardInterrupt)) == "d"
    assert asyncio.run(_drive(EOFError)) == "d"


def test_approval_long_panel_scrolls(restore_chat_apps) -> None:
    """A 100+ line panel is accepted as-is; no exception, returned value is the typed answer.

    The fresh `PromptSession` handles overflow natively; this is a smoke
    check that we propagate a tall panel string through unchanged.
    """
    tall_panel = "\n".join(f"line-{i:03d}" for i in range(120))

    async def _drive() -> str:
        with patch.object(prompt_mod, "PromptSession", autospec=False) as ps_cls:
            instance = ps_cls.return_value

            async def _fake_prompt_async() -> str:
                return "a"

            instance.prompt_async = _fake_prompt_async
            answer = await prompt_approval_inline(
                surface=Surface.CLI_GATEWAY,
                approval_panel=tall_panel,
            )
            # Sanity: we passed the tall panel into the inline session.
            ps_cls.assert_called_once()
            _, kwargs = ps_cls.call_args
            assert kwargs.get("message") == tall_panel
            return answer

    assert asyncio.run(_drive()) == "a"


def test_typed_chars_preserved_across_approval(restore_chat_apps) -> None:
    """Outer buffer text survives the approval cycle.

    The inline approval contract is that the outer `ChatApplication`'s buffer is
    untouched across `set_approval_in_flight(True)` → inline-session →
    `set_approval_in_flight(False)`. The full suspend_to_background path is
    integration-tested elsewhere; here we lock the buffer-state invariant
    that the cycle does not mutate `_buffer.text` on its own.
    """
    chat_app = _fresh_chat_app()
    _chat_applications[Surface.CLI_GATEWAY] = chat_app

    # Pre-fill the outer buffer as if the user had typed mid-turn.
    chat_app._buffer.text = "hello wor"
    chat_app._buffer.cursor_position = len("hello wor")

    chat_app.set_approval_in_flight(True)
    # Simulate the inline approval session by running a noop coroutine — we
    # only need to assert the buffer text was not stomped by the toggling
    # itself. The real suspend/resume is owned by prompt-toolkit and was
    # validated by the prompt-toolkit terminal handoff checks.
    chat_app.set_approval_in_flight(False)

    assert chat_app._buffer.text == "hello wor"
    assert chat_app._buffer.cursor_position == len("hello wor")


def test_approval_in_flight_event_toggles(restore_chat_apps) -> None:
    """`set_approval_in_flight` set/clears the underlying `asyncio.Event`."""
    chat_app = _fresh_chat_app()
    assert chat_app.approval_in_flight.is_set() is False

    chat_app.set_approval_in_flight(True)
    assert chat_app.approval_in_flight.is_set() is True

    chat_app.set_approval_in_flight(False)
    assert chat_app.approval_in_flight.is_set() is False


def test_turn_completes_during_approval_does_not_print_until_resume(
    restore_chat_apps,
    monkeypatch,
) -> None:
    """Suspend-window gap: turn-task writes block until approval clears.

    The output-lock acquirer awaits `wait_approval_idle()` inside the
    lock; while `_approval_in_flight` is set the awaiting task cannot run
    its write, so no bytes hit the terminal until the inline approval
    `PromptSession` releases and the outer Application resumes.
    """
    import io

    from opensquilla.cli import ui as cli_ui

    async def _drive() -> None:
        chat_app = _fresh_chat_app()
        buffer = io.StringIO()
        # Monkeypatch the shared `console.file` so writes land in our buffer.
        monkeypatch.setattr(cli_ui.console, "file", buffer, raising=True)

        chat_app.set_approval_in_flight(True)
        task = asyncio.create_task(chat_app.write_through("CHUNK\n"))
        # Yield a few times so the task definitely enters write_through and
        # awaits the suspend gate.
        for _ in range(10):
            await asyncio.sleep(0)

        # While approval is in flight, the write must NOT have landed.
        assert "CHUNK" not in buffer.getvalue(), (
            f"write_through wrote during approval window: {buffer.getvalue()!r}"
        )

        chat_app.set_approval_in_flight(False)
        await asyncio.wait_for(task, timeout=1.0)
        assert "CHUNK\n" in buffer.getvalue()

    asyncio.run(_drive())


def test_header_status_thinking_then_clear(restore_toolbar_status) -> None:
    """The assistant header renders status iff ``_toolbar_context['status']`` is set."""
    _toolbar_context["status"] = "thinking…"
    header = prompt_mod._input_header_fragments()
    toolbar = prompt_mod._bottom_toolbar()
    assert "thinking…" in header.value
    assert "thinking…" not in toolbar.value

    _toolbar_context["status"] = None
    header = prompt_mod._input_header_fragments()
    assert "thinking…" not in header.value


def test_stream_py_has_no_live_constructor() -> None:
    """Lock the inline approval invariant: no `Live(` in cli/repl/stream.py.

    The approval path relies on the pre-token surface being the
    prompt-toolkit assistant header slot, not a Rich `Live` region. Run
    Keep this check in Python so it works on Windows hosts that do not ship
    GNU grep.
    """
    repo_root = Path(__file__).resolve().parents[4]
    target = repo_root / "src" / "opensquilla" / "cli" / "repl" / "stream.py"
    assert target.exists(), f"missing target: {target}"
    matches = [
        f"{index}: {line}"
        for index, line in enumerate(target.read_text(encoding="utf-8").splitlines(), start=1)
        if "Live(" in line
    ]
    assert not matches, "`Live(` re-appeared in stream.py:\n" + "\n".join(matches)


def test_prompt_approval_inline_uses_in_terminal_not_suspend_to_background() -> None:
    """Regression guard: the approval flow MUST use
    ``prompt_toolkit.application.run_in_terminal.in_terminal`` to scope the
    outer-Application suspension to the body of the approval prompt.

    ``Application.suspend_to_background`` sends SIGTSTP to the entire
    process group (the shell-Ctrl-Z equivalent) and is therefore the wrong
    primitive for "temporarily release the terminal for an inline prompt".
    ``in_terminal`` is the documented async context manager that yields
    control back when the body completes.
    """
    source = inspect.getsource(prompt_approval_inline)
    assert "async with in_terminal()" in source, (
        "prompt_approval_inline must use `async with in_terminal():` to "
        "scope the outer-Application suspension to the approval body."
    )
    assert ".suspend_to_background(" not in source, (
        "prompt_approval_inline must NOT call `.suspend_to_background(...)`; "
        "that primitive sends SIGTSTP to the process group instead of "
        "scoping the suspension to the approval prompt body."
    )


# --------------------------------------------------------------------------- #
# Surface plumbing through `prompt_approval`                                  #
# --------------------------------------------------------------------------- #


def test_standalone_approval_toggles_standalone_application(restore_chat_apps) -> None:
    """`prompt_approval(surface=Surface.CLI_STANDALONE)` MUST hit the
    standalone ChatApplication's ``_approval_in_flight`` Event.

    Pre-fix, ``prompt_approval`` hardcoded ``Surface.CLI_GATEWAY`` so the
    standalone REPL fell back to the bare ``PromptSession`` path without
    ever flipping the suspend gate on its own Application. Stream chunks
    from the active turn would then race the inline approval prompt.
    """
    standalone_app = _fresh_chat_app()
    # Register ONLY the standalone surface; gateway lookup must miss.
    _chat_applications[Surface.CLI_STANDALONE] = standalone_app
    assert Surface.CLI_GATEWAY not in _chat_applications

    seen_in_flight: list[bool] = []

    async def _drive() -> str:
        with patch.object(prompt_mod, "PromptSession", autospec=False) as ps_cls:
            instance = ps_cls.return_value

            async def _fake_prompt_async() -> str:
                # Capture the standalone Application's gate state from
                # inside the suspend window; it MUST be set.
                seen_in_flight.append(standalone_app.approval_in_flight.is_set())
                return "o"

            instance.prompt_async = _fake_prompt_async
            return await prompt_approval(
                "Decision: ", surface=Surface.CLI_STANDALONE
            )

    answer = asyncio.run(_drive())
    assert answer == "o"
    assert seen_in_flight == [True], (
        "standalone ChatApplication._approval_in_flight must be set "
        "for the inline approval body when surface=CLI_STANDALONE"
    )
    # After resume the gate must clear so subsequent stream writes can
    # land.
    assert standalone_app.approval_in_flight.is_set() is False


def test_gateway_approval_default_unchanged(restore_chat_apps) -> None:
    """Default ``prompt_approval(...)`` still routes through the gateway
    surface so legacy non-REPL callers keep working unchanged.

    A standalone Application is registered but the call omits ``surface``;
    the gateway lookup must miss and the fallback fresh-session path runs
    (the standalone Application's gate stays clear because its surface
    was not requested).
    """
    standalone_app = _fresh_chat_app()
    _chat_applications[Surface.CLI_STANDALONE] = standalone_app

    async def _drive() -> str:
        with patch.object(prompt_mod, "PromptSession", autospec=False) as ps_cls:
            instance = ps_cls.return_value

            async def _fake_prompt_async() -> str:
                return "a"

            instance.prompt_async = _fake_prompt_async
            return await prompt_approval("Decision: ")

    assert asyncio.run(_drive()) == "a"
    # Standalone gate must NOT have been toggled because gateway was the
    # default surface and gateway has no Application registered.
    assert standalone_app.approval_in_flight.is_set() is False


def test_prompt_approval_signature_accepts_surface_keyword() -> None:
    """Lock the new contract: ``prompt_approval`` takes a keyword-only
    ``surface`` argument with a gateway default.

    Inspect the source so a future regression that drops the kwarg cannot
    silently revert the wiring.
    """
    source = inspect.getsource(prompt_approval)
    assert "surface: Surface = Surface.CLI_GATEWAY" in source, (
        "prompt_approval must declare `surface: Surface = "
        "Surface.CLI_GATEWAY` so non-REPL callers keep the legacy "
        "default while the concurrent loop can pass CLI_STANDALONE."
    )
