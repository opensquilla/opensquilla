"""Completer and auto-suggest survive the prompt.py refactor.

The legacy `PromptSession` driver wired a fuzzy slash-command completer and
`AutoSuggestFromHistory` into its session; the long-lived application moves those onto
`Buffer.completer` / `Buffer.auto_suggest` on the long-lived
`ChatApplication`. These tests pin both wirings.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import (
    CompleteEvent,
    Completer,
    FuzzyCompleter,
    WordCompleter,
)
from prompt_toolkit.document import Document
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.input.base import DummyInput
from prompt_toolkit.layout import FloatContainer
from prompt_toolkit.layout.menus import CompletionsMenuControl
from prompt_toolkit.output.base import DummyOutput

from opensquilla.cli.repl import prompt as prompt_mod
from opensquilla.cli.repl.app import ChatApplication
from opensquilla.engine.commands import Surface


def _make_chat_app(
    *,
    completer: Completer | None = None,
    auto_suggest=None,
    history=None,
) -> ChatApplication:
    return ChatApplication(
        surface=Surface.CLI_GATEWAY,
        toolbar_context={"model": None, "session_id": None, "suppress": None},
        bottom_toolbar=lambda: "",
        style=None,
        input=DummyInput(),
        output=DummyOutput(),
        completer=completer,
        auto_suggest=auto_suggest,
        history=history,
    )


def test_chat_application_buffer_accepts_completer_kwarg() -> None:
    completer = WordCompleter(["/help", "/clear"], ignore_case=True)
    app = _make_chat_app(completer=completer)
    # The Buffer instance carries the completer the caller passed.
    assert app._buffer.completer is completer


def test_chat_application_layout_renders_completion_menu() -> None:
    app = _make_chat_app(completer=WordCompleter(["/help"], ignore_case=True))

    root = app.application.layout.container
    assert isinstance(root, FloatContainer)
    [completion_float] = root.floats
    assert completion_float.left == 7
    assert completion_float.xcursor is False
    assert completion_float.ycursor is True
    assert any(
        isinstance(
            getattr(getattr(float_.content, "content", None), "content", None),
            CompletionsMenuControl,
        )
        for float_ in root.floats
    )


def test_chat_application_buffer_accepts_auto_suggest_and_history() -> None:
    history = InMemoryHistory()
    auto_suggest = AutoSuggestFromHistory()
    app = _make_chat_app(history=history, auto_suggest=auto_suggest)
    assert app._buffer.history is history
    assert app._buffer.auto_suggest is auto_suggest


def test_tab_completes_slash_help() -> None:
    """Fuzzy slash-completer expands `/he` to `/help`."""
    inner = WordCompleter(["/help", "/clear", "/new", "/exit"], ignore_case=True, WORD=True)
    fuzzy = FuzzyCompleter(inner)
    app = _make_chat_app(completer=fuzzy)

    buffer = app._buffer
    buffer.text = "/he"
    buffer.cursor_position = len(buffer.text)

    completions = list(
        fuzzy.get_completions(
            Document(buffer.text, cursor_position=buffer.cursor_position),
            CompleteEvent(),
        )
    )
    texts = {c.text for c in completions}
    assert "/help" in texts, f"expected /help in completions, got {texts}"


def test_auto_suggest_from_history_returns_prior_line() -> None:
    """AutoSuggestFromHistory yields the prior matching prefix from history."""
    history = InMemoryHistory()
    history.append_string("/hello world")

    auto_suggest = AutoSuggestFromHistory()
    app = _make_chat_app(history=history, auto_suggest=auto_suggest)

    suggestion = asyncio.run(
        auto_suggest.get_suggestion_async(app._buffer, Document("/he"))
    )
    assert suggestion is not None
    assert suggestion.text == "llo world"


def test_interactive_session_wires_completer_and_auto_suggest() -> None:
    """The interactive_session()-built ChatApplication has the slash completer
    + AutoSuggestFromHistory + FileHistory wired through `_get_or_create_chat_app`.
    """
    # Reset the per-surface cache so this test sees a fresh build.
    prompt_mod._chat_applications.clear()
    chat_app = prompt_mod._get_or_create_chat_app(
        Surface.CLI_GATEWAY,
        output=DummyOutput(),
    )

    # Completer is the FuzzyCompleter-wrapping _SlashCompleter from prompt.py.
    assert chat_app._buffer.completer is not None
    assert isinstance(chat_app._buffer.completer, prompt_mod._SlashCompleter)

    # AutoSuggest is the from-history flavor.
    assert isinstance(chat_app._buffer.auto_suggest, AutoSuggestFromHistory)

    # History is a FileHistory pointing at the state dir history file.
    from prompt_toolkit.history import FileHistory

    assert isinstance(chat_app._buffer.history, FileHistory)
    history_filename = Path(chat_app._buffer.history.filename)
    assert history_filename.name == "chat"  # state_dir("history", "chat") in _history_path
