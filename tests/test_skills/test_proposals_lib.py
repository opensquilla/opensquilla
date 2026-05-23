"""Unit tests for opensquilla.skills.proposals_lib."""

from __future__ import annotations

import json
from pathlib import Path

from opensquilla.skills import proposals_lib

SAMPLE_SKILL_MD = """---
name: synth-test-pipeline
description: "Sample synthetic pipeline for proposals_lib tests"
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
        task: "{{ inputs.user_message }}"
---
"""

GATES_PASSING = {
    "G1": {"passed": True}, "G2": {"passed": True},
}
SMOKE_PASSING = {
    "G3": {"passed": True}, "G4": {"passed": True},
}


def _seed_proposal(home: Path, *, eligible: bool = True) -> str:
    result = proposals_lib.write_proposal(
        home,
        SAMPLE_SKILL_MD,
        GATES_PASSING if eligible else {"G1": {"passed": False}},
        SMOKE_PASSING,
    )
    assert result["status"] == "ok"
    return result["proposal_id"]


def test_is_valid_proposal_id() -> None:
    assert proposals_lib.is_valid_proposal_id("abcd1234") is True
    assert proposals_lib.is_valid_proposal_id("ABCD1234") is False  # uppercase rejected
    assert proposals_lib.is_valid_proposal_id("abcd123") is False   # too short
    assert proposals_lib.is_valid_proposal_id("../etc/passwd") is False
    assert proposals_lib.is_valid_proposal_id("") is False
    assert proposals_lib.is_valid_proposal_id(None) is False


def test_write_then_list_then_pending_count(tmp_path: Path) -> None:
    home = tmp_path / ".opensquilla"
    pid1 = _seed_proposal(home)
    pid2 = _seed_proposal(home)
    rows = proposals_lib.list_proposals(home)["proposals"]
    assert sorted(r["proposal_id"] for r in rows) == sorted([pid1, pid2])
    assert all(r["auto_enable_eligible"] for r in rows)
    assert proposals_lib.pending_count(home) == {"count": 2}


def test_pending_count_on_empty_home(tmp_path: Path) -> None:
    home = tmp_path / "empty"
    assert proposals_lib.pending_count(home) == {"count": 0}


def test_list_proposals_surfaces_provenance(tmp_path: Path) -> None:
    home = tmp_path / ".opensquilla"
    pid = _seed_proposal(home)
    # Patch gates.json with provenance
    gates_path = home / "proposals" / pid / "gates.json"
    gates = json.loads(gates_path.read_text())
    gates["provenance"] = {
        "triggered_by": "auto_cron",
        "chain_hash": "deadbeefcafebabe",
    }
    gates_path.write_text(json.dumps(gates))
    rows = proposals_lib.list_proposals(home)["proposals"]
    assert rows[0]["triggered_by"] == "auto_cron"
    assert rows[0]["chain_hash"] == "deadbeefcafebabe"


def test_show_returns_payload(tmp_path: Path) -> None:
    home = tmp_path / ".opensquilla"
    pid = _seed_proposal(home)
    out = proposals_lib.show_proposal(home, pid)
    assert out["status"] == "ok"
    assert out["proposal_id"] == pid
    assert "synth-test-pipeline" in out["skill_md"]
    assert out["gates"]["auto_enable_eligible"] is True


def test_show_rejects_invalid_id(tmp_path: Path) -> None:
    home = tmp_path / ".opensquilla"
    out = proposals_lib.show_proposal(home, "../etc")
    assert out["status"] == "error"


def test_show_missing_proposal(tmp_path: Path) -> None:
    home = tmp_path / ".opensquilla"
    out = proposals_lib.show_proposal(home, "deadbeef")
    assert out["status"] == "error"
    assert "not found" in out["reason"]


def test_accept_promotes_to_managed_skills(tmp_path: Path) -> None:
    home = tmp_path / ".opensquilla"
    pid = _seed_proposal(home)
    out = proposals_lib.accept_proposal(home, pid)
    assert out["status"] == "ok"
    assert out["name"] == "synth-test-pipeline"
    moved = home / "skills" / "synth-test-pipeline" / "SKILL.md"
    assert moved.is_file()
    # Source dir disappears
    assert not (home / "proposals" / pid).exists()


def test_accept_refuses_when_gates_fail_without_force(tmp_path: Path) -> None:
    home = tmp_path / ".opensquilla"
    pid = _seed_proposal(home, eligible=False)
    out = proposals_lib.accept_proposal(home, pid)
    assert out["status"] == "refused"
    out2 = proposals_lib.accept_proposal(home, pid, force=True)
    assert out2["status"] == "ok"


def test_accept_refuses_when_target_skill_exists(tmp_path: Path) -> None:
    home = tmp_path / ".opensquilla"
    pid1 = _seed_proposal(home)
    proposals_lib.accept_proposal(home, pid1)
    pid2 = _seed_proposal(home)
    out = proposals_lib.accept_proposal(home, pid2)
    assert out["status"] == "refused"
    assert "already exists" in out["reason"]


def test_reject_removes_directory(tmp_path: Path) -> None:
    home = tmp_path / ".opensquilla"
    pid = _seed_proposal(home)
    out = proposals_lib.reject_proposal(home, pid)
    assert out["status"] == "ok"
    assert not (home / "proposals" / pid).exists()


def test_reject_rejects_invalid_id(tmp_path: Path) -> None:
    home = tmp_path / ".opensquilla"
    out = proposals_lib.reject_proposal(home, "../etc/passwd")
    assert out["status"] == "error"


def test_reject_missing_proposal(tmp_path: Path) -> None:
    home = tmp_path / ".opensquilla"
    out = proposals_lib.reject_proposal(home, "deadbeef")
    assert out["status"] == "error"


def test_write_atomic_under_concurrent_writers(tmp_path: Path) -> None:
    """Writing N proposals should produce N distinct directories — the
    atomic-rename guarantees uniqueness even if proposal_ids collide."""
    home = tmp_path / ".opensquilla"
    ids = []
    for _ in range(5):
        out = proposals_lib.write_proposal(home, SAMPLE_SKILL_MD, GATES_PASSING, SMOKE_PASSING)
        assert out["status"] == "ok"
        ids.append(out["proposal_id"])
    assert len(set(ids)) == 5  # all distinct
    assert proposals_lib.pending_count(home)["count"] == 5
