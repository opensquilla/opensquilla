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
    assert cfg.llm_ensemble.proposer_tools is False
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
        "google/gemini-3.1-pro-preview",
    ]
    assert cfg.llm_ensemble.profiles["g3_standard"].aggregator.model == "z-ai/glm-5.2"
    assert (
        cfg.llm_ensemble.profiles["g4_gemini_aggregator"].aggregator.model
        == "google/gemini-3.1-pro-preview"
    )
    assert (
        cfg.llm_ensemble.profiles["g6_gpt_aggregator"].aggregator_timeout_seconds
        == 300.0
    )
    assert cfg.llm_ensemble.profiles["g9_qwen_aggregator"].aggregator.model == (
        "qwen/qwen3.7-max"
    )
    assert cfg.llm_ensemble.profiles["g10_gemini_aggregator"].aggregator.model == (
        "google/gemini-3.1-pro-preview"
    )
    assert cfg.llm_ensemble.profiles["g11_deepseek_aggregator"].aggregator.model == (
        "deepseek/deepseek-v4-pro"
    )
    g12_proposers = cfg.llm_ensemble.profiles["g12_k2_replace_gemini"].proposers
    assert [ref.model for ref in g12_proposers] == [
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
        "moonshotai/kimi-k2.7-code",
        "qwen/qwen3.7-max",
    ]
    assert (
        cfg.llm_ensemble.profiles["g12_k2_replace_gemini"].proposer_timeout_seconds
        == 240.0
    )
    assert (
        cfg.llm_ensemble.profiles[
            "g12_k2_replace_gemini"
        ].proposer_early_stop_success_count
        == 3
    )
    assert (
        cfg.llm_ensemble.profiles[
            "g12_k2_replace_gemini"
        ].proposer_early_stop_after_seconds
        == 150.0
    )
    assert len(cfg.llm_ensemble.profiles["g13_five_proposers"].proposers) == 5
    g14_proposers = cfg.llm_ensemble.profiles["g14_k2_replace_qwen"].proposers
    assert [ref.model for ref in g14_proposers] == [
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
        "google/gemini-3.1-pro-preview",
        "moonshotai/kimi-k2.7-code",
    ]
    g15 = cfg.llm_ensemble.profiles["g15_g8_top3_prefilter"]
    assert [ref.model for ref in g15.proposers] == [
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
        "google/gemini-3.1-pro-preview",
        "qwen/qwen3.7-max",
    ]
    assert g15.aggregator.model == "z-ai/glm-5.2"
    assert g15.candidate_scorer is not None
    assert g15.candidate_scorer.model == "google/gemini-3.1-pro-preview"
    assert g15.candidate_prefilter_top_k == 3
    g16 = cfg.llm_ensemble.profiles["g16_sampled_cheap_proposers"]
    assert [ref.model for ref in g16.proposers] == [
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
        "google/gemini-3.1-pro-preview",
        "qwen/qwen3.7-max",
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
        "google/gemini-3.1-pro-preview",
        "qwen/qwen3.7-max",
    ]
    assert g17.aggregator.model == "z-ai/glm-5.2"
    assert g17.moa_layers == 2
    g18 = cfg.llm_ensemble.profiles["g18_select_best_candidate"]
    assert [ref.model for ref in g18.proposers] == [
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
        "google/gemini-3.1-pro-preview",
        "qwen/qwen3.7-max",
    ]
    assert g18.aggregator.model == "z-ai/glm-5.2"
    assert g18.output_strategy == "select_best_candidate"
    assert g18.moa_layers == 1
    g19 = cfg.llm_ensemble.profiles["g19_g12_top3_prefilter"]
    assert [ref.model for ref in g19.proposers] == [
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
        "moonshotai/kimi-k2.7-code",
        "qwen/qwen3.7-max",
    ]
    assert g19.aggregator.model == "z-ai/glm-5.2"
    assert g19.candidate_scorer is not None
    assert g19.candidate_scorer.model == "google/gemini-3.1-pro-preview"
    assert g19.candidate_prefilter_top_k == 3
    assert g19.moa_layers == 1
    assert g19.proposer_timeout_seconds == 120.0
    assert g19.proposer_early_stop_success_count == 0
    assert g19.proposer_early_stop_after_seconds == 0.0
    g20 = cfg.llm_ensemble.profiles["g20_g12_top2_prefilter"]
    assert [ref.model for ref in g20.proposers] == [
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
        "moonshotai/kimi-k2.7-code",
        "qwen/qwen3.7-max",
    ]
    assert g20.candidate_scorer is not None
    assert g20.candidate_scorer.model == "google/gemini-3.1-pro-preview"
    assert g20.candidate_prefilter_top_k == 2
    assert g20.moa_layers == 1
    assert g20.proposer_timeout_seconds == 120.0
    assert g20.proposer_early_stop_success_count == 0
    assert g20.proposer_early_stop_after_seconds == 0.0
    g21 = cfg.llm_ensemble.profiles["g21_g13_top3_prefilter"]
    assert [ref.model for ref in g21.proposers] == [
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
        "google/gemini-3.1-pro-preview",
        "qwen/qwen3.7-max",
        "moonshotai/kimi-k2.7-code",
    ]
    assert g21.candidate_scorer is not None
    assert g21.candidate_scorer.model == "google/gemini-3.1-pro-preview"
    assert g21.candidate_prefilter_top_k == 3
    assert g21.moa_layers == 1
    g22 = cfg.llm_ensemble.profiles["g22_g12_glm_top3_prefilter"]
    assert [ref.model for ref in g22.proposers] == [
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
        "moonshotai/kimi-k2.7-code",
        "qwen/qwen3.7-max",
    ]
    assert g22.candidate_scorer is not None
    assert g22.candidate_scorer.model == "z-ai/glm-5.2"
    assert g22.candidate_prefilter_top_k == 3
    assert g22.moa_layers == 1
    assert g22.proposer_timeout_seconds == 120.0
    assert g22.proposer_early_stop_success_count == 0
    assert g22.proposer_early_stop_after_seconds == 0.0
    g23 = cfg.llm_ensemble.profiles["g23_g12_plus_gemini_sampled_top3_prefilter"]
    assert [ref.model for ref in g23.proposers] == [
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
        "moonshotai/kimi-k2.7-code",
        "qwen/qwen3.7-max",
        "google/gemini-3.1-pro-preview",
    ]
    assert [ref.k for ref in g23.proposers] == [1, 1, 1, 2, 2]
    assert [ref.temperature for ref in g23.proposers] == [
        0.0,
        0.0,
        0.0,
        0.3,
        0.3,
    ]
    assert g23.aggregator.model == "z-ai/glm-5.2"
    assert g23.aggregator.temperature == 0.0
    assert g23.candidate_scorer is not None
    assert g23.candidate_scorer.model == "google/gemini-3.1-pro-preview"
    assert g23.candidate_prefilter_top_k == 3
    assert g23.preserve_member_temperature is True
    assert g23.moa_layers == 1
    assert g23.proposer_timeout_seconds == 120.0
    assert g23.proposer_early_stop_success_count == 0
    assert g23.proposer_early_stop_after_seconds == 0.0
    g24 = cfg.llm_ensemble.profiles["g24_g12_drop_k2_7_code"]
    assert [ref.model for ref in g24.proposers] == [
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
        "qwen/qwen3.7-max",
    ]
    assert g24.aggregator.model == "z-ai/glm-5.2"
    assert g24.proposer_timeout_seconds == 240.0
    assert g24.proposer_early_stop_success_count == 3
    assert g24.proposer_early_stop_after_seconds == 150.0
    g25 = cfg.llm_ensemble.profiles["g25_g12_drop_qwen3_7"]
    assert [ref.model for ref in g25.proposers] == [
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-5.2",
        "moonshotai/kimi-k2.7-code",
    ]
    assert g25.aggregator.model == "z-ai/glm-5.2"
    assert g25.proposer_timeout_seconds == 240.0
    assert g25.proposer_early_stop_success_count == 3
    assert g25.proposer_early_stop_after_seconds == 150.0
    assert cfg.llm_ensemble.profiles["g3_standard"].record_candidates is False
    assert cfg.llm_ensemble.profiles["g3_standard"].proposer_early_stop_success_count == 0


def test_llm_ensemble_config_validates_enabled_profile() -> None:
    with pytest.raises(ValueError, match="active_profile"):
        LlmEnsembleConfig(enabled=True, active_profile="missing")


def test_build_ensemble_provider_from_gateway_config() -> None:
    cfg = GatewayConfig(
        llm_ensemble={
            "enabled": True,
            "proposer_tools": True,
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
                    "proposer_early_stop_success_count": 2,
                    "proposer_early_stop_after_seconds": 45,
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
    assert provider.proposer_tools is True
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
    assert provider.proposer_early_stop_success_count == 2
    assert provider.proposer_early_stop_after_seconds == 45.0
