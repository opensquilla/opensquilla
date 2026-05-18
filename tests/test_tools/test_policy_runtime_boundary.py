from __future__ import annotations

import ast
from pathlib import Path

from opensquilla.tools.policy_runtime import (
    ToolSurfaceCapabilities,
    resolve_runtime_tool_surface,
    tool_surface_capabilities_from_runtime,
)
from opensquilla.tools.types import InteractionMode, ToolContext

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "src/opensquilla/tools/policy.py"
POLICY_RUNTIME = ROOT / "src/opensquilla/tools/policy_runtime.py"
VISIBILITY = ROOT / "src/opensquilla/tools/visibility.py"
SURFACE = ROOT / "src/opensquilla/tools/surface.py"
RPC_PAYLOAD = ROOT / "src/opensquilla/tools/rpc_payload.py"
REGISTRY = ROOT / "src/opensquilla/tools/registry.py"


def _imports_from(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imports.add((node.module, alias.name))
    return imports


def _top_level_classes(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {node.name for node in tree.body if isinstance(node, ast.ClassDef)}


def _top_level_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _top_level_assignments(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def test_policy_module_delegates_runtime_surface_to_policy_runtime_boundary() -> None:
    imports = _imports_from(POLICY)

    assert ("opensquilla.tools", "policy_runtime") in imports
    assert "ToolSurfaceCapabilities" not in _top_level_classes(POLICY)
    assert {
        "ToolSurfaceCapabilities",
        "resolve_runtime_tool_surface",
        "detect_runtime_tool_surface_capabilities",
        "tool_surface_capabilities_from_runtime",
    } <= _top_level_assignments(POLICY)
    assert "resolve_runtime_tool_surface" not in _top_level_functions(POLICY)
    assert "detect_runtime_tool_surface_capabilities" not in _top_level_functions(POLICY)
    assert "tool_surface_capabilities_from_runtime" not in _top_level_functions(POLICY)

    runtime_classes = _top_level_classes(POLICY_RUNTIME)
    runtime_functions = _top_level_functions(POLICY_RUNTIME)
    assert "ToolSurfaceCapabilities" in runtime_classes
    assert "resolve_runtime_tool_surface" in runtime_functions
    assert "detect_runtime_tool_surface_capabilities" in runtime_functions
    assert "tool_surface_capabilities_from_runtime" in runtime_functions


def test_tool_surface_depends_on_policy_runtime_not_policy_facade() -> None:
    surface_imports = _imports_from(SURFACE)
    assert (
        "opensquilla.tools.policy_runtime",
        "ToolSurfaceCapabilities",
    ) in surface_imports
    assert (
        "opensquilla.tools.policy_runtime",
        "resolve_runtime_tool_surface",
    ) in surface_imports
    assert (
        "opensquilla.tools.policy_runtime",
        "tool_surface_capabilities_from_runtime",
    ) in surface_imports

    for path in (SURFACE, VISIBILITY, RPC_PAYLOAD, REGISTRY):
        imports = _imports_from(path)
        assert ("opensquilla.tools.policy", "ToolSurfaceCapabilities") not in imports
        assert ("opensquilla.tools.policy", "resolve_runtime_tool_surface") not in imports

    for path in (VISIBILITY, RPC_PAYLOAD, REGISTRY):
        assert ("opensquilla.tools", "surface") in _imports_from(path)


def test_policy_runtime_preserves_runtime_capability_denylists() -> None:
    ctx = ToolContext(
        is_owner=True,
        interaction_mode=InteractionMode.UNATTENDED,
        allowed_tools={
            "agents_list",
            "cron",
            "gateway",
            "image_generate",
            "message",
            "session_status",
            "sessions_send",
        },
    )

    result = resolve_runtime_tool_surface(
        ctx,
        capabilities=ToolSurfaceCapabilities(
            session_manager=False,
            task_runtime=False,
            scheduler=False,
            gateway_config=False,
            channel_backing=False,
            image_generation=False,
        ),
    )

    assert {
        "agents_list",
        "cron",
        "gateway",
        "image_generate",
        "message",
        "session_status",
        "sessions_send",
    } <= result.denied_tools
    assert result.allowed_tools == set()


def test_policy_runtime_builds_capabilities_from_injected_dependencies() -> None:
    caps = tool_surface_capabilities_from_runtime(
        session_manager=object(),
        task_runtime=None,
        scheduler=object(),
        gateway_config=object(),
        channel_manager=None,
        originating_envelope=object(),
        image_generation=False,
    )

    assert caps == ToolSurfaceCapabilities(
        session_manager=True,
        task_runtime=False,
        scheduler=True,
        gateway_config=True,
        channel_backing=True,
        image_generation=False,
    )
