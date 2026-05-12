"""Architecture import-contract regression tests."""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "opensquilla"

APPROVED_PACKAGE_IMPORTS: frozenset[tuple[str, str]] = frozenset({
    ("agents", "gateway"),
    ("agents", "identity"),
    ("agents", "onboarding"),
    ("agents", "session"),
    ("channels", "engine"),
    ("channels", "gateway"),
    ("channels", "session"),
    ("cli", "agents"),
    ("cli", "dist"),
    ("cli", "engine"),
    ("cli", "gateway"),
    ("cli", "memory"),
    ("cli", "mcp_server"),
    ("cli", "observability"),
    ("cli", "onboarding"),
    ("cli", "sandbox"),
    ("cli", "session"),
    ("cli", "skills"),
    ("cli", "tools"),
    ("engine", "agents"),
    ("engine", "channels"),
    ("engine", "gateway"),
    ("engine", "identity"),
    ("engine", "memory"),
    ("engine", "observability"),
    ("engine", "provider"),
    ("engine", "safety"),
    ("engine", "session"),
    ("engine", "skills"),
    ("engine", "squilla_router"),
    ("engine", "tools"),
    ("gateway", "agents"),
    ("gateway", "channels"),
    ("gateway", "engine"),
    ("gateway", "identity"),
    ("gateway", "mcp"),
    ("gateway", "memory"),
    ("gateway", "observability"),
    ("gateway", "onboarding"),
    ("gateway", "persistence"),
    ("gateway", "provider"),
    ("gateway", "sandbox"),
    ("gateway", "scheduler"),
    ("gateway", "search"),
    ("gateway", "session"),
    ("gateway", "skills"),
    ("gateway", "tools"),
    ("identity", "safety"),
    ("identity", "session"),
    ("mcp", "tools"),
    ("memory", "agents"),
    ("memory", "compat"),
    ("memory", "engine"),
    ("memory", "gateway"),
    ("memory", "identity"),
    ("memory", "provider"),
    ("memory", "tools"),
    ("onboarding", "channels"),
    ("onboarding", "gateway"),
    ("onboarding", "provider"),
    ("onboarding", "search"),
    ("provider", "engine"),
    ("sandbox", "gateway"),
    ("sandbox", "safety"),
    ("sandbox", "tools"),
    ("scheduler", "agents"),
    ("scheduler", "channels"),
    ("scheduler", "compat"),
    ("scheduler", "engine"),
    ("scheduler", "gateway"),
    ("scheduler", "session"),
    ("scheduler", "tools"),
    ("session", "compat"),
    ("session", "engine"),
    ("session", "gateway"),
    ("session", "provider"),
    ("session", "tools"),
    ("skills", "memory"),
    ("skills", "safety"),
    ("tools", "agents"),
    ("tools", "channels"),
    ("tools", "engine"),
    ("tools", "gateway"),
    ("tools", "identity"),
    ("tools", "memory"),
    ("tools", "provider"),
    ("tools", "safety"),
    ("tools", "sandbox"),
    ("tools", "scheduler"),
    ("tools", "search"),
    ("tools", "session"),
    ("tools", "skills"),
})

APPROVED_CYCLIC_PACKAGES: frozenset[str] = frozenset({
    "agents",
    "channels",
    "engine",
    "gateway",
    "identity",
    "mcp",
    "memory",
    "onboarding",
    "provider",
    "sandbox",
    "scheduler",
    "session",
    "skills",
    "tools",
})


def _top_level_packages() -> set[str]:
    return {
        path.name
        for path in PACKAGE_ROOT.iterdir()
        if path.is_dir() and not path.name.startswith("__")
    }


def _resolve_relative_import(file_path: Path, node: ast.ImportFrom) -> list[str]:
    rel_path = file_path.relative_to(PACKAGE_ROOT)
    package_parts = ("opensquilla", *rel_path.parent.parts)
    if node.level > len(package_parts):
        return []

    base_parts = package_parts[: len(package_parts) - node.level + 1]
    module_parts = tuple(node.module.split(".")) if node.module else ()
    resolved = ".".join((*base_parts, *module_parts))
    if resolved == "opensquilla":
        return [f"opensquilla.{alias.name}" for alias in node.names if alias.name != "*"]
    return [resolved]


def _module_imports(tree: ast.AST, file_path: Path) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                modules.extend(_resolve_relative_import(file_path, node))
            elif node.module:
                modules.append(node.module)
    return modules


def _package_import_edges() -> set[tuple[str, str]]:
    packages = _top_level_packages()
    edges: set[tuple[str, str]] = set()
    for file_path in PACKAGE_ROOT.rglob("*.py"):
        if "__pycache__" in file_path.parts:
            continue
        source_pkg = file_path.relative_to(PACKAGE_ROOT).parts[0]
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        for module in _module_imports(tree, file_path):
            if not module.startswith("opensquilla."):
                continue
            parts = module.split(".")
            if len(parts) < 2:
                continue
            target_pkg = parts[1]
            if target_pkg in packages and target_pkg != source_pkg:
                edges.add((source_pkg, target_pkg))
    return edges


def _strongly_connected_components(
    edges: set[tuple[str, str]], packages: set[str]
) -> list[frozenset[str]]:
    adjacency: dict[str, set[str]] = {package: set() for package in packages}
    for source, target in edges:
        adjacency.setdefault(source, set()).add(target)
        adjacency.setdefault(target, set())

    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indexes: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    components: list[frozenset[str]] = []

    def visit(package: str) -> None:
        nonlocal index
        indexes[package] = index
        lowlinks[package] = index
        index += 1
        stack.append(package)
        on_stack.add(package)

        for target in adjacency.get(package, set()):
            if target not in indexes:
                visit(target)
                lowlinks[package] = min(lowlinks[package], lowlinks[target])
            elif target in on_stack:
                lowlinks[package] = min(lowlinks[package], indexes[target])

        if lowlinks[package] == indexes[package]:
            component: set[str] = set()
            while True:
                target = stack.pop()
                on_stack.remove(target)
                component.add(target)
                if target == package:
                    break
            components.append(frozenset(component))

    for package in sorted(adjacency):
        if package not in indexes:
            visit(package)
    return components


def test_package_imports_do_not_add_new_edges() -> None:
    """New top-level package imports must update the architecture contract deliberately."""
    actual_edges = _package_import_edges()
    unexpected = actual_edges - APPROVED_PACKAGE_IMPORTS
    assert not unexpected, "Unexpected package import edges: " + ", ".join(
        f"{source}->{target}" for source, target in sorted(unexpected)
    )


def test_relative_imports_are_resolved_for_edge_detection() -> None:
    tree = ast.parse("from ..gateway.routing import build_channel_route_envelope\n")
    fake_file = PACKAGE_ROOT / "scheduler" / "handlers.py"

    assert "opensquilla.gateway.routing" in _module_imports(tree, fake_file)


def test_new_packages_do_not_join_existing_circular_dependency_baseline() -> None:
    """The known cyclic package set is a shrink target, not an expansion point."""
    actual_edges = _package_import_edges()
    cyclic_packages = frozenset(
        package
        for component in _strongly_connected_components(actual_edges, _top_level_packages())
        if len(component) > 1
        for package in component
    )
    unexpected = cyclic_packages - APPROVED_CYCLIC_PACKAGES
    assert not unexpected, "Packages unexpectedly joined import cycles: " + ", ".join(
        sorted(unexpected)
    )
