from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import opensquilla.gateway.rpc_channels  # noqa: F401
from opensquilla.channels._util import ChannelAccessPolicy, ChannelDmAccess
from opensquilla.channels.admission import decide_channel_admission
from opensquilla.channels.delivery_store import ChannelDeliveryStore
from opensquilla.channels.manager import ChannelManager
from opensquilla.channels.types import (
    AuthenticatedPrincipal,
    IncomingMessage,
    IngressProvenance,
    IngressVerification,
    OutgoingMessage,
)
from opensquilla.gateway.auth import Principal
from opensquilla.gateway.channel_dispatch import run_channel_dispatch
from opensquilla.gateway.config import (
    DingTalkChannelEntry,
    DiscordChannelEntry,
    MatrixChannelEntry,
    QQChannelEntry,
)
from opensquilla.gateway.rpc import RpcContext, get_dispatcher


def _message(*, event_id: str = "event-1", content: str = "private input") -> IncomingMessage:
    return IncomingMessage(
        sender_id="user-42",
        channel_id="dm-9",
        content=content,
        metadata={"is_group": False, "conversation_kind": "dm"},
        provenance=IngressProvenance(
            provider="telegram",
            account_id="bot-account",
            transport="polling",
            verification=IngressVerification.OAUTH_TOKEN,
            event_id=event_id,
            principal=AuthenticatedPrincipal(
                subject_id="user-42",
                display_name="Alice",
            ),
        ),
    )


@dataclass
class _Channel:
    policy: ChannelAccessPolicy = field(default_factory=ChannelAccessPolicy)


def test_authenticated_dm_defaults_to_durable_pending_pairing(tmp_path: Path) -> None:
    store = ChannelDeliveryStore(tmp_path / "delivery.sqlite")
    channel = _Channel()
    channel._delivery_store = store
    channel._delivery_channel_name = "telegram-main"

    decision = decide_channel_admission(channel, _message(), "agent:main:telegram:dm:user-42")

    assert decision.admit is False
    assert decision.reason == "pairing_required"
    assert decision.pairing_id
    assert decision.pairing_notice is True
    record = store.list_pairings(channel_name="telegram-main")[0]
    assert record.status == "pending"
    assert record.sender_id == "user-42"
    assert record.sender_name == "Alice"
    store.close()


def test_pairing_persists_approval_and_revocation_without_message_content(
    tmp_path: Path,
) -> None:
    path = tmp_path / "delivery.sqlite"
    secret_content = "do not persist this inbound message"
    store = ChannelDeliveryStore(path)
    channel = _Channel()
    channel._delivery_store = store
    channel._delivery_channel_name = "telegram-main"
    pending = decide_channel_admission(
        channel,
        _message(content=secret_content),
        "agent:main:telegram:dm:user-42",
    )
    assert pending.pairing_id
    store.set_pairing_status(
        channel_name="telegram-main",
        pairing_id=pending.pairing_id,
        status="approved",
    )
    store.close()

    reopened = ChannelDeliveryStore(path)
    channel = _Channel()
    # The fresh adapter must be connected to the reopened durable store.
    channel._delivery_store = reopened
    channel._delivery_channel_name = "telegram-main"
    approved = decide_channel_admission(
        channel,
        _message(event_id="event-2", content=secret_content),
        "agent:main:telegram:dm:user-42",
    )
    assert approved.admit is True
    reopened.set_pairing_status(
        channel_name="telegram-main",
        pairing_id=pending.pairing_id,
        status="revoked",
    )
    revoked = decide_channel_admission(
        channel,
        _message(event_id="event-3", content=secret_content),
        "agent:main:telegram:dm:user-42",
    )
    assert revoked.admit is False
    assert revoked.reason == "pairing_revoked"
    reopened.close()

    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT sender_id, sender_name FROM channel_pairings"
        ).fetchone()
    assert row == ("user-42", "Alice")
    assert secret_content not in path.read_bytes().decode("utf-8", errors="ignore")


@pytest.mark.parametrize(
    ("policy", "sender_id", "admitted"),
    [
        (ChannelAccessPolicy(dm_access=ChannelDmAccess.OPEN), "any-user", True),
        (
            ChannelAccessPolicy(
                dm_access=ChannelDmAccess.ALLOWLIST,
                allowlist=frozenset({"user-42"}),
            ),
            "user-42",
            True,
        ),
        (
            ChannelAccessPolicy(
                dm_access=ChannelDmAccess.ALLOWLIST,
                allowlist=frozenset({"another-user"}),
            ),
            "user-42",
            False,
        ),
    ],
)
def test_explicit_open_and_allowlist_modes(
    policy: ChannelAccessPolicy,
    sender_id: str,
    admitted: bool,
) -> None:
    message = _message().model_copy(
        update={
            "sender_id": sender_id,
            "provenance": IngressProvenance(
                provider="telegram",
                account_id="bot-account",
                verification=IngressVerification.OAUTH_TOKEN,
                principal=AuthenticatedPrincipal(subject_id=sender_id),
            ),
        }
    )
    decision = decide_channel_admission(
        _Channel(policy=policy),
        message,
        f"agent:main:telegram:dm:{sender_id}",
    )
    assert decision.admit is admitted


@pytest.mark.parametrize(
    "entry",
    [
        DiscordChannelEntry(
            name="discord-main",
            token="test-token",
            dm_access="allowlist",
            allowed_senders="user-42, user-7",
        ),
        DingTalkChannelEntry(
            name="dingtalk-main",
            client_id="test-id",
            client_secret="test-secret",
            dm_access="allowlist",
            allowed_senders="user-42, user-7",
        ),
        MatrixChannelEntry(
            name="matrix-main",
            homeserver_url="https://matrix.invalid",
            user_id="@bot:matrix.invalid",
            access_token="test-token",
            dm_access="allowlist",
            allowed_senders="user-42, user-7",
        ),
        QQChannelEntry(
            name="qq-main",
            app_id="test-id",
            app_secret="test-secret",
            dm_access="allowlist",
            allowed_senders="user-42, user-7",
        ),
    ],
    ids=["declared-policy", "dingtalk", "matrix", "qq"],
)
def test_manager_wires_entry_access_fields_without_leaking_them_to_adapter_config(
    tmp_path: Path,
    entry: Any,
) -> None:
    manager = ChannelManager.from_config(
        [entry],
        turn_runner=object(),
        session_manager=object(),
        config=SimpleNamespace(state_dir=str(tmp_path)),
    )
    try:
        adapter = manager.get(entry.name)
        assert adapter is not None
        assert adapter.policy.dm_access == ChannelDmAccess.ALLOWLIST
        assert adapter.policy.allowlist == frozenset({"user-42", "user-7"})
    finally:
        manager._delivery_store.close()


@dataclass
class _DispatchChannel:
    message: IncomingMessage
    store: ChannelDeliveryStore
    sent: list[OutgoingMessage] = field(default_factory=list)
    policy: ChannelAccessPolicy = field(default_factory=ChannelAccessPolicy)
    calls: int = 0

    def __post_init__(self) -> None:
        self._delivery_store = self.store
        self._delivery_channel_name = "telegram-main"

    async def receive(self) -> IncomingMessage:
        self.calls += 1
        if self.calls == 1:
            return self.message
        raise asyncio.CancelledError

    async def send(self, message: OutgoingMessage) -> None:
        self.sent.append(message)


@pytest.mark.asyncio
async def test_pending_pairing_notice_precedes_all_session_and_tool_side_effects(
    tmp_path: Path,
) -> None:
    store = ChannelDeliveryStore(tmp_path / "delivery.sqlite")
    message = _message()
    assert store.accept_inbound("telegram-main", message) is True
    channel = _DispatchChannel(message=message, store=store)

    class Forbidden:
        def __getattr__(self, name: str) -> Any:
            raise AssertionError(f"unexpected side effect: {name}")

    with pytest.raises(asyncio.CancelledError):
        await run_channel_dispatch(
            channel=channel,
            turn_runner=Forbidden(),
            session_manager=Forbidden(),
            session_key_builder=lambda _msg: "agent:main:telegram:dm:user-42",
            session_prefix="telegram-main",
        )

    assert len(channel.sent) == 1
    notice = channel.sent[0]
    assert "pairing" in notice.content.lower()
    assert "private input" not in notice.content
    assert notice.metadata["pairing_required"] is True
    assert len(notice.metadata["pairing_code"]) == 8
    with sqlite3.connect(store.path) as connection:
        persisted = connection.execute(
            "SELECT state, disposition, message_json FROM channel_ingress"
        ).fetchone()
    assert persisted == ("completed", "admission_denied", "{}")
    store.close()


@pytest.mark.asyncio
async def test_pairing_rpc_contract_and_scope(tmp_path: Path) -> None:
    store = ChannelDeliveryStore(tmp_path / "delivery.sqlite")
    pending = store.request_pairing(
        channel_name="telegram-main",
        provider="telegram",
        account_id="bot-account",
        sender_id="user-42",
        sender_name="Alice",
    )

    class Manager:
        _delivery_store = store

    admin = RpcContext(
        conn_id="admin",
        principal=Principal(
            role="operator",
            scopes=frozenset({"operator.admin"}),
            is_owner=True,
            authenticated=True,
        ),
        channel_manager=Manager(),
    )
    listed = await get_dispatcher().dispatch(
        "r1",
        "channels.pairings",
        {"channelName": "telegram-main"},
        admin,
    )
    assert listed.error is None
    assert listed.payload == {
        "pairings": [
            {
                "pairingId": pending.pairing_id,
                "pairingCode": pending.pairing_id[:8],
                "channelName": "telegram-main",
                "senderId": "user-42",
                "senderName": "Alice",
                "status": "pending",
                "createdAt": listed.payload["pairings"][0]["createdAt"],
                "approvedAt": None,
            }
        ]
    }
    approved = await get_dispatcher().dispatch(
        "r2",
        "channels.pairing.approve",
        {"channelName": "telegram-main", "pairingId": pending.pairing_id},
        admin,
    )
    assert approved.error is None
    assert approved.payload["pairing"]["status"] == "approved"
    assert approved.payload["pairing"]["approvedAt"]
    revoked = await get_dispatcher().dispatch(
        "r3",
        "channels.pairing.revoke",
        {"channelName": "telegram-main", "pairingId": pending.pairing_id},
        admin,
    )
    assert revoked.error is None
    assert revoked.payload["pairing"]["status"] == "revoked"

    read_only = RpcContext(
        conn_id="reader",
        principal=Principal(
            role="operator",
            scopes=frozenset({"operator.read"}),
            is_owner=False,
            authenticated=True,
        ),
        channel_manager=Manager(),
    )
    denied = await get_dispatcher().dispatch(
        "r4",
        "channels.pairings",
        {"channelName": "telegram-main"},
        read_only,
    )
    assert denied.error is not None
    assert denied.error.code == "UNAUTHORIZED"
    store.close()


def test_pairing_store_adds_reply_to_column_to_a_preexisting_database(tmp_path):
    """A store created before reply_to existed must not break on upgrade.

    CREATE TABLE IF NOT EXISTS is a no-op on an existing table, so without an
    explicit column migration every pairing read would raise "no such column".
    """
    path = tmp_path / "legacy.sqlite"
    legacy = sqlite3.connect(path)
    legacy.executescript(
        """
        CREATE TABLE channel_pairings (
            pairing_id  TEXT PRIMARY KEY,
            channel_name TEXT NOT NULL,
            provider     TEXT NOT NULL,
            account_id   TEXT NOT NULL,
            sender_id    TEXT NOT NULL,
            sender_name  TEXT,
            status       TEXT NOT NULL,
            created_at   REAL NOT NULL,
            last_seen_at REAL NOT NULL,
            approved_at  REAL,
            revoked_at   REAL,
            request_count INTEGER NOT NULL DEFAULT 1,
            UNIQUE (channel_name, account_id, sender_id)
        );
        INSERT INTO channel_pairings
        (pairing_id, channel_name, provider, account_id, sender_id, sender_name,
         status, created_at, last_seen_at, request_count)
        VALUES ('old', 'work', 'slack', 'acct', 'U-1', 'Ada', 'approved', 1.0, 1.0, 1);
        """
    )
    legacy.commit()
    legacy.close()

    store = ChannelDeliveryStore(path)
    try:
        rows = store.list_pairings(channel_name="work")
        assert [row.pairing_id for row in rows] == ["old"]
        assert rows[0].reply_to is None  # legacy row predates the captured address

        fresh = store.request_pairing(
            channel_name="work",
            provider="slack",
            account_id="acct",
            sender_id="U-2",
            reply_to="dm-2",
        )
        assert fresh.reply_to == "dm-2"
    finally:
        store.close()


def test_pairing_request_captures_and_refreshes_the_reply_address(tmp_path):
    store = ChannelDeliveryStore(tmp_path / "delivery.sqlite")
    try:
        first = store.request_pairing(
            channel_name="work",
            provider="slack",
            account_id="acct",
            sender_id="U-1",
            reply_to="dm-1",
        )
        assert first.reply_to == "dm-1"

        # A later request from the same sender refreshes the address...
        moved = store.request_pairing(
            channel_name="work",
            provider="slack",
            account_id="acct",
            sender_id="U-1",
            reply_to="dm-2",
        )
        assert moved.reply_to == "dm-2"

        # ...but a request without one keeps the last known address.
        kept = store.request_pairing(
            channel_name="work",
            provider="slack",
            account_id="acct",
            sender_id="U-1",
        )
        assert kept.reply_to == "dm-2"
    finally:
        store.close()
