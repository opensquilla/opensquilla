"""End-to-end tests for the experimental meta-travel-planner.

Travel planning should produce an inline itinerary in the same turn when the
request already contains enough facts. Generic user_input behavior is covered
by the dedicated clarify/resume tests; this experimental skill must not pause
on a well-specified itinerary request.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from opensquilla.skills.loader import SkillLoader
from opensquilla.skills.meta.events import _StepDone
from opensquilla.skills.meta.orchestrator import MetaOrchestrator
from opensquilla.skills.meta.parser import parse_meta_plan
from opensquilla.skills.meta.types import MetaMatch


def _load_travel_planner_plan():
    bundled = Path("src/opensquilla/skills/bundled").resolve()
    exp = Path("src/opensquilla/skills/exp").resolve()
    loader = SkillLoader(bundled_dir=bundled, extra_dirs=[exp])
    specs = [s for s in loader.load_all() if getattr(s, "kind", "") == "meta"]
    for s in specs:
        if s.name == "meta-travel-planner":
            plan = parse_meta_plan(s)
            assert plan is not None
            return plan
    raise AssertionError("meta-travel-planner not found")


async def _sv(*_a):
    return
    yield  # type: ignore[unreachable]


def test_travel_planner_starts_with_same_turn_fact_extraction() -> None:
    plan = _load_travel_planner_plan()
    steps = {step.id: step for step in plan.steps}

    assert plan.steps[0].id == "trip_collect"
    assert plan.steps[0].kind == "llm_chat"
    assert plan.steps[0].clarify_config is None
    assert steps["trip_clarify"].kind == "user_input"
    assert steps["trip_clarify"].depends_on == ("trip_collect",)
    assert steps["trip_clarify"].when == (
        "'NEEDS_CLARIFICATION: yes' in outputs.trip_collect"
    )

    collect_prompt = str(steps["trip_collect"].with_args)
    assert "Do NOT ask the user to confirm details" in collect_prompt
    assert "safely inferable" in collect_prompt
    assert "ASSUMPTIONS" in collect_prompt
    assert "Original user request" in collect_prompt


@pytest.mark.asyncio
async def test_travel_planner_runs_to_final_plan_without_pause() -> None:
    plan = _load_travel_planner_plan()
    orch = MetaOrchestrator(
        agent_runner=None,
        skill_loader=None,
        dao=None,  # type: ignore[arg-type]
    )
    seen: list[str] = []
    observed: dict[str, object] = {}

    async def _dispatch(step, effective_skill, match_inputs, outputs):
        seen.append(step.id)
        if step.id == "trip_preferences":
            observed["trip_preferences_inputs"] = dict(match_inputs)
            observed["trip_collect_output"] = outputs.get("trip_collect")
        yield _StepDone(text=f"{step.id}-stub", status="ok")

    result = await orch.run_once(
        MetaMatch(
            plan=plan,
            inputs={
                "user_message": (
                    "Build a balanced 3-day Tokyo trip for two in late June "
                    "with food, transit grouping, rain backups, variants, and "
                    "moderate budget notes."
                )
            },
        ),
        run_id=None,
        session_id="S1",
        dispatch_step_stream=_dispatch,
        yield_skill_view_preface=_sv,
    )

    assert result.paused is False
    assert result.ok is True
    assert result.final_text == "final_plan-stub"
    assert seen[:2] == ["trip_collect", "trip_preferences"]
    assert {"weather", "poi"} <= set(seen[2:4])
    assert seen[-3:] == ["constraints", "itinerary", "final_plan"]
    assert observed["trip_collect_output"] == "trip_collect-stub"
    assert "Tokyo" in observed["trip_preferences_inputs"]["user_message"]
