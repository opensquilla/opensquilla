"""Tests for the step-level ``on_failure`` substitute pattern (Step A.3).

Covers:

* Parser
    - Accepts ``on_failure`` pointing to a valid step in the same plan.
    - Default for omitted ``on_failure`` is the empty string.
    - Rejects ``on_failure`` pointing to an unknown step.
    - Rejects ``on_failure`` pointing to the step itself.
    - Rejects chained fallbacks (substitute may not itself have
      ``on_failure``) — minimum subset constraint.

* Scheduler / orchestrator
    - When the original step fails, the named substitute runs and its
      output is mirrored into ``outputs[<original>.id]`` so downstream
      ``depends_on`` links remain satisfied.
    - When the substitute ALSO fails, the plan fails normally (no
      cascade beyond the substitute).
    - When the original step succeeds, the substitute is never run.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from opensquilla.engine.types import (
    AgentEvent,
    DoneEvent,
    TextDeltaEvent,
)
from opensquilla.skills.meta.orchestrator import MetaOrchestrator
from opensquilla.skills.meta.parser import MetaPlanError, parse_meta_plan
from opensquilla.skills.meta.types import MetaMatch, MetaResult
from opensquilla.skills.types import SkillLayer, SkillSpec

# ---------------------------------------------------------------------------
# Helpers (mirrors the patterns used in test_meta_parallel.py)
# ---------------------------------------------------------------------------


def _meta_spec(steps: list[dict[str, Any]]) -> SkillSpec:
    return SkillSpec(
        name="meta-test",
        description="t",
        layer=SkillLayer.BUNDLED,
        always=False,
        triggers=["t"],
        content="fallback",
        kind="meta",
        composition_raw={"steps": steps},
    )


def _skill(name: str) -> SkillSpec:
    return SkillSpec(
        name=name,
        description=f"{name} d",
        layer=SkillLayer.BUNDLED,
        always=False,
        triggers=[],
        content=name.upper(),
        kind="skill",
    )


class _FakeLoader:
    def __init__(self, specs: list[SkillSpec]) -> None:
        self._by_name = {s.name: s for s in specs}

    def get_by_name(self, name: str) -> SkillSpec | None:
        return self._by_name.get(name)


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


def test_parse_on_failure_to_valid_step() -> None:
    spec = _meta_spec(
        [
            {"id": "step_a", "skill": "skill_a", "on_failure": "step_b"},
            {"id": "step_b", "skill": "skill_b"},
        ],
    )
    plan = parse_meta_plan(spec)
    assert plan is not None
    assert plan.steps[0].on_failure == "step_b"
    assert plan.steps[1].on_failure == ""


def test_parse_on_failure_to_unknown_step_raises() -> None:
    spec = _meta_spec(
        [
            {"id": "step_a", "skill": "skill_a", "on_failure": "ghost"},
        ],
    )
    with pytest.raises(MetaPlanError, match="is not a step in this plan"):
        parse_meta_plan(spec)


def test_parse_on_failure_self_loop_raises() -> None:
    spec = _meta_spec(
        [
            {"id": "step_a", "skill": "skill_a", "on_failure": "step_a"},
        ],
    )
    with pytest.raises(MetaPlanError, match="cannot target itself"):
        parse_meta_plan(spec)


def test_parse_on_failure_chained_raises() -> None:
    spec = _meta_spec(
        [
            {"id": "step_a", "skill": "skill_a", "on_failure": "step_b"},
            {"id": "step_b", "skill": "skill_b", "on_failure": "step_c"},
            {"id": "step_c", "skill": "skill_c"},
        ],
    )
    with pytest.raises(MetaPlanError, match="may not have its own on_failure"):
        parse_meta_plan(spec)


def test_parse_default_on_failure_empty_string() -> None:
    spec = _meta_spec(
        [
            {"id": "step_a", "skill": "skill_a"},
        ],
    )
    plan = parse_meta_plan(spec)
    assert plan is not None
    assert plan.steps[0].on_failure == ""


def test_parse_on_failure_non_string_raises() -> None:
    spec = _meta_spec(
        [
            {"id": "step_a", "skill": "skill_a", "on_failure": 42},
            {"id": "step_b", "skill": "skill_b"},
        ],
    )
    with pytest.raises(MetaPlanError, match="on_failure"):
        parse_meta_plan(spec)


def test_parse_on_failure_shared_substitute_raises() -> None:
    """Two distinct primaries cannot both point at the same substitute —
    concurrent failovers would overwrite the alias and strand one parent."""
    spec = _meta_spec(
        [
            {"id": "step_a", "skill": "skill_a", "on_failure": "shared_fb"},
            {"id": "step_b", "skill": "skill_b", "on_failure": "shared_fb"},
            {"id": "shared_fb", "skill": "skill_fb"},
        ],
    )
    with pytest.raises(MetaPlanError, match="may only be referenced by one primary"):
        parse_meta_plan(spec)


def test_parse_on_failure_substitute_with_depends_on_raises() -> None:
    """A substitute step must not declare its own depends_on — the
    scheduler force-clears its pending deps on failover, so honouring
    them would require a more elaborate semantic."""
    spec = _meta_spec(
        [
            {"id": "setup", "skill": "skill_setup"},
            {"id": "step_a", "skill": "skill_a", "on_failure": "step_a_fb"},
            {
                "id": "step_a_fb",
                "skill": "skill_a_fb",
                "depends_on": ["setup"],
            },
        ],
    )
    with pytest.raises(MetaPlanError, match="must not declare depends_on"):
        parse_meta_plan(spec)


# ---------------------------------------------------------------------------
# Scheduler / orchestrator integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failover_triggers_substitute_and_mirrors_output() -> None:
    """A fails → A_fallback runs and its output is mirrored to outputs[A].

    Downstream step C depends on A; after failover, C must observe the
    substitute's output via outputs[A] and run to completion.
    """

    spec = _meta_spec(
        [
            {"id": "A", "skill": "skill_a", "on_failure": "A_fallback"},
            {"id": "A_fallback", "skill": "skill_a_fb"},
            {"id": "C", "skill": "skill_c", "depends_on": ["A"]},
        ],
    )
    plan = parse_meta_plan(spec)
    assert plan is not None

    async def runner(system_prompt: str, _u: str) -> AsyncIterator[AgentEvent]:
        if "SKILL_A_FB" in system_prompt:
            yield TextDeltaEvent(text="from-fallback")
            yield DoneEvent(text="")
            return
        if "SKILL_A" in system_prompt:
            raise RuntimeError("primary A failed")
        if "SKILL_C" in system_prompt:
            yield TextDeltaEvent(text="C-output")
            yield DoneEvent(text="")
            return
        yield DoneEvent(text="")

    orch = MetaOrchestrator(
        agent_runner=runner,
        skill_loader=_FakeLoader(
            [_skill("skill_a"), _skill("skill_a_fb"), _skill("skill_c")],
        ),
    )

    final: MetaResult | None = None
    async for ev in orch.iter_events(MetaMatch(plan=plan, inputs={})):
        if isinstance(ev, MetaResult):
            final = ev

    assert final is not None, "no MetaResult produced"
    assert final.ok is True, f"expected ok=True, got error={final.error}"
    assert final.step_outputs.get("A") == "from-fallback"
    assert final.step_outputs.get("A_fallback") == "from-fallback"
    assert final.step_outputs.get("C") == "C-output"


@pytest.mark.asyncio
async def test_failover_substitute_also_fails_propagates_plan_failure() -> None:
    """If the substitute fails too, the whole plan fails (no further cascade)."""

    spec = _meta_spec(
        [
            {"id": "A", "skill": "skill_a", "on_failure": "A_fallback"},
            {"id": "A_fallback", "skill": "skill_a_fb"},
        ],
    )
    plan = parse_meta_plan(spec)
    assert plan is not None

    async def runner(system_prompt: str, _u: str) -> AsyncIterator[AgentEvent]:
        if "SKILL_A_FB" in system_prompt:
            raise RuntimeError("substitute also failed")
        if "SKILL_A" in system_prompt:
            raise RuntimeError("primary A failed")
        yield DoneEvent(text="")

    orch = MetaOrchestrator(
        agent_runner=runner,
        skill_loader=_FakeLoader(
            [_skill("skill_a"), _skill("skill_a_fb")],
        ),
    )

    final: MetaResult | None = None
    async for ev in orch.iter_events(MetaMatch(plan=plan, inputs={})):
        if isinstance(ev, MetaResult):
            final = ev

    assert final is not None
    assert final.ok is False
    # The substitute is the step that ultimately failed unrecoverably,
    # so the scheduler reports its id (not the original primary's).
    assert final.failed_step_id == "A_fallback"
    assert final.error is not None
    assert final.error  # non-empty


@pytest.mark.asyncio
async def test_no_failover_when_step_succeeds() -> None:
    """If A succeeds, A_fallback must not run."""

    spec = _meta_spec(
        [
            {"id": "A", "skill": "skill_a", "on_failure": "A_fallback"},
            {"id": "A_fallback", "skill": "skill_a_fb"},
        ],
    )
    plan = parse_meta_plan(spec)
    assert plan is not None

    fallback_ran = False

    async def runner(system_prompt: str, _u: str) -> AsyncIterator[AgentEvent]:
        nonlocal fallback_ran
        if "SKILL_A_FB" in system_prompt:
            fallback_ran = True
            yield TextDeltaEvent(text="from-fallback")
            yield DoneEvent(text="")
            return
        if "SKILL_A" in system_prompt:
            yield TextDeltaEvent(text="A-output")
            yield DoneEvent(text="")
            return
        yield DoneEvent(text="")

    orch = MetaOrchestrator(
        agent_runner=runner,
        skill_loader=_FakeLoader(
            [_skill("skill_a"), _skill("skill_a_fb")],
        ),
    )

    final: MetaResult | None = None
    async for ev in orch.iter_events(MetaMatch(plan=plan, inputs={})):
        if isinstance(ev, MetaResult):
            final = ev

    assert final is not None
    assert final.ok is True
    assert fallback_ran is False
    assert final.step_outputs.get("A") == "A-output"
    # A_fallback must not appear in outputs (it was never spawned).
    assert "A_fallback" not in final.step_outputs
