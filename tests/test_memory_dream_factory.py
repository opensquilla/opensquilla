from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from opensquilla.gateway.config import GatewayConfig
from opensquilla.memory.dream_factory import build_dream_factory, build_dream_provider_selector


def test_dream_factory_does_not_accept_shared_turn_provider_or_tools() -> None:
    params = inspect.signature(build_dream_factory).parameters

    assert "provider_selector" not in params
    assert "tool_registry" not in params


def _primary_config(selector):
    return selector._config.primary  # type: ignore[attr-defined]  # test-only inspection


def test_dream_provider_follows_llm_model_when_router_disabled() -> None:
    config = GatewayConfig(
        llm={
            "provider": "openrouter",
            "model": "user/custom-model",
            "api_key": "test-key",
        },
        squilla_router={"enabled": False},
    )

    selector = build_dream_provider_selector(config)

    primary = _primary_config(selector)
    assert primary.provider == "openrouter"
    assert primary.model == "user/custom-model"


def test_dream_provider_uses_legacy_router_default_alias_when_router_active() -> None:
    config = GatewayConfig(
        llm={
            "provider": "openrouter",
            "model": "user/custom-model",
            "api_key": "test-key",
        },
        squilla_router={
            "enabled": True,
            "rollout_phase": "full",
            "tiers": {
                "t1": {
                    "provider": "openrouter",
                    "model": "router/t1-model",
                }
            },
        },
    )

    selector = build_dream_provider_selector(config)

    primary = _primary_config(selector)
    assert primary.provider == "openrouter"
    assert primary.model == "router/t1-model"
    assert config.squilla_router.default_tier == "c1"
    assert "c1" in config.squilla_router.tiers


def test_dream_rejects_dream_specific_model_override() -> None:
    with pytest.raises(ValidationError):
        GatewayConfig(memory={"dream": {"model_override": "dream/custom-model"}})
