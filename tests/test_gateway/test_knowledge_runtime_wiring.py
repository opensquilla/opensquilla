from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from opensquilla.gateway.boot import ServiceContainer, build_services
from opensquilla.gateway.config import GatewayConfig
from opensquilla.tools.registry import ToolRegistry


def _config(
    tmp_path: Path,
    *,
    enabled: bool,
    legacy_adapter: bool = False,
) -> GatewayConfig:
    return GatewayConfig(
        state_dir=str(tmp_path / "state"),
        workspace_dir=str(tmp_path / "workspace"),
        control_ui={"enabled": False},
        channels={"channels": []},
        mcp={"enabled": False},
        memory={"flush_enabled": False},
        sandbox={"auto_setup": False},
        knowledge={
            "enabled": enabled,
            "legacy_knowledge_adapter": legacy_adapter,
        },
    )


@pytest.mark.asyncio
async def test_service_container_close_stops_rag_provider_runtime_once() -> None:
    class Runtime:
        def __init__(self) -> None:
            self.stop_count = 0

        async def stop(self) -> None:
            self.stop_count += 1

    runtime = Runtime()
    services = ServiceContainer(
        config=GatewayConfig(),
        rag_provider_runtime=runtime,
        session_manager=SimpleNamespace(),
    )

    await services.close()
    await services.close()

    assert runtime.stop_count == 1


@pytest.mark.asyncio
async def test_disabled_config_does_not_construct_rag_provider_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.gateway import rag_provider_runtime as runtime_module

    calls: list[tuple[Any, Any]] = []

    def factory(config: Any, registry: Any) -> Any:
        calls.append((config, registry))
        raise AssertionError("disabled provider must not be constructed")

    monkeypatch.setattr(runtime_module, "create_rag_provider_runtime", factory)
    registry = ToolRegistry()
    services = await build_services(
        config=_config(tmp_path, enabled=False),
        tool_registry=registry,
        session_db_path=str(tmp_path / "sessions.sqlite"),
        seed_agent_workspaces=False,
    )
    try:
        assert calls == []
        assert services.rag_provider_runtime is None
        assert "knowledge_search" not in registry.list_names()
        assert "knowledge_get" not in registry.list_names()
    finally:
        await services.close()


@pytest.mark.asyncio
async def test_enabled_config_owns_one_started_rag_provider_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.gateway import rag_provider_runtime as runtime_module

    instances: list[Any] = []

    class Runtime:
        def __init__(self) -> None:
            self.start_count = 0
            self.stop_count = 0
            instances.append(self)

        async def start(self) -> None:
            self.start_count += 1

        async def stop(self) -> None:
            self.stop_count += 1

    monkeypatch.setattr(
        runtime_module,
        "create_rag_provider_runtime",
        lambda config, registry: Runtime(),
    )
    services = await build_services(
        config=_config(tmp_path, enabled=True),
        tool_registry=ToolRegistry(),
        session_db_path=str(tmp_path / "sessions.sqlite"),
        seed_agent_workspaces=False,
    )
    try:
        assert services.rag_provider_runtime is instances[0]
        assert instances[0].start_count == 1
    finally:
        await services.close()

    assert instances[0].stop_count == 1


@pytest.mark.asyncio
async def test_legacy_adapter_uses_the_same_single_runtime_wiring(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.gateway import rag_provider_runtime as runtime_module

    calls: list[tuple[Any, Any]] = []

    class Runtime:
        def __init__(self) -> None:
            self.start_count = 0
            self.stop_count = 0

        async def start(self) -> None:
            self.start_count += 1

        async def stop(self) -> None:
            self.stop_count += 1

        def snapshot(self) -> Any:
            return SimpleNamespace(state=SimpleNamespace(value="LEGACY"))

    runtime = Runtime()

    def factory(config: Any, registry: Any) -> Runtime:
        calls.append((config, registry))
        return runtime

    monkeypatch.setattr(runtime_module, "create_rag_provider_runtime", factory)
    registry = ToolRegistry()
    config = _config(tmp_path, enabled=True, legacy_adapter=True)

    services = await build_services(
        config=config,
        tool_registry=registry,
        session_db_path=str(tmp_path / "sessions.sqlite"),
        seed_agent_workspaces=False,
    )
    try:
        assert calls == [(config, registry)]
        assert config.knowledge.legacy_knowledge_adapter is True
        assert services.rag_provider_runtime is runtime
        assert runtime.start_count == 1
    finally:
        await services.close()

    assert runtime.stop_count == 1


@pytest.mark.asyncio
async def test_runtime_stop_failure_logs_only_fixed_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.gateway import boot

    warnings: list[tuple[str, dict[str, Any]]] = []

    class Runtime:
        async def stop(self) -> None:
            raise RuntimeError("secret runtime shutdown response")

    class Log:
        def warning(self, event: str, **kwargs: Any) -> None:
            warnings.append((event, kwargs))

    monkeypatch.setattr(boot, "log", Log())
    services = ServiceContainer(
        config=GatewayConfig(),
        rag_provider_runtime=Runtime(),
    )

    await services.close()

    assert warnings == [
        (
            "service_container.rag_provider_runtime_stop_failed",
            {"error_type": "RuntimeError"},
        )
    ]
    assert "secret runtime shutdown response" not in repr(warnings)
