"""Main+systemEvent cron must pin heartbeat reply target via the resolver.

Main-session reminders must not drift to whichever channel touched the session
last. These tests assert the resolver's mapping and that make_system_event_handler
forwards its result through to heartbeat run_once.
"""

from __future__ import annotations

import opensquilla.scheduler.handlers as handlers_mod
from opensquilla.scheduler.handlers import (
    _resolve_system_event_heartbeat_delivery_override,
    make_system_event_handler,
)
from opensquilla.scheduler.types import (
    CronJob,
    CronWakeMode,
    DeliveryConfig,
    DeliveryMode,
    ReplyTargetSnapshot,
    SessionTarget,
)

# --- pure unit tests on the resolver --------------------------------------


def _job(delivery: DeliveryConfig) -> CronJob:
    return CronJob(
        id="job-1",
        cron_expr="* * * * *",
        handler_key="system_event",
        payload={"kind": "system_event", "text": "x", "agent_id": "main"},
        session_target=SessionTarget.MAIN,
        delivery=delivery,
    )


def test_resolver_uses_explicit_channel_fields_when_channel_mode() -> None:
    delivery = DeliveryConfig(
        mode=DeliveryMode.CHANNEL,
        channel_name="slack",
        channel_id="C123",
        account_id="T1",
        thread_id="th-1",
    )
    override = _resolve_system_event_heartbeat_delivery_override(_job(delivery))
    assert override == {
        "channel_name": "slack",
        "channel_id": "C123",
        "account_id": "T1",
        "thread_id": "th-1",
    }


def test_resolver_falls_back_to_snapshot_when_mode_none() -> None:
    snap = ReplyTargetSnapshot(
        channel_name="feishu",
        channel_type="feishu",
        to="chat-9",
        account_id="acc-x",
        thread_id="msg-42",
    )
    delivery = DeliveryConfig(mode=DeliveryMode.NONE, originating_reply_target=snap)
    override = _resolve_system_event_heartbeat_delivery_override(_job(delivery))
    assert override == {
        "channel_name": "feishu",
        "channel_id": "chat-9",
        "account_id": "acc-x",
        "thread_id": "msg-42",
    }


def test_resolver_returns_none_when_no_snapshot_and_mode_none() -> None:
    override = _resolve_system_event_heartbeat_delivery_override(
        _job(DeliveryConfig(mode=DeliveryMode.NONE))
    )
    assert override is None


def test_resolver_prefers_snapshot_when_origin_mode() -> None:
    snap = ReplyTargetSnapshot(
        channel_name="feishu",
        channel_type="feishu",
        to="chat-42",
        account_id="",
        thread_id="",
    )
    delivery = DeliveryConfig(
        mode=DeliveryMode.ORIGIN,
        channel_name="discord",
        channel_id="dis-1",
        originating_reply_target=snap,
    )
    override = _resolve_system_event_heartbeat_delivery_override(_job(delivery))
    assert override == {
        "channel_name": "feishu",
        "channel_id": "chat-42",
        "account_id": "",
        "thread_id": "",
    }


def test_resolver_uses_origin_fields_when_origin_without_snapshot() -> None:
    delivery = DeliveryConfig(
        mode=DeliveryMode.ORIGIN,
        channel_name="discord",
        channel_id="dis-1",
        account_id="",
        thread_id="",
    )
    override = _resolve_system_event_heartbeat_delivery_override(_job(delivery))
    assert override == {
        "channel_name": "discord",
        "channel_id": "dis-1",
        "account_id": "",
        "thread_id": "",
    }


# --- integration: handler forwards override to run_once -------------------


class _StubChain:
    async def notify_start(self, job, text):
        pass


class _StubSessionManager:
    async def get_or_create(self, **kw):
        return None

    async def append_message(self, *a, **k):
        return None


class _CapturingHeartbeat:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def run_once(self, **kwargs):
        self.calls.append(kwargs)

        class _R:
            status = "delivered"
            reason = ""
            delivery_status = "delivered"

        return _R()


def _main_job(snapshot: ReplyTargetSnapshot | None) -> CronJob:
    delivery = DeliveryConfig(
        mode=DeliveryMode.NONE,
        originating_reply_target=snapshot,
    )
    return CronJob(
        id="job-1",
        cron_expr="* * * * *",
        handler_key="system_event",
        payload={"kind": "system_event", "text": "stand up", "agent_id": "main"},
        session_target=SessionTarget.MAIN,
        session_key="main:main",
        wake_mode=CronWakeMode.NOW,
        delivery=delivery,
        timeout_seconds=10.0,
    )


async def test_handler_forwards_resolver_output_as_delivery_override(monkeypatch):
    """When the resolver returns an override, the handler must pass it through."""
    monkeypatch.setattr(
        handlers_mod,
        "_build_cron_tool_context",
        lambda *a, **kw: object(),
    )
    snapshot = ReplyTargetSnapshot(
        channel_name="feishu",
        channel_type="feishu",
        to="chat-001",
        account_id="acct-xyz",
        thread_id="msg-42",
    )
    job = _main_job(snapshot)

    hb = _CapturingHeartbeat()
    handler = make_system_event_handler(
        delivery_chain=_StubChain(),
        session_manager_ref=lambda: _StubSessionManager(),
        heartbeat_service_ref=lambda: hb,
        heartbeat_loop_ref=lambda: None,
    )

    await handler(job)

    assert hb.calls, "heartbeat run_once must be invoked for wake_mode=NOW"
    override = hb.calls[-1].get("delivery_override")
    assert override is not None
    assert override["channel_name"] == "feishu"
    assert override["channel_id"] == "chat-001"
    assert override["account_id"] == "acct-xyz"
    assert override["thread_id"] == "msg-42"


async def test_handler_omits_override_when_resolver_returns_none(monkeypatch):
    """No snapshot + mode NONE → override is not forwarded (legacy behaviour)."""
    monkeypatch.setattr(
        handlers_mod,
        "_build_cron_tool_context",
        lambda *a, **kw: object(),
    )
    job = _main_job(None)

    hb = _CapturingHeartbeat()
    handler = make_system_event_handler(
        delivery_chain=_StubChain(),
        session_manager_ref=lambda: _StubSessionManager(),
        heartbeat_service_ref=lambda: hb,
        heartbeat_loop_ref=lambda: None,
    )

    await handler(job)

    assert hb.calls
    assert "delivery_override" not in hb.calls[-1]


class _CapturingLoop:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def run_once_now(self, **kwargs):
        self.calls.append(kwargs)

        class _R:
            status = "delivered"
            reason = ""
            delivery_status = "delivered"

        return _R()


async def test_handler_forwards_override_through_loop_run_once_now(monkeypatch):
    """When a heartbeat_loop is available, the override flows through its run_once_now too."""
    monkeypatch.setattr(
        handlers_mod,
        "_build_cron_tool_context",
        lambda *a, **kw: object(),
    )
    snapshot = ReplyTargetSnapshot(
        channel_name="feishu",
        channel_type="feishu",
        to="chat-77",
        account_id="",
        thread_id="",
    )
    job = _main_job(snapshot)

    loop = _CapturingLoop()
    # heartbeat_service is consulted only when loop has no run_once_now;
    # provide one anyway so a failure in the loop path doesn't silently fall
    # back to a different call site.
    hb = _CapturingHeartbeat()
    handler = make_system_event_handler(
        delivery_chain=_StubChain(),
        session_manager_ref=lambda: _StubSessionManager(),
        heartbeat_service_ref=lambda: hb,
        heartbeat_loop_ref=lambda: loop,
    )

    await handler(job)

    assert loop.calls, "heartbeat_loop.run_once_now must be invoked"
    assert hb.calls == [], "service.run_once must not be called when loop path succeeds"
    override = loop.calls[-1].get("delivery_override")
    assert override == {
        "channel_name": "feishu",
        "channel_id": "chat-77",
        "account_id": "",
        "thread_id": "",
    }
