"""Thinking-level precedence: CLI --thinking > [llm].thinking > router tiers.

Pins the resolution order that decides the delivered thinking budget in
scripted runs. A calling runner's hardcoded CLI ``--thinking`` flag
model_copies over the TOML ``[llm].thinking`` value, while config.toml router
tiers are dead config when the router is disabled. A config.toml-only edit to
the thinking level is therefore silently ignored while a runner flag persists;
these tests document each link of that chain.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from opensquilla.cli.agent_cmd import _with_agent_thinking_config
from opensquilla.engine import AgentConfig, ThinkingLevel
from opensquilla.engine.runtime import TurnRunner
from opensquilla.gateway.config import GatewayConfig


def _resolve_turn_thinking(
    explicit_thinking: Any,
    *,
    turn_metadata: dict[str, Any] | None = None,
) -> bool | ThinkingLevel:
    stub = SimpleNamespace(
        _config=SimpleNamespace(llm=SimpleNamespace(thinking=explicit_thinking)),
        _parse_thinking_level=TurnRunner._parse_thinking_level,
    )
    turn = SimpleNamespace(metadata=turn_metadata or {})
    return TurnRunner._resolve_turn_thinking(stub, turn)  # type: ignore[arg-type]


def test_explicit_llm_thinking_beats_router_tier_metadata() -> None:
    resolved = _resolve_turn_thinking(
        "high",
        turn_metadata={"thinking_requested": True, "thinking_level": "xhigh"},
    )

    assert resolved is ThinkingLevel.HIGH


def test_router_tier_metadata_applies_only_when_config_thinking_absent() -> None:
    resolved = _resolve_turn_thinking(
        None,
        turn_metadata={"thinking_requested": True, "thinking_level": "xhigh"},
    )

    assert resolved is ThinkingLevel.XHIGH


def test_invalid_explicit_thinking_forces_thinking_off() -> None:
    resolved = _resolve_turn_thinking(
        "garbage-level",
        turn_metadata={"thinking_requested": True, "thinking_level": "xhigh"},
    )

    assert resolved is False


def test_thinking_defaults_off_without_config_or_router_metadata() -> None:
    assert _resolve_turn_thinking(None) is False


def test_cli_thinking_flag_overrides_toml_llm_thinking(
    monkeypatch: Any,
) -> None:
    """The runner-delivered CLI flag replaces the TOML value after load.

    This is the runner delivery path: config.toml said nothing, the runner said
    ``--thinking xhigh``. It also means a config.toml-only edit to
    ``[llm].thinking`` is silently ignored while the runner flag persists.
    """
    monkeypatch.delenv("OPENSQUILLA_LLM_THINKING", raising=False)
    cfg = GatewayConfig(llm={"thinking": "high"})

    updated = _with_agent_thinking_config(cfg, "xhigh")

    assert updated.llm.thinking == "xhigh"


def test_resolve_thinking_budgets_for_high_and_xhigh() -> None:
    assert AgentConfig(thinking=ThinkingLevel.HIGH).resolve_thinking(None) == (
        True,
        20_000,
    )
    assert AgentConfig(thinking=ThinkingLevel.XHIGH).resolve_thinking(None) == (
        True,
        50_000,
    )
