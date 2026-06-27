"""scheduler.run_dag 入口在第一个 step 派发前 yield meta_run_announced。"""

import asyncio
from dataclasses import replace

import pytest

from opensquilla.engine.types import (
    MetaPreflightEvent,
    MetaRunAnnouncedEvent,
    ToolUseStartEvent,
)
from opensquilla.skills.meta.events import _StepDone
from opensquilla.skills.meta.types import MetaMatch, MetaPlan, MetaResult, MetaStep


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
        request_template={
            "outcome": "Short summary",
            "fields": [
                {"name": "topic", "required": True},
                {"name": "tone", "required": False, "default": "concise"},
            ],
            "assumptions": ["Use the user's current message as the topic"],
        },
    )
    return MetaMatch(
        plan=plan,
        inputs={
            "user_message": "hi",
            "topic": "hi",
            "meta_preflight_confirmed": True,
            "meta_preflight_run_id": "meta-fake-run",
        },
        run_id="meta-fake-run",
    )


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
    agen = run_dag(
        match,
        dispatch_step_stream=dispatch,
        yield_skill_view_preface=preface,
    )
    try:
        async for ev in agen:
            events.append(ev)
            if limit is not None and len(events) >= limit:
                break
    finally:
        await agen.aclose()
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


def test_preflight_precedes_run_announce(
    make_two_step_match, fake_dispatch_stream, fake_preface,
):
    events = asyncio.run(_collect_events(
        make_two_step_match, fake_dispatch_stream, fake_preface, limit=2,
    ))

    assert isinstance(events[0], MetaPreflightEvent)
    assert isinstance(events[1], MetaRunAnnouncedEvent)
    assert events[0].run_id == events[1].run_id
    assert events[0].meta_skill_name == "meta-fake"
    assert events[0].request_template["outcome"] == "Short summary"
    assert events[0].interpreted_request == "hi"
    assert events[0].missing_fields == []
    assert events[0].assumptions == ["Use the user's current message as the topic"]
    assert events[0].can_skip is True


def test_preflight_pauses_before_run_announce_until_confirmed(
    make_two_step_match, fake_dispatch_stream, fake_preface,
):
    plan = replace(
        make_two_step_match.plan,
        request_template={
            **make_two_step_match.plan.request_template,
            "mode": "confirm",
        },
    )
    match = MetaMatch(
        plan=plan,
        inputs={
            "user_message": "hi",
            "topic": "hi",
        },
    )
    events = asyncio.run(_collect_events(
        match, fake_dispatch_stream, fake_preface,
    ))

    assert isinstance(events[0], MetaPreflightEvent)
    assert events[0].can_skip is True
    assert not any(isinstance(e, MetaRunAnnouncedEvent) for e in events)
    result = next(e for e in events if isinstance(e, MetaResult))
    assert result.paused is True


def test_confirmed_preflight_requires_current_run_id(
    make_two_step_match, fake_dispatch_stream, fake_preface,
):
    plan = replace(
        make_two_step_match.plan,
        request_template={
            **make_two_step_match.plan.request_template,
            "mode": "confirm",
        },
    )
    match = MetaMatch(
        plan=plan,
        inputs={
            "user_message": "hi",
            "topic": "hi",
            "meta_preflight_confirmed": True,
            "meta_preflight_run_id": "stale-run",
        },
        run_id="current-run",
    )

    events = asyncio.run(_collect_events(
        match, fake_dispatch_stream, fake_preface,
    ))

    assert isinstance(events[0], MetaPreflightEvent)
    assert not any(isinstance(e, MetaRunAnnouncedEvent) for e in events)
    result = next(e for e in events if isinstance(e, MetaResult))
    assert result.paused is True


def test_announce_payload_lists_all_steps(make_two_step_match, fake_dispatch_stream, fake_preface):
    events = asyncio.run(_collect_events(
        make_two_step_match, fake_dispatch_stream, fake_preface, limit=2,
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


def test_announce_payload_carries_user_language(
    make_two_step_match, fake_dispatch_stream, fake_preface,
):
    match = MetaMatch(
        plan=make_two_step_match.plan,
        inputs={
            **make_two_step_match.inputs,
            "user_language": "zh",
        },
        run_id="localized-run",
    )

    events = asyncio.run(_collect_events(
        match, fake_dispatch_stream, fake_preface, limit=2,
    ))
    announce = next(
        (e for e in events if isinstance(e, MetaRunAnnouncedEvent)), None,
    )

    assert announce is not None
    assert announce.language == "zh"


def test_announce_uses_match_run_id(make_two_step_match, fake_dispatch_stream, fake_preface):
    match = MetaMatch(
        plan=make_two_step_match.plan,
        inputs={
            **make_two_step_match.inputs,
            "meta_preflight_run_id": "persisted-run-123",
        },
        run_id="persisted-run-123",
    )

    events = asyncio.run(_collect_events(
        match, fake_dispatch_stream, fake_preface, limit=2,
    ))
    announce = next(
        (e for e in events if isinstance(e, MetaRunAnnouncedEvent)), None,
    )

    assert announce is not None
    assert announce.run_id == "persisted-run-123"
