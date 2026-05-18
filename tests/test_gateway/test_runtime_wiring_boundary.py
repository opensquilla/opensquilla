from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from opensquilla.gateway.config import GatewayConfig

ROOT = Path(__file__).resolve().parents[2]
GATEWAY = ROOT / "src/opensquilla/gateway"
BOOT = GATEWAY / "boot.py"
RUNTIME_WIRING = GATEWAY / "runtime_wiring.py"


def _imports_from(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        (node.module, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    }


def _function(path: Path, name: str) -> ast.AsyncFunctionDef | ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    matches = [
        node
        for node in tree.body
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name
    ]
    assert len(matches) == 1
    return matches[0]


def test_runtime_wiring_module_exports_builder_contract() -> None:
    assert RUNTIME_WIRING.exists()

    from opensquilla.gateway.runtime_wiring import (
        GatewayRuntimeWiring,
        build_gateway_runtime_wiring,
    )

    wiring_fields = getattr(GatewayRuntimeWiring, "__dataclass_fields__")
    assert set(wiring_fields) == {
        "heartbeat_service",
        "heartbeat_loop",
        "heartbeat_watcher",
        "task_runtime",
        "runtime_event_bridge",
        "background_completion_manager",
    }
    assert callable(build_gateway_runtime_wiring)


def test_boot_delegates_runtime_startup_wiring_to_gateway_boundary() -> None:
    imports = _imports_from(BOOT)
    assert (
        "opensquilla.gateway.runtime_wiring",
        "build_gateway_runtime_wiring",
    ) in imports

    start_gateway_server = _function(BOOT, "start_gateway_server")
    forbidden_imports = {
        ("opensquilla.scheduler.heartbeat", "HeartbeatConfigWatcher"),
        ("opensquilla.scheduler.heartbeat", "HeartbeatRunner"),
        ("opensquilla.scheduler.heartbeat_loop", "HeartbeatLoop"),
        ("opensquilla.scheduler.heartbeat_service", "HeartbeatService"),
        ("opensquilla.gateway.background_completion", "BackgroundCompletionManager"),
        ("opensquilla.gateway.event_bridge", "EventBridge"),
        ("opensquilla.gateway.task_runtime", "TaskRuntime"),
        ("opensquilla.gateway.task_runtime", "TaskRun"),
    }
    function_imports = {
        (node.module, alias.name)
        for node in ast.walk(start_gateway_server)
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    }
    assert function_imports.isdisjoint(forbidden_imports)

    forbidden_calls = {
        "HeartbeatConfigWatcher",
        "HeartbeatRunner",
        "HeartbeatLoop",
        "HeartbeatService",
        "BackgroundCompletionManager",
        "EventBridge",
        "TaskRuntime",
    }
    calls = {
        node.func.id
        for node in ast.walk(start_gateway_server)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert calls.isdisjoint(forbidden_calls)


@pytest.mark.asyncio
async def test_builder_preserves_runtime_wiring_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.gateway import runtime_wiring

    events: list[str] = []
    configured: dict[str, Any] = {}
    registered_manager: list[Any] = []

    class FakeEventBridge:
        def __init__(self, *, subscription_manager: Any, connection_registry: Any) -> None:
            self.subscription_manager = subscription_manager
            self.connection_registry = connection_registry

        async def emit(
            self,
            session_key: str,
            event_name: str,
            payload: dict[str, Any] | None = None,
        ) -> None:
            events.append(f"emit:{session_key}:{event_name}:{payload or {}}")

    class FakeBackgroundCompletionManager:
        def __init__(
            self,
            *,
            session_manager: Any,
            event_emitter: Any,
            channel_manager_ref: Any,
        ) -> None:
            self.session_manager = session_manager
            self.event_emitter = event_emitter
            self.channel_manager_ref = channel_manager_ref

    class FakeHeartbeatService:
        def __init__(
            self,
            *,
            turn_runner: Any,
            session_storage: Any,
            channel_manager_ref: Any,
        ) -> None:
            self.turn_runner = turn_runner
            self.session_storage = session_storage
            self.channel_manager_ref = channel_manager_ref

    class FakeHeartbeatLoop:
        def __init__(self, *, config: Any, heartbeat_service: Any) -> None:
            self.config = config
            self.heartbeat_service = heartbeat_service

        def apply_overrides(self, _overrides: Any) -> None:
            events.append("loop.apply_overrides")

        async def start(self) -> None:
            events.append("loop.start")

    class FakeHeartbeatRunner:
        pass

    class FakeHeartbeatConfigWatcher:
        def __init__(
            self,
            heartbeat_runner: Any,
            heartbeat_md_path: Path,
            *,
            loop_listener: Any,
        ) -> None:
            self.heartbeat_runner = heartbeat_runner
            self.heartbeat_md_path = heartbeat_md_path
            self.loop_listener = loop_listener

        async def start(self) -> None:
            events.append("watcher.start")
            self.loop_listener(SimpleNamespace())

    class FakeTaskRuntime:
        def __init__(
            self,
            *,
            storage: Any,
            turn_handler: Any,
            event_emitter: Any,
            terminal_listener: Any,
            max_concurrency: int,
            max_pending_per_session: int,
            subagent_reserved_slots: int,
        ) -> None:
            self.storage = storage
            self.turn_handler = turn_handler
            self.event_emitter = event_emitter
            self.terminal_listener = terminal_listener
            self.max_concurrency = max_concurrency
            self.max_pending_per_session = max_pending_per_session
            self.subagent_reserved_slots = subagent_reserved_slots

        def _get_session_lock_for_turn(self, session_key: str) -> tuple[str, str]:
            return ("lock", session_key)

    class FakeTurnRunner:
        def __init__(self) -> None:
            self.lock_provider = None

        def set_session_lock_provider(self, provider: Any) -> None:
            self.lock_provider = provider

    class FakeSessionManager:
        def __init__(self) -> None:
            self.storage = object()
            self.attached_runtime = None

        def attach_task_runtime(self, task_runtime: Any) -> None:
            self.attached_runtime = task_runtime

    async def fake_dispatch(run: Any, **kwargs: Any) -> None:
        events.append(f"dispatch:{run}")
        assert kwargs["config"] is config
        assert kwargs["session_manager"] is svc.session_manager
        assert kwargs["turn_runner"] is turn_runner
        await kwargs["event_emitter"]("agent:main:test", "session.event.done", {"text": "ok"})

    async def fake_announce(event: Any, **kwargs: Any) -> None:
        events.append(f"announce:{event}")
        assert kwargs["session_manager"] is svc.session_manager
        assert kwargs["channel_manager"] is channel_manager
        assert kwargs["task_runtime"] is wiring.task_runtime

    monkeypatch.setattr(runtime_wiring, "EventBridge", FakeEventBridge)
    monkeypatch.setattr(
        runtime_wiring,
        "BackgroundCompletionManager",
        FakeBackgroundCompletionManager,
    )
    monkeypatch.setattr(runtime_wiring, "HeartbeatService", FakeHeartbeatService)
    monkeypatch.setattr(runtime_wiring, "HeartbeatLoop", FakeHeartbeatLoop)
    monkeypatch.setattr(runtime_wiring, "HeartbeatRunner", FakeHeartbeatRunner)
    monkeypatch.setattr(runtime_wiring, "HeartbeatConfigWatcher", FakeHeartbeatConfigWatcher)
    monkeypatch.setattr(runtime_wiring, "TaskRuntime", FakeTaskRuntime)
    monkeypatch.setattr(
        runtime_wiring,
        "configure_tool_services",
        lambda **kwargs: configured.update(kwargs),
    )
    monkeypatch.setattr(
        runtime_wiring,
        "set_background_completion_manager",
        lambda manager: registered_manager.append(manager),
    )
    monkeypatch.setattr(runtime_wiring, "announce_subagent_completion", fake_announce)

    config = GatewayConfig(
        state_dir=str(tmp_path / "state"),
        workspace_dir=str(tmp_path / "workspace"),
    )
    channel_manager = object()
    turn_runner = FakeTurnRunner()
    svc = SimpleNamespace(session_manager=FakeSessionManager(), task_runtime=None)

    wiring = await runtime_wiring.build_gateway_runtime_wiring(
        config=config,
        svc=svc,
        turn_runner=turn_runner,
        subscription_manager=object(),
        channel_manager_ref=lambda: channel_manager,
        task_turn_dispatcher=fake_dispatch,
        connection_registry=object(),
    )

    assert events == ["watcher.start", "loop.apply_overrides", "loop.start"]
    assert isinstance(wiring.task_runtime, FakeTaskRuntime)
    assert svc.task_runtime is wiring.task_runtime
    assert svc.heartbeat_watcher is wiring.heartbeat_watcher
    assert svc.heartbeat_loop is wiring.heartbeat_loop
    assert svc.session_manager.attached_runtime is wiring.task_runtime
    assert turn_runner.lock_provider("agent:main:test") == ("lock", "agent:main:test")
    assert configured["task_runtime"] is wiring.task_runtime
    assert registered_manager == [wiring.background_completion_manager]
    await wiring.task_runtime.turn_handler("turn")
    await wiring.task_runtime.terminal_listener("terminal")
    assert events[-3:] == [
        "dispatch:turn",
        "emit:agent:main:test:session.event.done:{'text': 'ok'}",
        "announce:terminal",
    ]
