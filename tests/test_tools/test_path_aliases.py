from __future__ import annotations

from pathlib import PureWindowsPath

from opensquilla.tools.path_aliases import resolve_workspace_alias


def test_workspace_alias_accepts_windows_root_relative_path(tmp_path):
    resolved = resolve_workspace_alias(
        PureWindowsPath("/workspace/figure.pdf"),
        tmp_path,
    )

    assert resolved == (tmp_path / "figure.pdf").resolve(strict=False)
