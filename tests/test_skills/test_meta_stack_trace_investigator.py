"""Tests for meta-stack-trace-investigator (Round-2 fan-out + fan-in).

Single parse → parallel investigations (repo grep + GH issues + git log +
skill-context checks + memory) → fan-in root-cause synthesis → persist.
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
_EXP = Path(__file__).resolve().parents[2] / "src" / "opensquilla" / "skills" / "exp"


def _bundle_loader(tmp_path: Path) -> SkillLoader:
    loader = SkillLoader(
        bundled_dir=_BUNDLED,
        extra_dirs=[_EXP],
        snapshot_path=tmp_path / "snap.json",
    )
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
    # trace_collect extracts the investigation brief from the same turn so a
    # pasted traceback does not pause for a confirmation form. Newly-added
    # *_degraded fallback siblings
    # (grep_repo_degraded, search_issues_degraded, git_history_degraded,
    # memory_recall_degraded) make the previous evidence-source order
    # explicit; they were present in the SKILL.md before this migration
    # but missing from this list.
    assert step_ids == [
        "trace_collect",
        "parse_trace",
        "grep_repo",
        "grep_repo_degraded",
        "search_issues",
        "search_issues_degraded",
        "git_history",
        "git_history_degraded",
        "diff_context",
        "diff_context_degraded",
        "history_patterns",
        "history_patterns_degraded",
        "memory_recall",
        "memory_recall_degraded",
        "language_probe",
        "root_cause",
        "repro_suggestion",
        "degraded_summary",
        "persist",
    ]

    by_id = {s.id: s for s in plan.steps}
    assert by_id["trace_collect"].kind == "llm_chat"
    assert by_id["parse_trace"].depends_on == ("trace_collect",)
    assert by_id["diff_context"].on_failure == "diff_context_degraded"
    assert by_id["diff_context_degraded"].depends_on == ()
    assert by_id["history_patterns"].on_failure == "history_patterns_degraded"
    assert by_id["history_patterns_degraded"].depends_on == ()
    # Investigations each fan out from parse_trace (parallel).
    for inv in (
        "grep_repo",
        "search_issues",
        "git_history",
        "diff_context",
        "history_patterns",
        "memory_recall",
        "language_probe",
    ):
        assert by_id[inv].depends_on == ("parse_trace",), (
            f"investigation {inv} should fan out only from parse_trace"
        )
    # root_cause gathers all investigations.
    assert set(by_id["root_cause"].depends_on) == {
        "grep_repo",
        "search_issues",
        "git_history",
        "diff_context",
        "history_patterns",
        "memory_recall",
        "language_probe",
    }
    assert by_id["repro_suggestion"].depends_on == ("root_cause",)
    assert set(by_id["degraded_summary"].depends_on) == {
        "grep_repo",
        "search_issues",
        "git_history",
        "diff_context",
        "history_patterns",
        "memory_recall",
        "language_probe",
        "repro_suggestion",
    }
    assert by_id["persist"].depends_on == ("degraded_summary",)
    assert plan.final_text_mode == "step:degraded_summary"


def test_language_probe_routes_to_language_specific_skills(tmp_path: Path) -> None:
    loader = _bundle_loader(tmp_path)
    spec = loader.get_by_name("meta-stack-trace-investigator")
    assert spec is not None
    plan = parse_meta_plan(spec)
    assert plan is not None

    by_id = {s.id: s for s in plan.steps}
    probe = by_id["language_probe"]
    assert probe.kind == "agent"
    assert probe.skill == "stack-trace-generic-probe"
    assert probe.depends_on == ("parse_trace",)
    assert [(case.when, case.to) for case in probe.route] == [
        (
            "'\"language\":\"python\"' in outputs.parse_trace or "
            "'\"language\": \"python\"' in outputs.parse_trace or "
            "'LANGUAGE: python' in outputs.trace_collect",
            "stack-trace-python-probe",
        ),
        (
            "'\"language\":\"javascript\"' in outputs.parse_trace or "
            "'\"language\": \"javascript\"' in outputs.parse_trace or "
            "'\"language\":\"typescript\"' in outputs.parse_trace or "
            "'\"language\": \"typescript\"' in outputs.parse_trace or "
            "'LANGUAGE: javascript' in outputs.trace_collect or "
            "'LANGUAGE: typescript' in outputs.trace_collect",
            "stack-trace-js-probe",
        ),
        (
            "'\"language\":\"go\"' in outputs.parse_trace or "
            "'\"language\": \"go\"' in outputs.parse_trace or "
            "'LANGUAGE: go' in outputs.trace_collect",
            "stack-trace-go-probe",
        ),
        (
            "'\"language\":\"rust\"' in outputs.parse_trace or "
            "'\"language\": \"rust\"' in outputs.parse_trace or "
            "'LANGUAGE: rust' in outputs.trace_collect",
            "stack-trace-rust-probe",
        ),
    ]
    for name in {
        "stack-trace-generic-probe",
        "stack-trace-python-probe",
        "stack-trace-js-probe",
        "stack-trace-go-probe",
        "stack-trace-rust-probe",
    }:
        routed_spec = loader.get_by_name(name)
        assert routed_spec is not None, f"missing routed skill {name}"
        assert routed_spec.kind == "skill"


def _classify(system: str, user_message: str) -> str:
    if "Extract a compact investigation brief" in user_message:
        return "trace_collect"
    if "trace parser" in user_message:
        return "parse_trace"
    if "Classify the stack trace language" in user_message:
        return "classify_language"
    if "Search the current working-directory repository" in user_message:
        return "grep_repo"
    if "Search this project's GitHub repository" in user_message:
        return "search_issues"
    if "List recent commits" in user_message:
        return "git_history"
    if "Tool: exec_command" in user_message and "parse_tool_result|run_step" in user_message:
        return "grep_repo"
    if "Tool: exec_command" in user_message and "gh issue list" in user_message:
        return "search_issues"
    if "Tool: exec_command" in user_message and "git log" in user_message:
        return "git_history"
    if "Tool: memory_search" in user_message:
        return "memory_recall"
    if "Tool: memory_save" in user_message:
        return "persist"
    if "Run a language-specific stack-trace probe" in user_message:
        return "language_probe"
    # memory skill (action=search or action=save): runs as agent skill.
    # The first memory step uses action=search (memory_recall), the second
    # uses action=save (persist). Distinguish by content presence.
    if "action: save" in user_message or "action=save" in user_message:
        return "persist"
    if "Synthesize a root-cause hypothesis" in user_message:
        return "root_cause"
    if "Propose the smallest safe verification" in user_message:
        return "repro_suggestion"
    if "Produce the final user-facing investigation" in user_message:
        return "degraded_summary"
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
        if which == "trace_collect":
            yield TextDeltaEvent(
                text=(
                    "LANGUAGE: python\n"
                    "EXPECTED_BEHAVIOR: ASSUMED: not provided\n"
                    "RECENT_CHANGES: ASSUMED: not provided\n"
                    "TRACE_PRESENT: yes\n"
                    "PRIMARY_EXCEPTION: AttributeError\n"
                    "PRIMARY_FILES:\n"
                    "  - src/opensquilla/engine/agent.py:1234"
                )
            )
        elif which == "classify_language":
            yield TextDeltaEvent(
                text='{"language":"python","runtime":"cpython","confidence":"high"}'
            )
        elif which == "parse_trace":
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
        elif which == "language_probe":
            yield TextDeltaEvent(
                text=(
                    "LANGUAGE_PROBE: python\n"
                    "CHECKS:\n  - KeyError/None contract\n"
                    "VERIFY:\n  - python -m pytest tests/test_agent.py -k tool"
                )
            )
        elif which == "root_cause":
            yield TextDeltaEvent(
                text=(
                    "ROOT_CAUSE: handler returned None for some branch\n"
                    "EVIDENCE:\n  - grep: agent.py:1230\n"
                    "SUGGESTIONS:\n  - agent.py:1234 — guard None return"
                ),
            )
        elif which == "repro_suggestion":
            yield TextDeltaEvent(
                text=(
                    "CONFIDENCE: high\n"
                    "VERIFY:\n  - python -m pytest tests/test_agent.py -k tool\n"
                    "FIX_FIRST:\n  - src/opensquilla/engine/agent.py: guard None return"
                )
            )
        elif which == "degraded_summary":
            yield TextDeltaEvent(
                text=(
                    "## Diagnosis\nhandler returned None\n"
                    "## Evidence Status\nrepo evidence present\n"
                    "## Verification Commands\npython -m pytest tests/test_agent.py"
                )
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
    assert result.final_text.startswith("## Diagnosis")
    assert "memory record saved" not in result.final_text


@pytest.mark.asyncio
async def test_root_cause_fans_in_parallel_investigations(tmp_path: Path) -> None:
    """Verify root_cause prompt embeds output from all 4 investigations
    by checking the rendered task body contains each upstream marker."""
    loader = _bundle_loader(tmp_path)
    spec = loader.get_by_name("meta-stack-trace-investigator")
    plan = parse_meta_plan(spec)
    assert plan is not None

    captured_root_cause_prompt: dict[str, str] = {}

    async def runner(_system: str, user_msg: str) -> AsyncIterator[AgentEvent]:
        which = _classify(_system, user_msg)
        if which == "trace_collect":
            yield TextDeltaEvent(text="LANGUAGE: python\nPRIMARY_EXCEPTION: RuntimeError")
        elif which == "parse_trace":
            yield TextDeltaEvent(text="<<PARSE_RESULT>>")
        elif which == "classify_language":
            yield TextDeltaEvent(text="<<CLASSIFY_RESULT>>")
        elif which == "grep_repo":
            yield TextDeltaEvent(text="<<GREP_HIT>>")
        elif which == "search_issues":
            yield TextDeltaEvent(text="<<ISSUE_HIT>>")
        elif which == "git_history":
            yield TextDeltaEvent(text="<<COMMIT_HIT>>")
        elif which == "memory_recall":
            yield TextDeltaEvent(text="<<MEMORY_HIT>>")
        elif which == "language_probe":
            yield TextDeltaEvent(text="<<LANGUAGE_PROBE>>")
        elif which == "root_cause":
            captured_root_cause_prompt["body"] = user_msg
            yield TextDeltaEvent(text="ROOT_CAUSE: ok")
        elif which == "repro_suggestion":
            yield TextDeltaEvent(text="CONFIDENCE: medium")
        elif which == "degraded_summary":
            yield TextDeltaEvent(text="## Diagnosis\nok")
        else:
            yield TextDeltaEvent(text="saved")
        yield DoneEvent(text="")

    orch = MetaOrchestrator(agent_runner=runner, skill_loader=loader)
    result = await orch.run(
        MetaMatch(
            plan=plan,
            inputs={
                "user_message": "investigate stack trace",
            },
        ),
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
        "<<LANGUAGE_PROBE>>",
    ):
        assert sentinel in body, f"root_cause prompt missing upstream {sentinel}"
