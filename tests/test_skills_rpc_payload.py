from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from opensquilla.gateway import rpc_skills
from opensquilla.skills.eligibility import EligibilityReport
from opensquilla.skills.rpc_payload import (
    skill_deps_install_result_rpc_payload,
    skill_get_rpc_payload,
    skill_install_result_rpc_payload,
    skill_install_unavailable_rpc_payload,
    skill_status_from_report,
    skill_to_rpc_payload,
    skill_uninstall_result_rpc_payload,
    skill_uninstall_unavailable_rpc_payload,
    skills_bins_rpc_payload,
    skills_list_rpc_payload,
    skills_search_rpc_payload,
    skills_search_unavailable_rpc_payload,
    skills_status_rpc_payload,
    skills_update_empty_results_rpc_payload,
    skills_update_results_rpc_payload,
    skills_update_unavailable_rpc_payload,
)
from opensquilla.skills.types import (
    SkillInstallSpec,
    SkillLayer,
    SkillPlatformMeta,
    SkillProvenance,
    SkillRequires,
    SkillSpec,
)


class FakeLoader:
    def __init__(self, skills: list[SkillSpec]) -> None:
        self._skills = skills

    def load_all(self) -> list[SkillSpec]:
        return list(self._skills)

    def get_by_name(self, name: str) -> SkillSpec | None:
        return next((skill for skill in self._skills if skill.name == name), None)


def _skill(**overrides: Any) -> SkillSpec:
    values: dict[str, Any] = {
        "name": "planner",
        "description": "Plan work",
        "layer": SkillLayer.WORKSPACE,
        "always": False,
        "triggers": ["plan"],
        "content": "Use a plan.",
        "metadata": None,
        "homepage": "https://example.test/planner",
        "file_path": "/tmp/planner/SKILL.md",
        "base_dir": "/tmp/planner",
        "provenance": SkillProvenance(
            origin="fixture",
            license="MIT",
            upstream_url="https://example.test/upstream",
            maintained_by="Tests",
        ),
    }
    values.update(overrides)
    return SkillSpec(**values)


def test_skill_to_rpc_payload_preserves_wire_shape_and_filters_install_os() -> None:
    metadata = SkillPlatformMeta(
        emoji="*",
        primary_env="PLANNER_TOKEN",
        homepage="https://example.test/home",
        os=["linux"],
        requires=SkillRequires(bins=["node"], env=["PLANNER_TOKEN"]),
        install=[
            SkillInstallSpec(
                id="node-linux",
                kind="brew",
                label="Node",
                bins=["node"],
                os=["linux"],
            ),
            SkillInstallSpec(
                id="node-darwin",
                kind="brew",
                label="Node",
                bins=["node"],
                os=["darwin"],
            ),
            SkillInstallSpec(id="common", kind="uv", label="Common", bins=["uv"]),
        ],
    )
    report = EligibilityReport(
        eligible=False,
        declared=True,
        reasons=["Missing binary: node"],
        missing_bins=["node"],
        missing_env=["PLANNER_TOKEN"],
    )

    payload = skill_to_rpc_payload(_skill(metadata=metadata), report, os_name="linux")

    assert payload == {
        "name": "planner",
        "description": "Plan work",
        "layer": "workspace",
        "always": False,
        "triggers": ["plan"],
        "eligible": False,
        "emoji": "*",
        "primary_env": "PLANNER_TOKEN",
        "homepage": "https://example.test/home",
        "file_path": "/tmp/planner/SKILL.md",
        "os": ["linux"],
        "disabled": False,
        "install": [
            {"id": "node-linux", "kind": "brew", "label": "Node", "bins": ["node"]},
            {"id": "common", "kind": "uv", "label": "Common", "bins": ["uv"]},
        ],
        "provenance": {
            "origin": "fixture",
            "license": "MIT",
            "upstream_url": "https://example.test/upstream",
            "maintained_by": "Tests",
        },
        "declared": True,
        "status": "needs_setup",
        "status_detail": "Needs setup — missing: node, PLANNER_TOKEN",
        "reasons": ["Missing binary: node"],
        "missing_bins": ["node"],
        "missing_env": ["PLANNER_TOKEN"],
    }
    assert all("os" not in entry for entry in payload["install"])


def test_skill_status_from_report_maps_wire_statuses() -> None:
    assert skill_status_from_report(EligibilityReport(eligible=False)) == "needs_setup"
    assert skill_status_from_report(EligibilityReport(eligible=True, declared=False)) == (
        "not_declared"
    )
    assert skill_status_from_report(EligibilityReport(eligible=True, declared=True)) == "ready"


def test_skills_list_status_and_get_payloads_handle_loader_boundary() -> None:
    skill = _skill()
    loader = FakeLoader([skill])

    status_payload = skills_status_rpc_payload(loader)
    assert status_payload[0]["name"] == "planner"
    assert status_payload[0]["status"] == "not_declared"

    assert skills_list_rpc_payload(loader) == {"skills": status_payload}
    assert skills_status_rpc_payload(None) == []
    assert skills_list_rpc_payload(None) == {"skills": []}

    get_payload = skill_get_rpc_payload({"name": "planner"}, loader)
    assert get_payload["content"] == "Use a plan."
    assert get_payload["file_path"] == "/tmp/planner/SKILL.md"
    assert get_payload["base_dir"] == "/tmp/planner"

    with pytest.raises(ValueError, match="params.name is required"):
        skill_get_rpc_payload({}, loader)
    with pytest.raises(KeyError, match="No skill loader available"):
        skill_get_rpc_payload({"name": "planner"}, None)
    with pytest.raises(KeyError, match="Skill not found: missing"):
        skill_get_rpc_payload({"name": "missing"}, loader)


def test_skills_bins_payload_collects_required_bins_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill = _skill(
        metadata=SkillPlatformMeta(
            requires=SkillRequires(
                bins=["node", "python"],
                any_bins=["uv", "node"],
            )
        )
    )
    loader = FakeLoader([skill, _skill(metadata=SkillPlatformMeta(requires=None))])
    checked: list[str] = []

    def fake_which(name: str) -> str | None:
        checked.append(name)
        return f"/usr/bin/{name}" if name in {"node", "uv"} else None

    monkeypatch.setattr("opensquilla.skills.rpc_payload.shutil.which", fake_which)

    assert skills_bins_rpc_payload(None) == {}
    assert skills_bins_rpc_payload(loader) == {
        "node": True,
        "python": False,
        "uv": True,
    }
    assert checked == ["node", "python", "uv"]


def test_skills_search_payloads_preserve_wire_shape_and_installed_aliases() -> None:
    results = [
        SimpleNamespace(
            name="Display Planner",
            description="Plan work",
            version="1.2.3",
            author="Tests",
            source_id="clawhub",
            trust_level="community",
            identifier="planner",
        ),
        SimpleNamespace(
            name="installed-by-name",
            description="Installed via name",
            version="0.1.0",
            author="Tests",
            source_id="github",
            trust_level="community",
            identifier="acme/repo@main:skills/installed/SKILL.md",
        ),
    ]

    assert skills_search_unavailable_rpc_payload() == {
        "results": [],
        "message": "No skill sources configured",
    }
    assert skills_search_rpc_payload(results, {"planner", "installed-by-name"}) == {
        "results": [
            {
                "name": "Display Planner",
                "description": "Plan work",
                "version": "1.2.3",
                "author": "Tests",
                "source": "clawhub",
                "trust_level": "community",
                "identifier": "planner",
                "installed": True,
            },
            {
                "name": "installed-by-name",
                "description": "Installed via name",
                "version": "0.1.0",
                "author": "Tests",
                "source": "github",
                "trust_level": "community",
                "identifier": "acme/repo@main:skills/installed/SKILL.md",
                "installed": True,
            },
        ]
    }


@pytest.mark.asyncio
async def test_gateway_search_delegates_to_hub_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router = object()

    async def fake_search_skills(actual_router: object, request: object) -> SimpleNamespace:
        assert actual_router is router
        assert request == ("search", {"query": "plan", "limit": 3})
        return SimpleNamespace(
            results=[
                SimpleNamespace(
                    name="Display Planner",
                    description="Plan work",
                    version="1.2.3",
                    author="Tests",
                    source_id="clawhub",
                    trust_level="community",
                    identifier="planner",
                )
            ],
            installed_names={"planner"},
            unavailable=False,
        )

    monkeypatch.setattr(
        rpc_skills,
        "skill_search_request",
        lambda params: ("search", params),
    )
    monkeypatch.setattr(rpc_skills, "search_skills", fake_search_skills)

    payload = await rpc_skills._handle_skills_search(
        {"query": "plan", "limit": 3},
        SimpleNamespace(_skill_router=router),
    )

    assert payload["results"][0]["installed"] is True


def test_skill_install_payloads_preserve_wire_shape_and_scan_details() -> None:
    result = SimpleNamespace(
        success=True,
        name="planner",
        message="Installed planner",
        scan=SimpleNamespace(
            verdict="warning",
            findings=[
                SimpleNamespace(
                    rule="shell",
                    severity="medium",
                    message="runs shell",
                    line=7,
                )
            ],
        ),
    )

    assert skill_install_unavailable_rpc_payload("No skill installer configured") == {
        "success": False,
        "message": "No skill installer configured",
    }
    assert skill_install_result_rpc_payload(result) == {
        "success": True,
        "name": "planner",
        "message": "Installed planner",
        "scan_verdict": "warning",
        "scan_findings": [
            {
                "rule": "shell",
                "severity": "medium",
                "message": "runs shell",
                "line": 7,
            }
        ],
    }
    assert skill_install_result_rpc_payload(
        SimpleNamespace(success=False, name="", message="missing", scan=None)
    ) == {
        "success": False,
        "name": "",
        "message": "missing",
    }


def test_skill_update_and_uninstall_payloads_preserve_wire_shape() -> None:
    first = SimpleNamespace(success=True, name="planner", message="Updated planner")
    second = SimpleNamespace(success=False, name="writer", message="Missing writer")

    assert skills_update_empty_results_rpc_payload("No skill loader configured") == {
        "results": [],
        "success": False,
        "message": "No skill loader configured",
    }
    assert skills_update_unavailable_rpc_payload("No skill installer configured") == {
        "success": False,
        "message": "No skill installer configured",
    }
    assert skills_update_results_rpc_payload([first, second]) == {
        "results": [
            {"success": True, "name": "planner", "message": "Updated planner"},
            {"success": False, "name": "writer", "message": "Missing writer"},
        ]
    }
    assert skill_uninstall_unavailable_rpc_payload("No skill installer configured") == {
        "success": False,
        "message": "No skill installer configured",
    }
    assert skill_uninstall_result_rpc_payload(first) == {
        "success": True,
        "name": "planner",
        "message": "Updated planner",
    }


def test_skill_deps_install_payload_preserves_wire_shape() -> None:
    result = SimpleNamespace(success=True, kind="brew", message="Installed node")

    assert skill_deps_install_result_rpc_payload(
        result,
        {"bins": ["node"], "env": ["PLANNER_TOKEN"]},
    ) == {
        "success": True,
        "kind": "brew",
        "message": "Installed node",
        "missing_still": {"bins": ["node"], "env": ["PLANNER_TOKEN"]},
    }


@pytest.mark.asyncio
async def test_gateway_delegates_skill_rpc_payloads_to_skills_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loader = object()
    ctx = SimpleNamespace(skill_loader=loader)

    monkeypatch.setattr(
        rpc_skills,
        "skills_status_rpc_payload",
        lambda actual_loader: [{"name": "status", "loader": actual_loader is loader}],
    )
    monkeypatch.setattr(
        rpc_skills,
        "skills_list_rpc_payload",
        lambda actual_loader: {"skills": [{"name": "list", "loader": actual_loader is loader}]},
    )
    monkeypatch.setattr(
        rpc_skills,
        "skills_bins_rpc_payload",
        lambda actual_loader: {"node": actual_loader is loader},
    )
    monkeypatch.setattr(
        rpc_skills,
        "skill_get_rpc_payload",
        lambda params, actual_loader: {"name": params["name"], "loader": actual_loader is loader},
    )
    monkeypatch.setattr(
        rpc_skills,
        "skills_search_unavailable_rpc_payload",
        lambda: {"results": [], "delegated": True},
    )
    monkeypatch.setattr(
        rpc_skills,
        "skill_install_unavailable_rpc_payload",
        lambda message: {"success": False, "message": message, "delegated": True},
    )
    monkeypatch.setattr(
        rpc_skills,
        "skills_update_empty_results_rpc_payload",
        lambda message: {
            "results": [],
            "success": False,
            "message": message,
            "delegated": True,
        },
    )
    monkeypatch.setattr(
        rpc_skills,
        "skills_update_unavailable_rpc_payload",
        lambda message: {"success": False, "message": message, "delegated": True},
    )
    monkeypatch.setattr(
        rpc_skills,
        "skill_uninstall_unavailable_rpc_payload",
        lambda message: {"success": False, "message": message, "delegated": True},
    )
    monkeypatch.setattr(
        rpc_skills,
        "skill_deps_install_result_rpc_payload",
        lambda result, missing_still: {
            "kind": result.kind,
            "missing_still": missing_still,
            "delegated": True,
        },
    )

    assert await rpc_skills._handle_skills_status(None, ctx) == [
        {"name": "status", "loader": True}
    ]
    assert await rpc_skills._handle_skills_list(None, ctx) == {
        "skills": [{"name": "list", "loader": True}]
    }
    assert await rpc_skills._handle_skills_bins(None, ctx) == {"node": True}
    assert await rpc_skills._handle_skills_get({"name": "planner"}, ctx) == {
        "name": "planner",
        "loader": True,
    }
    async def fake_unavailable_search_skills(
        actual_router: object,
        request: object,
    ) -> SimpleNamespace:
        assert actual_router is None
        return SimpleNamespace(results=[], installed_names=set(), unavailable=True)

    monkeypatch.setattr(rpc_skills, "search_skills", fake_unavailable_search_skills)
    assert await rpc_skills._handle_skills_search({"query": "planner"}, ctx) == {
        "results": [],
        "delegated": True,
    }
    assert await rpc_skills._handle_skills_install({"identifier": "planner"}, object()) == {
        "success": False,
        "message": "No skill loader configured",
        "delegated": True,
    }
    deps_loader = SimpleNamespace()
    deps_ctx = SimpleNamespace(skill_loader=deps_loader)

    async def fake_install_loaded_skill_dependency(
        actual_loader: object,
        request: object,
    ) -> SimpleNamespace:
        assert actual_loader is deps_loader
        assert request == ("deps", {"name": "planner", "install_id": "brew"})
        return SimpleNamespace(
            result=SimpleNamespace(success=True, kind="brew", message="installed"),
            missing_still={"bins": [], "env": []},
        )

    monkeypatch.setattr(
        rpc_skills,
        "skill_deps_install_request",
        lambda params: ("deps", params),
    )
    monkeypatch.setattr(
        rpc_skills,
        "install_loaded_skill_dependency",
        fake_install_loaded_skill_dependency,
    )
    assert await rpc_skills._handle_skills_deps_install(
        {"name": "planner", "install_id": "brew"},
        deps_ctx,
    ) == {
        "kind": "brew",
        "missing_still": {"bins": [], "env": []},
        "delegated": True,
    }

    async def fake_unavailable_update_operation(
        actual_loader: object | None,
        request: object,
    ) -> SimpleNamespace:
        if actual_loader is None:
            return SimpleNamespace(
                results=[],
                unavailable_message="No skill loader configured",
                unavailable_payload="empty_results",
            )
        assert actual_loader is loader
        return SimpleNamespace(
            results=[],
            unavailable_message="No skill installer configured",
            unavailable_payload="unavailable",
        )

    async def fake_unavailable_uninstall_operation(
        actual_loader: object | None,
        request: object,
    ) -> SimpleNamespace:
        assert actual_loader is loader
        return SimpleNamespace(
            result=None,
            unavailable_message="No skill installer configured",
        )

    monkeypatch.setattr(
        rpc_skills,
        "run_skills_update_operation",
        fake_unavailable_update_operation,
    )
    monkeypatch.setattr(
        rpc_skills,
        "run_skill_uninstall_operation",
        fake_unavailable_uninstall_operation,
    )
    assert await rpc_skills._handle_skills_update(None, object()) == {
        "results": [],
        "success": False,
        "message": "No skill loader configured",
        "delegated": True,
    }
    assert await rpc_skills._handle_skills_update(None, ctx) == {
        "success": False,
        "message": "No skill installer configured",
        "delegated": True,
    }
    assert await rpc_skills._handle_skills_uninstall({"name": "planner"}, ctx) == {
        "success": False,
        "message": "No skill installer configured",
        "delegated": True,
    }


@pytest.mark.asyncio
async def test_gateway_delegates_skill_operations_to_hub_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loader = object()
    ctx = SimpleNamespace(skill_loader=loader)
    calls: list[tuple[str, object]] = []

    async def fake_run_skill_install_operation(
        actual_loader: object,
        request: object,
    ) -> SimpleNamespace:
        assert actual_loader is loader
        calls.append(("install", request))
        return SimpleNamespace(
            result=SimpleNamespace(
                success=True,
                name="planner",
                message="installed",
                scan=None,
            ),
            unavailable_message="",
        )

    async def fake_run_skills_update_operation(
        actual_loader: object,
        request: object,
    ) -> SimpleNamespace:
        assert actual_loader is loader
        calls.append(("update", request))
        return SimpleNamespace(
            results=[SimpleNamespace(success=True, name="planner", message="updated")],
            unavailable_message="",
            unavailable_payload="empty_results",
        )

    async def fake_run_skill_uninstall_operation(
        actual_loader: object,
        request: object,
    ) -> SimpleNamespace:
        assert actual_loader is loader
        calls.append(("uninstall", request))
        return SimpleNamespace(
            result=SimpleNamespace(success=True, name="planner", message="removed"),
            unavailable_message="",
        )

    monkeypatch.setattr(rpc_skills, "skill_install_request", lambda params: ("install", params))
    monkeypatch.setattr(rpc_skills, "skills_update_request", lambda params: ("update", params))
    monkeypatch.setattr(
        rpc_skills,
        "skill_uninstall_request",
        lambda params: ("uninstall", params),
    )
    monkeypatch.setattr(
        rpc_skills,
        "run_skill_install_operation",
        fake_run_skill_install_operation,
    )
    monkeypatch.setattr(
        rpc_skills,
        "run_skills_update_operation",
        fake_run_skills_update_operation,
    )
    monkeypatch.setattr(
        rpc_skills,
        "run_skill_uninstall_operation",
        fake_run_skill_uninstall_operation,
    )

    assert await rpc_skills._handle_skills_install(
        {"identifier": "planner"},
        ctx,
    ) == {
        "success": True,
        "name": "planner",
        "message": "installed",
    }
    assert await rpc_skills._handle_skills_update({"name": "planner"}, ctx) == {
        "results": [{"success": True, "name": "planner", "message": "updated"}]
    }
    assert await rpc_skills._handle_skills_uninstall({"name": "planner"}, ctx) == {
        "success": True,
        "name": "planner",
        "message": "removed",
    }
    assert calls == [
        ("install", ("install", {"identifier": "planner"})),
        ("update", ("update", {"name": "planner"})),
        ("uninstall", ("uninstall", {"name": "planner"})),
    ]


def test_gateway_rpc_skills_keeps_payload_logic_out_of_gateway_boundary() -> None:
    source = Path(rpc_skills.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_modules = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    imported_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_helpers = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "opensquilla.skills.rpc_payload"
        for alias in node.names
    }
    top_level_functions = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    top_level_assigns = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    handlers = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_skills_search"
    }
    handler_names = {
        node.id
        for handler in handlers.values()
        for node in ast.walk(handler)
        if isinstance(node, ast.Name)
    }
    direct_key_sets = {
        tuple(key.value for key in node.keys if isinstance(key, ast.Constant))
        for handler in handlers.values()
        for node in ast.walk(handler)
        if isinstance(node, ast.Dict)
    }
    handler_attrs = {
        node.attr
        for handler in handlers.values()
        for node in ast.walk(handler)
        if isinstance(node, ast.Attribute)
    }
    handler_constants = {
        node.value
        for handler in handlers.values()
        for node in ast.walk(handler)
        if isinstance(node, ast.Constant)
    }

    assert "opensquilla.skills.eligibility" not in imported_modules
    assert "opensquilla.paths" not in imported_modules
    assert "opensquilla.skills.hub.deps" not in imported_modules
    assert "opensquilla.skills.hub.operations" in imported_modules
    assert "opensquilla.skills.hub.clawhub" not in imported_modules
    assert "opensquilla.skills.hub.github" not in imported_modules
    assert "opensquilla.skills.hub.installer" not in imported_modules
    assert "opensquilla.skills.hub.router" not in imported_modules
    assert "opensquilla.skills.hub.defaults" not in imported_modules
    assert "opensquilla.skills.hub.lockfile" not in imported_modules
    assert "opensquilla.skills.hub.search" not in imported_modules
    assert "opensquilla.skills.loader" not in imported_modules
    assert "asyncio" not in imported_names
    assert "shutil" not in imported_names
    assert "weakref" not in imported_names
    assert "_deps_lock_for" not in top_level_functions
    assert "_installed_names" not in top_level_functions
    assert "_invalidate_loader" not in top_level_functions
    assert "_get_default_router" not in top_level_functions
    assert "_get_default_installer" not in top_level_functions
    assert "_deps_locks" not in top_level_assigns
    assert "_default_router" not in top_level_assigns
    assert "_default_installer" not in top_level_assigns
    assert {
        "skills_search_rpc_payload",
        "skills_search_unavailable_rpc_payload",
        "skill_deps_install_result_rpc_payload",
        "skill_install_result_rpc_payload",
        "skill_install_unavailable_rpc_payload",
        "skill_uninstall_result_rpc_payload",
        "skill_uninstall_unavailable_rpc_payload",
        "skills_bins_rpc_payload",
        "skills_update_empty_results_rpc_payload",
        "skills_update_results_rpc_payload",
        "skills_update_unavailable_rpc_payload",
    }.issubset(imported_helpers)
    assert {
        "search_skills",
        "skill_search_request",
        "skills_search_rpc_payload",
        "skills_search_unavailable_rpc_payload",
    }.issubset(handler_names)
    assert "search" not in handler_attrs
    assert "query" not in handler_constants
    assert "limit" not in handler_constants
    assert "source" not in handler_constants
    assert "get_default_skill_router" not in handler_names
    bins_handler = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_skills_bins"
    }
    bins_handler_names = {
        node.id
        for handler in bins_handler.values()
        for node in ast.walk(handler)
        if isinstance(node, ast.Name)
    }
    bins_direct_key_sets = {
        tuple(key.value for key in node.keys if isinstance(key, ast.Constant))
        for handler in bins_handler.values()
        for node in ast.walk(handler)
        if isinstance(node, ast.Dict)
    }
    assert {"skills_bins_rpc_payload"}.issubset(bins_handler_names)
    install_handler = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_skills_install"
    }
    install_handler_names = {
        node.id
        for handler in install_handler.values()
        for node in ast.walk(handler)
        if isinstance(node, ast.Name)
    }
    install_direct_key_sets = {
        tuple(key.value for key in node.keys if isinstance(key, ast.Constant))
        for handler in install_handler.values()
        for node in ast.walk(handler)
        if isinstance(node, ast.Dict)
    }
    install_handler_constants = {
        node.value
        for handler in install_handler.values()
        for node in ast.walk(handler)
        if isinstance(node, ast.Constant)
    }
    install_handler_attrs = {
        node.attr
        for handler in install_handler.values()
        for node in ast.walk(handler)
        if isinstance(node, ast.Attribute)
    }
    assert {
        "run_skill_install_operation",
        "skill_install_request",
        "skill_install_result_rpc_payload",
        "skill_install_unavailable_rpc_payload",
    }.issubset(install_handler_names)
    assert "identifier" not in install_handler_constants
    assert "source" not in install_handler_constants
    assert "force" not in install_handler_constants
    assert "get_default_skill_installer" not in install_handler_names
    assert "invalidate_cache" not in install_handler_attrs
    update_handler = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_skills_update"
    }
    update_handler_names = {
        node.id
        for handler in update_handler.values()
        for node in ast.walk(handler)
        if isinstance(node, ast.Name)
    }
    update_direct_key_sets = {
        tuple(key.value for key in node.keys if isinstance(key, ast.Constant))
        for handler in update_handler.values()
        for node in ast.walk(handler)
        if isinstance(node, ast.Dict)
    }
    update_handler_constants = {
        node.value
        for handler in update_handler.values()
        for node in ast.walk(handler)
        if isinstance(node, ast.Constant)
    }
    update_handler_attrs = {
        node.attr
        for handler in update_handler.values()
        for node in ast.walk(handler)
        if isinstance(node, ast.Attribute)
    }
    assert {
        "run_skills_update_operation",
        "skills_update_request",
        "skills_update_empty_results_rpc_payload",
        "skills_update_results_rpc_payload",
        "skills_update_unavailable_rpc_payload",
    }.issubset(update_handler_names)
    assert "name" not in update_handler_constants
    assert "No skill loader configured" not in update_handler_constants
    assert "No skill installer configured" not in update_handler_constants
    assert "get_default_skill_installer" not in update_handler_names
    assert "invalidate_cache" not in update_handler_attrs
    assert "OSError" not in update_handler_names
    uninstall_handler = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_skills_uninstall"
    }
    uninstall_handler_names = {
        node.id
        for handler in uninstall_handler.values()
        for node in ast.walk(handler)
        if isinstance(node, ast.Name)
    }
    uninstall_direct_key_sets = {
        tuple(key.value for key in node.keys if isinstance(key, ast.Constant))
        for handler in uninstall_handler.values()
        for node in ast.walk(handler)
        if isinstance(node, ast.Dict)
    }
    uninstall_handler_constants = {
        node.value
        for handler in uninstall_handler.values()
        for node in ast.walk(handler)
        if isinstance(node, ast.Constant)
    }
    uninstall_handler_attrs = {
        node.attr
        for handler in uninstall_handler.values()
        for node in ast.walk(handler)
        if isinstance(node, ast.Attribute)
    }
    assert {
        "run_skill_uninstall_operation",
        "skill_uninstall_request",
        "skill_uninstall_result_rpc_payload",
        "skill_uninstall_unavailable_rpc_payload",
    }.issubset(uninstall_handler_names)
    assert "name" not in uninstall_handler_constants
    assert "No skill installer configured" not in uninstall_handler_constants
    assert "get_default_skill_installer" not in uninstall_handler_names
    assert "invalidate_cache" not in uninstall_handler_attrs
    deps_install_handler = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_skills_deps_install"
    }
    deps_install_handler_names = {
        node.id
        for handler in deps_install_handler.values()
        for node in ast.walk(handler)
        if isinstance(node, ast.Name)
    }
    deps_install_direct_key_sets = {
        tuple(key.value for key in node.keys if isinstance(key, ast.Constant))
        for handler in deps_install_handler.values()
        for node in ast.walk(handler)
        if isinstance(node, ast.Dict)
    }
    deps_install_handler_attrs = {
        node.attr
        for handler in deps_install_handler.values()
        for node in ast.walk(handler)
        if isinstance(node, ast.Attribute)
    }
    deps_install_handler_constants = {
        node.value
        for handler in deps_install_handler.values()
        for node in ast.walk(handler)
        if isinstance(node, ast.Constant)
    }
    assert {
        "install_loaded_skill_dependency",
        "skill_deps_install_request",
        "skill_deps_install_result_rpc_payload",
    }.issubset(deps_install_handler_names)
    assert "get_by_name" not in deps_install_handler_attrs
    assert "name" not in deps_install_handler_constants
    assert "install_id" not in deps_install_handler_constants
    assert "install_deps" not in deps_install_handler_names
    assert "validate_skill_install_supported" not in deps_install_handler_names
    assert "skill_missing_requirements_rpc_payload" not in deps_install_handler_names
    assert "_skill_to_dict" not in top_level_functions
    assert "_status_from_report" not in top_level_functions
    assert "_status_detail" not in top_level_functions
    assert ("results", "message") not in direct_key_sets
    assert ("results",) not in direct_key_sets
    assert (
        "name",
        "description",
        "version",
        "author",
        "source",
        "trust_level",
        "identifier",
        "installed",
    ) not in direct_key_sets
    assert ("success", "message") not in install_direct_key_sets
    assert ("success", "name", "message") not in install_direct_key_sets
    assert ("scan_verdict", "scan_findings") not in install_direct_key_sets
    assert ("results", "success", "message") not in update_direct_key_sets
    assert ("success", "message") not in update_direct_key_sets
    assert ("results",) not in update_direct_key_sets
    assert ("success", "message") not in uninstall_direct_key_sets
    assert ("success", "name", "message") not in uninstall_direct_key_sets
    assert (
        "success",
        "kind",
        "message",
        "missing_still",
    ) not in deps_install_direct_key_sets
    assert () not in bins_direct_key_sets
