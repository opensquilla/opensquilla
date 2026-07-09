"""Endgame git freeze lever: shell-side blocking of workspace-reverting git.

Covers the tools half of OPENSQUILLA_ENDGAME_GIT_FREEZE_MARGIN_SECONDS: the
engine arms ToolContext.endgame_git_freeze_active near the turn deadline, and
the shell tools then block destructive git commands — restore, path/branch
checkouts, hard resets, force-clean, stash push/drop/clear — outright, with
no protected-path intersection, so the current workspace diff survives
runner-side collection. Unarmed contexts (the default) are untouched.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from opensquilla.gateway.approval_queue import reset_approval_queue
from opensquilla.sandbox.integration import reset_runtime
from opensquilla.tools.builtin import shell
from opensquilla.tools.source_diff_preservation import (
    endgame_git_freeze_block_json,
    endgame_git_freeze_decision,
)
from opensquilla.tools.types import (
    CallerKind,
    InteractionMode,
    ToolContext,
    current_tool_context,
)


@pytest.fixture(autouse=True)
def _tool_context():
    reset_approval_queue()
    reset_runtime()
    token = current_tool_context.set(
        ToolContext(is_owner=True, caller_kind=CallerKind.CLI, session_key="agent:main:test")
    )
    yield
    current_tool_context.reset(token)
    reset_approval_queue()
    reset_runtime()


def _configure_ctx(workspace: Path | None = None, *, frozen: bool = False) -> ToolContext:
    ctx = current_tool_context.get()
    assert ctx is not None
    ctx.interaction_mode = InteractionMode.UNATTENDED
    ctx.elevated = "bypass"
    if workspace is not None:
        ctx.workspace_dir = str(workspace)
    ctx.endgame_git_freeze_active = frozen
    return ctx


def _init_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "workspace"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "agent@test.invalid"],
        check=True,
    )
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "agent"], check=True)
    target = repo / "pkg.py"
    target.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True)
    return repo, target


def test_decision_none_when_flag_unset() -> None:
    # The default: nothing armed the context, so even a hard reset is left to
    # the ordinary guards.
    _configure_ctx(frozen=False)

    assert endgame_git_freeze_decision(command="git reset --hard") is None


@pytest.mark.parametrize(
    ("command", "operation"),
    [
        ("git reset --hard", "git_reset_hard"),
        ("git reset --hard HEAD~1", "git_reset_hard"),
        ("git checkout -- pkg.py", "git_checkout"),
        ("git checkout main", "git_checkout"),
        ("git checkout -f", "git_checkout_force"),
        ("git restore pkg.py", "git_restore"),
        ("git restore --staged pkg.py", "git_restore"),
        ("git clean -fd", "git_clean"),
        ("git stash", "git_stash"),
        ("git stash -u", "git_stash"),
        ("git stash push -m wip", "git_stash"),
        ("git stash save wip", "git_stash"),
        ("git stash drop", "git_stash"),
        ("git stash clear", "git_stash"),
        ("echo done && git reset --hard", "git_reset_hard"),
    ],
)
def test_decision_blocks_destructive_git_when_frozen(command: str, operation: str) -> None:
    _configure_ctx(frozen=True)

    payload = endgame_git_freeze_decision(command=command)

    assert payload is not None
    assert payload["status"] == "blocked"
    assert payload["reason"] == "endgame_git_freeze"
    assert payload["matched_operation"] == operation
    assert payload["retry_allowed"] is True


@pytest.mark.parametrize(
    "command",
    [
        "git status",
        "git diff",
        "git add -A",
        "git commit -m done",
        "git log --oneline",
        "git stash pop",
        "git stash apply",
        "git stash list",
        "git stash show -p",
        "git checkout -b feature",
        "ls -la",
        "sed -i 's/a/b/' pkg.py",
    ],
)
def test_decision_allows_non_destructive_commands_when_frozen(command: str) -> None:
    # The freeze only blocks workspace-reverting operations; committing,
    # inspecting, applying stashed work, editing files, and creating branches
    # all remain available in the wrap-up window.
    _configure_ctx(frozen=True)

    assert endgame_git_freeze_decision(command=command) is None


def test_decision_emits_runtime_event() -> None:
    ctx = _configure_ctx(frozen=True)
    events: list[dict] = []
    ctx.on_runtime_event = events.append

    payload = endgame_git_freeze_decision(command="git reset --hard")

    assert payload is not None
    assert len(events) == 1
    assert events[0]["feature"] == "endgame_git_freeze"
    assert events[0]["name"] == "endgame_git_freeze.blocked"
    assert events[0]["matched_operation"] == "git_reset_hard"
    assert events[0]["command"] == "git reset --hard"


def test_block_json_round_trips_payload() -> None:
    _configure_ctx(frozen=True)

    raw = endgame_git_freeze_block_json(command="git checkout -- pkg.py")

    assert raw is not None
    payload = json.loads(raw)
    assert payload["status"] == "blocked"
    assert payload["reason"] == "endgame_git_freeze"
    assert payload["target_paths"] == ["pkg.py"]
    assert endgame_git_freeze_block_json(command="git status") is None


@pytest.mark.asyncio
async def test_exec_command_blocks_checkout_when_frozen(tmp_path: Path) -> None:
    repo, target = _init_repo(tmp_path)
    target.write_text("value = 2\n", encoding="utf-8")
    _configure_ctx(repo, frozen=True)

    result = await shell.exec_command("git checkout -- pkg.py", workdir=str(repo))

    payload = json.loads(result)
    assert payload["status"] == "blocked"
    assert payload["reason"] == "endgame_git_freeze"
    assert target.read_text(encoding="utf-8") == "value = 2\n"


@pytest.mark.asyncio
async def test_exec_command_default_lets_checkout_revert(tmp_path: Path) -> None:
    # Documents the default gap the lever closes: with the freeze unarmed the
    # revert executes and the pending diff is gone.
    repo, target = _init_repo(tmp_path)
    target.write_text("value = 2\n", encoding="utf-8")
    _configure_ctx(repo, frozen=False)

    result = await shell.exec_command("git checkout -- pkg.py", workdir=str(repo))

    assert result.startswith("exit_code=0")
    assert target.read_text(encoding="utf-8") == "value = 1\n"


@pytest.mark.asyncio
async def test_exec_command_scans_stdin_when_frozen(tmp_path: Path) -> None:
    repo, target = _init_repo(tmp_path)
    target.write_text("value = 2\n", encoding="utf-8")
    _configure_ctx(repo, frozen=True)

    result = await shell.exec_command(
        "sh", workdir=str(repo), stdin="git reset --hard\n"
    )

    payload = json.loads(result)
    assert payload["status"] == "blocked"
    assert payload["reason"] == "endgame_git_freeze"
    assert target.read_text(encoding="utf-8") == "value = 2\n"


@pytest.mark.asyncio
async def test_background_process_blocks_destructive_git_when_frozen(
    tmp_path: Path,
) -> None:
    repo, target = _init_repo(tmp_path)
    target.write_text("value = 2\n", encoding="utf-8")
    _configure_ctx(repo, frozen=True)

    result = await shell.background_process("git reset --hard", workdir=str(repo))

    payload = json.loads(result)
    assert payload["status"] == "blocked"
    assert payload["reason"] == "endgame_git_freeze"
    assert target.read_text(encoding="utf-8") == "value = 2\n"
