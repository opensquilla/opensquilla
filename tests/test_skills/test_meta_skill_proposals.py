"""Tests for meta-skill-proposals bundled skill (write/list/accept/reject)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_BUNDLED = REPO / "src" / "opensquilla" / "skills" / "bundled"
PROPOSALS = _BUNDLED / "meta-skill-proposals" / "scripts" / "proposals.py"


def _run(action: str, *args, home: Path, **kwargs) -> dict:
    cmd = [sys.executable, str(PROPOSALS), "--action", action,
           "--home", str(home), *args]
    for k, v in kwargs.items():
        cmd.extend([f"--{k.replace('_', '-')}", str(v)])
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(proc.stdout)


SAMPLE_SKILL_MD = """---
name: synth-test-pipeline
description: "Sample synthetic pipeline for proposals tests"
kind: meta
meta_priority: 50
triggers:
  - "synth test trigger"
provenance:
  origin: opensquilla-user
composition:
  steps:
    - id: a
      skill: summarize
      with:
        task: "{{ inputs.user_message | xml_escape | truncate(512) }}"
---
"""


def test_write_proposal_creates_directory(tmp_path: Path) -> None:
    home = tmp_path / ".opensquilla"
    out = _run(
        "write_proposal", home=home,
        skill_md_inline=SAMPLE_SKILL_MD,
        lint_result=json.dumps({"G1": {"passed": True}, "G2": {"passed": True}}),
        smoke_result=json.dumps({"G3": {"passed": True}, "G4": {"passed": True}}),
    )
    assert out["status"] == "ok"
    proposal_id = out["proposal_id"]
    proposal_dir = home / "proposals" / proposal_id
    assert (proposal_dir / "SKILL.md").exists()
    assert (proposal_dir / "gates.json").exists()
    gates = json.loads((proposal_dir / "gates.json").read_text())
    assert gates["auto_enable_eligible"] is True


def test_write_proposal_marks_ineligible_on_g3_fail(tmp_path: Path) -> None:
    home = tmp_path / ".opensquilla"
    out = _run(
        "write_proposal", home=home,
        skill_md_inline=SAMPLE_SKILL_MD,
        lint_result=json.dumps({"G1": {"passed": True}, "G2": {"passed": True}}),
        smoke_result=json.dumps({"G3": {"passed": False, "reason": "classifier missed"},
                                  "G4": {"passed": True}}),
    )
    gates = json.loads((home / "proposals" / out["proposal_id"] / "gates.json").read_text())
    assert gates["auto_enable_eligible"] is False


def test_accept_rejects_path_traversal_proposal_id(tmp_path: Path) -> None:
    """I1 regression: cmd_accept must reject proposal IDs that aren't 8 hex chars."""
    home = tmp_path / ".opensquilla"
    home.mkdir()
    (home / "proposals").mkdir()

    for bad_id in ["../../etc", "../sibling", "abcd1234567890", "ABCDEF12", ""]:
        out = _run("accept", home=home, proposal_id=bad_id)
        assert out["status"] == "error", f"should reject {bad_id!r}, got: {out}"
        assert "invalid proposal_id" in out["reason"]
