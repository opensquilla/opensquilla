from __future__ import annotations

from types import SimpleNamespace

import pytest

from opensquilla.engine.turn_policy import resolve_turn_policy


class _SessionConfigManager:
    def __init__(self, config: object | None) -> None:
        self.config = config

    def get_session_config(self, session_key: str) -> object | None:
        return self.config


def test_turn_policy_preserves_max_iteration_precedence() -> None:
    policy = resolve_turn_policy(
        session_key="agent:main:test",
        session_manager=_SessionConfigManager(
            SimpleNamespace(agent_max_iterations=111)
        ),
        gateway_config=SimpleNamespace(agent_max_iterations=333),
        env={"OPENSQUILLA_AGENT_MAX_ITERATIONS": "222"},
    )

    assert policy.max_iterations == 111
    assert policy.max_iterations_source == "session config"


def test_turn_policy_prefers_explicit_zero() -> None:
    policy = resolve_turn_policy(
        session_key="agent:main:test",
        explicit_max_iterations=0,
        session_manager=_SessionConfigManager(
            SimpleNamespace(agent_max_iterations=111)
        ),
        gateway_config=SimpleNamespace(agent_max_iterations=333),
        env={"OPENSQUILLA_AGENT_MAX_ITERATIONS": "222"},
    )

    assert policy.max_iterations == 0
    assert policy.max_iterations_source == "explicit argument"


def test_turn_policy_env_falls_back_to_gateway_when_invalid() -> None:
    policy = resolve_turn_policy(
        session_key="agent:main:test",
        session_manager=_SessionConfigManager(None),
        gateway_config=SimpleNamespace(agent_max_iterations=333),
        env={"OPENSQUILLA_AGENT_MAX_ITERATIONS": "bad"},
    )

    assert policy.max_iterations == 333
    assert policy.max_iterations_source == "gateway config"


def test_turn_policy_rejects_invalid_explicit_value() -> None:
    with pytest.raises(ValueError, match="max_iterations"):
        resolve_turn_policy(session_key="agent:main:test", explicit_max_iterations=-1)
