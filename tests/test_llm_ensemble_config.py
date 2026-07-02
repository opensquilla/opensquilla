from __future__ import annotations

import pytest

from opensquilla.gateway.config import GatewayConfig
from opensquilla.provider.ensemble import build_ensemble_provider_from_config
from opensquilla.provider.selector import ProviderConfig


def test_llm_ensemble_defaults_to_disabled_g8_profile() -> None:
    cfg = GatewayConfig()

    ensemble = cfg.llm_ensemble
    assert ensemble.enabled is False
    assert ensemble.active_profile == "default"
    assert ensemble.mode == "b5_fusion"
    assert ensemble.selection_strategy == "static_profile"
    assert ensemble.proposer_tools is False
    assert ensemble.min_successful_proposers == 1
    assert ensemble.model_options == [
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
        "google/gemini-3-flash-preview",
        "qwen/qwen3.7-plus",
        "deepseek/deepseek-v4-flash",
        "qwen/qwen3.7-max",
        "anthropic/claude-sonnet-4.6",
        "anthropic/claude-opus-4.8",
        "openai/gpt-5.5",
        "openai/gpt-5.4-mini",
        "x-ai/grok-4.3",
        "moonshotai/kimi-k2.6",
        "mistralai/mistral-large-2512",
        "meta-llama/llama-4-maverick",
    ]

    profile = ensemble.profiles["default"]
    assert [member.model for member in profile.proposers] == [
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
        "google/gemini-3-flash-preview",
        "qwen/qwen3.7-plus",
    ]
    assert all(member.provider == "openrouter" for member in profile.proposers)
    assert all(member.thinking == "high" for member in profile.proposers)
    assert profile.aggregator.provider == "openrouter"
    assert profile.aggregator.model == "z-ai/glm-5.2"
    assert profile.aggregator.thinking == "high"
    assert profile.proposer_timeout_seconds == 120.0
    assert profile.aggregator_timeout_seconds == 120.0


def test_llm_ensemble_validates_active_profile_when_enabled() -> None:
    with pytest.raises(ValueError, match="active_profile"):
        GatewayConfig(llm_ensemble={"enabled": True, "active_profile": "missing"})


def test_llm_ensemble_migrates_legacy_g8_profile_name() -> None:
    cfg = GatewayConfig(
        llm_ensemble={
            "enabled": True,
            "active_profile": "g8_four_proposers",
            "profiles": {
                "g8_four_proposers": {
                    "proposers": [{"provider": "openrouter", "model": "legacy/proposer"}],
                    "aggregator": {"provider": "openrouter", "model": "legacy/aggregator"},
                }
            },
        }
    )

    assert cfg.llm_ensemble.active_profile == "default"
    assert cfg.llm_ensemble.profiles["default"].proposers[0].model == "legacy/proposer"
    assert cfg.llm_ensemble.profiles["default"].aggregator.model == "legacy/aggregator"


def test_llm_ensemble_migrates_legacy_g8_profile_without_active_profile() -> None:
    cfg = GatewayConfig(
        llm_ensemble={
            "enabled": True,
            "profiles": {
                "g8_four_proposers": {
                    "proposers": [{"provider": "openrouter", "model": "legacy/proposer"}],
                    "aggregator": {"provider": "openrouter", "model": "legacy/aggregator"},
                }
            },
        }
    )

    assert cfg.llm_ensemble.active_profile == "default"
    assert cfg.llm_ensemble.profiles["default"].proposers[0].model == "legacy/proposer"
    assert cfg.llm_ensemble.profiles["default"].aggregator.model == "legacy/aggregator"


def test_llm_ensemble_validates_enabled_profile_has_proposers() -> None:
    with pytest.raises(ValueError, match="at least one proposer"):
        GatewayConfig(
            llm_ensemble={
                "enabled": True,
                "profiles": {
                    "default": {
                        "proposers": [],
                        "aggregator": {"provider": "openrouter", "model": "z-ai/glm-5.2"},
                    }
                },
            }
        )


def test_llm_ensemble_validates_model_options_not_empty() -> None:
    with pytest.raises(ValueError, match="model_options"):
        GatewayConfig(llm_ensemble={"model_options": []})


def test_llm_ensemble_model_options_are_operator_configurable() -> None:
    cfg = GatewayConfig(
        llm_ensemble={
            "model_options": [" custom/model ", "custom/model", "other/model"],
            "profiles": {
                "default": {
                    "proposers": [{"provider": "openrouter", "model": "custom/model"}],
                    "aggregator": {"provider": "openrouter", "model": "other/model"},
                }
            },
        }
    )

    assert cfg.llm_ensemble.model_options == ["custom/model", "other/model"]
    assert [member.model for member in cfg.llm_ensemble.profiles["default"].proposers] == [
        "custom/model"
    ]


def test_llm_ensemble_validates_enabled_profile_has_aggregator_model() -> None:
    with pytest.raises(ValueError, match="aggregator model"):
        GatewayConfig(
            llm_ensemble={
                "enabled": True,
                "profiles": {
                    "default": {
                        "proposers": [{"provider": "openrouter", "model": "a/model"}],
                        "aggregator": {"provider": "openrouter", "model": ""},
                    }
                },
            }
        )


def test_llm_ensemble_validates_enabled_profile_proposer_models() -> None:
    with pytest.raises(ValueError, match="proposer 1 must define a model"):
        GatewayConfig(
            llm_ensemble={
                "enabled": True,
                "profiles": {
                    "default": {
                        "proposers": [{"provider": "openrouter", "model": ""}],
                        "aggregator": {"provider": "openrouter", "model": "z-ai/glm-5.2"},
                    }
                },
            }
        )


def test_llm_ensemble_validates_profile_shape_even_when_disabled() -> None:
    with pytest.raises(ValueError, match="aggregator model"):
        GatewayConfig(
            llm_ensemble={
                "enabled": False,
                "profiles": {
                    "default": {
                        "proposers": [{"provider": "openrouter", "model": "a/model"}],
                        "aggregator": {"provider": "openrouter", "model": ""},
                    }
                },
            }
        )


def test_llm_ensemble_rejects_whitespace_aggregator_model() -> None:
    with pytest.raises(ValueError, match="aggregator model"):
        GatewayConfig(
            llm_ensemble={
                "enabled": True,
                "profiles": {
                    "default": {
                        "proposers": [{"provider": "openrouter", "model": "a/model"}],
                        "aggregator": {"provider": "openrouter", "model": "   "},
                    }
                },
            }
        )


def test_build_ensemble_provider_inherits_current_openrouter_credentials() -> None:
    cfg = GatewayConfig(llm_ensemble={"enabled": True})
    inherited = ProviderConfig(
        provider="openrouter",
        model="routed/model",
        api_key="runtime-secret",
        base_url="https://openrouter.example/api/v1",
        proxy="http://proxy.local:7890",
        provider_routing={"z-ai/glm-5.2": "z-ai"},
    )

    provider = build_ensemble_provider_from_config(
        config=cfg,
        inherited_provider_config=inherited,
        fallback_provider=None,
    )

    members = [*provider.proposers, provider.aggregator]
    assert [member.provider_config.model for member in provider.proposers] == [
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
        "google/gemini-3-flash-preview",
        "qwen/qwen3.7-plus",
    ]
    assert all(member.provider_config.api_key == "runtime-secret" for member in members)
    assert all(
        member.provider_config.base_url == "https://openrouter.example/api/v1"
        for member in members
    )
    assert all(member.provider_config.proxy == "http://proxy.local:7890" for member in members)
    assert provider.aggregator.provider_config.provider_routing == {"z-ai/glm-5.2": "z-ai"}


def test_router_dynamic_ensemble_uses_small_c0_slot_template() -> None:
    cfg = GatewayConfig(
        llm_ensemble={
            "enabled": True,
            "selection_strategy": "router_dynamic",
            "min_successful_proposers": 4,
        }
    )
    inherited = ProviderConfig(
        provider="openrouter",
        model="deepseek/deepseek-v4-flash",
        api_key="runtime-secret",
        base_url="https://openrouter.example/api/v1",
    )

    provider = build_ensemble_provider_from_config(
        config=cfg,
        inherited_provider_config=inherited,
        fallback_provider=None,
        turn_metadata={"routed_tier": "c0", "routing_confidence": 0.93},
    )

    assert provider.profile_name == "router_dynamic/c0"
    assert [member.label for member in provider.proposers] == ["anchor", "cheap_contrast"]
    assert [member.provider_config.model for member in provider.proposers][0] == (
        "deepseek/deepseek-v4-flash"
    )
    assert len(provider.proposers) == 2
    assert provider.min_successful_proposers == 2
    assert provider.selection_plan["slot_template"] == ["anchor", "cheap_contrast"]
    assert provider.selection_plan["aggregator_slot"] == "aggregator_fast"
    assert provider.selection_plan["duplicate_policy"] == "selected_penalty"


def test_router_dynamic_ensemble_uses_slot_specific_c2_selection() -> None:
    cfg = GatewayConfig(
        llm_ensemble={
            "enabled": True,
            "selection_strategy": "router_dynamic",
            "model_options": [
                "deepseek/deepseek-v4-pro",
                "z-ai/glm-5.2",
                "google/gemini-3-flash-preview",
                "qwen/qwen3.7-plus",
                "anthropic/claude-opus-4.8",
            ],
        }
    )
    inherited = ProviderConfig(
        provider="openrouter",
        model="z-ai/glm-5.2",
        api_key="runtime-secret",
        base_url="https://openrouter.example/api/v1",
    )

    provider = build_ensemble_provider_from_config(
        config=cfg,
        inherited_provider_config=inherited,
        fallback_provider=None,
        turn_metadata={"routed_tier": "c2", "routing_confidence": 0.82},
    )

    assert provider.profile_name == "router_dynamic/c2"
    assert [member.label for member in provider.proposers] == [
        "anchor",
        "adjacent_tier_check",
        "orthogonal_family",
    ]
    assert provider.proposers[0].provider_config.model == "z-ai/glm-5.2"
    assert provider.selection_plan["aggregator_slot"] == "aggregator_strong"
    assert provider.selection_plan["slots"][1]["slot"] == "adjacent_tier_check"
    assert provider.selection_plan["slots"][2]["slot"] == "orthogonal_family"
    assert provider.selection_plan["aggregator"]["slot"] == "aggregator_strong"
    assert provider.selection_plan["candidate_pool_size"] >= 5
