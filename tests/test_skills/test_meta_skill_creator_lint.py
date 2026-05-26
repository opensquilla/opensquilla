"""Dogfood: meta-skill-creator/SKILL.md itself must pass G1+G2."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LINT = (
    REPO / "src" / "opensquilla" / "skills" / "bundled"
    / "skill-creator-linter" / "scripts" / "lint.py"
)
CREATOR_MD = (
    REPO / "src" / "opensquilla" / "skills" / "bundled"
    / "meta-skill-creator" / "SKILL.md"
)


def test_meta_skill_creator_passes_g1_g2() -> None:
    proc = subprocess.run(
        [sys.executable, str(LINT), "--skill-md", str(CREATOR_MD), "--gates", "G1,G2"],
        capture_output=True, text=True, check=True,
    )
    out = json.loads(proc.stdout)
    assert out["G1"]["passed"] is True, f"G1 fail: {out['G1']['diagnostics']}"
    assert out["G2"]["passed"] is True, f"G2 fail: {out['G2']['diagnostics']}"
