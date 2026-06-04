"""scheduler 在 step 开始/成功时分别发出 meta_step_state(running/succeeded)。"""

import asyncio

import pytest

from opensquilla.engine.types import MetaStepStateEvent
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


async def _collect_all_events(match, dispatch, preface):
    from opensquilla.skills.meta.scheduler import run_dag

    events = []
    async for ev in run_dag(
        match,
        dispatch_step_stream=dispatch,
        yield_skill_view_preface=preface,
    ):
        events.append(ev)
    return events


def test_running_emitted_at_step_start(
    make_two_step_match, fake_dispatch_stream, fake_preface,
):
    events = asyncio.run(_collect_all_events(
        make_two_step_match, fake_dispatch_stream, fake_preface,
    ))

    step_states = [
        (ev.step_id, ev.state)
        for ev in events
        if isinstance(ev, MetaStepStateEvent)
    ]
    assert ("intake", "running") in step_states
    assert ("intake", "succeeded") in step_states


def test_running_precedes_succeeded(
    make_two_step_match, fake_dispatch_stream, fake_preface,
):
    events = asyncio.run(_collect_all_events(
        make_two_step_match, fake_dispatch_stream, fake_preface,
    ))

    seq = [
        ev.state
        for ev in events
        if isinstance(ev, MetaStepStateEvent) and ev.step_id == "intake"
    ]
    assert seq.index("running") < seq.index("succeeded")


@pytest.fixture
def make_skipped_match():
    plan = MetaPlan(
        name="meta-skip-fake",
        triggers=("fake",),
        priority=0,
        steps=(
            MetaStep(id="intake", skill="intake", kind="llm_chat", label="意图提取"),
            MetaStep(
                id="optional", skill="optional", kind="llm_chat",
                label="可选", depends_on=("intake",), when="False",
            ),
        ),
        final_text_mode="raw",
    )
    return MetaMatch(plan=plan, inputs={"user_message": "hi"})


def test_skipped_emitted_on_when_false(
    make_skipped_match, fake_dispatch_stream, fake_preface,
):
    events = asyncio.run(_collect_all_events(
        make_skipped_match, fake_dispatch_stream, fake_preface,
    ))

    states = [
        (ev.step_id, ev.state)
        for ev in events
        if isinstance(ev, MetaStepStateEvent)
    ]
    assert ("optional", "skipped") in states
