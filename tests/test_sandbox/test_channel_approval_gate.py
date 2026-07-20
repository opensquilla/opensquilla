"""Channel-context behavior of ``request_sandbox_approval``.

A plain channel caller must never open a sandbox approval (hard deny, ask an
admin instead); a channel-admin turn opens one that is routed back to the
originating chat via the ``senderId``/``sessionKey`` params the notifier keys
on.
"""

from __future__ import annotations

import pytest

from opensquilla.gateway.approval_queue import get_approval_queue, reset_approval_queue
from opensquilla.sandbox.escalation import request_sandbox_approval
from opensquilla.tools.types import CallerKind, ToolContext, current_tool_context


@pytest.fixture(autouse=True)
def _reset_queue():
    reset_approval_queue()
    yield
    reset_approval_queue()


def _channel_context(*, is_owner: bool, sender_id: str | None = "ou_admin") -> ToolContext:
    return ToolContext(
        is_owner=is_owner,
        caller_kind=CallerKind.CHANNEL,
        session_key="feishu:oc_demo",
        channel_kind="feishu",
        channel_id="oc_demo",
        sender_id=sender_id,
        source_name="feishu-main",
    )


def _params() -> dict[str, object]:
    return {
        "approvalKind": "sandbox_network",
        "host": "pypi.org",
        "fingerprint": "fp-test",
        "choices": [
            {"id": "allow_once", "label": "Allow once", "approved": True},
            {"id": "allow_same_type", "label": "Allow same type", "approved": True},
            {"id": "deny", "label": "Deny", "approved": False},
        ],
    }


def _with_context(ctx: ToolContext | None, fn):
    token = current_tool_context.set(ctx)
    try:
        return fn()
    finally:
        current_tool_context.reset(token)


def test_non_admin_channel_caller_is_denied_without_a_request() -> None:
    payload = _with_context(
        _channel_context(is_owner=False),
        lambda: request_sandbox_approval(_params(), message="ask"),
    )

    assert payload["status"] == "approval_denied"
    assert payload["approval_id"] == ""
    assert "admin" in str(payload["message"])
    assert get_approval_queue().list_pending() == []


def test_admin_channel_caller_opens_a_channel_routed_approval() -> None:
    payload = _with_context(
        _channel_context(is_owner=True),
        lambda: request_sandbox_approval(_params(), message="ask"),
    )

    assert payload["status"] == "approval_required"
    approval_id = str(payload["approval_id"])
    entry = get_approval_queue().get(approval_id)
    # The stamps the channel notifier keys on: without them the prompt would
    # never reach the chat and the approval could not be resolved there.
    assert entry.params["senderId"] == "ou_admin"
    assert entry.params["sessionKey"] == "feishu:oc_demo"


def test_admin_without_sender_identity_stays_denied() -> None:
    # is_owner alone is not enough: without a sender id the resolver could
    # never match the approval back to a person, so the deny stands.
    payload = _with_context(
        _channel_context(is_owner=True, sender_id=None),
        lambda: request_sandbox_approval(_params(), message="ask"),
    )

    assert payload["status"] == "approval_denied"
    assert get_approval_queue().list_pending() == []


def test_non_channel_context_is_not_stamped() -> None:
    payload = _with_context(
        None,
        lambda: request_sandbox_approval(_params(), message="ask"),
    )

    assert payload["status"] == "approval_required"
    entry = get_approval_queue().get(str(payload["approval_id"]))
    assert "senderId" not in entry.params
