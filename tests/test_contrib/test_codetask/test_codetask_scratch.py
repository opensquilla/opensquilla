"""Scratch (from-scratch, green-only) verification mode."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from opensquilla.contrib.codetask import config, workspace
from opensquilla.contrib.codetask import runner as codetask_runner
from opensquilla.contrib.codetask.inputs import InputError
from opensquilla.contrib.codetask.types import TaskState
from opensquilla.contrib.codetask.verification import verify_scratch


def _runs(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSQUILLA_CODETASK_RUNS_DIR", str(tmp_path / "runs"))


def test_prompt_template_scratch() -> None:
    assert config.prompt_template_path("scratch").name == "scratch.txt"
    assert config.prompt_template_path("red-green").name == "default.txt"


def test_prepare_scratch_repo_empty_with_base(monkeypatch, tmp_path) -> None:
    _runs(monkeypatch, tmp_path)
    pr = workspace.prepare_scratch_repo("codetask-scr-0001", slug="demo")
    assert pr.path.exists()
    assert pr.base_commit and pr.base_ref == "(scratch)"
    assert pr.branch.endswith("demo")
    log = subprocess.run(
        ["git", "-C", str(pr.path), "log", "--oneline"],
        capture_output=True, text=True,
    ).stdout.strip()
    assert log.count("\n") == 0 and "scratch base" in log  # exactly one empty base commit


def test_runner_scratch_rejects_repo() -> None:
    with pytest.raises(InputError, match="Do not pass repo"):
        codetask_runner.solve(repo="/tmp/x", task="do it", verification_mode="scratch")


def test_runner_requires_repo_outside_scratch() -> None:
    with pytest.raises(InputError, match="Pass repo"):
        codetask_runner.solve(task="do it")


def _scratch_repo(monkeypatch, tmp_path):
    _runs(monkeypatch, tmp_path)
    pr = workspace.prepare_scratch_repo("codetask-scr-vfy", slug="demo")
    (pr.path / "solution.py").write_text("def double(x):\n    return x * 2\n")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    return pr, scratch


def _write_manifest(scratch: Path, manifest: dict) -> None:
    (scratch / config.VERIFICATION_MANIFEST_NAME).write_text(json.dumps(manifest))


@pytest.mark.skipif(sys.platform == "win32", reason="code-task Windows support is WIP")
def test_verify_scratch_green_verified(monkeypatch, tmp_path) -> None:
    pr, scratch = _scratch_repo(monkeypatch, tmp_path)
    _write_manifest(
        scratch,
        {
            "testable": True,
            "acceptance_tests": [
                {
                    "name": "double",
                    "command": (
                        f"PYTHONPATH=. {sys.executable} "
                        "-c 'from solution import double; assert double(3)==6'"
                    ),
                }
            ],
        },
    )
    out = verify_scratch(repo=pr.path, scratch_dir=scratch)
    assert out.state == TaskState.VERIFIED
    assert out.acceptance and out.acceptance[0].after == "pass"
    assert out.acceptance[0].green_exit_code == 0
    assert out.regression is None  # green-only: no regression


def test_verify_scratch_failing_command_failed(monkeypatch, tmp_path) -> None:
    pr, scratch = _scratch_repo(monkeypatch, tmp_path)
    _write_manifest(
        scratch,
        {
            "testable": True,
            "acceptance_tests": [
                {
                    "name": "bad",
                    "command": (
                        f"PYTHONPATH=. {sys.executable} "
                        "-c 'from solution import double; assert double(3)==7'"
                    ),
                }
            ],
        },
    )
    out = verify_scratch(repo=pr.path, scratch_dir=scratch)
    assert out.state == TaskState.FAILED
    assert out.acceptance[0].after == "fail"


def test_verify_scratch_no_manifest_invalid(monkeypatch, tmp_path) -> None:
    pr, scratch = _scratch_repo(monkeypatch, tmp_path)
    out = verify_scratch(repo=pr.path, scratch_dir=scratch)
    assert out.state == TaskState.INVALID_ACCEPTANCE_TEST


def test_verify_scratch_not_testable(monkeypatch, tmp_path) -> None:
    pr, scratch = _scratch_repo(monkeypatch, tmp_path)
    _write_manifest(scratch, {"testable": False, "not_testable_reason": "needs a GUI"})
    out = verify_scratch(repo=pr.path, scratch_dir=scratch)
    assert out.state == TaskState.NOT_TESTABLE
    assert "GUI" in (out.detail or "")


def test_verify_scratch_no_runnable_tests_invalid(monkeypatch, tmp_path) -> None:
    pr, scratch = _scratch_repo(monkeypatch, tmp_path)
    _write_manifest(scratch, {"testable": True, "acceptance_tests": []})
    out = verify_scratch(repo=pr.path, scratch_dir=scratch)
    assert out.state == TaskState.INVALID_ACCEPTANCE_TEST
