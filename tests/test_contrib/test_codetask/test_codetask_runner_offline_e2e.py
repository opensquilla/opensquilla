"""Offline runner-level E2E coverage for code-task scratch mode."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from opensquilla.contrib.codetask import config, runner
from opensquilla.contrib.codetask.types import AgentOutcome, TaskState


class _OfflineAdapter:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def run(self, prompt, *, repo: Path, scratch_dir: Path, artifact_dir: Path):
        repo.mkdir(parents=True, exist_ok=True)
        scratch_dir.mkdir(parents=True, exist_ok=True)
        artifact_dir.mkdir(parents=True, exist_ok=True)

        (repo / "calc.py").write_text(
            "def add(a, b):\n"
            "    return a + b\n",
            encoding="utf-8",
        )
        (repo / "test_calc.py").write_text(
            "from calc import add\n\n\n"
            "def test_add():\n"
            "    assert add(1, 2) == 3\n",
            encoding="utf-8",
        )
        (scratch_dir / config.VERIFICATION_MANIFEST_NAME).write_text(
            json.dumps(
                {
                    "testable": True,
                    "acceptance_tests": [
                        {
                            "name": "pytest",
                            "command": "python -m pytest -q",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        (artifact_dir / "agent_stdout.log").write_text(
            "offline adapter wrote calc.py and test_calc.py\n",
            encoding="utf-8",
        )
        return AgentOutcome(
            success=True,
            timeout=False,
            exit_code=0,
            finish_reason="stop",
            usage={"total_tokens": 0, "model": "offline"},
            duration_seconds=0.0,
        )


def test_scratch_runner_e2e_offline_adapter_verifies(monkeypatch, tmp_path) -> None:
    run_id = "codetask-offline-e2e"
    runs_dir = tmp_path / "runs"
    monkeypatch.setenv("OPENSQUILLA_CODETASK_RUNS_DIR", str(runs_dir))
    monkeypatch.setattr(runner, "LocalAdapter", _OfflineAdapter)

    result = runner.solve(
        task="create a tested add function",
        verification_mode="scratch",
        run_id=run_id,
        timeout=600,
        max_attempts=1,
    )

    assert result.state is TaskState.VERIFIED
    assert result.verified is True
    assert result.verification_kind == "scratch"
    assert result.attempts == 1
    assert result.files_changed >= 2
    assert result.acceptance
    assert result.acceptance[0].after == "pass"

    run_dir = runs_dir / run_id
    assert Path(result.artifact_dir or "").is_dir()
    assert result.artifact_dir == str(run_dir)
    assert Path(result.patch_path or "").is_file()
    assert (run_dir / "result.json").is_file()
    assert (run_dir / "prompt.txt").is_file()
    assert (run_dir / config.VERIFICATION_MANIFEST_NAME).is_file()
    assert (run_dir / "attempts" / "01" / "change.patch").is_file()
    assert (run_dir / "repo" / "calc.py").is_file()
