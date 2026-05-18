from __future__ import annotations

import ast
from pathlib import Path

import pytest

from opensquilla.provider.types import ToolDefinition, ToolInputSchema
from opensquilla.tools.policy import ToolSurfaceCapabilities
from opensquilla.tools.registry import ToolRegistry
from opensquilla.tools.types import (
    CallerKind,
    InteractionMode,
    RegisteredTool,
    ToolContext,
    ToolSpec,
)
from opensquilla.tools.visibility import (
    ToolProfile,
    effective_tool_context,
    filter_by_profile,
    resolve_profile,
    visible_registered_tools,
)

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "src/opensquilla/tools/registry.py"
SURFACE = ROOT / "src/opensquilla/tools/surface.py"
VISIBILITY = ROOT / "src/opensquilla/tools/visibility.py"


async def _handler() -> str:
    return "ok"


def _registered_tool(
    name: str,
    *,
    exposed_by_default: bool = True,
    owner_only: bool = False,
) -> RegisteredTool:
    return RegisteredTool(
        spec=ToolSpec(
            name=name,
            description=f"{name} tool",
            parameters={},
            exposed_by_default=exposed_by_default,
            owner_only=owner_only,
        ),
        handler=_handler,
    )


def _tool_definition(name: str) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"{name} tool",
        input_schema=ToolInputSchema(type="object", properties={}, required=[]),
    )


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


def _class_methods(path: Path, class_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                child.name
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
    return set()


def test_tools_surface_boundary_owns_runtime_request_and_row_helpers() -> None:
    imports = _imports_from(REGISTRY)

    assert ("opensquilla.tools", "surface") in imports
    assert "ToolSurfaceRequest" in _top_level_classes(SURFACE)
    assert {
        "default_tool_context",
        "tool_context_for_profile",
        "effective_tool_context",
        "tool_context_for_surface_request",
        "catalog_tool_row",
        "effective_tool_row",
    } <= _top_level_functions(SURFACE)
    assert "effective_tool_context" not in _top_level_functions(VISIBILITY)
    assert "effective_tool_context" in _top_level_assignments(VISIBILITY)
    assert "_schema_for" not in _class_methods(REGISTRY, "ToolRegistry")


def test_registry_delegates_visibility_policy_to_tools_visibility_boundary() -> None:
    imports = _imports_from(REGISTRY)

    assert ("opensquilla.tools", "visibility") in imports

    registry_classes = _top_level_classes(REGISTRY)
    registry_functions = _top_level_functions(REGISTRY)
    registry_assignments = _top_level_assignments(REGISTRY)
    assert "ToolProfile" not in registry_classes
    assert "filter_by_profile" not in registry_functions
    assert "resolve_profile" not in registry_functions
    assert {"ToolProfile", "filter_by_profile", "resolve_profile"} <= registry_assignments
    assert "_CHANNEL_DEFAULT_ALLOW" not in registry_assignments

    visibility_classes = _top_level_classes(VISIBILITY)
    visibility_functions = _top_level_functions(VISIBILITY)
    visibility_assignments = _top_level_assignments(VISIBILITY)
    assert "ToolProfile" in visibility_classes
    assert "filter_by_profile" in visibility_functions
    assert "resolve_profile" in visibility_functions
    assert "effective_tool_context" in visibility_assignments
    assert "visible_registered_tools" in visibility_functions
    assert "_CHANNEL_DEFAULT_ALLOW" in visibility_assignments


def test_visibility_boundary_preserves_channel_profile_filtering() -> None:
    channel_ctx = ToolContext(is_owner=False, caller_kind=CallerKind.CHANNEL)
    profile = resolve_profile(channel_ctx)

    filtered = filter_by_profile(
        [
            _tool_definition("publish_artifact"),
            _tool_definition("git_commit"),
            _tool_definition("read_file"),
        ],
        profile,
    )

    assert profile is ToolProfile.CHANNEL_DEFAULT
    assert [tool.name for tool in filtered] == ["publish_artifact", "read_file"]


def test_visibility_boundary_preserves_context_visibility_rules() -> None:
    tools = [
        _registered_tool("visible"),
        _registered_tool("owner_only", owner_only=True),
        _registered_tool("hidden", exposed_by_default=False),
    ]
    ctx = ToolContext(
        is_owner=False,
        caller_kind=CallerKind.CHANNEL,
        allowed_tools={"visible", "hidden", "owner_only"},
        surfaced_tools={"hidden"},
    )

    visible = visible_registered_tools(tools, ctx, sort=True)

    assert [tool.spec.name for tool in visible] == ["hidden", "visible"]


def test_visibility_boundary_preserves_effective_runtime_contexts() -> None:
    subagent_ctx = effective_tool_context(
        session_key="subagent:worker",
        caller_kind=None,
        interaction_mode=None,
        tool_surface_capabilities=ToolSurfaceCapabilities(session_manager=True),
        is_owner=True,
    )
    cron_ctx = effective_tool_context(
        session_key="cron:nightly",
        caller_kind=None,
        interaction_mode=None,
        tool_surface_capabilities=ToolSurfaceCapabilities(scheduler=True),
        is_owner=True,
    )

    assert subagent_ctx.caller_kind is CallerKind.SUBAGENT
    assert subagent_ctx.interaction_mode is InteractionMode.UNATTENDED
    assert "publish_artifact" in subagent_ctx.denied_tools
    assert cron_ctx.caller_kind is CallerKind.CRON
    assert cron_ctx.is_owner is False


def test_tool_surface_request_runtime_params_override_profile() -> None:
    from opensquilla.tools.surface import (
        ToolSurfaceRequest,
        tool_context_for_surface_request,
    )

    ctx = tool_context_for_surface_request(
        ToolSurfaceRequest(
            profile="cron",
            session_key="agent:main:auto",
            agent_id="main",
            caller_kind=CallerKind.AGENT,
            interaction_mode=InteractionMode.UNATTENDED,
            tool_surface_capabilities=ToolSurfaceCapabilities(session_manager=True),
            is_owner=True,
        )
    )

    assert ctx.caller_kind is CallerKind.AGENT
    assert ctx.interaction_mode is InteractionMode.UNATTENDED
    assert ctx.is_owner is True
    assert ctx.allowed_tools is None


@pytest.mark.asyncio
async def test_registry_catalog_and_effective_share_surface_context_but_keep_row_shapes() -> None:
    registry = ToolRegistry()
    registry.register(_registered_tool("write_file").spec, _handler)
    registry.register(_registered_tool("sessions_send").spec, _handler)
    caps = ToolSurfaceCapabilities(session_manager=True, task_runtime=False)

    catalog = await registry.list_tools(
        profile="cron",
        session_key="agent:main:auto",
        caller_kind=CallerKind.AGENT,
        interaction_mode=InteractionMode.UNATTENDED,
        tool_surface_capabilities=caps,
        is_owner=True,
    )
    effective = await registry.effective_tools(
        session_key="agent:main:auto",
        caller_kind=CallerKind.AGENT,
        interaction_mode=InteractionMode.UNATTENDED,
        tool_surface_capabilities=caps,
        is_owner=True,
    )

    assert {tool["name"] for tool in catalog} == {"write_file"}
    assert {tool["name"] for tool in effective} == {"write_file"}
    assert {"source", "enabled"} <= set(catalog[0])
    assert "source" not in effective[0]
    assert "enabled" not in effective[0]
