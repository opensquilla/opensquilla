from __future__ import annotations

from types import SimpleNamespace

import pytest

from opensquilla.engine.runtime import TurnRunner
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
async def test_run_pipeline_upgrades_tool_required_turn_from_no_tool_tier(
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

    assert turn.metadata["routed_tier"] == "c2"
    assert turn.metadata["routed_provider"] == "openrouter"
    assert turn.metadata["tool_required_route_upgrade"] == {
        "from_tier": "c1",
        "to_tier": "c2",
        "reason": "selected_tier_without_tools",
        "from_tool_support_state": "unsupported",
        "to_tool_support_state": "supported",
    }
    assert cloned_selector.current_config.provider == "openrouter"
    assert cloned_selector.current_config.model == "z-ai/glm-5.1"
    assert getattr(provider, "_provider_kind") == "openrouter"


@pytest.mark.asyncio
async def test_run_pipeline_marks_tool_required_turn_without_tool_capable_fallback(
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
    assert turn.metadata["tool_required_no_tool_route"] == {
        "tier": "c1",
        "reason": "selected_tier_without_tools",
        "tool_support_state": "unsupported",
    }
    assert "tool_required_route_upgrade" not in turn.metadata
    assert cloned_selector.current_config.provider == "inception"
    assert getattr(provider, "_provider_kind") == "inception"


@pytest.mark.asyncio
async def test_run_pipeline_upgrades_tool_required_turn_from_unknown_auto_tier(
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

    assert turn.metadata["routed_tier"] == "c2"
    assert turn.metadata["routed_provider"] == "openrouter"
    assert turn.metadata["tool_required_route_upgrade"] == {
        "from_tier": "c1",
        "to_tier": "c2",
        "reason": "selected_tier_without_tools",
        "from_tool_support_state": "unknown",
        "to_tool_support_state": "supported",
    }
    assert getattr(provider, "_provider_kind") == "openrouter"
