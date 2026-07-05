from __future__ import annotations

import pytest

from opensquilla.gateway.config import GatewayConfig
from opensquilla.provider.ensemble import build_ensemble_provider_from_config
from opensquilla.provider.selector import ProviderConfig


def test_llm_ensemble_defaults_to_disabled_for_model_router_first_install() -> None:
    cfg = GatewayConfig()

    ensemble = cfg.llm_ensemble
    assert cfg.squilla_router.enabled is True
    assert ensemble.enabled is False
    assert ensemble.mode == "b5_fusion"
    assert ensemble.selection_mode == "static_openrouter_b5"
    assert ensemble.proposer_tools is False
    assert ensemble.min_successful_proposers == 1
    assert ensemble.model_options == []
    assert ensemble.candidates == []
    assert ensemble.candidate_max_chars == 24_000
    assert ensemble.proposer_timeout_seconds == 3600.0
    assert ensemble.aggregator_timeout_seconds == 3600.0
    assert ensemble.shuffle_candidates is True
    assert ensemble.record_candidates is False

    enabled_cfg = cfg.model_copy(deep=True)
    enabled_cfg.llm_ensemble.enabled = True
    provider = build_ensemble_provider_from_config(
        config=enabled_cfg,
        inherited_provider_config=ProviderConfig(
            provider="openrouter",
            model="routed/model",
            api_key="fake",
            base_url="https://openrouter.example/api/v1",
        ),
        fallback_provider=None,
        turn_metadata={"routed_tier": "c0"},
    )
    assert provider.profile_name == "static_openrouter_b5"
    assert [member.provider_config.model for member in provider.proposers] == [
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
        "moonshotai/kimi-k2.7-code",
        "qwen/qwen3.7-max",
    ]
    assert provider.aggregator.provider_config.model == "z-ai/glm-5.2"
    assert provider.min_successful_proposers == 3
    assert provider.proposer_timeout_seconds == 300.0
    assert provider.aggregator_timeout_seconds == 480.0
    assert provider.shuffle_candidates is False
    assert provider.quorum_grace_seconds == 30.0


def test_static_openrouter_b5_does_not_need_model_options() -> None:
    cfg = GatewayConfig(
        llm_ensemble={
            "enabled": True,
            "selection_mode": "static_openrouter_b5",
            "model_options": [],
        }
    )

    provider = build_ensemble_provider_from_config(
        config=cfg,
        inherited_provider_config=ProviderConfig(
            provider="openrouter",
            model="routed/model",
            api_key="fake",
            base_url="https://openrouter.example/api/v1",
        ),
        fallback_provider=None,
    )

    assert provider.profile_name == "static_openrouter_b5"
    assert [member.provider_config.model for member in provider.proposers] == [
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
        "moonshotai/kimi-k2.7-code",
        "qwen/qwen3.7-max",
    ]
    assert provider.aggregator.provider_config.model == "z-ai/glm-5.2"


def test_router_dynamic_ensemble_allows_empty_custom_model_options() -> None:
    cfg = GatewayConfig(
        llm_ensemble={
            "selection_mode": "router_dynamic",
            "model_options": [],
        }
    )

    assert cfg.llm_ensemble.model_options == []


def test_router_dynamic_ignores_legacy_default_openrouter_model_options() -> None:
    cfg = GatewayConfig(
        llm={
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "api_key": "fake",
            "base_url": "https://api.deepseek.com",
        },
        llm_ensemble={
            "enabled": True,
            "selection_mode": "router_dynamic",
            "model_options": [
                "deepseek/deepseek-v4-pro",
                "z-ai/glm-5.2",
                "qwen/qwen3.7-plus",
                "deepseek/deepseek-v4-flash",
                "qwen/qwen3.7-max",
                "moonshotai/kimi-k2.6",
                "moonshotai/kimi-k2.7-code",
                "minimax/minimax-m3",
            ],
        },
        squilla_router={
            "enabled": True,
            "tiers": {
                "c0": {"provider": "deepseek", "model": "deepseek-v4-flash"},
                "c1": {"provider": "deepseek", "model": "deepseek-v4-flash"},
                "c2": {"provider": "deepseek", "model": "deepseek-v4-pro"},
                "c3": {"provider": "deepseek", "model": "deepseek-v4-pro"},
            },
        },
    )
    inherited = ProviderConfig(
        provider="deepseek",
        model="deepseek-v4-flash",
        api_key="fake",
        base_url="https://api.deepseek.com",
    )

    provider = build_ensemble_provider_from_config(
        config=cfg,
        inherited_provider_config=inherited,
        fallback_provider=None,
        turn_metadata={"routed_tier": "c1"},
    )

    pool = provider.selection_plan["candidate_pool"]
    assert all(candidate["source"] != "legacy_model_options" for candidate in pool)
    assert all(candidate["provider"] != "openrouter" for candidate in pool)


def test_llm_ensemble_validates_selection_mode() -> None:
    with pytest.raises(ValueError, match="selection_mode"):
        GatewayConfig(llm_ensemble={"selection_mode": "static_unknown"})


def test_llm_ensemble_model_options_are_operator_configurable() -> None:
    cfg = GatewayConfig(
        llm_ensemble={
            "model_options": [" custom/model ", "custom/model", "other/model"],
        }
    )

    assert cfg.llm_ensemble.model_options == ["custom/model", "other/model"]


def test_router_dynamic_keeps_non_default_legacy_model_options_with_source() -> None:
    cfg = GatewayConfig(
        llm_ensemble={
            "enabled": True,
            "selection_mode": "router_dynamic",
            "model_options": ["vendor/custom-model"],
        }
    )
    inherited = ProviderConfig(
        provider="deepseek",
        model="deepseek-v4-flash",
        api_key="fake",
        base_url="https://api.deepseek.com",
    )

    provider = build_ensemble_provider_from_config(
        config=cfg,
        inherited_provider_config=inherited,
        fallback_provider=None,
        turn_metadata={"routed_tier": "c1"},
    )

    pool = provider.selection_plan["candidate_pool"]
    legacy = next(candidate for candidate in pool if candidate["model"] == "vendor/custom-model")
    assert legacy["provider"] == "openrouter"
    assert legacy["source"] == "legacy_model_options"


def test_router_dynamic_uses_structured_candidates_with_source() -> None:
    cfg = GatewayConfig(
        llm_ensemble={
            "enabled": True,
            "selection_mode": "router_dynamic",
            "candidates": [
                {
                    "provider": "openrouter",
                    "model": "qwen/qwen3.7-max",
                    "source": "custom",
                    "enabled": True,
                },
                {
                    "provider": "openrouter",
                    "model": "disabled/model",
                    "source": "custom",
                    "enabled": False,
                },
            ],
        }
    )
    inherited = ProviderConfig(
        provider="deepseek",
        model="deepseek-v4-flash",
        api_key="fake",
        base_url="https://api.deepseek.com",
    )

    provider = build_ensemble_provider_from_config(
        config=cfg,
        inherited_provider_config=inherited,
        fallback_provider=None,
        turn_metadata={"routed_tier": "c2"},
    )

    pool = provider.selection_plan["candidate_pool"]
    assert any(
        candidate["provider"] == "openrouter"
        and candidate["model"] == "qwen/qwen3.7-max"
        and candidate["source"] == "custom"
        for candidate in pool
    )
    assert all(candidate["model"] != "disabled/model" for candidate in pool)


def test_build_ensemble_provider_inherits_current_openrouter_credentials() -> None:
    cfg = GatewayConfig(llm_ensemble={"enabled": True})
    inherited = ProviderConfig(
        provider="openrouter",
        model="routed/model",
        api_key="fake",
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
    assert all(member.provider_config.api_key == "fake" for member in members)
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
            "selection_mode": "router_dynamic",
            "min_successful_proposers": 4,
        }
    )
    inherited = ProviderConfig(
        provider="openrouter",
        model="deepseek/deepseek-v4-flash",
        api_key="fake",
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
    assert provider.proposer_timeout_seconds == 3600.0
    assert provider.aggregator_timeout_seconds == 3600.0
    assert provider.quorum_grace_seconds == 0.0


def test_router_dynamic_ensemble_uses_slot_specific_c2_selection() -> None:
    cfg = GatewayConfig(
        llm_ensemble={
            "enabled": True,
            "selection_mode": "router_dynamic",
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
        api_key="fake",
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


def test_static_openrouter_b5_ensemble_locks_members_across_routed_tiers() -> None:
    cfg = GatewayConfig(
        llm_ensemble={
            "enabled": True,
            "selection_mode": "static_openrouter_b5",
            "min_successful_proposers": 9,
            "shuffle_candidates": False,
        }
    )
    inherited = ProviderConfig(
        provider="openrouter",
        model="routed/model",
        api_key="fake",
        base_url="https://openrouter.example/api/v1",
        proxy="http://proxy.local:7890",
        provider_routing={"z-ai/glm-5.2": "z-ai"},
    )
    expected_proposers = [
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
        "moonshotai/kimi-k2.7-code",
        "qwen/qwen3.7-max",
    ]

    for tier in ("c0", "c1", "c2", "c3"):
        provider = build_ensemble_provider_from_config(
            config=cfg,
            inherited_provider_config=inherited,
            fallback_provider=None,
            turn_metadata={"routed_tier": tier, "routing_confidence": 0.99},
        )

        assert provider.profile_name == "static_openrouter_b5"
        assert [member.provider_config.model for member in provider.proposers] == expected_proposers
        assert provider.aggregator.provider_config.model == "z-ai/glm-5.2"
        assert provider.selection_plan == {
            "strategy": "static_openrouter_b5",
            "profile": "static_openrouter_b5",
            "proposer_models": expected_proposers,
            "aggregator_model": "z-ai/glm-5.2",
            "proposer_count": 4,
            "configured_min_successful_proposers": 9,
            "effective_min_successful_proposers": 4,
            "configured_proposer_timeout_seconds": 3600.0,
            "effective_proposer_timeout_seconds": 300.0,
            "configured_aggregator_timeout_seconds": 3600.0,
            "effective_aggregator_timeout_seconds": 480.0,
            "configured_shuffle_candidates": False,
            "effective_shuffle_candidates": False,
            "quorum_grace_seconds": 30.0,
        }
        assert provider.min_successful_proposers == 4
        assert provider.proposer_timeout_seconds == 300.0
        assert provider.aggregator_timeout_seconds == 480.0
        assert provider.shuffle_candidates is False
        assert provider.quorum_grace_seconds == 30.0
        members = [*provider.proposers, provider.aggregator]
        assert all(member.provider_config.provider == "openrouter" for member in members)
        assert all(member.provider_config.api_key == "fake" for member in members)
        assert all(
            member.provider_config.base_url == "https://openrouter.example/api/v1"
            for member in members
        )
        assert all(member.provider_config.proxy == "http://proxy.local:7890" for member in members)
        assert all(
            member.provider_config.provider_routing == {"z-ai/glm-5.2": "z-ai"}
            for member in members
        )


def test_static_openrouter_b5_ensemble_uses_profile_effective_defaults() -> None:
    cfg = GatewayConfig(
        llm_ensemble={
            "enabled": True,
            "selection_mode": "static_openrouter_b5",
        }
    )
    provider = build_ensemble_provider_from_config(
        config=cfg,
        inherited_provider_config=ProviderConfig(
            provider="openrouter",
            model="routed/model",
            api_key="fake",
            base_url="https://openrouter.example/api/v1",
        ),
        fallback_provider=None,
    )

    assert cfg.llm_ensemble.min_successful_proposers == 1
    assert cfg.llm_ensemble.proposer_timeout_seconds == 3600.0
    assert cfg.llm_ensemble.aggregator_timeout_seconds == 3600.0
    assert cfg.llm_ensemble.shuffle_candidates is True
    assert provider.min_successful_proposers == 3
    assert provider.proposer_timeout_seconds == 300.0
    assert provider.aggregator_timeout_seconds == 480.0
    assert provider.shuffle_candidates is False
    assert provider.quorum_grace_seconds == 30.0


def test_static_openrouter_b5_ensemble_preserves_custom_effective_values() -> None:
    cfg = GatewayConfig(
        llm_ensemble={
            "enabled": True,
            "selection_mode": "static_openrouter_b5",
            "min_successful_proposers": 2,
            "proposer_timeout_seconds": 180.0,
            "aggregator_timeout_seconds": 900.0,
            "shuffle_candidates": False,
        }
    )
    provider = build_ensemble_provider_from_config(
        config=cfg,
        inherited_provider_config=ProviderConfig(
            provider="openrouter",
            model="routed/model",
            api_key="fake",
            base_url="https://openrouter.example/api/v1",
        ),
        fallback_provider=None,
    )

    assert provider.min_successful_proposers == 2
    assert provider.proposer_timeout_seconds == 180.0
    assert provider.aggregator_timeout_seconds == 900.0
    assert provider.shuffle_candidates is False
