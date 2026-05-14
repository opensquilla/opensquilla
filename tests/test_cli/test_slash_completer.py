"""Tests for _SlashCompleter fuzzy gating in prompt.py."""

from __future__ import annotations

from prompt_toolkit.document import Document

from opensquilla.cli.repl.prompt import _SlashCompleter
from opensquilla.engine.commands import Surface


def _completions_for(text: str, surface: Surface = Surface.CLI_GATEWAY) -> list[str]:
    """Return the completion text values for a given buffer text."""
    completer = _SlashCompleter(surface)
    doc = Document(text, cursor_position=len(text))
    return [c.text for c in completer.get_completions(doc, None)]


def test_empty_buffer_no_completions() -> None:
    results = _completions_for("")
    assert results == []


def test_plain_text_no_completions() -> None:
    results = _completions_for("hello world")
    assert results == []


def test_slash_prefix_resume_and_reset_both_match() -> None:
    results = _completions_for("/re")
    # /resume and /reset both start with /re and should be fuzzy-matched
    assert any("resume" in r for r in results), results
    assert any("reset" in r for r in results), results


def test_fuzzy_match_compact_from_cmp() -> None:
    results = _completions_for("/cmp")
    assert any("compact" in r for r in results), results


def test_slash_alone_returns_all_commands() -> None:
    results = _completions_for("/")
    # Should return completions for all gateway commands
    assert len(results) > 5


def test_exact_slash_command_matches() -> None:
    results = _completions_for("/help")
    assert any("help" in r for r in results), results


def test_standalone_surface_excludes_gateway_only_commands() -> None:
    gateway_results = _completions_for("/usage", Surface.CLI_GATEWAY)
    standalone_results = _completions_for("/usage", Surface.CLI_STANDALONE)
    assert any("usage" in r for r in gateway_results), gateway_results
    # /usage is not in standalone, so fuzzy match should not find it
    assert not any(r == "/usage" for r in standalone_results), standalone_results
