from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from opensquilla.engine.types import ToolCall
from opensquilla.tools.dispatch import build_tool_handler
from opensquilla.tools.registry import ToolRegistry
from opensquilla.tools.types import CallerKind, ToolContext, ToolSpec

ROOT = Path(__file__).resolve().parents[2]
DISPATCH = ROOT / "src/opensquilla/tools/dispatch.py"
VISIBILITY = ROOT / "src/opensquilla/tools/visibility.py"


async def _handler() -> str:
    return "ok"


def _spec(
    name: str,
    *,
    owner_only: bool = False,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=f"{name} tool",
        parameters={},
        owner_only=owner_only,
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


def test_tool_registry_tracks_lifecycle_owner_for_external_tools() -> None:
    registry = ToolRegistry()
    registry.register(_spec("read_file"), _handler)
    registry.register(_spec("mcp_lookup"), _handler, owner="mcp:docs")
    registry.register(_spec("mcp_search"), _handler, owner="mcp:docs")
    registry.register(_spec("mcp_other"), _handler, owner="mcp:other")

    removed = registry.unregister_owner("mcp:docs")

    assert removed == ["mcp_lookup", "mcp_search"]
    assert registry.owner_for("read_file") is None
    assert registry.owner_for("mcp_lookup") is None
    assert registry.get("mcp_lookup") is None
    assert registry.get("mcp_search") is None
    assert registry.get("read_file") is not None
    assert registry.get("mcp_other") is not None


def test_registry_lifecycle_owner_survives_overwrite_and_unregister() -> None:
    registry = ToolRegistry()
    registry.register(_spec("mcp_lookup"), _handler, owner="mcp:old")
    registry.register(_spec("mcp_lookup"), _handler, owner="mcp:new")

    assert registry.owner_for("mcp_lookup") == "mcp:new"
    assert registry.unregister("mcp_lookup") is True
    assert registry.owner_for("mcp_lookup") is None


def test_dispatch_visibility_boundary_owns_defense_in_depth_decisions() -> None:
    imports = _imports_from(DISPATCH)

    assert ("opensquilla.tools", "visibility") in imports
    assert "ToolDispatchBlock" in _top_level_classes(VISIBILITY)
    assert "tool_dispatch_block" in _top_level_functions(VISIBILITY)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "ctx", "expected_error_class", "expected_message"),
    [
        (
            "owner_tool",
            ToolContext(is_owner=False, caller_kind=CallerKind.AGENT),
            "OwnerOnly",
            "Tool 'owner_tool' restricted to owner.",
        ),
        (
            "denied_tool",
            ToolContext(
                is_owner=True,
                caller_kind=CallerKind.CLI,
                denied_tools={"denied_tool"},
            ),
            "PolicyDenied",
            "Tool 'denied_tool' not available in this context.",
        ),
        (
            "unsurfaced_tool",
            ToolContext(
                is_owner=True,
                caller_kind=CallerKind.CLI,
                allowed_tools={"other_tool"},
            ),
            "PolicyDenied",
            "Tool 'unsurfaced_tool' not available in this context.",
        ),
    ],
)
async def test_dispatch_boundary_preserves_visibility_failure_envelopes(
    tool_name: str,
    ctx: ToolContext,
    expected_error_class: str,
    expected_message: str,
) -> None:
    registry = ToolRegistry()
    registry.register(_spec("owner_tool", owner_only=True), _handler)
    registry.register(_spec("denied_tool"), _handler)
    registry.register(_spec("unsurfaced_tool"), _handler)

    handler = build_tool_handler(registry, ctx)
    result = await handler(
        ToolCall(
            tool_use_id=f"tc-{tool_name}",
            tool_name=tool_name,
            arguments={},
        )
    )

    assert result.is_error is True
    payload = json.loads(result.content)
    assert payload["error_class"] == expected_error_class
    assert payload["user_message"] == expected_message
