from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from typing import Any

import pytest
import structlog.testing

from opensquilla.engine.runtime import TurnRunner
from opensquilla.gateway.config import GatewayConfig, SquillaRouterConfig
from opensquilla.provider import ChatConfig, EnsembleProvider, Message
from opensquilla.provider.ranking_router import (
    TASK_ANALYZER_MODEL_ID,
    TASK_ANALYZER_PROVIDER_ID,
    DynamicRankingError,
    TaskAnalysisResult,
    fallback_task_profile,
)
from opensquilla.provider.selector import ProviderConfig
from opensquilla.provider.tree_baseline_router import TreeBaselineError


class _Provider:
    provider_name = "fake"

    def chat(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        raise AssertionError("credential-guard tests must not start provider chat")

    async def list_models(self) -> list[Any]:
        return []


class _FakeSelector:
    def __init__(self, *, provider: str, api_key: str) -> None:
        self._cfg = ProviderConfig(
            provider=provider,
            model="base-model",
            api_key=api_key,
            base_url="https://example.invalid/api",
        )

    @property
    def current_config(self) -> ProviderConfig:
        return self._cfg

    def override_model(self, model: str) -> None:
        self._cfg = ProviderConfig(
            provider=self._cfg.provider,
            model=model,
            api_key=self._cfg.api_key,
            base_url=self._cfg.base_url,
            proxy=self._cfg.proxy,
            provider_routing=self._cfg.provider_routing,
        )

    def resolve(self) -> _Provider:
        return _Provider()


def _static_b5_config(**ensemble_overrides: Any) -> GatewayConfig:
    return GatewayConfig(
        squilla_router=SquillaRouterConfig(enabled=False),
        llm_ensemble={"enabled": True, **ensemble_overrides},
    )


async def test_static_b5_tracks_missing_openrouter_credential_per_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    runner = TurnRunner(provider_selector=None, config=_static_b5_config())
    selector = _FakeSelector(provider="groq", api_key="sk-groq-synthetic")
    single_provider = _Provider()

    with structlog.testing.capture_logs() as captured:
        turn, provider = await runner._run_pipeline(
            "hello",
            "agent:main:test",
            single_provider,
            selector,
            [],
            "system prompt",
            [],
        )

    assert isinstance(provider, EnsembleProvider)
    assert all(not member.ready for member in [*provider.proposers, provider.aggregator])
    assert all(
        member.unavailable_reason == "missing_credential"
        for member in [*provider.proposers, provider.aggregator]
    )
    assert turn.metadata["ensemble_enabled"] is True
    assert "ensemble_wrap_skipped_reason" not in turn.metadata
    decision_id = turn.metadata["ensemble_decision_id"]
    routing_events = [
        row
        for row in captured
        if str(row["event"]).startswith("llm_ensemble.routing.")
    ]
    assert routing_events[0]["event"] == "llm_ensemble.routing.decision_started"
    assert routing_events[-1]["event"] == "llm_ensemble.routing.decision_completed"
    assert not any(
        row["event"] == "llm_ensemble.routing.decision_skipped"
        for row in routing_events
    )
    assert all(row["decision_id"] == decision_id for row in routing_events)
    assert [row["sequence"] for row in routing_events] == list(
        range(len(routing_events))
    )


async def test_static_b5_wraps_when_openrouter_env_key_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-synthetic")
    runner = TurnRunner(provider_selector=None, config=_static_b5_config())
    selector = _FakeSelector(provider="groq", api_key="sk-groq-synthetic")

    turn, provider = await runner._run_pipeline(
        "hello",
        "agent:main:test",
        _Provider(),
        selector,
        [],
        "system prompt",
        [],
    )

    assert isinstance(provider, EnsembleProvider)
    assert turn.metadata["ensemble_enabled"] is True
    assert "ensemble_wrap_skipped_reason" not in turn.metadata


async def test_static_b5_wraps_when_active_provider_is_keyed_openrouter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    runner = TurnRunner(provider_selector=None, config=_static_b5_config())
    selector = _FakeSelector(provider="openrouter", api_key="sk-or-synthetic")

    turn, provider = await runner._run_pipeline(
        "hello",
        "agent:main:test",
        _Provider(),
        selector,
        [],
        "system prompt",
        [],
    )

    assert isinstance(provider, EnsembleProvider)
    assert turn.metadata["ensemble_enabled"] is True
    assert "ensemble_wrap_skipped_reason" not in turn.metadata


async def test_static_tokenrhythm_b5_tracks_missing_credential_per_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TOKENRHYTHM_API_KEY", raising=False)
    # An OpenRouter key must not unlock the tokenrhythm profile.
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-synthetic")
    runner = TurnRunner(
        provider_selector=None,
        config=_static_b5_config(selection_mode="static_tokenrhythm_b5"),
    )
    selector = _FakeSelector(provider="groq", api_key="sk-groq-synthetic")

    turn, provider = await runner._run_pipeline(
        "hello",
        "agent:main:test",
        _Provider(),
        selector,
        [],
        "system prompt",
        [],
    )

    assert isinstance(provider, EnsembleProvider)
    assert all(not member.ready for member in [*provider.proposers, provider.aggregator])
    assert all(
        member.unavailable_reason == "missing_credential"
        for member in [*provider.proposers, provider.aggregator]
    )
    assert turn.metadata["ensemble_enabled"] is True
    assert "ensemble_wrap_skipped_reason" not in turn.metadata


async def test_static_tokenrhythm_b5_wraps_when_active_provider_is_keyed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TOKENRHYTHM_API_KEY", raising=False)
    runner = TurnRunner(
        provider_selector=None,
        config=_static_b5_config(selection_mode="static_tokenrhythm_b5"),
    )
    selector = _FakeSelector(provider="tokenrhythm", api_key="sk-tr-synthetic")

    turn, provider = await runner._run_pipeline(
        "hello",
        "agent:main:test",
        _Provider(),
        selector,
        [],
        "system prompt",
        [],
    )

    assert isinstance(provider, EnsembleProvider)
    assert turn.metadata["ensemble_enabled"] is True
    assert "ensemble_wrap_skipped_reason" not in turn.metadata


async def test_router_dynamic_wrap_is_not_credential_gated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    runner = TurnRunner(
        provider_selector=None,
        config=_static_b5_config(selection_mode="router_dynamic"),
    )
    selector = _FakeSelector(provider="groq", api_key="sk-groq-synthetic")

    turn, provider = await runner._run_pipeline(
        "hello",
        "agent:main:test",
        _Provider(),
        selector,
        [],
        "system prompt",
        [],
    )

    assert isinstance(provider, EnsembleProvider)
    assert turn.metadata["ensemble_enabled"] is True
    assert "ensemble_wrap_skipped_reason" not in turn.metadata
    assert turn.metadata["router_dynamic_task_analyzer"]["source"] == "router_fallback"
    assert turn.metadata["router_dynamic_task_analyzer"]["schema_valid"] is False
    assert turn.metadata["router_dynamic_task_analyzer"]["provider"] == (
        TASK_ANALYZER_PROVIDER_ID
    )
    assert turn.metadata["router_dynamic_task_analyzer"]["model"] == (
        TASK_ANALYZER_MODEL_ID
    )
    assert turn.metadata["router_dynamic_task_analyzer"]["fallback_reason"] == (
        "provider_unavailable"
    )
    assert turn.metadata["router_dynamic_decision"]["ranking_version"] == "step2-ranking-v2"
    assert len(turn.metadata["router_dynamic_decision"]["registry_snapshot_hash"]) == 64
    assert turn.metadata["router_dynamic_decision"]["selected_P"]
    assert turn.metadata["router_dynamic_decision"]["selected_A"]


async def test_router_dynamic_uses_fixed_opus_task_analyzer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-synthetic")
    fixed_analyzer_provider = object()
    provider_builds: list[ProviderConfig] = []
    analyzer_calls: list[dict[str, Any]] = []

    def fake_resolve(selector: Any) -> object:
        provider_builds.append(selector.current_config)
        return fixed_analyzer_provider

    async def fake_analyze_task_with_provider(**kwargs: Any) -> TaskAnalysisResult:
        analyzer_calls.append(kwargs)
        profile = fallback_task_profile(
            routed_tier=str(kwargs["routed_tier"]),
            request_context=kwargs["request_context"],
        )
        return TaskAnalysisResult(
            profile=profile,
            source="test",
            schema_valid=True,
            confidence=1.0,
            provider_id=str(kwargs["analyzer_provider_id"]),
            model_id=str(kwargs["analyzer_model_id"]),
        )

    monkeypatch.setattr(
        "opensquilla.provider.selector.ModelSelector.resolve",
        fake_resolve,
    )
    monkeypatch.setattr(
        "opensquilla.provider.ranking_router.analyze_task_with_provider",
        fake_analyze_task_with_provider,
    )
    config = _static_b5_config(
        selection_mode="router_dynamic",
        ranking_user_profile_generation_enabled=False,
        ranking_user_profile_enabled=True,
    )
    config.llm.provider_routing = {TASK_ANALYZER_MODEL_ID: "anthropic"}
    runner = TurnRunner(provider_selector=None, config=config)
    selector = _FakeSelector(provider="groq", api_key="sk-groq-synthetic")

    turn, provider = await runner._run_pipeline(
        "analyze with the dedicated model",
        "agent:main:fixed-task-analyzer",
        _Provider(),
        selector,
        [],
        "system prompt",
        [],
    )

    assert isinstance(provider, EnsembleProvider)
    assert len(provider_builds) == 1
    analyzer_config = provider_builds[0]
    assert analyzer_config.provider == TASK_ANALYZER_PROVIDER_ID
    assert analyzer_config.model == TASK_ANALYZER_MODEL_ID
    assert analyzer_config.api_key == "sk-or-synthetic"
    assert analyzer_config.base_url == "https://openrouter.ai/api/v1"
    assert analyzer_config.provider_routing == {
        TASK_ANALYZER_MODEL_ID: "anthropic"
    }
    assert analyzer_config.replay_provider_state is False
    assert len(analyzer_calls) == 1
    assert analyzer_calls[0]["provider"] is fixed_analyzer_provider
    assert analyzer_calls[0]["analyzer_provider_id"] == TASK_ANALYZER_PROVIDER_ID
    assert analyzer_calls[0]["analyzer_model_id"] == TASK_ANALYZER_MODEL_ID
    assert analyzer_calls[0]["user_profile_enabled"] is True
    assert "user_profile" not in analyzer_calls[0]
    assert turn.metadata["routed_model_before_ensemble"] != TASK_ANALYZER_MODEL_ID
    assert turn.metadata["router_dynamic_task_analyzer"]["provider"] == (
        TASK_ANALYZER_PROVIDER_ID
    )
    assert turn.metadata["router_dynamic_task_analyzer"]["model"] == (
        TASK_ANALYZER_MODEL_ID
    )


async def test_router_dynamic_profile_application_defaults_off_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    analyzer_calls: list[dict[str, Any]] = []

    async def fake_analyze_task_with_provider(**kwargs: Any) -> TaskAnalysisResult:
        analyzer_calls.append(kwargs)
        profile = fallback_task_profile(
            routed_tier=str(kwargs["routed_tier"]),
            request_context=kwargs["request_context"],
        )
        return TaskAnalysisResult(
            profile=profile,
            source="test",
            schema_valid=True,
            confidence=1.0,
        )

    monkeypatch.setattr(
        "opensquilla.provider.ranking_router.analyze_task_with_provider",
        fake_analyze_task_with_provider,
    )
    runner = TurnRunner(
        provider_selector=None,
        config=_static_b5_config(
            selection_mode="router_dynamic",
            ranking_user_profile_generation_enabled=True,
        ),
    )
    selector = _FakeSelector(provider="groq", api_key="sk-groq-synthetic")

    with structlog.testing.capture_logs() as captured:
        turn, provider = await runner._run_pipeline(
            "route without a user profile",
            "agent:main:no-ranking-profile",
            _Provider(),
            selector,
            [],
            "system prompt",
            [],
        )

    assert isinstance(provider, EnsembleProvider)
    assert len(analyzer_calls) == 1
    assert analyzer_calls[0]["user_profile_enabled"] is False
    assert "user_profile" not in analyzer_calls[0]
    decision_id = turn.metadata["ensemble_decision_id"]
    assert analyzer_calls[0]["decision_id"] == decision_id
    assert turn.metadata["router_dynamic_user_profile"] == {
        "enabled": False,
        "source": "",
        "version": "",
    }
    assert provider.selection_plan["decision_id"] == decision_id
    assert provider.selection_plan["user_profile_enabled"] is False
    assert turn.metadata["router_dynamic_decision"]["decision_id"] == decision_id

    routing_events = [
        row
        for row in captured
        if str(row["event"]).startswith("llm_ensemble.routing.")
    ]
    assert routing_events[0]["event"] == "llm_ensemble.routing.decision_started"
    assert routing_events[-1]["event"] == "llm_ensemble.routing.decision_completed"
    assert all(row["decision_id"] == decision_id for row in routing_events)
    assert [row["sequence"] for row in routing_events] == list(
        range(len(routing_events))
    )
    assert {
        "llm_ensemble.routing.task_analysis_recorded",
        "llm_ensemble.routing.hard_filter_recorded",
        "llm_ensemble.routing.model_score_recorded",
        "llm_ensemble.routing.proposer_step_recorded",
        "llm_ensemble.routing.aggregator_score_recorded",
    }.issubset({row["event"] for row in routing_events})


async def test_router_tree_baseline_never_calls_the_remote_task_analyzer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unexpected_analyzer_call(**kwargs: Any) -> TaskAnalysisResult:
        raise AssertionError(f"tree baseline invoked analyzer with {kwargs!r}")

    monkeypatch.setattr(
        "opensquilla.provider.ranking_router.analyze_task_with_provider",
        unexpected_analyzer_call,
    )
    runner = TurnRunner(
        provider_selector=None,
        config=_static_b5_config(selection_mode="router_tree_baseline"),
    )
    selector = _FakeSelector(provider="openrouter", api_key="sk-or-synthetic")

    turn, provider = await runner._run_pipeline(
        "use the local tree baseline",
        "agent:main:tree-baseline",
        _Provider(),
        selector,
        [],
        "system prompt",
        [],
    )

    assert isinstance(provider, EnsembleProvider)
    assert provider.profile_name == "router_tree_baseline/c1"
    assert provider.selection_plan["router_source"] == "compatibility_default"
    assert "router_dynamic_task_analyzer" not in turn.metadata
    assert turn.metadata["router_tree_baseline_decision"]["routed_tier"] == "c1"
    assert turn.metadata["router_tree_baseline_decision"]["selected_P"]
    assert turn.metadata["router_tree_baseline_decision"]["selected_A"]


async def test_router_tree_baseline_runs_without_the_ranking_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        sys.modules,
        "opensquilla.provider.ranking_router",
        None,
    )
    runner = TurnRunner(
        provider_selector=None,
        config=_static_b5_config(selection_mode="router_tree_baseline"),
    )
    selector = _FakeSelector(provider="openrouter", api_key="sk-or-synthetic")

    turn, provider = await runner._run_pipeline(
        "run the isolated local tree baseline",
        "agent:main:tree-baseline-no-ranking",
        _Provider(),
        selector,
        [],
        "system prompt",
        [],
    )

    assert isinstance(provider, EnsembleProvider)
    assert provider.profile_name == "router_tree_baseline/c1"
    assert turn.metadata["router_tree_baseline_decision"]["selected_P"]


async def test_router_tree_baseline_selection_failure_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_selection(**kwargs: Any) -> None:
        raise TreeBaselineError(f"invalid frozen config: {sorted(kwargs)}")

    monkeypatch.setattr(
        "opensquilla.provider.tree_baseline_router.select_tree_baseline",
        fail_selection,
    )
    runner = TurnRunner(
        provider_selector=None,
        config=_static_b5_config(selection_mode="router_tree_baseline"),
    )
    selector = _FakeSelector(provider="openrouter", api_key="sk-or-synthetic")

    turn, provider = await runner._run_pipeline(
        "use the local tree baseline",
        "agent:main:tree-baseline-fail-open",
        _Provider(),
        selector,
        [],
        "system prompt",
        [],
    )

    assert isinstance(provider, _Provider)
    assert not isinstance(provider, EnsembleProvider)
    assert "ensemble_enabled" not in turn.metadata
    assert turn.metadata["ensemble_wrap_skipped_reason"] == (
        "router_tree_baseline_unavailable"
    )
    assert "invalid frozen config" in turn.metadata["router_tree_baseline_error"]


def test_router_dynamic_task_analyzer_resolution_failure_uses_local_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_resolution(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("credential pool unavailable")

    monkeypatch.setattr(
        "opensquilla.engine.selector_override.resolve_tier_provider_config",
        fail_resolution,
    )
    runner = TurnRunner(
        provider_selector=None,
        config=GatewayConfig(
            llm={"provider": "groq", "model": "base-model", "api_key": "fake"},
            squilla_router=SquillaRouterConfig(enabled=False),
            llm_ensemble={"enabled": True, "selection_mode": "router_dynamic"},
        ),
    )

    provider = runner._router_dynamic_task_analyzer_provider(
        ProviderConfig(provider="groq", model="base-model", api_key="fake"),
        session_key="agent:main:analyzer-resolution-failure",
    )

    assert provider is None


async def test_router_dynamic_carries_the_previous_route_into_the_next_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_last_routes: list[dict[str, Any]] = []

    async def fake_analyze_task_with_provider(**kwargs: Any) -> TaskAnalysisResult:
        request_context = kwargs["request_context"]
        last_route = dict(request_context.get("last_route") or {})
        seen_last_routes.append(last_route)
        profile = fallback_task_profile(
            routed_tier=str(kwargs["routed_tier"]),
            request_context=request_context,
        )
        if last_route:
            profile["session_intent"] = {"type": "continue", "confidence": 1.0}
        return TaskAnalysisResult(
            profile=profile,
            source="test",
            schema_valid=True,
            confidence=1.0,
        )

    monkeypatch.setattr(
        "opensquilla.provider.ranking_router.analyze_task_with_provider",
        fake_analyze_task_with_provider,
    )
    runner = TurnRunner(
        provider_selector=None,
        config=_static_b5_config(selection_mode="router_dynamic"),
    )
    selector = _FakeSelector(provider="groq", api_key="sk-groq-synthetic")
    session_key = "agent:main:router-dynamic-continuity"

    first_turn, _ = await runner._run_pipeline(
        "first",
        session_key,
        _Provider(),
        selector,
        [],
        "system prompt",
        [],
    )
    second_turn, _ = await runner._run_pipeline(
        "continue",
        session_key,
        _Provider(),
        selector,
        [],
        "system prompt",
        [],
    )

    assert seen_last_routes[0] == {}
    assert seen_last_routes[1]["selected_P"] == first_turn.metadata[
        "router_dynamic_decision"
    ]["selected_P"]
    assert seen_last_routes[1]["selected_A"] == first_turn.metadata[
        "router_dynamic_decision"
    ]["selected_A"]
    assert second_turn.metadata["router_dynamic_last_route"]["strategy_mode"] == (
        "B5_fuse"
    )
    assert second_turn.metadata["router_dynamic_decision"]["session"][
        "sticky_applied"
    ] is True


async def test_router_dynamic_ranking_failure_fails_open_to_the_single_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    async def extra_long_task(**kwargs: Any) -> TaskAnalysisResult:
        profile = fallback_task_profile(
            routed_tier=str(kwargs["routed_tier"]),
            request_context=kwargs["request_context"],
        )
        profile["constraints"]["context"] = "extra_long"
        return TaskAnalysisResult(
            profile=profile,
            source="test",
            schema_valid=True,
            confidence=1.0,
        )

    monkeypatch.setattr(
        "opensquilla.provider.ranking_router.analyze_task_with_provider",
        extra_long_task,
    )
    runner = TurnRunner(
        provider_selector=None,
        config=_static_b5_config(selection_mode="router_dynamic"),
    )
    selector = _FakeSelector(provider="groq", api_key="sk-groq-synthetic")

    turn, provider = await runner._run_pipeline(
        "an extra-long request",
        "agent:main:router-dynamic-fail-open",
        _Provider(),
        selector,
        [],
        "system prompt",
        [],
    )

    assert isinstance(provider, _Provider)
    assert not isinstance(provider, EnsembleProvider)
    assert "ensemble_enabled" not in turn.metadata
    assert turn.metadata["ensemble_wrap_skipped_reason"] == (
        "router_dynamic_ranking_unavailable"
    )
    assert "no proposer" in turn.metadata["router_dynamic_ranking_error"]


async def test_router_dynamic_config_load_failure_fails_open_before_analysis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_config_load() -> dict[str, Any]:
        raise DynamicRankingError("ranking config is malformed")

    monkeypatch.setattr(
        "opensquilla.provider.ranking_router.ranking_config_snapshot",
        fail_config_load,
    )
    runner = TurnRunner(
        provider_selector=None,
        config=_static_b5_config(selection_mode="router_dynamic"),
    )
    selector = _FakeSelector(provider="groq", api_key="sk-groq-synthetic")

    turn, provider = await runner._run_pipeline(
        "hello",
        "agent:main:router-dynamic-bad-config",
        _Provider(),
        selector,
        [],
        "system prompt",
        [],
    )

    assert isinstance(provider, _Provider)
    assert not isinstance(provider, EnsembleProvider)
    assert "ensemble_enabled" not in turn.metadata
    assert turn.metadata["ensemble_wrap_skipped_reason"] == (
        "router_dynamic_ranking_unavailable"
    )
    assert turn.metadata["router_dynamic_ranking_error"] == (
        "ranking config is malformed"
    )
    assert "router_dynamic_task_analyzer" not in turn.metadata


def _custom_b5_guard_config(candidates: list[dict[str, Any]]) -> GatewayConfig:
    return GatewayConfig(
        squilla_router=SquillaRouterConfig(enabled=False),
        llm={
            "provider": "groq",
            "model": "base-model",
            "api_key": "sk-groq-synthetic",
            "base_url": "https://example.invalid/api",
        },
        llm_ensemble={
            "enabled": True,
            "selection_mode": "custom_b5",
            "candidates": candidates,
        },
    )


async def test_custom_b5_tracks_missing_member_and_preserves_quorum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    cfg = _custom_b5_guard_config(
        [
            {"provider": "groq", "model": "candidate-a"},
            {"provider": "openrouter", "model": "z-ai/glm-5.2"},
        ]
    )
    runner = TurnRunner(provider_selector=None, config=cfg)
    selector = _FakeSelector(provider="groq", api_key="sk-groq-synthetic")

    turn, provider = await runner._run_pipeline(
        "hello",
        "agent:main:test",
        _Provider(),
        selector,
        [],
        "system prompt",
        [],
    )

    assert isinstance(provider, EnsembleProvider)
    by_provider = {
        member.provider_config.provider: member for member in provider.proposers
    }
    assert by_provider["groq"].ready is True
    assert by_provider["openrouter"].ready is False
    assert by_provider["openrouter"].unavailable_reason == "missing_credential"
    assert turn.metadata["ensemble_enabled"] is True
    assert "ensemble_wrap_skipped_reason" not in turn.metadata


async def test_custom_b5_wraps_when_every_member_resolves_a_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-synthetic")
    cfg = _custom_b5_guard_config(
        [
            {"provider": "groq", "model": "candidate-a", "role": "primary"},
            {"provider": "openrouter", "model": "z-ai/glm-5.2", "role": "contrast"},
            {"provider": "groq", "model": "fuser", "role": "aggregator"},
        ]
    )
    runner = TurnRunner(provider_selector=None, config=cfg)
    selector = _FakeSelector(provider="groq", api_key="sk-groq-synthetic")

    turn, provider = await runner._run_pipeline(
        "hello",
        "agent:main:test",
        _Provider(),
        selector,
        [],
        "system prompt",
        [],
    )

    assert isinstance(provider, EnsembleProvider)
    assert provider.profile_name == "custom_b5"
    assert [member.label for member in provider.proposers] == ["primary", "contrast"]
    assert provider.aggregator.provider_config.model == "fuser"
    assert turn.metadata["ensemble_enabled"] is True
    assert "ensemble_wrap_skipped_reason" not in turn.metadata
