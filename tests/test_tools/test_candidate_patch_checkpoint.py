from __future__ import annotations

import subprocess
from pathlib import Path

from opensquilla.tools.candidate_patch_checkpoint import (
    create_candidate_patch_checkpoint,
    restore_candidate_patch_checkpoint,
)


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


def test_candidate_patch_checkpoint_restores_tracked_and_untracked_files(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _init_git_workspace(workspace)
    source = _commit_file(workspace, "src/app.py", "print('base')\n")

    checkpoint = create_candidate_patch_checkpoint(workspace, label="before-candidate")

    source.write_text("print('candidate')\n", encoding="utf-8")
    scratch = workspace / "scratch.py"
    scratch.write_text("print('debug')\n", encoding="utf-8")

    restore_candidate_patch_checkpoint(checkpoint)

    assert source.read_text(encoding="utf-8") == "print('base')\n"
    assert not scratch.exists()


def test_candidate_patch_checkpoint_preserves_preexisting_dirty_state(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _init_git_workspace(workspace)
    source = _commit_file(workspace, "src/app.py", "print('base')\n")

    source.write_text("print('accepted')\n", encoding="utf-8")
    checkpoint = create_candidate_patch_checkpoint(workspace, label="accepted")

    source.write_text("print('failed-candidate')\n", encoding="utf-8")

    restore_candidate_patch_checkpoint(checkpoint)

    assert source.read_text(encoding="utf-8") == "print('accepted')\n"
