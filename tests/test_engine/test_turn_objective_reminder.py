"""Tests for the turn-objective reminder override.

OPENSQUILLA_TURN_OBJECTIVE_REMINDER gates the per-turn
"[Current user request reminder]" user message appended after tool results.
Unset/"off" suppresses the message (the default); "on" restores it;
"trim:<chars>" restores it with a replacement truncation cap.
"""

import pytest

from opensquilla.engine.agent import (
    _TURN_OBJECTIVE_REMINDER_MAX_CHARS,
    Agent,
    _resolve_turn_objective_reminder,
)

ENV = "OPENSQUILLA_TURN_OBJECTIVE_REMINDER"


def test_resolver_defaults_off(monkeypatch) -> None:
    monkeypatch.delenv(ENV, raising=False)

    enabled, _ = _resolve_turn_objective_reminder()
    assert enabled is False


def test_resolver_blank_env_keeps_default_off(monkeypatch) -> None:
    monkeypatch.setenv(ENV, "  ")

    enabled, _ = _resolve_turn_objective_reminder()
    assert enabled is False


def test_resolver_on_keeps_shipped_cap(monkeypatch) -> None:
    monkeypatch.setenv(ENV, "on")

    assert _resolve_turn_objective_reminder() == (
        True,
        _TURN_OBJECTIVE_REMINDER_MAX_CHARS,
    )


def test_resolver_off_disables(monkeypatch) -> None:
    monkeypatch.setenv(ENV, "off")

    enabled, _ = _resolve_turn_objective_reminder()
    assert enabled is False


def test_resolver_trim_sets_cap(monkeypatch) -> None:
    monkeypatch.setenv(ENV, "trim:800")

    assert _resolve_turn_objective_reminder() == (True, 800)


@pytest.mark.parametrize("value", ["trim:0", "trim:-5", "trim:abc", "trim:", "enabled"])
def test_resolver_rejects_unrecognized_values(monkeypatch, value) -> None:
    monkeypatch.setenv(ENV, value)

    with pytest.raises(ValueError, match=ENV):
        _resolve_turn_objective_reminder()


def test_message_shape_unchanged_by_default() -> None:
    message = Agent._turn_objective_message("fix the bug in foo.py")

    assert message is not None
    assert message.role == "user"
    assert message.content == (
        "[Current user request reminder]\n"
        "This is the active user request for this same turn, not a new request.\n"
        "Continue using the tool results above to make progress on:\n"
        "fix the bug in foo.py"
    )


def test_message_default_truncation_at_shipped_cap() -> None:
    objective = "x" * (_TURN_OBJECTIVE_REMINDER_MAX_CHARS + 100)

    message = Agent._turn_objective_message(objective)

    assert message is not None
    assert message.content.endswith("x" * 10 + "...")
    last_line = message.content.rsplit("\n", 1)[-1]
    assert len(last_line) == _TURN_OBJECTIVE_REMINDER_MAX_CHARS + len("...")


def test_message_disabled_returns_none() -> None:
    assert Agent._turn_objective_message("fix the bug", enabled=False) is None


def test_message_trim_cap_applies() -> None:
    message = Agent._turn_objective_message("a" * 500, max_chars=100)

    assert message is not None
    last_line = message.content.rsplit("\n", 1)[-1]
    assert last_line == "a" * 100 + "..."


def test_message_empty_objective_returns_none() -> None:
    assert Agent._turn_objective_message(None) is None
    assert Agent._turn_objective_message("   ") is None


def test_agent_init_resolves_env(monkeypatch) -> None:
    monkeypatch.setenv(ENV, "trim:1234")

    agent = Agent(provider=object())

    assert agent._turn_objective_reminder_enabled is True
    assert agent._turn_objective_reminder_max_chars == 1234


def test_agent_init_default_disables_reminder(monkeypatch) -> None:
    monkeypatch.delenv(ENV, raising=False)

    agent = Agent(provider=object())

    assert agent._turn_objective_reminder_enabled is False


def test_agent_init_on_restores_shipped_behavior(monkeypatch) -> None:
    monkeypatch.setenv(ENV, "on")

    agent = Agent(provider=object())

    assert agent._turn_objective_reminder_enabled is True
    assert agent._turn_objective_reminder_max_chars == _TURN_OBJECTIVE_REMINDER_MAX_CHARS


def test_agent_init_rejects_bad_env(monkeypatch) -> None:
    monkeypatch.setenv(ENV, "sometimes")

    with pytest.raises(ValueError, match=ENV):
        Agent(provider=object())
