"""scheduler.run_dag 入口在第一个 step 派发前 yield meta_run_announced。"""

import asyncio

import pytest

from opensquilla.engine.types import (
    MetaRunAnnouncedEvent,
    ToolUseStartEvent,
)
from opensquilla.skills.meta.events import _StepDone
from opensquilla.skills.meta.types import MetaMatch, MetaPlan, MetaStep


@pytest.fixture
def make_two_step_match():
    plan = MetaPlan(
        name="meta-fake",
        triggers=("fake",),
        priority=0,
        steps=(
            MetaStep(id="intake", skill="intake", kind="llm_chat", label="意图提取"),
            MetaStep(
                id="summary", skill="summary", kind="llm_chat",
                label="总结", depends_on=("intake",),
            ),
        ),
        final_text_mode="raw",
    )
    return MetaMatch(plan=plan, inputs={"user_message": "hi"})


@pytest.fixture
def fake_dispatch_stream():
    async def _dispatch(step, effective_skill, inputs, outputs):
        yield _StepDone(text=f"out:{step.id}")

    return _dispatch


@pytest.fixture
def fake_preface():
    async def _preface(step_id, effective_skill):
        return
        yield  # never reached; keeps it an async generator

    return _preface


async def _collect_events(match, dispatch, preface, *, limit=None):
    from opensquilla.skills.meta.scheduler import run_dag

    events = []
    async for ev in run_dag(
        match,
        dispatch_step_stream=dispatch,
        yield_skill_view_preface=preface,
    ):
        events.append(ev)
        if limit is not None and len(events) >= limit:
            break
    return events


def test_announces_plan_before_first_tool_use(
    make_two_step_match, fake_dispatch_stream, fake_preface,
):
    """meta_run_announced 必须先于任何 step 的 ToolUseStartEvent。"""

    events = asyncio.run(_collect_events(
        make_two_step_match, fake_dispatch_stream, fake_preface, limit=3,
    ))

    kinds = [type(e).__name__ for e in events]
    assert "MetaRunAnnouncedEvent" in kinds
    first_announce = next(
        i for i, e in enumerate(events) if isinstance(e, MetaRunAnnouncedEvent)
    )
    first_tool = next(
        (i for i, e in enumerate(events) if isinstance(e, ToolUseStartEvent)),
        None,
    )
    assert first_tool is None or first_announce < first_tool


def test_announce_payload_lists_all_steps(make_two_step_match, fake_dispatch_stream, fake_preface):
    events = asyncio.run(_collect_events(
        make_two_step_match, fake_dispatch_stream, fake_preface, limit=1,
    ))
    announce = next(
        (e for e in events if isinstance(e, MetaRunAnnouncedEvent)), None,
    )

    assert announce is not None
    assert announce.total == 2
    ids = [s["id"] for s in announce.steps]
    assert ids == ["intake", "summary"]
    assert announce.steps[0]["label"] == "意图提取"
    assert announce.steps[1]["depends_on"] == ["intake"]
