"""Tests for meta-stack-trace-investigator (Round-2 fan-out + fan-in).

Single parse → 4 parallel investigations (grep + GH issues + git log +
memory) → fan-in root-cause synthesis → persist.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from opensquilla.engine.types import AgentEvent, DoneEvent, TextDeltaEvent
from opensquilla.skills.loader import SkillLoader
from opensquilla.skills.meta.orchestrator import MetaOrchestrator
from opensquilla.skills.meta.parser import parse_meta_plan
from opensquilla.skills.meta.types import MetaMatch

_BUNDLED = (
    Path(__file__).resolve().parents[2] / "src" / "opensquilla" / "skills" / "bundled"
)


def _bundle_loader(tmp_path: Path) -> SkillLoader:
    loader = SkillLoader(bundled_dir=_BUNDLED, snapshot_path=tmp_path / "snap.json")
    loader.invalidate_cache()
    loader.load_all()
    return loader


def test_parses_with_expected_topology(tmp_path: Path) -> None:
    loader = _bundle_loader(tmp_path)
    spec = loader.get_by_name("meta-stack-trace-investigator")
    assert spec is not None
    plan = parse_meta_plan(spec)
    assert plan is not None

    step_ids = [s.id for s in plan.steps]
    assert step_ids == [
        "parse_trace",
        "grep_repo",
        "search_issues",
        "git_history",
        "memory_recall",
        "root_cause",
        "persist",
    ]

    by_id = {s.id: s for s in plan.steps}
    # 4 investigations each fan out from parse_trace (parallel).
    for inv in ("grep_repo", "search_issues", "git_history", "memory_recall"):
        assert by_id[inv].depends_on == ("parse_trace",), (
            f"investigation {inv} should fan out only from parse_trace"
        )
    # root_cause gathers all 4.
    assert set(by_id["root_cause"].depends_on) == {
        "grep_repo",
        "search_issues",
        "git_history",
        "memory_recall",
    }
    assert by_id["persist"].depends_on == ("root_cause",)


def _classify(system: str, user_message: str) -> str:
    if "trace parser" in user_message:
        return "parse_trace"
    if "Search the current working-directory repository" in user_message:
        return "grep_repo"
    if "Search this project's GitHub repository" in user_message:
        return "search_issues"
    if "List recent commits" in user_message:
        return "git_history"
    # memory skill (action=search or action=save): runs as agent skill.
    # The first memory step uses action=search (memory_recall), the second
    # uses action=save (persist). Distinguish by content presence.
    if "action: save" in user_message or "action=save" in user_message:
        return "persist"
    if "Synthesize a root-cause hypothesis" in user_message:
        return "root_cause"
    if "action: search" in user_message or "action=search" in user_message:
        return "memory_recall"
    # Memory skill sub-Agent could also come in via its system prompt; just
    # treat any unmatched call as "memory" (returns canned recall).
    if "memory" in (system or "").lower():
        return "memory_recall"
    return "other"


@pytest.mark.asyncio
async def test_happy_path_synthesizes_root_cause(tmp_path: Path) -> None:
    loader = _bundle_loader(tmp_path)
    spec = loader.get_by_name("meta-stack-trace-investigator")
    plan = parse_meta_plan(spec)
    assert plan is not None

    canned_parse = (
        '{"exception_class":"AttributeError",'
        '"exception_message":"NoneType has no attribute foo",'
        '"primary_file":"src/opensquilla/engine/agent.py",'
        '"primary_line":1234,'
        '"symbols":["_run_one_streaming","handle_tool"]}'
    )

    async def runner(_system: str, user_msg: str) -> AsyncIterator[AgentEvent]:
        which = _classify(_system, user_msg)
        if which == "parse_trace":
            yield TextDeltaEvent(text=canned_parse)
        elif which == "grep_repo":
            yield TextDeltaEvent(
                text="src/opensquilla/engine/agent.py:1230: def _run_one_streaming(...)",
            )
        elif which == "search_issues":
            yield TextDeltaEvent(text="#42 AttributeError in agent loop (closed)")
        elif which == "git_history":
            yield TextDeltaEvent(text="a3f7c2 2026-05-20 fix: stream agent events")
        elif which == "memory_recall":
            yield TextDeltaEvent(text="NO_PRIOR_INCIDENTS")
        elif which == "root_cause":
            yield TextDeltaEvent(
                text=(
                    "ROOT_CAUSE: handler returned None for some branch\n"
                    "EVIDENCE:\n  - grep: agent.py:1230\n"
                    "SUGGESTIONS:\n  - agent.py:1234 — guard None return"
                ),
            )
        else:
            yield TextDeltaEvent(text="memory record saved")
        yield DoneEvent(text="")

    orch = MetaOrchestrator(agent_runner=runner, skill_loader=loader)
    result = await orch.run(
        MetaMatch(
            plan=plan,
            inputs={
                "user_message": (
                    "investigate stack trace:\n"
                    "Traceback (most recent call last):\n"
                    "  File \"src/opensquilla/engine/agent.py\", line 1234, in foo\n"
                    "AttributeError: 'NoneType' object has no attribute 'foo'"
                ),
            },
        ),
    )
    assert result.ok, f"plan failed: {result.error}"
    assert "ROOT_CAUSE" in result.step_outputs["root_cause"]
    assert "AttributeError" in result.step_outputs["parse_trace"]


@pytest.mark.asyncio
async def test_root_cause_fans_in_all_four(tmp_path: Path) -> None:
    """Verify root_cause prompt embeds output from all 4 investigations
    by checking the rendered task body contains each upstream marker."""
    loader = _bundle_loader(tmp_path)
    spec = loader.get_by_name("meta-stack-trace-investigator")
    plan = parse_meta_plan(spec)
    assert plan is not None

    captured_root_cause_prompt: dict[str, str] = {}

    async def runner(_system: str, user_msg: str) -> AsyncIterator[AgentEvent]:
        which = _classify(_system, user_msg)
        if which == "parse_trace":
            yield TextDeltaEvent(text="<<PARSE_RESULT>>")
        elif which == "grep_repo":
            yield TextDeltaEvent(text="<<GREP_HIT>>")
        elif which == "search_issues":
            yield TextDeltaEvent(text="<<ISSUE_HIT>>")
        elif which == "git_history":
            yield TextDeltaEvent(text="<<COMMIT_HIT>>")
        elif which == "memory_recall":
            yield TextDeltaEvent(text="<<MEMORY_HIT>>")
        elif which == "root_cause":
            captured_root_cause_prompt["body"] = user_msg
            yield TextDeltaEvent(text="ROOT_CAUSE: ok")
        else:
            yield TextDeltaEvent(text="saved")
        yield DoneEvent(text="")

    orch = MetaOrchestrator(agent_runner=runner, skill_loader=loader)
    result = await orch.run(
        MetaMatch(plan=plan, inputs={"user_message": "investigate stack trace"}),
    )
    assert result.ok
    body = captured_root_cause_prompt["body"]
    # Fan-in evidence: each upstream sentinel is embedded.
    for sentinel in (
        "<<PARSE_RESULT>>",
        "<<GREP_HIT>>",
        "<<ISSUE_HIT>>",
        "<<COMMIT_HIT>>",
        "<<MEMORY_HIT>>",
    ):
        assert sentinel in body, f"root_cause prompt missing upstream {sentinel}"
