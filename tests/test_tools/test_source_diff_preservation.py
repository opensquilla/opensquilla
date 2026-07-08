from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from opensquilla.tools.builtin.shell import exec_command
from opensquilla.tools.mutation_receipts import (
    fingerprint_file,
    record_semantic_mutation_receipt,
)
from opensquilla.tools.source_diff_preservation import (
    source_diff_preservation_decision,
)
from opensquilla.tools.types import ToolContext, current_tool_context


def _init_git_workspace(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, stdout=subprocess.DEVNULL)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)


def _commit_file(workspace: Path, relative_path: str, text: str) -> Path:
    target = workspace / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", relative_path], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=workspace, check=True)
    return target


def _record_changed_source_receipt(ctx: ToolContext, target: Path) -> None:
    before = fingerprint_file(target)
    target.write_text("print('after')\n", encoding="utf-8")
    after = fingerprint_file(target)
    record_semantic_mutation_receipt(
        tool_name="edit_source",
        path=target,
        operation="edit_source",
        before=before,
        after=after,
        partial=False,
        ctx=ctx,
    )


@pytest.fixture
def protected_workspace(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _init_git_workspace(workspace)
    target = _commit_file(workspace, "src/app.py", "print('before')\n")
    events: list[dict] = []
    ctx = ToolContext(
        workspace_dir=str(workspace),
        source_diff_preservation_mode="block",
        on_runtime_event=events.append,
        session_key="agent:main:test",
    )
    token = current_tool_context.set(ctx)
    try:
        _record_changed_source_receipt(ctx, target)
        yield workspace, target, ctx, events
    finally:
        current_tool_context.reset(token)


def test_decision_blocks_git_restore_for_protected_source_path(protected_workspace) -> None:
    workspace, _target, ctx, _events = protected_workspace

    decision = source_diff_preservation_decision(
        command="git restore src/app.py",
        workdir=workspace,
        ctx=ctx,
    )

    assert decision is not None
    assert decision.should_block is True
    assert decision.payload["reason"] == "source_diff_revert_blocked"
    assert decision.payload["matched_operation"] == "git_restore"
    assert decision.payload["protected_source_paths"] == ["src/app.py"]


def test_decision_blocks_worktree_wide_destructive_commands(protected_workspace) -> None:
    workspace, _target, ctx, _events = protected_workspace

    for command, operation in (
        ("git checkout -- .", "git_checkout"),
        ("git checkout --ours src/app.py", "git_checkout"),
        ("cd /tmp && git checkout src/app.py && echo restored", "git_checkout"),
        (
            'cd /tmp && git checkout -- src/app.py 2>&1 || echo "restore failed"',
            "git_checkout",
        ),
        (
            'cd /tmp && git checkout src/app.py 2>&1 || echo "restore failed"',
            "git_checkout",
        ),
        ("git reset --hard", "git_reset_hard"),
    ):
        decision = source_diff_preservation_decision(
            command=command,
            workdir=workspace,
            ctx=ctx,
        )
        assert decision is not None
        assert decision.should_block is True
        assert decision.payload["matched_operation"] == operation


def test_decision_allows_unrelated_path_restore(protected_workspace) -> None:
    workspace, _target, ctx, _events = protected_workspace

    decision = source_diff_preservation_decision(
        command="git restore docs/readme.md",
        workdir=workspace,
        ctx=ctx,
    )

    assert decision is None


def test_decision_allows_read_only_git_commands(protected_workspace) -> None:
    workspace, _target, ctx, _events = protected_workspace

    assert (
        source_diff_preservation_decision(
            command="git diff -- src/app.py",
            workdir=workspace,
            ctx=ctx,
        )
        is None
    )
    assert (
        source_diff_preservation_decision(
            command="git status --short",
            workdir=workspace,
            ctx=ctx,
        )
        is None
    )


def test_log_mode_marks_matching_source_candidate_lost(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _init_git_workspace(workspace)
    target = _commit_file(workspace, "src/app.py", "print('before')\n")
    events: list[dict] = []
    ctx = ToolContext(
        workspace_dir=str(workspace),
        source_diff_preservation_mode="log",
        on_runtime_event=events.append,
    )
    _record_changed_source_receipt(ctx, target)

    assert len(ctx.source_diff_candidates) == 1
    decision = source_diff_preservation_decision(
        command="git checkout -- src/app.py",
        workdir=workspace,
        ctx=ctx,
    )

    assert decision is not None
    assert decision.should_block is False
    assert ctx.source_diff_candidates[0]["lost"] is True
    assert ctx.source_diff_candidates[0]["lost_command"] == "git checkout -- src/app.py"
    assert any(
        event.get("name") == "source_diff_candidate.marked_lost"
        for event in events
    )


def test_unrelated_restore_does_not_mark_source_candidate_lost(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _init_git_workspace(workspace)
    target = _commit_file(workspace, "src/app.py", "print('before')\n")
    ctx = ToolContext(
        workspace_dir=str(workspace),
        source_diff_preservation_mode="log",
    )
    _record_changed_source_receipt(ctx, target)

    decision = source_diff_preservation_decision(
        command="git checkout -- docs/readme.md",
        workdir=workspace,
        ctx=ctx,
    )

    assert decision is None
    assert ctx.source_diff_candidates[0]["lost"] is False


def test_decision_blocks_git_clean_for_protected_untracked_source(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _init_git_workspace(workspace)
    target = workspace / "src" / "new_feature.py"
    target.parent.mkdir(parents=True)
    before = {"exists": False, "size": 0, "sha256": None}
    target.write_text("print('new')\n", encoding="utf-8")
    after = fingerprint_file(target)
    ctx = ToolContext(workspace_dir=str(workspace), source_diff_preservation_mode="block")
    record_semantic_mutation_receipt(
        tool_name="edit_source",
        path=target,
        operation="edit_source",
        before=before,
        after=after,
        partial=False,
        ctx=ctx,
    )

    decision = source_diff_preservation_decision(
        command="git clean -fd",
        workdir=workspace,
        ctx=ctx,
    )

    assert decision is not None
    assert decision.should_block is True
    assert decision.payload["matched_operation"] == "git_clean"
    assert decision.payload["protected_source_paths"] == ["src/new_feature.py"]


@pytest.mark.asyncio
async def test_exec_command_blocks_source_diff_revert_and_preserves_file(
    protected_workspace,
) -> None:
    workspace, target, _ctx, events = protected_workspace

    result = await exec_command("git restore src/app.py", workdir=str(workspace))

    payload = json.loads(result)
    assert payload["status"] == "blocked"
    assert payload["reason"] == "source_diff_revert_blocked"
    assert target.read_text(encoding="utf-8") == "print('after')\n"
    assert any(
        event.get("name") == "source_diff_revert_blocked"
        for event in events
    )


@pytest.mark.asyncio
async def test_exec_command_log_mode_allows_revert_and_records_event(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _init_git_workspace(workspace)
    target = _commit_file(workspace, "src/app.py", "print('before')\n")
    events: list[dict] = []
    ctx = ToolContext(
        workspace_dir=str(workspace),
        source_diff_preservation_mode="log",
        on_runtime_event=events.append,
        session_key="agent:main:test",
    )
    token = current_tool_context.set(ctx)
    try:
        _record_changed_source_receipt(ctx, target)
        result = await exec_command("git restore src/app.py", workdir=str(workspace))
    finally:
        current_tool_context.reset(token)

    assert result.startswith("exit_code=0")
    assert target.read_text(encoding="utf-8") == "print('before')\n"
    assert any(
        event.get("name") == "source_diff_revert_observed"
        for event in events
    )
    assert ctx.source_diff_candidates[0]["lost"] is True
