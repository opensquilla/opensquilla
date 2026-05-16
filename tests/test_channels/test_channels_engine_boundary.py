from __future__ import annotations

import ast
from pathlib import Path

CHANNELS_ROOT = Path(__file__).resolve().parents[2] / "src" / "opensquilla" / "channels"


def _module_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_channels_package_does_not_import_engine_modules() -> None:
    imported_modules = {
        module
        for path in CHANNELS_ROOT.rglob("*.py")
        for module in _module_imports(path)
        if module == "opensquilla.engine" or module.startswith("opensquilla.engine.")
    }

    assert imported_modules == set()
