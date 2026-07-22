from __future__ import annotations

import asyncio
import contextlib
import sqlite3
from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from opensquilla.channels.contract import (
    UNCLASSIFIED_ERROR_CLASS,
    ChannelCapabilities,
    ChannelCapabilityProfile,
    ChannelSendResult,
)
from opensquilla.channels.delivery_store import (
    ChannelDeliveryStore,
    deliver_with_outbox,
    durable_enqueue,
    inbound_event_key,
    install_outbox,
)
from opensquilla.channels.manager import ChannelManager
from opensquilla.channels.types import (
    AuthenticatedPrincipal,
    IncomingMessage,
    IngressProvenance,
    IngressVerification,
    OutgoingMessage,
)
from opensquilla.gateway.config import DiscordChannelEntry


def _message(event_id: str = "event-1") -> IncomingMessage:
    return IncomingMessage(
        sender_id="user-1",
        channel_id="chat-1",
        content="hello",
        metadata={"is_group": False, "native_message_id": event_id},
        provenance=IngressProvenance(
            provider="slack",
            account_id="team-1",
            transport="webhook",
            verification=IngressVerification.WEBHOOK_SIGNATURE,
            event_id=event_id,
            principal=AuthenticatedPrincipal(subject_id="user-1"),
        ),
    )


def test_ingress_accept_claim_complete_and_restart_recovery(tmp_path) -> None:
    path = tmp_path / "channel_delivery.sqlite"
    store = ChannelDeliveryStore(path)
    message = _message()

    assert store.accept_inbound("slack-main", message) is True
    claim = store.claim_inbound("slack-main", message)
    assert claim is not None
    store.close()

    restarted = ChannelDeliveryStore(path)
    recovered = restarted.recover_inbound("slack-main")
    assert len(recovered) == 1
    assert recovered[0].provenance.event_id == "event-1"

    recovered_claim = restarted.claim_inbound("slack-main", recovered[0])
    assert recovered_claim is not None
    restarted.complete_inbound(recovered_claim, "turn_dispatched")

    assert restarted.recover_inbound("slack-main") == []
    assert restarted.accept_inbound("slack-main", message) is False
    diagnostics = restarted.diagnostics("slack-main")
    assert diagnostics["ingress"]["completed"]["count"] == 1
    restarted.close()


def test_durable_enqueue_commits_before_memory_visibility(tmp_path) -> None:
    store = ChannelDeliveryStore(tmp_path / "channel_delivery.sqlite")
    queue: list[IncomingMessage] = []

    class Queue:
        def put_nowait(self, message: IncomingMessage) -> None:
            with sqlite3.connect(store.path) as connection:
                state = connection.execute("SELECT state FROM channel_ingress").fetchone()
            assert state == ("accepted",)
            queue.append(message)

    channel = SimpleNamespace(
        _delivery_store=store,
        _delivery_channel_name="slack-main",
    )

    assert durable_enqueue(channel, _message(), Queue()) is True
    assert len(queue) == 1
    store.close()


@contextlib.contextmanager
def _blocked_journal(store: ChannelDeliveryStore) -> Iterator[None]:
    """Hold the write lock from a second connection to force SQLITE_BUSY."""
    store._conn.execute("PRAGMA busy_timeout=100;")
    blocker = sqlite3.connect(store.path)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        yield
    finally:
        blocker.rollback()
        blocker.close()


def test_journal_write_failure_degrades_to_memory_only_acceptance(tmp_path) -> None:
    """A storage fault must not raise out of accept_inbound or lose the event."""
    store = ChannelDeliveryStore(tmp_path / "channel_delivery.sqlite")
    message = _message()

    with _blocked_journal(store):
        assert store.accept_inbound("slack-main", message) is True

    # The degraded event has no journal row, yet dispatch must still be able
    # to claim and finalize it instead of skipping it as a duplicate.
    claim = store.claim_inbound("slack-main", message)
    assert claim is not None
    assert claim.event_key == ""
    store.complete_inbound(claim, "turn_dispatched")  # pass-through no-op

    # Once storage recovers, the journal is used again.
    follow_up = _message("event-2")
    assert store.accept_inbound("slack-main", follow_up) is True
    follow_claim = store.claim_inbound("slack-main", follow_up)
    assert follow_claim is not None
    assert follow_claim.event_key
    assert store.diagnostics("slack-main")["ingress"]["processing"]["count"] == 1
    store.close()


def _durable_ingress_count(store: ChannelDeliveryStore) -> int:
    with sqlite3.connect(store.path) as connection:
        row = connection.execute("SELECT COUNT(*) FROM channel_ingress").fetchone()
    return int(row[0])


def test_recovery_after_degraded_accept_does_not_double_dispatch(tmp_path) -> None:
    """A redelivery after storage recovers must not add a durable row alongside
    the memory-only marker, which would let the same event be claimed twice."""
    store = ChannelDeliveryStore(tmp_path / "channel_delivery.sqlite")
    message = _message()
    event_key = inbound_event_key("slack-main", message)
    assert event_key is not None
    queue: list[IncomingMessage] = []

    class Queue:
        def put_nowait(self, item: IncomingMessage) -> None:
            queue.append(item)

    channel = SimpleNamespace(_delivery_store=store, _delivery_channel_name="slack-main")

    # Delivery A during a storage fault: degrades to memory-only acceptance but
    # is still enqueued for dispatch, with no durable journal row.
    with _blocked_journal(store):
        assert durable_enqueue(channel, message, Queue()) is True
    assert event_key in store._unjournaled_events
    assert _durable_ingress_count(store) == 0
    assert len(queue) == 1

    # Delivery B after storage recovers: a redelivery of the SAME event must be
    # treated as a duplicate — no durable row is committed and nothing is
    # re-enqueued — so it cannot produce a second, independently claimable row.
    assert durable_enqueue(channel, message, Queue()) is False
    assert store.accept_inbound("slack-main", message) is False
    assert _durable_ingress_count(store) == 0
    assert len(queue) == 1

    # End to end, exactly one claim is dispatchable: the pending pass-through
    # from delivery A. The marker is reconciled (discarded) as it is claimed.
    claim = store.claim_inbound("slack-main", queue[0])
    assert claim is not None
    assert claim.event_key == ""
    assert event_key not in store._unjournaled_events
    # No second dispatchable claim exists: the marker is gone and no durable
    # 'accepted' row was ever written.
    assert store.claim_inbound("slack-main", message) is None
    store.close()


def test_redelivery_after_passthrough_claim_does_not_double_dispatch(tmp_path) -> None:
    """A redelivery arriving AFTER the pass-through claim must still be a
    duplicate: the claim consumed the memory-only marker, so without a durable
    trace the redelivery would journal a fresh 'accepted' row and hand out a
    second claim for the same event."""
    store = ChannelDeliveryStore(tmp_path / "channel_delivery.sqlite")
    message = _message()
    event_key = inbound_event_key("slack-main", message)
    assert event_key is not None

    # Delivery A during a storage fault: memory-only acceptance, no durable row.
    with _blocked_journal(store):
        assert store.accept_inbound("slack-main", message) is True
    assert event_key in store._unjournaled_events
    assert _durable_ingress_count(store) == 0

    # Dispatch claims first: the marker is consumed by the pass-through claim.
    claim = store.claim_inbound("slack-main", message)
    assert claim is not None
    assert claim.event_key == ""
    assert event_key not in store._unjournaled_events

    # Delivery B after storage recovers: the redelivery must be rejected — it
    # must not commit an independently claimable 'accepted' row.
    assert store.accept_inbound("slack-main", message) is False
    with sqlite3.connect(store.path) as connection:
        rows = connection.execute(
            "SELECT state FROM channel_ingress WHERE event_key = ?", (event_key,)
        ).fetchall()
    assert len(rows) <= 1
    assert all(row[0] != "accepted" for row in rows)
    # Exactly ONE dispatchable claim across the whole sequence.
    assert store.claim_inbound("slack-main", message) is None
    store.close()


def test_redelivery_after_passthrough_claim_survives_restart(tmp_path) -> None:
    """The dedup trace left by the pass-through claim must be durable: a
    restart clears the in-memory marker set, so only a journal row can stop a
    post-restart redelivery from dispatching the event a second time."""
    path = tmp_path / "channel_delivery.sqlite"
    store = ChannelDeliveryStore(path)
    message = _message()
    event_key = inbound_event_key("slack-main", message)
    assert event_key is not None

    with _blocked_journal(store):
        assert store.accept_inbound("slack-main", message) is True
    claim = store.claim_inbound("slack-main", message)
    assert claim is not None
    assert claim.event_key == ""
    store.close()

    restarted = ChannelDeliveryStore(path)
    # The trace row must not be resurrected as recoverable pending work.
    assert restarted.recover_inbound("slack-main") == []
    # A post-restart redelivery is a duplicate, not a second dispatch.
    assert restarted.accept_inbound("slack-main", message) is False
    assert restarted.claim_inbound("slack-main", message) is None
    restarted.close()


def test_normal_duplicate_without_fault_is_still_rejected(tmp_path) -> None:
    """Control: with healthy storage, a redelivered event is a durable duplicate
    and is rejected without going through the memory-only marker path."""
    store = ChannelDeliveryStore(tmp_path / "channel_delivery.sqlite")
    message = _message()

    assert store.accept_inbound("slack-main", message) is True
    assert _durable_ingress_count(store) == 1
    # A second, fault-free delivery hits the durable IntegrityError branch.
    assert store.accept_inbound("slack-main", message) is False
    assert _durable_ingress_count(store) == 1
    assert store._unjournaled_events == set()
    store.close()


async def test_telegram_poll_loop_survives_journal_write_failure(tmp_path) -> None:
    """One SQLite fault must not kill the Telegram receive path."""
    from opensquilla.channels.telegram import TelegramChannel, TelegramChannelConfig

    store = ChannelDeliveryStore(tmp_path / "channel_delivery.sqlite")
    channel = TelegramChannel(TelegramChannelConfig(token="synthetic-token"))
    channel._delivery_store = store
    channel._delivery_channel_name = "telegram-main"

    calls = 0

    async def fake_api(method: str, payload: dict | None = None) -> list[dict]:
        nonlocal calls
        assert method == "getUpdates"
        calls += 1
        if calls == 1:
            return [
                {
                    "update_id": 7,
                    "message": {
                        "message_id": 1,
                        "chat": {"id": 42, "type": "private"},
                        "from": {"id": 9},
                        "text": "hello",
                    },
                }
            ]
        raise asyncio.CancelledError

    channel._api = fake_api  # type: ignore[method-assign]

    with _blocked_journal(store):
        with pytest.raises(asyncio.CancelledError):
            await channel._poll_loop()

    assert channel._update_offset == 8
    assert channel._queue.get_nowait().content == "hello"
    store.close()


async def test_discord_dispatch_enqueue_survives_journal_write_failure(tmp_path) -> None:
    """A journal fault in the Discord dispatch path must not raise."""
    from opensquilla.channels.discord import DiscordChannel, DiscordChannelConfig

    store = ChannelDeliveryStore(tmp_path / "channel_delivery.sqlite")
    channel = DiscordChannel(DiscordChannelConfig(token="synthetic-token"))
    channel.bot_user_id = "bot-1"
    channel._delivery_store = store
    channel._delivery_channel_name = "discord-main"

    with _blocked_journal(store):
        await channel._handle_dispatch(
            "MESSAGE_CREATE",
            {
                "id": "message-1",
                "channel_id": "channel-1",
                "author": {"id": "user-1"},
                "content": "hello",
            },
        )

    assert channel._queue.get_nowait().content == "hello"
    store.close()


def test_qq_enqueue_survives_journal_write_failure(tmp_path) -> None:
    """A journal fault in the QQ message hook must not raise."""
    from opensquilla.channels.qq import QQChannel, QQChannelConfig

    store = ChannelDeliveryStore(tmp_path / "channel_delivery.sqlite")
    channel = QQChannel(
        QQChannelConfig(name="qq", app_id="app-id", app_secret="app-secret")
    )
    channel._delivery_store = store
    channel._delivery_channel_name = "qq-main"

    with _blocked_journal(store):
        channel._enqueue_message(
            SimpleNamespace(
                id="message-1",
                author=SimpleNamespace(user_openid="user-1"),
                content="hello",
            ),
            is_group=False,
        )

    assert channel._inbound_queue.get_nowait().content == "hello"
    store.close()


def test_transport_lease_uses_fencing_and_exclusive_ownership(tmp_path) -> None:
    path = tmp_path / "channel_delivery.sqlite"
    first_store = ChannelDeliveryStore(path)
    second_store = ChannelDeliveryStore(path)
    try:
        first = first_store.acquire_transport_lease(
            "wecom",
            "bot-account",
            "gateway-a",
            ttl_seconds=30,
        )
        assert first is not None
        assert first.fencing_token == 1
        assert (
            second_store.acquire_transport_lease(
                "wecom",
                "bot-account",
                "gateway-b",
                ttl_seconds=30,
            )
            is None
        )

        renewed = first_store.renew_transport_lease(first, ttl_seconds=30)
        assert renewed is not None
        assert renewed.fencing_token == first.fencing_token
        assert first_store.release_transport_lease(renewed) is True

        second = second_store.acquire_transport_lease(
            "wecom",
            "bot-account",
            "gateway-b",
            ttl_seconds=30,
        )
        assert second is not None
        assert second.fencing_token == 2
    finally:
        first_store.close()
        second_store.close()


def test_manager_construction_does_not_recover_an_active_owners_claim(tmp_path) -> None:
    owner = ChannelDeliveryStore(tmp_path / "channel_delivery.sqlite")
    message = _message()
    assert owner.accept_inbound("discord-main", message) is True
    claim = owner.claim_inbound("discord-main", message)
    assert claim is not None

    manager = ChannelManager.from_config(
        [DiscordChannelEntry(name="discord-main", token="synthetic-token")],
        turn_runner=object(),
        session_manager=object(),
        config=SimpleNamespace(state_dir=str(tmp_path)),
    )
    try:
        diagnostics = owner.diagnostics("discord-main")
        assert diagnostics["ingress"]["processing"]["count"] == 1
        owner.complete_inbound(claim, "turn_dispatched")
        assert owner.diagnostics("discord-main")["ingress"]["completed"]["count"] == 1
    finally:
        manager._delivery_store.close()
        owner.close()


@pytest.mark.asyncio
async def test_stop_failure_still_releases_transport_lease() -> None:
    adapter = SimpleNamespace(stop=AsyncMock(side_effect=RuntimeError("stop failed")))
    delivery_store = MagicMock()
    lease = object()
    manager = ChannelManager(
        _channels={"discord-main": adapter},
        _turn_runner=object(),
        _session_manager=object(),
        _delivery_store=delivery_store,
        _transport_leases={"discord-main": lease},
    )
    manager._unregister_tool_channel = MagicMock()

    with pytest.raises(RuntimeError, match="stop failed"):
        await manager.stop_channel("discord-main")

    delivery_store.release_transport_lease.assert_called_once_with(lease)
    manager._unregister_tool_channel.assert_called_once_with("discord-main", adapter)
    assert manager._transport_leases == {}


@pytest.mark.asyncio
async def test_outbox_records_provider_receipt(tmp_path) -> None:
    store = ChannelDeliveryStore(tmp_path / "channel_delivery.sqlite")

    class Channel:
        _delivery_store = store
        _delivery_channel_name = "discord-main"

        async def send(self, message: OutgoingMessage) -> ChannelSendResult:
            assert message.metadata.get("delivery_id")
            return ChannelSendResult.sent(
                capability=ChannelCapabilities.GROUP_CHAT,
                target_id=str(message.reply_to or ""),
                provider_message_id="provider-1",
            )

    channel = Channel()
    channel._delivery_raw_send = channel.send

    await deliver_with_outbox(
        channel,
        OutgoingMessage(content="hello", reply_to="chat-1"),
    )

    diagnostics = store.diagnostics("discord-main")
    assert diagnostics["outbox"]["sent"]["count"] == 1
    store.close()


@pytest.mark.asyncio
async def test_outbox_marks_ambiguous_exception_unknown_without_retry(tmp_path) -> None:
    store = ChannelDeliveryStore(tmp_path / "channel_delivery.sqlite")
    attempts = 0

    class Channel:
        _delivery_store = store
        _delivery_channel_name = "discord-main"

        async def send(self, message: OutgoingMessage) -> None:
            nonlocal attempts
            attempts += 1
            raise TimeoutError("provider outcome unknown")

    channel = Channel()
    channel._delivery_raw_send = channel.send

    with pytest.raises(TimeoutError):
        await deliver_with_outbox(
            channel,
            OutgoingMessage(content="hello", reply_to="chat-1"),
        )

    assert attempts == 1
    diagnostics = store.diagnostics("discord-main")
    assert diagnostics["outbox"]["unknown"]["count"] == 1
    store.close()


@pytest.mark.asyncio
async def test_outbox_wraps_declared_file_edit_delete_reaction_and_streaming(
    tmp_path,
) -> None:
    store = ChannelDeliveryStore(tmp_path / "channel_delivery.sqlite")
    calls: list[tuple[str, tuple[object, ...]]] = []

    class Channel:
        _delivery_store = store
        _delivery_channel_name = "complete-main"
        capability_profile = ChannelCapabilityProfile(
            channel_type="complete",
            native_file_upload=True,
            reactions=True,
            edit=True,
            delete=True,
        )

        async def send(self, message: OutgoingMessage) -> ChannelSendResult:
            calls.append(("send", (message,)))
            return ChannelSendResult.sent(capability="message")

        async def send_file(
            self,
            chat_id: str,
            file_path: str,
            content: str = "",
        ) -> ChannelSendResult:
            calls.append(("send_file", (chat_id, file_path, content)))
            return ChannelSendResult.sent(
                capability=ChannelCapabilities.NATIVE_FILE_UPLOAD,
                target_id=chat_id,
                provider_file_id="file-1",
            )

        async def edit(self, message_id: str, content: str) -> None:
            calls.append(("edit", (message_id, content)))

        async def delete(self, message_id: str) -> None:
            calls.append(("delete", (message_id,)))

        async def set_reaction(
            self,
            chat_id: str,
            message_id: str,
            emoji: str,
        ) -> ChannelSendResult:
            calls.append(("set_reaction", (chat_id, message_id, emoji)))
            return ChannelSendResult.sent(
                capability=ChannelCapabilities.REACTIONS,
                target_id=chat_id,
                provider_message_id=message_id,
            )

        async def send_streaming(self, chunks, *, channel_id: str | None = None) -> str:
            rendered = "".join([chunk async for chunk in chunks])
            calls.append(("send_streaming", (rendered, channel_id)))
            return "stream-message-1"

    async def chunks():
        yield "one"
        yield "two"

    channel = Channel()
    install_outbox(channel)

    await channel.send_file("chat-1", "/private/local/file.txt", "caption")
    await channel.edit("chat-1|message-1", "replacement")
    await channel.delete("chat-1|message-1")
    await channel.set_reaction("chat-1", "message-1", "✅")
    await channel.send_streaming(chunks(), channel_id="chat-1")

    with sqlite3.connect(store.path) as connection:
        rows = connection.execute(
            "SELECT capability, state, target_id, message_json "
            "FROM channel_outbox ORDER BY created_at"
        ).fetchall()

    assert [row[0] for row in rows] == [
        "native_file_upload",
        "edit",
        "delete",
        "reactions",
        "send_streaming",
    ]
    assert [row[1] for row in rows] == [
        "sent",
        "sent_unconfirmed",
        "sent_unconfirmed",
        "sent",
        "sent",
    ]
    assert all(row[2] == "chat-1" or row[2].startswith("chat-1|") for row in rows)
    assert "/private/local/file.txt" not in "".join(row[3] for row in rows)
    assert len(calls) == 5
    store.close()


@pytest.mark.asyncio
async def test_outbox_only_wraps_declared_operations_and_redacts_failure(
    tmp_path,
) -> None:
    store = ChannelDeliveryStore(tmp_path / "channel_delivery.sqlite")

    class Channel:
        _delivery_store = store
        _delivery_channel_name = "minimal-main"
        capability_profile = ChannelCapabilityProfile(channel_type="minimal")

        async def send(self, message: OutgoingMessage) -> None:
            return None

        async def edit(self, message_id: str, content: str) -> None:
            raise AssertionError("unsupported stub must remain unwrapped")

        async def send_streaming(self, chunks, *, channel_id: str | None = None) -> None:
            del chunks, channel_id
            raise RuntimeError("bot token=do-not-persist")

    channel = Channel()
    raw_edit = channel.edit
    install_outbox(channel)

    assert channel.edit == raw_edit
    assert not hasattr(channel, "_delivery_raw_edit")
    with pytest.raises(RuntimeError, match="do-not-persist"):
        await channel.send_streaming(None, channel_id="chat-1")

    with sqlite3.connect(store.path) as connection:
        row = connection.execute(
            "SELECT capability, state, error_class, error_message FROM channel_outbox"
        ).fetchone()
    capability, state, error_class, error_message = row
    assert (capability, state) == ("send_streaming", "unknown")
    # A bare RuntimeError carries no status, no retry hint, and no declared
    # class, so it must park rather than be guessed into the taxonomy.
    assert error_class == UNCLASSIFIED_ERROR_CLASS
    # The credential stays redacted; the exception type is retained alongside
    # it now that error_class carries the taxonomy value instead.
    assert error_message == "RuntimeError: bot token=[REDACTED]"
    assert "do-not-persist" not in error_message
    store.close()


def test_fail_send_persists_the_taxonomy_class_not_the_exception_type(tmp_path) -> None:
    # The outbox's error_class column is what doctor alerts on and what the
    # console renders operator cause lines from. Storing type(error).__name__
    # ("HTTPStatusError") made it unusable for any decision.
    store = ChannelDeliveryStore(tmp_path / "channel_delivery.sqlite")
    request = httpx.Request("POST", "https://provider.example/send")
    response = httpx.Response(401, request=request)

    send_id = store.begin_send(
        "slack-main",
        OutgoingMessage(content="hi", reply_to="C1"),
    )
    store.fail_send(send_id, httpx.HTTPStatusError("nope", request=request, response=response))

    with sqlite3.connect(store.path) as connection:
        state, error_class, error_message = connection.execute(
            "SELECT state, error_class, error_message FROM channel_outbox WHERE send_id = ?",
            (send_id,),
        ).fetchone()

    assert state == "unknown"
    assert error_class == "auth_invalid"
    # The concrete type stays available for debugging rather than being lost.
    assert "HTTPStatusError" in error_message
    store.close()


def test_fail_send_parks_an_unclassifiable_error_without_guessing(tmp_path) -> None:
    store = ChannelDeliveryStore(tmp_path / "channel_delivery.sqlite")
    send_id = store.begin_send("slack-main", OutgoingMessage(content="hi", reply_to="C1"))

    store.fail_send(send_id, ValueError("something bespoke"))

    with sqlite3.connect(store.path) as connection:
        error_class = connection.execute(
            "SELECT error_class FROM channel_outbox WHERE send_id = ?", (send_id,)
        ).fetchone()[0]

    assert error_class == UNCLASSIFIED_ERROR_CLASS
    store.close()
