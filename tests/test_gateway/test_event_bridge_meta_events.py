"""event_bridge 把 3 个新 meta 事件 dataclass 映射到正确的 session.event 名。"""

from opensquilla.engine.types import (
    MetaPreflightEvent,
    MetaRunAnnouncedEvent,
    MetaRunCompletedEvent,
    MetaStepStateEvent,
)
from opensquilla.gateway.event_bridge import bridge_event_name


def test_meta_run_announced_event_name():
    ev = MetaRunAnnouncedEvent(run_id="r1", meta_skill_name="x", steps=[], total=0)
    assert bridge_event_name(ev) == "session.event.meta_run_announced"


def test_meta_preflight_event_name():
    ev = MetaPreflightEvent(
        run_id="r1",
        meta_skill_name="x",
        request_template={"outcome": "Decision memo"},
        interpreted_request="Help me decide",
        requires_confirmation=True,
    )
    assert bridge_event_name(ev) == "session.event.meta_preflight"
    assert ev.requires_confirmation is True


def test_meta_step_state_event_name():
    ev = MetaStepStateEvent(run_id="r1", step_id="s1", state="running")
    assert bridge_event_name(ev) == "session.event.meta_step_state"


def test_meta_run_completed_event_name():
    ev = MetaRunCompletedEvent(run_id="r1", outcome="ok")
    assert bridge_event_name(ev) == "session.event.meta_run_completed"
