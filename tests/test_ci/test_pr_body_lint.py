from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path


def _load_lint_module():
    script = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "validate_pr_body.py"
    spec = importlib.util.spec_from_file_location("validate_pr_body", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pr_body_lint_accepts_complete_structured_template_body() -> None:
    lint = _load_lint_module()

    body = "\n".join(
        [
            "Scope boundary: update CI governance",
            "Base branch: dev",
            "Main exception: N/A",
            "Linked issue: Refs #210",
            "Release note: NONE",
            "Tests:",
            "Ruff: uv run ruff check tests",
            "Pytest: uv run pytest tests/test_ci -q",
            "Build: not run locally; CI only",
            "Maintainer live check: no",
            "Third-party origin: none",
        ]
    )

    assert lint.missing_fields(body) == []


def test_pr_body_lint_accepts_repository_template_fields() -> None:
    lint = _load_lint_module()
    template = Path(".github/pull_request_template.md").read_text(encoding="utf-8")

    assert lint.missing_fields(template) == []


def test_pr_body_lint_warns_for_old_unstructured_checklist() -> None:
    lint = _load_lint_module()

    missing = lint.missing_fields("- [ ] I ran `uv run pytest -q`.")

    assert "Scope boundary" in missing
    assert "Base branch" in missing
    assert "Linked issue" in missing
    assert "Release note" in missing
    assert "Maintainer live check" in missing


def test_pr_body_lint_is_warning_only_for_incomplete_body(tmp_path: Path) -> None:
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps({"pull_request": {"body": "Fixes #100"}}),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["GITHUB_EVENT_PATH"] = event_path.as_posix()
    env["PR_BODY_LINT_STRICT"] = "0"
    result = subprocess.run(
        [
            sys.executable,
            ".github/scripts/validate_pr_body.py",
        ],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "::warning title=Missing PR template field::" in result.stdout
    assert "Scope boundary" in result.stdout


def test_pr_body_lint_can_fail_in_strict_mode(tmp_path: Path) -> None:
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps({"pull_request": {"body": "Fixes #100"}}),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["GITHUB_EVENT_PATH"] = event_path.as_posix()
    env["PR_BODY_LINT_STRICT"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            ".github/scripts/validate_pr_body.py",
        ],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "::warning title=Missing PR template field::" in result.stdout


def test_pr_body_lint_handles_missing_event_path_as_warning_only() -> None:
    env = os.environ.copy()
    env.pop("GITHUB_EVENT_PATH", None)
    env["PR_BODY_LINT_STRICT"] = "0"

    result = subprocess.run(
        [
            sys.executable,
            ".github/scripts/validate_pr_body.py",
        ],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "::warning title=Missing PR event::" in result.stdout
