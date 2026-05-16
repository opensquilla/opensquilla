from __future__ import annotations

import ast
import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from opensquilla.channels.manager import ChannelManager


class _FakeChannel:
    stopped = False

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        self.stopped = True


class _FakeInFlight:
    cancelled = False

    async def cancel_all(self) -> None:
        self.cancelled = True


class _RecordingIngress:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.in_flight = _FakeInFlight()

    def create_in_flight_set(self, config: Any) -> _FakeInFlight:
        return self.in_flight

    async def run_dispatch(
        self,
        *,
        channel: Any,
        turn_runner: Any,
        session_manager: Any,
        session_key_builder: Callable[[Any], str],
        session_prefix: str,
        event_bridge: Any = None,
        config: Any = None,
        task_runtime: Any = None,
        rpc_dispatcher: Any = None,
        channel_rpc_context_factory: Callable[[Any], Any] | None = None,
        debounce_coordinator: Any = None,
        debounce_window_s: float = 0.0,
        in_flight: Any = None,
    ) -> None:
        self.calls.append(
            {
                "channel": channel,
                "turn_runner": turn_runner,
                "session_manager": session_manager,
                "session_prefix": session_prefix,
                "event_bridge": event_bridge,
                "config": config,
                "task_runtime": task_runtime,
                "rpc_dispatcher": rpc_dispatcher,
                "channel_rpc_context_factory": channel_rpc_context_factory,
                "debounce_coordinator": debounce_coordinator,
                "debounce_window_s": debounce_window_s,
                "in_flight": in_flight,
            }
        )


class _BlockingIngress(_RecordingIngress):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()

    async def run_dispatch(self, **kwargs: Any) -> None:
        await super().run_dispatch(**kwargs)
        self.started.set()
        await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_channel_manager_dispatches_through_injected_ingress_port() -> None:
    channel = _FakeChannel()
    ingress = _RecordingIngress()
    manager = ChannelManager(
        {"slack": channel},
        "turn-runner",
        "session-manager",
        _event_bridge="event-bridge",
        _config="config",
        _task_runtime="task-runtime",
        _rpc_dispatcher="rpc-dispatcher",
        _channel_rpc_context_factory=lambda ctx: ctx,
        _channel_ingress=ingress,
        _max_retries=0,
    )

    await manager._run_one_dispatch_cycle(  # noqa: SLF001 - verifies adapter boundary wiring
        "slack",
        lambda _msg: "session-key",
        in_flight=ingress.in_flight,
    )

    assert len(ingress.calls) == 1
    call = ingress.calls[0]
    assert call["channel"] is channel
    assert call["turn_runner"] == "turn-runner"
    assert call["session_manager"] == "session-manager"
    assert call["session_prefix"] == "slack"
    assert call["event_bridge"] == "event-bridge"
    assert call["config"] == "config"
    assert call["task_runtime"] == "task-runtime"
    assert call["rpc_dispatcher"] == "rpc-dispatcher"
    assert call["in_flight"] is ingress.in_flight


@pytest.mark.asyncio
async def test_channel_manager_start_stop_uses_ingress_in_flight_set() -> None:
    channel = _FakeChannel()
    ingress = _BlockingIngress()
    manager = ChannelManager(
        {"slack": channel},
        "turn-runner",
        "session-manager",
        _channel_ingress=ingress,
    )

    results = await manager.start_all()
    await asyncio.wait_for(ingress.started.wait(), timeout=1.0)
    await manager.stop_all()

    assert results == {"slack": True}
    assert ingress.in_flight.cancelled is True
    assert channel.stopped is True


def test_channel_manager_does_not_import_gateway_dispatch_directly() -> None:
    manager_path = (
        Path(__file__).resolve().parents[2] / "src" / "opensquilla" / "channels" / "manager.py"
    )
    tree = ast.parse(manager_path.read_text(encoding="utf-8"), filename=str(manager_path))

    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    assert "opensquilla.gateway.channel_dispatch" not in imported_modules
    assert "opensquilla.gateway._debounce" not in imported_modules
