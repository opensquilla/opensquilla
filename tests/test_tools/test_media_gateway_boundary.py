"""Architecture guards for media tools decoupling."""

from __future__ import annotations

import ast
from pathlib import Path

MEDIA_TOOL = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "opensquilla"
    / "tools"
    / "builtin"
    / "media.py"
)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_media_tool_does_not_import_gateway() -> None:
    offenders = sorted(
        module
        for module in _imported_modules(MEDIA_TOOL)
        if module == "opensquilla.gateway" or module.startswith("opensquilla.gateway.")
    )

    assert offenders == []


def test_media_tool_source_does_not_reference_gateway_package() -> None:
    assert "opensquilla.gateway" not in MEDIA_TOOL.read_text(encoding="utf-8")
