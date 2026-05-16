"""Architecture guards for session tools decoupling."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

from opensquilla.gateway.routing import tool_context_from_envelope
from opensquilla.session.subagent_routing import build_subagent_route_envelope
from opensquilla.tools.builtin import sessions as sessions_tool
from opensquilla.tools.types import CallerKind, ToolContext, current_tool_context

SESSIONS_TOOL = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "opensquilla"
    / "tools"
    / "builtin"
    / "sessions.py"
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


def test_sessions_tool_does_not_import_gateway() -> None:
    offenders = sorted(
        module
        for module in _imported_modules(SESSIONS_TOOL)
        if module == "opensquilla.gateway" or module.startswith("opensquilla.gateway.")
    )

    assert offenders == []


def test_sessions_tool_source_does_not_reference_gateway_package() -> None:
    assert "opensquilla.gateway" not in SESSIONS_TOOL.read_text(encoding="utf-8")


def test_session_subagent_envelope_maps_to_subagent_tool_context() -> None:
    envelope = build_subagent_route_envelope(
        session_key="agent:worker:child",
        parent_session_key="agent:main:parent",
        agent_id="worker",
        parent_task_id="task-parent",
        spawn_depth=1,
    )

    ctx = tool_context_from_envelope(envelope)

    assert ctx.caller_kind is CallerKind.SUBAGENT
    assert ctx.session_key == "agent:worker:child"
    assert ctx.agent_id == "worker"
    assert ctx.subagent_depth == 1


@pytest.mark.asyncio
async def test_sessions_yield_uses_injected_spawn_group_closer() -> None:
    calls: list[dict[str, Any]] = []
    mgr = object()
    runtime = object()

    async def fake_close(
        parent_session_key: str,
        parent_task_id: str,
        *,
        session_manager: object,
        task_runtime: object,
    ) -> bool:
        calls.append(
            {
                "parent_session_key": parent_session_key,
                "parent_task_id": parent_task_id,
                "session_manager": session_manager,
                "task_runtime": task_runtime,
            }
        )
        return True

    sessions_tool.set_session_manager(mgr)
    sessions_tool.set_task_runtime(runtime)
    sessions_tool.set_spawn_group_closer(fake_close)
    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.AGENT,
            session_key="agent:main:parent",
            task_id="task-parent",
        )
    )
    try:
        payload = json.loads(await sessions_tool.sessions_yield(timeout_seconds=0))
    finally:
        current_tool_context.reset(token)
        sessions_tool.set_session_manager(None)
        sessions_tool.set_task_runtime(None)
        sessions_tool.set_spawn_group_closer(None)

    assert payload["status"] == "yielded"
    assert calls == [
        {
            "parent_session_key": "agent:main:parent",
            "parent_task_id": "task-parent",
            "session_manager": mgr,
            "task_runtime": runtime,
        }
    ]
