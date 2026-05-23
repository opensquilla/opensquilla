from __future__ import annotations

import json
from typing import Any

from typer.testing import CliRunner

from opensquilla.cli.main import app

runner = CliRunner()


class _FakeGatewayClient:
    calls: list[tuple[str, dict[str, Any]]] = []
    payloads: dict[str, Any] = {}

    async def connect(self, url: str, *, token: str | None = None) -> None:
        type(self).calls.append(("connect", {"url": url, "token": token}))

    async def close(self) -> None:
        type(self).calls.append(("close", {}))

    async def call(self, method: str, params: dict | None = None) -> Any:
        type(self).calls.append((method, params or {}))
        return type(self).payloads.get(method, {})


def _install_fake_gateway(monkeypatch) -> type[_FakeGatewayClient]:
    _FakeGatewayClient.calls = []
    _FakeGatewayClient.payloads = {
        "diagnostics.status": {
            "enabled": False,
            "detail": "off",
            "raw_turn_call": {"enabled": False, "source": "off", "env_override": False},
            "applies_to": "next_turn",
        },
        "diagnostics.set": {
            "enabled": True,
            "detail": "standard",
            "raw_turn_call": {"enabled": False, "source": "off", "env_override": False},
            "applies_to": "next_turn",
        },
    }
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", _FakeGatewayClient)
    return _FakeGatewayClient


def test_diagnostics_status_uses_status_rpc(monkeypatch) -> None:
    fake = _install_fake_gateway(monkeypatch)

    result = runner.invoke(app, ["diagnostics", "status", "--json"])

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["detail"] == "off"
    assert ("diagnostics.status", {}) in fake.calls


def test_diagnostics_on_raw_uses_set_rpc(monkeypatch) -> None:
    fake = _install_fake_gateway(monkeypatch)

    result = runner.invoke(app, ["diagnostics", "on", "--raw", "--json"])

    assert result.exit_code == 0, result.stdout
    assert ("diagnostics.set", {"enabled": True, "raw": True}) in fake.calls


def test_diagnostics_off_uses_set_rpc(monkeypatch) -> None:
    fake = _install_fake_gateway(monkeypatch)

    result = runner.invoke(app, ["diagnostics", "off", "--json"])

    assert result.exit_code == 0, result.stdout
    assert ("diagnostics.set", {"enabled": False}) in fake.calls
