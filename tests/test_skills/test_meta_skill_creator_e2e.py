"""End-to-end: creator pipeline with stubbed LLMs produces a valid proposal."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# creator_fixtures is on sys.path via tests/test_skills/conftest.py
from creator_fixtures import INTENT_PDF_DIGEST, INTENT_TRIP_PLANNER, synth_decision_log

from opensquilla.engine.types import TextDeltaEvent
from opensquilla.skills.loader import SkillLoader
from opensquilla.skills.meta.orchestrator import MetaOrchestrator
from opensquilla.skills.meta.parser import parse_meta_plan
from opensquilla.skills.meta.types import MetaMatch, MetaResult

REPO = Path(__file__).resolve().parents[2]
_BUNDLED_BASE = REPO / "src" / "opensquilla" / "skills" / "bundled"
PROPOSALS = _BUNDLED_BASE / "skill-creator-proposals" / "scripts" / "proposals.py"
LINT = _BUNDLED_BASE / "skill-creator-linter" / "scripts" / "lint.py"
BUNDLED = _BUNDLED_BASE


def test_e2e_p1_proposal_lint_pass(tmp_path, monkeypatch) -> None:
    """Stub each LLM step + run the full pipeline; verify proposal is
    auto_enable_eligible."""
    home = tmp_path / ".opensquilla"
    log_dir = home / "logs"
    synth_decision_log(log_dir, INTENT_PDF_DIGEST["co_occurrence_seed"])

    from opensquilla.skills.creator import proposer

    canned_slots = {
        "name": "synth-pdf-digest-pipeline",
        "description": "Synthetic PDF digest: extract then summarize then memorize.",
        "meta_priority": 50,
        "triggers": ["synth pdf digest"],
        "steps": [
            {"id": "extract", "skill": "pdf-toolkit", "task": "extract", "with_keys": {}},
            {"id": "digest", "skill": "summarize", "task": "summarize", "with_keys": {}},
            {"id": "save", "skill": "memory", "task": "persist", "with_keys": {}},
        ],
    }
    monkeypatch.setattr(
        proposer, "_call_llm_for_slots", lambda prompt, **_: json.dumps(canned_slots),
    )

    skill_md = proposer.meta_skill_assemble("p1_sequential", json.dumps(canned_slots))
    assert "synth-pdf-digest-pipeline" in skill_md

    proc = subprocess.run(
        [sys.executable, str(LINT), "--skill-md-stdin", "--gates", "G1,G2"],
        input=skill_md, capture_output=True, text=True, check=True,
    )
    lint_result = json.loads(proc.stdout)
    assert lint_result["G1"]["passed"]
    assert lint_result["G2"]["passed"]

    smoke_result = proposer.run_smoke_gates(
        skill_md=skill_md,
        fixture_gen_fn=lambda md, kind: {
            "positive": "please use synth pdf digest now",
            "negative": "tell me a joke unrelated",
        }[kind],
        classifier_model="stub",
    )
    assert smoke_result["G3"]["passed"]
    assert smoke_result["G4"]["passed"]

    out = subprocess.run(
        [sys.executable, str(PROPOSALS),
         "--action", "write_proposal", "--home", str(home),
         "--skill-md-inline", skill_md,
         "--lint-result", json.dumps(lint_result),
         "--smoke-result", json.dumps(smoke_result)],
        capture_output=True, text=True, check=True,
    )
    persist = json.loads(out.stdout)
    assert persist["auto_enable_eligible"] is True

    proposal_dir = home / "proposals" / persist["proposal_id"]
    assert (proposal_dir / "SKILL.md").is_file()
    assert (proposal_dir / "gates.json").is_file()


def test_manual_creator_persist_auto_enables_when_setting_is_on(tmp_path) -> None:
    """The manual meta-skill-creator persist tool should use the same
    conservative auto-enable path as cron/dream auto-propose when the
    operator has enabled it in runtime settings."""
    home = tmp_path / ".opensquilla"

    from opensquilla.skills import proposals_lib
    from opensquilla.skills.creator import proposer

    proposals_lib.write_auto_propose_settings(
        home,
        {"auto_enable": True, "auto_enable_max_risk": "low"},
    )
    skill_md = """---
name: synth-manual-auto-enable
description: "Manual creator output that is safe to auto-enable."
kind: meta
meta_priority: 50
triggers:
  - "manual auto enable"
composition:
  steps:
    - id: explore
      skill: history-explorer
      with:
        query: "{{ inputs.user_message | xml_escape | truncate(512) }}"
    - id: digest
      skill: summarize
      depends_on: [explore]
      with:
        text: "{{ outputs.explore | truncate(2000) }}"
---
"""
    lint_result = {"G1": {"passed": True}, "G2": {"passed": True}}
    smoke_result = {"G3": {"passed": True}, "G4": {"passed": True}}

    out = json.loads(proposer.meta_skill_persist_proposal(
        skill_md,
        json.dumps(lint_result),
        json.dumps(smoke_result),
        home=str(home),
    ))

    assert out["status"] == "ok"
    assert out["auto_enable"]["status"] == "enabled"
    assert out["auto_enable"]["triggered_by"] == "manual"
    assert not (home / "proposals" / out["proposal_id"]).exists()
    assert (home / "skills" / "synth-manual-auto-enable" / "SKILL.md").is_file()


async def test_orchestrator_drives_creator_dag_end_to_end(tmp_path, monkeypatch) -> None:
    """Full DAG through MetaOrchestrator with stubbed downstream runners."""
    home = tmp_path / ".opensquilla"
    log_dir = home / "logs"
    synth_decision_log(log_dir, INTENT_PDF_DIGEST["co_occurrence_seed"])
    monkeypatch.setenv("OPENSQUILLA_LOG_DIR", str(log_dir))

    loader = SkillLoader(bundled_dir=BUNDLED, snapshot_path=tmp_path / "snap.json")
    loader.invalidate_cache()
    creator_spec = loader.get_by_name("meta-skill-creator")
    assert creator_spec is not None, "meta-skill-creator not loaded; check Task 6"
    plan = parse_meta_plan(creator_spec)
    assert plan is not None

    async def stub_agent_runner(system_prompt: str, user_prompt: str):
        yield TextDeltaEvent(text="<stub:agent>")

    async def stub_llm_chat(system_prompt: str, user_prompt: str) -> str:
        return "p1_sequential"

    async def stub_tool_invoker(tool_name: str, args: dict) -> str:
        if tool_name == "meta_skill_fill_slots":
            return json.dumps({
                "name": "synth-orch-e2e", "description": "x" * 50,
                "meta_priority": 50, "triggers": ["orch e2e trigger"],
                "steps": [
                    {"id": "a", "skill": "summarize", "task": "t", "with_keys": {}},
                    {"id": "b", "skill": "memory", "task": "t", "with_keys": {}},
                ],
            })
        if tool_name == "meta_skill_assemble":
            from opensquilla.skills.creator.proposer import meta_skill_assemble
            return meta_skill_assemble(args["pattern_id"], args["slots_json"])
        return f"<stub:{tool_name}>"

    orchestrator = MetaOrchestrator(
        agent_runner=stub_agent_runner,
        skill_loader=loader,
        llm_chat=stub_llm_chat,
        tool_invoker=stub_tool_invoker,
    )
    match = MetaMatch(
        plan=plan,
        inputs={"user_message": "compose a meta-skill that does X then Y"},
    )

    final_result = None
    async for event in orchestrator.iter_events(match):
        if isinstance(event, MetaResult):
            final_result = event

    assert final_result is not None, "orchestrator did not yield a MetaResult"
    assert final_result.ok, f"orchestrator failed: {final_result.error}"
    assert set(final_result.step_outputs.keys()) >= {
        "harvest", "pick_pattern", "fill_slots", "assemble", "lint", "smoke", "persist"
    }
    # harvest now runs as skill_exec (history-explorer has an entrypoint:),
    # so it returns JSON from explore.py rather than a stub agent reply.
    harvest_output = final_result.step_outputs.get("harvest", "")
    assert harvest_output, "harvest step produced no output"
    harvest_json = json.loads(harvest_output)
    assert "co_occurrences" in harvest_json


async def test_orchestrator_p2_fan_out_merge_proposal(tmp_path, monkeypatch) -> None:
    """P2 fan-out-merge topology: two parallel branches + merge step."""
    home = tmp_path / ".opensquilla"
    log_dir = home / "logs"
    synth_decision_log(log_dir, INTENT_TRIP_PLANNER["co_occurrence_seed"])
    monkeypatch.setenv("OPENSQUILLA_LOG_DIR", str(log_dir))

    loader = SkillLoader(bundled_dir=BUNDLED, snapshot_path=tmp_path / "snap.json")
    loader.invalidate_cache()
    creator_spec = loader.get_by_name("meta-skill-creator")
    plan = parse_meta_plan(creator_spec)

    async def stub_agent_runner(system_prompt: str, user_prompt: str):
        yield TextDeltaEvent(text="<stub:agent>")

    async def stub_llm_chat(system_prompt: str, user_prompt: str) -> str:
        return "p2_fan_out_merge"

    async def stub_tool_invoker(tool_name: str, args: dict) -> str:
        if tool_name == "meta_skill_fill_slots":
            return json.dumps({
                "name": "synth-p2-trip", "description": "x" * 50,
                "meta_priority": 50, "triggers": ["synth p2 trigger"],
                "branches": [
                    {"id": "weather", "skill": "weather", "task": "w", "with_keys": {}},
                    {"id": "poi", "skill": "multi-search-engine", "task": "p", "with_keys": {}},
                ],
                "merge": {"id": "itin", "skill": "summarize", "task": "m", "with_keys": {}},
                "tail": None,
            })
        if tool_name == "meta_skill_assemble":
            from opensquilla.skills.creator.proposer import meta_skill_assemble
            return meta_skill_assemble(args["pattern_id"], args["slots_json"])
        return f"<stub:{tool_name}>"

    orchestrator = MetaOrchestrator(
        agent_runner=stub_agent_runner,
        skill_loader=loader,
        llm_chat=stub_llm_chat,
        tool_invoker=stub_tool_invoker,
    )
    match = MetaMatch(
        plan=plan,
        inputs={"user_message": "compose a trip-planner meta-skill"},
    )

    final_result = None
    async for event in orchestrator.iter_events(match):
        if isinstance(event, MetaResult):
            final_result = event

    assert final_result is not None and final_result.ok
    assemble_output = final_result.step_outputs["assemble"]
    assert "depends_on: [weather, poi]" in assemble_output
