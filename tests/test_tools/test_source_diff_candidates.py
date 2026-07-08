from __future__ import annotations

import subprocess
from pathlib import Path

from opensquilla.tools.source_diff_candidates import (
    MAX_PATCH_CHARS,
    capture_source_diff_candidate,
    latest_recoverable_source_candidate,
    mark_source_diff_candidates_lost,
)
from opensquilla.tools.types import ToolContext


def _run_git(workspace: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=workspace,
        check=True,
        capture_output=True,
    )


def _init_git_workspace(workspace: Path) -> Path:
    (workspace / "src").mkdir()
    target = workspace / "src" / "a.py"
    target.write_text("old\n", encoding="utf-8")
    _run_git(workspace, "init")
    _run_git(workspace, "config", "user.email", "test@example.com")
    _run_git(workspace, "config", "user.name", "Test User")
    _run_git(workspace, "add", ".")
    _run_git(workspace, "commit", "-m", "init")
    return target


def test_capture_source_candidate_records_patch(tmp_path: Path) -> None:
    target = _init_git_workspace(tmp_path)
    target.write_text("new\n", encoding="utf-8")
    events: list[dict[str, object]] = []

    ctx = ToolContext(workspace_dir=str(tmp_path), on_runtime_event=events.append)
    candidate = capture_source_diff_candidate(
        ctx=ctx,
        relative_path="src/a.py",
        workspace_epoch=1,
        receipt_id="receipt-1",
        tool_name="edit_source",
    )

    assert candidate is not None
    assert candidate["candidate_id"].startswith("srcdiff-")
    assert candidate["paths"] == ["src/a.py"]
    assert "-old" in candidate["patch"]
    assert "+new" in candidate["patch"]
    assert latest_recoverable_source_candidate(ctx) == candidate
    assert events[-1]["name"] == "source_diff_candidate.captured"


def test_capture_source_candidate_skips_when_mode_off(tmp_path: Path) -> None:
    target = _init_git_workspace(tmp_path)
    target.write_text("new\n", encoding="utf-8")
    events: list[dict[str, object]] = []

    ctx = ToolContext(
        workspace_dir=str(tmp_path),
        source_diff_candidate_mode="off",
        on_runtime_event=events.append,
    )
    candidate = capture_source_diff_candidate(
        ctx=ctx,
        relative_path="src/a.py",
        workspace_epoch=1,
        receipt_id="receipt-1",
        tool_name="edit_source",
    )

    assert candidate is None
    assert ctx.source_diff_candidates == []
    assert events == []


def test_capture_source_candidate_skips_non_git_workspace(tmp_path: Path) -> None:
    target = tmp_path / "src" / "a.py"
    target.parent.mkdir()
    target.write_text("new\n", encoding="utf-8")
    events: list[dict[str, object]] = []

    ctx = ToolContext(workspace_dir=str(tmp_path), on_runtime_event=events.append)
    candidate = capture_source_diff_candidate(
        ctx=ctx,
        relative_path="src/a.py",
        workspace_epoch=1,
        receipt_id="receipt-1",
        tool_name="edit_source",
    )

    assert candidate is None
    assert events[-1]["name"] == "source_diff_candidate.capture_skipped"
    assert events[-1]["reason"] == "git_diff_failed"


def test_capture_source_candidate_skips_oversized_patch(tmp_path: Path) -> None:
    target = _init_git_workspace(tmp_path)
    target.write_text("x" * (MAX_PATCH_CHARS + 1), encoding="utf-8")
    events: list[dict[str, object]] = []

    ctx = ToolContext(workspace_dir=str(tmp_path), on_runtime_event=events.append)
    candidate = capture_source_diff_candidate(
        ctx=ctx,
        relative_path="src/a.py",
        workspace_epoch=1,
        receipt_id="receipt-1",
        tool_name="edit_source",
    )

    assert candidate is None
    assert ctx.source_diff_candidates == []
    assert events[-1]["reason"] == "patch_too_large"


def test_mark_source_diff_candidates_lost_updates_matching_candidates() -> None:
    events: list[dict[str, object]] = []
    ctx = ToolContext(on_runtime_event=events.append)
    ctx.source_diff_candidates.extend(
        [
            {
                "candidate_id": "srcdiff-1",
                "paths": ["src/a.py"],
                "patch": "diff --git a/src/a.py b/src/a.py\n",
                "lost": False,
                "restored": False,
            },
            {
                "candidate_id": "srcdiff-2",
                "paths": ["src/b.py"],
                "patch": "diff --git a/src/b.py b/src/b.py\n",
                "lost": False,
                "restored": False,
            },
        ]
    )

    marked = mark_source_diff_candidates_lost(
        ctx=ctx,
        paths=["src/a.py"],
        reason="source_diff_revert_observed",
        command="git checkout -- src/a.py",
    )

    assert [item["candidate_id"] for item in marked] == ["srcdiff-1"]
    assert ctx.source_diff_candidates[0]["lost"] is True
    assert ctx.source_diff_candidates[0]["lost_reason"] == "source_diff_revert_observed"
    assert ctx.source_diff_candidates[1]["lost"] is False
    assert events[-1]["name"] == "source_diff_candidate.marked_lost"
