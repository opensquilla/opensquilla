from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
import structlog.testing

import opensquilla.provider.ranking_router as ranking_router
from opensquilla.engine.usage_accounting import (
    UsageAccountingScope,
    UsageExecutionContext,
    bind_usage_accounting_scope,
)
from opensquilla.provider.ranking_router import (
    CAPABILITIES,
    DOMAINS,
    TASK_ANALYZER_MODEL_ID,
    TASK_ANALYZER_PROVIDER_ID,
    DynamicRankingError,
    TaskAnalysisResult,
    analyze_task_with_provider,
    build_model_registry_snapshot,
    build_request_context,
    dynamic_output_token_budgets,
    fallback_task_profile,
    load_model_registry_snapshot,
    load_ranking_config,
    mock_user_profile,
    normalize_task_profile,
    rank_models,
)
from opensquilla.provider.types import ChatConfig, DoneEvent, Message, TextDeltaEvent


def _task_profile(
    *,
    tier: int = 3,
    risk: str = "medium",
    cost: str = "medium",
    latency: str = "normal",
    context: str = "short",
    modalities: list[str] | None = None,
    intent: str = "new_task",
    intent_confidence: float = 1.0,
) -> dict[str, Any]:
    return {
        "capability_dist": {"reasoning": 0.6, "code_generation": 0.4},
        "domain_dist": {"software_engineering": 1.0},
        "tier_dist": {str(tier): 1.0},
        "constraints": {
            "cost": cost,
            "latency": latency,
            "context": context,
            "modality": modalities or ["text"],
            "risk": risk,
        },
        "optional_constraints": {"format": "patch"},
        "session_intent": {"type": intent, "confidence": intent_confidence},
    }


def _analysis(**kwargs: Any) -> TaskAnalysisResult:
    return TaskAnalysisResult(
        profile=_task_profile(**kwargs),
        source="test",
        schema_valid=True,
        confidence=1.0,
    )


def _context(
    *,
    input_tokens: int = 1_000,
    candidate_tokens: int = 1_000,
    aggregator_tokens: int = 1_000,
    last_route: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "routing_budget": {
            "estimated_input_tokens": input_tokens,
            "tool_log_tokens": 0,
            "candidate_output_tokens": candidate_tokens,
            "aggregator_output_tokens": aggregator_tokens,
        },
        "input_modalities": ["text"],
        "last_route": last_route or {},
        "snapshot_hash": "request-context-test",
    }


def _model(
    model_id: str,
    *,
    provider: str = "test-provider",
    vendor: str | None = None,
    family: str | None = None,
    roles: list[str] | None = None,
    status: str = "enabled",
    health: str = "healthy",
    credential_available: bool = True,
    context_window: int = 128_000,
    modalities: list[str] | None = None,
    capability: float = 0.8,
    aggregator_fit: float = 0.8,
    price: float = 1.0,
    latency_ms: int = 2_000,
) -> dict[str, Any]:
    return {
        "source": "test_registry",
        "runtime": {"thinking": "off"},
        "registry_facts": {
            "model_id": model_id,
            "version": "test-v1",
            "provider": provider,
            "vendor": vendor or provider,
            "family": family or model_id,
            "status": status,
            "roles": roles or ["proposer", "aggregator"],
            "context_window": context_window,
            "effective_context_bucket": "extra_long",
            "modalities": modalities or ["text"],
            "tools": [],
            "price": {
                "input_per_million": price,
                "output_per_million": price,
            },
            "latency_p50_ms": latency_ms // 2,
            "latency_p95_ms": latency_ms,
            "quota": "available",
            "rate_limit": "available",
            "health": health,
            "credential_available": credential_available,
        },
        "static_profile": {
            "capability_dist_prior": {
                "reasoning": capability,
                "code_generation": capability,
                "format_following": capability,
            },
            "domain_dist_prior": {"software_engineering": capability},
            "tier_dist_prior": {
                "1": capability,
                "2": capability,
                "3": capability,
                "4": capability,
            },
            "role_fit_prior": {
                "proposer": capability,
                "aggregator": aggregator_fit,
            },
        },
        "online_profile": {
            "error_rates": {
                "hallucination": max(0.0, 1.0 - capability),
                "omission": max(0.0, 0.9 - capability),
            }
        },
    }


def _snapshot(*models: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "test",
        "snapshot_version": "test-snapshot-v1",
        "models": list(models),
    }


def _decision(
    *models: dict[str, Any],
    analysis: TaskAnalysisResult | None = None,
    context: dict[str, Any] | None = None,
    user_profile: dict[str, Any] | None = None,
    ranking_config: dict[str, Any] | None = None,
):
    return rank_models(
        task_analysis=analysis or _analysis(),
        user_profile=user_profile or mock_user_profile(),
        request_context=context or _context(),
        registry_snapshot=_snapshot(*models),
        routed_tier="c2",
        routing_confidence=0.9,
        ranking_config=ranking_config,
    )


def test_packaged_ranking_config_is_versioned_validated_and_isolated() -> None:
    first = load_ranking_config()
    second = load_ranking_config()

    assert first["schema_version"] == "step2-ranking-config-v3"
    assert first["config_version"].startswith("step2-ranking-")
    assert first["task_analyzer"]["max_output_tokens"] == 1_200
    assert first["routing_tiers"]["mapping"] == {"c0": 1, "c1": 2, "c2": 3, "c3": 4}
    assert first["context"]["bucket_min_tokens"]["extra_long"] == 128_000
    assert first["context"]["token_estimation"]["dense_chars_per_token"] == 1
    assert first["validation"]["task_profile_sum_tolerance"] == pytest.approx(0.02)
    assert first["fallback_task_profile"]["capability_dist"]["reasoning"] == 0.50
    assert first["synthetic_model"]["context_window"] == 128_000
    assert first["hard_filter"]["eligible_statuses"] == ["enabled", "canary"]
    assert first["exploration"] == {"enabled": False, "decision_propensity": 1.0}
    assert first["rerank"]["similarity_penalty_weight"] == pytest.approx(0.25)
    first["rerank"]["similarity_penalty_weight"] = 99.0
    assert second["rerank"]["similarity_penalty_weight"] == pytest.approx(0.25)


def test_invalid_ranking_config_fails_before_selection() -> None:
    config = load_ranking_config()
    config["quality"]["task_match_weight"] = 0.90

    with pytest.raises(DynamicRankingError, match="sum to 1"):
        _decision(_model("only"), analysis=_analysis(tier=1), ranking_config=config)


def test_ranking_config_rejects_ambiguous_or_inactive_settings() -> None:
    duplicate_errors = load_ranking_config()
    duplicate_errors["rerank"]["error_dimensions"].append("timeout")

    ambiguous_tiers = load_ranking_config()
    ambiguous_tiers["routing_tiers"]["mapping"]["c3"] = 3

    bool_penalty = load_ranking_config()
    bool_penalty["penalties"]["task_cost_weights"]["low"] = True

    inactive_exploration = load_ranking_config()
    inactive_exploration["exploration"]["enabled"] = True

    for config, message in (
        (duplicate_errors, "cannot contain duplicates"),
        (ambiguous_tiers, "one-to-one"),
        (bool_penalty, "must be numeric"),
        (inactive_exploration, "exploration is reserved"),
    ):
        with pytest.raises(DynamicRankingError, match=message):
            _decision(
                _model("only"),
                analysis=_analysis(tier=1),
                ranking_config=config,
            )


def test_ranking_config_rejects_unknown_or_missing_nested_parameters() -> None:
    unknown = load_ranking_config()
    unknown["rerank"]["similarity"]["capabilty_weight"] = 0.5

    missing = load_ranking_config()
    missing["task_analyzer"].pop("temperature")

    unsupported_protocol_value = load_ranking_config()
    unsupported_protocol_value["penalties"]["task_cost_weights"]["economy"] = 0.1

    for config, message in (
        (unknown, "unknown or missing keys"),
        (missing, "unknown or missing keys"),
        (unsupported_protocol_value, "supported protocol values"),
    ):
        with pytest.raises(DynamicRankingError, match=message):
            _decision(
                _model("only"),
                analysis=_analysis(tier=1),
                ranking_config=config,
            )


def test_packaged_mock_registry_has_versioned_step2_profiles() -> None:
    snapshot = load_model_registry_snapshot()
    model_ids = [model["registry_facts"]["model_id"] for model in snapshot["models"]]

    assert snapshot["snapshot_version"].startswith("mock-step2-")
    assert len(snapshot["models"]) == 20
    assert len(set(model_ids)) == len(model_ids)
    assert {
        "poolside/laguna-xs-2.1",
        "tencent/hy3",
        "kwaipilot/kat-coder-air-v2.5",
        "meta-llama/llama-4-scout",
        "kwaipilot/kat-coder-pro-v2.5",
        "minimax/minimax-m3",
        "mistralai/mistral-medium-3-5",
        "openai/gpt-5.6-luna",
        "anthropic/claude-sonnet-5",
        "x-ai/grok-4.5",
        "google/gemini-3.1-pro-preview",
    }.issubset(model_ids)
    for model in snapshot["models"]:
        assert model["registry_facts"]["model_id"]
        assert model["registry_facts"]["provider"] == "openrouter"
        assert model["registry_facts"]["roles"]
        assert model["registry_facts"]["context_window"] > 0
        assert set(model["static_profile"]["capability_dist_prior"]) == set(CAPABILITIES)
        assert set(model["static_profile"]["domain_dist_prior"]) == set(DOMAINS)
        assert model["static_profile"]["tier_dist_prior"]
        assert model["static_profile"]["role_fit_prior"]["aggregator"] >= 0

    catalog_models = [
        model
        for model in snapshot["models"]
        if model["source"] == "openrouter_catalog_mock_profile"
    ]
    assert len(catalog_models) == 11
    assert all(
        model["registry_facts"]["catalog_verified_at"] == "2026-07-14"
        and model["registry_facts"]["latency_source"] == "mock"
        for model in catalog_models
    )
    assert min(
        model["registry_facts"]["price"]["input_per_million"]
        for model in catalog_models
    ) <= 0.10
    assert max(
        model["static_profile"]["role_fit_prior"]["proposer"]
        for model in catalog_models
    ) >= 0.94


def test_normalize_task_profile_falls_back_on_missing_required_distributions() -> None:
    profile, valid, errors = normalize_task_profile(
        {"constraints": {"risk": "low"}},
        routed_tier="c3",
        request_context=_context(),
    )

    assert valid is False
    assert "invalid_capability_dist" in errors
    assert profile["tier_dist"] == {"4": 1.0}
    assert profile["session_intent"] == {"type": "new_task", "confidence": 0.0}


@pytest.mark.parametrize(
    ("mutate", "expected_error"),
    [
        (
            lambda profile: profile.update(
                capability_dist={"reasoning": 0.5, "code_generation": 0.3}
            ),
            "invalid_capability_dist",
        ),
        (
            lambda profile: profile.update(
                capability_dist={"reasoning": "0.6", "code_generation": 0.4}
            ),
            "invalid_capability_dist",
        ),
        (
            lambda profile: profile["session_intent"].update(confidence=True),
            "invalid_session_intent_confidence",
        ),
    ],
)
def test_normalize_task_profile_rejects_invalid_required_numeric_fields(
    mutate: Any,
    expected_error: str,
) -> None:
    raw_profile = _task_profile(tier=2)
    mutate(raw_profile)

    _, valid, issues = normalize_task_profile(
        raw_profile,
        routed_tier="c1",
        request_context=_context(),
    )

    assert valid is False
    assert expected_error in issues


def test_normalize_task_profile_accepts_configured_distribution_rounding() -> None:
    raw_profile = _task_profile(tier=2)
    raw_profile["capability_dist"] = {"reasoning": 0.60, "code_generation": 0.39}

    profile, valid, issues = normalize_task_profile(
        raw_profile,
        routed_tier="c1",
        request_context=_context(),
    )

    assert valid is True
    assert issues == []
    assert sum(profile["capability_dist"].values()) == pytest.approx(1.0)


def test_request_context_uses_bounded_history_and_attachment_facts() -> None:
    context = build_request_context(
        message="current request",
        turn_metadata={
            "router_history_user_texts": ["old-1", "old-2"],
            "router_prev_assistant_text": "previous answer",
        },
        attachments=[{"name": "diagram.png", "media_type": "image/png"}],
        candidate_output_tokens=2_000,
        aggregator_output_tokens=3_000,
    )

    assert context["conversation"]["recent_turns"] == [
        "user: old-1",
        "user: old-2",
        "assistant: previous answer",
    ]
    assert context["input_modalities"] == ["text", "image"]
    assert context["workspace_state"]["referenced_files"] == ["diagram.png"]
    assert len(context["snapshot_hash"]) == 64


def test_request_context_bounds_supplied_history_and_preserves_media_modalities() -> None:
    context = build_request_context(
        message="current request",
        turn_metadata={
            "material_estimated_tokens": 12_345,
            "router_dynamic_request_context": {
                "conversation": {
                    "summary": "s" * 5_000,
                    "recent_turns": [f"turn-{index}-" + ("x" * 3_000) for index in range(9)],
                }
            },
        },
        attachments=[
            {"filename": "voice.wav", "mime": "audio/wav"},
            {"name": "clip.mp4", "type": "video/mp4"},
            {"name": "brief.pdf", "media_type": "application/pdf"},
        ],
        candidate_output_tokens=2_000,
        aggregator_output_tokens=3_000,
    )

    assert len(context["conversation"]["summary"]) == 4_000
    assert len(context["conversation"]["recent_turns"]) == 6
    assert context["conversation"]["recent_turns"][0].startswith("turn-3-")
    assert all(len(turn) <= 2_000 for turn in context["conversation"]["recent_turns"])
    assert context["input_modalities"] == ["text", "audio", "video", "file"]
    assert context["attachment_refs"] == ["voice.wav", "clip.mp4", "brief.pdf"]
    assert context["routing_budget"]["estimated_input_tokens"] >= 12_345


def test_request_context_limits_and_token_estimation_are_config_driven() -> None:
    config = load_ranking_config()
    config["context"]["request_limits"]["max_recent_turns"] = 2
    config["context"]["request_limits"]["turn_max_chars"] = 12
    config["context"]["token_estimation"]["utf8_bytes_per_token"] = 1

    context = build_request_context(
        message="abcdefghij",
        turn_metadata={
            "router_dynamic_request_context": {
                "conversation": {
                    "recent_turns": ["first-long-turn", "second-long-turn", "third-long-turn"]
                }
            }
        },
        attachments=[],
        candidate_output_tokens=10,
        aggregator_output_tokens=10,
        ranking_config=config,
    )

    assert context["conversation"]["recent_turns"] == ["second-long-", "third-long-t"]
    assert context["routing_budget"]["estimated_input_tokens"] >= 10


def test_request_context_uses_a_conservative_dense_script_token_estimate() -> None:
    ascii_context = build_request_context(
        message="a" * 400,
        turn_metadata={},
        attachments=[],
        candidate_output_tokens=10,
        aggregator_output_tokens=10,
    )
    dense_context = build_request_context(
        message="中" * 400,
        turn_metadata={},
        attachments=[],
        candidate_output_tokens=10,
        aggregator_output_tokens=10,
    )

    ascii_tokens = ascii_context["routing_budget"]["estimated_input_tokens"]
    dense_tokens = dense_context["routing_budget"]["estimated_input_tokens"]
    assert dense_tokens >= ascii_tokens + 250


def test_dynamic_output_token_budgets_do_not_assume_ascii_density() -> None:
    assert dynamic_output_token_budgets(
        configured_output_tokens=0,
        candidate_max_chars=24_000,
    ) == (24_000, 8_192)
    assert dynamic_output_token_budgets(
        configured_output_tokens=20_000,
        candidate_max_chars=6_000,
    ) == (6_000, 20_000)
    assert dynamic_output_token_budgets(
        configured_output_tokens=4_096,
        candidate_max_chars=24_000,
    ) == (24_000, 4_096)
    assert dynamic_output_token_budgets(
        configured_output_tokens=4_096,
        candidate_max_chars=0,
    ) == (4_096, 4_096)

    config = load_ranking_config()
    config["context"]["output_budget"]["default_tokens"] = 77
    config["context"]["token_estimation"]["candidate_chars_per_token"] = 2
    assert dynamic_output_token_budgets(
        configured_output_tokens=0,
        candidate_max_chars=100,
        ranking_config=config,
    ) == (50, 77)


def test_request_context_sanitizes_supplied_state_and_estimates_tool_tokens() -> None:
    context = build_request_context(
        message="review the workspace",
        turn_metadata={
            "router_dynamic_request_context": {
                "secret_unbounded_field": "do-not-forward",
                "tool_state": {
                    "called_tools": [
                        {"name": f"tool-{index}", "arguments": [index]} for index in range(40)
                    ],
                    "tool_results_summary": "result" * 2_000,
                    "failed_tools": [["nested", index] for index in range(40)],
                },
                "workspace_state": {
                    "referenced_files": [{"path": f"src/file-{index}.py"} for index in range(40)],
                    "changed_files": ["changed.py", "changed.py"],
                    "test_results": "failed" * 1_000,
                },
                "intermediate_outputs": {
                    "previous_candidates": [
                        f"candidate-{index}:" + ("candidate" * 500) for index in range(12)
                    ],
                    "current_errors": [f"error-{index}:" + ("error" * 500) for index in range(12)],
                },
                "last_route": {
                    "selected_P": [f"provider:model-{index}" for index in range(20)],
                    "selected_A": "provider:aggregator",
                    "quality_feedback": 2.0,
                    "escalation_level": 99,
                    "raw_prompt": "must-not-survive",
                },
            }
        },
        attachments=[{"name": {"path": "diagram.png"}, "media_type": "image/png"}],
        candidate_output_tokens=8_192,
        aggregator_output_tokens=8_192,
    )

    assert "secret_unbounded_field" not in context
    assert len(context["tool_state"]["called_tools"]) == 32
    assert len(context["tool_state"]["tool_results_summary"]) == 4_000
    assert len(context["workspace_state"]["referenced_files"]) == 32
    assert context["workspace_state"]["changed_files"] == ["changed.py"]
    assert len(context["intermediate_outputs"]["previous_candidates"]) == 8
    assert len(context["last_route"]["selected_P"]) == 8
    assert context["last_route"]["quality_feedback"] == 1.0
    assert context["last_route"]["escalation_level"] == 2
    assert "raw_prompt" not in context["last_route"]
    assert context["routing_budget"]["tool_log_tokens"] > 0
    assert all(isinstance(value, str) for value in context["workspace_state"]["referenced_files"])


def test_fallback_context_bucket_uses_boundary_token_as_the_larger_bucket() -> None:
    profile = fallback_task_profile(
        routed_tier="c1",
        request_context=_context(input_tokens=8_000),
    )

    assert profile["constraints"]["context"] == "medium"


def test_fallback_profile_and_mock_user_are_loaded_from_ranking_config() -> None:
    config = load_ranking_config()
    config["context"]["bucket_min_tokens"]["medium"] = 100
    config["fallback_task_profile"]["capability_dist"] = {"writing": 1.0}
    config["fallback_task_profile"]["risk_by_tier"]["2"] = "high"
    config["mock_user_profile"]["preference"]["cost_sensitivity"] = "high"

    profile = fallback_task_profile(
        routed_tier="c1",
        request_context=_context(input_tokens=100),
        ranking_config=config,
    )
    user = mock_user_profile(config)

    assert profile["capability_dist"] == {"writing": 1.0}
    assert profile["constraints"]["context"] == "medium"
    assert profile["constraints"]["risk"] == "high"
    assert user["preference"]["cost_sensitivity"] == "high"


def test_runtime_anchor_does_not_inherit_unverified_task_modalities() -> None:
    snapshot = build_model_registry_snapshot(
        inherited_provider="test-provider",
        inherited_model="test-vendor/unknown-model",
        routed_tier="c2",
        anchor_modalities=["text"],
        packaged_snapshot={
            "schema_version": "test",
            "snapshot_version": "test-v1",
            "models": [],
        },
    )

    assert snapshot["models"][0]["registry_facts"]["modalities"] == ["text"]


def test_unknown_model_synthesis_is_config_driven() -> None:
    config = load_ranking_config()
    config["synthetic_model"]["context_window"] = 77_777
    config["synthetic_model"]["price_input_per_million"] = 1.25
    config["synthetic_model"]["base_strength_by_tier"]["3"] = 0.42

    snapshot = build_model_registry_snapshot(
        inherited_provider="test-provider",
        inherited_model="vendor/unknown-model-v1",
        routed_tier="c2",
        packaged_snapshot={
            "schema_version": "test",
            "snapshot_version": "test-v1",
            "models": [],
        },
        ranking_config=config,
    )

    anchor = snapshot["models"][0]
    assert anchor["registry_facts"]["context_window"] == 77_777
    assert anchor["registry_facts"]["price"]["input_per_million"] == 1.25
    assert anchor["static_profile"]["capability_dist_prior"]["reasoning"] == 0.42


def test_vendor_qualified_model_does_not_reuse_another_vendor_template() -> None:
    google_template = _model(
        "google/shared-model",
        provider="openrouter",
        vendor="google",
        family="google-shared",
        capability=0.99,
    )
    snapshot = build_model_registry_snapshot(
        inherited_provider="openrouter",
        inherited_model="acme/shared-model",
        routed_tier="c2",
        packaged_snapshot={
            "schema_version": "test",
            "snapshot_version": "test-v1",
            "models": [google_template],
        },
    )

    anchor = snapshot["models"][0]
    assert anchor["registry_facts"]["model_id"] == "acme/shared-model"
    assert anchor["registry_facts"]["vendor"] == "acme"
    assert anchor["registry_facts"]["family"] == "shared-model"


def test_ambiguous_bare_model_name_uses_synthesized_profile() -> None:
    snapshot = build_model_registry_snapshot(
        inherited_provider="openrouter",
        inherited_model="shared-model",
        routed_tier="c2",
        packaged_snapshot={
            "schema_version": "test",
            "snapshot_version": "test-v1",
            "models": [
                _model("google/shared-model", capability=0.99),
                _model("acme/shared-model", capability=0.10),
            ],
        },
    )

    anchor = snapshot["models"][0]
    assert anchor["registry_facts"]["model_id"] == "shared-model"
    assert anchor["static_profile"]["capability_dist_prior"]["reasoning"] == 0.74


def test_operator_candidates_only_use_explicit_aggregator_role_for_aggregation() -> None:
    snapshot = build_model_registry_snapshot(
        inherited_provider="anchor-provider",
        inherited_model="anchor-model",
        routed_tier="c2",
        operator_candidates=[
            {"provider": "provider-a", "model": "model-a", "role": ""},
            {"provider": "provider-b", "model": "model-b", "role": "critic"},
            {
                "provider": "provider-c",
                "model": "model-c",
                "role": "aggregator",
            },
        ],
        packaged_snapshot={
            "schema_version": "test",
            "snapshot_version": "test-v1",
            "models": [],
        },
    )
    by_model = {
        row["registry_facts"]["model_id"]: row["registry_facts"]["roles"]
        for row in snapshot["models"]
    }

    assert by_model["model-a"] == ["proposer"]
    assert by_model["model-b"] == ["proposer"]
    assert by_model["model-c"] == ["aggregator"]


def test_operator_role_overrides_duplicate_routed_anchor_role() -> None:
    snapshot = build_model_registry_snapshot(
        inherited_provider="anchor-provider",
        inherited_model="anchor-model",
        routed_tier="c2",
        operator_candidates=[
            {
                "provider": "ANCHOR-PROVIDER",
                "model": "ANCHOR-MODEL",
                "role": "aggregator",
            }
        ],
        packaged_snapshot={
            "schema_version": "test",
            "snapshot_version": "test-v1",
            "models": [],
        },
    )

    assert len(snapshot["models"]) == 1
    assert snapshot["models"][0]["source"] == "router_anchor"
    assert snapshot["models"][0]["registry_facts"]["roles"] == ["aggregator"]


def test_registry_builder_rejects_malformed_or_duplicate_profile_rows() -> None:
    malformed = {
        "schema_version": "test",
        "snapshot_version": "test-v1",
        "models": ["not-a-model"],
    }
    duplicate = {
        "schema_version": "test",
        "snapshot_version": "test-v1",
        "models": [_model("Vendor/Model"), _model("vendor/model")],
    }

    for snapshot, message in (
        (malformed, "row 0 must be an object"),
        (duplicate, "duplicate model identities"),
    ):
        with pytest.raises(DynamicRankingError, match=message):
            build_model_registry_snapshot(
                inherited_provider="test-provider",
                inherited_model="anchor",
                routed_tier="c1",
                packaged_snapshot=snapshot,
            )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("price", -1.0, "negative price"),
        ("latency", -1, "invalid latency bounds"),
        ("strength", 1.1, "out-of-range capability_dist_prior.reasoning"),
    ],
)
def test_ranking_rejects_malformed_numeric_model_profiles(
    field: str,
    value: float,
    message: str,
) -> None:
    model = _model("malformed")
    if field == "price":
        model["registry_facts"]["price"]["output_per_million"] = value
    elif field == "latency":
        model["registry_facts"]["latency_p95_ms"] = value
    else:
        model["static_profile"]["capability_dist_prior"]["reasoning"] = value

    with pytest.raises(DynamicRankingError, match=message):
        _decision(model, analysis=_analysis(tier=1))


class _AnalyzerProvider:
    provider_name = "analyzer-test"

    def __init__(self, response: str, *, include_done: bool = True) -> None:
        self.response = response
        self.include_done = include_done
        self.calls: list[tuple[list[Message], ChatConfig | None]] = []

    async def _stream(self) -> AsyncIterator[Any]:
        yield TextDeltaEvent(text=self.response)
        if self.include_done:
            yield DoneEvent(
                model="analyzer-test",
                input_tokens=11,
                output_tokens=7,
                billed_cost=0.012,
                cost_source="provider_billed",
                provider_usage={
                    "is_byok": False,
                    "provider_reported_cost": 0.012,
                    "response_ids": ["analyzer-1"],
                    "router_metadata": {"is_byok": False},
                },
            )

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        self.calls.append((messages, config))
        return self._stream()

    async def list_models(self) -> list[Any]:
        return []


@pytest.mark.asyncio
async def test_task_analyzer_uses_provider_interface_and_validates_json() -> None:
    expected = _task_profile(tier=2)
    provider = _AnalyzerProvider(f"```json\n{json.dumps(expected)}\n```")

    class _UsageTracker:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        def add(self, session_key: str, **kwargs: Any) -> None:
            self.calls.append((session_key, kwargs))

    usage_tracker = _UsageTracker()

    result = await analyze_task_with_provider(
        provider=provider,
        message="implement a parser",
        user_profile_enabled=True,
        request_context=_context(),
        routed_tier="c1",
        routing_confidence=0.8,
        usage_tracker=usage_tracker,
        session_key="agent:main:test",
        analyzer_provider_id=TASK_ANALYZER_PROVIDER_ID,
        analyzer_model_id=TASK_ANALYZER_MODEL_ID,
    )

    assert result.source == "llm_provider"
    assert result.schema_valid is True
    assert result.profile["tier_dist"] == {"2": 1.0}
    assert len(provider.calls) == 1
    assert provider.calls[0][1] is not None
    assert provider.calls[0][1].temperature == 0.0
    assert '"modality":["<allowed modality>"]' in provider.calls[0][1].system
    assert '"session_intent":{"type":"<allowed intent>"' in provider.calls[0][1].system
    assert "research is a domain, not a capability" in provider.calls[0][1].system
    assert result.usage["input_tokens"] == 11
    assert result.usage["billed_cost"] == pytest.approx(0.012)
    assert result.provider_id == TASK_ANALYZER_PROVIDER_ID
    assert result.model_id == TASK_ANALYZER_MODEL_ID
    assert result.trace()["provider"] == TASK_ANALYZER_PROVIDER_ID
    assert result.trace()["model"] == TASK_ANALYZER_MODEL_ID
    assert usage_tracker.calls[0][0] == "agent:main:test"
    assert usage_tracker.calls[0][1]["output_tokens"] == 7
    analyzer_payload = json.loads(str(provider.calls[0][0][0].content))
    assert analyzer_payload["allowed_constraints"]["risk"] == ["low", "medium", "high"]
    assert analyzer_payload["allowed_session_intents"] == ["new_task", "continue", "redo"]
    # The profile never reaches the analyzer provider, even when one is supplied.
    assert "user_profile" not in analyzer_payload


@pytest.mark.asyncio
async def test_task_analyzer_uses_durable_accounting_and_retains_provider_evidence() -> None:
    class _Sink:
        def __init__(self) -> None:
            self.started: list[Any] = []
            self.finalized: list[tuple[Any, Any]] = []
            self.unknown: list[tuple[Any, str]] = []

        async def start(self, call: Any) -> None:
            self.started.append(call)

        async def finalize(self, call: Any, result: Any) -> None:
            self.finalized.append((call, result))

        async def mark_unknown(self, call: Any, reason: str) -> None:
            self.unknown.append((call, reason))

    sink = _Sink()
    scope = UsageAccountingScope(
        sink=sink,
        context=UsageExecutionContext(
            execution_id="routing-decision-1",
            agent_run_id="routing-decision-1",
            turn_id="turn-1",
            session_id="session-1",
            agent_id="main",
            run_kind="routing",
        ),
    )
    provider = _AnalyzerProvider(json.dumps(_task_profile(tier=2)))

    with bind_usage_accounting_scope(scope):
        result = await analyze_task_with_provider(
            provider=provider,
            message="implement a parser",
            user_profile_enabled=False,
            request_context=_context(),
            routed_tier="c1",
            routing_confidence=0.8,
            analyzer_provider_id=TASK_ANALYZER_PROVIDER_ID,
            analyzer_model_id=TASK_ANALYZER_MODEL_ID,
        )

    assert len(sink.started) == 1
    assert len(sink.finalized) == 1
    assert sink.unknown == []
    assert sink.started[0].provider == TASK_ANALYZER_PROVIDER_ID
    assert sink.finalized[0][1].cost_source == "provider_billed"
    assert result.usage["provider_usage"]["is_byok"] is False
    assert result.usage["provider_usage"]["response_ids"] == ["analyzer-1"]


@pytest.mark.asyncio
async def test_task_analyzer_omits_user_profile_and_correlates_logs() -> None:
    provider = _AnalyzerProvider(json.dumps(_task_profile(tier=2)))

    with structlog.testing.capture_logs() as captured:
        result = await analyze_task_with_provider(
            provider=provider,
            message="implement a parser",
            user_profile_enabled=False,
            request_context=_context(),
            routed_tier="c1",
            routing_confidence=0.8,
            decision_id="decision-without-profile",
        )

    assert result.source == "llm_provider"
    analyzer_payload = json.loads(str(provider.calls[0][0][0].content))
    assert "user_profile" not in analyzer_payload
    analyzer_events = [
        row
        for row in captured
        if str(row["event"]).startswith("llm_ensemble.router_dynamic.task_analyzer_")
    ]
    assert [row["event"] for row in analyzer_events] == [
        "llm_ensemble.router_dynamic.task_analyzer_started",
        "llm_ensemble.router_dynamic.task_analyzer_completed",
    ]
    assert all(
        row["decision_id"] == "decision-without-profile"
        for row in analyzer_events
    )
    assert all(row["user_profile_enabled"] is False for row in analyzer_events)


@pytest.mark.asyncio
async def test_task_analyzer_logs_profile_enabled_without_receiving_profile() -> None:
    provider = _AnalyzerProvider(json.dumps(_task_profile(tier=2)))

    with structlog.testing.capture_logs() as captured:
        await analyze_task_with_provider(
            provider=provider,
            message="implement a parser",
            user_profile_enabled=True,
            request_context=_context(),
            routed_tier="c1",
            routing_confidence=0.8,
            decision_id="decision-with-profile",
        )

    assert "user_profile" not in json.loads(str(provider.calls[0][0][0].content))
    analyzer_events = [
        row
        for row in captured
        if str(row["event"]).startswith("llm_ensemble.router_dynamic.task_analyzer_")
    ]
    assert analyzer_events
    assert all(row["user_profile_enabled"] is True for row in analyzer_events)


@pytest.mark.asyncio
async def test_task_analyzer_chat_parameters_are_loaded_from_ranking_config() -> None:
    config = load_ranking_config()
    config["task_analyzer"]["max_output_tokens"] = 321
    config["task_analyzer"]["temperature"] = 0.2
    config["task_analyzer"]["thinking"] = True
    config["task_analyzer"]["timeout_seconds"] = 7.5
    config["task_analyzer"]["input_max_chars"] = 80
    provider = _AnalyzerProvider(json.dumps(_task_profile(tier=2)))

    result = await analyze_task_with_provider(
        provider=provider,
        message="implement a parser " * 100,
        user_profile_enabled=True,
        request_context=_context(),
        routed_tier="c1",
        routing_confidence=0.8,
        ranking_config=config,
    )

    chat_config = provider.calls[0][1]
    assert result.source == "llm_provider"
    assert chat_config is not None
    assert chat_config.max_tokens == 321
    assert chat_config.temperature == 0.2
    assert chat_config.thinking is True
    assert chat_config.timeout == 7.5
    analyzer_payload = json.loads(str(provider.calls[0][0][0].content))
    assert len(analyzer_payload["task"]) == 80
    assert "truncated for classification" in analyzer_payload["task"]


@pytest.mark.asyncio
async def test_task_analyzer_incomplete_stream_falls_back_even_with_valid_json() -> None:
    result = await analyze_task_with_provider(
        provider=_AnalyzerProvider(json.dumps(_task_profile(tier=2)), include_done=False),
        message="hello",
        user_profile_enabled=True,
        request_context=_context(),
        routed_tier="c2",
        routing_confidence=0.77,
    )

    assert result.source == "router_fallback"
    assert result.schema_valid is False
    assert result.fallback_reason == "RuntimeError"


@pytest.mark.asyncio
async def test_task_analyzer_malformed_output_falls_back_to_tree_router_profile() -> None:
    result = await analyze_task_with_provider(
        provider=_AnalyzerProvider("not-json"),
        message="hello",
        user_profile_enabled=True,
        request_context=_context(),
        routed_tier="c2",
        routing_confidence=0.77,
    )

    assert result.source == "router_fallback"
    assert result.schema_valid is False
    assert result.profile["tier_dist"] == {"3": 1.0}
    assert result.confidence == pytest.approx(0.77)


@pytest.mark.asyncio
async def test_task_analyzer_invalid_required_constraint_uses_fallback() -> None:
    malformed = _task_profile(tier=2)
    malformed["constraints"]["risk"] = "catastrophic"

    result = await analyze_task_with_provider(
        provider=_AnalyzerProvider(json.dumps(malformed)),
        message="hello",
        user_profile_enabled=True,
        request_context=_context(),
        routed_tier="c2",
        routing_confidence=0.77,
    )

    assert result.source == "router_fallback"
    assert result.schema_valid is False
    assert result.profile["tier_dist"] == {"3": 1.0}


@pytest.mark.asyncio
async def test_task_analyzer_drops_invalid_optional_fields_without_full_fallback() -> None:
    profile = _task_profile(tier=2)
    profile["optional_constraints"] = {"format": "unsupported-format"}
    profile["analysis_confidence"] = "high"

    result = await analyze_task_with_provider(
        provider=_AnalyzerProvider(json.dumps(profile)),
        message="hello",
        user_profile_enabled=True,
        request_context=_context(),
        routed_tier="c1",
        routing_confidence=0.77,
    )

    assert result.source == "llm_provider"
    assert result.schema_valid is True
    assert result.profile["optional_constraints"] == {}
    assert result.confidence == pytest.approx(0.80)
    assert result.normalization_warnings == (
        "invalid_optional_format",
        "invalid_analysis_confidence",
    )
    assert result.trace()["normalization_warnings"] == [
        "invalid_optional_format",
        "invalid_analysis_confidence",
    ]


@pytest.mark.asyncio
async def test_task_analyzer_cannot_drop_an_actual_input_modality() -> None:
    incomplete = _task_profile(tier=2, modalities=["text"])
    request_context = _context()
    request_context["input_modalities"] = ["text", "image"]

    result = await analyze_task_with_provider(
        provider=_AnalyzerProvider(json.dumps(incomplete)),
        message="review the attached diagram",
        user_profile_enabled=True,
        request_context=request_context,
        routed_tier="c2",
        routing_confidence=0.77,
    )

    assert result.source == "router_fallback"
    assert result.profile["constraints"]["modality"] == ["text", "image"]


def test_hard_filter_records_availability_permission_modality_and_context_reasons() -> None:
    eligible = _model("eligible", roles=["proposer", "aggregator"], modalities=["text", "image"])
    unavailable = _model("unavailable", credential_available=False, modalities=["text", "image"])
    denied = _model("denied", modalities=["text", "image"])
    text_only = _model("text-only", modalities=["text"])
    short_context = _model("short-context", context_window=1_500, modalities=["image"])
    user = mock_user_profile()
    user["permission"]["deny_models"] = ["denied"]

    decision = _decision(
        eligible,
        unavailable,
        denied,
        text_only,
        short_context,
        analysis=_analysis(tier=1, modalities=["image"]),
        context=_context(input_tokens=1_000, candidate_tokens=1_000),
        user_profile=user,
    )
    by_model = {row["model"]: row for row in decision.trace["hard_filter"]["proposer_results"]}

    assert "credential_unavailable" in by_model["unavailable"]["reasons"]
    assert "no_permission" in by_model["denied"]["reasons"]
    assert "modality_mismatch" in by_model["text-only"]["reasons"]
    assert "context_exceeded" in by_model["short-context"]["reasons"]
    assert decision.proposers[0].model_id == "eligible"


def _profile_with_history(*, positive: list[str], negative: list[str], count: int) -> dict:
    profile = mock_user_profile()
    profile["history"]["positive_model_ids"] = positive
    profile["history"]["negative_model_ids"] = negative
    profile["history"]["feedback_count"] = count
    return profile


def test_history_reorders_candidates_that_task_match_alone_would_not() -> None:
    """The regression that matters: history must be able to change the order.

    With an empty history every model gets the same neutral S_user, so the
    0.15 * S_user term is a uniform offset and cannot reorder anything — the
    profile is inert rather than approximate. A saturated history splits
    S_user across models and the weaker-but-liked model wins.
    """
    liked = _model("liked", capability=0.80, aggregator_fit=0.80)
    disliked = _model("disliked", capability=0.85, aggregator_fit=0.85)

    neutral = _decision(liked, disliked, analysis=_analysis(tier=2))
    assert [m.model_id for m in neutral.proposers][0] == "disliked"

    opinionated = _decision(
        liked,
        disliked,
        analysis=_analysis(tier=2),
        user_profile=_profile_with_history(
            positive=["liked"], negative=["disliked"], count=20
        ),
    )
    assert [m.model_id for m in opinionated.proposers][0] == "liked"


def test_history_confidence_ramps_in_with_feedback_count() -> None:
    """One click must not swing the ranking to an extreme.

    confidence = min(1, feedback_count / 20), so a single rating moves S_user
    by 1/20th of the full signal — not enough to overturn a task-match gap
    that a saturated history does overturn.
    """
    liked = _model("liked", capability=0.80, aggregator_fit=0.80)
    disliked = _model("disliked", capability=0.85, aggregator_fit=0.85)

    barely = _decision(
        liked,
        disliked,
        analysis=_analysis(tier=2),
        user_profile=_profile_with_history(
            positive=["liked"], negative=["disliked"], count=1
        ),
    )
    assert [m.model_id for m in barely.proposers][0] == "disliked"


def test_ranking_without_user_profile_bypasses_all_profile_effects() -> None:
    preferred = _model("preferred", capability=0.95, aggregator_fit=0.95)
    backup = _model("backup", capability=0.80, aggregator_fit=0.80)
    contrast = _model("contrast", capability=0.70, aggregator_fit=0.70)
    profile = mock_user_profile()
    profile["permission"]["deny_models"] = ["preferred"]
    profile["permission"]["risk_allowlist"] = ["medium"]
    profile["preference"]["cost_sensitivity"] = "hard_limit"
    profile["preference"]["quality_latency_tradeoff"] = "latency_first"

    enabled = _decision(
        preferred,
        backup,
        contrast,
        analysis=_analysis(tier=3, risk="medium"),
        user_profile=profile,
    )
    risk_blocked_profile = mock_user_profile()
    risk_blocked_profile["permission"]["risk_allowlist"] = ["low"]
    with pytest.raises(DynamicRankingError, match="no proposer"):
        _decision(
            preferred,
            backup,
            contrast,
            analysis=_analysis(tier=3, risk="medium"),
            user_profile=risk_blocked_profile,
        )
    disabled = rank_models(
        task_analysis=_analysis(tier=3, risk="medium"),
        user_profile=None,
        request_context=_context(),
        registry_snapshot=_snapshot(preferred, backup, contrast),
        routed_tier="c2",
        routing_confidence=0.9,
        decision_id="ranking-without-profile",
    )

    assert enabled.trace["user_profile_enabled"] is True
    assert enabled.trace["N_max"] == 2
    assert disabled.trace["decision_id"] == "ranking-without-profile"
    assert disabled.trace["user_profile_enabled"] is False
    assert disabled.trace["user_profile_version"] == ""
    assert disabled.trace["user_profile_source"] == ""
    assert disabled.trace["N_max"] == 3
    disabled_filters = [
        *disabled.trace["hard_filter"]["proposer_results"],
        *disabled.trace["hard_filter"]["aggregator_results"],
    ]
    assert all("no_permission" not in row["reasons"] for row in disabled_filters)
    assert all("risk_not_allowed" not in row["reasons"] for row in disabled_filters)
    assert {row["model"] for row in disabled.trace["model_scores"]} == {
        "preferred",
        "backup",
        "contrast",
    }
    for row in disabled.trace["model_scores"]:
        assert row["S_user"] == 0.0
        assert row["S_qual_clean"] == row["S_match"]
        assert row["cost_weight"] == pytest.approx(0.10)
        assert row["latency_weight"] == pytest.approx(0.08)


def test_availability_filter_covers_registry_health_quota_rate_and_role() -> None:
    healthy = _model("healthy")
    disabled = _model("disabled", status="disabled")
    unhealthy = _model("unhealthy", health="unavailable")
    no_quota = _model("no-quota")
    no_quota["registry_facts"]["quota"] = 0
    limited = _model("limited")
    limited["registry_facts"]["rate_limit"] = "limited"
    aggregator_only = _model("aggregator-only", roles=["aggregator"])

    decision = _decision(
        healthy,
        disabled,
        unhealthy,
        no_quota,
        limited,
        aggregator_only,
        analysis=_analysis(tier=1),
    )
    by_model = {row["model"]: row for row in decision.trace["hard_filter"]["proposer_results"]}

    assert "status_unavailable" in by_model["disabled"]["reasons"]
    assert "health_unavailable" in by_model["unhealthy"]["reasons"]
    assert "quota_exhausted" in by_model["no-quota"]["reasons"]
    assert "rate_limited" in by_model["limited"]["reasons"]
    assert "role_proposer_unsupported" in by_model["aggregator-only"]["reasons"]


def test_hard_filter_availability_states_are_config_driven() -> None:
    config = load_ranking_config()
    config["hard_filter"]["eligible_statuses"].append("maintenance")

    decision = _decision(
        _model("maintenance-model", status="maintenance"),
        analysis=_analysis(tier=1),
        ranking_config=config,
    )

    assert decision.proposers[0].model_id == "maintenance-model"


def test_user_risk_permission_is_a_hard_filter() -> None:
    user = mock_user_profile()
    user["permission"]["risk_allowlist"] = ["low", "medium"]

    with pytest.raises(DynamicRankingError, match="no proposer"):
        _decision(
            _model("eligible-by-model"),
            analysis=_analysis(tier=4, risk="high"),
            user_profile=user,
        )


def test_greedy_selection_prefers_cross_family_complement_over_duplicate_family() -> None:
    primary = _model(
        "primary",
        provider="openrouter",
        vendor="vendor-a",
        family="family-a",
        capability=0.88,
    )
    duplicate = _model(
        "duplicate",
        provider="openrouter",
        vendor="vendor-a",
        family="family-a",
        capability=0.87,
    )
    complement = _model(
        "complement",
        provider="openrouter",
        vendor="vendor-b",
        family="family-b",
        capability=0.86,
    )

    decision = _decision(
        primary,
        duplicate,
        complement,
        analysis=_analysis(tier=3, latency="interactive"),
    )

    assert decision.trace["N_min"] == 2
    assert decision.trace["N_max"] == 2
    assert [model.model_id for model in decision.proposers] == ["primary", "complement"]
    assert decision.trace["selection_steps"][1]["max_similarity"] < 0.75
    assert [row["proposer_count"] for row in decision.trace["aggregator_feasibility"]] == [1, 2]
    assert all(row["eligible_aggregator_ids"] for row in decision.trace["aggregator_feasibility"])
    assert decision.trace["selection_steps"][0]["eligible_aggregator_count"] == 3


def test_rerank_trace_records_quality_floor_exclusions_and_stop_detail() -> None:
    strong = _model("strong", capability=0.90)
    weak = _model("weak", provider="provider-b", capability=0.10)

    decision = _decision(
        strong,
        weak,
        analysis=_analysis(tier=2, risk="low"),
    )

    assert [model.model_id for model in decision.proposers] == ["strong"]
    assert decision.trace["quality_floor_excluded_ids"] == ["provider-b:weak"]
    assert decision.trace["stop_reason"] == "quality_floor_or_pool_exhausted"
    assert decision.trace["stop_detail"] == {
        "quality_floor_excluded_count": 1,
        "remaining_candidate_count": 0,
    }


def test_aggregator_feasibility_filters_once_per_prospective_set_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    models = tuple(
        _model(
            f"model-{index}",
            provider=f"provider-{index}",
            family=f"family-{index}",
        )
        for index in range(4)
    )
    original = ranking_router._hard_filter_reasons
    aggregator_filter_calls = 0

    def counted_hard_filter(*args: Any, **kwargs: Any):
        nonlocal aggregator_filter_calls
        if kwargs.get("role") == "aggregator":
            aggregator_filter_calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(ranking_router, "_hard_filter_reasons", counted_hard_filter)

    decision = _decision(*models, analysis=_analysis(tier=3))

    prospective_counts = len(decision.trace["aggregator_feasibility"])
    assert prospective_counts == len(decision.proposers)
    assert aggregator_filter_calls == len(models) * (prospective_counts + 1)


def test_rerank_weights_from_json_change_the_selected_proposer_set() -> None:
    primary = _model(
        "primary",
        provider="openrouter",
        vendor="vendor-a",
        family="family-a",
        capability=0.88,
    )
    duplicate = _model(
        "duplicate",
        provider="openrouter",
        vendor="vendor-a",
        family="family-a",
        capability=0.87,
    )
    complement = _model(
        "complement",
        provider="openrouter",
        vendor="vendor-b",
        family="family-b",
        capability=0.86,
    )
    config = load_ranking_config()
    config["config_version"] = "test-no-similarity-penalty-v1"
    config["rerank"]["similarity_penalty_weight"] = 0.0

    decision = _decision(
        primary,
        duplicate,
        complement,
        analysis=_analysis(tier=3, latency="interactive"),
        ranking_config=config,
    )

    assert [model.model_id for model in decision.proposers] == ["primary", "duplicate"]
    assert decision.trace["ranking_config_version"] == config["config_version"]
    assert decision.trace["ranking_parameters"] == config
    assert len(decision.trace["ranking_config_hash"]) == 64


def test_cost_and_latency_break_quality_ties_in_proposer_selection() -> None:
    expensive = _model(
        "a-expensive",
        capability=0.82,
        price=40.0,
        latency_ms=30_000,
    )
    efficient = _model(
        "z-efficient",
        provider="provider-b",
        capability=0.82,
        price=0.1,
        latency_ms=1_000,
    )

    decision = _decision(
        expensive,
        efficient,
        analysis=_analysis(tier=1, cost="low", latency="interactive"),
    )

    assert decision.proposers[0].model_id == "z-efficient"
    efficient_score = next(
        row for row in decision.trace["model_scores"] if row["model"] == "z-efficient"
    )
    expensive_score = next(
        row for row in decision.trace["model_scores"] if row["model"] == "a-expensive"
    )
    assert efficient_score["S_base_clean"] > expensive_score["S_base_clean"]


def test_aggregator_is_ranked_after_proposers_with_full_context_need() -> None:
    proposer_a = _model("proposer-a", roles=["proposer"], capability=0.9)
    proposer_b = _model(
        "proposer-b",
        provider="provider-b",
        family="family-b",
        roles=["proposer"],
        capability=0.88,
    )
    short_aggregator = _model(
        "short-aggregator",
        roles=["aggregator"],
        context_window=4_500,
        capability=0.98,
        aggregator_fit=0.99,
    )
    long_aggregator = _model(
        "long-aggregator",
        roles=["aggregator"],
        context_window=20_000,
        capability=0.80,
        aggregator_fit=0.85,
    )

    decision = _decision(
        proposer_a,
        proposer_b,
        short_aggregator,
        long_aggregator,
        analysis=_analysis(tier=3, latency="interactive"),
        context=_context(input_tokens=1_000, candidate_tokens=2_000, aggregator_tokens=1_000),
    )

    assert len(decision.proposers) == 2
    assert decision.aggregator.model_id == "long-aggregator"
    short_filter = next(
        row
        for row in decision.trace["hard_filter"]["aggregator_results"]
        if row["model"] == "short-aggregator"
    )
    assert short_filter["context_need_tokens"] == 6_000
    assert "context_exceeded" in short_filter["reasons"]


def test_continue_applies_weak_stickiness_between_near_equal_models() -> None:
    first = _model("first", capability=0.80)
    previous = _model("previous", provider="provider-b", capability=0.79)
    context = _context(
        last_route={
            "selected_P": ["previous"],
            "selected_A": "previous",
            "quality_feedback": 1.0,
            "escalation_level": 0,
        }
    )

    decision = _decision(
        first,
        previous,
        analysis=_analysis(tier=1, intent="continue"),
        context=context,
    )

    assert decision.proposers[0].model_id == "previous"
    assert decision.trace["session"]["sticky_applied"] is True
    previous_score = next(
        row for row in decision.trace["model_scores"] if row["model"] == "previous"
    )
    assert previous_score["S_session"] == pytest.approx(0.1)


def test_low_confidence_continue_does_not_apply_stickiness() -> None:
    previous = _model("previous", capability=0.79)
    stronger = _model("stronger", provider="provider-b", capability=0.80)
    context = _context(
        last_route={
            "selected_P": ["previous"],
            "selected_A": "previous",
            "quality_feedback": 1.0,
            "escalation_level": 0,
        }
    )

    decision = _decision(
        previous,
        stronger,
        analysis=_analysis(tier=1, intent="continue", intent_confidence=0.4),
        context=context,
    )

    assert decision.proposers[0].model_id == "stronger"
    assert decision.trace["session"]["intent"] == "new_task"
    assert decision.trace["session"]["sticky_applied"] is False


def test_continue_without_a_previous_route_is_treated_as_a_new_task() -> None:
    decision = _decision(
        _model("first"),
        _model("second", provider="provider-b"),
        analysis=_analysis(tier=1, intent="continue"),
        context=_context(),
    )

    assert decision.trace["session"]["intent"] == "new_task"
    assert decision.trace["session"]["sticky_applied"] is False


def test_continue_does_not_claim_stickiness_when_previous_models_are_ineligible() -> None:
    context = _context(
        last_route={
            "selected_P": ["unavailable"],
            "selected_A": "unavailable",
            "quality_feedback": 1.0,
            "escalation_level": 0,
        }
    )

    decision = _decision(
        _model("available"),
        _model("unavailable", provider="provider-b", credential_available=False),
        analysis=_analysis(tier=1, intent="continue"),
        context=context,
    )

    assert decision.trace["session"]["intent"] == "continue"
    assert decision.trace["session"]["sticky_applied"] is False
    assert decision.trace["session"]["adjusted_model_ids"] == []


def test_session_adjustment_applies_to_aggregator_selection() -> None:
    proposer = _model("proposer", roles=["proposer"], capability=0.90)
    previous = _model(
        "previous-aggregator",
        provider="provider-b",
        roles=["aggregator"],
        capability=0.80,
        aggregator_fit=0.80,
    )
    alternative = _model(
        "alternative-aggregator",
        provider="provider-c",
        roles=["aggregator"],
        capability=0.82,
        aggregator_fit=0.82,
    )
    context = _context(
        last_route={
            "selected_P": ["proposer"],
            "selected_A": "previous-aggregator",
            "quality_feedback": 1.0,
            "escalation_level": 0,
        }
    )

    continued = _decision(
        proposer,
        previous,
        alternative,
        analysis=_analysis(tier=1, intent="continue"),
        context=context,
    )
    redone = _decision(
        proposer,
        previous,
        alternative,
        analysis=_analysis(tier=1, intent="redo"),
        context=context,
    )

    assert continued.aggregator.model_id == "previous-aggregator"
    continued_score = next(
        row
        for row in continued.trace["aggregator"]["scores"]
        if row["model"] == "previous-aggregator"
    )
    assert continued_score["S_session"] == pytest.approx(0.1)
    assert redone.aggregator.model_id == "alternative-aggregator"


def test_redo_demotes_previous_models_and_shifts_tier_once() -> None:
    previous = _model("previous", capability=0.86)
    alternative = _model("alternative", provider="provider-b", capability=0.84)
    context = _context(
        last_route={
            "selected_P": ["previous"],
            "selected_A": "previous",
            "quality_feedback": 0.2,
            "escalation_level": 0,
        }
    )

    decision = _decision(
        previous,
        alternative,
        analysis=_analysis(tier=2, intent="redo"),
        context=context,
    )

    assert decision.effective_tier == 3
    assert decision.trace["session"]["tier_shifted"] is True
    assert decision.trace["session"]["escalation_level"] == 1
    assert decision.trace["task_profile_pre_escalation"]["tier_dist"] == {"2": 1.0}
    assert decision.trace["task_profile_post_escalation"]["tier_dist"] == {"3": 1.0}
    previous_score = next(
        row for row in decision.trace["model_scores"] if row["model"] == "previous"
    )
    assert previous_score["S_session"] == pytest.approx(-0.1)
    assert decision.proposers[0].model_id == "alternative"


def test_redo_stops_escalating_at_the_configured_ceiling() -> None:
    context = _context(
        last_route={
            "selected_P": ["previous"],
            "selected_A": "previous",
            "quality_feedback": 0.1,
            "escalation_level": 2,
        }
    )

    decision = _decision(
        _model("previous"),
        _model("alternative", provider="provider-b"),
        analysis=_analysis(tier=3, intent="redo"),
        context=context,
    )

    assert decision.effective_tier == 3
    assert decision.trace["session"]["tier_shifted"] is False
    assert decision.trace["session"]["escalation_level"] == 2


def test_high_risk_shortfall_is_recorded_without_violating_filters() -> None:
    decision = _decision(
        _model("one", provider="provider-a"),
        _model("two", provider="provider-b"),
        analysis=_analysis(tier=4, risk="high"),
    )

    assert decision.trace["N_min"] == 4
    assert len(decision.proposers) == 2
    assert decision.trace["coverage_shortfall"] is True
    assert decision.trace["stop_reason"] == "candidate_pool_exhausted"


def test_no_feasible_aggregator_fails_with_explicit_error() -> None:
    with pytest.raises(DynamicRankingError, match="feasible aggregator"):
        _decision(
            _model("proposer", roles=["proposer"]),
            analysis=_analysis(tier=1),
        )


def test_duplicate_registry_identity_is_rejected_before_scoring() -> None:
    duplicate = _model("Vendor/Duplicate")
    duplicate_case_variant = _model("vendor/duplicate")

    with pytest.raises(DynamicRankingError, match="duplicate model identities"):
        _decision(duplicate, duplicate_case_variant, analysis=_analysis(tier=1))


def test_malformed_registry_row_is_not_silently_dropped() -> None:
    with pytest.raises(DynamicRankingError, match="malformed model row"):
        rank_models(
            task_analysis=_analysis(tier=1),
            user_profile=mock_user_profile(),
            request_context=_context(),
            registry_snapshot={
                "snapshot_version": "test",
                "models": [_model("valid"), "not-a-model"],
            },
            routed_tier="c0",
            routing_confidence=1.0,
        )


def test_ranking_is_deterministic_for_the_same_snapshot() -> None:
    models = (
        _model("a", provider="provider-a"),
        _model("b", provider="provider-b"),
        _model("c", provider="provider-c"),
    )

    first = _decision(*models, analysis=_analysis(tier=3))
    second = _decision(*models, analysis=_analysis(tier=3))

    assert [model.identity for model in first.proposers] == [
        model.identity for model in second.proposers
    ]
    assert first.aggregator.identity == second.aggregator.identity
    assert first.trace["selection_steps"] == second.trace["selection_steps"]
    assert first.trace["registry_snapshot_hash"] == second.trace["registry_snapshot_hash"]
    assert len(first.trace["registry_snapshot_hash"]) == 64
    assert all(len(row["profile_hash"]) == 64 for row in first.trace["candidate_pool"])


def test_ranking_emits_the_required_debug_lifecycle_events() -> None:
    with structlog.testing.capture_logs() as captured:
        rank_models(
            task_analysis=_analysis(tier=2),
            user_profile=mock_user_profile(),
            request_context=_context(),
            registry_snapshot=_snapshot(
                _model("a", provider="provider-a"),
                _model("b", provider="provider-b"),
            ),
            routed_tier="c1",
            routing_confidence=0.9,
            decision_id="ranking-log-decision",
        )

    event_names = {row["event"] for row in captured}
    assert {
        "llm_ensemble.router_dynamic.candidate_pool_recorded",
        "llm_ensemble.router_dynamic.model_scores_recorded",
        "llm_ensemble.router_dynamic.proposer_selection_recorded",
        "llm_ensemble.router_dynamic.aggregator_selection_recorded",
        "llm_ensemble.router_dynamic.router_decision_recorded",
    }.issubset(event_names)
    lifecycle = [
        row
        for row in captured
        if str(row["event"]).startswith("llm_ensemble.router_dynamic.")
    ]
    assert all(row["decision_id"] == "ranking-log-decision" for row in lifecycle)
