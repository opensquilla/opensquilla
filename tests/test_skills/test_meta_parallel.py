"""DAG-parallelism contract tests for MetaOrchestrator (M7).

Three contracts:
1. Two steps with disjoint depends_on run concurrently — their
   ToolUseStartEvents both arrive before either's ToolResultEvent.
2. When one step in a parallel batch fails, the sibling task is
   cancelled — its ToolResultEvent never arrives.
3. A purely-linear DAG keeps the same event order as the old
   linear-topo scheduler (backwards compat).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from opensquilla.engine.types import (
    AgentEvent,
    DoneEvent,
    TextDeltaEvent,
    ToolResultEvent,
    ToolUseStartEvent,
)
from opensquilla.skills.meta.orchestrator import MetaOrchestrator
from opensquilla.skills.meta.parser import parse_meta_plan
from opensquilla.skills.meta.types import MetaMatch, MetaResult
from opensquilla.skills.types import SkillLayer, SkillSpec


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


@pytest.mark.asyncio
async def test_independent_steps_run_concurrently() -> None:
    """Two steps with no deps both start before either finishes."""
    spec = _meta_spec(
        [
            {"id": "a", "skill": "skill_a", "with": {}},
            {"id": "b", "skill": "skill_b", "with": {}},  # no depends_on
        ],
    )
    plan = parse_meta_plan(spec)
    assert plan is not None

    started = asyncio.Event()
    second_started_first = asyncio.Event()

    async def runner(system_prompt: str, _u: str) -> AsyncIterator[AgentEvent]:
        # First runner blocks until the second has also started — proves
        # they overlap. With a serial scheduler this hangs forever.
        if "SKILL_A" in system_prompt:
            started.set()
            await asyncio.wait_for(second_started_first.wait(), timeout=2.0)
            yield TextDeltaEvent(text="A done")
        else:
            await asyncio.wait_for(started.wait(), timeout=2.0)
            second_started_first.set()
            yield TextDeltaEvent(text="B done")
        yield DoneEvent(text="")

    orch = MetaOrchestrator(
        agent_runner=runner,
        skill_loader=_FakeLoader([_skill("skill_a"), _skill("skill_b")]),
    )

    starts: list[str] = []
    results: list[str] = []
    final: MetaResult | None = None
    async for ev in orch.iter_events(MetaMatch(plan=plan, inputs={})):
        if isinstance(ev, MetaResult):
            final = ev
        elif isinstance(ev, ToolUseStartEvent) and ev.tool_name.startswith("meta-step:"):
            starts.append(ev.tool_name)
        elif isinstance(ev, ToolResultEvent) and ev.tool_name.startswith("meta-step:"):
            results.append(ev.tool_name)

    assert final is not None and final.ok, final.error if final else "no final"
    # Both starts must arrive before either result.
    assert set(starts) == {"meta-step:a", "meta-step:b"}
    assert set(results) == {"meta-step:a", "meta-step:b"}
    # In the linear scheduler, starts[0] would always produce results[0]
    # before starts[1]. The parallel scheduler interleaves them, which we
    # already proved by the asyncio.Event coupling above — if we got here
    # without TimeoutError, the steps ran concurrently.


@pytest.mark.asyncio
async def test_failing_step_cancels_sibling() -> None:
    """When one parallel step raises, the sibling task is cancelled."""
    spec = _meta_spec(
        [
            {"id": "a", "skill": "skill_a", "with": {}},
            {"id": "b", "skill": "skill_b", "with": {}},
        ],
    )
    plan = parse_meta_plan(spec)
    assert plan is not None

    sibling_completed = False

    async def runner(system_prompt: str, _u: str) -> AsyncIterator[AgentEvent]:
        nonlocal sibling_completed
        if "SKILL_A" in system_prompt:
            # Fail fast.
            raise RuntimeError("a failed")
        # b is slow — must be cancelled before it finishes.
        try:
            await asyncio.sleep(5.0)
        except asyncio.CancelledError:
            raise
        sibling_completed = True
        yield TextDeltaEvent(text="should not arrive")
        yield DoneEvent(text="")

    orch = MetaOrchestrator(
        agent_runner=runner,
        skill_loader=_FakeLoader([_skill("skill_a"), _skill("skill_b")]),
    )

    final: MetaResult | None = None
    error_results: list[ToolResultEvent] = []
    async for ev in orch.iter_events(MetaMatch(plan=plan, inputs={})):
        if isinstance(ev, MetaResult):
            final = ev
        elif isinstance(ev, ToolResultEvent) and ev.is_error:
            error_results.append(ev)

    assert final is not None and final.ok is False
    assert sibling_completed is False
    assert len(error_results) >= 1


@pytest.mark.asyncio
async def test_linear_dag_event_order_preserved() -> None:
    """A→B→C chain keeps deterministic event ordering."""
    spec = _meta_spec(
        [
            {"id": "a", "skill": "skill_a", "with": {}},
            {"id": "b", "skill": "skill_b", "depends_on": ["a"], "with": {}},
            {"id": "c", "skill": "skill_c", "depends_on": ["b"], "with": {}},
        ],
    )
    plan = parse_meta_plan(spec)
    assert plan is not None

    async def runner(system_prompt: str, _u: str) -> AsyncIterator[AgentEvent]:
        for letter in ("A", "B", "C"):
            if f"SKILL_{letter}" in system_prompt:
                yield TextDeltaEvent(text=f"{letter}-done")
                break
        yield DoneEvent(text="")

    orch = MetaOrchestrator(
        agent_runner=runner,
        skill_loader=_FakeLoader(
            [_skill("skill_a"), _skill("skill_b"), _skill("skill_c")],
        ),
    )

    ordering: list[tuple[str, str]] = []
    final: MetaResult | None = None
    async for ev in orch.iter_events(MetaMatch(plan=plan, inputs={})):
        if isinstance(ev, MetaResult):
            final = ev
        elif isinstance(ev, ToolUseStartEvent) and ev.tool_name.startswith("meta-step:"):
            ordering.append(("start", ev.tool_name))
        elif isinstance(ev, ToolResultEvent) and ev.tool_name.startswith("meta-step:"):
            ordering.append(("end", ev.tool_name))

    assert final is not None and final.ok
    # Strict interleaving: start(a) → end(a) → start(b) → end(b) → start(c) → end(c)
    assert ordering == [
        ("start", "meta-step:a"),
        ("end", "meta-step:a"),
        ("start", "meta-step:b"),
        ("end", "meta-step:b"),
        ("start", "meta-step:c"),
        ("end", "meta-step:c"),
    ]
