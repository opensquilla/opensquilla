"""DiscordChannel: adapter for Discord Bot Gateway (WebSocket) and REST API."""

from __future__ import annotations

import asyncio
import json
import random
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import httpx
import structlog
import websockets
import websockets.asyncio.client
from pydantic import BaseModel

from opensquilla.channels._attachment_io import (
    attachment_limit_for_mime,
    ensure_declared_size_within_limit,
    fetch_httpx_bytes_limited,
    preferred_attachment_mime,
)
from opensquilla.channels._util import (
    ChannelAccessPolicy,
    EventDedupeCache,
    RateLimiter,
    StreamThrottle,
    retry_request,
    split_text_for_channel,
)
from opensquilla.channels.contract import (
    ChannelCapabilities,
    ChannelCapabilityProfile,
    ChannelPlatformCapability,
    ChannelPlatformCapabilityStatus,
    ChannelPlatformCategories,
    ChannelPlatformManifest,
    ChannelSendResult,
)
from opensquilla.channels.types import (
    Attachment,
    ChannelHealth,
    IncomingMessage,
    OutgoingMessage,
)
from opensquilla.env import trust_env as _trust_env

log = structlog.get_logger(__name__)

_DISCORD_MENTION_RE = re.compile(r"<@!?(\d+)>")
_DISCORD_DM_CHANNEL_TYPES = {1}
# Discord rejects message content longer than 2000 characters.
_DISCORD_MAX_MESSAGE_CHARS = 2000
_DISCORD_GROUP_DM_CHANNEL_TYPES = {3}
_DISCORD_THREAD_CHANNEL_TYPES = {10, 11, 12}

# Gateway intents bitmask
GATEWAY_INTENTS = (
    (1 << 0)  # GUILDS
    | (1 << 9)  # GUILD_MESSAGES
    | (1 << 12)  # DIRECT_MESSAGES
    | (1 << 15)  # MESSAGE_CONTENT (privileged)
    | (1 << 10)  # GUILD_MESSAGE_REACTIONS
)

# Channel-contract constants pinned by the adapter audit.
CAPABILITY_TIER = "GREEN-shipping"

# Discord is a DM/group channel; the permission matrix denies admin-only tools.
DM_SAFETY_TIERS: tuple[str, ...] = ("safe", "confirm")

RETRYABLE_ERROR_CLASSES: tuple[str, ...] = (
    "transport_transient",
    "rate_limited",
    "channel_degraded",
)
FATAL_ERROR_CLASSES: tuple[str, ...] = (
    "auth_invalid",
    "payload_rejected",
    "target_missing",
    "contract_violation",
)


class DiscordChannelConfig(BaseModel):
    """Pydantic config for Discord channel adapter."""

    token: str
    application_id: str = ""
    default_channel_id: str = ""
    api_base: str = "https://discord.com/api/v10"
    gateway_url: str = "wss://gateway.discord.gg/?v=10&encoding=json"
    intents: int = GATEWAY_INTENTS
    reconnect_max_retries: int = 5
    reconnect_base_delay_s: float = 1.0

    model_config = {}  # explicit params only; no env loading


@dataclass
class _GatewayState:
    session_id: str | None = None
    sequence: int | None = None
    resume_url: str | None = None
    heartbeat_interval_ms: int = 41250
    last_heartbeat_ack: bool = True


@dataclass
class DiscordChannel:
    """Channel adapter for Discord via Gateway WebSocket and REST API.

    Uses the ``websockets`` library for the gateway connection
    and ``httpx.AsyncClient`` for REST calls.
    """

    config: DiscordChannelConfig
    bot_user_id: str | None = None
    supports_slash_commands: bool = True
    # Discord mirrors slack/feishu: DMs admit, groups require mention.
    policy: ChannelAccessPolicy = field(
        default_factory=lambda: ChannelAccessPolicy(
            dm_allowed=True,
            group_allowed=True,
            mention_required_in_group=True,
            allowlist=frozenset(),
        )
    )

    _queue: asyncio.Queue[IncomingMessage] = field(
        default_factory=asyncio.Queue, init=False, repr=False
    )
    _client: httpx.AsyncClient | None = field(default=None, init=False, repr=False)
    _connected: bool = field(default=False, init=False, repr=False)
    _last_message_at: datetime | None = field(default=None, init=False, repr=False)
    _ws: Any = field(default=None, init=False, repr=False)
    _state: _GatewayState = field(default_factory=_GatewayState, init=False, repr=False)
    _heartbeat_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _dispatch_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _reconnect_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _reconnecting: bool = field(default=False, init=False, repr=False)
    _dedupe: EventDedupeCache = field(
        default_factory=lambda: EventDedupeCache(max_size=10_000),
        init=False,
        repr=False,
    )
    _rate_limiter: RateLimiter = field(default_factory=RateLimiter, init=False, repr=False)
    _sent_messages: dict[str, str] = field(default_factory=dict, init=False, repr=False)
    _channel_types: dict[str, int] = field(default_factory=dict, init=False, repr=False)
    _thread_parent_channels: dict[str, str] = field(
        default_factory=dict, init=False, repr=False
    )

    @property
    def capability_profile(self) -> ChannelCapabilityProfile:
        return ChannelCapabilityProfile(
            channel_type="discord",
            group_chat=True,
            mentions=True,
            typing_indicator=True,
            native_file_upload=True,
            media=True,
            reactions=True,
            inbound_reactions=True,
            threads=True,
            group_dm=True,
            edit=True,
            delete=True,
            transports=("websocket",),
        )

    @property
    def platform_capability_manifest(self) -> ChannelPlatformManifest:
        return ChannelPlatformManifest.from_channel_profile(
            self.capability_profile,
            has_send_file=True,
            has_inbound_attachment_resolver=True,
        ).with_capabilities(
            ChannelPlatformCapability(
                category=ChannelPlatformCategories.FILES,
                status=ChannelPlatformCapabilityStatus.SUPPORTED,
                tools=("multipart/form-data message attachments",),
                mutates=True,
                notes=("Discord file delivery attaches files to create-message requests.",),
            ),
            ChannelPlatformCapability(
                category=ChannelPlatformCategories.ATTACHMENTS,
                status=ChannelPlatformCapabilityStatus.SUPPORTED,
                tools=("attachment.url",),
                notes=("Inbound Discord attachments are downloaded from message attachment URLs.",),
            ),
            ChannelPlatformCapability(
                category=ChannelPlatformCategories.THREADS,
                status=ChannelPlatformCapabilityStatus.SUPPORTED,
                notes=("Discord thread channels are detected from channel type metadata.",),
            ),
        )

    @property
    def capabilities(self) -> frozenset[str]:
        return self.capability_profile.capability_tags()

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.config.api_base,
                timeout=30.0,
                trust_env=_trust_env(),
            )
        return self._client

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bot {self.config.token}"}

    # ------------------------------------------------------------------
    # Gateway WebSocket helpers
    # ------------------------------------------------------------------

    async def _connect_ws(self, url: str) -> Any:
        ws = await websockets.asyncio.client.connect(url)
        return ws

    async def _ws_send(self, payload: dict[str, Any]) -> None:
        if self._ws is not None:
            await self._ws.send(json.dumps(payload))

    async def _ws_recv(self) -> dict[str, Any]:
        raw = await self._ws.recv()
        return cast(dict[str, Any], json.loads(raw))

    async def _close_ws(self) -> None:
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def _fetch_gateway_url(self) -> str:
        client = self._get_client()
        resp = await client.get("/gateway/bot", headers=self._auth_headers())
        resp.raise_for_status()
        return cast(str, resp.json()["url"]) + "?v=10&encoding=json"

    async def _identify(self) -> None:
        await self._ws_send(
            {
                "op": 2,
                "d": {
                    "token": self.config.token,
                    "intents": self.config.intents,
                    "properties": {
                        "os": "linux",
                        "browser": "opensquilla",
                        "device": "opensquilla",
                    },
                },
            }
        )

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    async def _heartbeat_loop(self) -> None:
        while self._connected:
            if not self._state.last_heartbeat_ack:
                log.warning("discord.heartbeat_timeout")
                await self._reconnect()
                return
            self._state.last_heartbeat_ack = False
            await self._ws_send({"op": 1, "d": self._state.sequence})
            await asyncio.sleep(self._state.heartbeat_interval_ms / 1000.0)

    # ------------------------------------------------------------------
    # Reconnection
    # ------------------------------------------------------------------

    async def _reconnect(self) -> None:
        """Re-establish the gateway connection.

        Idempotent under concurrent calls: a second invocation while a
        first is in flight is a no-op. Without this guard a heartbeat
        timeout racing an op-7 / op-9 in the dispatch loop could trigger
        two simultaneous IDENTIFY sequences and leave two heartbeat tasks
        running against the same socket.
        """
        if self._reconnecting:
            log.info("discord.reconnect_skipped_already_in_flight")
            return
        async with self._reconnect_lock:
            self._reconnecting = True
            try:
                await self._do_reconnect()
            finally:
                self._reconnecting = False

    async def _do_reconnect(self) -> None:
        log.info("discord.reconnecting", session_id=self._state.session_id)
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        await self._close_ws()

        url = self._state.resume_url or await self._fetch_gateway_url()
        self._ws = await self._connect_ws(url)
        hello = await self._ws_recv()
        self._state.heartbeat_interval_ms = hello["d"]["heartbeat_interval"]

        if self._state.session_id and self._state.sequence is not None:
            await self._ws_send(
                {
                    "op": 6,
                    "d": {
                        "token": self.config.token,
                        "session_id": self._state.session_id,
                        "seq": self._state.sequence,
                    },
                }
            )
        else:
            await self._identify()

        self._state.last_heartbeat_ack = True
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    # ------------------------------------------------------------------
    # Dispatch loop
    # ------------------------------------------------------------------

    async def _dispatch_loop(self) -> None:
        while self._connected:
            try:
                raw = await self._ws_recv()
            except (
                websockets.exceptions.ConnectionClosed,
                websockets.exceptions.ConnectionClosedError,
                websockets.exceptions.ConnectionClosedOK,
            ):
                if self._connected:
                    await self._reconnect()
                return

            op = raw.get("op")
            if op == 0:  # Dispatch
                self._state.sequence = raw.get("s")
                event_type = raw.get("t")
                data = raw.get("d", {})
                await self._handle_dispatch(event_type, data)
            elif op == 1:  # Heartbeat request
                await self._ws_send({"op": 1, "d": self._state.sequence})
            elif op == 7:  # Reconnect
                await self._reconnect()
                return
            elif op == 9:  # Invalid Session
                resumable = raw.get("d", False)
                if not resumable:
                    self._state.session_id = None
                    self._state.sequence = None
                await asyncio.sleep(1 + random.random() * 4)
                await self._reconnect()
                return
            elif op == 11:  # Heartbeat ACK
                self._state.last_heartbeat_ack = True

    async def _handle_dispatch(self, event_type: str | None, data: dict[str, Any]) -> None:
        if event_type == "READY":
            self._state.session_id = data["session_id"]
            self._state.resume_url = data.get("resume_gateway_url")
            self.bot_user_id = data["user"]["id"]
            log.info(
                "discord.ready",
                user=data["user"]["username"],
                guilds=len(data.get("guilds", [])),
            )
        elif event_type == "MESSAGE_CREATE":
            if data.get("author", {}).get("id") == self.bot_user_id:
                return
            msg_id = str(data.get("id") or "")
            if msg_id and not self._dedupe.check_and_add(f"message:{msg_id}"):
                return
            msg = self.parse_event(self._annotate_channel_context(data))
            self.enqueue(msg)
        elif event_type == "MESSAGE_REACTION_ADD":
            reaction_key = self._reaction_dedupe_key(data)
            if reaction_key and not self._dedupe.check_and_add(reaction_key):
                return
            self._enqueue_reaction(self._annotate_channel_context(data))
        elif event_type == "INTERACTION_CREATE":
            interaction_id = str(data.get("id") or "")
            if interaction_id and not self._dedupe.check_and_add(
                f"interaction:{interaction_id}"
            ):
                return
            self._handle_interaction(self._annotate_channel_context(data))
        elif event_type in {"CHANNEL_CREATE", "CHANNEL_UPDATE", "THREAD_CREATE", "THREAD_UPDATE"}:
            self._cache_channel_context(data)
        elif event_type == "GUILD_CREATE":
            for channel in data.get("channels", []):
                if isinstance(channel, dict):
                    self._cache_channel_context(channel)
            for thread in data.get("threads", []):
                if isinstance(thread, dict):
                    self._cache_channel_context(thread)
        elif event_type == "THREAD_LIST_SYNC":
            for thread in data.get("threads", []):
                if isinstance(thread, dict):
                    self._cache_channel_context(thread)
        elif event_type == "RESUMED":
            log.info("discord.resumed")

    def _cache_channel_context(self, data: dict[str, Any]) -> None:
        channel_id = data.get("id")
        channel_type = self._channel_type(data.get("type"))
        if isinstance(channel_id, str) and channel_id and channel_type is not None:
            self._channel_types[channel_id] = channel_type
        parent_id = data.get("parent_id")
        if (
            isinstance(channel_id, str)
            and channel_id
            and isinstance(parent_id, str)
            and parent_id
        ):
            self._thread_parent_channels[channel_id] = parent_id

    def _annotate_channel_context(self, data: dict[str, Any]) -> dict[str, Any]:
        channel_id = data.get("channel_id")
        if not isinstance(channel_id, str) or not channel_id:
            return data
        enriched = dict(data)
        if "channel_type" not in enriched and channel_id in self._channel_types:
            enriched["channel_type"] = self._channel_types[channel_id]
        if (
            "thread_parent_channel_id" not in enriched
            and channel_id in self._thread_parent_channels
        ):
            enriched["thread_parent_channel_id"] = self._thread_parent_channels[channel_id]
        return enriched

    @staticmethod
    def _reaction_dedupe_key(data: dict[str, Any]) -> str:
        emoji = data.get("emoji", {})
        emoji_key = emoji.get("id") or emoji.get("name") or ""
        if not data.get("message_id") or not data.get("user_id") or not emoji_key:
            return ""
        return (
            f"reaction:{data.get('message_id', '')}:"
            f"{data.get('user_id', '')}:{emoji_key}"
        )

    def _enqueue_reaction(self, data: dict[str, Any]) -> None:
        user_id = data.get("user_id", "unknown")
        channel_id = data.get("channel_id", "unknown")
        emoji = data.get("emoji", {})
        channel_type = self._channel_type(data.get("channel_type"))
        thread_id = self._native_thread_id(data, channel_type)
        conversation_kind = self._conversation_kind(data, channel_type, thread_id)
        parent_channel_id = data.get("thread_parent_channel_id")
        msg = IncomingMessage(
            sender_id=user_id,
            channel_id=channel_id,
            content="",
            metadata={
                "event_type": "MESSAGE_REACTION_ADD",
                "message_id": data.get("message_id"),
                "emoji_name": emoji.get("name", ""),
                "emoji_id": emoji.get("id"),
                "guild_id": data.get("guild_id"),
                "channel_type": channel_type,
                "is_group": conversation_kind in {"group", "group_dm", "thread", "topic"},
                "conversation_kind": conversation_kind,
                "native_message_id": data.get("message_id"),
                "native_chat_id": channel_id,
                "native_thread_id": thread_id,
                "native_parent_channel_id": parent_channel_id,
                "reply_target_id": data.get("message_id"),
            },
        )
        self.enqueue(msg)

    def _handle_interaction(self, data: dict[str, Any]) -> None:
        """Parse a slash command interaction into IncomingMessage."""
        interaction_data = data.get("data", {})
        user = data.get("member", {}).get("user", data.get("user", {}))
        channel_id = data.get("channel_id", "unknown")

        # Build content from command name and options
        command_name = interaction_data.get("name", "")
        options = interaction_data.get("options", [])
        option_parts = [opt.get("value", "") for opt in options if opt.get("value")]
        content = f"/{command_name} {' '.join(str(v) for v in option_parts)}".strip()
        channel_type = self._channel_type(data.get("channel_type"))
        thread_id = self._native_thread_id(data, channel_type)
        conversation_kind = self._conversation_kind(data, channel_type, thread_id)
        parent_channel_id = data.get("thread_parent_channel_id")

        msg = IncomingMessage(
            sender_id=user.get("id", "unknown"),
            channel_id=channel_id,
            content=content,
            metadata={
                "interaction_type": "slash_command",
                "command_name": command_name,
                "interaction_id": data.get("id"),
                "interaction_token": data.get("token"),
                "guild_id": data.get("guild_id"),
                "channel_type": channel_type,
                "is_group": conversation_kind in {"group", "group_dm", "thread", "topic"},
                "conversation_kind": conversation_kind,
                "native_message_id": data.get("id"),
                "native_chat_id": channel_id,
                "native_thread_id": thread_id,
                "native_parent_channel_id": parent_channel_id,
                "reply_target_id": data.get("id"),
            },
        )
        self.enqueue(msg)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Connect to the Discord gateway and begin dispatch/heartbeat loops."""
        url = self.config.gateway_url
        self._ws = await self._connect_ws(url)

        # Receive Hello
        hello = await self._ws_recv()
        self._state.heartbeat_interval_ms = hello["d"]["heartbeat_interval"]

        # Identify
        await self._identify()

        # Receive Ready
        ready = await self._ws_recv()
        if ready.get("t") == "READY":
            await self._handle_dispatch("READY", ready.get("d", {}))

        self._connected = True
        self._state.last_heartbeat_ack = True
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self._dispatch_task = asyncio.create_task(self._dispatch_loop())
        log.info("discord.started", bot_user_id=self.bot_user_id)

    async def stop(self) -> None:
        """Disconnect from gateway and clean up."""
        self._connected = False
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        if self._dispatch_task is not None:
            self._dispatch_task.cancel()
            self._dispatch_task = None
        await self._close_ws()
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        log.info("discord.stopped")

    def is_connected(self) -> bool:
        return self._connected

    async def health_check(self) -> ChannelHealth:
        return ChannelHealth(
            connected=self._connected,
            bot_user_id=self.bot_user_id,
            last_message_at=self._last_message_at,
            extra={
                "session_id": self._state.session_id,
                "sequence": self._state.sequence,
            },
        )

    # ------------------------------------------------------------------
    # Inbound
    # ------------------------------------------------------------------

    def enqueue(self, message: IncomingMessage) -> None:
        self._queue.put_nowait(message)
        self._last_message_at = datetime.now(UTC)

    async def receive(self) -> IncomingMessage:
        msg = await self._queue.get()
        log.debug("discord.receive", content=msg.content[:80])
        return msg

    async def resolve_inbound_attachment(self, attachment: Attachment) -> Attachment:
        """Fetch Discord attachment bytes; shared ingest owns validation."""

        if attachment.data is not None or not attachment.url:
            return attachment
        limit = attachment_limit_for_mime(attachment.mime_type)
        ensure_declared_size_within_limit(attachment.size, name=attachment.name, limit=limit)
        payload, content_type = await fetch_httpx_bytes_limited(
            self._get_client(),
            attachment.url,
            name=attachment.name,
            limit=limit,
        )
        return Attachment(
            name=attachment.name,
            mime_type=preferred_attachment_mime(content_type, attachment.mime_type),
            data=payload,
            size=len(payload),
            metadata={**attachment.metadata, "source_url": attachment.url},
        )

    def parse_event(self, data: dict[str, Any]) -> IncomingMessage:
        author = data.get("author", {})
        content = data.get("content", "")
        channel_id = data.get("channel_id", "unknown")
        message_id = data.get("id")
        channel_type = self._channel_type(data.get("channel_type"))
        thread_id = self._native_thread_id(data, channel_type)
        referenced_message_id = data.get("message_reference", {}).get("message_id")
        parent_channel_id = data.get("thread_parent_channel_id")
        if not isinstance(parent_channel_id, str):
            parent_channel_id = data.get("message_reference", {}).get("channel_id")
        conversation_kind = self._conversation_kind(data, channel_type, thread_id)
        is_group = conversation_kind in {"group", "group_dm", "thread", "topic"}

        attachments: list[Attachment] = []
        for att in data.get("attachments", []):
            attachments.append(
                Attachment(
                    name=att.get("filename", "unknown"),
                    mime_type=att.get("content_type"),
                    url=att.get("url"),
                    size=att.get("size"),
                )
            )

        metadata: dict[str, Any] = {
            "message_id": message_id,
            "channel_id": channel_id,
            "guild_id": data.get("guild_id"),
            "channel_type": channel_type,
            "is_group": is_group,
            "conversation_kind": conversation_kind,
            "thread_id": thread_id,
            "referenced_message_id": referenced_message_id,
            "native_message_id": message_id,
            "native_chat_id": channel_id,
            "native_thread_id": thread_id,
            "native_parent_id": referenced_message_id,
            "native_parent_channel_id": parent_channel_id,
            "native_root_id": referenced_message_id,
            "reply_target_id": message_id,
        }

        return IncomingMessage(
            sender_id=author.get("id", "unknown"),
            channel_id=channel_id,
            content=content,
            attachments=attachments,
            metadata=metadata,
        )

    @staticmethod
    def _channel_type(raw: Any) -> int | None:
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str) and raw.isdecimal():
            return int(raw)
        return None

    @staticmethod
    def _native_thread_id(data: dict[str, Any], channel_type: int | None) -> str | None:
        explicit = data.get("thread_id")
        if isinstance(explicit, str) and explicit:
            return explicit
        thread = data.get("thread")
        if isinstance(thread, dict):
            thread_id = thread.get("id")
            if isinstance(thread_id, str) and thread_id:
                return thread_id
        if channel_type in _DISCORD_THREAD_CHANNEL_TYPES:
            channel_id = data.get("channel_id")
            if isinstance(channel_id, str) and channel_id:
                return channel_id
        return None

    @staticmethod
    def _conversation_kind(
        data: dict[str, Any],
        channel_type: int | None,
        thread_id: str | None,
    ) -> str:
        if thread_id or channel_type in _DISCORD_THREAD_CHANNEL_TYPES:
            return "thread"
        if channel_type in _DISCORD_GROUP_DM_CHANNEL_TYPES:
            return "group_dm"
        if channel_type in _DISCORD_DM_CHANNEL_TYPES:
            return "dm"
        if data.get("guild_id") is not None:
            return "group"
        return "dm"

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------

    async def send(self, message: OutgoingMessage) -> ChannelSendResult:
        client = self._get_client()
        channel_id = message.reply_to or self.config.default_channel_id

        # Discord rejects message content over 2000 chars; split long replies
        # so the whole answer is delivered across sequential messages instead
        # of the API rejecting (and dropping) it.
        chunks = split_text_for_channel(message.content, _DISCORD_MAX_MESSAGE_CHARS)
        data: dict[str, Any] = {}
        for idx, chunk in enumerate(chunks):
            await self._rate_limiter.acquire()
            payload: dict[str, Any] = {"content": chunk}

            if idx == 0 and message.metadata.get("embeds"):
                payload["embeds"] = message.metadata["embeds"]

            if idx == 0 and message.metadata.get("reply_to_message_id"):
                payload["message_reference"] = {
                    "message_id": message.metadata["reply_to_message_id"],
                }

            resp = await retry_request(
                client.post,
                f"/channels/{channel_id}/messages",
                json=payload,
                headers=self._auth_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            self._sent_messages[data["id"]] = channel_id
        log.debug("discord.send", channel_id=channel_id, message_id=data.get("id"))
        return ChannelSendResult.sent(
            capability=ChannelCapabilities.GROUP_CHAT,
            target_id=channel_id,
            provider_message_id=str(data.get("id", "")),
        )

    async def send_file(
        self,
        channel_id: str,
        file_path: str,
        content: str = "",
    ) -> ChannelSendResult:
        await self._rate_limiter.acquire()
        client = self._get_client()
        with open(file_path, "rb") as f:
            resp = await retry_request(
                client.post,
                f"/channels/{channel_id}/messages",
                data={"content": content} if content else {},
                files={"file": (Path(file_path).name, f)},
                headers=self._auth_headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        message_id = str(data.get("id", ""))
        if message_id:
            self._sent_messages[message_id] = channel_id
        return ChannelSendResult.sent(
            capability=ChannelCapabilities.NATIVE_FILE_UPLOAD,
            target_id=channel_id,
            provider_message_id=message_id,
        )

    async def edit(self, message_id: str, content: str) -> ChannelSendResult:
        await self._rate_limiter.acquire()
        client = self._get_client()
        channel_id = self._sent_messages.get(message_id, self.config.default_channel_id)
        resp = await retry_request(
            client.patch,
            f"/channels/{channel_id}/messages/{message_id}",
            json={"content": content},
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        log.debug("discord.edit", message_id=message_id)
        return ChannelSendResult.sent(
            capability=ChannelCapabilities.EDIT,
            target_id=channel_id,
            provider_message_id=message_id,
        )

    async def delete(self, message_id: str) -> ChannelSendResult:
        await self._rate_limiter.acquire()
        client = self._get_client()
        channel_id = self._sent_messages.get(message_id, self.config.default_channel_id)
        resp = await retry_request(
            client.delete,
            f"/channels/{channel_id}/messages/{message_id}",
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        self._sent_messages.pop(message_id, None)
        log.debug("discord.delete", message_id=message_id)
        return ChannelSendResult.sent(
            capability=ChannelCapabilities.DELETE,
            target_id=channel_id,
            provider_message_id=message_id,
        )

    # ------------------------------------------------------------------
    # Slash commands
    # ------------------------------------------------------------------

    async def register_slash_commands(self, commands: list[dict[str, Any]]) -> None:
        """Register global slash commands for the bot application."""
        await self._rate_limiter.acquire()
        client = self._get_client()
        resp = await retry_request(
            client.put,
            f"/applications/{self.config.application_id}/commands",
            json=commands,
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        log.info("discord.commands_registered", count=len(commands))

    # ------------------------------------------------------------------
    # Mentions
    # ------------------------------------------------------------------

    @staticmethod
    def extract_mentions(text: str) -> list[str]:
        return _DISCORD_MENTION_RE.findall(text)

    @staticmethod
    def format_mention(user_id: str) -> str:
        return f"<@{user_id}>"

    def is_mentioned(self, text: str) -> bool:
        if self.bot_user_id is None:
            return False
        return self.bot_user_id in self.extract_mentions(text)

    def is_group_mentioned(self, msg: IncomingMessage) -> bool:
        """Uniform mention check for group gating. Delegates to is_mentioned."""
        return self.is_mentioned(msg.content)

    # ------------------------------------------------------------------
    # Typing indicator
    # ------------------------------------------------------------------

    async def send_typing(self, channel_id: str | None = None) -> ChannelSendResult:
        """Send typing indicator via Discord REST API (lasts ~10s)."""
        target = channel_id or self.config.default_channel_id
        if not target:
            return ChannelSendResult.unsupported(
                capability=ChannelCapabilities.TYPING_INDICATOR,
                reason="no channel target",
            )
        client = self._get_client()
        await client.post(
            f"/channels/{target}/typing",
            headers=self._auth_headers(),
        )
        return ChannelSendResult.sent(
            capability=ChannelCapabilities.TYPING_INDICATOR,
            target_id=target,
        )

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    async def send_streaming(
        self,
        chunks: AsyncIterator[str],
        *,
        channel_id: str | None = None,
        update_interval_ms: int = 500,
    ) -> str | None:
        """Stream a message: post first chunk, PATCH edits for subsequent.

        Returns the message ID or None if iterator was empty.

        Uses ``StreamThrottle`` so two PATCH calls cannot race and a
        single transient failure does not lose accumulated text.
        """
        target = channel_id or self.config.default_channel_id
        client = self._get_client()
        throttle = StreamThrottle(interval_s=update_interval_ms / 1000.0)
        message_id: str | None = None

        async def _post(text: str) -> None:
            nonlocal message_id
            await self._rate_limiter.acquire()
            resp = await retry_request(
                client.post,
                f"/channels/{target}/messages",
                json={"content": text},
                headers=self._auth_headers(),
            )
            resp.raise_for_status()
            message_id = resp.json().get("id")

        async def _edit(text: str) -> None:
            await self._rate_limiter.acquire()
            resp = await retry_request(
                client.patch,
                f"/channels/{target}/messages/{message_id}",
                json={"content": text},
                headers=self._auth_headers(),
            )
            # retry_request returns 4xx as-is; surface them like every other
            # REST helper so a rejected edit (e.g. 400 code 50035 for >2000
            # chars) triggers the stream relay's batch fallback instead of
            # silently truncating the reply.
            resp.raise_for_status()

        async for chunk in chunks:
            throttle.add(chunk)
            await throttle.maybe_flush(post=_post, edit=_edit)

        await throttle.force_flush(post=_post, edit=_edit)
        return message_id

    # ------------------------------------------------------------------
    # Reply routing (ChannelTransport hooks)
    # ------------------------------------------------------------------

    def streaming_reply_kwargs(self, inbound: IncomingMessage) -> dict[str, Any]:
        """Stream the reply into the channel/thread that triggered the turn.

        Without this, ``send_streaming`` falls back to
        ``config.default_channel_id`` and every streamed reply lands in one
        static channel regardless of who asked. Discord thread IDs are channel
        IDs, so ``inbound.channel_id`` is the correct target for threads too.
        """
        return {"channel_id": inbound.channel_id}

    def build_reply_message(self, content: str, inbound: IncomingMessage) -> OutgoingMessage:
        """Target the inbound channel so batch replies need no static channel id."""
        metadata: dict[str, Any] = {}
        message_id = inbound.metadata.get("message_id") or inbound.metadata.get(
            "native_message_id"
        )
        if isinstance(message_id, str) and message_id:
            metadata["reply_to_message_id"] = message_id
        return OutgoingMessage(
            content=content, reply_to=inbound.channel_id, metadata=metadata
        )

    # ------------------------------------------------------------------
    # Session key
    # ------------------------------------------------------------------

    def session_key(self, user_id: str, channel_id: str) -> str:
        return f"discord:{user_id}:{channel_id}"

    def session_key_from_event(self, data: dict[str, Any]) -> str:
        user_id = data.get("author", {}).get("id", "unknown")
        channel_id = data.get("channel_id", "unknown")
        return self.session_key(user_id, channel_id)
