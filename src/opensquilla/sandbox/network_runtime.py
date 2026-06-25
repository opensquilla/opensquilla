"""Codex-style network policy and approval runtime.

The network proxy is the enforcement point: it sees the real outbound
``host/protocol/port`` and asks this runtime whether the request can continue.
Tool preflight may still provide nicer early UX, but it must not be the only
network boundary.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from opensquilla.sandbox.escalation import (
    build_network_approval_params,
    consume_persisted_temporary_network_grant,
    consume_temporary_network_grant,
    context_with_temporary_network_grants,
    has_temporary_network_grant,
    request_sandbox_approval,
)
from opensquilla.sandbox.governance import action_fingerprint
from opensquilla.sandbox.network_guard import NetworkDecision, decide_network_access
from opensquilla.sandbox.run_context import RunContext
from opensquilla.sandbox.types import SandboxRequest


class NetworkProtocol(StrEnum):
    HTTP = "http"
    HTTPS = "https"
    HTTPS_CONNECT = "https_connect"
    SOCKS5_TCP = "socks5_tcp"
    SOCKS5_UDP = "socks5_udp"


@dataclass(frozen=True)
class NetworkPolicyRequest:
    protocol: NetworkProtocol
    host: str
    port: int
    method: str | None = None
    client_addr: str | None = None
    tool_name: str | None = None
    command: str | None = None
    exec_policy_hint: str | None = None


class NetworkPolicyDecider(Protocol):
    def decide(self, request: NetworkPolicyRequest) -> Awaitable[NetworkDecision]: ...


@dataclass(frozen=True)
class HostApprovalKey:
    host: str
    protocol: NetworkProtocol
    port: int

    @classmethod
    def from_request(cls, request: NetworkPolicyRequest) -> HostApprovalKey:
        return cls(
            host=request.host.casefold(),
            protocol=request.protocol,
            port=int(request.port),
        )


@dataclass
class _PendingHostApproval:
    event: asyncio.Event = field(default_factory=asyncio.Event)
    decision: NetworkDecision | None = None


@dataclass
class NetworkApprovalService:
    """Runtime approval bridge used by managed network proxies.

    The service deliberately wraps the existing OpenSquilla approval queue so
    the rest of the sandbox can speak in Codex-shaped policy requests instead
    of hand-rolled approval payloads.
    """

    context: RunContext
    request: SandboxRequest
    runtime: Any
    approval_timeout_seconds: float | None = None
    consume_temporary_grants: bool = True
    session_key_override: str | None = None
    workspace_override: str | None = None
    approval_requester: Callable[..., dict[str, object]] = request_sandbox_approval
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _pending: dict[HostApprovalKey, _PendingHostApproval] = field(
        default_factory=dict,
        init=False,
    )

    def __call__(self, host: str) -> NetworkDecision:
        """Compatibility shim for old proxy fakes that synchronously ask by host."""
        effective_context = context_with_temporary_network_grants(
            self.context,
            fingerprint=self.fingerprint,
        )
        return decide_network_access(host, effective_context)

    async def decide(self, policy_request: NetworkPolicyRequest) -> NetworkDecision:
        key = HostApprovalKey.from_request(policy_request)
        async with self._lock:
            pending = self._pending.get(key)
            if pending is None:
                pending = _PendingHostApproval()
                self._pending[key] = pending
                owner = True
            else:
                owner = False

        if not owner:
            await pending.event.wait()
            return pending.decision or self._blocked(policy_request, "not_allowed")

        try:
            decision = await self._decide_owned(policy_request)
            pending.decision = decision
            return decision
        finally:
            pending.event.set()
            async with self._lock:
                self._pending.pop(key, None)

    async def _decide_owned(
        self,
        policy_request: NetworkPolicyRequest,
    ) -> NetworkDecision:
        effective_context = context_with_temporary_network_grants(
            self.context,
            fingerprint=self.fingerprint,
        )
        decision = decide_network_access(policy_request.host, effective_context)
        if decision.status == "allow":
            await self._consume_temporary_grant_if_needed(decision)
            return decision
        if decision.status == "block":
            return decision
        return await self._request_approval(policy_request, decision)

    async def _request_approval(
        self,
        policy_request: NetworkPolicyRequest,
        decision: NetworkDecision,
    ) -> NetworkDecision:
        params = build_network_approval_params(
            decision,
            session_key=self.session_key,
            workspace=self.workspace,
            fingerprint=self.fingerprint,
        )
        if params is None:
            return self._blocked(policy_request, decision.reason)

        payload = self.approval_requester(
            params,
            message=(
                "This network target is outside the current managed-network "
                "grants. Resolve this approval to continue the current request."
            ),
        )
        status = str(payload.get("status") or "")
        if status == "approval_denied":
            return self._blocked(policy_request, "denied")
        approval_id = str(payload.get("approval_id") or "")
        if not approval_id:
            return self._blocked(policy_request, "approval_missing")

        from opensquilla.gateway.approval_queue import get_approval_queue

        approved = await get_approval_queue().wait(
            approval_id,
            timeout=self.approval_timeout_seconds,
        )
        if not approved:
            return self._blocked(policy_request, "denied")

        return NetworkDecision(
            status="allow",
            normalized_host=decision.normalized_host,
            reason="approval",
            source="approval:sandbox_network",
        )

    async def _consume_temporary_grant_if_needed(self, decision: NetworkDecision) -> None:
        if not self.consume_temporary_grants:
            return
        if not has_temporary_network_grant(
            self.context,
            host=decision.normalized_host,
            fingerprint=self.fingerprint,
        ):
            return
        consume_temporary_network_grant(
            session_key=self.session_key,
            workspace=self.workspace,
            host=decision.normalized_host,
            fingerprint=self.fingerprint,
        )
        await consume_persisted_temporary_network_grant(
            session_key=self.session_key,
            workspace=self.workspace,
            host=decision.normalized_host,
            fingerprint=self.fingerprint,
        )

    def _blocked(self, request: NetworkPolicyRequest, reason: str) -> NetworkDecision:
        return NetworkDecision(
            status="block",
            normalized_host=request.host.casefold(),
            reason=reason or "not_allowed",
            source="approval",
        )

    @property
    def fingerprint(self) -> str:
        return action_fingerprint(self.request)

    @property
    def session_key(self) -> str | None:
        if self.session_key_override:
            return self.session_key_override
        value = str(self.request.session_id or "").strip()
        return value or None

    @property
    def workspace(self) -> str | None:
        if self.workspace_override:
            return self.workspace_override
        candidate = getattr(self.runtime, "workspace", None)
        if candidate:
            return str(candidate)
        return str(self.request.cwd) if self.request.cwd else None


async def call_network_policy_decider(
    decider: Any,
    request: NetworkPolicyRequest,
) -> NetworkDecision:
    decide = getattr(decider, "decide", None)
    result = decide(request) if callable(decide) else decider(request)
    if hasattr(result, "__await__"):
        result = await result
    if not isinstance(result, NetworkDecision):
        raise TypeError("network policy decider returned invalid decision")
    return result


__all__ = [
    "HostApprovalKey",
    "NetworkApprovalService",
    "NetworkPolicyDecider",
    "NetworkPolicyRequest",
    "NetworkProtocol",
    "call_network_policy_decider",
]
