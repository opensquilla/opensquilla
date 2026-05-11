"""SlackChannel: adapter for Slack Web API with threading, mentions, lifecycle."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from opensquilla.channels._reactions import NULL_STATUS_REACTOR, SlackStatusReactor
from opensquilla.channels._util import ChannelAccessPolicy, EventDedupeCache, StreamThrottle
from opensquilla.channels.types import ChannelHealth, IncomingMessage, OutgoingMessage
from opensquilla.env import trust_env as _trust_env

log = structlog.get_logger(__name__)

SLACK_API_BASE = "https://slack.com/api"

_MENTION_RE = re.compile(r"<@(U[A-Z0-9]+)(?:\|[^>]*)?>")

# Channel-contract constants pinned by the adapter audit.
CAPABILITY_TIER = "GREEN-shipping"

# Slack is a DM/group channel; the permission matrix denies admin-only tools.
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


class SlackAuthError(Exception):
    """Raised when Slack token validation fails."""


@dataclass
class SlackChannel:
    """Channel adapter for Slack Web API.

    Inbound messages are delivered via ``enqueue`` (populated by a Slack
    Events API webhook handler or socket-mode listener).

    Outbound messages use ``chat.postMessage`` via httpx.
    """

    token: str
    slack_channel_id: str
    channel_id: str = "slack"
    sender_id: str = "slack-user"
    bot_user_id: str | None = None
    reply_in_thread: bool = False
    signing_secret: str | None = None
    status_reactions_enabled: bool = False
    # ``policy`` declares the admit/deny semantics consumed by
    # ``opensquilla.channels._util.evaluate_policy``. Slack admits DMs, admits
    # group messages only when the bot is mentioned, and applies no
    # sender-allowlist filter at the dispatch layer today.
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
    _last_thread_ts: str | None = field(default=None, init=False, repr=False)
    _last_message_at: datetime | None = field(default=None, init=False, repr=False)
    _dedupe: EventDedupeCache = field(
        default_factory=lambda: EventDedupeCache(max_size=10_000),
        init=False,
        repr=False,
    )
    supports_slash_commands: bool = True

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=SLACK_API_BASE,
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=30.0,
                trust_env=_trust_env(),
            )
        return self._client

    @property
    def status_reactor(self) -> Any:
        if not self.status_reactions_enabled:
            return NULL_STATUS_REACTOR
        if (reactor := getattr(self, "_status_reactor", None)) is None:
            reactor = self._status_reactor = SlackStatusReactor(self, log)
        return reactor

    async def close(self) -> None:
        """Close the underlying httpx client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Inbound
    # ------------------------------------------------------------------

    def enqueue(self, message: IncomingMessage) -> None:
        """Push an inbound Slack message into the receive queue."""
        self._queue.put_nowait(message)

    async def receive(self) -> IncomingMessage:
        """Block until an inbound message is available."""
        msg = await self._queue.get()
        self._last_message_at = datetime.now(UTC)
        log.debug("slack.receive", channel=self.slack_channel_id, content=msg.content[:80])
        return msg

    def parse_event(self, event: dict[str, Any]) -> IncomingMessage:
        """Convert a Slack event payload dict into IncomingMessage."""
        ts = event.get("ts")
        thread_ts = event.get("thread_ts")

        # channel_type: "channel"/"group" = group, "im"/"mpim" = DM
        # Fallback: infer from channel ID prefix (C/G = group, D = direct)
        channel_type = event.get("channel_type")
        if channel_type is None:
            ch = event.get("channel", "")
            if ch.startswith(("C", "G")):
                channel_type = "channel"
            elif ch.startswith("D"):
                channel_type = "im"

        metadata: dict[str, Any] = {
            "ts": ts,
            "thread_ts": thread_ts,
            "team": event.get("team"),
            "channel_type": channel_type,
        }

        # Detect thread root: thread_ts == ts
        if thread_ts is not None and ts is not None:
            metadata["is_thread_root"] = thread_ts == ts

        # Track last thread_ts for reply_in_thread auto-threading
        if thread_ts is not None:
            self._last_thread_ts = thread_ts

        return IncomingMessage(
            sender_id=event.get("user", self.sender_id),
            channel_id=event.get("channel", self.slack_channel_id),
            content=event.get("text", ""),
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------

    async def send(self, message: OutgoingMessage) -> None:
        """Post a message to the Slack channel via chat.postMessage."""
        payload: dict[str, Any] = {
            "channel": self.slack_channel_id,
            "text": message.content,
        }
        if message.reply_to:
            payload["thread_ts"] = message.reply_to
        elif self.reply_in_thread and self._last_thread_ts:
            payload["thread_ts"] = self._last_thread_ts
        if message.metadata:
            if "thread_ts" in message.metadata and message.metadata["thread_ts"] is None:
                payload.pop("thread_ts", None)
            payload.update(
                {key: value for key, value in message.metadata.items() if value is not None}
            )

        client = self._get_client()
        resp = await client.post("/chat.postMessage", json=payload)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            log.error("slack.send_failed", error=data.get("error"), channel=self.slack_channel_id)
            raise RuntimeError(f"Slack API error: {data.get('error')}")
        log.debug("slack.send", channel=self.slack_channel_id, ts=data.get("ts"))

    async def edit(self, message_id: str, content: str) -> None:
        """Update an existing Slack message via chat.update."""
        payload: dict[str, Any] = {
            "channel": self.slack_channel_id,
            "ts": message_id,
            "text": content,
        }
        client = self._get_client()
        resp = await client.post("/chat.update", json=payload)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            log.error("slack.edit_failed", error=data.get("error"), message_id=message_id)
            raise RuntimeError(f"Slack API error: {data.get('error')}")
        log.debug("slack.edit", message_id=message_id)

    async def delete(self, message_id: str) -> None:
        """Delete a Slack message via chat.delete."""
        payload: dict[str, Any] = {
            "channel": self.slack_channel_id,
            "ts": message_id,
        }
        client = self._get_client()
        resp = await client.post("/chat.delete", json=payload)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            log.error("slack.delete_failed", error=data.get("error"), message_id=message_id)
            raise RuntimeError(f"Slack API error: {data.get('error')}")
        log.debug("slack.delete", message_id=message_id)

    # ------------------------------------------------------------------
    # Streaming (T008)
    # ------------------------------------------------------------------

    async def send_streaming(
        self,
        chunks: AsyncIterator[str],
        *,
        thread_ts: str | None = None,
        update_interval_ms: int = 500,
    ) -> str | None:
        """Send a streaming message: post first chunk, update with subsequent chunks.

        Returns the message ``ts`` or ``None`` if the iterator was empty.

        Uses ``StreamThrottle`` so a fast producer cannot fire two
        concurrent ``chat.update`` calls and a single network failure
        does not lose accumulated text.
        """
        client = self._get_client()
        throttle = StreamThrottle(interval_s=update_interval_ms / 1000.0)
        message_ts: str | None = None

        async def _post(text: str) -> None:
            nonlocal message_ts
            payload: dict[str, Any] = {
                "channel": self.slack_channel_id,
                "text": text,
            }
            if thread_ts:
                payload["thread_ts"] = thread_ts
            resp = await client.post("/chat.postMessage", json=payload)
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                raise RuntimeError(f"Slack API error: {data.get('error')}")
            message_ts = data["ts"]
            log.debug("slack.stream_start", ts=message_ts)

        async def _edit(text: str) -> None:
            resp = await client.post(
                "/chat.update",
                json={
                    "channel": self.slack_channel_id,
                    "ts": message_ts,
                    "text": text,
                },
            )
            resp.raise_for_status()

        async for chunk in chunks:
            throttle.add(chunk)
            await throttle.maybe_flush(post=_post, edit=_edit)

        await throttle.force_flush(post=_post, edit=_edit)
        if message_ts is not None:
            log.debug("slack.stream_end", ts=message_ts, length=len(throttle.text))

        return message_ts

    # ------------------------------------------------------------------
    # Mentions (T004)
    # ------------------------------------------------------------------

    @staticmethod
    def extract_mentions(text: str) -> list[str]:
        """Extract user IDs from Slack mention markup like ``<@U123>`` or ``<@U123|name>``."""
        return _MENTION_RE.findall(text)

    @staticmethod
    def format_mention(user_id: str) -> str:
        """Format a user ID as a Slack mention string."""
        return f"<@{user_id}>"

    def is_mentioned(self, text: str) -> bool:
        """Check whether this bot is mentioned in the given text."""
        if self.bot_user_id is None:
            return False
        return self.bot_user_id in self.extract_mentions(text)

    def is_group_mentioned(self, msg: IncomingMessage) -> bool:
        """Uniform mention check for group gating. Delegates to is_mentioned."""
        return self.is_mentioned(msg.content)

    # Note: Slack Web API has no typing endpoint for webhook-based bots.
    # send_typing() is intentionally not implemented here.

    # ------------------------------------------------------------------
    # Lifecycle (T006)
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Validate token via auth.test and store bot_user_id."""
        client = self._get_client()
        resp = await client.post("/auth.test")
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise SlackAuthError(data.get("error", "unknown auth error"))
        self.bot_user_id = data["user_id"]
        self._connected = True
        log.info("slack.started", bot_user_id=self.bot_user_id)

    async def stop(self) -> None:
        """Gracefully shut down the channel adapter."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._connected = False
        log.info("slack.stopped")

    def is_connected(self) -> bool:
        """Return whether the adapter has been started and is connected."""
        return self._connected

    # ------------------------------------------------------------------
    # Gateway Webhook (T012)
    # ------------------------------------------------------------------

    def create_webhook_route(self, path: str = "/slack/events") -> Route:
        """Return a Starlette Route for handling Slack Events API webhooks."""
        return Route(path, endpoint=self._handle_webhook, methods=["POST"])

    async def _handle_webhook(self, request: Request) -> Response:
        """Handle an incoming Slack Events API request."""
        body = await request.body()

        # Signature verification
        if self.signing_secret is not None:
            timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
            signature = request.headers.get("X-Slack-Signature", "")

            # Reject requests older than 5 minutes (replay protection)
            try:
                if abs(time.time() - float(timestamp)) > 300:
                    return Response(status_code=403)
            except (ValueError, TypeError):
                return Response(status_code=403)

            if not self._verify_signature(body, timestamp, signature):
                return Response(status_code=401)
        else:
            log.warning("slack.webhook_no_signing_secret")

        try:
            data = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return Response(status_code=400)

        event_type = data.get("type")

        if event_type == "url_verification":
            challenge = data.get("challenge", "")
            return JSONResponse({"challenge": challenge})

        if event_type == "event_callback":
            event = data.get("event", {})
            if event.get("type") == "message":
                dedupe_key = str(
                    data.get("event_id")
                    or event.get("client_msg_id")
                    or f"{event.get('channel', '')}:{event.get('ts', '')}"
                ).strip(":")
                if dedupe_key and not self._dedupe.check_and_add(dedupe_key):
                    return Response(status_code=200)
                msg = self.parse_event(event)
                self.enqueue(msg)

        return Response(status_code=200)

    def _verify_signature(self, body: bytes, timestamp: str, signature: str) -> bool:
        """Verify Slack request signature using HMAC-SHA256."""
        if self.signing_secret is None:
            return False
        sig_basestring = f"v0:{timestamp}:{body.decode()}"
        expected = (
            "v0="
            + hmac.HMAC(
                self.signing_secret.encode(),
                sig_basestring.encode(),
                hashlib.sha256,
            ).hexdigest()
        )
        return hmac.compare_digest(expected, signature)

    # ------------------------------------------------------------------
    # Health Check (T014)
    # ------------------------------------------------------------------

    async def health_check(self) -> ChannelHealth:
        """Return current health status of the Slack adapter."""
        return ChannelHealth(
            connected=self._connected,
            bot_user_id=self.bot_user_id,
            last_message_at=self._last_message_at,
        )
