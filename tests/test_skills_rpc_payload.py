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
    skill_status_from_report,
    skill_to_rpc_payload,
    skills_list_rpc_payload,
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


def test_gateway_rpc_skills_keeps_payload_logic_out_of_gateway_boundary() -> None:
    source = Path(rpc_skills.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_modules = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    top_level_functions = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert "opensquilla.skills.eligibility" not in imported_modules
    assert "_skill_to_dict" not in top_level_functions
    assert "_status_from_report" not in top_level_functions
    assert "_status_detail" not in top_level_functions
