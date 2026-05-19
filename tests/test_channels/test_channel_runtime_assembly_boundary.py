from __future__ import annotations

import ast
import inspect
from types import SimpleNamespace
from typing import Any

from opensquilla.channels import manager as manager_module
from opensquilla.channels.entries import ConfiguredChannelEntry
from opensquilla.channels.manager import ChannelManager
from opensquilla.channels.runtime_assembly import (
    build_channel_runtime_assembly,
    collect_channel_webhook_routes,
)


class _FakeLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def info(self, event: str, **kw: Any) -> None:
        self.events.append((event, kw))

    def warning(self, event: str, **kw: Any) -> None:
        self.events.append((event, kw))


class _FakeAdapter:
    transport_name = "webhook"

    def __init__(self, route_path: str = "/hook") -> None:
        self.route_path = route_path

    def create_webhook_route(self) -> Any:
        return SimpleNamespace(path=self.route_path)


class _WebsocketAdapter(_FakeAdapter):
    transport_name = "websocket"

    def create_webhook_route(self) -> Any:  # pragma: no cover - must not be called
        raise AssertionError("non-webhook transports must not create webhook routes")


def test_channel_runtime_assembly_owns_adapter_metadata(monkeypatch: Any) -> None:
    import opensquilla.channels.runtime_assembly as runtime_assembly

    logger = _FakeLogger()

    def fake_build(entry: Any) -> Any:
        if entry.type == "unknown":
            return None
        return _FakeAdapter(route_path=f"/{entry.name}")

    monkeypatch.setattr(runtime_assembly, "build_managed_channel", fake_build)

    assembly = build_channel_runtime_assembly(
        [
            ConfiguredChannelEntry(name="disabled", type="slack", enabled=False),
            ConfiguredChannelEntry(
                name="alpha",
                type="slack",
                enabled=True,
                agent_id="agent-a",
                debounce_window_s=0.2,
            ),
            ConfiguredChannelEntry(name="missing", type="unknown", enabled=True),
        ],
        logger=logger,
    )

    assert list(assembly.channels) == ["alpha"]
    assert assembly.agent_ids == {"alpha": "agent-a"}
    assert assembly.channel_types == {"alpha": "slack"}
    assert getattr(assembly.channels["alpha"], "debounce_window_s") == 0.2
    assert ("channel.skipped_disabled", {"name": "disabled"}) in logger.events
    assert ("channel.unknown_type", {"type": "unknown", "name": "missing"}) in logger.events


def test_channel_webhook_routes_are_collected_by_transport_boundary() -> None:
    logger = _FakeLogger()

    routes = collect_channel_webhook_routes(
        {
            "hook": _FakeAdapter("/hook"),
            "socket": _WebsocketAdapter("/socket"),
            "plain": SimpleNamespace(transport_name="webhook"),
        },
        logger=logger,
    )

    assert [route.path for route in routes] == ["/hook"]
    assert (
        "channel.webhook_route_collected",
        {"channel": "hook", "path": "/hook"},
    ) in logger.events


def test_channel_manager_delegates_adapter_and_webhook_boundaries(monkeypatch: Any) -> None:
    import opensquilla.channels.runtime_assembly as runtime_assembly

    fake_adapter = _FakeAdapter("/alpha")

    def fake_build(entries: list[Any], *, logger: Any) -> Any:
        assert [entry.name for entry in entries] == ["alpha"]
        return runtime_assembly.ChannelRuntimeAssembly(
            channels={"alpha": fake_adapter},
            agent_ids={"alpha": "agent-a"},
            channel_types={"alpha": "slack"},
        )

    monkeypatch.setattr(manager_module, "build_channel_runtime_assembly", fake_build)
    manager = ChannelManager.from_config(
        [ConfiguredChannelEntry(name="alpha", type="slack", agent_id="agent-a")],
        turn_runner=object(),
        session_manager=object(),
    )

    assert dict(manager.items()) == {"alpha": fake_adapter}
    assert manager._agent_ids == {"alpha": "agent-a"}
    assert manager._channel_types == {"alpha": "slack"}

    captured_channels: dict[str, Any] = {}

    def fake_collect(channels: dict[str, Any], *, logger: Any) -> list[Any]:
        captured_channels.update(channels)
        return [SimpleNamespace(path="/delegated")]

    monkeypatch.setattr(manager_module, "collect_channel_webhook_routes", fake_collect)
    assert [route.path for route in manager.collect_webhook_routes()] == ["/delegated"]
    assert captured_channels == {"alpha": fake_adapter}


def test_channel_manager_no_longer_owns_adapter_or_route_collection() -> None:
    source = inspect.getsource(manager_module)
    tree = ast.parse(source)
    manager_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ChannelManager"
    )
    method_sources = {
        node.name: ast.get_source_segment(source, node) or ""
        for node in manager_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert "build_managed_channel" not in source
    assert "create_webhook_route" not in method_sources["collect_webhook_routes"]
    assert "build_channel_runtime_assembly" in method_sources["from_config"]
    assert "collect_channel_webhook_routes" in method_sources["collect_webhook_routes"]
