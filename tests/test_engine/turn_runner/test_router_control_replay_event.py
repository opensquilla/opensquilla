from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from opensquilla.engine import runtime as runtime_module
from opensquilla.engine.runtime import TurnRunner
from opensquilla.engine.steps import squilla_router as squilla_router_step
from opensquilla.engine.types import DoneEvent, RouterControlReplayEvent
from opensquilla.gateway.config import (
    GatewayConfig,
    SquillaRouterConfig,
    _router_tier_profile_defaults,
)
from opensquilla.provider import (
    ChatConfig,
)
from opensquilla.provider import (
    DoneEvent as ProviderDone,
)
from opensquilla.provider import (
    TextDeltaEvent as ProviderText,
)
from opensquilla.provider import ToolUseEndEvent as ProviderToolEnd
from opensquilla.provider import ToolUseStartEvent as ProviderToolStart
from opensquilla.tools import get_default_registry
from opensquilla.tools.types import CallerKind, ToolContext


class _Strategy:
    async def classify(
        self,
        message: str,
        valid_tiers: list[str],
        routing_history: list[dict] | None = None,
        **kwargs: object,
    ) -> tuple[str, float, str, dict]:
        return "c1", 0.9, "v4_phase3", {"route_class": "R1"}


class _ReplayProvider:
    provider_name = "test"

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.provider_requests: list[str] = []
        self.model = "base-model"

    def chat(
        self,
        messages: list[Any],
        tools=None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        self.calls.append(self.model)
        system_prompt = config.system if config and config.system else ""
        self.provider_requests.append(f"{system_prompt}\n\n{messages!r}")
        return self._stream(len(self.calls))

    async def _stream(self, call_number: int) -> AsyncIterator[Any]:
        if call_number == 1:
            yield ProviderText(text="old partial")
            yield ProviderToolStart(tool_use_id="tool-1", tool_name="router_control")
            yield ProviderToolEnd(
                tool_use_id="tool-1",
                tool_name="router_control",
                arguments={
                    "action": "set_hold",
                    "target_id": "tier:c3",
                    "evidence": "use c3",
                },
            )
            yield ProviderDone(model=self.model)
            return
        yield ProviderText(text="new final")
        yield ProviderDone(model=self.model)

    async def list_models(self) -> list[Any]:
        return []


class _SelectorClone:
    def __init__(self, provider: _ReplayProvider) -> None:
        self.provider = provider
        self.current_config = SimpleNamespace(model=provider.model)

    def override_model(self, model: str) -> None:
        self.current_config = SimpleNamespace(model=model)
        self.provider.model = model

    def resolve(self) -> _ReplayProvider:
        return self.provider


class _Selector:
    def __init__(self, provider: _ReplayProvider) -> None:
        self.provider = provider

    def clone(self) -> _SelectorClone:
        return _SelectorClone(self.provider)


@pytest.mark.asyncio
async def test_router_control_replay_event_replays_turn_once(monkeypatch) -> None:
    monkeypatch.setattr(squilla_router_step, "_get_strategy", lambda _cfg: _Strategy())
    provider = _ReplayProvider()
    cfg = GatewayConfig(
        squilla_router=SquillaRouterConfig(
            enabled=True,
            rollout_phase="full",
            require_router_runtime=False,
            tiers=_router_tier_profile_defaults("openrouter"),
        )
    )
    runner = TurnRunner(
        provider_selector=_Selector(provider),
        tool_registry=get_default_registry(),
        config=cfg,
    )

    events = [
        event
        async for event in runner.run(
            "Use c3 for this",
            "agent:main:router-control-replay",
            tool_context=ToolContext(is_owner=True, caller_kind=CallerKind.CLI),
            history_has_persisted_user=False,
            no_memory_capture=True,
        )
    ]

    replay_events = [event for event in events if isinstance(event, RouterControlReplayEvent)]
    done_events = [event for event in events if isinstance(event, DoneEvent)]
    text = "".join(getattr(event, "text", "") for event in events if event.kind == "text_delta")

    assert len(replay_events) == 1
    assert replay_events[0].target_tier == "c3"
    assert provider.calls == ["deepseek/deepseek-v4-pro", "anthropic/claude-opus-4.7"]
    assert "Router Control status" not in provider.provider_requests[0]
    assert "Router Control status" in provider.provider_requests[1]
    assert "target_id=tier:c3" in provider.provider_requests[1]
    assert "model=anthropic/claude-opus-4.7" in provider.provider_requests[1]
    assert "Do not call router_control again" in provider.provider_requests[1]
    assert done_events[-1].text == "new final"
    assert text.endswith("new final")


@pytest.mark.asyncio
async def test_router_control_replay_depth_cap_finishes_turn_without_recursion(
    monkeypatch,
) -> None:
    """The runtime-side ceiling must hold even if the tool-side guard fails.

    With the cap forced to zero, the first replay request is already over
    the limit: the replay event is suppressed, the turn finishes normally
    on the original route, and the provider is called exactly once.
    """
    monkeypatch.setattr(squilla_router_step, "_get_strategy", lambda _cfg: _Strategy())
    monkeypatch.setattr(runtime_module, "_MAX_ROUTER_CONTROL_REPLAYS", 0)
    provider = _ReplayProvider()
    cfg = GatewayConfig(
        squilla_router=SquillaRouterConfig(
            enabled=True,
            rollout_phase="full",
            require_router_runtime=False,
            tiers=_router_tier_profile_defaults("openrouter"),
        )
    )
    runner = TurnRunner(
        provider_selector=_Selector(provider),
        tool_registry=get_default_registry(),
        config=cfg,
    )

    events = [
        event
        async for event in runner.run(
            "Use c3 for this",
            "agent:main:router-control-replay-cap",
            tool_context=ToolContext(is_owner=True, caller_kind=CallerKind.CLI),
            history_has_persisted_user=False,
            no_memory_capture=True,
        )
    ]

    replay_events = [event for event in events if isinstance(event, RouterControlReplayEvent)]
    done_events = [event for event in events if isinstance(event, DoneEvent)]

    assert replay_events == []
    assert provider.calls == ["deepseek/deepseek-v4-pro"]
    assert done_events
    assert done_events[-1].text == "old partial"


class _TextRouterControlProvider:
    """Emits a text-form router_control call instead of a native tool call."""

    provider_name = "test"

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.model = "base-model"

    def chat(
        self,
        messages: list[Any],
        tools=None,
        config: ChatConfig | None = None,
    ) -> AsyncIterator[Any]:
        self.calls.append(self.model)
        return self._stream()

    async def _stream(self) -> AsyncIterator[Any]:
        yield ProviderText(
            text=(
                "I will switch now.\n"
                'router_control{"action": "set_hold", "target_id": "tier:c3",'
                ' "evidence": "user asked for opus"}'
            )
        )
        yield ProviderDone(model=self.model)

    async def list_models(self) -> list[Any]:
        return []


@pytest.mark.asyncio
async def test_router_control_text_synthesis_blocked_when_toolset_lacks_router_control(
    monkeypatch,
) -> None:
    """Hold-lock characterization (live incident agent:main:webchat:t65cahdl).

    With a hold pinning c1 and c1's toolset narrowed to exclude
    router_control, a text-compat model imitating router_control{...} must
    not produce a synthesized tool call (allowlist gate keys on the tools
    actually sent), the turn must finish, and the hold must stay in place —
    the session is locked until the toolset regains the escape hatch.
    """
    monkeypatch.setattr(squilla_router_step, "_get_strategy", lambda _cfg: _Strategy())
    provider = _TextRouterControlProvider()
    tiers = _router_tier_profile_defaults("openrouter")
    tiers["c1"] = dict(tiers["c1"])
    tiers["c1"]["toolset"] = "files"
    cfg = GatewayConfig(
        squilla_router=SquillaRouterConfig(
            enabled=True,
            rollout_phase="full",
            require_router_runtime=False,
            tiers=tiers,
        )
    )
    runner = TurnRunner(
        provider_selector=_Selector(provider),
        tool_registry=get_default_registry(),
        config=cfg,
    )
    session_key = "agent:main:router-control-hold-locked"
    store = runner._router_control_hold_store
    targets = store.build_targets(cfg.squilla_router)
    c1_target = next(t for t in targets if t.tier == "c1")
    store.set_hold(session_key, c1_target, evidence="pin c1 for testing")

    events = [
        event
        async for event in runner.run(
            "Switch to opus please",
            session_key,
            tool_context=ToolContext(is_owner=True, caller_kind=CallerKind.CLI),
            history_has_persisted_user=False,
            no_memory_capture=True,
        )
    ]

    tool_events = [event for event in events if getattr(event, "kind", "") == "tool_use_start"]
    replay_events = [event for event in events if isinstance(event, RouterControlReplayEvent)]
    done_events = [event for event in events if isinstance(event, DoneEvent)]

    assert tool_events == []
    assert replay_events == []
    assert done_events
    hold_after = store.get_valid(session_key)
    assert hold_after is not None
    assert hold_after.tier == "c1"
