from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from opensquilla.cli.main import app

runner = CliRunner()


class FakeGatewayClient:
    calls: list[tuple[str, Any]] = []
    rpc_payloads: dict[str, Any] = {}
    model_rows: list[dict[str, Any]] = []
    sessions_payload: dict[str, Any] = {"sessions": [], "count": 0}
    cost_payload: dict[str, Any] = {"breakdown": [], "totalCostUsd": 0.0}

    async def connect(self, url: str) -> None:
        type(self).calls.append(("connect", url))

    async def close(self) -> None:
        type(self).calls.append(("close", None))

    async def call(self, method: str, params: dict | None = None) -> Any:
        type(self).calls.append((method, params or {}))
        return type(self).rpc_payloads.get(method, {})

    async def list_models(
        self,
        provider: str | None = None,
        capabilities: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        type(self).calls.append(
            ("models.list", {"provider": provider, "capabilities": capabilities})
        )
        return type(self).model_rows

    async def list_sessions(self, limit: int = 50) -> dict[str, Any]:
        type(self).calls.append(("sessions.list", {"limit": limit}))
        return type(self).sessions_payload

    async def resolve_session(self, key: str) -> dict[str, Any]:
        type(self).calls.append(("sessions.resolve", {"key": key}))
        return type(self).rpc_payloads.get("sessions.resolve", {"key": key})

    async def preview_sessions(
        self,
        keys: list[str] | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        type(self).calls.append(("sessions.preview", {"keys": keys, "limit": limit}))
        return type(self).rpc_payloads.get("sessions.preview", {"previews": []})

    async def abort_session(self, key: str) -> dict[str, Any]:
        type(self).calls.append(("sessions.abort", {"key": key}))
        return type(self).rpc_payloads.get("sessions.abort", {"aborted": False, "key": key})

    async def usage_cost(self) -> dict[str, Any]:
        type(self).calls.append(("usage.cost", {}))
        return type(self).cost_payload


class FailingConnectGatewayClient(FakeGatewayClient):
    async def connect(self, url: str) -> None:
        raise SystemExit("gateway offline")


class RPCFailGatewayClient(FakeGatewayClient):
    async def call(self, method: str, params: dict | None = None) -> Any:
        from opensquilla.cli.gateway_client import GatewayRPCError

        type(self).calls.append((method, params or {}))
        raise GatewayRPCError(
            method,
            code="UNAUTHORIZED",
            message="operator.admin scope required",
            data={"scope": "operator.admin"},
        )


def _install_fake_gateway(monkeypatch, cls=FakeGatewayClient) -> type[FakeGatewayClient]:
    cls.calls = []
    cls.rpc_payloads = {}
    cls.model_rows = []
    cls.sessions_payload = {"sessions": [], "count": 0}
    cls.cost_payload = {"breakdown": [], "totalCostUsd": 0.0}
    monkeypatch.setattr("opensquilla.cli.gateway_client.GatewayClient", cls)
    return cls


def test_catalog_list_json_surfaces(tmp_path: Path, monkeypatch):
    target = tmp_path / "c.toml"
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))
    runner.invoke(app, ["channels", "add", "slack", "--name", "w", "--token", "supersecret"])

    providers = runner.invoke(app, ["providers", "list", "--json"])
    search = runner.invoke(app, ["search", "list", "--json"])
    channels = runner.invoke(app, ["channels", "list", "--json"])

    assert providers.exit_code == 0, providers.stdout
    assert search.exit_code == 0, search.stdout
    assert channels.exit_code == 0, channels.stdout
    assert any(row["providerId"] == "openrouter" for row in json.loads(providers.stdout))
    assert any(row["providerId"] == "brave" for row in json.loads(search.stdout))
    channel_payload = json.loads(channels.stdout)
    assert channel_payload[0]["name"] == "w"
    assert "supersecret" not in channels.stdout
    assert "***" in channels.stdout


def test_models_list_json_uses_gateway_client(monkeypatch):
    fake = _install_fake_gateway(monkeypatch)
    fake.model_rows = [
        {
            "id": "model-a",
            "provider": "openrouter",
            "contextWindow": 123,
            "capabilities": ["chat"],
        }
    ]

    result = runner.invoke(app, ["models", "list", "--provider", "openrouter", "--json"])

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)[0]["id"] == "model-a"
    assert ("models.list", {"provider": "openrouter", "capabilities": None}) in fake.calls


def test_config_get_honors_env_path_and_redacts(tmp_path: Path, monkeypatch):
    target = tmp_path / "opensquilla.toml"
    target.write_text(
        "search_api_key = \"secret\"\n"
        "[llm]\nprovider = \"openrouter\"\nmodel = \"test/model\"\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", str(target))

    model_result = runner.invoke(app, ["config", "get", "llm.model"])
    key_result = runner.invoke(app, ["config", "get", "search_api_key"])
    all_result = runner.invoke(app, ["config", "get"])

    assert model_result.exit_code == 0, model_result.stdout
    assert "test/model" in model_result.stdout
    assert key_result.exit_code == 0, key_result.stdout
    assert "[redacted]" in key_result.stdout
    assert "secret" not in key_result.stdout
    assert all_result.exit_code == 0, all_result.stdout
    assert "[redacted]" in all_result.stdout
    assert "secret" not in all_result.stdout


def test_config_get_explicit_config_path_wins(tmp_path: Path):
    target = tmp_path / "explicit.toml"
    target.write_text("[llm]\nmodel = \"explicit/model\"\n", encoding="utf-8")

    result = runner.invoke(app, ["config", "get", "llm.model", "--config", str(target)])

    assert result.exit_code == 0, result.stdout
    assert "explicit/model" in result.stdout


def test_gateway_json_errors_go_to_stderr(monkeypatch):
    _install_fake_gateway(monkeypatch, FailingConnectGatewayClient)

    result = runner.invoke(app, ["models", "list", "--json"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert json.loads(result.stderr)["error"]["code"] == "GATEWAY_UNAVAILABLE"


def test_skills_view_and_update_use_gateway_rpc(monkeypatch):
    fake = _install_fake_gateway(monkeypatch)
    fake.rpc_payloads = {
        "skills.get": {
            "name": "planner",
            "layer": "managed",
            "eligible": True,
            "description": "Plan work",
            "content": "skill body",
        },
        "skills.update": {
            "results": [{"success": True, "name": "planner", "message": "updated"}]
        },
    }

    view = runner.invoke(app, ["skills", "view", "planner", "--json"])
    update = runner.invoke(app, ["skills", "update", "planner", "--json"])

    assert view.exit_code == 0, view.stdout
    assert json.loads(view.stdout)["name"] == "planner"
    assert update.exit_code == 0, update.stdout
    assert json.loads(update.stdout)["results"][0]["success"] is True
    assert ("skills.get", {"name": "planner"}) in fake.calls
    assert ("skills.update", {"name": "planner"}) in fake.calls


def test_skills_update_all_exits_nonzero_on_partial_failure(monkeypatch):
    fake = _install_fake_gateway(monkeypatch)
    fake.rpc_payloads = {
        "skills.update": {
            "results": [
                {"success": True, "name": "a", "message": "updated"},
                {"success": False, "name": "b", "message": "failed"},
            ]
        }
    }

    result = runner.invoke(app, ["skills", "update", "--all", "--json"])

    assert result.exit_code == 1
    assert json.loads(result.stdout)["results"][1]["name"] == "b"
    assert ("skills.update", {}) in fake.calls


def test_skills_update_exits_nonzero_on_top_level_failure(monkeypatch):
    fake = _install_fake_gateway(monkeypatch)
    fake.rpc_payloads = {
        "skills.update": {
            "success": False,
            "message": "No skill installer configured",
        }
    }

    result = runner.invoke(app, ["skills", "update", "planner", "--json"])

    assert result.exit_code == 1
    assert json.loads(result.stdout)["message"] == "No skill installer configured"
    assert ("skills.update", {"name": "planner"}) in fake.calls


def test_skills_install_and_uninstall_use_gateway_rpc_when_available(monkeypatch):
    fake = _install_fake_gateway(monkeypatch)
    fake.rpc_payloads = {
        "skills.install": {
            "success": True,
            "name": "planner",
            "message": "installed by gateway",
            "path": "/gateway/skill",
        },
        "skills.uninstall": {
            "success": True,
            "name": "planner",
            "message": "removed by gateway",
        },
    }

    install = runner.invoke(app, ["skills", "install", "planner", "--json"])
    uninstall = runner.invoke(app, ["skills", "uninstall", "planner", "--json"])

    assert install.exit_code == 0, install.stdout
    assert json.loads(install.stdout)["path"] == "/gateway/skill"
    assert uninstall.exit_code == 0, uninstall.stdout
    assert json.loads(uninstall.stdout)["message"] == "removed by gateway"
    assert (
        "skills.install",
        {"identifier": "planner", "source": "clawhub", "force": False},
    ) in fake.calls
    assert ("skills.uninstall", {"name": "planner"}) in fake.calls


def test_skills_install_and_uninstall_fall_back_when_gateway_unavailable(monkeypatch):
    _install_fake_gateway(monkeypatch, FailingConnectGatewayClient)
    from opensquilla.skills.hub.installer import InstallResult, SkillInstaller

    async def fake_install(self, identifier: str, source: str, force: bool = False):
        return InstallResult(
            success=True,
            name=identifier,
            message=f"installed from {source}",
            path="/tmp/skill",
        )

    async def fake_uninstall(self, name: str):
        return InstallResult(success=False, name=name, message="missing")

    monkeypatch.setattr(SkillInstaller, "install", fake_install)
    monkeypatch.setattr(SkillInstaller, "uninstall", fake_uninstall)

    install = runner.invoke(app, ["skills", "install", "planner", "--json"])
    uninstall = runner.invoke(app, ["skills", "uninstall", "missing", "--json"])

    assert install.exit_code == 0, install.stdout
    assert json.loads(install.stdout)["path"] == "/tmp/skill"
    assert uninstall.exit_code == 1
    assert json.loads(uninstall.stdout)["message"] == "missing"


def test_skills_install_fallback_exposes_github_source_without_token(monkeypatch):
    _install_fake_gateway(monkeypatch, FailingConnectGatewayClient)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    from opensquilla.skills.hub.installer import InstallResult, SkillInstaller

    async def fake_install(self, identifier: str, source: str, force: bool = False):
        assert source == "github"
        assert identifier == "https://github.com/acme/skillpack/tree/main/skills/demo"
        assert "github" in self._router.source_ids
        return InstallResult(
            success=True,
            name="demo",
            message="installed from github",
            path="/tmp/demo",
        )

    monkeypatch.setattr(SkillInstaller, "install", fake_install)

    install = runner.invoke(
        app,
        [
            "skills",
            "install",
            "https://github.com/acme/skillpack/tree/main/skills/demo",
            "--source",
            "github",
            "--json",
        ],
    )

    assert install.exit_code == 0, install.stdout
    assert json.loads(install.stdout)["name"] == "demo"


def test_skills_install_rpc_error_does_not_fall_back_to_local_installer(monkeypatch):
    fake = _install_fake_gateway(monkeypatch, RPCFailGatewayClient)
    from opensquilla.skills.hub.installer import SkillInstaller

    local_install_called = False

    async def fake_install(self, identifier: str, source: str, force: bool = False):
        nonlocal local_install_called
        local_install_called = True
        raise AssertionError("local fallback must not run after RPC errors")

    monkeypatch.setattr(SkillInstaller, "install", fake_install)

    result = runner.invoke(app, ["skills", "install", "planner", "--json"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert json.loads(result.stderr)["error"]["code"] == "UNAUTHORIZED"
    assert local_install_called is False
    assert (
        "skills.install",
        {"identifier": "planner", "source": "clawhub", "force": False},
    ) in fake.calls


def test_sessions_list_json_filters_client_side(monkeypatch):
    fake = _install_fake_gateway(monkeypatch)
    fake.sessions_payload = {
        "sessions": [
            {
                "key": "a",
                "agentId": "main",
                "status": "active",
                "channel": "slack",
                "updatedAt": "2026-05-05T00:00:00Z",
                "message_count": 2,
            },
            {
                "key": "b",
                "agentId": "ops",
                "status": "done",
                "channel": "telegram",
                "updatedAt": "2026-05-01T00:00:00Z",
                "message_count": 1,
            },
        ],
        "count": 2,
        "ts": 1,
    }

    result = runner.invoke(
        app,
        [
            "sessions",
            "list",
            "--agent",
            "main",
            "--status",
            "active",
            "--channel",
            "slack",
            "--since",
            "2026-05-04",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["count"] == 1
    assert payload["sessions"][0]["key"] == "a"


def test_sessions_show_json_resolves_and_previews(monkeypatch):
    fake = _install_fake_gateway(monkeypatch)
    fake.rpc_payloads = {
        "sessions.resolve": {
            "session_key": "agent:main:abc",
            "session_id": "abc",
            "status": "active",
            "agent_id": "main",
            "model": "openai/test",
        },
        "sessions.preview": {
            "previews": [
                {
                    "key": "agent:main:abc",
                    "title": "Debugging",
                    "lastMessage": "latest",
                    "updatedAt": 123,
                }
            ]
        },
    }

    result = runner.invoke(app, ["sessions", "show", "abc", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["resolved"]["session_key"] == "agent:main:abc"
    assert payload["preview"]["previews"][0]["lastMessage"] == "latest"
    assert ("sessions.resolve", {"key": "abc"}) in fake.calls
    assert ("sessions.preview", {"keys": ["agent:main:abc"], "limit": 50}) in fake.calls


def test_sessions_show_json_errors_go_to_stderr(monkeypatch):
    _install_fake_gateway(monkeypatch, FailingConnectGatewayClient)

    result = runner.invoke(app, ["sessions", "show", "abc", "--json"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert json.loads(result.stderr)["error"]["code"] == "GATEWAY_UNAVAILABLE"


def test_sessions_abort_resolves_then_aborts(monkeypatch):
    fake = _install_fake_gateway(monkeypatch)
    fake.rpc_payloads = {
        "sessions.resolve": {"key": "agent:main:abc", "session_id": "abc"},
        "sessions.abort": {"aborted": True, "key": "agent:main:abc"},
    }

    result = runner.invoke(app, ["sessions", "abort", "abc", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["aborted"] is True
    assert ("sessions.resolve", {"key": "abc"}) in fake.calls
    assert ("sessions.abort", {"key": "agent:main:abc"}) in fake.calls


def test_memory_status_json_reuses_doctor_rpc(monkeypatch):
    fake = _install_fake_gateway(monkeypatch)
    fake.rpc_payloads = {
        "doctor.memory.status": {
            "backend": "sqlite",
            "status": "ok",
            "entryCount": 3,
            "sizeBytes": 42,
            "error": None,
        }
    }

    result = runner.invoke(app, ["memory", "status", "--agent", "main", "--json"])

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["entryCount"] == 3
    assert ("doctor.memory.status", {"agentId": "main"}) in fake.calls


def test_memory_status_table_surfaces_source_counts(monkeypatch):
    fake = _install_fake_gateway(monkeypatch)
    fake.rpc_payloads = {
        "doctor.memory.status": {
            "backend": "sqlite",
            "status": "ok",
            "entryCount": 4,
            "sizeBytes": 42,
            "error": None,
            "sourceCounts": {
                "memory": {"files": 1, "chunks": 2},
                "sessions": {"files": 1, "chunks": 2},
            },
        }
    }

    result = runner.invoke(app, ["memory", "status", "--agent", "main"])

    assert result.exit_code == 0, result.stdout
    assert "Sources" in result.stdout
    assert "memory" in result.stdout
    assert "sessions" in result.stdout


def test_memory_status_deep_json_passes_deep_flag(monkeypatch):
    fake = _install_fake_gateway(monkeypatch)
    fake.rpc_payloads = {
        "doctor.memory.status": {
            "backend": "sqlite",
            "status": "degraded",
            "vecAvailable": False,
            "ftsAvailable": True,
            "degraded": [],
        }
    }

    result = runner.invoke(app, ["memory", "status", "--agent", "main", "--deep", "--json"])

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["vecAvailable"] is False
    assert ("doctor.memory.status", {"agentId": "main", "deep": True}) in fake.calls


def test_memory_list_json_uses_gateway_rpc(monkeypatch):
    fake = _install_fake_gateway(monkeypatch)
    fake.rpc_payloads = {
        "memory.list": {
            "agentId": "main",
            "count": 1,
            "files": [{"path": "memory/a.md", "lineCount": 2, "sizeBytes": 12}],
        }
    }

    result = runner.invoke(app, ["memory", "list", "--agent", "main", "--json"])

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["files"][0]["path"] == "memory/a.md"
    assert ("memory.list", {"agentId": "main"}) in fake.calls


def test_memory_search_and_show_use_gateway_rpcs(monkeypatch):
    fake = _install_fake_gateway(monkeypatch)
    fake.rpc_payloads = {
        "memory.search": {
            "agentId": "main",
            "query": "alpha",
            "count": 1,
            "results": [
                {
                    "source": "sessions",
                    "path": "sessions/main/session-1.md",
                    "startLine": 1,
                    "endLine": 2,
                    "score": 0.8,
                    "snippet": "alpha transcript",
                }
            ],
        },
        "memory.show": {
            "agentId": "main",
            "path": "memory/a.md",
            "fromLine": 2,
            "lineCount": 1,
            "truncated": False,
            "content": "line",
        },
    }

    search = runner.invoke(
        app,
        ["memory", "search", "alpha", "--limit", "3", "--source", "sessions", "--json"],
    )
    search_table = runner.invoke(
        app,
        ["memory", "search", "alpha", "--limit", "3", "--source", "sessions"],
    )
    show = runner.invoke(
        app,
        [
            "memory",
            "show",
            "memory/a.md",
            "--from-line",
            "2",
            "--lines",
            "1",
            "--json",
        ],
    )

    assert search.exit_code == 0, search.stdout
    assert search_table.exit_code == 0, search_table.stdout
    assert show.exit_code == 0, show.stdout
    assert "Source" in search_table.stdout
    assert "sessions" in search_table.stdout
    assert json.loads(show.stdout)["content"] == "line"
    assert (
        "memory.search",
        {"query": "alpha", "agentId": "main", "limit": 3, "source": "sessions"},
    ) in fake.calls
    assert (
        "memory.show",
        {"path": "memory/a.md", "agentId": "main", "fromLine": 2, "lines": 1},
    ) in fake.calls


def test_memory_index_and_raw_fallback_commands_use_admin_rpcs(monkeypatch):
    fake = _install_fake_gateway(monkeypatch)
    fake.rpc_payloads = {
        "memory.index": {"agentId": "main", "force": True},
        "memory.raw_fallbacks.list": {
            "agentId": "main",
            "count": 1,
            "files": [{"path": "memory/.raw_fallbacks/raw.md", "sizeBytes": 12}],
        },
        "memory.raw_fallbacks.show": {
            "agentId": "main",
            "path": "memory/.raw_fallbacks/raw.md",
            "fromLine": 1,
            "lineCount": 1,
            "truncated": False,
            "content": "raw",
        },
    }

    index = runner.invoke(app, ["memory", "index", "--agent", "main", "--force", "--json"])
    listed = runner.invoke(app, ["memory", "raw-fallbacks", "list", "--json"])
    shown = runner.invoke(
        app,
        ["memory", "raw-fallbacks", "show", "memory/.raw_fallbacks/raw.md", "--json"],
    )

    assert index.exit_code == 0, index.stdout
    assert listed.exit_code == 0, listed.stdout
    assert shown.exit_code == 0, shown.stdout
    assert ("memory.index", {"agentId": "main", "force": True}) in fake.calls
    assert ("memory.raw_fallbacks.list", {"agentId": "main"}) in fake.calls
    assert (
        "memory.raw_fallbacks.show",
        {"path": "memory/.raw_fallbacks/raw.md", "agentId": "main"},
    ) in fake.calls


def test_cron_run_requires_confirmation_before_gateway_call(monkeypatch):
    fake = _install_fake_gateway(monkeypatch)

    result = runner.invoke(app, ["cron", "run", "job-1", "--json"])

    assert result.exit_code == 2
    assert result.stdout == ""
    assert json.loads(result.stderr)["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert fake.calls == []


def test_cron_run_yes_calls_existing_rpc(monkeypatch):
    fake = _install_fake_gateway(monkeypatch)
    fake.rpc_payloads = {"cron.run": {"success": True, "status": "accepted"}}

    result = runner.invoke(app, ["cron", "run", "job-1", "--yes", "--json"])

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["status"] == "accepted"
    assert ("cron.run", {"id": "job-1"}) in fake.calls


def test_cron_commands_use_existing_rpc_payloads(monkeypatch):
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
            "--agent",
            "main",
            "--session-target",
            "isolated",
            "--json",
        ],
    )
    update_result = runner.invoke(app, ["cron", "update", "job-1", "--disabled", "--json"])
    remove_result = runner.invoke(app, ["cron", "remove", "job-1", "--yes", "--json"])
    runs_result = runner.invoke(app, ["cron", "runs", "job-1", "--limit", "3", "--json"])

    assert list_result.exit_code == 0, list_result.stdout
    assert status_result.exit_code == 0, status_result.stdout
    assert add_result.exit_code == 0, add_result.stdout
    assert update_result.exit_code == 0, update_result.stdout
    assert remove_result.exit_code == 0, remove_result.stdout
    assert runs_result.exit_code == 0, runs_result.stdout
    assert ("cron.list", {"agentId": "main"}) in fake.calls
    assert ("cron.status", {"id": "job-1"}) in fake.calls
    assert (
        "cron.add",
        {
            "expression": "*/5 * * * *",
            "text": "check in",
            "payloadKind": "reminder",
            "sessionTarget": "isolated",
            "agentId": "main",
        },
    ) in fake.calls
    assert ("cron.update", {"id": "job-1", "enabled": False}) in fake.calls
    assert ("cron.remove", {"id": "job-1"}) in fake.calls
    assert ("cron.runs", {"id": "job-1", "limit": 3}) in fake.calls


def test_channels_runtime_restart_requires_confirmation(monkeypatch):
    fake = _install_fake_gateway(monkeypatch)

    result = runner.invoke(app, ["channels", "restart", "slack", "--json"])

    assert result.exit_code == 2
    assert json.loads(result.stderr)["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert fake.calls == []


def test_channels_status_and_logout_use_existing_rpcs(monkeypatch):
    fake = _install_fake_gateway(monkeypatch)
    fake.rpc_payloads = {
        "channels.status": {
            "channels": [{"name": "slack", "status": "connected", "connected": True}]
        },
        "channels.logout": {"status": "disconnected", "channel": "slack"},
    }

    status = runner.invoke(app, ["channels", "status", "slack", "--json"])
    logout = runner.invoke(app, ["channels", "logout", "slack", "--yes", "--json"])

    assert status.exit_code == 0, status.stdout
    assert logout.exit_code == 0, logout.stdout
    assert json.loads(status.stdout)["channels"][0]["status"] == "connected"
    assert json.loads(logout.stdout)["status"] == "disconnected"
    assert ("channels.status", {}) in fake.calls
    assert ("channels.logout", {"name": "slack"}) in fake.calls


def test_cost_json_returns_gateway_payload(monkeypatch):
    fake = _install_fake_gateway(monkeypatch)
    fake.cost_payload = {
        "breakdown": [{"session": "s", "model": "m", "input_tokens": 1, "cost_usd": 0.1}],
        "totalCostUsd": 0.1,
    }

    result = runner.invoke(app, ["cost", "--json"])

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["totalCostUsd"] == 0.1
    assert ("usage.cost", {}) in fake.calls


def test_provider_and_search_diagnostics_use_gateway_rpcs(monkeypatch):
    fake = _install_fake_gateway(monkeypatch)
    fake.rpc_payloads = {
        "providers.status": {"activeProvider": "openrouter", "providers": [], "count": 0},
        "search.status": {
            "activeProvider": "duckduckgo",
            "provider": "duckduckgo",
            "configured": True,
            "buildable": True,
        },
        "search.query": {
            "ok": True,
            "query": "hello",
            "provider": "duckduckgo",
            "results": [{"title": "T", "url": "https://example.com", "snippet": "S"}],
        },
    }

    providers = runner.invoke(app, ["providers", "status", "--json"])
    search_status = runner.invoke(app, ["search", "status", "--json"])
    search_query = runner.invoke(
        app,
        ["search", "query", "hello", "--provider", "duckduckgo", "--limit", "2", "--json"],
    )

    assert providers.exit_code == 0, providers.stdout
    assert search_status.exit_code == 0, search_status.stdout
    assert search_query.exit_code == 0, search_query.stdout
    assert json.loads(search_query.stdout)["results"][0]["title"] == "T"
    assert ("providers.status", {"probeModels": False}) in fake.calls
    assert ("search.status", {}) in fake.calls
    assert (
        "search.query",
        {"query": "hello", "provider": "duckduckgo", "limit": 2},
    ) in fake.calls


def test_search_query_json_exits_nonzero_on_diagnostic_failure(monkeypatch):
    fake = _install_fake_gateway(monkeypatch)
    fake.rpc_payloads = {
        "search.query": {
            "ok": False,
            "query": "hello",
            "provider": "duckduckgo",
            "results": [],
            "error": {
                "kind": "network",
                "class": "ConnectError",
                "message": "network down",
                "retryable": True,
            },
        }
    }

    result = runner.invoke(app, ["search", "query", "hello", "--json"])

    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["message"] == "network down"
