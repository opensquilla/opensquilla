from __future__ import annotations

from opensquilla.engine.runtime import TurnRunner
from opensquilla.tools.types import CallerKind, ToolContext


def test_full_host_access_tool_context_is_visible_to_model_prompt() -> None:
    ctx = ToolContext(
        caller_kind=CallerKind.WEB,
        run_mode="full",
        workspace_dir="/workspace/.opensquilla/workspace",
    )

    extra = TurnRunner._extra_context_for_tool_context(ctx)

    execution_context = extra["Execution Context"]
    assert "Run mode: Full Host Access" in execution_context
    assert "Execution target: host" in execution_context
    assert "Sandbox: disabled for tool execution" in execution_context
