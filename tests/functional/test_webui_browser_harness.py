"""Unit coverage for the opt-in Web UI Playwright browser harness."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import _webui_browser_playwright as playwright_harness
import pytest


def test_install_playwright_installs_chromium_with_local_cli(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[list[str], Path, int]] = []

    def fake_run(
        args: list[str],
        *,
        cwd: Path,
        check: bool,
        capture_output: bool,
        text: bool,
        timeout: int,
        **_: Any,
    ) -> subprocess.CompletedProcess[str]:
        assert check is False
        assert capture_output is True
        assert text is True
        calls.append((args, cwd, timeout))
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(playwright_harness.subprocess, "run", fake_run)

    playwright_harness.install_playwright(tmp_path)

    assert calls == [
        (
            [playwright_harness.npm_command(), "--prefix", str(tmp_path), "install", "playwright"],
            Path.cwd(),
            120,
        ),
        (
            [str(playwright_harness.playwright_command(tmp_path)), "install", "chromium"],
            tmp_path,
            300,
        ),
    ]
