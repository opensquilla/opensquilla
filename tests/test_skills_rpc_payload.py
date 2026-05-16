from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from opensquilla.gateway import rpc_skills
from opensquilla.skills.eligibility import EligibilityReport
from opensquilla.skills.rpc_payload import (
    skill_get_rpc_payload,
    skill_install_result_rpc_payload,
    skill_install_unavailable_rpc_payload,
    skill_status_from_report,
    skill_to_rpc_payload,
    skills_list_rpc_payload,
    skills_search_rpc_payload,
    skills_search_unavailable_rpc_payload,
    skills_status_rpc_payload,
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

    assert await rpc_skills._handle_skills_status(None, ctx) == [
        {"name": "status", "loader": True}
    ]
    assert await rpc_skills._handle_skills_list(None, ctx) == {
        "skills": [{"name": "list", "loader": True}]
    }
    assert await rpc_skills._handle_skills_get({"name": "planner"}, ctx) == {
        "name": "planner",
        "loader": True,
    }
    monkeypatch.setattr(rpc_skills, "_get_default_router", lambda: None)
    assert await rpc_skills._handle_skills_search({"query": "planner"}, ctx) == {
        "results": [],
        "delegated": True,
    }
    assert await rpc_skills._handle_skills_install({"identifier": "planner"}, object()) == {
        "success": False,
        "message": "No skill loader configured",
        "delegated": True,
    }


def test_gateway_rpc_skills_keeps_payload_logic_out_of_gateway_boundary() -> None:
    source = Path(rpc_skills.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_modules = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
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

    assert "opensquilla.skills.eligibility" not in imported_modules
    assert {
        "skills_search_rpc_payload",
        "skills_search_unavailable_rpc_payload",
        "skill_install_result_rpc_payload",
        "skill_install_unavailable_rpc_payload",
    }.issubset(imported_helpers)
    assert {
        "skills_search_rpc_payload",
        "skills_search_unavailable_rpc_payload",
    }.issubset(handler_names)
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
    assert {
        "skill_install_result_rpc_payload",
        "skill_install_unavailable_rpc_payload",
    }.issubset(install_handler_names)
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
