from __future__ import annotations

import pytest

from opensquilla.gateway.config import GatewayConfig, LlmEnsembleConfig
from opensquilla.provider import EnsembleProvider, build_ensemble_provider_from_config
from opensquilla.provider.selector import ProviderConfig
from opensquilla.provider.types import DoneEvent, Message, TextDeltaEvent


class _FallbackProvider:
    provider_name = "fallback"

    async def chat(self, messages: list[Message], tools=None, config=None):  # noqa: ANN001
        yield TextDeltaEvent(text="fallback")
        yield DoneEvent(model="fallback")

    async def list_models(self) -> list:
        return []


def test_llm_ensemble_config_defaults_disabled_with_profiles() -> None:
    cfg = GatewayConfig()

    assert cfg.llm_ensemble.enabled is False
    assert cfg.llm_ensemble.active_profile == "g3_standard"
    assert "g3_standard" in cfg.llm_ensemble.profiles
    assert "g1_code" in cfg.llm_ensemble.profiles
    assert [ref.model for ref in cfg.llm_ensemble.profiles["g1_code"].proposers] == [
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
        "moonshotai/kimi-k2.7-code",
    ]
    assert [ref.model for ref in cfg.llm_ensemble.profiles["g3_standard"].proposers] == [
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
        "google/gemini-3-flash-preview",
    ]
    assert cfg.llm_ensemble.profiles["g3_standard"].aggregator.model == "z-ai/glm-5.2"
    assert (
        cfg.llm_ensemble.profiles["g4_gemini_aggregator"].aggregator.model
        == "google/gemini-3-flash-preview"
    )
    assert (
        cfg.llm_ensemble.profiles["g6_gpt_aggregator"].aggregator_timeout_seconds
        == 300.0
    )
    assert cfg.llm_ensemble.profiles["g9_qwen_aggregator"].aggregator.model == (
        "qwen/qwen3.7-plus"
    )
    assert cfg.llm_ensemble.profiles["g10_gemini_aggregator"].aggregator.model == (
        "google/gemini-3-flash-preview"
    )
    assert cfg.llm_ensemble.profiles["g11_deepseek_aggregator"].aggregator.model == (
        "deepseek/deepseek-v4-pro"
    )
    g12_proposers = cfg.llm_ensemble.profiles["g12_k2_replace_gemini"].proposers
    assert [ref.model for ref in g12_proposers] == [
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
        "moonshotai/kimi-k2.7-code",
        "qwen/qwen3.7-plus",
    ]
    assert len(cfg.llm_ensemble.profiles["g13_five_proposers"].proposers) == 5
    g14_proposers = cfg.llm_ensemble.profiles["g14_k2_replace_qwen"].proposers
    assert [ref.model for ref in g14_proposers] == [
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
        "google/gemini-3-flash-preview",
        "moonshotai/kimi-k2.7-code",
    ]
    g15 = cfg.llm_ensemble.profiles["g15_g8_top3_prefilter"]
    assert [ref.model for ref in g15.proposers] == [
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
        "google/gemini-3-flash-preview",
        "qwen/qwen3.7-plus",
    ]
    assert g15.aggregator.model == "z-ai/glm-5.2"
    assert g15.candidate_scorer is not None
    assert g15.candidate_scorer.model == "google/gemini-3-flash-preview"
    assert g15.candidate_prefilter_top_k == 3
    g16 = cfg.llm_ensemble.profiles["g16_sampled_cheap_proposers"]
    assert [ref.model for ref in g16.proposers] == [
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
        "google/gemini-3-flash-preview",
        "qwen/qwen3.7-plus",
    ]
    assert [ref.k for ref in g16.proposers] == [1, 1, 2, 2]
    assert [ref.temperature for ref in g16.proposers] == [0.0, 0.0, 0.3, 0.3]
    assert g16.aggregator.model == "z-ai/glm-5.2"
    assert g16.aggregator.temperature == 0.0
    assert g16.preserve_member_temperature is True
    g17 = cfg.llm_ensemble.profiles["g17_two_layer_moa"]
    assert [ref.model for ref in g17.proposers] == [
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
        "google/gemini-3-flash-preview",
        "qwen/qwen3.7-plus",
    ]
    assert g17.aggregator.model == "z-ai/glm-5.2"
    assert g17.moa_layers == 2
    g18 = cfg.llm_ensemble.profiles["g18_select_best_candidate"]
    assert [ref.model for ref in g18.proposers] == [
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
        "google/gemini-3-flash-preview",
        "qwen/qwen3.7-plus",
    ]
    assert g18.aggregator.model == "z-ai/glm-5.2"
    assert g18.output_strategy == "select_best_candidate"
    assert g18.moa_layers == 1
    assert cfg.llm_ensemble.profiles["g3_standard"].record_candidates is False


def test_llm_ensemble_config_validates_enabled_profile() -> None:
    with pytest.raises(ValueError, match="active_profile"):
        LlmEnsembleConfig(enabled=True, active_profile="missing")


def test_build_ensemble_provider_from_gateway_config() -> None:
    cfg = GatewayConfig(
        llm_ensemble={
            "enabled": True,
            "active_profile": "custom",
            "profiles": {
                "custom": {
                    "proposers": [{"model": "p1"}, {"model": "p2", "k": 2}],
                    "aggregator": {"model": "agg"},
                    "candidate_scorer": {"model": "judge"},
                    "candidate_prefilter_top_k": 1,
                    "output_strategy": "select_best_candidate",
                    "moa_layers": 2,
                    "candidate_max_chars": 123,
                }
            },
        }
    )
    inherited = ProviderConfig(
        provider="openrouter",
        model="base",
        api_key="sk-test",
        base_url="https://openrouter.ai/api",
    )

    provider = build_ensemble_provider_from_config(
        config=cfg,
        inherited_provider_config=inherited,
        fallback_provider=_FallbackProvider(),
    )

    assert isinstance(provider, EnsembleProvider)
    assert provider.profile_name == "custom"
    assert [member.provider_config.model for member in provider.proposers] == ["p1", "p2"]
    assert provider.proposers[1].k == 2
    assert provider.aggregator.provider_config.model == "agg"
    assert provider.candidate_scorer is not None
    assert provider.candidate_scorer.provider_config.model == "judge"
    assert provider.candidate_prefilter_top_k == 1
    assert provider.output_strategy == "select_best_candidate"
    assert provider.moa_layers == 2
    assert provider.candidate_max_chars == 123
