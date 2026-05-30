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


def test_list_proposals_surfaces_auto_enable_decision(tmp_path: Path) -> None:
    home = tmp_path / ".opensquilla"
    pid = _seed_proposal(home)
    gates_path = home / "proposals" / pid / "gates.json"
    gates = json.loads(gates_path.read_text())
    gates["auto_enable"] = {
        "status": "skipped",
        "reason": "risk_too_high",
        "risk_level": "high",
        "max_risk": "low",
    }
    gates_path.write_text(json.dumps(gates))
    rows = proposals_lib.list_proposals(home)["proposals"]
    assert rows[0]["auto_enable"] == {
        "status": "skipped",
        "reason": "risk_too_high",
        "risk_level": "high",
        "max_risk": "low",
        "validation_profile": "unknown",
        "skills": [],
        "tools": [],
        "reasons": [],
    }


def test_show_returns_payload(tmp_path: Path) -> None:
    home = tmp_path / ".opensquilla"
    pid = _seed_proposal(home)
    out = proposals_lib.show_proposal(home, pid)
    assert out["status"] == "ok"
    assert out["proposal_id"] == pid
    assert "synth-test-pipeline" in out["skill_md"]
    assert out["gates"]["auto_enable_eligible"] is True


def test_full_gated_requires_runtime_e2e_result(tmp_path: Path) -> None:
    home = tmp_path / ".opensquilla"
    result = proposals_lib.write_proposal(
        home,
        SAMPLE_SKILL_MD,
        GATES_PASSING,
        SMOKE_PASSING,
        creator_mode="FULL_GATED",
        acceptance_result={
            "raw": (
                "WINNER: orchestrated\n"
                "REASONS:\n"
                "- candidate has stricter gates\n"
                "REGRESSIONS:\n"
                "- none\n"
                "REQUIRED_IMPROVEMENTS:\n"
                "- none\n"
            ),
        },
    )

    assert result["status"] == "ok"
    assert result["auto_enable_eligible"] is False
    shown = proposals_lib.show_proposal(home, result["proposal_id"])
    assert shown["gates"]["runtime_e2e"]["required"] is True
    assert shown["gates"]["runtime_e2e"]["passed"] is False
    assert shown["gates"]["runtime_e2e"]["reason"] == "missing_runtime_e2e_result"

    accepted = proposals_lib.accept_proposal(home, result["proposal_id"])
    assert accepted["status"] == "refused"
    assert "gates not all passed" in accepted["reason"]


def test_full_gated_runtime_e2e_blocks_baseline_winner(tmp_path: Path) -> None:
    home = tmp_path / ".opensquilla"
    result = proposals_lib.write_proposal(
        home,
        SAMPLE_SKILL_MD,
        GATES_PASSING,
        SMOKE_PASSING,
        creator_mode="FULL_GATED",
        acceptance_result={
            "raw": (
                "WINNER: orchestrated\n"
                "REASONS:\n"
                "- candidate has stricter gates\n"
                "REGRESSIONS:\n"
                "- none\n"
                "REQUIRED_IMPROVEMENTS:\n"
                "- none\n"
            ),
        },
        runtime_e2e_result={
            "status": "ok",
            "passed": False,
            "winner": "baseline",
            "cases": [
                {
                    "prompt": "please use synth test trigger",
                    "winner": "baseline",
                    "regression": "meta answer missed the requested summary",
                },
            ],
        },
    )

    assert result["auto_enable_eligible"] is False
    shown = proposals_lib.show_proposal(home, result["proposal_id"])
    assert shown["gates"]["runtime_e2e"]["passed"] is False
    assert shown["gates"]["runtime_e2e"]["winner"] == "baseline"


def test_full_gated_acceptance_blocks_single_model_winner_even_when_runtime_passes(
    tmp_path: Path,
) -> None:
    home = tmp_path / ".opensquilla"
    result = proposals_lib.write_proposal(
        home,
        SAMPLE_SKILL_MD,
        GATES_PASSING,
        SMOKE_PASSING,
        creator_mode="FULL_GATED",
        acceptance_result={
            "raw": (
                "WINNER: single-model\n"
                "REASONS:\n"
                "- baseline SKILL.md reads cleaner\n"
                "REGRESSIONS:\n"
                "- none\n"
                "REQUIRED_IMPROVEMENTS:\n"
                "- none\n"
            ),
        },
        runtime_e2e_result={
            "status": "ok",
            "passed": True,
            "winner": "meta",
            "cases": [
                {
                    "prompt": "please use synth test trigger",
                    "winner": "meta",
                    "regression": "",
                },
            ],
        },
        collision_result="PASS: no trigger collision",
        risk_result="RISK: low\nCAPABILITIES:\n- read-only",
    )

    assert result["auto_enable_eligible"] is False
    shown = proposals_lib.show_proposal(home, result["proposal_id"])
    assert shown["gates"]["acceptance_compare"]["passed"] is False
    assert shown["gates"]["acceptance_compare"]["winner"] == "single-model"
    assert shown["gates"]["runtime_e2e"]["passed"] is True


def test_full_gated_acceptance_blocks_low_weighted_quality_score(tmp_path: Path) -> None:
    home = tmp_path / ".opensquilla"
    result = proposals_lib.write_proposal(
        home,
        SAMPLE_SKILL_MD,
        GATES_PASSING,
        SMOKE_PASSING,
        creator_mode="FULL_GATED",
        acceptance_result={
            "raw": (
                "WINNER: orchestrated\n"
                "QUALITY_SCORE: 0.71\n"
                "REASONS:\n"
                "- candidate works but lacks output contracts\n"
                "REGRESSIONS:\n"
                "- weaker final artifact quality\n"
                "REQUIRED_IMPROVEMENTS:\n"
                "- none\n"
            ),
        },
        runtime_e2e_result={
            "status": "ok",
            "passed": True,
            "winner": "meta",
            "cases": [{"winner": "meta", "regression": ""}],
        },
    )

    assert result["auto_enable_eligible"] is False
    shown = proposals_lib.show_proposal(home, result["proposal_id"])
    assert shown["gates"]["acceptance_compare"]["passed"] is False
    assert shown["gates"]["acceptance_compare"]["quality_score"] == 0.71
    assert "quality score below 0.80" in shown["gates"]["acceptance_compare"]["diagnostics"]


def test_full_gated_blocks_collision_and_high_risk_results(tmp_path: Path) -> None:
    home = tmp_path / ".opensquilla"
    result = proposals_lib.write_proposal(
        home,
        SAMPLE_SKILL_MD,
        GATES_PASSING,
        SMOKE_PASSING,
        creator_mode="FULL_GATED",
        acceptance_result={
            "raw": (
                "WINNER: orchestrated\n"
                "QUALITY_SCORE: 0.93\n"
                "REQUIRED_IMPROVEMENTS:\n"
                "- none\n"
            ),
        },
        runtime_e2e_result={
            "status": "ok",
            "passed": True,
            "winner": "meta",
            "cases": [{"winner": "meta", "regression": ""}],
        },
        collision_result="REVISE_NEEDED: trigger overlaps with summarize",
        risk_result="RISK: high\nCAPABILITIES:\n- shell",
    )

    assert result["auto_enable_eligible"] is False
    shown = proposals_lib.show_proposal(home, result["proposal_id"])
    assert shown["gates"]["collision_check"]["passed"] is False
    assert shown["gates"]["risk_classify"]["passed"] is False


def test_full_gated_runtime_e2e_allows_meta_winner_when_acceptance_passes(
    tmp_path: Path,
) -> None:
    home = tmp_path / ".opensquilla"
    result = proposals_lib.write_proposal(
        home,
        SAMPLE_SKILL_MD,
        GATES_PASSING,
        SMOKE_PASSING,
        creator_mode="FULL_GATED",
        acceptance_result={
            "raw": (
                "WINNER: orchestrated\n"
                "REASONS:\n"
                "- candidate has stricter gates\n"
                "REGRESSIONS:\n"
                "- none\n"
                "REQUIRED_IMPROVEMENTS:\n"
                "- none\n"
            ),
        },
        runtime_e2e_result={
            "status": "ok",
            "passed": True,
            "winner": "meta",
            "cases": [
                {
                    "prompt": "please use synth test trigger",
                    "winner": "meta",
                    "regression": "",
                },
            ],
        },
        collision_result="PASS: no trigger collision",
        risk_result="RISK: low\nCAPABILITIES:\n- read-only",
    )

    assert result["auto_enable_eligible"] is True
    shown = proposals_lib.show_proposal(home, result["proposal_id"])
    assert shown["gates"]["acceptance_compare"]["passed"] is True
    assert shown["gates"]["runtime_e2e"]["passed"] is True


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


def test_list_and_disable_auto_enabled_skill(tmp_path: Path) -> None:
    home = tmp_path / ".opensquilla"
    pid = _seed_proposal(home)
    gates_path = home / "proposals" / pid / "gates.json"
    gates = json.loads(gates_path.read_text())
    gates["auto_enable"] = {
        "status": "enabled",
        "proposal_id": pid,
        "risk_level": "low",
        "max_risk": "low",
        "triggered_by": "manual",
        "enabled_at_ms": 123,
    }
    gates_path.write_text(json.dumps(gates))
    accepted = proposals_lib.accept_proposal(home, pid)
    assert accepted["status"] == "ok"

    rows = proposals_lib.list_auto_enabled_skills(home)["skills"]
    assert rows == [{
        "name": "synth-test-pipeline",
        "proposal_id": pid,
        "risk_level": "low",
        "max_risk": "low",
        "triggered_by": "manual",
        "enabled_at_ms": 123,
        "validation_profile": "unknown",
        "skills": [],
        "tools": [],
        "reasons": [],
    }]

    out = proposals_lib.disable_auto_enabled_skill(home, "synth-test-pipeline")
    assert out["status"] == "ok"
    assert out["proposal_id"] == pid
    assert not (home / "skills" / "synth-test-pipeline").exists()
    assert (home / "proposals" / pid / "SKILL.md").is_file()
    disabled_gates = json.loads((home / "proposals" / pid / "gates.json").read_text())
    assert disabled_gates["auto_enable"]["status"] == "disabled"
    assert disabled_gates["auto_enable"]["previous_status"] == "enabled"


def test_disable_auto_enabled_skill_refuses_manual_skill(tmp_path: Path) -> None:
    home = tmp_path / ".opensquilla"
    pid = _seed_proposal(home)
    accepted = proposals_lib.accept_proposal(home, pid)
    assert accepted["status"] == "ok"
    out = proposals_lib.disable_auto_enabled_skill(home, "synth-test-pipeline")
    assert out["status"] == "refused"
    assert "not auto-enabled" in out["reason"]


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


def test_auto_propose_settings_round_trip(tmp_path: Path) -> None:
    home = tmp_path / ".opensquilla"
    assert proposals_lib.read_auto_propose_settings(home) == {}
    proposals_lib.write_auto_propose_settings(
        home, {
            "enabled": True,
            "on_dream_complete": False,
            "auto_enable": True,
            "auto_enable_max_risk": "medium",
        },
    )
    out = proposals_lib.read_auto_propose_settings(home)
    assert out == {
        "enabled": True,
        "on_dream_complete": False,
        "auto_enable": True,
        "auto_enable_max_risk": "medium",
    }


def test_auto_propose_settings_drops_unknown_and_bad_types(tmp_path: Path) -> None:
    home = tmp_path / ".opensquilla"
    # Unknown keys dropped at write time
    proposals_lib.write_auto_propose_settings(
        home, {
            "enabled": True,
            "auto_enable_max_risk": "dangerous",
            "bogus_key": True,
        },  # type: ignore[arg-type]
    )
    assert proposals_lib.read_auto_propose_settings(home) == {"enabled": True}
    # Bad-shape file → empty dict (no exception)
    proposals_lib.auto_propose_settings_path(home).write_text("[1,2,3]")
    assert proposals_lib.read_auto_propose_settings(home) == {}


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
