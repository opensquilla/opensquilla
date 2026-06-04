from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from opensquilla.sandbox.integration import reset_runtime
from opensquilla.tools.builtin import git
from opensquilla.tools.types import ToolContext, current_tool_context


class _FakeProcess:
    returncode = 0

    async def communicate(self) -> tuple[bytes, None]:
        return b"## main\n", None


@pytest.mark.asyncio
async def test_git_status_run_mode_full_uses_host_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_runtime()
    calls: list[dict[str, Any]] = []

    async def fake_create_subprocess_exec(*args: str, **kwargs: Any) -> _FakeProcess:
        calls.append({"args": args, "kwargs": kwargs})
        return _FakeProcess()

    monkeypatch.setattr(git.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    token = current_tool_context.set(
        ToolContext(
            is_owner=True,
            workspace_dir=str(tmp_path),
            run_mode="full",
            session_key="agent:main:test",
        )
    )
    try:
        result = await git.git_status()
    finally:
        current_tool_context.reset(token)
        reset_runtime()

    assert result == "## main\n"
    assert calls == [
        {
            "args": ("git", "status", "--short", "--branch"),
            "kwargs": {
                "stdout": git.asyncio.subprocess.PIPE,
                "stderr": git.asyncio.subprocess.STDOUT,
                "cwd": str(tmp_path),
            },
        }
    ]
