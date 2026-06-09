from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from opensquilla.engine.runtime import TurnRunner
from opensquilla.engine.steps import squilla_router as squilla_router_step
from opensquilla.engine.types import DoneEvent, RouterControlReplayEvent
from opensquilla.gateway.config import (
    GatewayConfig,
    SquillaRouterConfig,
    _router_tier_profile_defaults,
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
        self.model = "base-model"

    def chat(self, messages: list[Any], tools=None, config=None) -> AsyncIterator[Any]:
        self.calls.append(self.model)
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
    assert done_events[-1].text == "new final"
    assert text.endswith("new final")
