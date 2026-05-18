from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from opensquilla.engine.types import ToolCall
from opensquilla.tools.dispatch import build_tool_handler
from opensquilla.tools.registry import ToolRegistry
from opensquilla.tools.types import (
    CallerKind,
    InteractionMode,
    ToolContext,
    ToolSpec,
    current_tool_context,
)

ROOT = Path(__file__).resolve().parents[2]
DISPATCH = ROOT / "src/opensquilla/tools/dispatch.py"
ENVELOPE = ROOT / "src/opensquilla/tools/envelope.py"


def _top_level_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _imports_from(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imports.add((node.module, alias.name))
    return imports


def test_dispatch_envelope_boundary_uses_shared_envelope_result_builder() -> None:
    dispatch_functions = _top_level_functions(DISPATCH)
    dispatch_imports = _imports_from(DISPATCH)
    envelope_functions = _top_level_functions(ENVELOPE)

    assert "_build_envelope_result" not in dispatch_functions
    assert ("opensquilla.tools.envelope", "build_tool_failure_result") in dispatch_imports
    assert "build_tool_failure_result" in envelope_functions


def _build_registry() -> ToolRegistry:
    registry = ToolRegistry()

    async def boom() -> str:
        raise ValueError("bad argument")

    async def pending() -> str:
        return json.dumps(
            {
                "status": "approval_required",
                "approval_id": "abc123",
                "command": "rm secret",
                "warning": "destructive",
                "message": "Resolve this approval via exec.approval.resolve",
            }
        )

    registry.register(ToolSpec(name="boom", description="boom", parameters={}), boom)
    registry.register(ToolSpec(name="pending", description="pending", parameters={}), pending)
    return registry


@pytest.mark.asyncio
async def test_dispatch_missing_tool_returns_five_field_error_envelope() -> None:
    handler = build_tool_handler(_build_registry())

    result = await handler(
        ToolCall(
            tool_use_id="tc-1",
            tool_name="nope",
            arguments={},
        )
    )

    assert result.is_error is True
    payload = json.loads(result.content)
    assert set(payload.keys()) == {
        "status",
        "tool",
        "error_class",
        "user_message",
        "retry_allowed",
    }
    assert payload["status"] == "error"
    assert payload["tool"] == "nope"
    assert payload["error_class"] == "ToolNotFound"


@pytest.mark.asyncio
async def test_dispatch_tool_exception_envelope_is_canonical_five_key_shape() -> None:
    handler = build_tool_handler(_build_registry())

    result = await handler(
        ToolCall(
            tool_use_id="tc-2",
            tool_name="boom",
            arguments={},
        )
    )

    assert result.is_error is True
    payload = json.loads(result.content)
    assert payload["tool"] == "boom"
    assert payload["error_class"] == "ValueError"
    assert set(payload.keys()) == {
        "status",
        "tool",
        "error_class",
        "user_message",
        "retry_allowed",
    }


@pytest.mark.asyncio
async def test_dispatch_unsupported_surface_approval_payload_is_error_envelope() -> None:
    handler = build_tool_handler(_build_registry())
    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CHANNEL,
            interaction_mode=InteractionMode.UNATTENDED,
            session_key="agent:main:demo",
            agent_id="main",
        )
    )
    try:
        result = await handler(
            ToolCall(
                tool_use_id="tc-3",
                tool_name="pending",
                arguments={},
            )
        )
    finally:
        current_tool_context.reset(token)

    assert result.is_error is True
    payload = json.loads(result.content)
    assert payload["status"] == "error"
    assert payload["tool"] == "pending"
    assert payload["error_class"] == "UnsupportedSurface"
    assert payload["retry_allowed"] is False


@pytest.mark.asyncio
async def test_dispatch_unattended_cli_approval_payload_is_error_envelope() -> None:
    handler = build_tool_handler(_build_registry())
    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            interaction_mode=InteractionMode.UNATTENDED,
            session_key="agent:main:demo",
            agent_id="main",
        )
    )
    try:
        result = await handler(
            ToolCall(
                tool_use_id="tc-4",
                tool_name="pending",
                arguments={},
            )
        )
    finally:
        current_tool_context.reset(token)

    assert result.is_error is True
    payload = json.loads(result.content)
    assert set(payload.keys()) == {
        "status",
        "tool",
        "error_class",
        "user_message",
        "retry_allowed",
    }
    assert payload["status"] == "error"
    assert payload["tool"] == "pending"
    assert payload["error_class"] == "UnsupportedSurface"
    assert payload["retry_allowed"] is False


@pytest.mark.asyncio
async def test_dispatch_unknown_tool_in_skill_name_context_raises_unsupported_surface() -> None:
    known_skill_names = {"shell"}
    handler = build_tool_handler(_build_registry(), known_skill_names=known_skill_names)

    result = await handler(
        ToolCall(
            tool_use_id="tc-4",
            tool_name="shell",
            arguments={},
        )
    )

    payload = json.loads(result.content)
    assert result.is_error is True
    assert payload["error_class"] == "UnsupportedSurface"
    assert payload["tool"] == "shell"
    assert "skill" in payload["user_message"].lower()


@pytest.mark.asyncio
async def test_dispatch_attaches_published_artifacts_to_tool_result() -> None:
    registry = ToolRegistry()
    artifact = {
        "id": "art-dispatch",
        "kind": "artifact_ref",
        "name": "report.txt",
        "mime": "text/plain",
        "size": 4,
        "sha256": "1" * 64,
        "session_id": "session-1",
        "session_key": "agent:main:demo",
        "source": "publish_artifact",
        "created_at": "2026-05-06T12:00:00Z",
        "download_url": "/api/v1/artifacts/art-dispatch",
    }

    async def publish() -> str:
        ctx = current_tool_context.get()
        assert ctx is not None
        ctx.published_artifacts.append(artifact)
        return "published"

    registry.register(ToolSpec(name="publish", description="publish", parameters={}), publish)
    handler = build_tool_handler(registry)
    ctx = ToolContext(session_key="agent:main:demo")
    token = current_tool_context.set(ctx)
    try:
        result = await handler(
            ToolCall(
                tool_use_id="tc-5",
                tool_name="publish",
                arguments={},
            )
        )
    finally:
        current_tool_context.reset(token)

    assert result.content == "published"
    assert result.artifacts == [artifact]
