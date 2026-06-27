"""Report rendering + import-isolation guards for codetask."""

import subprocess
import sys

from opensquilla.contrib.codetask.report import render
from opensquilla.contrib.codetask.types import (
    AcceptanceCheck,
    RegressionResult,
    TaskResult,
    TaskState,
)


def _result(state, **kw):
    return TaskResult(
        task_slug="fix-it",
        run_id="r1",
        state=state,
        repo="org/proj",
        base_ref="main",
        branch="task/fix-it",
        source="inline",
        **kw,
    )


def test_render_verified():
    r = _result(
        TaskState.VERIFIED,
        verified=True,
        files_changed=2,
        commits=1,
        acceptance=[AcceptanceCheck(name="t", command="c", before="fail", after="pass")],
        regression=RegressionResult(
            command="pytest", ran=True, passed=10, failed=0, new_failures=0
        ),
        usage={"cost_usd": 0.18, "request_count": 12},
        duration_seconds=120.0,
    )
    text = render(r)
    assert "task/fix-it" in text
    assert "verified" in text
    assert "fail → pass" in text
    assert "$0.18" in text


def test_render_every_state_smoke():
    for state in TaskState:
        text = render(_result(state, assumptions=["assumed CSV not Excel"]))
        assert state.value in text


def test_opensquilla_import_does_not_load_codetask():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, opensquilla\nassert 'opensquilla.contrib.codetask' not in sys.modules\n",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
