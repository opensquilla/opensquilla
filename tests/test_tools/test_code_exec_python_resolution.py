from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from opensquilla.tools.builtin import code_exec


def test_code_exec_prefers_current_interpreter_when_path_has_no_python(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    python_bin = tmp_path / ("python.exe" if os.name == "nt" else "python")
    python_bin.write_text("", encoding="utf-8")
    python_bin.chmod(python_bin.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(sys, "executable", str(python_bin))
    monkeypatch.setattr(code_exec.shutil, "which", lambda _name: None)

    assert code_exec._resolve_python_bin(sandbox_enabled=False) == str(python_bin)
