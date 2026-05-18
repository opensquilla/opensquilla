"""Offline unit tests for the meta-paper-write bundled scripts.

Each test runs the wrapped CLI directly via subprocess, no LLM, no
orchestrator. The point is to catch syntax bugs and confirm the
contract (output files exist + look right) so the meta-skill
composition can rely on them.
"""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

BUNDLED = (
    Path(__file__).resolve().parents[2]
    / "src" / "opensquilla" / "skills" / "bundled"
)


def test_paper_experiment_stub_generates_csv(tmp_path: Path) -> None:
    out = tmp_path / "results.csv"
    script = BUNDLED / "paper-experiment-stub" / "scripts" / "gen_results.py"
    subprocess.run(
        [sys.executable, str(script), "--topic", "RAG benchmark", "--out", str(out)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert out.is_file()
    rows = list(csv.reader(out.open()))
    assert rows[0] == ["x", "y_baseline", "y_ours"]
    assert len(rows) == 21  # header + 20 data rows
    # y_ours must be ≥ y_baseline for every row (the stub's only invariant).
    for row in rows[1:]:
        assert float(row[2]) >= float(row[1])
