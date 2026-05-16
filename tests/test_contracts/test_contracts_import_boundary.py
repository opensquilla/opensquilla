"""Contracts package import-boundary tests."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

CONTRACTS_ROOT = Path(__file__).resolve().parents[2] / "src" / "opensquilla" / "contracts"
FORBIDDEN_OPENSQUILLA_IMPORTS = frozenset(
    {
        "adapters",
        "agents",
        "application",
        "channels",
        "cli",
        "engine",
        "gateway",
        "identity",
        "mcp",
        "memory",
        "onboarding",
        "provider",
        "sandbox",
        "scheduler",
        "search",
        "session",
        "skills",
        "squilla_router",
        "tools",
    }
)


def _imports_for(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
    return imports


def test_contracts_public_surface_imports() -> None:
    contracts = importlib.import_module("opensquilla.contracts")

    assert "ProviderPort" in contracts.__all__
    assert "ToolRegistryPort" in contracts.__all__
    assert "ChannelIngressPort" in contracts.__all__
    assert "SessionStorePort" in contracts.__all__
    assert "SandboxPort" in contracts.__all__


def test_contracts_do_not_import_implementation_packages() -> None:
    offenders: list[str] = []
    for path in sorted(CONTRACTS_ROOT.glob("*.py")):
        for module in _imports_for(path):
            parts = module.split(".")
            if (
                len(parts) >= 2
                and parts[0] == "opensquilla"
                and parts[1] in FORBIDDEN_OPENSQUILLA_IMPORTS
            ):
                offenders.append(f"{path.name}: {module}")

    assert not offenders, "contracts must not import implementation packages: " + ", ".join(
        offenders
    )
