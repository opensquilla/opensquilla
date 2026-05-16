from __future__ import annotations

from datetime import UTC, datetime

from opensquilla.scheduler.payloads import AGENT_TURN_KIND
from opensquilla.scheduler.rpc_payload import (
    cron_job_to_wire,
    cron_run_to_wire,
    cron_subscription_error_response,
    cron_subscription_response,
    manual_run_to_wire,
    tool_policy_from_params,
)
from opensquilla.scheduler.types import (
    CronJob,
    DeliveryConfig,
    DeliveryMode,
    JobExecution,
    ManualRunResult,
    ManualRunStatus,
    SessionTarget,
)


def test_cron_job_to_wire_preserves_ui_shape_and_policy_aliases() -> None:
    job = CronJob(
        id="drink",
        name="Drink",
        cron_expr="*/5 * * * *",
        schedule_raw="*/5 * * * *",
        payload={"kind": AGENT_TURN_KIND, "task": "drink water", "agent_id": "ops"},
        session_target=SessionTarget.CURRENT,
        session_key="agent:ops:webchat:abc",
        origin_session_key="agent:ops:webchat:abc",
        delivery=DeliveryConfig(
            mode=DeliveryMode.CHANNEL,
            channel_name="slack",
            channel_id="C1",
            account_id="A1",
            thread_id="T1",
        ),
        tool_policy={"profile": "minimal", "also_allow": ["memory_search"]},
    )

    payload = cron_job_to_wire(job)

    assert payload["id"] == "drink"
    assert payload["expression"] == "*/5 * * * *"
    assert payload["prompt"] == "drink water"
    assert payload["message"] == "drink water"
    assert payload["text"] == "drink water"
    assert payload["payloadKind"] == AGENT_TURN_KIND
    assert payload["agentId"] == "ops"
    assert payload["sessionTarget"] == "current"
    assert payload["targetSessionKey"] == "agent:ops:webchat:abc"
    assert payload["originSessionKey"] == "agent:ops:webchat:abc"
    assert payload["delivery"] == {
        "mode": "channel",
        "channelName": "slack",
        "channelId": "C1",
        "accountId": "A1",
        "threadId": "T1",
    }
    assert payload["toolPolicy"] == {
        "profile": "minimal",
        "allow": [],
        "alsoAllow": ["memory_search"],
        "deny": [],
    }


def test_manual_run_and_execution_payloads_preserve_wire_shape() -> None:
    started_at = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    finished_at = datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)
    execution = JobExecution(
        id="run-1",
        job_id="drink",
        started_at=started_at,
        finished_at=finished_at,
        success=True,
        summary="done",
        session_key="agent:main:webchat:abc",
        delivery_status="skipped",
    )

    assert manual_run_to_wire(
        ManualRunResult(status=ManualRunStatus.ACCEPTED, execution=execution)
    ) == {
        "success": True,
        "status": "accepted",
        "reply": "done",
        "error": None,
        "duration_ms": 1000,
    }
    assert cron_run_to_wire(execution) == {
        "id": "run-1",
        "started_at": "2026-01-01T00:00:00+00:00",
        "finished_at": "2026-01-01T00:00:01+00:00",
        "success": True,
        "status": "ok",
        "duration_ms": 1000,
        "error": None,
        "summary": "done",
        "sessionKey": "agent:main:webchat:abc",
        "deliveryStatus": "skipped",
    }


def test_cron_subscription_responses_preserve_wire_shape() -> None:
    assert cron_subscription_error_response("no connection context") == {
        "ok": False,
        "error": "no connection context",
    }
    assert cron_subscription_response("cron:drink") == {
        "ok": True,
        "topic": "cron:drink",
    }


def test_tool_policy_from_params_normalizes_camelcase_aliases() -> None:
    assert tool_policy_from_params(
        {
            "toolPolicy": {
                "profile": "minimal",
                "allow": "session_status",
                "alsoAllow": ["memory_search"],
                "deny": {"web_fetch"},
            }
        }
    ) == {
        "profile": "minimal",
        "allow": ["session_status"],
        "also_allow": ["memory_search"],
        "deny": ["web_fetch"],
    }
