from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from opensquilla.gateway.config import GatewayConfig
from opensquilla.tools.registry import ToolRegistry


@dataclass
class FakeMemoryManager:
    store: object
    retriever: object
    sync_manager: object
    turn_capture: object


@pytest.mark.asyncio
async def test_memory_gateway_runtime_builds_views_and_registers_tools(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.memory.gateway_runtime import build_memory_gateway_runtime

    managers = {
        "main": FakeMemoryManager(object(), object(), object(), object()),
        "ops": FakeMemoryManager(object(), object(), object(), object()),
    }
    captured: dict[str, Any] = {}

    async def fake_build_memory_managers(
        config: GatewayConfig,
        agent_ids: list[str],
    ) -> dict[str, FakeMemoryManager]:
        captured["build_config"] = config
        captured["agent_ids"] = agent_ids
        return managers

    def fake_create_memory_tools(**kwargs: Any) -> None:
        captured["tool_kwargs"] = kwargs

    monkeypatch.setattr(
        "opensquilla.memory.manager.build_memory_managers",
        fake_build_memory_managers,
    )
    monkeypatch.setattr(
        "opensquilla.tools.builtin.memory_tools.create_memory_tools",
        fake_create_memory_tools,
    )

    class FakeTurnRunner:
        def __init__(self) -> None:
            self.refreshed: list[str] = []

        def refresh_memory_snapshot(self, agent_id: str) -> None:
            self.refreshed.append(agent_id)

    registry = ToolRegistry()
    turn_runner_ref = [FakeTurnRunner()]
    config = GatewayConfig(
        state_dir=str(tmp_path / "state"),
        workspace_dir=str(tmp_path / "workspace"),
        memory={"source": "workspace"},
    )

    runtime = await build_memory_gateway_runtime(
        config=config,
        tool_registry=registry,
        agent_ids=["main", "ops"],
        turn_runner_ref=turn_runner_ref,
    )

    assert captured["build_config"] is config
    assert captured["agent_ids"] == ["main", "ops"]
    assert runtime.memory_managers == managers
    assert runtime.memory_stores == {aid: mgr.store for aid, mgr in managers.items()}
    assert runtime.memory_retrievers == {aid: mgr.retriever for aid, mgr in managers.items()}
    assert runtime.memory_sync_managers == {
        aid: mgr.sync_manager for aid, mgr in managers.items()
    }
    assert runtime.turn_capture_services == {
        aid: mgr.turn_capture for aid, mgr in managers.items()
    }
    assert runtime.memory_watchers == [mgr.sync_manager for mgr in managers.values()]

    tool_kwargs = captured["tool_kwargs"]
    assert tool_kwargs["stores"] == runtime.memory_stores
    assert tool_kwargs["retrievers"] == runtime.memory_retrievers
    assert tool_kwargs["memory_base"] == config.state_dir
    assert tool_kwargs["registry"] is registry
    assert tool_kwargs["memory_source"] == "workspace"
    assert tool_kwargs["memory_config"] is config.memory
    assert tool_kwargs["workspace_base"] == config.workspace_dir

    tool_kwargs["on_memory_write"]("ops")
    assert turn_runner_ref[0].refreshed == ["ops"]


@pytest.mark.asyncio
async def test_memory_gateway_runtime_skips_tool_registration_without_views(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.memory.gateway_runtime import build_memory_gateway_runtime

    async def fake_build_memory_managers(
        _config: GatewayConfig,
        _agent_ids: list[str],
    ) -> dict[str, FakeMemoryManager]:
        return {}

    def fake_create_memory_tools(**_kwargs: Any) -> None:
        raise AssertionError("create_memory_tools should not be called without views")

    monkeypatch.setattr(
        "opensquilla.memory.manager.build_memory_managers",
        fake_build_memory_managers,
    )
    monkeypatch.setattr(
        "opensquilla.tools.builtin.memory_tools.create_memory_tools",
        fake_create_memory_tools,
    )

    runtime = await build_memory_gateway_runtime(
        config=GatewayConfig(state_dir=str(tmp_path / "state")),
        tool_registry=ToolRegistry(),
        agent_ids=["main"],
        turn_runner_ref=[],
    )

    assert runtime.memory_managers == {}
    assert runtime.memory_stores == {}
    assert runtime.memory_retrievers == {}
    assert runtime.memory_watchers == []
