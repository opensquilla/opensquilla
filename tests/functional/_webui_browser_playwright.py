"""Shared Playwright setup helpers for opt-in functional browser tests."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def npm_command() -> str:
    return "npm.cmd" if os.name == "nt" else "npm"


def node_command() -> str:
    return "node.exe" if os.name == "nt" else "node"


def playwright_command(work_dir: Path) -> Path:
    suffix = "playwright.cmd" if os.name == "nt" else "playwright"
    return work_dir / "node_modules" / ".bin" / suffix


def install_playwright(work_dir: Path) -> None:
    package_result = subprocess.run(
        [npm_command(), "--prefix", str(work_dir), "install", "playwright"],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert package_result.returncode == 0, package_result.stderr or package_result.stdout

    browser_result = subprocess.run(
        [str(playwright_command(work_dir)), "install", "chromium"],
        cwd=work_dir,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert browser_result.returncode == 0, browser_result.stderr or browser_result.stdout
