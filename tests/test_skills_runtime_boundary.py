from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from opensquilla.skills import runtime as skill_runtime
from opensquilla.tools.builtin import skill_tools

ROOT = Path(__file__).resolve().parents[1]
SKILL_TOOLS = ROOT / "src/opensquilla/tools/builtin/skill_tools.py"
BOOT = ROOT / "src/opensquilla/gateway/boot.py"
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


def test_skill_tool_does_not_own_loader_runtime_state() -> None:
    assert "_loader" not in _top_level_names(SKILL_TOOLS)


def test_skill_tool_uses_skills_runtime_boundary() -> None:
    imports = _imports_from(SKILL_TOOLS)

    assert ("opensquilla.skills.runtime", "configure_skill_loader") in imports
    assert ("opensquilla.skills.runtime", "current_skill_loader") in imports


def test_boot_documents_skills_runtime_side_effect() -> None:
    source = BOOT.read_text(encoding="utf-8")

    assert "- skills.runtime" in source
    assert "create_configured_skill_loader + configure_skill_loader" in source
    assert "via create_skill_tools" in source


def test_boot_delegates_skill_loader_construction_to_skills_runtime() -> None:
    imports = _runtime_imports_from(BOOT)

    assert ("opensquilla.skills.runtime", "create_configured_skill_loader") in imports
    assert ("opensquilla.skills.loader", "SkillLoader") not in imports
    assert ("opensquilla.skills.paths", "resolve_skill_layer_dirs") not in imports


def test_skills_public_api_exposes_loader_setup_boundary() -> None:
    imports = _imports_from(SKILLS_INIT)

    assert ("opensquilla.skills.runtime", "SkillLoaderSetup") in imports
    assert ("opensquilla.skills.runtime", "create_configured_skill_loader") in imports


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
