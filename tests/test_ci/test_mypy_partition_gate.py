from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

TIER_A_MYPY_PARTITION: tuple[str, ...] = (
    "src/opensquilla/tool_boundary.py",
    "src/opensquilla/tools/boundary.py",
    "src/opensquilla/gateway/session_services.py",
    "src/opensquilla/memory/protocols.py",
    "src/opensquilla/provider/protocol.py",
    "src/opensquilla/provider/openai.py",
    "src/opensquilla/session/compaction.py",
    "src/opensquilla/scheduler/routing.py",
    "src/opensquilla/scheduler/delivery.py",
    "src/opensquilla/scheduler/handlers.py",
    "src/opensquilla/skills/hub/installer.py",
    "src/opensquilla/skills/hub/scanner.py",
    "src/opensquilla/skills/hub/lockfile.py",
    "src/opensquilla/mcp/discovery.py",
    "src/opensquilla/tools/builtin/web.py",
)


@pytest.mark.skipif(
    os.environ.get("GITHUB_ACTIONS") == "true"
    and os.environ.get("GITHUB_WORKFLOW") == "CI",
    reason="the ubuntu-quality job runs mypy over all of src/opensquilla before pytest",
)
def test_tier_a_mypy_partition_stays_clean() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "mypy", *TIER_A_MYPY_PARTITION],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert result.returncode == 0, result.stdout
