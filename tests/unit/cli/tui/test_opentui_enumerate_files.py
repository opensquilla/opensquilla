from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from opensquilla.cli.tui.opentui import completion
from opensquilla.cli.tui.opentui.completion import enumerate_workspace_files


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")


def test_enumerate_workspace_files_fallback_filters_ignored_hidden_and_sensitive_paths(
    tmp_path: Path,
) -> None:
    (tmp_path / ".gitignore").write_text("ignored.txt\nbuild/\n*.tmp\n", encoding="utf-8")
    _touch(tmp_path / "src" / "main.py")
    _touch(tmp_path / "src" / "compact.py")
    _touch(tmp_path / "docs" / "reset.md")
    _touch(tmp_path / "ignored.txt")
    _touch(tmp_path / "build" / "artifact.log")
    _touch(tmp_path / ".hidden" / "shadow.py")
    _touch(tmp_path / "__pycache__" / "cached.pyc")
    _touch(tmp_path / "scratch.tmp")
    _touch(tmp_path / ".env")

    assert enumerate_workspace_files(tmp_path) == [
        ".gitignore",
        "docs/reset.md",
        "src/compact.py",
        "src/main.py",
    ]


def test_enumerate_workspace_files_applies_query_and_max_results(tmp_path: Path) -> None:
    _touch(tmp_path / "src" / "compact.py")
    _touch(tmp_path / "src" / "component.py")
    _touch(tmp_path / "docs" / "commands.md")
    _touch(tmp_path / "docs" / "reset.md")

    assert enumerate_workspace_files(tmp_path, query="cmp", max_results=2) == [
        "src/compact.py",
        "src/component.py",
    ]


def test_enumerate_workspace_files_uses_git_ls_files_when_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".git").mkdir()
    _touch(tmp_path / "src" / "compact.py")
    _touch(tmp_path / "src" / ".env")
    _touch(tmp_path / "docs" / "reset.md")
    monkeypatch.setattr(completion.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.setattr(
        completion.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="src/compact.py\nsrc/.env\ndocs/reset.md\n",
            stderr="",
        ),
    )

    assert enumerate_workspace_files(tmp_path, query="cmp") == ["src/compact.py"]
