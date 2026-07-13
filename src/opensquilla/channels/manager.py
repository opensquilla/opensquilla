"""ChannelManager — lifecycle management for ManagedChannel adapters."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from functools import partial
from typing import Any

import structlog
from starlette.routing import Route

from opensquilla.channels.registry import build_managed_channel
from opensquilla.channels.types import ChannelHealth, DeliveryTargetResolution, ManagedChannel
from opensquilla.gateway._debounce import _DefaultDebounceCoordinator
from opensquilla.gateway.channel_dispatch import run_channel_dispatch
from opensquilla.session.keys import (
    DmScope,
    build_direct_key,
    build_group_key,
    build_group_sender_key,
    build_thread_key,
)

log = structlog.get_logger(__name__)


def _structured_diagnostic(exc: BaseException) -> dict[str, Any] | None:
    raw = getattr(exc, "diagnostic", None)
    if not isinstance(raw, dict):
        return None
    diagnostic: dict[str, Any] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        if isinstance(value, str | int | float | bool) or value is None:
            diagnostic[key] = value
    return diagnostic or None


@dataclass
class ChannelManager:
    """Manages lifecycle of ManagedChannel instances.

    Responsibilities:
    - Build adapters from gateway config entries (from_config)
    - Collect webhook routes for Starlette registration
    - Start/stop/restart individual channels or all at once
    - Run dispatch loops with exponential-backoff retry
    - Build proper session keys via session/keys.py
    """

    _channels: dict[str, ManagedChannel]
    _turn_runner: Any  # TurnRunner (avoid circular import at module level)
    _session_manager: Any  # SessionManager
    _event_bridge: Any = None  # EventBridge | None (injected from gateway boot)
    _config: Any = None
    _task_runtime: Any = None
    _rpc_dispatcher: Any = None
    _channel_rpc_context_factory: Callable[[Any], Any] | None = None
    _delivery_store: Any = None
    _lease_owner_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    _transport_leases: dict[str, Any] = field(default_factory=dict)
    _lease_tasks: dict[str, asyncio.Task[Any]] = field(default_factory=dict)
    _debounce_coordinator: Any = field(default_factory=_DefaultDebounceCoordinator)
    _agent_ids: dict[str, str] = field(default_factory=dict)
    _channel_types: dict[str, str] = field(default_factory=dict)
    _group_session_scopes: dict[str, str] = field(default_factory=dict)
    _busy_input_modes: dict[str, str] = field(default_factory=dict)
    _tasks: dict[str, asyncio.Task] = field(default_factory=dict)
    # Per-channel in-flight reply task sets.
    # Keyed by channel name; populated in _safe_start and consumed in stop_channel.
    _in_flight_sets: dict[str, Any] = field(default_factory=dict)
    # Dispatch state machine — see _dispatch_with_retry for the lifecycle.
    # Values: "running" | "exhausted" | "restarting" | "dead". Unset entries
    # are treated as "unknown" by health() so a channel that never started
    # does not look healthy.
    _dispatch_states: dict[str, str] = field(default_factory=dict)
    _restart_counts: dict[str, int] = field(default_factory=dict)
    _start_errors: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Inner-loop retry policy (overridable for tests).
    _max_retries: int = 5
    _retry_backoff_initial: float = 1.0
    _retry_backoff_max: float = 60.0
    # Outer-loop restart policy. ``dead`` is operator-recoverable via the
    # ``channels.restart`` admin RPC; the cap only bounds *automatic*
    # restart attempts.
    _restart_delay_s: float = 30.0
    _max_restart_cycles: int = 3

    # ── Factory ──────────────────────────────────────────────

    @classmethod
    def from_config(
        cls,
        entries: list,
        *,
        turn_runner: Any,
        session_manager: Any,
        event_bridge: Any = None,
        config: Any = None,
        task_runtime: Any = None,
        rpc_dispatcher: Any = None,
        channel_rpc_context_factory: Callable[[Any], Any] | None = None,
    ) -> ChannelManager:
        """Build adapter instances from gateway config entries.

        Each entry's ``type`` field selects the adapter class.
        Disabled entries are skipped.
        """
        channels: dict[str, ManagedChannel] = {}
        from opensquilla.channels.delivery_store import (
            delivery_store_for_config,
            install_outbox,
        )

        delivery_store = delivery_store_for_config(config)
        agent_ids: dict[str, str] = {}
        channel_types: dict[str, str] = {}
        group_session_scopes: dict[str, str] = {}
        busy_input_modes: dict[str, str] = {}
        for entry in entries:
            if not entry.enabled:
                log.info("channel.skipped_disabled", name=entry.name)
                continue

            adapter = build_managed_channel(entry)
            if adapter is None:
                log.warning("channel.unknown_type", type=entry.type, name=entry.name)
                continue

            channels[entry.name] = adapter
            from opensquilla.channels._util import ChannelAccessPolicy, ChannelDmAccess

            declared_policy = getattr(adapter, "policy", None)
            if not isinstance(declared_policy, ChannelAccessPolicy):
                declared_policy = ChannelAccessPolicy()
            setattr(
                adapter,
                "policy",
                replace(
                    declared_policy,
                    dm_access=ChannelDmAccess(str(getattr(entry, "dm_access", "pairing"))),
                    allowlist=frozenset(getattr(entry, "allowed_senders", ())),
                ),
            )
            setattr(adapter, "_delivery_store", delivery_store)
            setattr(adapter, "_delivery_channel_name", entry.name)
            install_outbox(adapter)
            cls._register_tool_channel(entry.name, adapter)
            agent_ids[entry.name] = getattr(entry, "agent_id", "main")
            channel_types[entry.name] = entry.type
            group_session_scopes[entry.name] = getattr(
                entry, "group_session_scope", "per_sender"
            )
            busy_input_modes[entry.name] = getattr(entry, "busy_input_mode", "followup")
            setattr(adapter, "debounce_window_s", getattr(entry, "debounce_window_s", 0.0))
            log.info("channel.adapter_created", name=entry.name, type=entry.type)

        return cls(
            _channels=channels,
            _turn_runner=turn_runner,
            _session_manager=session_manager,
            _event_bridge=event_bridge,
            _config=config,
            _task_runtime=task_runtime,
            _rpc_dispatcher=rpc_dispatcher,
            _channel_rpc_context_factory=channel_rpc_context_factory,
            _delivery_store=delivery_store,
            _agent_ids=agent_ids,
            _channel_types=channel_types,
            _group_session_scopes=group_session_scopes,
            _busy_input_modes=busy_input_modes,
        )

    @staticmethod
    def _register_tool_channel(name: str, adapter: ManagedChannel) -> None:
        try:
            from opensquilla.tools.builtin.messaging import register_channel

            register_channel(name, adapter)
        except Exception as exc:
            log.debug("channel.tool_register_failed", name=name, tool="message", error=str(exc))
        if type(adapter).__name__ != "FeishuChannel":
            return
        try:
            from opensquilla.channels.feishu import FeishuChannel
            from opensquilla.tools.builtin.feishu_platform import register_feishu_channel

            if isinstance(adapter, FeishuChannel):
                register_feishu_channel(name, adapter)
        except Exception as exc:
            log.debug(
                "channel.tool_register_failed",
                name=name,
                tool="feishu_platform",
                error=str(exc),
            )

    @staticmethod
    def _unregister_tool_channel(name: str, adapter: ManagedChannel | None) -> None:
        try:
            from opensquilla.tools.builtin.messaging import unregister_channel

            unregister_channel(name)
        except Exception as exc:
            log.debug("channel.tool_unregister_failed", name=name, tool="message", error=str(exc))
        if adapter is not None and type(adapter).__name__ != "FeishuChannel":
            return
        try:
            from opensquilla.tools.builtin.feishu_platform import unregister_feishu_channel

            unregister_feishu_channel(name)
        except Exception as exc:
            log.debug(
                "channel.tool_unregister_failed",
                name=name,
                tool="feishu_platform",
                error=str(exc),
            )

    # ── Webhook routes ───────────────────────────────────────

    def collect_webhook_routes(self) -> list[Route]:
        """Extract Starlette Routes from adapters that support webhooks.

        Slack and Feishu adapters expose ``create_webhook_route()``;
        Discord uses a persistent WebSocket and has no webhook.
        """
        routes: list[Route] = []
        for name, adapter in self._channels.items():
            if getattr(adapter, "transport_name", "webhook") != "webhook":
                continue
            if hasattr(adapter, "create_webhook_route"):
                route = adapter.create_webhook_route()
                routes.append(route)
                log.info("channel.webhook_route_collected", channel=name, path=route.path)
        return routes

    # ── Lifecycle ────────────────────────────────────────────

    async def start_all(self) -> dict[str, bool]:
        """Start all channels concurrently.

        Returns ``{name: success}`` map.  Partial failures do NOT
        prevent other channels from starting.
        """
        results = await asyncio.gather(
            *[self._safe_start(name) for name in self._channels],
            return_exceptions=True,
        )
        statuses: dict[str, bool] = {}
        for name, result in zip(self._channels, results):
            if isinstance(result, BaseException):
                details: dict[str, Any] = {
                    "error_type": type(result).__name__,
                    "error": str(result),
                    "exception": repr(result),
                }
                diagnostic = _structured_diagnostic(result)
                if diagnostic:
                    details["diagnostic"] = diagnostic
                self._start_errors[name] = details
                statuses[name] = False
            else:
                self._start_errors.pop(name, None)
                statuses[name] = True
        return statuses

    def start_errors(self) -> dict[str, dict[str, Any]]:
        """Return sanitized per-channel startup errors for operator diagnostics."""
        return {name: dict(details) for name, details in self._start_errors.items()}

    async def _safe_start(self, name: str) -> None:
        """Start a single channel with 30 s timeout, then launch dispatch loop."""
        from opensquilla.gateway.channel_dispatch import _ChannelInFlightSet, _compute_channel_cap

        adapter = self._channels[name]
        lease = None
        if self._delivery_store is not None:
            account_id = self._transport_account_id(name, adapter)
            lease = self._delivery_store.acquire_transport_lease(
                self._channel_types.get(name, name),
                account_id,
                self._lease_owner_id,
            )
            if lease is None:
                raise RuntimeError(f"channel transport lease is already held for {name}")
            self._transport_leases[name] = lease
            setattr(adapter, "_transport_fencing_token", lease.fencing_token)
        startup_timeout = float(getattr(adapter, "startup_timeout_s", 30.0))
        try:
            if lease is not None and self._delivery_store is not None:
                enqueue = getattr(adapter, "enqueue", None)
                if callable(enqueue):
                    for recovered in self._delivery_store.recover_inbound(name):
                        enqueue(recovered)
            self._unregister_tool_channel(name, adapter)
            await asyncio.wait_for(adapter.start(), timeout=startup_timeout)
            self._register_tool_channel(name, adapter)
        except Exception:
            stop = getattr(adapter, "stop", None)
            if callable(stop):
                with contextlib.suppress(Exception):
                    await stop()
            self._unregister_tool_channel(name, adapter)
            if lease is not None and self._delivery_store is not None:
                self._delivery_store.release_transport_lease(lease)
                self._transport_leases.pop(name, None)
            raise
        if lease is not None:
            self._lease_tasks[name] = asyncio.create_task(
                self._renew_transport_lease(name),
                name=f"channel-lease:{name}",
            )
        entry_agent_id = self._agent_ids.get(name, "main")
        key_builder = partial(
            self._build_session_key,
            name,
            agent_id=entry_agent_id,
            group_session_scope=self._group_session_scopes.get(name, "per_sender"),
        )
        cap = _compute_channel_cap(self._config)
        in_flight = _ChannelInFlightSet(cap)
        self._in_flight_sets[name] = in_flight
        self._tasks[name] = asyncio.create_task(
            self._dispatch_with_retry(name, key_builder, in_flight=in_flight),
            name=f"channel:{name}",
        )

    def _transport_account_id(self, name: str, adapter: Any) -> str:
        config = getattr(adapter, "config", None)
        candidates: list[str] = []
        for source in (config, adapter):
            if source is None:
                continue
            for field_name in (
                "app_id",
                "bot_id",
                "corp_id",
                "client_id",
                "user_id",
                "homeserver_url",
                "token",
                "app_token",
            ):
                value = str(getattr(source, field_name, "") or "").strip()
                if value:
                    candidates.append(f"{field_name}={value}")
        if not candidates:
            candidates.append(f"name={name}")
        return hashlib.sha256("\0".join(candidates).encode()).hexdigest()[:24]

    async def _renew_transport_lease(self, name: str) -> None:
        while True:
            await asyncio.sleep(30.0)
            lease = self._transport_leases.get(name)
            if lease is None or self._delivery_store is None:
                return
            renewed = self._delivery_store.renew_transport_lease(lease)
            if renewed is not None:
                self._transport_leases[name] = renewed
                continue
            log.error("channel.transport_lease_lost", channel=name)
            adapter = self._channels.get(name)
            if adapter is not None:
                setattr(adapter, "_connected", False)
                with contextlib.suppress(Exception):
                    await adapter.stop()
            return

    async def _run_one_dispatch_cycle(
        self,
        name: str,
        key_builder: Callable[[Any], str],
        in_flight: Any = None,
    ) -> None:
        """Inner retry loop. Returns once retries are exhausted.

        CRITICAL: ``CancelledError`` always propagates — it signals
        intentional shutdown via ``stop_channel``.  Only ``Exception``
        subclasses trigger retry.
        """
        backoff = self._retry_backoff_initial
        max_backoff = self._retry_backoff_max

        for attempt in range(self._max_retries + 1):
            try:
                await run_channel_dispatch(
                    channel=self._channels[name],
                    turn_runner=self._turn_runner,
                    session_manager=self._session_manager,
                    session_key_builder=key_builder,
                    session_prefix=name,
                    event_bridge=self._event_bridge,
                    config=self._config,
                    task_runtime=self._task_runtime,
                    rpc_dispatcher=self._rpc_dispatcher,
                    channel_rpc_context_factory=self._channel_rpc_context_factory,
                    debounce_coordinator=self._debounce_coordinator,
                    debounce_window_s=getattr(self._channels[name], "debounce_window_s", 0.0),
                    busy_input_mode=self._busy_input_modes.get(name, "followup"),
                    _in_flight=in_flight,
                )
            except asyncio.CancelledError:
                raise  # intentional shutdown — never retry
            except Exception as exc:
                log.error(
                    "channel.dispatch_error",
                    channel=name,
                    attempt=attempt,
                    max_retries=self._max_retries,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, max_backoff)
                else:
                    log.error("channel.dispatch_exhausted", channel=name)

    async def _dispatch_with_retry(
        self,
        name: str,
        key_builder: Callable[[Any], str],
        in_flight: Any = None,
    ) -> None:
        """Outer cycle loop wrapping the inner retry budget.

        Each iteration runs one dispatch cycle. After the inner retry budget
        is exhausted the channel transitions through
        ``running → exhausted → restarting → running`` until the configured
        restart cap is hit, at which point it transitions to ``dead`` and
        the loop exits. ``dead`` is operator-recoverable through
        ``restart_channel``.
        """
        self._dispatch_states[name] = "running"
        self._restart_counts.setdefault(name, 0)
        while True:
            await self._run_one_dispatch_cycle(name, key_builder, in_flight=in_flight)

            self._dispatch_states[name] = "exhausted"
            log.warning(
                "dispatch.running_to_exhausted",
                channel=name,
                restart_count=self._restart_counts[name],
            )

            if self._restart_counts[name] >= self._max_restart_cycles:
                self._dispatch_states[name] = "dead"
                log.error(
                    "dispatch.restarting_to_dead",
                    channel=name,
                    restart_count=self._restart_counts[name],
                )
                return

            self._restart_counts[name] += 1
            self._dispatch_states[name] = "restarting"
            log.warning(
                "dispatch.exhausted_to_restarting",
                channel=name,
                restart_count=self._restart_counts[name],
                max_cycles=self._max_restart_cycles,
            )
            await asyncio.sleep(self._restart_delay_s)
            self._dispatch_states[name] = "running"

    async def stop_all(self) -> None:
        """Stop every managed channel (dispatch task + adapter)."""
        for name in list(self._channels):
            await self.stop_channel(name)
        await self._debounce_coordinator.cancel_all()
        if self._delivery_store is not None:
            self._delivery_store.close()
            self._delivery_store = None

    async def stop_channel(self, name: str) -> None:
        """Cancel dispatch task, cancel all in-flight reply tasks, then stop adapter.

        MUST use this instead of calling ``adapter.stop()`` directly,
        otherwise the dispatch task becomes orphaned.

        In-flight reply tasks are cancelled and awaited
        before the adapter is stopped so no dangling coroutines remain after
        shutdown.
        """
        task = self._tasks.pop(name, None)
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        # Cancel and await all in-flight reply tasks for this channel.
        in_flight = self._in_flight_sets.pop(name, None)
        if in_flight is not None:
            await in_flight.cancel_all()
        adapter = self._channels.get(name)
        try:
            if adapter:
                await adapter.stop()
        finally:
            lease_task = self._lease_tasks.pop(name, None)
            if lease_task is not None and not lease_task.done():
                lease_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await lease_task
            lease = self._transport_leases.pop(name, None)
            if lease is not None and self._delivery_store is not None:
                self._delivery_store.release_transport_lease(lease)
            self._unregister_tool_channel(name, adapter)

    async def restart_channel(self, name: str) -> None:
        """Stop then re-start a single channel.

        On a ``dead`` channel this is the operator-recoverable path: the
        restart counter is cleared and a single ``dispatch.dead_to_running``
        decision-log entry is emitted before the new dispatch loop spins up.
        """
        prev_state = self._dispatch_states.get(name)
        await self.stop_channel(name)
        self._restart_counts[name] = 0
        if prev_state == "dead":
            log.info("dispatch.dead_to_running", channel=name)
        await self._safe_start(name)

    # ── Health ───────────────────────────────────────────────

    async def health(self) -> dict[str, ChannelHealth]:
        """Return health status for every managed channel.

        Adapter-reported ``ChannelHealth.extra`` is augmented with the
        dispatch-loop state so operators can distinguish "channel dropped a
        message" from "channel is permanently dead pending admin restart".
        """
        out: dict[str, ChannelHealth] = {}
        for name, a in self._channels.items():
            health = await a.health_check()
            health.extra["dispatch_state"] = self._dispatch_states.get(name, "unknown")
            lease = self._transport_leases.get(name)
            if lease is not None:
                health.extra["transport_lease"] = {
                    "owner_id": lease.owner_id,
                    "fencing_token": lease.fencing_token,
                    "expires_at": lease.expires_at,
                }
            out[name] = health
        return out

    # ── Accessors ────────────────────────────────────────────

    def items(self):  # noqa: ANN201
        """Iterate ``(name, adapter)`` pairs."""
        return self._channels.items()

    def get(self, name: str) -> ManagedChannel | None:
        """Look up an adapter by name."""
        return self._channels.get(name)

    def resolve_delivery_target(
        self,
        *,
        target: str,
        to: str = "",
        account_id: str = "",
        thread_id: str = "",
    ) -> DeliveryTargetResolution:
        """Resolve delivery fields to a concrete adapter.

        ``target`` may be an OpenSquilla adapter entry name, or a
        channel type such as ``slack`` when the type maps to one adapter.
        ``account_id`` currently selects a concrete entry until opensquilla grows a
        first-class multi-account channel config.
        """

        target_name = target.strip()
        target_type = target_name.lower()
        account = account_id.strip()
        to = to.strip()
        thread = thread_id.strip()

        if not target_name:
            return DeliveryTargetResolution(ok=False, reason="unsupported_target")

        candidates = [
            name
            for name, channel_type in self._channel_types.items()
            if channel_type.lower() == target_type
        ]
        if account:
            if account not in candidates:
                return DeliveryTargetResolution(ok=False, reason="unsupported_account")
            return self._build_delivery_resolution(
                adapter_name=account,
                channel_type=target_type,
                to=to,
                account_id=account,
                thread_id=thread,
            )

        if target_name in self._channels:
            adapter_name = target_name
            channel_type = self._channel_types.get(adapter_name, adapter_name).lower()
            return self._build_delivery_resolution(
                adapter_name=adapter_name,
                channel_type=channel_type,
                to=to,
                account_id=account,
                thread_id=thread,
            )

        if not candidates:
            return DeliveryTargetResolution(ok=False, reason="unsupported_target")
        if len(candidates) > 1:
            return DeliveryTargetResolution(ok=False, reason="ambiguous_account")

        return self._build_delivery_resolution(
            adapter_name=candidates[0],
            channel_type=target_type,
            to=to,
            account_id=account,
            thread_id=thread,
        )

    def _build_delivery_resolution(
        self,
        *,
        adapter_name: str,
        channel_type: str,
        to: str,
        account_id: str,
        thread_id: str,
    ) -> DeliveryTargetResolution:
        if thread_id and channel_type not in {"slack"}:
            return DeliveryTargetResolution(ok=False, reason="unsupported_thread")
        return DeliveryTargetResolution(
            ok=True,
            adapter=self._channels.get(adapter_name),
            adapter_name=adapter_name,
            channel_type=channel_type,
            to=to,
            account_id=account_id,
            thread_id=thread_id,
        )

    # ── Session key builder ──────────────────────────────────

    @staticmethod
    def _build_session_key(
        channel_name: str,
        msg: Any,
        agent_id: str = "main",
        group_session_scope: str = "per_sender",
    ) -> str:
        """Build a proper session key using ``session/keys.py`` builders.

        Detects group vs DM from message metadata:
        - Feishu: ``metadata.chat_type == "group"``
        - Discord: ``metadata.guild_id is not None``
        - Slack: ``metadata.channel_type in ("channel", "group")``

        Group keys use ``msg.channel_id`` as peer_id and, by default,
        ``msg.sender_id`` to isolate participants in the same room.
        ``group_session_scope='shared_room'`` preserves the explicit
        compatibility mode where every participant shares one transcript.
        DM keys use ``msg.sender_id`` as peer_id (per-user session).
        """
        meta = getattr(msg, "metadata", {}) or {}
        flag = meta.get("is_group")
        if flag is not None:
            is_group = bool(flag)
        else:
            # Adapter metadata fallback for events that do not yet carry the
            # ``metadata['is_group']`` contract documented in ``channels/types.py``.
            is_group = (
                meta.get("chat_type") == "group"  # Feishu
                or meta.get("guild_id") is not None  # Discord
                or meta.get("channel_type") in ("channel", "group")  # Slack
            )

        if is_group:
            if group_session_scope == "shared_room":
                base_key = build_group_key(
                    agent_id=agent_id,
                    channel=channel_name,
                    peer_id=msg.channel_id,
                )
            else:
                base_key = build_group_sender_key(
                    agent_id=agent_id,
                    channel=channel_name,
                    peer_id=msg.channel_id,
                    sender_id=msg.sender_id,
                )
            thread_id = (
                meta.get("native_thread_id") or meta.get("thread_ts") or meta.get("thread_id")
            )
            if isinstance(thread_id, str) and thread_id:
                return build_thread_key(base_key, thread_id, channel_hint=channel_name)
            return base_key

        return build_direct_key(
            agent_id=agent_id,
            channel=channel_name,
            peer_id=msg.sender_id,
            dm_scope=DmScope.PER_CHANNEL_PEER,
        )
