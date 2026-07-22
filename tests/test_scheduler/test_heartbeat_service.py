from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import opensquilla.scheduler.heartbeat_service as heartbeat_service_module
from opensquilla.scheduler.heartbeat_service import HeartbeatService


@pytest.mark.asyncio
async def test_empty_heartbeat_summary_is_not_delivered(monkeypatch: pytest.MonkeyPatch) -> None:
    service = HeartbeatService(
        turn_runner=None,
        session_storage=None,
        channel_manager_ref=lambda: None,
    )
    collect_output = AsyncMock(return_value="")
    send_delivery = AsyncMock(return_value=None)
    infer_delivery = AsyncMock(
        return_value=SimpleNamespace(
            channel_name="feishu",
            channel_id="chat-id",
            account_id="",
            thread_id="",
        )
    )
    monkeypatch.setattr(service, "_collect_output", collect_output)
    monkeypatch.setattr(service, "_send_delivery", send_delivery)
    monkeypatch.setattr(heartbeat_service_module, "infer_delivery", infer_delivery)

    result = await service.run_once(
        reason="scheduled",
        agent_id="main",
        session_key="agent:main:main",
        prompt="Reply HEARTBEAT_OK.",
    )

    assert result.status == "skipped"
    assert result.delivery_status == "skipped"
    assert result.reason == "heartbeat_ack"
    assert result.summary == ""
    infer_delivery.assert_not_awaited()
    send_delivery.assert_not_awaited()
