from __future__ import annotations

import importlib
import json
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from opensquilla.cli import gateway_lifecycle
from opensquilla.cli.main import app

runner = CliRunner()


def _gateway_lifecycle_boundary_modules() -> tuple[Any, Any]:
    try:
        workflows = importlib.import_module("opensquilla.cli.gateway_lifecycle_workflows")
        presenters = importlib.import_module("opensquilla.cli.gateway_lifecycle_presenters")
    except ModuleNotFoundError as exc:
        pytest.fail(f"missing gateway lifecycle boundary module: {exc.name}")
    return workflows, presenters


def test_gateway_lifecycle_workflow_builds_manager_with_cli_host_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflows, _presenters = _gateway_lifecycle_boundary_modules()
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", "/tmp/opensquilla-gateway.toml")

    manager = workflows.build_lifecycle_manager(
        port=18888,
        bind="127.0.0.2",
        listen="0.0.0.0",
        health_timeout=2.5,
        shutdown_timeout=1.5,
    )

    assert manager.host == "0.0.0.0"
    assert manager.probe_host == "127.0.0.1"
    assert manager.port == 18888
    assert manager.config_path == "/tmp/opensquilla-gateway.toml"
    assert manager.health_timeout == 2.5
    assert manager.shutdown_timeout == 1.5


def test_gateway_lifecycle_presenter_preserves_json_payload_and_exit_code(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _workflows, presenters = _gateway_lifecycle_boundary_modules()
    result = gateway_lifecycle.GatewayLifecycleResult(
        action="start",
        state="unmanaged",
        ok=False,
        host="127.0.0.1",
        port=18790,
        managed=False,
        code=gateway_lifecycle.UNMANAGED_GATEWAY_RUNNING,
        message="A healthy gateway is already running.",
        pidfile="/tmp/gateway.json",
        log_path="/tmp/gateway.log",
    )

    with pytest.raises(typer.Exit) as exc_info:
        presenters.emit_lifecycle_result(result, json_output=True)

    assert exc_info.value.exit_code == 3
    assert json.loads(capsys.readouterr().out) == result.to_payload()


def test_gateway_start_cli_delegates_to_lifecycle_workflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflows, _presenters = _gateway_lifecycle_boundary_modules()
    calls: list[dict[str, object]] = []

    def fake_start_gateway_for_cli(**kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(workflows, "start_gateway_for_cli", fake_start_gateway_for_cli)

    result = runner.invoke(
        app,
        [
            "gateway",
            "start",
            "--listen",
            "127.0.0.2",
            "--port",
            "18888",
            "--timeout",
            "2.25",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert calls == [
        {
            "port": 18888,
            "bind": "127.0.0.1",
            "listen": "127.0.0.2",
            "health_timeout": 2.25,
            "json_output": True,
        }
    ]
