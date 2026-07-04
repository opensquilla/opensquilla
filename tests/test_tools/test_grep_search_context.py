"""Regression test: filesystem search must not lose the tool context.

grep_search (and list_dir / glob_search) classify each entry with helpers that
read the current run mode from the ``current_tool_context`` contextvar
(``_sandbox_path_access_marker`` / ``_is_sensitive_access_path``). Those helpers
run inside ``loop.run_in_executor``, which does not propagate contextvars to the
worker thread. Without an explicit ``copy_context().run`` the worker sees no run
mode, so ``full_host_access_active()`` is False and every file outside the
sandbox workspace is falsely marked ``[blocked]`` even though the session is in
Full Host Access mode (where the top-level check already waved the path
through).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from opensquilla.sandbox.config import SandboxSettings
from opensquilla.sandbox.integration import configure_runtime, reset_runtime
from opensquilla.tools.builtin import filesystem
from opensquilla.tools.types import CallerKind, ToolContext, current_tool_context


@pytest.mark.asyncio
async def test_grep_search_full_host_access_does_not_false_block_outside_files(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "data.txt").write_text("needle in a haystack\n", encoding="utf-8")

    configure_runtime(
        SandboxSettings(run_mode="standard", backend="noop", allow_legacy_mode=True),
        workspace=workspace,
    )
    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            caller_kind=CallerKind.CLI,
            workspace_dir=str(workspace),
            run_mode="full",
            session_key="s1",
        )
    )
    try:
        result = await filesystem.grep_search("needle", path=str(outside))
    finally:
        current_tool_context.reset(token)
        reset_runtime()

    # Full Host Access: the outside file must be searched and matched, never
    # reported as blocked/outside the sandbox view.
    assert "needle in a haystack" in result
    assert "[blocked]" not in result
