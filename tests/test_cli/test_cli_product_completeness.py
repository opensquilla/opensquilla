from __future__ import annotations

import ast
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
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


def test_skills_search_delegates_to_cli_search_rows_boundary(monkeypatch):
    from opensquilla.cli import skills_cmd

    async def fake_search_skill_rows(query: str, *, limit: int = 20):
        assert query == "plan"
        assert limit == 20
        return [
            {
                "name": "Planner",
                "description": "Plan work",
                "version": "1.0.0",
                "author": "Tests",
                "source_id": "clawhub",
                "trust_level": "community",
                "identifier": "planner",
            }
        ]

    monkeypatch.setattr(skills_cmd, "search_skill_rows", fake_search_skill_rows)

    result = runner.invoke(app, ["skills", "search", "plan", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload[0]["name"] == "Planner"
    assert payload[0]["source_id"] == "clawhub"


def test_cli_skill_search_rows_use_hub_operation_boundary(monkeypatch):
    from opensquilla.cli.skills_search_rows import search_skill_rows
    from opensquilla.skills.hub import operations as hub_operations

    @dataclass(frozen=True)
    class SearchResult:
        name: str
        description: str
        version: str
        author: str
        source_id: str
        trust_level: str
        identifier: str

    calls: list[tuple[str, object]] = []

    def fake_skill_search_request(params: object) -> object:
        calls.append(("request", params))
        return ("search", params)

    async def fake_search_skills(router: object, request: object) -> SimpleNamespace:
        assert router is None
        calls.append(("search", request))
        return SimpleNamespace(
            results=[
                SearchResult(
                    name="Planner",
                    description="Plan work",
                    version="1.0.0",
                    author="Tests",
                    source_id="clawhub",
                    trust_level="community",
                    identifier="planner",
                )
            ],
            unavailable=False,
        )

    monkeypatch.setattr(
        hub_operations,
        "skill_search_request",
        fake_skill_search_request,
    )
    monkeypatch.setattr(hub_operations, "search_skills", fake_search_skills)

    rows = asyncio.run(search_skill_rows("plan", limit=7))

    assert rows == [
        {
            "name": "Planner",
            "description": "Plan work",
            "version": "1.0.0",
            "author": "Tests",
            "source_id": "clawhub",
            "trust_level": "community",
            "identifier": "planner",
        }
    ]
    assert calls == [
        ("request", {"query": "plan", "limit": 7}),
        ("search", ("search", {"query": "plan", "limit": 7})),
    ]


def test_skills_list_delegates_to_cli_rows_boundary(monkeypatch):
    from opensquilla.cli import skills_cmd

    calls: list[str] = []

    def fake_load_skill_rows() -> list[dict[str, object]]:
        calls.append("load")
        return [
            {
                "name": "planner",
                "layer": "bundled",
                "eligible": True,
                "description": "Plan work",
                "always": False,
                "triggers": ["plan"],
                "path": "",
                "filePath": "/skills/planner/SKILL.md",
                "baseDir": "/skills/planner",
                "homepage": "https://example.test/planner",
                "userInvocable": True,
                "disableModelInvocation": False,
                "provenance": {
                    "origin": "opensquilla-original",
                    "license": "Apache-2.0",
                    "upstreamUrl": "",
                    "maintainedBy": "OpenSquilla",
                },
            }
        ]

    monkeypatch.setattr(skills_cmd, "load_skill_rows", fake_load_skill_rows)

    result = runner.invoke(app, ["skills", "list", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload[0]["name"] == "planner"
    assert calls == ["load"]


def test_cli_skill_rows_use_configured_loader_and_eligibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.cli.skills_rows import load_skill_rows
    from opensquilla.gateway import config as gateway_config
    from opensquilla.skills import eligibility, runtime

    calls: list[tuple[str, object]] = []
    ctx = object()

    skill = SimpleNamespace(
        name="planner",
        layer=SimpleNamespace(value="bundled"),
        description="Plan work",
        always=False,
        triggers=["plan"],
        path=None,
        file_path="/skills/planner/SKILL.md",
        base_dir="/skills/planner",
        homepage="https://example.test/planner",
        user_invocable=True,
        disable_model_invocation=False,
        provenance=SimpleNamespace(
            origin="opensquilla-original",
            license="Apache-2.0",
            upstream_url="https://example.test/upstream",
            maintained_by="OpenSquilla",
        ),
    )

    class FakeLoader:
        def load_all(self) -> list[SimpleNamespace]:
            calls.append(("load_all", None))
            return [skill]

    monkeypatch.setenv("OPENSQUILLA_GATEWAY_CONFIG_PATH", "/tmp/config.toml")
    monkeypatch.setattr(
        gateway_config.GatewayConfig,
        "load",
        staticmethod(
            lambda path: (
                calls.append(("config", path))
                or SimpleNamespace(
                    skills=SimpleNamespace(enabled=True),
                    workspace_dir="/tmp/ws",
                )
            )
        ),
    )
    monkeypatch.setattr(
        runtime,
        "create_configured_skill_loader",
        lambda skills_config, *, workspace_dir: (
            calls.append(("runtime", (skills_config.enabled, workspace_dir)))
            or SimpleNamespace(loader=FakeLoader())
        ),
    )
    monkeypatch.setattr(
        eligibility.EligibilityContext,
        "auto",
        staticmethod(lambda: calls.append(("ctx", None)) or ctx),
    )
    monkeypatch.setattr(
        eligibility,
        "check_eligibility",
        lambda actual_skill, actual_ctx: (
            calls.append(("eligible", (actual_skill.name, actual_ctx is ctx))) or True
        ),
    )

    rows = load_skill_rows()

    assert rows[0]["name"] == "planner"
    assert rows[0]["eligible"] is True
    assert rows[0]["provenance"] == {
        "origin": "opensquilla-original",
        "license": "Apache-2.0",
        "upstreamUrl": "https://example.test/upstream",
        "maintainedBy": "OpenSquilla",
    }
    assert calls == [
        ("config", "/tmp/config.toml"),
        ("runtime", (True, "/tmp/ws")),
        ("ctx", None),
        ("load_all", None),
        ("eligible", ("planner", True)),
    ]


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


def test_skills_install_and_uninstall_fallback_delegates_to_local_mutations(
    monkeypatch,
):
    _install_fake_gateway(monkeypatch, FailingConnectGatewayClient)
    from opensquilla.cli import skills_cmd

    @dataclass(frozen=True)
    class LocalResult:
        success: bool
        name: str
        message: str
        path: str | None = None
        scan: object | None = None

    calls: list[tuple[str, object]] = []

    async def fake_run_local_skill_install(
        identifier: str,
        *,
        source: str,
        force: bool,
    ) -> SimpleNamespace:
        calls.append(
            ("install", {"identifier": identifier, "source": source, "force": force})
        )
        return SimpleNamespace(
            result=LocalResult(True, "planner", "installed", "/tmp/planner"),
            unavailable_message="",
        )

    async def fake_run_local_skill_uninstall(name: str) -> SimpleNamespace:
        calls.append(("uninstall", {"name": name}))
        return SimpleNamespace(
            result=LocalResult(True, "planner", "removed"),
            unavailable_message="",
        )

    monkeypatch.setattr(
        skills_cmd,
        "run_local_skill_install",
        fake_run_local_skill_install,
    )
    monkeypatch.setattr(
        skills_cmd,
        "run_local_skill_uninstall",
        fake_run_local_skill_uninstall,
    )

    install = runner.invoke(
        app,
        ["skills", "install", "planner", "--source", "github", "--force", "--json"],
    )
    uninstall = runner.invoke(app, ["skills", "uninstall", "planner", "--json"])

    assert install.exit_code == 0, install.stdout
    assert json.loads(install.stdout)["path"] == "/tmp/planner"
    assert uninstall.exit_code == 0, uninstall.stdout
    assert json.loads(uninstall.stdout)["message"] == "removed"
    assert calls == [
        (
            "install",
            {"identifier": "planner", "source": "github", "force": True},
        ),
        ("uninstall", {"name": "planner"}),
    ]


def test_cli_local_skill_mutations_use_hub_operation_workflows(monkeypatch) -> None:
    from opensquilla.cli.skills_local_mutations import (
        run_local_skill_install,
        run_local_skill_uninstall,
    )
    from opensquilla.skills.hub import operations as hub_operations

    calls: list[tuple[str, object]] = []

    def fake_skill_install_request(params: object) -> object:
        calls.append(("install_request", params))
        return ("install", params)

    def fake_skill_uninstall_request(params: object) -> object:
        calls.append(("uninstall_request", params))
        return ("uninstall", params)

    async def fake_run_skill_install_operation(
        loader: object,
        request: object,
        **kwargs: object,
    ) -> SimpleNamespace:
        assert loader is None
        assert kwargs == {"require_loader": False}
        calls.append(("install", request))
        return SimpleNamespace(result="installed", unavailable_message="")

    async def fake_run_skill_uninstall_operation(
        loader: object,
        request: object,
    ) -> SimpleNamespace:
        assert loader is None
        calls.append(("uninstall", request))
        return SimpleNamespace(result="removed", unavailable_message="")

    monkeypatch.setattr(
        hub_operations,
        "skill_install_request",
        fake_skill_install_request,
    )
    monkeypatch.setattr(
        hub_operations,
        "skill_uninstall_request",
        fake_skill_uninstall_request,
    )
    monkeypatch.setattr(
        hub_operations,
        "run_skill_install_operation",
        fake_run_skill_install_operation,
    )
    monkeypatch.setattr(
        hub_operations,
        "run_skill_uninstall_operation",
        fake_run_skill_uninstall_operation,
    )

    install = asyncio.run(
        run_local_skill_install("planner", source="github", force=True)
    )
    uninstall = asyncio.run(run_local_skill_uninstall("planner"))

    assert install.result == "installed"
    assert uninstall.result == "removed"
    assert calls == [
        (
            "install_request",
            {"identifier": "planner", "source": "github", "force": True},
        ),
        (
            "install",
            ("install", {"identifier": "planner", "source": "github", "force": True}),
        ),
        ("uninstall_request", {"name": "planner"}),
        ("uninstall", ("uninstall", {"name": "planner"})),
    ]


def test_cli_skills_does_not_import_hub_defaults() -> None:
    from opensquilla.cli import skills_cmd

    tree = ast.parse(Path(skills_cmd.__file__).read_text(encoding="utf-8"))
    imported_modules = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }

    assert "opensquilla.skills.hub.defaults" not in imported_modules
    assert "opensquilla.skills.hub.search" not in imported_modules
    assert "opensquilla.gateway.config" not in imported_modules
    assert "opensquilla.skills.eligibility" not in imported_modules
    assert "opensquilla.skills.runtime" not in imported_modules


def test_cli_skills_search_does_not_import_hub_search_operation_details() -> None:
    from opensquilla.cli import skills_cmd

    tree = ast.parse(Path(skills_cmd.__file__).read_text(encoding="utf-8"))
    imported_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.skills.hub.operations"
        for alias in node.names
    }

    assert "search_skills" not in imported_names
    assert "skill_search_request" not in imported_names


def test_cli_skills_install_fallback_uses_local_mutation_boundary() -> None:
    from opensquilla.cli import skills_cmd

    tree = ast.parse(Path(skills_cmd.__file__).read_text(encoding="utf-8"))
    imported_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.skills.hub.operations"
        for alias in node.names
    }
    imported_cli_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "opensquilla.cli.skills_local_mutations"
        for alias in node.names
    }

    assert "run_local_skill_install" in imported_cli_names
    assert "run_local_skill_uninstall" in imported_cli_names
    assert "run_skill_install_operation" not in imported_names
    assert "run_skill_uninstall_operation" not in imported_names
    assert "skill_install_request" not in imported_names
    assert "skill_uninstall_request" not in imported_names
    assert "default_skill_installer_factory" not in imported_names
    assert "install_skill" not in imported_names
    assert "uninstall_skill" not in imported_names


def test_skills_tap_commands_delegate_to_hub_tap_operations(monkeypatch):
    from opensquilla.cli import skills_cmd

    manager = object()
    calls: list[tuple[str, object]] = []

    def fake_taps_manager_factory() -> object:
        calls.append(("factory", None))
        return manager

    def fake_add_tap(actual_manager: object, request: object) -> SimpleNamespace:
        assert actual_manager is manager
        calls.append(("add", request))
        return SimpleNamespace(full_name="acme/tap", url="https://example.test/acme/tap")

    def fake_list_taps(actual_manager: object) -> list[SimpleNamespace]:
        assert actual_manager is manager
        calls.append(("list", None))
        return [
            SimpleNamespace(
                full_name="acme/tap",
                url="https://example.test/acme/tap",
                added_at="2026-05-17T00:00:00Z",
            )
        ]

    def fake_remove_tap(actual_manager: object, request: object) -> bool:
        assert actual_manager is manager
        calls.append(("remove", request))
        return True

    monkeypatch.setattr(
        skills_cmd,
        "default_taps_manager_factory",
        fake_taps_manager_factory,
    )
    monkeypatch.setattr(skills_cmd, "add_tap", fake_add_tap)
    monkeypatch.setattr(skills_cmd, "list_taps", fake_list_taps)
    monkeypatch.setattr(skills_cmd, "remove_tap", fake_remove_tap)
    monkeypatch.setattr(
        skills_cmd,
        "tap_add_request",
        lambda params: ("add", params),
    )
    monkeypatch.setattr(
        skills_cmd,
        "tap_remove_request",
        lambda params: ("remove", params),
    )

    add = runner.invoke(app, ["skills", "tap", "add", "acme/tap"])
    listed = runner.invoke(app, ["skills", "tap", "list"])
    removed = runner.invoke(app, ["skills", "tap", "remove", "acme/tap"])

    assert add.exit_code == 0, add.stdout
    assert listed.exit_code == 0, listed.stdout
    assert removed.exit_code == 0, removed.stdout
    assert "acme/tap" in add.stdout
    assert "acme/tap" in listed.stdout
    assert "Removed" in removed.stdout
    assert calls == [
        ("factory", None),
        ("add", ("add", {"owner_repo": "acme/tap"})),
        ("factory", None),
        ("list", None),
        ("factory", None),
        ("remove", ("remove", {"owner_repo": "acme/tap"})),
    ]


def test_cli_skills_tap_does_not_import_taps_boundary() -> None:
    from opensquilla.cli import skills_cmd

    tree = ast.parse(Path(skills_cmd.__file__).read_text(encoding="utf-8"))
    imported_modules = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }

    assert "opensquilla.skills.hub.taps" not in imported_modules
    assert not any(
        isinstance(node, ast.Name) and node.id == "TapsManager"
        for node in ast.walk(tree)
    )


def test_skills_publish_delegates_to_hub_publish_request(monkeypatch):
    from opensquilla.cli import skills_cmd

    calls: list[tuple[str, object]] = []

    def fake_skill_publish_request(params: object) -> object:
        calls.append(("request", params))
        return ("publish", params)

    async def fake_publish_skill_from_request(request: object) -> SimpleNamespace:
        calls.append(("publish", request))
        return SimpleNamespace(success=True, message="validated")

    monkeypatch.setattr(
        skills_cmd,
        "skill_publish_request",
        fake_skill_publish_request,
    )
    monkeypatch.setattr(
        skills_cmd,
        "publish_skill_from_request",
        fake_publish_skill_from_request,
    )

    result = runner.invoke(
        app,
        ["skills", "publish", "/tmp/demo-skill", "--repo", "acme/skills"],
    )

    assert result.exit_code == 0, result.stdout
    assert "validated" in result.stdout
    assert calls == [
        (
            "request",
            {"skill_dir": "/tmp/demo-skill", "target_repo": "acme/skills"},
        ),
        (
            "publish",
            ("publish", {"skill_dir": "/tmp/demo-skill", "target_repo": "acme/skills"}),
        ),
    ]


def test_cli_skills_publish_does_not_import_publisher_boundary() -> None:
    from opensquilla.cli import skills_cmd

    tree = ast.parse(Path(skills_cmd.__file__).read_text(encoding="utf-8"))
    imported_modules = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }

    assert "opensquilla.skills.hub.publisher" not in imported_modules
    assert not any(
        isinstance(node, ast.Name) and node.id == "publish_skill"
        for node in ast.walk(tree)
    )


def test_skill_publish_request_builds_publish_request(tmp_path: Path) -> None:
    from opensquilla.skills.hub.publisher import skill_publish_request

    request = skill_publish_request(
        {"skill_dir": tmp_path / "demo-skill", "repo": "acme/skills"}
    )

    assert request.skill_dir == tmp_path / "demo-skill"
    assert request.target_repo == "acme/skills"


def test_publish_skill_from_request_delegates(monkeypatch, tmp_path: Path) -> None:
    from opensquilla.skills.hub import publisher

    calls: list[tuple[Path, str | None]] = []

    async def fake_publish_skill(skill_dir: Path, target_repo: str | None = None):
        calls.append((skill_dir, target_repo))
        return publisher.PublishResult(success=True, message="ok", skill_name="demo")

    monkeypatch.setattr(publisher, "publish_skill", fake_publish_skill)

    result = asyncio.run(
        publisher.publish_skill_from_request(
            publisher.SkillPublishRequest(
                skill_dir=tmp_path / "demo-skill",
                target_repo="acme/skills",
            )
        )
    )

    assert result.success is True
    assert calls == [(tmp_path / "demo-skill", "acme/skills")]


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
        "memory.search": {"agentId": "main", "query": "alpha", "count": 0, "results": []},
        "memory.show": {
            "agentId": "main",
            "path": "memory/a.md",
            "fromLine": 2,
            "lineCount": 1,
            "truncated": False,
            "content": "line",
        },
    }

    search = runner.invoke(app, ["memory", "search", "alpha", "--limit", "3", "--json"])
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
    assert show.exit_code == 0, show.stdout
    assert json.loads(show.stdout)["content"] == "line"
    assert ("memory.search", {"query": "alpha", "agentId": "main", "limit": 3}) in fake.calls
    assert (
        "memory.show",
        {"path": "memory/a.md", "agentId": "main", "fromLine": 2, "lines": 1},
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
