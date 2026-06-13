from __future__ import annotations

from types import SimpleNamespace

import pytest

from opensquilla.engine.runtime import TurnRunner, _tier_routed_provider_config
from opensquilla.gateway.config import GatewayConfig, SquillaRouterConfig
from opensquilla.provider.selector import ModelSelector, ProviderConfig, SelectorConfig


def _router_cfg() -> SquillaRouterConfig:
    return SquillaRouterConfig(
        enabled=True,
        rollout_phase="full",
        require_router_runtime=False,
        auto_thinking=False,
        default_tier="c1",
        routing_timeout_seconds=20.0,
        tiers={
            "c1": {
                "provider": "inception",
                "model": "inception/mercury-2",
                "base_url": "https://api.inceptionlabs.ai/v1",
                "api_key_env": "INCEPTION_API_KEY",
                "supports_image": False,
            },
            "c3": {
                "provider": "openrouter",
                "model": "anthropic/claude-opus-4.7",
                "api_key": "openrouter-tier-key",
                "supports_image": False,
            },
            "c2": {
                "provider": "openrouter",
                "model": "z-ai/glm-5.1",
                "api_key": "openrouter-tier-key",
                "supports_image": False,
            },
        },
    )


async def _run_pipeline_with_configured_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fallbacks: list[ProviderConfig],
    session_key: str,
) -> ModelSelector:
    class _Strategy:
        async def classify(self, *_args, **_kwargs):
            return "c1", 0.92, "test_strategy", {}

    monkeypatch.setattr(
        "opensquilla.engine.steps.squilla_router._get_strategy",
        lambda _cfg: _Strategy(),
    )
    config = GatewayConfig()
    config.squilla_router = _router_cfg()
    selector = ModelSelector(
        SelectorConfig(
            primary=ProviderConfig(
                provider="inception",
                model="inception/mercury-2",
                api_key="inception-key",
                base_url="https://api.inceptionlabs.ai/v1",
            ),
            fallbacks=fallbacks,
        )
    )
    cloned_selector = selector.clone()
    runner = TurnRunner(provider_selector=selector, config=config)

    await runner._run_pipeline(
        message="create an artifact",
        session_key=session_key,
        provider=selector.resolve(),
        cloned_selector=cloned_selector,
        tool_defs=[],
        base_prompt="system",
        attachments=[],
        semantic_message="create an artifact",
        tool_context=SimpleNamespace(
            agent_id="main",
            workspace_dir="",
            channel_kind="webchat",
            channel_id="webchat",
        ),
    )
    return cloned_selector


@pytest.mark.asyncio
async def test_run_pipeline_switches_selector_provider_for_routed_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Strategy:
        async def classify(self, *_args, **_kwargs):
            return "c2", 0.92, "test_strategy", {}

    monkeypatch.setattr(
        "opensquilla.engine.steps.squilla_router._get_strategy",
        lambda _cfg: _Strategy(),
    )
    config = GatewayConfig()
    config.squilla_router = _router_cfg()
    selector = ModelSelector(
        SelectorConfig(
            primary=ProviderConfig(
                provider="inception",
                model="inception/mercury-2",
                api_key="inception-key",
                base_url="https://api.inceptionlabs.ai/v1",
            )
        )
    )
    cloned_selector = selector.clone()
    runner = TurnRunner(provider_selector=selector, config=config)

    turn, provider = await runner._run_pipeline(
        message="hard reasoning question",
        session_key="agent:main:test-provider-override",
        provider=selector.resolve(),
        cloned_selector=cloned_selector,
        tool_defs=[],
        base_prompt="system",
        attachments=[],
        semantic_message="hard reasoning question",
        tool_context=SimpleNamespace(
            agent_id="main",
            workspace_dir="",
            channel_kind="webchat",
            channel_id="webchat",
        ),
    )

    assert turn.metadata["routed_provider"] == "openrouter"
    assert turn.model == "z-ai/glm-5.1"
    assert cloned_selector.current_config.provider == "openrouter"
    assert cloned_selector.current_config.model == "z-ai/glm-5.1"
    assert getattr(provider, "_provider_kind") == "openrouter"
    assert getattr(provider, "_model") == "z-ai/glm-5.1"
    assert selector.current_config.provider == "inception"
    assert selector.current_config.model == "inception/mercury-2"


@pytest.mark.asyncio
async def test_run_pipeline_adds_stronger_tier_fallbacks_for_mercury_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Strategy:
        async def classify(self, *_args, **_kwargs):
            return "c1", 0.92, "test_strategy", {}

    monkeypatch.setattr(
        "opensquilla.engine.steps.squilla_router._get_strategy",
        lambda _cfg: _Strategy(),
    )
    config = GatewayConfig()
    config.squilla_router = _router_cfg()
    selector = ModelSelector(
        SelectorConfig(
            primary=ProviderConfig(
                provider="inception",
                model="inception/mercury-2",
                api_key="inception-key",
                base_url="https://api.inceptionlabs.ai/v1",
            )
        )
    )
    cloned_selector = selector.clone()
    runner = TurnRunner(provider_selector=selector, config=config)

    turn, provider = await runner._run_pipeline(
        message="create an artifact",
        session_key="agent:main:test-provider-fallback",
        provider=selector.resolve(),
        cloned_selector=cloned_selector,
        tool_defs=[],
        base_prompt="system",
        attachments=[],
        semantic_message="create an artifact",
        tool_context=SimpleNamespace(
            agent_id="main",
            workspace_dir="",
            channel_kind="webchat",
            channel_id="webchat",
        ),
    )

    assert turn.metadata["routed_tier"] == "c1"
    assert turn.metadata["routed_provider"] == "inception"
    assert getattr(provider, "_provider_kind") == "inception"

    fallback = cloned_selector.next_fallback_after_failure(RuntimeError("malformed_empty"))

    assert cloned_selector.current_config.provider == "openrouter"
    assert cloned_selector.current_config.model == "z-ai/glm-5.1"
    assert getattr(fallback, "_provider_kind") == "openrouter"
    assert getattr(fallback, "_model") == "z-ai/glm-5.1"
    assert selector.current_config.provider == "inception"


@pytest.mark.asyncio
async def test_run_pipeline_appends_configured_fallbacks_after_router_tiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cloned_selector = await _run_pipeline_with_configured_fallbacks(
        monkeypatch,
        fallbacks=[
            ProviderConfig(
                provider="anthropic",
                model="claude-sonnet-4.5",
                api_key="anthropic-key",
            )
        ],
        session_key="agent:main:test-provider-configured-fallback",
    )

    first = cloned_selector.next_fallback_after_failure(RuntimeError("primary failed"))
    assert cloned_selector.current_config.provider == "openrouter"
    assert cloned_selector.current_config.model == "z-ai/glm-5.1"
    assert getattr(first, "_provider_kind") == "openrouter"

    second = cloned_selector.next_fallback_after_failure(RuntimeError("first failed"))
    assert cloned_selector.current_config.provider == "openrouter"
    assert cloned_selector.current_config.model == "anthropic/claude-opus-4.7"
    assert getattr(second, "_provider_kind") == "openrouter"

    third = cloned_selector.next_fallback_after_failure(RuntimeError("second failed"))
    assert cloned_selector.current_config.provider == "anthropic"
    assert cloned_selector.current_config.model == "claude-sonnet-4.5"
    assert getattr(third, "provider_name") == "anthropic"


@pytest.mark.asyncio
async def test_run_pipeline_deduplicates_configured_fallbacks_matching_router_tiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cloned_selector = await _run_pipeline_with_configured_fallbacks(
        monkeypatch,
        fallbacks=[
            ProviderConfig(
                provider="openrouter",
                model="z-ai/glm-5.1",
                api_key="configured-openrouter-key",
                base_url="https://openrouter.ai/api/v1",
            )
        ],
        session_key="agent:main:test-provider-configured-fallback-dedupe",
    )

    first = cloned_selector.next_fallback_after_failure(RuntimeError("primary failed"))
    assert cloned_selector.current_config.provider == "openrouter"
    assert cloned_selector.current_config.model == "z-ai/glm-5.1"
    assert getattr(first, "_provider_kind") == "openrouter"

    second = cloned_selector.next_fallback_after_failure(RuntimeError("first failed"))
    assert cloned_selector.current_config.provider == "openrouter"
    assert cloned_selector.current_config.model == "anthropic/claude-opus-4.7"
    assert getattr(second, "_provider_kind") == "openrouter"

    with pytest.raises(IndexError, match="No fallback chain available"):
        cloned_selector.next_fallback_after_failure(RuntimeError("second failed"))


@pytest.mark.asyncio
async def test_run_pipeline_keeps_search_text_on_experimental_supported_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Strategy:
        async def classify(self, *_args, **_kwargs):
            return "c1", 0.92, "test_strategy", {}

    monkeypatch.setattr(
        "opensquilla.engine.steps.squilla_router._get_strategy",
        lambda _cfg: _Strategy(),
    )
    config = GatewayConfig()
    config.squilla_router = _router_cfg()
    config.squilla_router.tiers["c0"] = {
        "provider": "inception",
        "model": "inception/mercury-2",
        "api_key": "inception-key",
        "base_url": "https://api.inceptionlabs.ai/v1",
        "tool_support": "on",
    }
    config.squilla_router.tiers["c1"] = {
        "provider": "openai_compatible",
        "model": "inclusionAI/LLaDA2.1-flash",
        "api_key": "llada-key",
        "base_url": "http://127.0.0.1:8008/v1",
        "tool_support": "on",
    }
    selector = ModelSelector(
        SelectorConfig(
            primary=ProviderConfig(
                provider="openai_compatible",
                model="inclusionAI/LLaDA2.1-flash",
                api_key="llada-key",
                base_url="http://127.0.0.1:8008/v1",
            )
        )
    )
    cloned_selector = selector.clone()
    runner = TurnRunner(provider_selector=selector, config=config)

    turn, provider = await runner._run_pipeline(
        message="search the web for synthetic routing test data",
        session_key="agent:main:test-tool-required-supported-tier-authority",
        provider=selector.resolve(),
        cloned_selector=cloned_selector,
        tool_defs=[SimpleNamespace(name="web_search")],
        base_prompt="system",
        attachments=[],
        semantic_message="search the web for synthetic routing test data",
        tool_context=SimpleNamespace(
            agent_id="main",
            workspace_dir="",
            channel_kind="webchat",
            channel_id="webchat",
        ),
    )

    assert turn.metadata["routed_tier"] == "c1"
    assert turn.metadata["routed_provider"] == "openai_compatible"
    assert turn.metadata["routed_model"] == "inclusionAI/LLaDA2.1-flash"
    assert "tool_required" not in turn.metadata
    assert "tool_required_route_reliability" not in turn.metadata
    assert "tool_required_unverified_tool_route" not in turn.metadata
    assert "tool_required_reliability_upgrade" not in turn.metadata
    assert "tool_required_anti_downgrade_bypassed" not in turn.metadata
    assert turn.metadata["routing_source"] != "tool_reliability_fallback"
    assert cloned_selector.current_config.provider == "openai_compatible"
    assert cloned_selector.current_config.model == "inclusionAI/LLaDA2.1-flash"
    assert getattr(provider, "_provider_kind") == "self_hosted_openai"


@pytest.mark.asyncio
async def test_run_pipeline_keeps_search_text_on_verified_current_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Strategy:
        async def classify(self, *_args, **_kwargs):
            return "c1", 0.92, "test_strategy", {}

    monkeypatch.setattr(
        "opensquilla.engine.steps.squilla_router._get_strategy",
        lambda _cfg: _Strategy(),
    )
    config = GatewayConfig()
    config.squilla_router = _router_cfg()
    config.squilla_router.tiers["c1"]["tool_support"] = "on"
    config.squilla_router.tiers["c2"]["tool_support"] = "on"
    selector = ModelSelector(
        SelectorConfig(
            primary=ProviderConfig(
                provider="inception",
                model="inception/mercury-2",
                api_key="inception-key",
                base_url="https://api.inceptionlabs.ai/v1",
            )
        )
    )
    cloned_selector = selector.clone()
    runner = TurnRunner(provider_selector=selector, config=config)

    turn, provider = await runner._run_pipeline(
        message="search the web for synthetic routing test data",
        session_key="agent:main:test-tool-required-verified-current",
        provider=selector.resolve(),
        cloned_selector=cloned_selector,
        tool_defs=[SimpleNamespace(name="web_search")],
        base_prompt="system",
        attachments=[],
        semantic_message="search the web for synthetic routing test data",
        tool_context=SimpleNamespace(
            agent_id="main",
            workspace_dir="",
            channel_kind="webchat",
            channel_id="webchat",
        ),
    )

    assert turn.metadata["routed_tier"] == "c1"
    assert "tool_required" not in turn.metadata
    assert "tool_required_route_reliability" not in turn.metadata
    assert "tool_required_reliability_upgrade" not in turn.metadata
    assert getattr(provider, "_provider_kind") == "inception"


@pytest.mark.asyncio
async def test_run_pipeline_does_not_mark_experimental_tool_route_for_search_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Strategy:
        async def classify(self, *_args, **_kwargs):
            return "c1", 0.92, "test_strategy", {}

    monkeypatch.setattr(
        "opensquilla.engine.steps.squilla_router._get_strategy",
        lambda _cfg: _Strategy(),
    )
    config = GatewayConfig()
    config.squilla_router = _router_cfg()
    config.squilla_router.tiers["c1"]["tool_support"] = "on"
    config.squilla_router.tiers["c2"]["tool_support"] = "on"
    config.squilla_router.tiers["c3"]["tool_support"] = "off"
    selector = ModelSelector(
        SelectorConfig(
            primary=ProviderConfig(
                provider="inception",
                model="inception/mercury-2",
                api_key="inception-key",
                base_url="https://api.inceptionlabs.ai/v1",
            )
        )
    )
    cloned_selector = selector.clone()
    runner = TurnRunner(provider_selector=selector, config=config)

    turn, provider = await runner._run_pipeline(
        message="search the web for synthetic routing test data",
        session_key="agent:main:test-tool-required-no-verified-route",
        provider=selector.resolve(),
        cloned_selector=cloned_selector,
        tool_defs=[SimpleNamespace(name="web_search")],
        base_prompt="system",
        attachments=[],
        semantic_message="search the web for synthetic routing test data",
        tool_context=SimpleNamespace(
            agent_id="main",
            workspace_dir="",
            channel_kind="webchat",
            channel_id="webchat",
        ),
    )

    assert turn.metadata["routed_tier"] == "c1"
    assert "tool_required" not in turn.metadata
    assert "tool_required_unverified_tool_route" not in turn.metadata
    assert "tool_required_reliability_upgrade" not in turn.metadata
    assert getattr(provider, "_provider_kind") == "inception"


@pytest.mark.asyncio
async def test_run_pipeline_ignores_tool_required_reliability_bypass_for_search_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Strategy:
        async def classify(self, *_args, **_kwargs):
            return "c1", 0.92, "test_strategy", {}

    monkeypatch.setattr(
        "opensquilla.engine.steps.squilla_router._get_strategy",
        lambda _cfg: _Strategy(),
    )
    config = GatewayConfig()
    config.squilla_router = _router_cfg()
    config.squilla_router.tiers["c0"] = {
        "provider": "inception",
        "model": "inception/mercury-2",
        "api_key": "inception-key",
        "base_url": "https://api.inceptionlabs.ai/v1",
        "tool_support": "on",
    }
    config.squilla_router.tiers["c1"] = {
        "provider": "openai_compatible",
        "model": "inclusionAI/LLaDA2.1-flash",
        "api_key": "llada-key",
        "base_url": "http://127.0.0.1:8008/v1",
        "tool_support": "on",
    }
    selector = ModelSelector(
        SelectorConfig(
            primary=ProviderConfig(
                provider="openai_compatible",
                model="inclusionAI/LLaDA2.1-flash",
                api_key="llada-key",
                base_url="http://127.0.0.1:8008/v1",
            )
        )
    )
    cloned_selector = selector.clone()
    runner = TurnRunner(provider_selector=selector, config=config)

    turn, provider = await runner._run_pipeline(
        message="search the web for synthetic routing test data",
        session_key="agent:main:test-tool-required-bypass-disabled",
        provider=selector.resolve(),
        cloned_selector=cloned_selector,
        tool_defs=[SimpleNamespace(name="web_search")],
        base_prompt="system",
        attachments=[],
        semantic_message="search the web for synthetic routing test data",
        tool_context=SimpleNamespace(
            agent_id="main",
            workspace_dir="",
            channel_kind="webchat",
            channel_id="webchat",
        ),
    )

    assert turn.metadata["routed_tier"] == "c1"
    assert "tool_required" not in turn.metadata
    assert "tool_required_unverified_tool_route" not in turn.metadata
    assert "tool_required_reliability_upgrade" not in turn.metadata
    assert getattr(provider, "_provider_kind") == "self_hosted_openai"


@pytest.mark.asyncio
async def test_run_pipeline_keeps_search_text_on_no_tool_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Strategy:
        async def classify(self, *_args, **_kwargs):
            return "c1", 0.92, "test_strategy", {}

    monkeypatch.setattr(
        "opensquilla.engine.steps.squilla_router._get_strategy",
        lambda _cfg: _Strategy(),
    )
    config = GatewayConfig()
    config.squilla_router = _router_cfg()
    config.squilla_router.tiers["c1"]["tool_support"] = "off"
    config.squilla_router.tiers["c2"]["tool_support"] = "on"
    selector = ModelSelector(
        SelectorConfig(
            primary=ProviderConfig(
                provider="inception",
                model="inception/mercury-2",
                api_key="inception-key",
                base_url="https://api.inceptionlabs.ai/v1",
            )
        )
    )
    cloned_selector = selector.clone()
    runner = TurnRunner(provider_selector=selector, config=config)

    turn, provider = await runner._run_pipeline(
        message="请检索今日 AI Agent 简报",
        session_key="agent:main:test-tool-required-fallback",
        provider=selector.resolve(),
        cloned_selector=cloned_selector,
        tool_defs=[SimpleNamespace(name="web_search")],
        base_prompt="system",
        attachments=[],
        semantic_message="请检索今日 AI Agent 简报",
        tool_context=SimpleNamespace(
            agent_id="main",
            workspace_dir="",
            channel_kind="webchat",
            channel_id="webchat",
        ),
    )

    assert turn.metadata["routed_tier"] == "c1"
    assert turn.metadata["routed_provider"] == "inception"
    assert "tool_required" not in turn.metadata
    assert "tool_required_route_upgrade" not in turn.metadata
    assert cloned_selector.current_config.provider == "inception"
    assert cloned_selector.current_config.model == "inception/mercury-2"
    assert getattr(provider, "_provider_kind") == "inception"


@pytest.mark.asyncio
async def test_run_pipeline_does_not_mark_search_text_without_tool_capable_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Strategy:
        async def classify(self, *_args, **_kwargs):
            return "c1", 0.92, "test_strategy", {}

    monkeypatch.setattr(
        "opensquilla.engine.steps.squilla_router._get_strategy",
        lambda _cfg: _Strategy(),
    )
    config = GatewayConfig()
    config.squilla_router = _router_cfg()
    config.squilla_router.tiers["c1"]["tool_support"] = "off"
    config.squilla_router.tiers["c2"]["tool_support"] = "off"
    config.squilla_router.tiers["c3"]["tool_support"] = "off"
    selector = ModelSelector(
        SelectorConfig(
            primary=ProviderConfig(
                provider="inception",
                model="inception/mercury-2",
                api_key="inception-key",
                base_url="https://api.inceptionlabs.ai/v1",
            )
        )
    )
    cloned_selector = selector.clone()
    runner = TurnRunner(provider_selector=selector, config=config)

    turn, provider = await runner._run_pipeline(
        message="请检索今日 AI Agent 简报",
        session_key="agent:main:test-tool-required-no-fallback",
        provider=selector.resolve(),
        cloned_selector=cloned_selector,
        tool_defs=[SimpleNamespace(name="web_search")],
        base_prompt="system",
        attachments=[],
        semantic_message="请检索今日 AI Agent 简报",
        tool_context=SimpleNamespace(
            agent_id="main",
            workspace_dir="",
            channel_kind="webchat",
            channel_id="webchat",
        ),
    )

    assert turn.metadata["routed_tier"] == "c1"
    assert "tool_required" not in turn.metadata
    assert "tool_required_no_tool_route" not in turn.metadata
    assert "tool_required_route_upgrade" not in turn.metadata
    assert cloned_selector.current_config.provider == "inception"
    assert getattr(provider, "_provider_kind") == "inception"


@pytest.mark.asyncio
async def test_run_pipeline_keeps_latest_text_on_unknown_auto_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Strategy:
        async def classify(self, *_args, **_kwargs):
            return "c1", 0.92, "test_strategy", {}

    monkeypatch.setattr(
        "opensquilla.engine.steps.squilla_router._get_strategy",
        lambda _cfg: _Strategy(),
    )
    config = GatewayConfig()
    config.squilla_router = _router_cfg()
    config.squilla_router.tiers["c1"]["tool_support"] = "auto"
    config.squilla_router.tiers["c2"]["tool_support"] = "on"
    selector = ModelSelector(
        SelectorConfig(
            primary=ProviderConfig(
                provider="inception",
                model="inception/mercury-2",
                api_key="inception-key",
                base_url="https://api.inceptionlabs.ai/v1",
            )
        )
    )
    cloned_selector = selector.clone()
    runner = TurnRunner(provider_selector=selector, config=config)

    turn, provider = await runner._run_pipeline(
        message="latest Silicon Valley AI agent developments",
        session_key="agent:main:test-tool-required-unknown-fallback",
        provider=selector.resolve(),
        cloned_selector=cloned_selector,
        tool_defs=[SimpleNamespace(name="web_search")],
        base_prompt="system",
        attachments=[],
        semantic_message="latest Silicon Valley AI agent developments",
        tool_context=SimpleNamespace(
            agent_id="main",
            workspace_dir="",
            channel_kind="webchat",
            channel_id="webchat",
        ),
    )

    assert turn.metadata["routed_tier"] == "c1"
    assert turn.metadata["routed_provider"] == "inception"
    assert "tool_required" not in turn.metadata
    assert "tool_required_route_upgrade" not in turn.metadata
    assert getattr(provider, "_provider_kind") == "inception"


def _current_provider_config() -> ProviderConfig:
    return ProviderConfig(
        provider="inception",
        model="inception/mercury-2",
        api_key="inception-key",
        base_url="https://api.inceptionlabs.ai/v1",
    )


def test_tier_routed_provider_config_skips_observe_mode_route() -> None:
    config = GatewayConfig()
    config.squilla_router = _router_cfg()

    routed = _tier_routed_provider_config(
        config=config,
        metadata={
            "routed_tier": "c2",
            "routed_model": "z-ai/glm-5.1",
            "routed_provider": "openrouter",
            "routing_applied": False,
            "routing_source": "v4_phase3",
        },
        current_config=_current_provider_config(),
        model="inception/mercury-2",
    )

    assert routed is None


def test_tier_routed_provider_config_keeps_explicit_model_pin() -> None:
    config = GatewayConfig()
    config.squilla_router = _router_cfg()

    routed = _tier_routed_provider_config(
        config=config,
        metadata={
            "routed_tier": "c2",
            "routed_model": "z-ai/glm-5.1",
            "routed_provider": "openrouter",
            "routing_applied": False,
            "routing_source": "explicit_model",
        },
        current_config=_current_provider_config(),
        model="z-ai/glm-5.1",
    )

    assert routed is not None
    assert routed.provider == "openrouter"
    assert routed.model == "z-ai/glm-5.1"
    assert routed.api_key == "openrouter-tier-key"


def test_external_acquisition_policy_scales_fetch_cap_to_routed_window() -> None:
    """The per-turn web policy derives the single-fetch cap from the routed
    model's context window: small windows shrink the cap so one fetch
    survives into the next iteration's request view; large windows keep the
    50k default via the ceiling.
    """
    from types import SimpleNamespace

    from opensquilla.engine.runtime import _external_acquisition_policy_for_turn
    from opensquilla.result_budget import DEFAULT_TOOL_RUN_BUDGET_POLICY

    small_cfg = SimpleNamespace(
        context_window_tokens=32_768,
        max_tokens=4_096,
        context_overflow_threshold=0.85,
        provider_request_proof_max_chars=0,
        tool_use_argument_provider_request_max_chars=0,
        tool_result_provider_request_max_chars=0,
    )
    small = _external_acquisition_policy_for_turn(small_cfg)
    assert small.max_single_fetch_chars == 8_000
    assert small.max_web_search_results == (
        DEFAULT_TOOL_RUN_BUDGET_POLICY.max_web_search_results
    )

    large_cfg = SimpleNamespace(
        context_window_tokens=200_000,
        max_tokens=16_384,
        context_overflow_threshold=0.85,
        provider_request_proof_max_chars=0,
        tool_use_argument_provider_request_max_chars=0,
        tool_result_provider_request_max_chars=0,
    )
    large = _external_acquisition_policy_for_turn(large_cfg)
    assert large.max_single_fetch_chars == 50_000

    broken_cfg = SimpleNamespace()
    assert (
        _external_acquisition_policy_for_turn(broken_cfg)
        is DEFAULT_TOOL_RUN_BUDGET_POLICY
        or _external_acquisition_policy_for_turn(broken_cfg).max_single_fetch_chars
        is not None
    )


@pytest.mark.asyncio
async def test_external_acquisition_policy_clamps_web_fetch_reservation() -> None:
    """Integration: the routed-window policy clamps a web_fetch's max_chars
    at reservation time, so a small-context tier never acquires a page it
    cannot keep across iterations (the elision-loop in incident
    agent:main:webchat:3h1bj7ek). Verified live against a 1.5MB page.
    """
    from types import SimpleNamespace

    from opensquilla.engine.runtime import _external_acquisition_policy_for_turn
    from opensquilla.result_budget import ToolRunBudgetTracker

    c1_cfg = SimpleNamespace(
        context_window_tokens=32_768,
        max_tokens=4_096,
        context_overflow_threshold=0.85,
        provider_request_proof_max_chars=0,
        tool_use_argument_provider_request_max_chars=0,
        tool_result_provider_request_max_chars=0,
    )
    policy = _external_acquisition_policy_for_turn(c1_cfg)
    tracker = ToolRunBudgetTracker(policy)

    # No caller-supplied max_chars: the reservation must inject the cap.
    args: dict = {"url": "https://example.com/big"}
    reservation = await tracker.reserve_tool_call(tool_name="web_fetch", arguments=args)
    assert reservation.arguments["max_chars"] == 8_000

    # A caller asking for more than the cap is clamped down.
    over_args: dict = {"url": "https://example.com/big", "max_chars": 1_000_000}
    over = await ToolRunBudgetTracker(policy).reserve_tool_call(
        tool_name="web_fetch", arguments=over_args
    )
    assert over.arguments["max_chars"] == 8_000

    # A caller asking for less keeps the smaller request.
    under_args: dict = {"url": "https://example.com/big", "max_chars": 2_000}
    under = await ToolRunBudgetTracker(policy).reserve_tool_call(
        tool_name="web_fetch", arguments=under_args
    )
    assert under.arguments["max_chars"] == 2_000
