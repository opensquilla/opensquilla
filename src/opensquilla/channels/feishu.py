"""FeishuChannel: adapter for Feishu (Lark) Open Platform with webhook events and REST API."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import inspect
import json
import mimetypes
import re
import threading
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar, Literal, cast

import httpx
import structlog
from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from opensquilla.channels._attachment_io import (
    attachment_limit_for_mime,
    ensure_declared_size_within_limit,
    fetch_httpx_bytes_limited,
    preferred_attachment_mime,
)
from opensquilla.channels._reactions import NULL_STATUS_REACTOR, FeishuStatusReactor
from opensquilla.channels._util import (
    ChannelAccessPolicy,
    EventDedupeCache,
    RateLimiter,
    retry_request,
)
from opensquilla.channels.contract import (
    ChannelCapabilities,
    ChannelCapabilityProfile,
    ChannelPlatformManifest,
    ChannelSendResult,
)
from opensquilla.channels.transports import InboundEventEnvelope, InboundEventHandler
from opensquilla.channels.types import (
    Attachment,
    ChannelHealth,
    IncomingMessage,
    OutgoingMessage,
)
from opensquilla.env import trust_env as _trust_env

log = structlog.get_logger(__name__)

_FEISHU_MENTION_RE = re.compile(r"@_user_(\d+)")
_MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+")
_MARKDOWN_BULLET_RE = re.compile(r"^(\s*)[-*+]\s+")
_MARKDOWN_BOLD_RE = re.compile(r"(\*\*|__)(.*?)\1")
_MARKDOWN_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_FEISHU_WS_STARTUP_TIMEOUT_S = 1.0
_FEISHU_WS_STARTUP_GRACE_S = 0.05
_FEISHU_WS_JOIN_TIMEOUT_S = 1.0
_FEISHU_WS_SINGLETON_LOCK = threading.Lock()
_FEISHU_WS_ACTIVE_TRANSPORT: FeishuWebSocketTransport | None = None
_FEISHU_INBOUND_RESOURCE_DEFAULTS: dict[str, tuple[str, str, str, tuple[str, ...]]] = {
    "image": ("image.png", "image/png", "image", ("image_key",)),
    "file": ("file", "application/octet-stream", "file", ("file_key",)),
    "media": ("media.mp4", "video/mp4", "media", ("file_key",)),
    "audio": ("audio.ogg", "audio/ogg", "audio", ("file_key",)),
    "sticker": ("sticker.png", "image/png", "image", ("image_key", "file_key")),
}

# Channel-contract constants pinned by the adapter audit.
CAPABILITY_TIER = "GREEN-shipping"

# Feishu is a DM/group channel; the permission matrix denies admin-only tools.
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


def _normalize_outbound_text(content: str) -> str:
    """Convert common Markdown markers to Feishu-friendly plain text."""
    lines: list[str] = []
    in_code_fence = False
    for raw_line in content.replace("\r\n", "\n").split("\n"):
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            in_code_fence = not in_code_fence
            continue
        line = raw_line
        if not in_code_fence:
            line = _MARKDOWN_HEADING_RE.sub("", line)
            line = _MARKDOWN_BULLET_RE.sub(r"\1• ", line)
            line = _MARKDOWN_LINK_RE.sub(r"\1 (\2)", line)
            line = _MARKDOWN_INLINE_CODE_RE.sub(r"\1", line)
            line = _MARKDOWN_BOLD_RE.sub(r"\2", line)
        lines.append(line)
    return "\n".join(lines).strip()


def _feishu_receive_id_type(receive_id: str) -> str:
    if receive_id.startswith("ou_"):
        return "open_id"
    return "chat_id"


def _feishu_file_upload_type(path: Path, requested: str | None = None) -> str:
    if requested and requested != "file":
        return requested
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".doc", ".docx"}:
        return "doc"
    if suffix in {".xls", ".xlsx", ".csv"}:
        return "xls"
    if suffix in {".ppt", ".pptx"}:
        return "ppt"
    if suffix == ".mp4":
        return "mp4"
    if suffix in {".opus", ".ogg"}:
        return "opus"
    return "stream"


def _is_feishu_image_file(path: Path) -> bool:
    guessed, _encoding = mimetypes.guess_type(path.name)
    return bool(guessed and guessed.startswith("image/"))


def _verify_feishu_signature(
    encrypt_key: str,
    timestamp: str,
    nonce: str,
    body: str,
    signature: str,
) -> bool:
    concat = timestamp + nonce + encrypt_key + body
    expected = hashlib.sha256(concat.encode()).hexdigest()
    return hmac.compare_digest(expected, signature)


def _import_lark_oapi() -> Any:
    try:
        import lark_oapi as lark  # type: ignore[import-not-found, import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "Feishu adapter dependency missing — reinstall OpenSquilla"
        ) from exc
    return lark


def _coerce_sdk_event_dict(event: Any, *, lark: Any | None = None) -> dict[str, Any]:
    if isinstance(event, dict):
        return event
    for attr in ("raw", "data"):
        value = getattr(event, attr, None)
        if isinstance(value, dict):
            return value
    lark_json = getattr(lark, "JSON", None) if lark is not None else None
    marshal = getattr(lark_json, "marshal", None)
    if callable(marshal):
        marshaled = marshal(event)
        if isinstance(marshaled, dict):
            return marshaled
        if isinstance(marshaled, bytes):
            marshaled = marshaled.decode()
        if isinstance(marshaled, str):
            dumped = json.loads(marshaled)
            if isinstance(dumped, dict):
                return dumped
    model_dump = getattr(event, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, dict):
            return dumped
    to_dict = getattr(event, "to_dict", None)
    if callable(to_dict):
        dumped = to_dict()
        if isinstance(dumped, dict):
            return dumped
    raise TypeError(f"Unsupported Feishu SDK event object: {type(event)!r}")


class FeishuAuthError(Exception):
    """Raised when Feishu token acquisition or refresh fails."""


class FeishuApiError(Exception):
    """Raised when a Feishu API call returns a non-zero code."""

    def __init__(
        self,
        msg: str,
        *,
        code: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.data = data or {}
        super().__init__(msg)


class FeishuChannelConfig(BaseModel):
    """Pydantic config for Feishu channel adapter."""

    app_id: str
    app_secret: str
    encrypt_key: str = ""
    verification_token: str = ""
    default_chat_id: str = ""
    webhook_path: str = "/feishu/events"
    connection_mode: Literal["webhook", "websocket"] = "webhook"
    domain: Literal["feishu", "lark"] = "feishu"
    api_base: str = "https://open.feishu.cn/open-apis"
    event_dedupe_size: int = 10_000
    token_refresh_margin_s: int = 300
    status_reactions_enabled: bool = False

    model_config = {}  # explicit params only; no env loading


@dataclass
class _TokenState:
    token: str
    expires_at: float  # time.monotonic() based


class FeishuWebhookTransport:
    """Feishu event callback ingress transport."""

    def __init__(
        self,
        config: FeishuChannelConfig,
        dedupe: EventDedupeCache,
    ) -> None:
        self.config = config
        self._dedupe = dedupe
        self._handler: InboundEventHandler | None = None
        self._connected = False

    async def start(self, handler: InboundEventHandler) -> None:
        self._handler = handler
        self._connected = True

    async def stop(self) -> None:
        self._connected = False
        self._handler = None

    async def health_check(self) -> ChannelHealth:
        return ChannelHealth(connected=self._connected, extra={"transport": "webhook"})

    def create_route(self, path: str | None = None) -> Route:
        route_path = path or self.config.webhook_path
        return Route(route_path, endpoint=self._handle_webhook, methods=["POST"])

    async def _handle_webhook(self, request: Request) -> Response:
        body_bytes = await request.body()
        body_str = body_bytes.decode()

        if self.config.encrypt_key:
            timestamp = request.headers.get("X-Lark-Request-Timestamp", "")
            nonce = request.headers.get("X-Lark-Request-Nonce", "")
            signature = request.headers.get("X-Lark-Signature", "")
            if not _verify_feishu_signature(
                self.config.encrypt_key,
                timestamp,
                nonce,
                body_str,
                signature,
            ):
                return Response(status_code=401)

        try:
            data = json.loads(body_str)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return Response(status_code=400)

        if data.get("type") == "url_verification":
            return JSONResponse({"challenge": data.get("challenge", "")})

        header = data.get("header", {})
        event_id = header.get("event_id")
        event_type = header.get("event_type", "")

        if event_id and not self._dedupe.check_and_add(event_id):
            return Response(status_code=200)

        if self._handler is not None:
            await self._handler(
                InboundEventEnvelope(
                    source="feishu:webhook",
                    event_id=event_id,
                    event_type=event_type,
                    raw=data,
                    received_at=datetime.now(UTC),
                )
            )

        return Response(status_code=200)


class FeishuWebSocketTransport:
    """Feishu long-connection ingress transport backed by lark-oapi."""

    def __init__(self, config: FeishuChannelConfig) -> None:
        self.config = config
        self._handler: InboundEventHandler | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._connected = False
        self._last_error: str | None = None
        self._ws_client: Any | None = None
        self._lark: Any | None = None
        self._stop_requested = threading.Event()
        self._worker_loop: asyncio.AbstractEventLoop | None = None
        self._active_registration = False

    async def start(self, handler: InboundEventHandler) -> None:
        lark = _import_lark_oapi()
        self._lark = lark
        self._handler = handler
        self._loop = asyncio.get_running_loop()
        self._stop_requested.clear()

        builder = lark.EventDispatcherHandler.builder(
            self.config.encrypt_key or "",
            self.config.verification_token or "",
        ).register_p2_im_message_receive_v1(self._on_message_sync)
        builder = self._register_optional_event(
            builder,
            "register_p2_im_message_message_read_v1",
            self._ignore_message_read_sync,
        )
        for registrar_name, event_type in (
            ("register_p2_im_chat_member_bot_added_v1", "im.chat.member.bot.added_v1"),
            ("register_p2_im_chat_member_bot_deleted_v1", "im.chat.member.bot.deleted_v1"),
            ("register_p2_im_message_reaction_created_v1", "im.message.reaction.created_v1"),
            ("register_p2_im_message_reaction_deleted_v1", "im.message.reaction.deleted_v1"),
            ("register_p2_card_action_trigger", "card.action.trigger"),
        ):
            builder = self._register_optional_event(
                builder,
                registrar_name,
                self._event_callback(event_type),
            )
        event_handler = builder.build()

        domain = (
            getattr(lark, "LARK_DOMAIN", None)
            if self.config.domain == "lark"
            else getattr(lark, "FEISHU_DOMAIN", None)
        )
        kwargs: dict[str, Any] = {
            "event_handler": event_handler,
            "log_level": lark.LogLevel.INFO,
        }
        if domain is not None:
            kwargs["domain"] = domain

        self._ws_client = lark.ws.Client(
            self.config.app_id,
            self.config.app_secret,
            **kwargs,
        )
        ws_client = self._ws_client
        if ws_client is None:
            raise RuntimeError("Feishu WebSocket client failed to initialize")

        startup_event = threading.Event()
        startup_error: list[Exception] = []

        def _run() -> None:
            worker_loop = asyncio.new_event_loop()
            self._worker_loop = worker_loop
            try:
                asyncio.set_event_loop(worker_loop)
                self._bind_sdk_event_loop(worker_loop)
                self._connected = True
                startup_event.set()
                ws_client.start()
                if not self._stop_requested.is_set():
                    self._last_error = "Feishu WebSocket client stopped during startup"
            except asyncio.CancelledError:
                if not self._stop_requested.is_set():
                    startup_error.append(
                        RuntimeError("Feishu WebSocket client loop was cancelled")
                    )
                    self._last_error = "Feishu WebSocket client loop was cancelled"
                    log.warning("feishu.websocket_cancelled")
                startup_event.set()
            except Exception as exc:
                if not self._stop_requested.is_set():
                    startup_error.append(exc)
                    log.warning("feishu.websocket_failed", error=str(exc))
                self._last_error = str(exc)
                startup_event.set()
            finally:
                self._connected = False
                startup_event.set()
                self._unbind_sdk_event_loop(worker_loop)
                self._drain_worker_loop(worker_loop)
                with contextlib.suppress(Exception):
                    worker_loop.close()
                if self._worker_loop is worker_loop:
                    self._worker_loop = None
                self._release_active_client()

        try:
            self._register_active_client()
            self._thread = threading.Thread(target=_run, daemon=True, name="opensquilla-feishu-ws")
            self._thread.start()
        except Exception:
            self._handler = None
            self._loop = None
            self._lark = None
            self._ws_client = None
            self._thread = None
            self._release_active_client()
            raise
        startup_deadline = time.monotonic() + _FEISHU_WS_STARTUP_TIMEOUT_S
        while not startup_event.is_set() and time.monotonic() < startup_deadline:
            await asyncio.sleep(0.01)
        await asyncio.sleep(_FEISHU_WS_STARTUP_GRACE_S)
        if startup_error:
            self._handler = None
            self._loop = None
            self._lark = None
            if self._thread is not None and not self._thread.is_alive():
                self._thread = None
            raise startup_error[0]
        if self._thread is not None and not self._thread.is_alive():
            self._handler = None
            self._loop = None
            self._lark = None
            self._thread = None
            raise RuntimeError("Feishu WebSocket client stopped during startup")

    async def stop(self) -> None:
        self._connected = False
        self._stop_requested.set()
        await self._request_sdk_stop()
        thread = self._thread
        if thread is not None and thread.is_alive():
            stop_deadline = time.monotonic() + _FEISHU_WS_JOIN_TIMEOUT_S
            while thread.is_alive() and time.monotonic() < stop_deadline:
                self._stop_sdk_event_loop()
                await asyncio.sleep(0.01)
        if thread is not None and thread.is_alive():
            self._last_error = "Feishu WebSocket worker did not stop within timeout"
            self._release_active_client()
            self._thread = None
            self._worker_loop = None
        else:
            if thread is not None:
                thread.join(timeout=0)
            self._thread = None
            self._worker_loop = None
        self._handler = None
        self._loop = None
        self._lark = None

    async def health_check(self) -> ChannelHealth:
        return ChannelHealth(
            connected=self._connected,
            extra={
                "transport": "websocket",
                "last_error": self._last_error,
            },
        )

    def _on_message_sync(self, event: Any) -> None:
        self._on_event_sync(event, default_event_type="im.message.receive_v1")

    def _event_callback(self, default_event_type: str) -> Callable[[Any], None]:
        def _callback(event: Any) -> None:
            self._on_event_sync(event, default_event_type=default_event_type)

        return _callback

    @staticmethod
    def _register_optional_event(
        builder: Any,
        registrar_name: str,
        callback: Callable[[Any], None],
    ) -> Any:
        registrar = getattr(builder, registrar_name, None)
        if not callable(registrar):
            return builder
        return registrar(callback)

    def _on_event_sync(self, event: Any, *, default_event_type: str) -> None:
        if self._loop is None or self._handler is None:
            return
        try:
            raw = _coerce_sdk_event_dict(event, lark=self._lark)
            header = raw.get("header", {})
            envelope = InboundEventEnvelope(
                source="feishu:websocket",
                event_id=header.get("event_id"),
                event_type=header.get("event_type", default_event_type),
                raw=raw,
                received_at=datetime.now(UTC),
            )
        except Exception as exc:
            self._last_error = str(exc)
            log.warning("feishu.websocket_event_decode_failed", error=str(exc))
            return

        async def _deliver() -> None:
            if self._handler is not None:
                await self._handler(envelope)

        self._loop.call_soon_threadsafe(lambda: asyncio.create_task(_deliver()))

    def _ignore_message_read_sync(self, event: Any) -> None:
        log.debug("feishu.websocket_ignored_event", event_type="im.message.message_read_v1")

    async def _request_sdk_stop(self) -> None:
        if self._ws_client is None:
            return
        stop = getattr(self._ws_client, "stop", None)
        if callable(stop):
            try:
                result = stop()
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                self._last_error = str(exc)
                log.warning("feishu.websocket_stop_failed", error=str(exc))
            return

        disconnect = getattr(self._ws_client, "_disconnect", None)
        if not callable(disconnect):
            return
        try:
            result = disconnect()
            if inspect.iscoroutine(result):
                sdk_loop = self._sdk_event_loop()
                if sdk_loop is not None and sdk_loop.is_running():
                    future = asyncio.run_coroutine_threadsafe(result, sdk_loop)
                    try:
                        await asyncio.wait_for(
                            asyncio.wrap_future(future),
                            timeout=_FEISHU_WS_JOIN_TIMEOUT_S,
                        )
                    except TimeoutError:
                        self._last_error = "Feishu WebSocket disconnect timed out"
                        log.warning("feishu.websocket_disconnect_failed", error=self._last_error)
                        future.cancel()
                        self._stop_sdk_event_loop()
                        retry = disconnect()
                        if inspect.isawaitable(retry):
                            await retry
                        elif hasattr(retry, "close"):
                            retry.close()
                else:
                    await result
            elif inspect.isawaitable(result):
                await result
            elif hasattr(result, "close"):
                result.close()
        except Exception as exc:
            self._last_error = str(exc)
            log.warning("feishu.websocket_disconnect_failed", error=str(exc))
        finally:
            self._stop_sdk_event_loop()

    def _sdk_event_loop(self) -> asyncio.AbstractEventLoop | None:
        if self._worker_loop is not None:
            return self._worker_loop
        if self._ws_client is None:
            return None
        sdk_module = inspect.getmodule(self._ws_client.__class__)
        loop = getattr(sdk_module, "loop", None)
        return loop if isinstance(loop, asyncio.AbstractEventLoop) else None

    def _bind_sdk_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._ws_client is None:
            return
        sdk_module = inspect.getmodule(self._ws_client.__class__)
        if sdk_module is not None and hasattr(sdk_module, "loop"):
            setattr(sdk_module, "loop", loop)

    def _unbind_sdk_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._ws_client is None:
            return
        sdk_module = inspect.getmodule(self._ws_client.__class__)
        if sdk_module is not None and getattr(sdk_module, "loop", None) is loop:
            setattr(sdk_module, "loop", None)

    def _stop_sdk_event_loop(self) -> None:
        sdk_loop = self._sdk_event_loop()
        if sdk_loop is None or sdk_loop.is_closed():
            return
        def _cancel_pending_and_stop() -> None:
            for task in asyncio.all_tasks(sdk_loop):
                task.cancel()

        with contextlib.suppress(RuntimeError):
            sdk_loop.call_soon_threadsafe(_cancel_pending_and_stop)

    def _drain_worker_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        if loop.is_closed():
            return
        pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            with contextlib.suppress(Exception):
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        with contextlib.suppress(Exception):
            loop.run_until_complete(loop.shutdown_asyncgens())

    def _register_active_client(self) -> None:
        global _FEISHU_WS_ACTIVE_TRANSPORT
        with _FEISHU_WS_SINGLETON_LOCK:
            active = _FEISHU_WS_ACTIVE_TRANSPORT
            if active is not None and active is not self:
                raise RuntimeError(
                    "only one Feishu websocket channel can run in one OpenSquilla gateway "
                    "process because lark-oapi uses a process-global asyncio event loop; "
                    "disable duplicate Feishu websocket channels or run the second bot in "
                    "a separate gateway process."
                )
            _FEISHU_WS_ACTIVE_TRANSPORT = self
            self._active_registration = True

    def _release_active_client(self) -> None:
        global _FEISHU_WS_ACTIVE_TRANSPORT
        with _FEISHU_WS_SINGLETON_LOCK:
            if _FEISHU_WS_ACTIVE_TRANSPORT is self:
                _FEISHU_WS_ACTIVE_TRANSPORT = None
            self._active_registration = False


@dataclass
class FeishuChannel:
    """Channel adapter for Feishu Open Platform.

    Inbound messages arrive via HTTP webhook (event v2 format).
    Outbound messages use Feishu REST API via httpx.
    """

    STREAM_UPDATE_STRATEGY = "final_only"
    startup_timeout_s: ClassVar[float] = 90.0

    config: FeishuChannelConfig
    bot_open_id: str | None = None
    supports_slash_commands: bool = True
    # See ``ChannelAccessPolicy`` docstring + slack adopter for context.
    # Feishu mirrors slack's defaults today: DMs admit, group requires mention.
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
    _token_state: _TokenState | None = field(default=None, init=False, repr=False)
    _token_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _identity_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _dedupe: EventDedupeCache = field(init=False, repr=False)
    _transport: FeishuWebhookTransport | FeishuWebSocketTransport = field(
        init=False,
        repr=False,
    )
    _rate_limiter: RateLimiter = field(default_factory=RateLimiter, init=False, repr=False)

    def __post_init__(self) -> None:
        self._dedupe = EventDedupeCache(max_size=self.config.event_dedupe_size)
        if self.config.connection_mode == "webhook":
            self._transport = FeishuWebhookTransport(self.config, self._dedupe)
            self._transport._handler = self._handle_inbound_event
        elif self.config.connection_mode == "websocket":
            self._transport = FeishuWebSocketTransport(self.config)
        else:
            raise ValueError(f"Unsupported Feishu connection_mode: {self.config.connection_mode}")

    @property
    def capability_profile(self) -> ChannelCapabilityProfile:
        return ChannelCapabilityProfile(
            channel_type="feishu",
            group_chat=True,
            mentions=True,
            native_file_upload=True,
            media=True,
            reactions=self.config.status_reactions_enabled,
            outbound_status_reactions=self.config.status_reactions_enabled,
            cards=True,
            interactive_cards=True,
            member_events=True,
            edit=True,
            delete=True,
            reply=True,
            thread_reply=True,
            scope_diagnostics=True,
            transports=(self.config.connection_mode,),
        )

    @property
    def platform_capability_manifest(self) -> ChannelPlatformManifest:
        from opensquilla.tools.builtin.feishu_platform import build_feishu_platform_manifest

        return build_feishu_platform_manifest()

    @property
    def capabilities(self) -> frozenset[str]:
        return self.capability_profile.capability_tags()

    @property
    def transport_name(self) -> str:
        return self.config.connection_mode

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.config.api_base,
                timeout=30.0,
                trust_env=_trust_env(),
            )
        return self._client

    @property
    def status_reactor(self) -> Any:
        if not self.config.status_reactions_enabled:
            return NULL_STATUS_REACTOR
        if (reactor := getattr(self, "_status_reactor", None)) is None:
            reactor = self._status_reactor = FeishuStatusReactor(self, log)
        return reactor

    # ------------------------------------------------------------------
    # Auth / Token
    # ------------------------------------------------------------------

    async def _get_token(self) -> str:
        """Return a valid tenant_access_token, refreshing if needed."""
        async with self._token_lock:
            now = time.monotonic()
            margin = self.config.token_refresh_margin_s
            if self._token_state is not None and now < self._token_state.expires_at - margin:
                return self._token_state.token
            client = self._get_client()
            resp = await retry_request(
                client.post,
                "/auth/v3/tenant_access_token/internal",
                json={
                    "app_id": self.config.app_id,
                    "app_secret": self.config.app_secret,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                raise FeishuAuthError(data.get("msg", "token refresh failed"))
            self._token_state = _TokenState(
                token=data["tenant_access_token"],
                expires_at=now + data["expire"],
            )
            return self._token_state.token

    async def _auth_headers(self) -> dict[str, str]:
        token = await self._get_token()
        return {"Authorization": f"Bearer {token}"}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Validate credentials and obtain bot identity."""
        if self.config.connection_mode == "websocket":
            await self._transport.start(self._handle_inbound_event)
            self._connected = True
            self._identity_task = asyncio.create_task(self._refresh_bot_identity_best_effort())
            log.info("feishu.started", bot_open_id=self.bot_open_id)
            return

        await self._refresh_bot_identity()
        await self._transport.start(self._handle_inbound_event)
        self._connected = True
        log.info("feishu.started", bot_open_id=self.bot_open_id)

    async def _refresh_bot_identity(self) -> None:
        token = await self._get_token()
        client = self._get_client()
        resp = await client.get(
            "/bot/v3/info",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") == 0:
            self.bot_open_id = data.get("bot", {}).get("open_id")

    async def _refresh_bot_identity_best_effort(self) -> None:
        try:
            await self._refresh_bot_identity()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("feishu.bot_identity_lookup_failed", error=str(exc))

    async def stop(self) -> None:
        """Gracefully shut down the channel adapter."""
        identity_task = self._identity_task
        self._identity_task = None
        if identity_task is not None and not identity_task.done():
            identity_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await identity_task
        await self._transport.stop()
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._connected = False
        self._token_state = None
        log.info("feishu.stopped")

    def is_connected(self) -> bool:
        return self._connected

    async def health_check(self) -> ChannelHealth:
        transport_health = await self._transport.health_check()
        return ChannelHealth(
            connected=self._connected,
            bot_user_id=self.bot_open_id,
            last_message_at=self._last_message_at,
            extra={
                "transport": self.transport_name,
                "transport_connected": transport_health.connected,
            },
        )

    # ------------------------------------------------------------------
    # Inbound
    # ------------------------------------------------------------------

    def enqueue(self, message: IncomingMessage) -> None:
        self._queue.put_nowait(message)

    async def receive(self) -> IncomingMessage:
        msg = await self._queue.get()
        self._last_message_at = datetime.now(UTC)
        log.debug("feishu.receive", content=msg.content[:80])
        return msg

    # ------------------------------------------------------------------
    # Webhook route
    # ------------------------------------------------------------------

    def create_webhook_route(self, path: str | None = None) -> Route:
        if not isinstance(self._transport, FeishuWebhookTransport):
            raise RuntimeError("Feishu webhook route is only available in webhook mode")
        return self._transport.create_route(path)

    async def _handle_inbound_event(self, envelope: InboundEventEnvelope) -> None:
        if (
            envelope.source == "feishu:websocket"
            and envelope.event_id
            and not self._dedupe.check_and_add(envelope.event_id)
        ):
            return

        if envelope.event_type == "im.message.receive_v1":
            self.enqueue(self.parse_event(envelope.raw))
        elif envelope.event_type == "im.chat.member.bot.added_v1":
            chat_id = envelope.raw.get("event", {}).get("chat_id", "unknown")
            log.info(
                "feishu.bot_added",
                chat_id=chat_id,
                event_id=envelope.event_id,
            )
        elif envelope.event_type == "im.chat.member.bot.deleted_v1":
            chat_id = envelope.raw.get("event", {}).get("chat_id", "unknown")
            log.info(
                "feishu.bot_deleted",
                chat_id=chat_id,
                event_id=envelope.event_id,
            )
        elif envelope.event_type in {
            "im.message.reaction.created_v1",
            "im.message.reaction.deleted_v1",
        }:
            event_body = envelope.raw.get("event", {})
            reaction = event_body.get("reaction_type", {}).get("emoji_type", "")
            user = event_body.get("user_id", {}).get("open_id", "unknown")
            log.info(
                "feishu.reaction_event",
                event_type=envelope.event_type,
                event_id=envelope.event_id,
                message_id=event_body.get("message_id", ""),
                user_id=user,
                reaction_type=reaction,
            )
        elif envelope.event_type == "card.action.trigger":
            if msg := self._parse_clarify_card_action(envelope.raw):
                self.enqueue(msg)
                return
            log.info("feishu.card_action_ignored", event_id=envelope.event_id)
        else:
            log.info(
                "feishu.event_ignored",
                event_type=envelope.event_type,
                event_id=envelope.event_id,
            )

    def _verify_signature(self, timestamp: str, nonce: str, body: str, signature: str) -> bool:
        """Verify Feishu event callback signature."""
        return _verify_feishu_signature(self.config.encrypt_key, timestamp, nonce, body, signature)

    def _parse_clarify_card_action(self, raw: dict[str, Any]) -> IncomingMessage | None:
        event = raw.get("event", {})
        if not isinstance(event, dict):
            return None
        action = event.get("action", {})
        if not isinstance(action, dict):
            return None
        value = action.get("value", {})
        if not isinstance(value, dict):
            return None
        if value.get("opensquilla_action") != "clarify_submit":
            return None

        fields = action.get("form_value")
        if not isinstance(fields, dict):
            fields = action.get("form_values")
        if not isinstance(fields, dict):
            fields = value.get("fields")
        if not isinstance(fields, dict):
            return None

        content = self._clarify_fields_to_text(fields)
        if not content:
            return None

        operator = event.get("operator", {})
        sender_id = ""
        if isinstance(operator, dict):
            sender_id = str(operator.get("open_id") or "")
        sender_id = sender_id or str(event.get("open_id") or "unknown")
        channel_id = str(
            value.get("channel_id")
            or event.get("open_chat_id")
            or event.get("chat_id")
            or "unknown"
        )
        is_group = self._clarify_card_is_group(value, event)
        metadata: dict[str, Any] = {
            "conversation_kind": "interaction",
            "is_group": is_group,
            "event_id": raw.get("header", {}).get("event_id"),
            "message_type": "interactive",
            "native_chat_id": channel_id,
            "input_provenance": "clarify_form",
        }
        chat_type = value.get("chat_type") or event.get("chat_type")
        if isinstance(chat_type, str) and chat_type:
            metadata["chat_type"] = chat_type
        run_id = value.get("run_id")
        if isinstance(run_id, str) and run_id:
            metadata["clarify_run_id"] = run_id
        step = value.get("step")
        if isinstance(step, str) and step:
            metadata["clarify_step"] = step

        return IncomingMessage(
            sender_id=sender_id,
            channel_id=channel_id,
            content=content,
            metadata=metadata,
        )

    @staticmethod
    def _clarify_fields_to_text(fields: dict[str, Any]) -> str:
        lines: list[str] = []
        for key, value in fields.items():
            if value is None or value == "":
                continue
            if isinstance(value, bool):
                rendered = "true" if value else "false"
            else:
                rendered = str(value)
            lines.append(f"{key}: {rendered}")
        return "\n".join(lines)

    @staticmethod
    def _clarify_card_is_group(value: dict[str, Any], event: dict[str, Any]) -> bool:
        raw_is_group = value.get("is_group")
        if isinstance(raw_is_group, bool):
            return raw_is_group
        chat_type = value.get("chat_type")
        if not isinstance(chat_type, str) or not chat_type:
            chat_type = event.get("chat_type")
        if isinstance(chat_type, str) and chat_type:
            return chat_type in {"group", "topic_group"}
        return True

    # ------------------------------------------------------------------
    # Event parsing
    # ------------------------------------------------------------------

    def parse_event(self, event: dict[str, Any]) -> IncomingMessage:
        header = event.get("header", {})
        body = event.get("event", {})
        sender = body.get("sender", {})
        message = body.get("message", {})

        sender_id = sender.get("sender_id", {}).get("open_id", "unknown")
        chat_id = message.get("chat_id", "unknown")
        msg_type = message.get("message_type", "text")
        raw_content = message.get("content", "{}")

        content = self._extract_content(msg_type, raw_content)
        attachments = self._extract_attachments(
            msg_type,
            raw_content,
            message_id=str(message.get("message_id") or ""),
        )

        # Strip bot mention prefix from group messages
        if message.get("chat_type") == "group" and content.startswith("@_user_1 "):
            content = content[len("@_user_1 ") :].strip()

        # Extract mention_map from Feishu mentions array for is_group_mentioned
        mentions_raw = message.get("mentions", [])
        mention_map: dict[str, str] = {}
        for m in mentions_raw:
            key = m.get("key", "")
            user_id = m.get("id", {}).get("open_id", "")
            if key and user_id:
                mention_map[key] = user_id

        chat_type = str(message.get("chat_type") or "")
        conversation_kind = self._conversation_kind(message)
        metadata: dict[str, Any] = {
            "message_id": message.get("message_id"),
            "chat_id": chat_id,
            "root_id": message.get("root_id"),
            "parent_id": message.get("parent_id"),
            "chat_type": chat_type,
            "is_group": chat_type in {"group", "topic_group"},
            "event_id": header.get("event_id"),
            "message_type": msg_type,
            "conversation_kind": conversation_kind,
            "native_message_id": message.get("message_id"),
            "native_chat_id": chat_id,
            "native_root_id": message.get("root_id"),
            "native_parent_id": message.get("parent_id"),
            "native_thread_id": message.get("thread_id"),
            "reply_target_id": message.get("message_id"),
            "mentions": mentions_raw,
            "mention_map": mention_map,
        }

        return IncomingMessage(
            sender_id=sender_id,
            channel_id=chat_id,
            content=content,
            attachments=attachments,
            metadata=metadata,
        )

    @staticmethod
    def _conversation_kind(message: dict[str, Any]) -> str:
        chat_type = str(message.get("chat_type") or "")
        has_thread = bool(message.get("thread_id"))
        if chat_type == "topic_group":
            return "topic" if has_thread else "group"
        if chat_type == "group":
            return "thread" if has_thread else "group"
        return "dm"

    def _extract_content(self, msg_type: str, raw: str) -> str:
        """Extract plain text content from Feishu's JSON-wrapped message body."""
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw
        if msg_type == "text":
            return cast(str, parsed.get("text", raw))
        if msg_type == "post":
            return self._flatten_rich_text(parsed)
        if msg_type == "interactive":
            title = parsed.get("header", {}).get("title", {}).get("content", "")
            return title or "[interactive card]"
        return f"[{msg_type}]"

    def _extract_attachments(
        self,
        msg_type: str,
        raw: str,
        *,
        message_id: str,
    ) -> list[Attachment]:
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
        if not isinstance(parsed, dict):
            return []

        if msg_type == "post":
            attachments: list[Attachment] = []
            for paragraph in parsed.get("content", []):
                if not isinstance(paragraph, list):
                    continue
                for element in paragraph:
                    if not isinstance(element, dict) or element.get("tag") != "img":
                        continue
                    resource_key = element.get("image_key")
                    if not isinstance(resource_key, str) or not resource_key:
                        continue
                    attachments.append(
                        Attachment(
                            name="image.png",
                            mime_type="image/png",
                            metadata={
                                "feishu_message_id": message_id,
                                "feishu_message_type": msg_type,
                                "feishu_resource_key": resource_key,
                                "feishu_resource_type": "image",
                            },
                        )
                    )
            return attachments

        defaults = _FEISHU_INBOUND_RESOURCE_DEFAULTS.get(msg_type)
        if defaults is None:
            return []

        default_name, default_mime, resource_type, key_fields = defaults
        resource_key = next(
            (
                parsed.get(field)
                for field in key_fields
                if isinstance(parsed.get(field), str) and parsed.get(field)
            ),
            None,
        )
        if not isinstance(resource_key, str):
            return []

        name = Path(str(parsed.get("file_name") or default_name)).name or default_name
        mime_type = mimetypes.guess_type(name)[0] or default_mime
        size = parsed.get("file_size")
        return [
            Attachment(
                name=name,
                mime_type=mime_type,
                size=size if isinstance(size, int) else None,
                metadata={
                    "feishu_message_id": message_id,
                    "feishu_message_type": msg_type,
                    "feishu_resource_key": resource_key,
                    "feishu_resource_type": resource_type,
                },
            )
        ]

    async def resolve_inbound_attachment(self, attachment: Attachment) -> Attachment:
        message_id = attachment.metadata.get("feishu_message_id")
        resource_key = attachment.metadata.get("feishu_resource_key")
        resource_type = attachment.metadata.get("feishu_resource_type")
        if not all(isinstance(value, str) and value for value in (message_id, resource_key)):
            raise ValueError("Feishu attachment is missing resource metadata")
        if not isinstance(resource_type, str) or not resource_type:
            resource_type = "file"

        limit = attachment_limit_for_mime(attachment.mime_type)
        ensure_declared_size_within_limit(attachment.size, name=attachment.name, limit=limit)
        headers = await self._auth_headers()
        client = self._get_client()
        data, downloaded_mime = await fetch_httpx_bytes_limited(
            client,
            f"/im/v1/messages/{message_id}/resources/{resource_key}",
            name=attachment.name,
            limit=limit,
            params={"type": resource_type},
            headers=headers,
        )
        return Attachment(
            name=attachment.name,
            mime_type=preferred_attachment_mime(downloaded_mime, attachment.mime_type),
            data=data,
            size=len(data),
            metadata=dict(attachment.metadata),
        )

    def _flatten_rich_text(self, post: dict[str, Any]) -> str:
        """Flatten Feishu post (rich text) structure to plain text."""
        lines: list[str] = []
        title = post.get("title", "")
        if title:
            lines.append(title)
        for paragraph in post.get("content", []):
            parts: list[str] = []
            for element in paragraph:
                tag = element.get("tag", "")
                if tag == "text":
                    parts.append(element.get("text", ""))
                elif tag == "a":
                    parts.append(element.get("text", element.get("href", "")))
                elif tag == "at":
                    parts.append(f"@{element.get('user_name', element.get('user_id', ''))}")
                elif tag == "img":
                    parts.append("[image]")
            lines.append("".join(parts))
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------

    def build_reply_message(
        self,
        content: str,
        inbound: IncomingMessage,
    ) -> OutgoingMessage:
        """Build a Feishu reply that targets the inbound chat."""
        metadata: dict[str, Any] = {}
        reply_message_id = inbound.metadata.get("reply_target_id") or inbound.metadata.get(
            "native_message_id"
        )
        if isinstance(reply_message_id, str) and reply_message_id:
            metadata["reply_message_id"] = reply_message_id
        native_thread_id = inbound.metadata.get("native_thread_id")
        if isinstance(native_thread_id, str) and native_thread_id:
            metadata["native_thread_id"] = native_thread_id
        return OutgoingMessage(content=content, reply_to=inbound.channel_id, metadata=metadata)

    def streaming_reply_kwargs(self, inbound: IncomingMessage) -> dict[str, Any]:
        """Return Feishu streaming target kwargs for the inbound chat."""
        return {"chat_id": inbound.channel_id}

    @staticmethod
    def _raise_api_error(data: dict[str, Any], fallback: str) -> None:
        if data.get("code") != 0:
            raise FeishuApiError(
                data.get("msg", fallback),
                code=data.get("code"),
                data=data,
            )

    async def send_text(self, chat_id: str, content: str) -> str:
        """Send a text message to a chat/open_id and return Feishu message_id."""
        await self._rate_limiter.acquire()
        headers = await self._auth_headers()
        client = self._get_client()
        receive_id_type = _feishu_receive_id_type(chat_id)
        payload: dict[str, Any] = {
            "receive_id": chat_id,
            "msg_type": "text",
            "content": json.dumps({"text": _normalize_outbound_text(content)}),
        }
        resp = await retry_request(
            client.post,
            f"/im/v1/messages?receive_id_type={receive_id_type}",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
        self._raise_api_error(data, "send failed")
        return str(data.get("data", {}).get("message_id", ""))

    async def reply_text(self, message_id: str, content: str) -> str:
        """Reply to a Feishu message and return the reply message_id."""
        await self._rate_limiter.acquire()
        headers = await self._auth_headers()
        client = self._get_client()
        resp = await retry_request(
            client.post,
            f"/im/v1/messages/{message_id}/reply",
            json={
                "msg_type": "text",
                "content": json.dumps({"text": _normalize_outbound_text(content)}),
            },
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
        self._raise_api_error(data, "reply failed")
        return str(data.get("data", {}).get("message_id", ""))

    async def read_message(self, message_id: str) -> dict[str, Any]:
        """Fetch a Feishu message payload."""
        await self._rate_limiter.acquire()
        headers = await self._auth_headers()
        client = self._get_client()
        resp = await retry_request(
            client.get,
            f"/im/v1/messages/{message_id}",
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
        self._raise_api_error(data, "read failed")
        payload = data.get("data", {})
        return payload if isinstance(payload, dict) else {}

    async def send(self, message: OutgoingMessage) -> None:
        reply_message_id = message.metadata.get("reply_message_id")
        if isinstance(reply_message_id, str) and reply_message_id:
            await self.reply_text(reply_message_id, message.content)
            log.debug("feishu.reply", message_id=reply_message_id)
            return
        chat_id = message.reply_to or self.config.default_chat_id

        if message.metadata.get("card"):
            await self._rate_limiter.acquire()
            headers = await self._auth_headers()
            client = self._get_client()
            receive_id_type = _feishu_receive_id_type(chat_id)
            payload: dict[str, Any] = {
                "receive_id": chat_id,
                "msg_type": "text",
                "content": json.dumps({"text": _normalize_outbound_text(message.content)}),
            }
            payload["msg_type"] = "interactive"
            payload["content"] = json.dumps(message.metadata["card"])
            resp = await retry_request(
                client.post,
                f"/im/v1/messages?receive_id_type={receive_id_type}",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            self._raise_api_error(data, "send failed")
        else:
            await self.send_text(chat_id, message.content)
        log.debug("feishu.send", chat_id=chat_id)

    async def send_file(
        self,
        chat_id: str,
        file_path: str,
        file_type: str = "file",
    ) -> ChannelSendResult:
        """Upload and send a file to a Feishu chat."""
        await self._rate_limiter.acquire()
        headers = await self._auth_headers()
        client = self._get_client()
        path = Path(file_path)

        if _is_feishu_image_file(path):
            with open(file_path, "rb") as f:
                upload_resp = await retry_request(
                    client.post,
                    "/im/v1/images",
                    data={"image_type": "message"},
                    files={"image": f},
                    headers=headers,
                )
            upload_resp.raise_for_status()
            upload_data = upload_resp.json()
            self._raise_api_error(upload_data, "image upload failed")
            key = upload_data["data"]["image_key"]
            provider_file_id = str(key)
            message_type = "image"
            content = {"image_key": key}
        else:
            upload_type = _feishu_file_upload_type(path, file_type)
            with open(file_path, "rb") as f:
                upload_resp = await retry_request(
                    client.post,
                    "/im/v1/files",
                    data={"file_type": upload_type, "file_name": path.name},
                    files={"file": f},
                    headers=headers,
                )
            upload_resp.raise_for_status()
            upload_data = upload_resp.json()
            self._raise_api_error(upload_data, "file upload failed")
            key = upload_data["data"]["file_key"]
            provider_file_id = str(key)
            message_type = "file"
            content = {"file_key": key}

        receive_id_type = _feishu_receive_id_type(chat_id)
        payload = {
            "receive_id": chat_id,
            "msg_type": message_type,
            "content": json.dumps(content),
        }
        resp = await retry_request(
            client.post,
            f"/im/v1/messages?receive_id_type={receive_id_type}",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
        self._raise_api_error(data, "send file failed")
        message_id = str(data.get("data", {}).get("message_id", ""))
        return ChannelSendResult.sent(
            capability=ChannelCapabilities.NATIVE_FILE_UPLOAD,
            target_id=chat_id,
            provider_message_id=message_id,
            provider_file_id=provider_file_id,
        )

    async def edit(self, message_id: str, content: str) -> None:
        await self._rate_limiter.acquire()
        headers = await self._auth_headers()
        client = self._get_client()
        resp = await retry_request(
            client.put,
            f"/im/v1/messages/{message_id}",
            json={
                "msg_type": "text",
                "content": json.dumps({"text": _normalize_outbound_text(content)}),
            },
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
        self._raise_api_error(data, "edit failed")
        log.debug("feishu.edit", message_id=message_id)

    async def delete(self, message_id: str) -> None:
        await self._rate_limiter.acquire()
        headers = await self._auth_headers()
        client = self._get_client()
        resp = await retry_request(
            client.delete,
            f"/im/v1/messages/{message_id}",
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
        self._raise_api_error(data, "delete failed")

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    async def send_streaming(
        self,
        chunks: AsyncIterator[str],
        *,
        chat_id: str | None = None,
        update_interval_ms: int = 500,
    ) -> str | None:
        """Collect a streamed reply and send one Feishu message.

        Returns the message_id or None if iterator was empty.
        """
        target = chat_id or self.config.default_chat_id
        accumulated = ""

        del update_interval_ms

        async for chunk in chunks:
            accumulated += chunk

        if not accumulated:
            return None
        await self.send(OutgoingMessage(content=accumulated, reply_to=target))
        return None

    # ------------------------------------------------------------------
    # Mentions
    # ------------------------------------------------------------------

    @staticmethod
    def extract_mentions(text: str, mention_map: dict[str, str]) -> list[str]:
        """Extract user open_ids from Feishu mention placeholders."""
        keys = _FEISHU_MENTION_RE.findall(text)
        return [mention_map.get(f"@_user_{k}", f"unknown_{k}") for k in keys]

    def is_mentioned(self, text: str, mention_map: dict[str, str]) -> bool:
        """Check if the bot is mentioned in the message."""
        bot_id = self.bot_open_id
        if not bot_id:
            return False
        return bot_id in set(mention_map.values()) or bot_id in self.extract_mentions(
            text, mention_map
        )

    def is_group_mentioned(self, msg: IncomingMessage) -> bool:
        """Uniform mention check for group gating. Reads mention_map from metadata."""
        mention_map = msg.metadata.get("mention_map", {})
        return self.is_mentioned(msg.content, mention_map)

    # ------------------------------------------------------------------
    # Session key
    # ------------------------------------------------------------------

    def session_key(self, sender_open_id: str, chat_id: str) -> str:
        return f"feishu:{sender_open_id}:{chat_id}"

    def session_key_from_event(self, event: dict[str, Any]) -> str:
        body = event.get("event", {})
        sender_id = body.get("sender", {}).get("sender_id", {}).get("open_id", "unknown")
        chat_id = body.get("message", {}).get("chat_id", "unknown")
        return self.session_key(sender_id, chat_id)
