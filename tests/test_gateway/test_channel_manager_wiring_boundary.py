from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import ANY

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATEWAY = ROOT / "src/opensquilla/gateway"
BOOT = GATEWAY / "boot.py"
CHANNEL_MANAGER_WIRING = GATEWAY / "channel_manager_wiring.py"


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


class FakeLogger:
    def __init__(self) -> None:
        self.infos: list[tuple[str, dict[str, Any]]] = []
        self.warnings: list[tuple[str, dict[str, Any]]] = []

    def info(self, event: str, **kwargs: Any) -> None:
        self.infos.append((event, kwargs))

    def warning(self, event: str, **kwargs: Any) -> None:
        self.warnings.append((event, kwargs))


def test_channel_manager_wiring_module_exports_builder_contract() -> None:
    assert CHANNEL_MANAGER_WIRING.exists()

    from opensquilla.gateway.channel_manager_wiring import (
        GatewayChannelManagerWiring,
        build_gateway_channel_manager_wiring,
        start_gateway_channels,
    )

    assert set(GatewayChannelManagerWiring.__dataclass_fields__) == {
        "channel_manager",
        "webhook_routes",
    }
    assert callable(build_gateway_channel_manager_wiring)
    assert callable(start_gateway_channels)


def test_boot_delegates_channel_manager_wiring_to_gateway_boundary() -> None:
    imports = _imports_from(BOOT)
    assert (
        "opensquilla.gateway.channel_manager_wiring",
        "build_gateway_channel_manager_wiring",
    ) in imports
    assert (
        "opensquilla.gateway.channel_manager_wiring",
        "start_gateway_channels",
    ) in imports

    start_gateway_server = _function(BOOT, "start_gateway_server")
    function_imports = {
        (node.module, alias.name)
        for node in ast.walk(start_gateway_server)
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    }
    assert (
        "opensquilla.channels.manager",
        "ChannelManager",
    ) not in function_imports
    assert (
        "opensquilla.gateway.channel_ingress",
        "GatewayChannelIngress",
    ) not in function_imports

    forbidden_attr_calls = {
        ("ChannelManager", "from_config"),
        ("channel_manager", "collect_webhook_routes"),
        ("channel_manager", "start_all"),
    }
    attr_calls = {
        (node.func.value.id, node.func.attr)
        for node in ast.walk(start_gateway_server)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
    }
    assert attr_calls.isdisjoint(forbidden_attr_calls)

    name_calls = {
        node.func.id
        for node in ast.walk(start_gateway_server)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "GatewayChannelIngress" not in name_calls
    assert "ChannelManager" not in name_calls


def test_builder_constructs_manager_collects_routes_and_populates_lazy_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.gateway import channel_manager_wiring

    entries = [SimpleNamespace(name="feishu"), SimpleNamespace(name="slack")]
    config = SimpleNamespace(channels=SimpleNamespace(channels=entries))
    svc = SimpleNamespace(session_manager=object())
    turn_runner = object()
    subscription_manager = object()
    runtime_event_bridge = object()
    task_runtime = object()
    heartbeat_service = object()
    diagnostics_state = object()
    dispatcher = object()
    context_factory = object()
    manager = SimpleNamespace(collect_webhook_routes=lambda: ["route-a", "route-b"])
    holder: list[Any] = [None]
    logger = FakeLogger()
    captured_factory: dict[str, Any] = {}
    captured_from_config: dict[str, Any] = {}

    class FakeGatewayChannelIngress:
        pass

    class FakeChannelManager:
        @classmethod
        def from_config(cls, received_entries: list[Any], **kwargs: Any) -> Any:
            captured_from_config["entries"] = received_entries
            captured_from_config["kwargs"] = kwargs
            return manager

    def fake_rpc_context_factory_builder(
        received_svc: Any,
        received_config: Any,
        **kwargs: Any,
    ) -> Any:
        captured_factory["svc"] = received_svc
        captured_factory["config"] = received_config
        captured_factory["kwargs"] = kwargs
        return context_factory

    monkeypatch.setattr(channel_manager_wiring, "ChannelManager", FakeChannelManager)
    monkeypatch.setattr(
        channel_manager_wiring,
        "GatewayChannelIngress",
        FakeGatewayChannelIngress,
    )
    monkeypatch.setattr(channel_manager_wiring, "get_dispatcher", lambda: dispatcher)

    wiring = channel_manager_wiring.build_gateway_channel_manager_wiring(
        config=config,
        svc=svc,
        turn_runner=turn_runner,
        subscription_manager=subscription_manager,
        channel_manager=None,
        channel_manager_ref=lambda: holder[0],
        set_channel_manager_ref=lambda value: holder.__setitem__(0, value),
        runtime_event_bridge=runtime_event_bridge,
        task_runtime=task_runtime,
        heartbeat_service=heartbeat_service,
        diagnostics_state=diagnostics_state,
        channel_rpc_context_factory_builder=fake_rpc_context_factory_builder,
        logger=logger,
    )

    assert wiring.channel_manager is manager
    assert wiring.webhook_routes == ["route-a", "route-b"]
    assert holder[0] is manager
    assert captured_factory == {
        "svc": svc,
        "config": config,
        "kwargs": {
            "subscription_manager": subscription_manager,
            "channel_manager_ref": ANY,
            "turn_runner": turn_runner,
            "heartbeat_service": heartbeat_service,
            "diagnostics_state": diagnostics_state,
        },
    }
    assert captured_factory["kwargs"]["channel_manager_ref"]() is manager
    assert captured_from_config["entries"] is entries
    assert captured_from_config["kwargs"]["turn_runner"] is turn_runner
    assert captured_from_config["kwargs"]["session_manager"] is svc.session_manager
    assert captured_from_config["kwargs"]["event_bridge"] is runtime_event_bridge
    assert captured_from_config["kwargs"]["config"] is config
    assert captured_from_config["kwargs"]["task_runtime"] is task_runtime
    assert captured_from_config["kwargs"]["rpc_dispatcher"] is dispatcher
    assert captured_from_config["kwargs"]["channel_rpc_context_factory"] is context_factory
    assert isinstance(
        captured_from_config["kwargs"]["channel_ingress"],
        FakeGatewayChannelIngress,
    )
    assert logger.infos == [
        ("gateway.channels_built", {"count": 2, "webhooks": 2}),
    ]


def test_builder_returns_injected_manager_and_populates_lazy_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.gateway import channel_manager_wiring

    injected_manager = object()
    holder: list[Any] = [None]
    logger = FakeLogger()

    class ExplodingChannelManager:
        @classmethod
        def from_config(cls, *_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("injected managers must not be constructed")

    monkeypatch.setattr(channel_manager_wiring, "ChannelManager", ExplodingChannelManager)

    wiring = channel_manager_wiring.build_gateway_channel_manager_wiring(
        config=SimpleNamespace(channels=SimpleNamespace(channels=[object()])),
        svc=SimpleNamespace(session_manager=object()),
        turn_runner=object(),
        subscription_manager=object(),
        channel_manager=injected_manager,
        channel_manager_ref=lambda: holder[0],
        set_channel_manager_ref=lambda value: holder.__setitem__(0, value),
        runtime_event_bridge=object(),
        task_runtime=object(),
        heartbeat_service=object(),
        diagnostics_state=object(),
        channel_rpc_context_factory_builder=lambda *_args, **_kwargs: object(),
        logger=logger,
    )

    assert wiring.channel_manager is injected_manager
    assert wiring.webhook_routes == []
    assert holder[0] is injected_manager
    assert logger.infos == []
    assert logger.warnings == []


@pytest.mark.asyncio
async def test_start_gateway_channels_logs_successes_and_failures() -> None:
    from opensquilla.gateway.channel_manager_wiring import start_gateway_channels

    logger = FakeLogger()

    class FakeChannelManager:
        async def start_all(self) -> dict[str, bool]:
            return {"feishu": True, "slack": False}

        def start_errors(self) -> dict[str, dict[str, str]]:
            return {
                "slack": {
                    "error_type": "RuntimeError",
                    "error": "boom",
                    "exception": "RuntimeError('boom')",
                },
            }

    await start_gateway_channels(FakeChannelManager(), logger=logger)
    await start_gateway_channels(None, logger=logger)

    assert logger.infos == [
        ("gateway.channel_started", {"channel": "feishu"}),
    ]
    assert logger.warnings == [
        (
            "gateway.channel_failed",
            {
                "channel": "slack",
                "error_type": "RuntimeError",
                "error": "boom",
                "exception": "RuntimeError('boom')",
            },
        ),
    ]
