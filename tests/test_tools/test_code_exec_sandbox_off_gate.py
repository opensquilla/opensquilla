"""Regression test: destructive execute_code must be gated when sandbox is off.

main routed destructive-Python operations through the shell warnlist approval
gate unconditionally. The sandbox refactor only runs the sandbox gate when the
runtime has the sandbox enabled, so with a configured-but-disabled sandbox and a
non Full-Host-Access run, destructive code (os.remove / shutil.rmtree) fell
straight through to host execution with no approval. eafcd824 restored this
guard for the shell tool; this test pins the equivalent guard for execute_code.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opensquilla.application.approval_queue import get_approval_queue
from opensquilla.sandbox.config import SandboxSettings
from opensquilla.sandbox.integration import configure_runtime, reset_runtime
from opensquilla.tools.builtin import code_exec
from opensquilla.tools.types import CallerKind, ToolContext, current_tool_context


@pytest.mark.asyncio
async def test_destructive_code_exec_requires_approval_when_sandbox_disabled(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "target.txt").write_text("keep me\n", encoding="utf-8")

    # Runtime present but sandbox disabled, and the session is not in Full Host
    # Access mode -> the sandbox gate never runs.
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

    payload = json.loads(result)
    assert payload["status"] == "approval_required"
    # The destructive op must not have run while approval is pending.
    assert (workspace / "target.txt").exists()
    pending = get_approval_queue().list_pending("exec")
    assert len(pending) == 1
