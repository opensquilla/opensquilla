from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from opensquilla.tools.builtin import shell
from opensquilla.tools.types import ToolContext, ToolError, current_tool_context


@pytest.mark.asyncio
async def test_exec_command_blocks_sensitive_workdir(tmp_path: Path) -> None:
    sensitive_dir = tmp_path / ".env"

    result = await shell.exec_command("echo ok", workdir=str(sensitive_dir))

    payload = json.loads(result)
    assert payload["status"] == "blocked"
    assert payload["reason"] == "sensitive_path"
    assert payload["tool"] == "exec_command"
    assert ".env" in payload["command"]


@pytest.mark.asyncio
async def test_exec_command_blocks_nested_sensitive_workdir() -> None:
    sensitive_dir = Path.home() / ".ssh" / "id_rsa"

    result = await shell.exec_command("echo ok", workdir=str(sensitive_dir))

    payload = json.loads(result)
    assert payload["status"] == "blocked"
    assert payload["sensitive_path"] == "~/.ssh"


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="/dev/null redirection is POSIX-specific")
async def test_exec_command_allows_dev_null_redirection() -> None:
    result = await shell.exec_command("printf ok 2>/dev/null")

    assert result == "exit_code=0\nok"


def test_dev_null_redirection_does_not_hide_sensitive_operand() -> None:
    payload = shell._sensitive_shell_block(
        "exec_command",
        "cat /dev/sda 2>/dev/null",
    )

    assert payload is not None
    assert json.loads(payload)["sensitive_path"] == "/dev"


@pytest.mark.asyncio
async def test_background_process_blocks_sensitive_workdir(tmp_path: Path) -> None:
    sensitive_dir = tmp_path / ".env"

    result = await shell.background_process("echo ok", workdir=str(sensitive_dir))

    payload = json.loads(result)
    assert payload["status"] == "blocked"
    assert payload["reason"] == "sensitive_path"
    assert payload["tool"] == "background_process"
    assert ".env" in payload["command"]


def test_effective_workdir_resolves_relative_paths_against_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    token = current_tool_context.set(ToolContext(workspace_dir=str(workspace)))
    try:
        assert shell._effective_workdir("subdir") == str((workspace / "subdir").resolve())
    finally:
        current_tool_context.reset(token)


def test_effective_workdir_rejects_foreign_posix_absolute_path_on_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(shell.os, "name", "nt")
    token = current_tool_context.set(ToolContext(workspace_dir=str(workspace)))
    try:
        with pytest.raises(ToolError, match="foreign_host_path"):
            shell._effective_workdir("/Users/a1/Desktop")
    finally:
        current_tool_context.reset(token)
