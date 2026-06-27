"""The channel-approval notifier pushes a prompt to the originating channel."""

from __future__ import annotations

import asyncio

import pytest

from opensquilla.channels.approval_prompt import reset_short_codes, resolve_short_code
from opensquilla.channels.contract import ChannelCapabilityProfile
from opensquilla.gateway.approval_notify import register_approval_channel_notifier
from opensquilla.gateway.approval_queue import get_approval_queue, reset_approval_queue


class _FakeNode:
    def __init__(self) -> None:
        self.last_channel = "feishu"
        self.last_to = "chat-1"
        self.last_thread_id = None


class _FakeSessionManager:
    async def get_session(self, session_key: str):
        return _FakeNode()


class _FakeAdapter:
    def __init__(self, interactive_cards: bool) -> None:
        self._interactive_cards = interactive_cards
        self.sent: list = []

    def capability_profile(self) -> ChannelCapabilityProfile:
        return ChannelCapabilityProfile(
            channel_type="feishu", interactive_cards=self._interactive_cards
        )

    async def send(self, message) -> None:
        self.sent.append(message)


class _FakeChannelManager:
    def __init__(self, adapter: _FakeAdapter) -> None:
        self._adapter = adapter

    def get(self, name: str):
        return self._adapter


@pytest.fixture(autouse=True)
def _reset_state():
    reset_approval_queue()
    reset_short_codes()
    yield
    reset_approval_queue()
    reset_short_codes()


def _run_notifier(adapter: _FakeAdapter, *, sender_id: str) -> str:
    async def _run() -> str:
        loop = asyncio.get_running_loop()
        scheduled: list = []

        def _schedule(coro):
            scheduled.append(loop.create_task(coro))

        remove = register_approval_channel_notifier(
            get_approval_queue(),
            session_manager=_FakeSessionManager(),
            channel_manager_ref=lambda: _FakeChannelManager(adapter),
            schedule=_schedule,
        )
        try:
            approval_id = get_approval_queue().request(
                namespace="exec",
                params={
                    "toolName": "exec_command",
                    "command": "rm target.txt",
                    "sessionKey": "agent:main:chat",
                    "senderId": sender_id,
                    "channelKind": "feishu",
                },
            )
            if scheduled:
                await asyncio.gather(*scheduled)
            return approval_id
        finally:
            remove()

    return asyncio.run(_run())


def test_notifier_sends_interactive_card_to_origin_channel() -> None:
    adapter = _FakeAdapter(interactive_cards=True)
    approval_id = _run_notifier(adapter, sender_id="owner-1")

    assert len(adapter.sent) == 1
    message = adapter.sent[0]
    assert message.reply_to == "chat-1"
    assert "card" in message.metadata
    # A short code bound to this approval + owner is now resolvable.
    code = None
    for candidate_card_value in message.metadata["card"]["elements"][1]["actions"]:
        code = candidate_card_value["value"]["code"]
        break
    assert code is not None
    binding = resolve_short_code(code)
    assert binding is not None
    assert binding.approval_id == approval_id
    assert binding.owner_sender_id == "owner-1"


def test_notifier_falls_back_to_text_without_cards() -> None:
    adapter = _FakeAdapter(interactive_cards=False)
    _run_notifier(adapter, sender_id="owner-1")

    assert len(adapter.sent) == 1
    message = adapter.sent[0]
    assert "card" not in message.metadata
    assert "/approve" in message.content


def test_notifier_ignores_non_channel_requests() -> None:
    adapter = _FakeAdapter(interactive_cards=True)

    async def _run() -> None:
        loop = asyncio.get_running_loop()
        scheduled: list = []
        remove = register_approval_channel_notifier(
            get_approval_queue(),
            session_manager=_FakeSessionManager(),
            channel_manager_ref=lambda: _FakeChannelManager(adapter),
            schedule=lambda coro: scheduled.append(loop.create_task(coro)),
        )
        try:
            # No senderId -> not a channel-originated approval; nothing scheduled.
            get_approval_queue().request(
                namespace="exec",
                params={"toolName": "exec_command", "command": "rm x", "sessionKey": "s"},
            )
            if scheduled:
                await asyncio.gather(*scheduled)
        finally:
            remove()

    asyncio.run(_run())
    assert adapter.sent == []
