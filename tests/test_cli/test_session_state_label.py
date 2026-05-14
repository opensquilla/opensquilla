"""Tests for _model_alias and PromptState.label in session_state."""

from __future__ import annotations

import pytest

from opensquilla.cli.repl.session_state import PromptState, _model_alias


def test_alias_none_returns_ellipsis() -> None:
    assert _model_alias(None) == "…"


def test_alias_empty_string_returns_ellipsis() -> None:
    assert _model_alias("") == "…"


def test_alias_with_slash_returns_last_segment() -> None:
    # "deepseek-v4-flash-20260423" is 26 chars — under 28, no ellipsis
    result = _model_alias("deepseek/deepseek-v4-flash-20260423")
    assert result == "deepseek-v4-flash-20260423"
    assert len(result) == 26


def test_alias_long_segment_is_middle_ellipsized() -> None:
    # Build a 40-char tail segment
    tail = "a" * 20 + "b" * 20  # 40 chars — over 28
    full = f"provider/{tail}"
    result = _model_alias(full)
    assert result == tail[:12] + "…" + tail[-12:]
    assert len(result) == 25  # 12 + 1 + 12


def test_alias_exactly_28_chars_no_ellipsis() -> None:
    seg = "x" * 28
    result = _model_alias(f"provider/{seg}")
    assert result == seg
    assert "…" not in result


def test_alias_29_chars_is_ellipsized() -> None:
    seg = "x" * 29
    result = _model_alias(f"provider/{seg}")
    assert "…" in result
    assert len(result) == 25  # 12 + 1 + 12


def test_alias_no_slash_returns_whole_string() -> None:
    assert _model_alias("gpt-5.1") == "gpt-5.1"


def test_alias_no_slash_long_string_is_ellipsized() -> None:
    # 40-char string with no slash — treated as the whole segment
    seg = "z" * 40
    result = _model_alias(seg)
    assert result == seg[:12] + "…" + seg[-12:]


def test_prompt_state_label_uses_alias() -> None:
    state = PromptState(model="openai/gpt-5.1", elevated=None)
    assert state.label == "[gpt-5.1 normal] you > "


def test_prompt_state_label_none_model() -> None:
    state = PromptState(model=None, elevated=None)
    assert state.label == "[… normal] you > "


def test_prompt_state_label_elevated_mode() -> None:
    state = PromptState(model="anthropic/claude-opus-4", elevated="bypass")
    assert state.label == "[claude-opus-4 bypass] you > "
