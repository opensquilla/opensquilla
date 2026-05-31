"""WeCom corp-app channel adapter.

Vendored AES-256-CBC + PKCS7 + sha1 msg-signature crypto in
:mod:`opensquilla.channels._wecom_crypto`, native ``httpx.AsyncClient``
outbound against ``https://qyapi.weixin.qq.com``, no ``wechatpy`` dependency.

WeCom corp app has no message-edit primitive: ``send_streaming`` accumulates
the LLM stream and emits exactly one outbound POST at completion. No calls
to ``cgi-bin/message/recall`` or ``cgi-bin/message/update_template_card``
happen mid-stream.
"""

from __future__ import annotations

import asyncio
import contextlib
import mimetypes
import time
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import httpx
import structlog
from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route

from opensquilla.channels._util import ChannelAccessPolicy, EventDedupeCache
from opensquilla.channels._wecom_crypto import WeComCrypto
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
    ChannelHealth,
    IncomingMessage,
    OutgoingMessage,
    UnsupportedChannelOperation,
)
from opensquilla.env import trust_env as _trust_env

log = structlog.get_logger(__name__)

_TOKEN_REFRESH_INTERVAL_S = 7000.0  # WeCom access_token TTL is 7200 s
_DEFAULT_TIMEOUT_S = 10.0
_DEDUPE_SIZE = 4096

# Channel-contract constants pinned by the adapter audit.
CAPABILITY_TIER = "GREEN-shipping"

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


class WeComAuthError(Exception):
    """Raised when ``gettoken`` fails."""


class WeComApiError(Exception):
    """Raised when a WeCom API call returns a non-zero ``errcode``."""

    def __init__(self, msg: str, *, code: int | None = None) -> None:
        self.code = code
        super().__init__(msg)


class WeComChannelConfig(BaseModel):
    """Adapter-level config for the WeCom corp-app channel.

    Defaults are empty so the existing ``ChannelManager.from_config``
    branch (which currently passes only ``name``) keeps working until a
    follow-up wires the real entry fields, populating ``corp_id``,
    ``corp_secret``, ``agent_id_int``, ``token``, and ``encoding_aes_key``
    from :class:`opensquilla.gateway.config.WeComChannelEntry`.
    """

    name: str = "wecom"
    corp_id: str = ""
    corp_secret: str = ""
    agent_id_int: int = 0
    token: str = ""
    encoding_aes_key: str = ""
    webhook_path: str = "/wecom/events"
    api_base: str = "https://qyapi.weixin.qq.com"

    model_config = {}


@dataclass
class _TokenState:
    token: str
    expires_at: float  # time.monotonic() based


@dataclass
class WeComChannel:
    """WeCom corp-app channel adapter.

    Webhook callbacks are AES-decrypted via the vendored
    :class:`~opensquilla.channels._wecom_crypto.WeComCrypto`. Outbound
    messages POST to ``cgi-bin/message/send`` with a cached ``access_token``
    refreshed by a background task.
    """

    config: WeComChannelConfig
    policy: ChannelAccessPolicy = field(
        default_factory=lambda: ChannelAccessPolicy(
            dm_allowed=True,
            group_allowed=True,
            mention_required_in_group=True,
            allowlist=frozenset(),
        )
    )

    _client: httpx.AsyncClient | None = field(default=None, init=False, repr=False)
    _connected: bool = field(default=False, init=False, repr=False)
    _token_state: _TokenState | None = field(default=None, init=False, repr=False)
    _token_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _refresh_task: asyncio.Task | None = field(default=None, init=False, repr=False)
    _queue: asyncio.Queue[IncomingMessage] = field(
        default_factory=asyncio.Queue, init=False, repr=False
    )
    _dedupe: EventDedupeCache = field(init=False, repr=False)
    _last_message_at: datetime | None = field(default=None, init=False, repr=False)
    _last_incoming_envelope: IncomingMessage | None = field(default=None, init=False, repr=False)
    _crypto: WeComCrypto | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._dedupe = EventDedupeCache(max_size=_DEDUPE_SIZE)
        if self.config.encoding_aes_key and self.config.token and self.config.corp_id:
            self._crypto = WeComCrypto(
                token=self.config.token,
                encoding_aes_key=self.config.encoding_aes_key,
                receiver_id=self.config.corp_id,
            )

    @property
    def capability_profile(self) -> ChannelCapabilityProfile:
        return ChannelCapabilityProfile(
            channel_type="wecom",
            group_chat=True,
            mentions=True,
            native_file_upload=True,
            media=True,
            reply=True,
            transports=("webhook",),
        )

    @property
    def platform_capability_manifest(self) -> ChannelPlatformManifest:
        return ChannelPlatformManifest.from_channel_profile(
            self.capability_profile,
            has_send_file=True,
        ).with_capabilities(
            ChannelPlatformCapability(
                category=ChannelPlatformCategories.FILES,
                status=ChannelPlatformCapabilityStatus.SUPPORTED,
                tools=("media/upload", "message/send:file"),
                mutates=True,
                notes=("WeCom file delivery uploads media then sends a file message.",),
            ),
            ChannelPlatformCapability(
                category=ChannelPlatformCategories.ATTACHMENTS,
                status=ChannelPlatformCapabilityStatus.UNSUPPORTED,
                notes=("Inbound WeCom attachment resolution is not implemented in this adapter.",),
            ),
        )

    @property
    def capabilities(self) -> frozenset[str]:
        return self.capability_profile.capability_tags()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.config.api_base,
                timeout=_DEFAULT_TIMEOUT_S,
                trust_env=_trust_env(),
            )
        return self._client

    def _get_crypto(self) -> WeComCrypto:
        if self._crypto is None:
            raise WeComAuthError("WeCom adapter is missing token/encoding_aes_key/corp_id")
        return self._crypto

    # ------------------------------------------------------------------
    # Token cache + refresh
    # ------------------------------------------------------------------

    async def _refresh_token(self) -> str:
        """Hit ``cgi-bin/gettoken`` and cache the access_token."""
        client = self._get_client()
        params = {
            "corpid": self.config.corp_id,
            "corpsecret": self.config.corp_secret,
        }
        resp = await client.get("/cgi-bin/gettoken", params=params)
        resp.raise_for_status()
        data = resp.json()
        if data.get("errcode", 0) != 0:
            raise WeComAuthError(
                f"gettoken failed: errcode={data.get('errcode')} errmsg={data.get('errmsg')}"
            )
        token = cast(str, data["access_token"])
        ttl = float(data.get("expires_in", 7200))
        self._token_state = _TokenState(
            token=token,
            expires_at=time.monotonic() + ttl,
        )
        log.info("wecom.token_refreshed", expires_in=ttl)
        return token

    async def _get_token(self) -> str:
        async with self._token_lock:
            if self._token_state is not None and time.monotonic() < self._token_state.expires_at:
                return self._token_state.token
            return await self._refresh_token()

    async def _refresh_loop(self) -> None:
        """Background task that proactively refreshes the access_token.

        Runs once per ``_TOKEN_REFRESH_INTERVAL_S`` (~7000 s, < 7200 s TTL).
        """
        try:
            while True:
                await asyncio.sleep(_TOKEN_REFRESH_INTERVAL_S)
                async with self._token_lock:
                    await self._refresh_token()
        except asyncio.CancelledError:
            raise

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        await self._get_token()
        self._connected = True
        self._refresh_task = asyncio.create_task(
            self._refresh_loop(), name=f"wecom-token-refresh:{self.config.name}"
        )
        log.info("wecom.started", name=self.config.name)

    async def stop(self) -> None:
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._refresh_task
            self._refresh_task = None
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._connected = False
        self._token_state = None
        log.info("wecom.stopped", name=self.config.name)

    async def health_check(self) -> ChannelHealth:
        return ChannelHealth(
            connected=self._connected,
            last_message_at=self._last_message_at,
        )

    # ------------------------------------------------------------------
    # Inbound queue
    # ------------------------------------------------------------------

    def enqueue(self, message: IncomingMessage) -> None:
        self._queue.put_nowait(message)

    async def receive(self) -> IncomingMessage:
        msg = await self._queue.get()
        self._last_message_at = datetime.now(UTC)
        # Cache the most recent envelope so ``send_streaming(chunks)``
        # invocations from the dispatcher (which carry no target kwarg)
        # can route the reply back to the originator.
        self._last_incoming_envelope = msg
        return msg

    # ------------------------------------------------------------------
    # Webhook route
    # ------------------------------------------------------------------

    def create_webhook_route(self, path: str | None = None) -> Route:
        route_path = path or self.config.webhook_path
        return Route(route_path, endpoint=self._handle_webhook, methods=["GET", "POST"])

    async def _handle_webhook(self, request: Request) -> Response:
        try:
            crypto = self._get_crypto()
        except WeComAuthError:
            return Response(status_code=503)

        params = request.query_params
        msg_signature = params.get("msg_signature", "")
        timestamp = params.get("timestamp", "")
        nonce = params.get("nonce", "")

        if request.method == "GET":
            echostr = params.get("echostr", "")
            if not crypto.verify_signature(
                self.config.token, timestamp, nonce, echostr, msg_signature
            ):
                log.warning("wecom.signature_invalid", phase="url_verify")
                return Response(status_code=401)
            try:
                plaintext = crypto.decrypt_message(echostr)
            except ValueError as exc:
                log.warning("wecom.signature_invalid", reason=str(exc))
                return Response(status_code=401)
            return PlainTextResponse(plaintext)

        # POST: encrypted event
        body_bytes = await request.body()
        try:
            outer = ET.fromstring(body_bytes.decode("utf-8"))
        except (ET.ParseError, UnicodeDecodeError):
            return Response(status_code=400)
        encrypt_node = outer.find("Encrypt")
        if encrypt_node is None or not encrypt_node.text:
            return Response(status_code=400)
        encrypt_b64 = encrypt_node.text

        if not crypto.verify_signature(
            self.config.token, timestamp, nonce, encrypt_b64, msg_signature
        ):
            log.warning("wecom.signature_invalid", phase="event")
            return Response(status_code=401)

        try:
            inner_xml = crypto.decrypt_message(encrypt_b64)
        except ValueError as exc:
            log.warning("wecom.signature_invalid", reason=str(exc))
            return Response(status_code=401)

        try:
            inner = ET.fromstring(inner_xml)
        except ET.ParseError:
            return Response(status_code=400)

        msg = self._parse_inbound_xml(inner)
        if msg is None:
            return Response(status_code=200)

        msg_id = str(msg.metadata.get("message_id", ""))
        if msg_id and not self._dedupe.check_and_add(msg_id):
            log.info("wecom.dedup_drop", message_id=msg_id)
            return Response(status_code=200)

        log.info(
            "wecom.inbound_received",
            message_id=msg_id,
            is_group=msg.metadata.get("is_group"),
        )
        self.enqueue(msg)
        return Response(status_code=200)

    @staticmethod
    def _xml_text(node: ET.Element, tag: str, default: str = "") -> str:
        child = node.find(tag)
        if child is None or child.text is None:
            return default
        return child.text

    def _parse_inbound_xml(self, root: ET.Element) -> IncomingMessage | None:
        """Map a decrypted WeCom callback XML into an :class:`IncomingMessage`.

        Sets ``metadata['is_group']`` from ``<ChatType>``: ``group`` → True,
        ``single`` (or absent) → False.
        """
        msg_type = self._xml_text(root, "MsgType", "text")
        msg_id = self._xml_text(root, "MsgId")
        from_user = self._xml_text(root, "FromUserName")
        to_user = self._xml_text(root, "ToUserName")
        chat_type = self._xml_text(root, "ChatType", "single")
        is_group = chat_type == "group"
        # Group messages may carry a chat ID separately.
        chat_id = self._xml_text(root, "ChatId") or to_user
        channel_id = chat_id if is_group else from_user

        if msg_type == "text":
            content = self._xml_text(root, "Content")
        elif msg_type == "image":
            content = "[image]"
        elif msg_type == "voice":
            content = "[voice]"
        elif msg_type == "event":
            event = self._xml_text(root, "Event", "")
            content = f"[event:{event}]" if event else "[event]"
        else:
            content = f"[{msg_type}]"

        metadata: dict[str, Any] = {
            "message_id": msg_id,
            "msg_type": msg_type,
            "chat_type": chat_type,
            "is_group": is_group,
            "from_user": from_user,
            "to_user": to_user,
        }
        if is_group:
            # Current WeCom group support targets the AI Bot callback shape:
            # group callbacks are delivered only when the bot is addressed.
            metadata["chat_id"] = chat_id
            metadata["wecom_protocol"] = "aibot"
            metadata["bot_mentioned"] = True

        return IncomingMessage(
            sender_id=from_user or "unknown",
            channel_id=channel_id or "unknown",
            content=content,
            metadata=metadata,
        )

    def is_group_mentioned(self, msg: IncomingMessage) -> bool:
        if not bool(msg.metadata.get("is_group")):
            return True
        return (
            msg.metadata.get("wecom_protocol") == "aibot"
            and bool(msg.metadata.get("bot_mentioned"))
        )

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------

    def _build_send_payload(self, message: OutgoingMessage) -> dict[str, Any]:
        """Translate ``OutgoingMessage`` into a WeCom corp-app message body.

        ``reply_to`` is interpreted as the user / party / tag target. Falls
        back to ``@all`` when nothing is set, matching Tencent's "broadcast
        within the configured app" behavior.
        """
        target = message.reply_to or message.metadata.get("touser") or "@all"
        payload: dict[str, Any] = {
            "touser": str(target),
            "msgtype": "text",
            "agentid": self.config.agent_id_int,
            "text": {"content": message.content},
            "safe": 0,
        }
        if "toparty" in message.metadata:
            payload["toparty"] = str(message.metadata["toparty"])
        if "totag" in message.metadata:
            payload["totag"] = str(message.metadata["totag"])
        return payload

    async def send(self, message: OutgoingMessage) -> None:
        token = await self._get_token()
        client = self._get_client()
        payload = self._build_send_payload(message)
        resp = await client.post(
            "/cgi-bin/message/send",
            params={"access_token": token},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("errcode", 0) != 0:
            raise WeComApiError(data.get("errmsg", "send failed"), code=data.get("errcode"))
        log.info("wecom.outbound_sent", touser=payload.get("touser"))

    async def send_file(
        self,
        target_id: str,
        file_path: str,
        content: str = "",
    ) -> ChannelSendResult:
        token = await self._get_token()
        client = self._get_client()
        path = Path(file_path)
        media_type = self._wecom_media_type(path)
        with path.open("rb") as f:
            upload_resp = await client.post(
                "/cgi-bin/media/upload",
                params={"access_token": token, "type": media_type},
                files={"media": (path.name, f)},
            )
        upload_resp.raise_for_status()
        upload_data = upload_resp.json()
        if upload_data.get("errcode", 0) != 0:
            raise WeComApiError(
                upload_data.get("errmsg", "media upload failed"),
                code=upload_data.get("errcode"),
            )
        media_id = str(upload_data.get("media_id", ""))
        if not media_id:
            raise WeComApiError("media upload returned no media_id")
        payload = {
            "touser": str(target_id),
            "msgtype": media_type,
            "agentid": self.config.agent_id_int,
            media_type: {"media_id": media_id},
            "safe": 0,
        }
        if content:
            await self.send(OutgoingMessage(content=content, reply_to=target_id))
        send_resp = await client.post(
            "/cgi-bin/message/send",
            params={"access_token": token},
            json=payload,
        )
        send_resp.raise_for_status()
        send_data = send_resp.json()
        if send_data.get("errcode", 0) != 0:
            raise WeComApiError(
                send_data.get("errmsg", "send failed"),
                code=send_data.get("errcode"),
            )
        return ChannelSendResult.sent(
            capability=ChannelCapabilities.NATIVE_FILE_UPLOAD,
            target_id=str(target_id),
            provider_message_id=str(send_data.get("msgid", "")),
            provider_file_id=media_id,
        )

    @staticmethod
    def _wecom_media_type(path: Path) -> str:
        mime_type = mimetypes.guess_type(path.name)[0] or ""
        if mime_type.startswith("image/"):
            return "image"
        if mime_type.startswith("video/"):
            return "video"
        if mime_type.startswith("audio/"):
            return "voice"
        return "file"

    async def edit(self, message_id: str, content: str) -> None:
        raise UnsupportedChannelOperation(
            channel="wecom",
            operation="edit",
            reason="WeCom corp app has no generic message-edit primitive",
        )

    async def delete(self, message_id: str) -> None:
        # `recall` exists but is intentionally NOT used here: streaming/edit
        # must not call recall mid-stream.
        raise UnsupportedChannelOperation(
            channel="wecom",
            operation="delete",
            reason="corp-app recall is not exposed as a generic delete primitive.",
        )

    # ------------------------------------------------------------------
    # Streaming — final-flush only
    # ------------------------------------------------------------------

    async def send_streaming(
        self,
        chunks: AsyncIterator[str],
        *,
        reply_to: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Accumulate the LLM stream and emit exactly one outbound POST.

        WeCom corp app has no edit/recall-safe streaming path; we
        never call ``cgi-bin/message/recall`` or
        ``cgi-bin/message/update_template_card`` mid-stream. If the
        stream raises before completing, we issue zero outbound HTTP.
        """
        accumulated = ""
        async for chunk in chunks:
            accumulated += chunk
        if not accumulated:
            return

        # Implicit reply-target fallback: when the dispatcher invokes
        # ``send_streaming(chunks)`` with no kwargs, fall back to the
        # last received envelope's sender so the reply is targeted at
        # the originator instead of broadcasting to ``@all``.
        last = self._last_incoming_envelope
        out_meta: dict[str, Any] = dict(metadata or {})
        target = reply_to or out_meta.get("touser")
        if not target and last is not None:
            target = last.sender_id
            for inherit_key in ("toparty", "totag"):
                if inherit_key not in out_meta and inherit_key in last.metadata:
                    out_meta[inherit_key] = last.metadata[inherit_key]
        await self.send(
            OutgoingMessage(
                content=accumulated,
                reply_to=target or "",
                metadata=out_meta,
            )
        )
