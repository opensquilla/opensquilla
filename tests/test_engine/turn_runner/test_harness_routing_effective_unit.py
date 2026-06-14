"""Unit tests for the harness routing-effectiveness gates.

Observe-mode routes (``routing_applied`` False with a non-explicit source)
must leave tier config, tool-support mode, and the defaulted-context-window
warning untouched; explicit_model pins and legacy metadata without
``routing_applied`` stay effective.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from opensquilla.engine.turn_runner import harness as harness_module
from opensquilla.engine.turn_runner.harness import (
    _routed_tier_cfg,
    _tool_support_mode_for_turn,
    _TurnRunnerModelCatalogAdapter,
)
from opensquilla.provider.model_catalog import ModelCatalog


def _config() -> Any:
    return SimpleNamespace(
        llm=SimpleNamespace(
            max_tokens=0,
            provider="inception",
            base_url="https://api.inceptionlabs.example/v1",
            api_key="",
            proxy="",
            tool_support="on",
        ),
        squilla_router=SimpleNamespace(
            tiers={
                "c1": {
                    "provider": "openai_compatible",
                    "model": "local-router-model",
                    "tool_support": "off",
                }
            }
        ),
    )


def _metadata(**extra: Any) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "routed_tier": "c1",
        "routed_model": "local-router-model",
        "routed_provider": "openai_compatible",
    }
    metadata.update(extra)
    return metadata


# ---------------------------------------------------------------------------
# _routed_tier_cfg
# ---------------------------------------------------------------------------


def test_routed_tier_cfg_observe_mode_returns_empty() -> None:
    tier_cfg = _routed_tier_cfg(
        _config(),
        _metadata(routing_applied=False, routing_source="v4_phase3"),
    )

    assert tier_cfg == {}


def test_routed_tier_cfg_explicit_model_pin_stays_effective() -> None:
    tier_cfg = _routed_tier_cfg(
        _config(),
        _metadata(routing_applied=False, routing_source="explicit_model"),
    )

    assert tier_cfg["tool_support"] == "off"


def test_routed_tier_cfg_missing_applied_key_stays_effective() -> None:
    tier_cfg = _routed_tier_cfg(_config(), _metadata())

    assert tier_cfg["tool_support"] == "off"


# ---------------------------------------------------------------------------
# _tool_support_mode_for_turn
# ---------------------------------------------------------------------------


def test_tool_support_mode_observe_mode_falls_back_to_llm_cfg() -> None:
    config = _config()

    mode = _tool_support_mode_for_turn(
        config,
        config.llm,
        _metadata(routing_applied=False, routing_source="v4_phase3"),
    )

    assert mode == "on"


def test_tool_support_mode_explicit_model_pin_uses_tier_cfg() -> None:
    config = _config()

    mode = _tool_support_mode_for_turn(
        config,
        config.llm,
        _metadata(routing_applied=False, routing_source="explicit_model"),
    )

    assert mode == "off"


def test_tool_support_mode_missing_applied_key_uses_tier_cfg() -> None:
    config = _config()

    mode = _tool_support_mode_for_turn(config, config.llm, _metadata())

    assert mode == "off"


# ---------------------------------------------------------------------------
# _TurnRunnerModelCatalogAdapter.lookup defaulted-context-window warn branch
# ---------------------------------------------------------------------------


def _lookup_with(metadata: dict[str, Any]) -> None:
    runner = SimpleNamespace(_config=_config(), _model_catalog=ModelCatalog())
    adapter = _TurnRunnerModelCatalogAdapter(runner)
    adapter.lookup("local-router-model", turn=SimpleNamespace(metadata=metadata))


def test_lookup_observe_mode_skips_default_context_window_warning(
    monkeypatch,
) -> None:
    monkeypatch.setattr(harness_module, "_DEFAULT_CONTEXT_WARNED", set())

    _lookup_with(_metadata(routing_applied=False, routing_source="v4_phase3"))

    assert harness_module._DEFAULT_CONTEXT_WARNED == set()


def test_lookup_explicit_model_pin_warns_on_default_context_window(
    monkeypatch,
) -> None:
    monkeypatch.setattr(harness_module, "_DEFAULT_CONTEXT_WARNED", set())

    _lookup_with(_metadata(routing_applied=False, routing_source="explicit_model"))

    assert harness_module._DEFAULT_CONTEXT_WARNED == {
        "c1|openai_compatible|local-router-model"
    }


def test_lookup_missing_applied_key_warns_on_default_context_window(
    monkeypatch,
) -> None:
    monkeypatch.setattr(harness_module, "_DEFAULT_CONTEXT_WARNED", set())

    _lookup_with(_metadata())

    assert harness_module._DEFAULT_CONTEXT_WARNED == {
        "c1|openai_compatible|local-router-model"
    }
