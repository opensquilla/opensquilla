"""Feishu interactive-card parsing of Approve/Deny actions."""

from __future__ import annotations

from opensquilla.channels.approval_prompt import parse_approval_action
from opensquilla.channels.feishu import FeishuChannel, FeishuChannelConfig


def _channel() -> FeishuChannel:
    return FeishuChannel(
        FeishuChannelConfig(app_id="app", app_secret="secret", connection_mode="websocket")
    )


def _card_event(decision: str, code: str) -> dict:
    return {
        "header": {"event_id": "evt-1"},
        "event": {
            "operator": {"open_id": "owner-open-id"},
            "open_chat_id": "chat-1",
            "action": {
                "value": {
                    "opensquilla_action": "approval_resolve",
                    "code": code,
                    "decision": decision,
                }
            },
        },
    }


def test_parse_approval_card_action_yields_inbound_message() -> None:
    channel = _channel()
    msg = channel._parse_approval_card_action(_card_event("approve", "AB12"))

    assert msg is not None
    assert msg.sender_id == "owner-open-id"
    assert msg.channel_id == "chat-1"
    assert msg.content == "/approve AB12"
    assert msg.metadata["approval_action"]["code"] == "AB12"
    # The shared parser recognises the carried action.
    assert parse_approval_action(msg) == ("AB12", True)


def test_parse_ignores_clarify_and_unknown_actions() -> None:
    channel = _channel()
    clarify = {
        "event": {"action": {"value": {"opensquilla_action": "clarify_submit"}}},
    }
    assert channel._parse_approval_card_action(clarify) is None
    bad_decision = _card_event("maybe", "AB12")
    assert channel._parse_approval_card_action(bad_decision) is None
    missing_code = {
        "event": {
            "action": {"value": {"opensquilla_action": "approval_resolve", "decision": "approve"}}
        }
    }
    assert channel._parse_approval_card_action(missing_code) is None
