"""MetaSkill 事件 dataclass 形状与默认值。"""

from opensquilla.engine.types import (
    MetaRunAnnouncedEvent,
    MetaRunCompletedEvent,
    MetaStepStateEvent,
)


def test_meta_run_announced_minimal():
    ev = MetaRunAnnouncedEvent(
        run_id="r1",
        meta_skill_name="meta-document-to-decision",
        steps=[
            {"id": "intake", "label": "意图提取", "kind": "llm_chat", "depends_on": []},
            {"id": "search", "label": "检索证据", "kind": "agent", "depends_on": ["intake"]},
        ],
        total=2,
        parent_run_id=None,
    )
    assert ev.kind == "meta_run_announced"
    assert ev.total == 2
    assert ev.parent_run_id is None


def test_meta_step_state_minimal():
    ev = MetaStepStateEvent(
        run_id="r1",
        step_id="search",
        state="running",
        status_text="检索中…",
    )
    assert ev.kind == "meta_step_state"
    assert ev.error is None
    assert ev.substitute_for is None


def test_meta_step_state_failed_with_error():
    ev = MetaStepStateEvent(
        run_id="r1",
        step_id="search",
        state="failed",
        error="web-research timeout",
    )
    assert ev.state == "failed"
    assert ev.error == "web-research timeout"


def test_meta_step_state_substituted_links_origin():
    ev = MetaStepStateEvent(
        run_id="r1",
        step_id="search_fallback",
        state="substituted",
        substitute_for="search",
    )
    assert ev.substitute_for == "search"


def test_meta_run_completed_minimal():
    ev = MetaRunCompletedEvent(
        run_id="r1",
        outcome="ok",
        completed_steps=["intake", "search"],
        failed_steps=[],
        skipped_steps=[],
    )
    assert ev.kind == "meta_run_completed"
    assert ev.outcome == "ok"


def test_meta_step_state_event_is_in_agent_event_union():
    """Ensure later tasks can yield MetaStepStateEvent through AgentEvent
    typed iterators without an isinstance fallback."""
    from typing import get_args

    from opensquilla.engine.types import AgentEvent

    members = get_args(AgentEvent)
    assert MetaRunAnnouncedEvent in members
    assert MetaStepStateEvent in members
    assert MetaRunCompletedEvent in members
