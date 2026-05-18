from __future__ import annotations

import ast
import importlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from opensquilla.gateway.config import AgentEntryConfig, GatewayConfig

ROOT = Path(__file__).resolve().parents[2]
BOOT = ROOT / "src/opensquilla/gateway/boot.py"
CRON_HANDLER_WIRING = ROOT / "src/opensquilla/gateway/cron_handler_wiring.py"


class _FakeScheduler:
    def __init__(self) -> None:
        self.handlers: dict[str, Any] = {}

    def register_handler(self, key: str, handler: Any) -> None:
        self.handlers[key] = handler


class _FakeLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def info(self, event: str, **kwargs: Any) -> None:
        self.events.append((event, kwargs))


def _boot_tree() -> ast.Module:
    return ast.parse(BOOT.read_text(encoding="utf-8"))


def _imports_from(tree: ast.Module) -> set[tuple[str, str]]:
    return {
        (node.module, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    }


def _start_gateway_server(tree: ast.Module) -> ast.AsyncFunctionDef:
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "start_gateway_server":
            return node
    raise AssertionError("start_gateway_server not found")


def _called_names(node: ast.AST) -> set[str]:
    calls: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if isinstance(child.func, ast.Name):
            calls.add(child.func.id)
        elif isinstance(child.func, ast.Attribute):
            calls.add(child.func.attr)
    return calls


def _wiring_module() -> Any:
    importlib.invalidate_caches()
    return importlib.import_module("opensquilla.gateway.cron_handler_wiring")


def test_cron_handler_wiring_boundary_exists_and_exports_register_helper() -> None:
    assert CRON_HANDLER_WIRING.exists()

    module = _wiring_module()

    assert hasattr(module, "register_gateway_cron_handlers")


def test_start_gateway_server_delegates_cron_handler_registration_to_boundary() -> None:
    tree = _boot_tree()
    imports = _imports_from(tree)
    start = _start_gateway_server(tree)
    calls = _called_names(start)

    assert (
        "opensquilla.gateway.cron_handler_wiring",
        "register_gateway_cron_handlers",
    ) in imports
    assert "register_gateway_cron_handlers" in calls


def test_start_gateway_server_no_longer_directly_wires_cron_handler_factories() -> None:
    tree = _boot_tree()
    imports = _imports_from(tree)
    start = _start_gateway_server(tree)
    calls = _called_names(start)
    moved_names = {
        "make_agent_run_handler",
        "make_system_event_handler",
        "make_memory_dream_handler",
        "build_dream_factory",
        "build_cron_delivery_chain",
    }

    assert all(
        ("opensquilla.scheduler.handlers", name) not in imports for name in moved_names
    )
    assert all(
        ("opensquilla.scheduler.dream_handler", name) not in imports for name in moved_names
    )
    assert all(
        ("opensquilla.memory.dream_factory", name) not in imports for name in moved_names
    )
    assert all(
        ("opensquilla.gateway.cron_result_delivery", name) not in imports
        for name in moved_names
    )
    assert calls.isdisjoint(moved_names)


@pytest.mark.asyncio
async def test_register_gateway_cron_handlers_noops_without_scheduler() -> None:
    module = _wiring_module()
    dream_calls: list[dict[str, Any]] = []
    logger = _FakeLogger()
    svc = SimpleNamespace(cron_scheduler=None)

    await module.register_gateway_cron_handlers(
        config=GatewayConfig(),
        svc=svc,
        turn_runner=object(),
        task_runtime=object(),
        heartbeat_service=object(),
        heartbeat_loop=object(),
        subscription_manager=object(),
        channel_manager_ref=lambda: object(),
        dream_cron_registrar=lambda **kwargs: dream_calls.append(kwargs),
        configured_agent_ids=lambda config: ["main"],
        logger=logger,
    )

    assert dream_calls == []
    assert logger.events == []


@pytest.mark.asyncio
async def test_register_gateway_cron_handlers_registers_exact_keys_and_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _wiring_module()
    scheduler = _FakeScheduler()
    logger = _FakeLogger()

    monkeypatch.setattr(module, "build_cron_delivery_chain", lambda **_kwargs: "delivery")
    monkeypatch.setattr(module, "make_agent_run_handler", lambda **_kwargs: "agent-handler")
    monkeypatch.setattr(module, "make_system_event_handler", lambda **_kwargs: "system-handler")
    monkeypatch.setattr(
        module,
        "make_memory_dream_handler",
        lambda **_kwargs: "dream-handler",
    )
    monkeypatch.setattr(module, "build_dream_factory", lambda **_kwargs: "dream-factory")

    async def dream_cron_registrar(**_kwargs: Any) -> None:
        return None

    await module.register_gateway_cron_handlers(
        config=GatewayConfig(),
        svc=SimpleNamespace(
            cron_scheduler=scheduler,
            session_manager=object(),
            provider_selector=object(),
            tool_registry=object(),
        ),
        turn_runner=object(),
        task_runtime=object(),
        heartbeat_service=object(),
        heartbeat_loop=object(),
        subscription_manager=object(),
        channel_manager_ref=lambda: object(),
        dream_cron_registrar=dream_cron_registrar,
        configured_agent_ids=lambda config: ["main"],
        logger=logger,
    )

    assert scheduler.handlers == {
        "agent_run": "agent-handler",
        "system_event": "system-handler",
        "memory_dream": "dream-handler",
    }
    assert logger.events == [
        ("gateway.cron_handler_registered", {"handler_key": "agent_run"}),
        ("gateway.cron_handler_registered", {"handler_key": "system_event"}),
        ("gateway.cron_handler_registered", {"handler_key": "memory_dream"}),
    ]


@pytest.mark.asyncio
async def test_register_gateway_cron_handlers_passes_dependencies_to_factories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _wiring_module()
    captured: dict[str, Any] = {}
    scheduler = _FakeScheduler()
    channel_manager = object()
    subscription_manager = object()
    session_manager = object()
    turn_runner = object()
    task_runtime = object()
    heartbeat_service = object()
    heartbeat_loop = object()

    def fake_build_cron_delivery_chain(**kwargs: Any) -> str:
        captured["delivery"] = kwargs
        return "delivery-chain"

    def fake_agent_handler(**kwargs: Any) -> str:
        captured["agent"] = kwargs
        return "agent-handler"

    def fake_system_handler(**kwargs: Any) -> str:
        captured["system"] = kwargs
        return "system-handler"

    def fake_build_dream_factory(**kwargs: Any) -> str:
        captured["dream_factory"] = kwargs
        return "dream-factory"

    def fake_dream_handler(**kwargs: Any) -> str:
        captured["dream_handler"] = kwargs
        return "dream-handler"

    monkeypatch.setattr(module, "build_cron_delivery_chain", fake_build_cron_delivery_chain)
    monkeypatch.setattr(module, "make_agent_run_handler", fake_agent_handler)
    monkeypatch.setattr(module, "make_system_event_handler", fake_system_handler)
    monkeypatch.setattr(module, "build_dream_factory", fake_build_dream_factory)
    monkeypatch.setattr(module, "make_memory_dream_handler", fake_dream_handler)

    async def dream_cron_registrar(**_kwargs: Any) -> None:
        return None

    await module.register_gateway_cron_handlers(
        config=GatewayConfig(),
        svc=SimpleNamespace(
            cron_scheduler=scheduler,
            session_manager=session_manager,
            provider_selector="provider-selector",
            tool_registry="tool-registry",
        ),
        turn_runner=turn_runner,
        task_runtime=task_runtime,
        heartbeat_service=heartbeat_service,
        heartbeat_loop=heartbeat_loop,
        subscription_manager=subscription_manager,
        channel_manager_ref=lambda: channel_manager,
        dream_cron_registrar=dream_cron_registrar,
        configured_agent_ids=lambda config: ["main"],
        logger=_FakeLogger(),
    )

    assert captured["delivery"]["channel_manager_ref"]() is channel_manager
    assert captured["delivery"]["subscription_manager"] is subscription_manager
    assert captured["delivery"]["session_manager"] is session_manager
    assert captured["agent"]["delivery_chain"] == "delivery-chain"
    assert captured["agent"]["turn_runner_ref"]() is turn_runner
    assert captured["agent"]["session_manager_ref"]() is session_manager
    assert captured["agent"]["task_runtime_ref"]() is task_runtime
    assert captured["system"]["delivery_chain"] == "delivery-chain"
    assert captured["system"]["turn_runner_ref"]() is turn_runner
    assert captured["system"]["session_manager_ref"]() is session_manager
    assert captured["system"]["heartbeat_service_ref"]() is heartbeat_service
    assert captured["system"]["heartbeat_loop_ref"]() is heartbeat_loop
    assert captured["system"]["session_event_emitter"] is not None
    assert captured["agent"]["workspace_resolver"] is captured["system"]["workspace_resolver"]
    assert captured["dream_factory"] == {
        "config": captured["dream_factory"]["config"],
        "provider_selector": "provider-selector",
        "tool_registry": "tool-registry",
        "turn_runner": turn_runner,
    }
    assert captured["dream_handler"]["build_dream"] == "dream-factory"


@pytest.mark.asyncio
async def test_workspace_resolver_uses_agent_scope_and_workspace_strict_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _wiring_module()
    resolvers: dict[str, Any] = {}

    monkeypatch.setattr(module, "build_cron_delivery_chain", lambda **_kwargs: "delivery")
    monkeypatch.setattr(
        module,
        "make_agent_run_handler",
        lambda **kwargs: resolvers.setdefault("agent", kwargs["workspace_resolver"]),
    )
    monkeypatch.setattr(
        module,
        "make_system_event_handler",
        lambda **kwargs: resolvers.setdefault("system", kwargs["workspace_resolver"]),
    )
    monkeypatch.setattr(module, "build_dream_factory", lambda **_kwargs: "dream-factory")
    monkeypatch.setattr(module, "make_memory_dream_handler", lambda **_kwargs: "dream-handler")

    async def dream_cron_registrar(**_kwargs: Any) -> None:
        return None

    config = GatewayConfig(
        workspace_dir=str(tmp_path / "workspace"),
        agents=[AgentEntryConfig(id="ops", workspace=str(tmp_path / "explicit-ops"))],
    )
    await module.register_gateway_cron_handlers(
        config=config,
        svc=SimpleNamespace(
            cron_scheduler=_FakeScheduler(),
            session_manager=object(),
            provider_selector=object(),
            tool_registry=object(),
        ),
        turn_runner=object(),
        task_runtime=object(),
        heartbeat_service=object(),
        heartbeat_loop=object(),
        subscription_manager=object(),
        channel_manager_ref=lambda: object(),
        dream_cron_registrar=dream_cron_registrar,
        configured_agent_ids=lambda config: ["main", "ops"],
        logger=_FakeLogger(),
    )

    assert resolvers["agent"]("ops") == (str(tmp_path / "explicit-ops"), True)

    config.workspace_strict = False
    assert resolvers["system"]("main") == (str(tmp_path / "workspace"), False)


@pytest.mark.asyncio
async def test_dream_cron_registrar_receives_scheduler_memory_config_and_configured_agents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _wiring_module()
    scheduler = _FakeScheduler()
    config = GatewayConfig()
    captured: dict[str, Any] = {}

    monkeypatch.setattr(module, "build_cron_delivery_chain", lambda **_kwargs: "delivery")
    monkeypatch.setattr(module, "make_agent_run_handler", lambda **_kwargs: "agent")
    monkeypatch.setattr(module, "make_system_event_handler", lambda **_kwargs: "system")
    monkeypatch.setattr(module, "build_dream_factory", lambda **_kwargs: "dream-factory")
    monkeypatch.setattr(module, "make_memory_dream_handler", lambda **_kwargs: "dream")

    async def dream_cron_registrar(**kwargs: Any) -> None:
        captured.update(kwargs)

    await module.register_gateway_cron_handlers(
        config=config,
        svc=SimpleNamespace(
            cron_scheduler=scheduler,
            session_manager=object(),
            provider_selector=object(),
            tool_registry=object(),
        ),
        turn_runner=object(),
        task_runtime=object(),
        heartbeat_service=object(),
        heartbeat_loop=object(),
        subscription_manager=object(),
        channel_manager_ref=lambda: object(),
        dream_cron_registrar=dream_cron_registrar,
        configured_agent_ids=lambda seen_config: ["main", "ops"],
        logger=_FakeLogger(),
    )

    assert captured == {
        "scheduler": scheduler,
        "memory_config": config.memory,
        "agent_ids": ["main", "ops"],
    }


@pytest.mark.asyncio
async def test_session_event_emitter_noops_without_subscription_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _wiring_module()
    captured: dict[str, Any] = {}
    delivery_calls: list[dict[str, Any]] = []
    registry = object()

    monkeypatch.setattr(module, "build_cron_delivery_chain", lambda **_kwargs: "delivery")
    monkeypatch.setattr(module, "make_agent_run_handler", lambda **_kwargs: "agent")
    monkeypatch.setattr(
        module,
        "make_system_event_handler",
        lambda **kwargs: captured.update(kwargs) or "system",
    )
    monkeypatch.setattr(module, "build_dream_factory", lambda **_kwargs: "dream-factory")
    monkeypatch.setattr(module, "make_memory_dream_handler", lambda **_kwargs: "dream")

    async def fake_deliver_session_event(**kwargs: Any) -> None:
        delivery_calls.append(kwargs)

    async def dream_cron_registrar(**_kwargs: Any) -> None:
        return None

    await module.register_gateway_cron_handlers(
        config=GatewayConfig(),
        svc=SimpleNamespace(
            cron_scheduler=_FakeScheduler(),
            session_manager=object(),
            provider_selector=object(),
            tool_registry=object(),
        ),
        turn_runner=object(),
        task_runtime=object(),
        heartbeat_service=object(),
        heartbeat_loop=object(),
        subscription_manager=None,
        channel_manager_ref=lambda: object(),
        deliver_session_event_fn=fake_deliver_session_event,
        connection_registry_getter=lambda: registry,
        dream_cron_registrar=dream_cron_registrar,
        configured_agent_ids=lambda config: ["main"],
        logger=_FakeLogger(),
    )

    await captured["session_event_emitter"](
        "agent:main:webchat:default",
        "sessions.changed",
        {"key": "agent:main:webchat:default"},
    )

    assert delivery_calls == []


@pytest.mark.asyncio
async def test_session_event_emitter_delivers_with_subscription_manager_and_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _wiring_module()
    captured: dict[str, Any] = {}
    delivery_calls: list[dict[str, Any]] = []
    subscription_manager = object()
    registry = object()
    logger = _FakeLogger()

    monkeypatch.setattr(module, "build_cron_delivery_chain", lambda **_kwargs: "delivery")
    monkeypatch.setattr(module, "make_agent_run_handler", lambda **_kwargs: "agent")
    monkeypatch.setattr(
        module,
        "make_system_event_handler",
        lambda **kwargs: captured.update(kwargs) or "system",
    )
    monkeypatch.setattr(module, "build_dream_factory", lambda **_kwargs: "dream-factory")
    monkeypatch.setattr(module, "make_memory_dream_handler", lambda **_kwargs: "dream")

    async def fake_deliver_session_event(**kwargs: Any) -> None:
        delivery_calls.append(kwargs)

    async def dream_cron_registrar(**_kwargs: Any) -> None:
        return None

    await module.register_gateway_cron_handlers(
        config=GatewayConfig(),
        svc=SimpleNamespace(
            cron_scheduler=_FakeScheduler(),
            session_manager=object(),
            provider_selector=object(),
            tool_registry=object(),
        ),
        turn_runner=object(),
        task_runtime=object(),
        heartbeat_service=object(),
        heartbeat_loop=object(),
        subscription_manager=subscription_manager,
        channel_manager_ref=lambda: object(),
        deliver_session_event_fn=fake_deliver_session_event,
        connection_registry_getter=lambda: registry,
        dream_cron_registrar=dream_cron_registrar,
        configured_agent_ids=lambda config: ["main"],
        logger=logger,
    )

    await captured["session_event_emitter"](
        "agent:main:webchat:default",
        "sessions.changed",
        {"key": "agent:main:webchat:default"},
    )

    assert delivery_calls == [
        {
            "subscription_manager": subscription_manager,
            "connection_registry": registry,
            "session_key": "agent:main:webchat:default",
            "event_name": "sessions.changed",
            "payload": {"key": "agent:main:webchat:default"},
            "logger": logger,
        }
    ]
