from __future__ import annotations

import json
from typing import Any

from typer.testing import CliRunner

from opensquilla.cli.main import app

runner = CliRunner()


class FakeGatewayClient:
    calls: list[tuple[str, Any]] = []
    rpc_payloads: dict[str, Any] = {}

    async def connect(self, url: str) -> None:
        type(self).calls.append(("connect", url))

    async def close(self) -> None:
        type(self).calls.append(("close", None))

    async def call(self, method: str, params: dict | None = None) -> Any:
        type(self).calls.append((method, params or {}))
        return type(self).rpc_payloads.get(method, {})


def _install_fake_gateway(monkeypatch) -> type[FakeGatewayClient]:
    FakeGatewayClient.calls = []
    FakeGatewayClient.rpc_payloads = {}
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", FakeGatewayClient)
    return FakeGatewayClient


def test_cron_json_commands_preserve_gateway_rpc_payloads(monkeypatch) -> None:
    fake = _install_fake_gateway(monkeypatch)
    fake.rpc_payloads = {
        "cron.list": [{"id": "job-1", "name": "Daily", "agentId": "main"}],
        "cron.status": {"id": "job-1", "name": "Daily"},
        "cron.add": {"id": "job-2", "expression": "*/5 * * * *"},
        "cron.update": {"id": "job-1", "enabled": False},
        "cron.runs": [{"id": "run-1", "status": "ok"}],
    }

    list_result = runner.invoke(app, ["cron", "list", "--agent", "main", "--json"])
    status_result = runner.invoke(app, ["cron", "status", "job-1", "--json"])
    add_result = runner.invoke(
        app,
        [
            "cron",
            "add",
            "--expression",
            "*/5 * * * *",
            "--text",
            "check in",
            "--name",
            "daily check",
            "--agent",
            "main",
            "--session-target",
            "isolated",
            "--timeout",
            "12.5",
            "--json",
        ],
    )
    update_result = runner.invoke(
        app,
        [
            "cron",
            "update",
            "job-1",
            "--expression",
            "*/10 * * * *",
            "--text",
            "new text",
            "--name",
            "new name",
            "--disabled",
            "--timeout",
            "7",
            "--json",
        ],
    )
    remove_result = runner.invoke(app, ["cron", "remove", "job-1", "--yes", "--json"])
    run_result = runner.invoke(app, ["cron", "run", "job-1", "--yes", "--json"])
    runs_result = runner.invoke(app, ["cron", "runs", "job-1", "--limit", "3", "--json"])

    assert list_result.exit_code == 0, list_result.stdout
    assert status_result.exit_code == 0, status_result.stdout
    assert add_result.exit_code == 0, add_result.stdout
    assert update_result.exit_code == 0, update_result.stdout
    assert remove_result.exit_code == 0, remove_result.stdout
    assert run_result.exit_code == 0, run_result.stdout
    assert runs_result.exit_code == 0, runs_result.stdout
    assert json.loads(list_result.stdout) == fake.rpc_payloads["cron.list"]
    assert json.loads(remove_result.stdout) == {"id": "job-1", "removed": True}
    assert ("cron.list", {"agentId": "main"}) in fake.calls
    assert ("cron.status", {"id": "job-1"}) in fake.calls
    assert (
        "cron.add",
        {
            "expression": "*/5 * * * *",
            "text": "check in",
            "sessionTarget": "isolated",
            "name": "daily check",
            "agentId": "main",
            "timeout": 12.5,
        },
    ) in fake.calls
    assert (
        "cron.update",
        {
            "id": "job-1",
            "expression": "*/10 * * * *",
            "text": "new text",
            "name": "new name",
            "enabled": False,
            "timeout": 7.0,
        },
    ) in fake.calls
    assert ("cron.remove", {"id": "job-1"}) in fake.calls
    assert ("cron.run", {"id": "job-1"}) in fake.calls
    assert ("cron.runs", {"id": "job-1", "limit": 3}) in fake.calls


def test_cron_run_requires_confirmation_before_gateway_call(monkeypatch) -> None:
    fake = _install_fake_gateway(monkeypatch)

    result = runner.invoke(app, ["cron", "run", "job-1", "--json"])

    assert result.exit_code == 2
    assert result.stdout == ""
    assert json.loads(result.stderr)["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert fake.calls == []


def test_cron_human_output_preserves_table_titles_and_empty_states(monkeypatch) -> None:
    fake = _install_fake_gateway(monkeypatch)
    fake.rpc_payloads = {
        "cron.list": [{"id": "job-1", "name": "Daily", "agentId": "main"}],
        "cron.runs": [{"id": "run-1", "status": "ok"}],
    }

    jobs_result = runner.invoke(app, ["cron", "list"])
    runs_result = runner.invoke(app, ["cron", "runs", "job-1"])

    fake.rpc_payloads = {"cron.list": [], "cron.runs": []}
    empty_jobs_result = runner.invoke(app, ["cron", "list"])
    empty_runs_result = runner.invoke(app, ["cron", "runs", "job-1"])

    assert jobs_result.exit_code == 0, jobs_result.stdout
    assert runs_result.exit_code == 0, runs_result.stdout
    assert "Cron jobs" in jobs_result.stdout
    assert "Cron runs" in runs_result.stdout
    assert empty_jobs_result.stdout.strip() == "No cron jobs."
    assert empty_runs_result.stdout.strip() == "No cron runs."
