from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from opensquilla.gateway.config import GatewayConfig

ROOT = Path(__file__).resolve().parents[2]
BOOT = ROOT / "src/opensquilla/gateway/boot.py"


def _function_calls(path: Path, function_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
        and node.name == function_name
    )
    calls: set[str] = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                parts: list[str] = []
                current: ast.AST = node.func
                while isinstance(current, ast.Attribute):
                    parts.append(current.attr)
                    current = current.value
                if isinstance(current, ast.Name):
                    parts.append(current.id)
                calls.add(".".join(reversed(parts)))
    return calls


def test_boot_delegates_app_server_wiring_to_gateway_boundary() -> None:
    calls = _function_calls(BOOT, "start_gateway_server")

    assert "build_gateway_app_server" in calls
    assert "create_gateway_app" not in calls
    assert "GatewayServer" not in calls
    assert "uvicorn.Config" not in calls
    assert "uvicorn.Server" not in calls


def test_app_server_wiring_run_false_builds_app_and_handle_without_uvicorn() -> None:
    from opensquilla.gateway.app_server_wiring import build_gateway_app_server

    config = GatewayConfig(host="127.0.0.1", port=8123)
    state = SimpleNamespace()
    app = SimpleNamespace(state=state)
    channel_manager = object()
    services = SimpleNamespace(
        session_manager=object(),
        provider_selector=object(),
        tool_registry=object(),
        usage_tracker=object(),
        skill_loader=object(),
        cron_scheduler=object(),
        flush_service=object(),
        agent_registry=object(),
        memory_managers={"main": object()},
        memory_stores={"main": object()},
        memory_retrievers={"main": object()},
    )
    background_completion_manager = object()
    heartbeat_service = object()
    heartbeat_loop = object()
    turn_runner = object()
    task_runtime = object()
    diagnostics_state = object()
    extra_route = object()
    created_app_kwargs: dict[str, Any] = {}
    background_tasks: list[Any] = []

    class FakeGatewayServer:
        def __init__(self, *, app: Any, config: GatewayConfig) -> None:
            self.app = app
            self.config = config
            self._channel_manager = None
            self._services = None
            self._background_completion_manager = None
            self._server = None
            self._task = None

    def fake_create_gateway_app(
        received_config: GatewayConfig,
        **kwargs: Any,
    ) -> Any:
        created_app_kwargs["config"] = received_config
        created_app_kwargs.update(kwargs)
        return app

    handle = build_gateway_app_server(
        config=config,
        svc=services,
        subscription_manager=object(),
        channel_manager=channel_manager,
        turn_runner=turn_runner,
        task_runtime=task_runtime,
        heartbeat_service=heartbeat_service,
        heartbeat_loop=heartbeat_loop,
        background_completion_manager=background_completion_manager,
        diagnostics_state=diagnostics_state,
        webhook_routes=[extra_route],
        run=False,
        gateway_server_factory=FakeGatewayServer,
        create_gateway_app_fn=fake_create_gateway_app,
        uvicorn_config_factory=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("run=False must not create uvicorn.Config")
        ),
        uvicorn_server_factory=lambda _config: (_ for _ in ()).throw(
            AssertionError("run=False must not create uvicorn.Server")
        ),
        background_task_factory=background_tasks.append,
    )

    assert handle.app is app
    assert handle.config is config
    assert state.gateway_ready is False
    assert handle._channel_manager is channel_manager
    assert handle._services is services
    assert handle._background_completion_manager is background_completion_manager
    assert handle._server is None
    assert handle._task is None
    assert background_tasks == []
    assert created_app_kwargs["config"] is config
    assert created_app_kwargs["session_manager"] is services.session_manager
    assert created_app_kwargs["provider_selector"] is services.provider_selector
    assert created_app_kwargs["tool_registry"] is services.tool_registry
    assert created_app_kwargs["subscription_manager"] is not None
    assert created_app_kwargs["channel_manager"] is channel_manager
    assert created_app_kwargs["usage_tracker"] is services.usage_tracker
    assert created_app_kwargs["skill_loader"] is services.skill_loader
    assert created_app_kwargs["cron_scheduler"] is services.cron_scheduler
    assert created_app_kwargs["turn_runner"] is turn_runner
    assert created_app_kwargs["task_runtime"] is task_runtime
    assert created_app_kwargs["flush_service"] is services.flush_service
    assert created_app_kwargs["heartbeat_service"] is heartbeat_service
    assert created_app_kwargs["heartbeat_loop"] is heartbeat_loop
    assert created_app_kwargs["agent_registry"] is services.agent_registry
    assert created_app_kwargs["diagnostics_state"] is diagnostics_state
    assert created_app_kwargs["memory_managers"] is services.memory_managers
    assert created_app_kwargs["memory_stores"] is services.memory_stores
    assert created_app_kwargs["memory_retrievers"] is services.memory_retrievers
    assert created_app_kwargs["extra_routes"] == [extra_route]


def test_app_server_wiring_run_true_starts_managed_uvicorn_and_logs_public_bind() -> None:
    from opensquilla.gateway.app_server_wiring import build_gateway_app_server

    config = GatewayConfig(host="0.0.0.0", port=8124, debug=True)
    app = SimpleNamespace(state=SimpleNamespace())
    services = SimpleNamespace(
        session_manager=None,
        provider_selector=None,
        tool_registry=None,
        usage_tracker=None,
        skill_loader=None,
        cron_scheduler=None,
        flush_service=None,
        agent_registry=None,
        memory_managers={},
        memory_stores={},
        memory_retrievers={},
    )
    uvicorn_config_kwargs: dict[str, Any] = {}
    served: list[str] = []
    background_tasks: list[Any] = []
    warnings: list[tuple[str, dict[str, Any]]] = []
    infos: list[tuple[str, dict[str, Any]]] = []

    class FakeGatewayServer:
        def __init__(self, *, app: Any, config: GatewayConfig) -> None:
            self.app = app
            self.config = config
            self._channel_manager = None
            self._services = None
            self._background_completion_manager = None
            self._server = None
            self._task = None

    class FakeUvicornServer:
        def __init__(self, uv_config: Any) -> None:
            self.uv_config = uv_config

        async def serve(self) -> None:
            served.append("serve")

    class FakeLogger:
        def warning(self, event: str, **kwargs: Any) -> None:
            warnings.append((event, kwargs))

        def info(self, event: str, **kwargs: Any) -> None:
            infos.append((event, kwargs))

    def fake_uvicorn_config(**kwargs: Any) -> Any:
        uvicorn_config_kwargs.update(kwargs)
        return SimpleNamespace(kind="uvicorn-config")

    def fake_background_task(coro: Any) -> Any:
        background_tasks.append(coro)
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return SimpleNamespace(kind="task")

    handle = build_gateway_app_server(
        config=config,
        svc=services,
        subscription_manager=None,
        channel_manager=None,
        turn_runner=None,
        task_runtime=None,
        heartbeat_service=None,
        heartbeat_loop=None,
        background_completion_manager=None,
        diagnostics_state=None,
        webhook_routes=[],
        run=True,
        gateway_server_factory=FakeGatewayServer,
        create_gateway_app_fn=lambda *_args, **_kwargs: app,
        uvicorn_config_factory=fake_uvicorn_config,
        uvicorn_server_factory=FakeUvicornServer,
        background_task_factory=fake_background_task,
        public_bind_checker=lambda host: host == "0.0.0.0",
        logger=FakeLogger(),
    )

    assert handle._server is not None
    assert handle._server.uv_config.kind == "uvicorn-config"
    assert handle._task.kind == "task"
    assert len(background_tasks) == 1
    assert served == []
    assert uvicorn_config_kwargs == {
        "app": app,
        "host": "0.0.0.0",
        "port": 8124,
        "log_level": "debug",
    }
    assert warnings == [
        (
            "gateway.bind.public",
            {
                "host": "0.0.0.0",
                "port": 8124,
                "message": (
                    "gateway bound to a wildcard address; reachable from "
                    "every interface. Opt-in required — only expose behind "
                    "a trusted reverse proxy or VPN."
                ),
            },
        )
    ]
    assert infos == [("gateway.started", {"host": "0.0.0.0", "port": 8124})]
