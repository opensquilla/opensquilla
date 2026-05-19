from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from opensquilla.skills import runtime as skill_runtime
from opensquilla.skills.eligibility import EligibilityContext, EligibilityReport
from opensquilla.skills.types import (
    SkillInstallSpec,
    SkillLayer,
    SkillPlatformMeta,
    SkillProvenance,
    SkillRequires,
    SkillSpec,
)
from opensquilla.tools.builtin import skill_tools

ROOT = Path(__file__).resolve().parents[1]
SKILL_TOOLS = ROOT / "src/opensquilla/tools/builtin/skill_tools.py"
BOOT = ROOT / "src/opensquilla/gateway/boot.py"
EXTENSION_RUNTIME = ROOT / "src/opensquilla/extension_services/gateway_runtime.py"
CLI_SKILLS = ROOT / "src/opensquilla/cli/skills_cmd.py"
CLI_SKILLS_ROWS = ROOT / "src/opensquilla/cli/skills_rows.py"
SKILLS_RUNTIME_FACADE = ROOT / "src/opensquilla/skills/runtime_facade.py"
SKILLS_INIT = ROOT / "src/opensquilla/skills/__init__.py"


class _Loader:
    workspace_dir = None

    def load_all(self) -> list[object]:
        return []

    def get_by_name(self, name: str) -> object | None:
        return None

    def invalidate_cache(self) -> None:
        return None


def _top_level_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _imports_from(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imports.add((node.module, alias.name))
    return imports


def _runtime_imports_from(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[tuple[str, str]] = set()

    class Visitor(ast.NodeVisitor):
        def visit_If(self, node: ast.If) -> None:
            if isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING":
                for child in node.orelse:
                    self.visit(child)
                return
            self.generic_visit(node)

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            if node.module:
                for alias in node.names:
                    imports.add((node.module, alias.name))

    Visitor().visit(tree)
    return imports


def _skill(**overrides: Any) -> SkillSpec:
    values: dict[str, Any] = {
        "name": "planner",
        "description": "Plan work",
        "layer": SkillLayer.WORKSPACE,
        "always": False,
        "triggers": ["plan"],
        "content": "Use a plan.",
        "metadata": SkillPlatformMeta(
            primary_env="PLANNER_TOKEN",
            requires=SkillRequires(bins=["node"], env=["PLANNER_TOKEN"]),
            install=[
                SkillInstallSpec(
                    id="node",
                    kind="brew",
                    label="Node",
                    bins=["node"],
                    formula="node",
                )
            ],
        ),
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


class _SkillLoader:
    workspace_dir = None

    def __init__(self, skills: list[SkillSpec]) -> None:
        self._skills = skills

    def load_all(self) -> list[SkillSpec]:
        return list(self._skills)

    def get_by_name(self, name: str) -> SkillSpec | None:
        return next((skill for skill in self._skills if skill.name == name), None)

    def invalidate_cache(self) -> None:
        return None


def test_skill_tool_does_not_own_loader_runtime_state() -> None:
    assert "_loader" not in _top_level_names(SKILL_TOOLS)


def test_skill_tool_uses_skills_runtime_boundary() -> None:
    imports = _imports_from(SKILL_TOOLS)

    assert ("opensquilla.skills.runtime", "configure_skill_loader") in imports
    assert ("opensquilla.skills.runtime", "current_skill_loader") in imports


def test_boot_documents_skills_runtime_side_effect() -> None:
    source = BOOT.read_text(encoding="utf-8")

    assert "- extension_services.gateway_runtime" in source
    assert "skills runtime" in source


def test_extension_services_delegates_skill_loader_construction_to_skills_runtime() -> None:
    boot_imports = _runtime_imports_from(BOOT)
    extension_imports = _runtime_imports_from(EXTENSION_RUNTIME)

    assert (
        "opensquilla.extension_services.gateway_runtime",
        "build_extension_services_runtime",
    ) in boot_imports
    assert ("opensquilla.skills.runtime", "create_configured_skill_loader") not in boot_imports
    assert ("opensquilla.skills.runtime", "create_configured_skill_loader") in extension_imports
    assert ("opensquilla.skills.loader", "SkillLoader") not in boot_imports
    assert ("opensquilla.skills.loader", "SkillLoader") not in extension_imports
    assert ("opensquilla.skills.paths", "resolve_skill_layer_dirs") not in boot_imports
    assert ("opensquilla.skills.paths", "resolve_skill_layer_dirs") not in extension_imports


def test_cli_delegates_skill_loader_construction_to_skills_runtime() -> None:
    imports = _runtime_imports_from(CLI_SKILLS_ROWS)

    assert ("opensquilla.skills", "runtime") in imports
    assert ("opensquilla.skills.runtime_facade", "loaded_skill_rows") in imports
    assert ("opensquilla.skills.loader", "SkillLoader") not in imports
    assert ("opensquilla.skills.paths", "resolve_skill_layer_dirs") not in imports


def test_cli_skill_rows_delegate_loaded_skill_rows_to_runtime_facade() -> None:
    imports = _runtime_imports_from(CLI_SKILLS_ROWS)

    assert ("opensquilla.skills.runtime_facade", "loaded_skill_rows") in imports
    assert ("opensquilla.skills.eligibility", "EligibilityContext") not in imports
    assert ("opensquilla.skills.eligibility", "check_eligibility") not in imports


def test_skill_tools_delegate_loaded_skill_helpers_to_runtime_facade() -> None:
    imports = _runtime_imports_from(SKILL_TOOLS)

    assert ("opensquilla.skills.runtime_facade", "loaded_skill_list_text") in imports
    assert ("opensquilla.skills.runtime_facade", "read_loaded_skill_resource") in imports
    assert ("opensquilla.skills.runtime_facade", "loaded_skill_dependency_preview") in imports
    assert ("opensquilla.skills.eligibility", "EligibilityContext") not in imports
    assert ("opensquilla.skills.eligibility", "diagnose_eligibility") not in imports
    assert ("opensquilla.skills.resources", "SkillResources") not in imports


def test_skills_runtime_facade_has_no_adapter_layer_imports() -> None:
    imports = _runtime_imports_from(SKILLS_RUNTIME_FACADE)

    assert {
        module
        for module, _name in imports
        if module.startswith(
            (
                "opensquilla.gateway",
                "opensquilla.cli",
                "opensquilla.tools",
            )
        )
    } == set()


def test_skills_public_api_exposes_loader_setup_boundary() -> None:
    imports = _imports_from(SKILLS_INIT)

    assert ("opensquilla.skills.runtime", "SkillLoaderSetup") in imports
    assert ("opensquilla.skills.runtime", "create_configured_skill_loader") in imports


def test_skills_runtime_facade_preserves_cli_row_shape(
    monkeypatch,
) -> None:
    from opensquilla.skills import runtime_facade

    ctx = EligibilityContext(os_name="linux", has_bin_cache={"node": True})
    skill = _skill(path=None)
    loader = _SkillLoader([skill])
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        runtime_facade.EligibilityContext,
        "auto",
        staticmethod(lambda: calls.append(("ctx", None)) or ctx),
    )
    monkeypatch.setattr(
        runtime_facade,
        "check_eligibility",
        lambda actual_skill, actual_ctx: (
            calls.append(("eligible", (actual_skill.name, actual_ctx is ctx))) or True
        ),
    )

    assert runtime_facade.loaded_skill_rows(loader) == [
        {
            "name": "planner",
            "layer": "workspace",
            "eligible": True,
            "description": "Plan work",
            "always": False,
            "triggers": ["plan"],
            "path": "",
            "filePath": "/tmp/planner/SKILL.md",
            "baseDir": "/tmp/planner",
            "homepage": "https://example.test/planner",
            "userInvocable": True,
            "disableModelInvocation": False,
            "provenance": {
                "origin": "fixture",
                "license": "MIT",
                "upstreamUrl": "https://example.test/upstream",
                "maintainedBy": "Tests",
            },
        }
    ]
    assert calls == [("ctx", None), ("eligible", ("planner", True))]


def test_skills_runtime_facade_preserves_rpc_status_list_and_get_shape(
    monkeypatch,
) -> None:
    from opensquilla.skills import runtime_facade

    skill = _skill()
    loader = _SkillLoader([skill])
    ctx = EligibilityContext(os_name="linux", has_bin_cache={"node": False})
    report = EligibilityReport(
        eligible=False,
        declared=True,
        reasons=["Missing binary: node"],
        missing_bins=["node"],
        missing_env=["PLANNER_TOKEN"],
    )

    monkeypatch.setattr(
        runtime_facade.EligibilityContext,
        "auto",
        staticmethod(lambda: ctx),
    )
    monkeypatch.setattr(
        runtime_facade,
        "diagnose_eligibility",
        lambda actual_skill, actual_ctx: report,
    )

    status_payload = runtime_facade.skills_status_payload(loader)

    assert status_payload == [
        {
            "name": "planner",
            "description": "Plan work",
            "layer": "workspace",
            "always": False,
            "triggers": ["plan"],
            "eligible": False,
            "emoji": "",
            "primary_env": "PLANNER_TOKEN",
            "homepage": "",
            "file_path": "/tmp/planner/SKILL.md",
            "os": [],
            "disabled": False,
            "install": [
                {"id": "node", "kind": "brew", "label": "Node", "bins": ["node"]}
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
    ]
    assert runtime_facade.skills_list_payload(loader) == {"skills": status_payload}

    get_payload = runtime_facade.skill_get_payload({"name": "planner"}, loader)
    assert get_payload["content"] == "Use a plan."
    assert get_payload["file_path"] == "/tmp/planner/SKILL.md"
    assert get_payload["base_dir"] == "/tmp/planner"


def test_skills_runtime_facade_preserves_tool_list_view_and_deps_preview(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from opensquilla.skills import runtime_facade

    skill_dir = tmp_path / "planner"
    refs = skill_dir / "references"
    refs.mkdir(parents=True)
    (refs / "notes.md").write_text("Reference notes", encoding="utf-8")
    skill = _skill(base_dir=str(skill_dir), content="# Planner")
    loader = _SkillLoader([skill])

    monkeypatch.setattr(
        runtime_facade.EligibilityContext,
        "auto",
        staticmethod(lambda: EligibilityContext(os_name="linux", has_bin_cache={})),
    )
    monkeypatch.setattr(
        runtime_facade,
        "diagnose_eligibility",
        lambda _skill, _ctx: EligibilityReport(
            eligible=False,
            declared=True,
            missing_bins=["node"],
            missing_env=["PLANNER_TOKEN"],
            install_hints=[SimpleNamespace(command="brew install node")],
        ),
    )

    assert runtime_facade.loaded_skill_list_text(loader) == "\n".join(
        [
            "Available skills (1):",
            "  - planner: Plan work",
            "      [unavailable] Missing: node (binary), PLANNER_TOKEN (env var)",
            "      Install: brew install node",
            "      Hint: Set environment variable PLANNER_TOKEN",
        ]
    )
    assert runtime_facade.read_loaded_skill_resource(loader, "planner") == "# Planner"
    assert runtime_facade.read_loaded_skill_resource(loader, "planner", "references/notes.md") == (
        "Reference notes"
    )
    assert json.loads(
        runtime_facade.loaded_skill_dependency_preview(loader, "planner", "node").to_json()
    ) == {
        "status": "preview",
        "skill_name": "planner",
        "install_id": "node",
        "kind": "brew",
        "label": "Node",
        "argv": ["brew", "install", "node"],
    }



def test_create_configured_skill_loader_resolves_layer_dirs(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_skills = workspace_root / "skills"
    workspace_skills.mkdir(parents=True)
    managed_dir = tmp_path / "managed"
    extra_dir = tmp_path / "extra"
    config = SimpleNamespace(
        allow_bundled=False,
        workspace_dir=None,
        managed_dir=str(managed_dir),
        extra_dirs=[str(extra_dir)],
    )

    setup = skill_runtime.create_configured_skill_loader(
        config,
        workspace_dir=workspace_root,
    )

    assert setup.layer_dirs.bundled_dir is None
    assert setup.layer_dirs.workspace_dir == workspace_skills
    assert setup.layer_dirs.managed_dir == managed_dir
    assert setup.layer_dirs.extra_dirs == [extra_dir]
    assert setup.loader.workspace_dir == workspace_skills


def test_create_skill_tools_sets_shared_skill_runtime() -> None:
    loader = _Loader()
    skill_runtime.reset_skill_runtime()

    skill_tools.create_skill_tools(loader)  # type: ignore[arg-type]

    assert skill_runtime.current_skill_loader() is loader
    assert skill_runtime.skill_loader_available() is True
    skill_runtime.reset_skill_runtime()
