"""Architecture guards for provider/engine decoupling."""

from __future__ import annotations

import ast
from pathlib import Path

PROVIDER_ROOT = Path(__file__).resolve().parents[1] / "src" / "opensquilla" / "provider"


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_provider_package_does_not_import_engine() -> None:
    offenders: list[str] = []
    for path in PROVIDER_ROOT.rglob("*.py"):
        for module in _imported_modules(path):
            if module == "opensquilla.engine" or module.startswith("opensquilla.engine."):
                offenders.append(f"{path.relative_to(PROVIDER_ROOT)}:{module}")

    assert offenders == []


def test_engine_thinking_level_is_provider_reexport() -> None:
    from opensquilla.engine import types as engine_types
    from opensquilla.provider.thinking import THINKING_BUDGETS, ThinkingLevel

    assert engine_types.ThinkingLevel is ThinkingLevel
    assert engine_types.THINKING_BUDGETS is THINKING_BUDGETS
