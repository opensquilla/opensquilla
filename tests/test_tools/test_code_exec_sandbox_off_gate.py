"""Regression test: configured sandbox-off execution is Full Host Access."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opensquilla.application.approval_queue import get_approval_queue, reset_approval_queue
from opensquilla.sandbox.config import SandboxSettings
from opensquilla.sandbox.integration import configure_runtime, reset_runtime
from opensquilla.tools.builtin import code_exec
from opensquilla.tools.types import CallerKind, ToolContext, current_tool_context


@pytest.mark.asyncio
async def test_destructive_code_exec_runs_without_approval_when_sandbox_disabled(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "target.txt").write_text("keep me\n", encoding="utf-8")

    configure_runtime(
        SandboxSettings(sandbox=False, security_grading=False),
        workspace=workspace,
    )
    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir=str(workspace),
            run_mode="standard",
            session_key="s1",
        )
    )
    try:
        result = await code_exec.execute_code("import os\nos.remove('target.txt')")
    finally:
        current_tool_context.reset(token)
        reset_runtime()

    try:
        payload = json.loads(result)
        assert payload["exit_code"] == 0
        assert not (workspace / "target.txt").exists()
        assert get_approval_queue().list_pending("exec") == []
    finally:
        reset_approval_queue()
