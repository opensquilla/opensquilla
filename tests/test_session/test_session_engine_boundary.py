"""Architecture guards for session package decoupling."""

from __future__ import annotations

import ast
from pathlib import Path

SESSION_ROOT = Path(__file__).resolve().parents[2] / "src" / "opensquilla" / "session"


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_session_package_does_not_import_engine_or_tools() -> None:
    offenders: list[str] = []
    blocked_prefixes = ("opensquilla.engine", "opensquilla.tools")
    blocked_subpackages = tuple(f"{prefix}." for prefix in blocked_prefixes)
    for path in SESSION_ROOT.rglob("*.py"):
        for module in _imported_modules(path):
            if module in blocked_prefixes or module.startswith(blocked_subpackages):
                offenders.append(f"{path.relative_to(SESSION_ROOT)}:{module}")

    assert offenders == []


def test_engine_time_prefix_is_session_reexport() -> None:
    from opensquilla.engine.steps import inject_time_prefix as engine_time_prefix
    from opensquilla.session import time_prefix

    assert engine_time_prefix.TIME_PREFIX_RE is time_prefix.TIME_PREFIX_RE
    assert engine_time_prefix.format_time_prefix is time_prefix.format_time_prefix
    assert engine_time_prefix.stamp is time_prefix.stamp
