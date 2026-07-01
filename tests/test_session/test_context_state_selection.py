from __future__ import annotations

from types import SimpleNamespace

from opensquilla.session.context_state_selection import latest_context_state


def _state(provider: str, created_at: int, state_id: int) -> SimpleNamespace:
    return SimpleNamespace(provider=provider, created_at=created_at, id=state_id)


def test_latest_context_state_without_provider_returns_global_newest() -> None:
    states = [_state("anthropic", 1, 1), _state("openai_responses", 2, 2)]
    latest = latest_context_state(states)
    assert latest is not None
    assert latest.provider == "openai_responses"


def test_latest_context_state_filters_by_provider() -> None:
    # Newest overall is openai_responses; the anthropic filter must still
    # pick the latest anthropic state rather than the globally-newest one.
    states = [_state("anthropic", 1, 1), _state("openai_responses", 2, 2)]
    latest = latest_context_state(states, provider="anthropic")
    assert latest is not None
    assert latest.provider == "anthropic"
    assert latest.id == 1


def test_latest_context_state_returns_none_when_no_provider_match() -> None:
    states = [_state("anthropic", 1, 1)]
    assert latest_context_state(states, provider="gemini") is None
