"""Tests for meta-skill-linter (G1 + G2 gates)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_LINTER_DIR = REPO / "src" / "opensquilla" / "skills" / "bundled" / "meta-skill-linter"
LINT = _LINTER_DIR / "scripts" / "lint.py"


def _run_lint(skill_md: str, gates: str = "G1,G2") -> dict:
    proc = subprocess.run(
        [sys.executable, str(LINT), "--gates", gates, "--skill-md-stdin"],
        input=skill_md, capture_output=True, text=True,
    )
    return json.loads(proc.stdout)


VALID_P1 = """---
name: lint-test-p1
description: "Lint-test P1 sequential meta-skill: extract then summarize."
kind: meta
meta_priority: 50
triggers:
  - "lint test trigger"
provenance:
  origin: opensquilla-user
composition:
  steps:
    - id: extract
      skill: pdf-toolkit
      with:
        task: "Extract: {{ inputs.user_message | xml_escape | truncate(512) }}"
    - id: digest
      skill: summarize
      depends_on: [extract]
      with:
        text: "{{ outputs.extract | truncate(2000) }}"
---
# Lint test P1
"""


def test_g1_passes_on_valid_p1() -> None:
    out = _run_lint(VALID_P1)
    assert out["G1"]["passed"] is True


def test_g1_fails_on_missing_xml_escape() -> None:
    bad = VALID_P1.replace("{{ inputs.user_message | xml_escape | truncate(512) }}",
                            "{{ inputs.user_message }}")
    out = _run_lint(bad)
    assert out["G1"]["passed"] is False
    assert any("xml_escape" in d.lower() for d in out["G1"]["diagnostics"])


def test_g1_fails_on_unknown_skill_reference() -> None:
    bad = VALID_P1.replace("skill: pdf-toolkit", "skill: this-skill-does-not-exist")
    out = _run_lint(bad)
    assert out["G1"]["passed"] is False
    assert any("does-not-exist" in d for d in out["G1"]["diagnostics"])


def test_g2_passes_on_valid_p1() -> None:
    out = _run_lint(VALID_P1)
    assert out["G2"]["passed"] is True


EXISTING_META_BUNDLES = [
    "meta-pdf-intelligence", "meta-travel-planner", "meta-security-review-bundle",
    "meta-migration-assistant", "meta-knowledge-base-bootstrap",
    "meta-multi-format-export-pack", "meta-compliance-audit-bundle",
    "meta-spreadsheet-insight", "meta-self-improving-skill-factory",
    "meta-research-to-deck", "meta-web-research-to-report",
    "meta-web-to-pdf-briefing", "meta-github-pr-watch-digest",
    "meta-issue-to-pr-autopilot", "meta-long-running-build-watchdog",
    "meta-pdf-reformat-pipeline", "meta-scheduled-morning-digest",
]


@pytest.mark.parametrize("bundle", EXISTING_META_BUNDLES)
def test_linter_passes_existing_meta_bundle(bundle: str) -> None:
    """Regression: linter must accept every existing kind=meta bundle.
    Catches over-strict lint rules."""
    skill_path = REPO / "src" / "opensquilla" / "skills" / "bundled" / bundle / "SKILL.md"
    skill_md = skill_path.read_text()
    out = _run_lint(skill_md)
    assert out["G1"]["passed"] is True, f"{bundle} G1 fail: {out['G1']['diagnostics']}"
    assert out["G2"]["passed"] is True, f"{bundle} G2 fail: {out['G2']['diagnostics']}"
