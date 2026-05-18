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
BOOT_PRELUDE = GATEWAY / "boot_prelude_wiring.py"


class FakeLogger:
    def __init__(self) -> None:
        self.infos: list[tuple[str, dict[str, Any]]] = []
        self.warnings: list[tuple[str, dict[str, Any]]] = []

    def info(self, event: str, **kwargs: Any) -> None:
        self.infos.append((event, kwargs))

    def warning(self, event: str, **kwargs: Any) -> None:
        self.warnings.append((event, kwargs))


class FakePidLock:
    def __init__(self, path: Path, events: list[str]) -> None:
        self.path = path
        self.events = events
        self.acquired = False

    def acquire(self) -> None:
        self.events.append(f"lock.acquire:{self.path}")
        self.acquired = True


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


def _call_names(function: ast.AsyncFunctionDef | ast.FunctionDef) -> list[str]:
    calls: list[str] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            calls.append(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            parts: list[str] = []
            current: ast.AST = node.func
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.append(current.id)
            calls.append(".".join(reversed(parts)))
    return calls


def test_boot_prelude_wiring_module_exports_builder_contract() -> None:
    assert BOOT_PRELUDE.exists()

    from opensquilla.gateway.boot_prelude_wiring import (
        GatewayBootPrelude,
        build_gateway_boot_prelude,
    )

    assert set(GatewayBootPrelude.__dataclass_fields__) == {"config", "pid_lock"}
    assert callable(build_gateway_boot_prelude)


def test_boot_delegates_prelude_setup_to_gateway_boundary() -> None:
    imports = _imports_from(BOOT)
    assert (
        "opensquilla.gateway.boot_prelude_wiring",
        "build_gateway_boot_prelude",
    ) in imports

    start_gateway_server = _function(BOOT, "start_gateway_server")
    calls = _call_names(start_gateway_server)
    assert "build_gateway_boot_prelude" in calls
    assert "GatewayConfig.load" not in calls
    assert "secrets.token_urlsafe" not in calls
    assert "emit_skill_filter_banner" not in calls
    assert "GatewayPidLock" not in calls
    assert "_setup_file_logging" not in calls


def test_builder_preserves_config_port_auth_logging_env_banner_and_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.gateway.boot_prelude_wiring import build_gateway_boot_prelude

    events: list[str] = []
    env: dict[str, str] = {}
    logger = FakeLogger()
    config = GatewayConfig(
        auth={"mode": "token", "token": None},
        control_ui={"enabled": False},
        port=9100,
        state_dir=str(tmp_path / "state"),
    )
    config.config_path = str(tmp_path / "gateway.toml")

    prelude = build_gateway_boot_prelude(
        config=config,
        port=9200,
        setup_file_logging=lambda received: events.append(
            f"file_logging:{received.port}"
        ),
        skill_filter_banner=lambda skills: events.append(
            f"skill_banner:{skills.filter_strategy}"
        ),
        state_path_factory=lambda received, filename: Path(received.state_dir) / filename,
        gateway_pid_lock_factory=lambda path: FakePidLock(path, events),
        token_urlsafe=lambda size: f"generated-{size}",
        environ=env,
        logger=logger,
    )

    assert prelude.config is not config
    assert prelude.config.port == 9200
    assert prelude.config.auth.token == "generated-32"
    assert "token" not in prelude.config.to_toml_dict()["auth"]
    assert env["OPENSQUILLA_GATEWAY_PORT"] == "9200"
    assert prelude.pid_lock.acquired is True
    assert events == [
        "file_logging:9200",
        "skill_banner:lexical",
        f"lock.acquire:{tmp_path / 'state'}",
    ]
    assert ("gateway.config_loaded", {"path": str(tmp_path / "gateway.toml")}) in (
        logger.infos
    )
    assert ("gateway.auth_token_generated", {}) in logger.infos
    assert ("gateway.control_ui.disabled", {}) in logger.infos


def test_builder_loads_config_from_env_when_no_explicit_config(
    tmp_path: Path,
) -> None:
    from opensquilla.gateway.boot_prelude_wiring import build_gateway_boot_prelude

    env_path = tmp_path / "from-env.toml"
    loaded_config = GatewayConfig(
        control_ui={"enabled": False},
        state_dir=str(tmp_path / "state"),
    )
    loaded_config.config_path = str(env_path)
    load_calls: list[str | None] = []

    prelude = build_gateway_boot_prelude(
        config=None,
        port=None,
        config_loader=lambda path: load_calls.append(path) or loaded_config,
        setup_file_logging=lambda _config: None,
        skill_filter_banner=lambda _skills: None,
        state_path_factory=lambda received, filename: Path(received.state_dir) / filename,
        gateway_pid_lock_factory=lambda path: FakePidLock(path, []),
        environ={"OPENSQUILLA_GATEWAY_CONFIG_PATH": str(env_path)},
        logger=FakeLogger(),
    )

    assert load_calls == [str(env_path)]
    assert prelude.config is loaded_config


def test_builder_logs_control_ui_paths_and_missing_assets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.gateway import control_ui
    from opensquilla.gateway.boot_prelude_wiring import build_gateway_boot_prelude

    template_dir = tmp_path / "missing-templates"
    static_dir = tmp_path / "missing-static"
    monkeypatch.setattr(control_ui, "_TEMPLATE_DIR", template_dir)
    monkeypatch.setattr(control_ui, "_STATIC_DIR", static_dir)
    logger = FakeLogger()

    build_gateway_boot_prelude(
        config=GatewayConfig(
            control_ui={"enabled": True, "base_path": "/console"},
            state_dir=str(tmp_path / "state"),
        ),
        setup_file_logging=lambda _config: None,
        skill_filter_banner=lambda _skills: None,
        state_path_factory=lambda received, filename: Path(received.state_dir) / filename,
        gateway_pid_lock_factory=lambda path: FakePidLock(path, []),
        environ={},
        logger=logger,
    )

    assert (
        "gateway.control_ui.templates_missing",
        {"path": str(template_dir)},
    ) in logger.warnings
    assert (
        "gateway.control_ui.static_missing",
        {"path": str(static_dir)},
    ) in logger.warnings
    assert (
        "gateway.control_ui.resolved",
        {
            "base_path": "/console",
            "templates": str(template_dir),
            "static": str(static_dir),
        },
    ) in logger.infos


@pytest.mark.asyncio
async def test_start_gateway_server_runs_prelude_before_services_and_retains_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from opensquilla.gateway import boot
    from opensquilla.gateway.boot_prelude_wiring import GatewayBootPrelude

    events: list[str] = []
    config = GatewayConfig(
        control_ui={"enabled": False},
        channels={"channels": []},
        state_dir=str(tmp_path / "state"),
    )
    pid_lock = object()

    def fake_prelude(**kwargs: Any) -> GatewayBootPrelude:
        events.append("prelude")
        assert kwargs["config"] is config
        return GatewayBootPrelude(config=config, pid_lock=pid_lock)

    async def fake_build_services(**kwargs: Any) -> Any:
        events.append("build_services")
        assert kwargs["config"] is config

        async def close() -> None:
            return None

        return SimpleNamespace(
            provider_selector=object(),
            tool_registry=object(),
            session_manager=object(),
            skill_loader=object(),
            usage_tracker=object(),
            config=config,
            memory_sync_managers={},
            model_catalog=None,
            memory_retrievers={},
            turn_capture_services={},
            flush_service=None,
            cron_scheduler=None,
            task_runtime=None,
            agent_registry=None,
            memory_managers={},
            memory_stores={},
            _turn_runner_ref=[],
            close=close,
        )

    async def fake_runtime_wiring(**_kwargs: Any) -> Any:
        return SimpleNamespace(
            heartbeat_service=object(),
            heartbeat_loop=object(),
            task_runtime=object(),
            runtime_event_bridge=object(),
            background_completion_manager=object(),
        )

    app = SimpleNamespace(state=SimpleNamespace())

    monkeypatch.setattr(boot, "build_gateway_boot_prelude", fake_prelude)
    monkeypatch.setattr(boot, "build_services", fake_build_services)
    monkeypatch.setattr(
        boot,
        "build_turn_runner_from_services",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(boot, "build_gateway_runtime_wiring", fake_runtime_wiring)
    monkeypatch.setattr(
        boot,
        "register_gateway_cron_handlers",
        lambda **_kwargs: SimpleNamespace(__await__=lambda self: iter(())),
    )

    async def fake_register_gateway_cron_handlers(**_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(
        boot,
        "register_gateway_cron_handlers",
        fake_register_gateway_cron_handlers,
    )
    monkeypatch.setattr(
        boot,
        "build_gateway_channel_manager_wiring",
        lambda **_kwargs: SimpleNamespace(channel_manager=object(), webhook_routes=[]),
    )
    monkeypatch.setattr(
        boot,
        "build_gateway_app_server",
        lambda **kwargs: boot.GatewayServer(app=app, config=kwargs["config"]),
    )

    async def fake_start_gateway_channels(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(boot, "start_gateway_channels", fake_start_gateway_channels)

    server = await boot.start_gateway_server(config=config, run=False)

    assert events[:2] == ["prelude", "build_services"]
    assert server._pid_lock is pid_lock
