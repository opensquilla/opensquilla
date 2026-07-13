from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from opensquilla.gateway.boot import ServiceContainer, build_services
from opensquilla.gateway.config import GatewayConfig
from opensquilla.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_service_container_close_stops_knowledge_runtime_once() -> None:
    class Runtime:
        def __init__(self) -> None:
            self.stop_count = 0

        async def stop(self) -> None:
            self.stop_count += 1

    runtime = Runtime()
    services = ServiceContainer(
        config=GatewayConfig(),
        knowledge_runtime=runtime,
        session_manager=SimpleNamespace(),
    )

    await services.close()
    await services.close()

    assert runtime.stop_count == 1


@pytest.mark.asyncio
async def test_build_services_owns_one_started_knowledge_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.knowledge import runtime as runtime_module
    from opensquilla.tools.builtin import knowledge_tools

    instances: list[Any] = []
    tool_kwargs: dict[str, Any] = {}

    class Runtime:
        def __init__(
            self,
            backend_provider: Any,
            *,
            enabled_provider: Any,
            ttl_seconds_provider: Any,
        ) -> None:
            self.backend_provider = backend_provider
            self.enabled_provider = enabled_provider
            self.ttl_seconds_provider = ttl_seconds_provider
            self.start_count = 0
            self.stop_count = 0
            instances.append(self)

        async def start(self) -> None:
            self.start_count += 1

        async def stop(self) -> None:
            self.stop_count += 1

    def capture_tools(*, runtime: Any, registry: Any) -> None:
        tool_kwargs.update(runtime=runtime, registry=registry)

    monkeypatch.setattr(runtime_module, "KnowledgeRuntime", Runtime)
    monkeypatch.setattr(knowledge_tools, "create_knowledge_tools", capture_tools)
    config = GatewayConfig(
        state_dir=str(tmp_path / "state"),
        workspace_dir=str(tmp_path / "workspace"),
        control_ui={"enabled": False},
        channels={"channels": []},
        mcp={"enabled": False},
        memory={"flush_enabled": False},
        sandbox={"auto_setup": False},
    )
    registry = ToolRegistry()

    services = await build_services(
        config=config,
        tool_registry=registry,
        session_db_path=str(tmp_path / "sessions.sqlite"),
        seed_agent_workspaces=False,
    )
    try:
        assert len(instances) == 1
        runtime = instances[0]
        assert services.knowledge_runtime is runtime
        assert runtime.start_count == 1
        assert tool_kwargs == {"runtime": runtime, "registry": registry}
        assert runtime.enabled_provider() is config.knowledge.enabled
        assert runtime.ttl_seconds_provider() == config.knowledge.capability_ttl_seconds
    finally:
        await services.close()

    assert instances[0].stop_count == 1


@pytest.mark.asyncio
async def test_build_services_does_not_retry_runtime_capable_tool_type_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.knowledge import runtime as runtime_module
    from opensquilla.tools.builtin import knowledge_tools

    instances: list[Any] = []
    tool_calls: list[dict[str, Any]] = []

    class Runtime:
        def __init__(
            self,
            backend_provider: Any,
            *,
            enabled_provider: Any,
            ttl_seconds_provider: Any,
        ) -> None:
            instances.append(self)

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

    def failing_tools(**kwargs: Any) -> None:
        tool_calls.append(kwargs)
        raise TypeError("unexpected keyword argument 'runtime': secret internal failure")

    monkeypatch.setattr(runtime_module, "KnowledgeRuntime", Runtime)
    monkeypatch.setattr(knowledge_tools, "create_knowledge_tools", failing_tools)
    config = GatewayConfig(
        state_dir=str(tmp_path / "state"),
        workspace_dir=str(tmp_path / "workspace"),
        control_ui={"enabled": False},
        channels={"channels": []},
        mcp={"enabled": False},
        memory={"flush_enabled": False},
        sandbox={"auto_setup": False},
    )
    registry = ToolRegistry()

    services = await build_services(
        config=config,
        tool_registry=registry,
        session_db_path=str(tmp_path / "sessions.sqlite"),
        seed_agent_workspaces=False,
    )
    try:
        assert len(instances) == 1
        assert tool_calls == [{"runtime": instances[0], "registry": registry}]
    finally:
        await services.close()


@pytest.mark.asyncio
async def test_service_container_stop_failure_logs_only_fixed_metadata(
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
        knowledge_runtime=Runtime(),
    )

    await services.close()

    assert warnings == [
        (
            "service_container.knowledge_runtime_stop_failed",
            {"error_type": "RuntimeError"},
        )
    ]
    assert "secret runtime shutdown response" not in repr(warnings)
