"""End-to-end: creator pipeline tests (components + orchestrator-driven)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from creator_fixtures import (
    INTENT_PDF_DIGEST,
    INTENT_TRIP_PLANNER,
    synth_decision_log,
)

REPO = Path(__file__).resolve().parents[2]
PROPOSALS = (
    REPO / "src" / "opensquilla" / "skills" / "bundled"
    / "meta-skill-proposals" / "scripts" / "proposals.py"
)
_LINT_SCRIPT = (
    REPO / "src" / "opensquilla" / "skills" / "bundled"
    / "meta-skill-linter" / "scripts" / "lint.py"
)


def test_e2e_p1_proposal_lint_pass(tmp_path, monkeypatch) -> None:
    """Components integration: assemble + lint + smoke + persist work together."""
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
        [sys.executable, str(_LINT_SCRIPT), "--skill-md-stdin", "--gates", "G1,G2"],
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
        [
            sys.executable, str(PROPOSALS),
            "--action", "write_proposal",
            "--home", str(home),
            "--skill-md-inline", skill_md,
            "--lint-result", json.dumps(lint_result),
            "--smoke-result", json.dumps(smoke_result),
        ],
        capture_output=True, text=True, check=True,
    )
    persist = json.loads(out.stdout)
    assert persist["auto_enable_eligible"] is True

    proposal_dir = home / "proposals" / persist["proposal_id"]
    assert (proposal_dir / "SKILL.md").is_file()
    assert (proposal_dir / "gates.json").is_file()


async def test_orchestrator_drives_creator_dag_end_to_end(tmp_path, monkeypatch) -> None:
    """Full DAG through MetaOrchestrator with stubbed runners. Verifies
    topology + Jinja var rendering + tool_call/skill_exec/llm_classify dispatch."""

    from opensquilla.engine.types import DoneEvent, TextDeltaEvent
    from opensquilla.skills.loader import SkillLoader
    from opensquilla.skills.meta.orchestrator import MetaOrchestrator
    from opensquilla.skills.meta.parser import parse_meta_plan
    from opensquilla.skills.meta.types import MetaMatch, MetaResult

    home = tmp_path / ".opensquilla"
    log_dir = home / "logs"
    synth_decision_log(log_dir, INTENT_PDF_DIGEST["co_occurrence_seed"])
    monkeypatch.setenv("OPENSQUILLA_LOG_DIR", str(log_dir))

    bundled = REPO / "src" / "opensquilla" / "skills" / "bundled"
    loader = SkillLoader(bundled_dir=bundled, snapshot_path=tmp_path / "snap.json")
    loader.invalidate_cache()
    creator_spec = loader.get_by_name("meta-skill-creator")
    assert creator_spec is not None
    plan = parse_meta_plan(creator_spec)
    assert plan is not None

    # agent_runner: yields TextDeltaEvent + DoneEvent (DoneEvent suppressed by executor)
    async def stub_agent_runner(system_prompt: str, user_message: str):
        yield TextDeltaEvent(text="<stub:agent>")
        yield DoneEvent()

    # llm_chat: (system_prompt, user_message) -> label
    async def stub_llm_chat(system_prompt: str, user_message: str) -> str:
        return "p1_sequential"

    # tool_invoker: (tool_name, args_dict) -> str
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

    # MetaOrchestrator requires skill_loader as 2nd positional arg
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

    assert final_result is not None
    assert final_result.ok, f"orchestrator failed: {final_result.error}"
    assert set(final_result.step_outputs.keys()) >= {
        "harvest", "pick_pattern", "fill_slots", "assemble", "lint", "smoke", "persist"
    }


async def test_orchestrator_p2_fan_out_merge_proposal(tmp_path, monkeypatch) -> None:
    """P2 path: same orchestrator-driven flow but pick_pattern returns p2."""

    from opensquilla.engine.types import DoneEvent, TextDeltaEvent
    from opensquilla.skills.loader import SkillLoader
    from opensquilla.skills.meta.orchestrator import MetaOrchestrator
    from opensquilla.skills.meta.parser import parse_meta_plan
    from opensquilla.skills.meta.types import MetaMatch, MetaResult

    home = tmp_path / ".opensquilla"
    log_dir = home / "logs"
    synth_decision_log(log_dir, INTENT_TRIP_PLANNER["co_occurrence_seed"])
    monkeypatch.setenv("OPENSQUILLA_LOG_DIR", str(log_dir))

    bundled = REPO / "src" / "opensquilla" / "skills" / "bundled"
    loader = SkillLoader(bundled_dir=bundled, snapshot_path=tmp_path / "snap.json")
    loader.invalidate_cache()
    creator_spec = loader.get_by_name("meta-skill-creator")
    plan = parse_meta_plan(creator_spec)

    async def stub_agent_runner(system_prompt: str, user_message: str):
        yield TextDeltaEvent(text="<stub:agent>")
        yield DoneEvent()

    async def stub_llm_chat(system_prompt: str, user_message: str) -> str:
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
    # P2 produces branches and a merge step with depends_on
    assert "depends_on:" in assemble_output
    assert "weather" in assemble_output and "poi" in assemble_output
