"""``opensquilla gateway reload`` CLI — calls the admin ``config.reload`` RPC.

Offline: the gateway client is replaced by a fake, no network, no credentials.
"""

from __future__ import annotations

import json
from typing import Any

from typer.testing import CliRunner

from opensquilla.cli.main import app

runner = CliRunner()


class FakeGatewayClient:
    calls: list[tuple[str, Any]] = []
    payload: dict[str, Any] = {}

    async def connect(self, url: str, *, token=None) -> None:
        type(self).calls.append(("connect", url))

    async def close(self) -> None:
        type(self).calls.append(("close", None))

    async def call(self, method: str, params: dict | None = None) -> Any:
        type(self).calls.append((method, params or {}))
        return type(self).payload


def _install(monkeypatch, payload: dict[str, Any]) -> type[FakeGatewayClient]:
    FakeGatewayClient.calls = []
    FakeGatewayClient.payload = payload
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", FakeGatewayClient)
    return FakeGatewayClient


def test_gateway_reload_calls_rpc_and_prints_summary(monkeypatch) -> None:
    _install(
        monkeypatch,
        {
            "ok": True,
            "path": "/tmp/example-config.toml",
            "restartRequired": True,
            "restartSections": ["channels"],
            "liveApplied": ["naming", "skills"],
        },
    )

    result = runner.invoke(app, ["gateway", "reload"])

    assert result.exit_code == 0, result.output
    assert ("config.reload", {}) in FakeGatewayClient.calls
    assert "naming, skills" in result.stdout
    assert "Restart required" in result.stdout
    assert "channels" in result.stdout


def test_gateway_reload_no_restart_needed(monkeypatch) -> None:
    _install(
        monkeypatch,
        {
            "ok": True,
            "path": "/tmp/example-config.toml",
            "restartRequired": False,
            "restartSections": [],
            "liveApplied": [],
        },
    )

    result = runner.invoke(app, ["gateway", "reload"])

    assert result.exit_code == 0, result.output
    assert "(no changes)" in result.stdout
    assert "Restart required" not in result.stdout


def test_gateway_reload_failure_exits_nonzero(monkeypatch) -> None:
    _install(
        monkeypatch,
        {"ok": False, "path": "/tmp/example-config.toml", "error": "bad toml"},
    )

    result = runner.invoke(app, ["gateway", "reload"])

    assert result.exit_code == 1
    assert "Reload failed" in result.stderr
    assert "bad toml" in result.stderr
    assert "left unchanged" in result.stderr


def test_gateway_reload_json_output(monkeypatch) -> None:
    _install(
        monkeypatch,
        {
            "ok": True,
            "path": "/tmp/example-config.toml",
            "restartRequired": False,
            "restartSections": [],
            "liveApplied": ["naming"],
        },
    )

    result = runner.invoke(app, ["gateway", "reload", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["liveApplied"] == ["naming"]
