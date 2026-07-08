from __future__ import annotations

from pathlib import Path

from opensquilla.sandbox.operation_runtime import SandboxOperation


def test_windows_filesystem_write_existing_file_targets_file_and_parent(
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend import windows_default as mod

    target = tmp_path / "notes.txt"
    target.write_text("old\n", encoding="utf-8")
    operation = SandboxOperation.filesystem(
        kind="write_text",
        workspace=tmp_path,
        run_mode="trusted",
        path=target,
        paths=(target,),
        content="new\n",
    )

    assert mod._filesystem_operation_target_roots(operation) == (tmp_path, target)


def test_windows_filesystem_write_missing_file_targets_parent_only(
    tmp_path: Path,
) -> None:
    from opensquilla.sandbox.backend import windows_default as mod

    target = tmp_path / "notes.txt"
    operation = SandboxOperation.filesystem(
        kind="write_text",
        workspace=tmp_path,
        run_mode="trusted",
        path=target,
        paths=(target,),
        content="new\n",
    )

    assert mod._filesystem_operation_target_roots(operation) == (tmp_path,)
