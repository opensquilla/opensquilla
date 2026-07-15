from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from opensquilla.gateway.rag_provider_tools import (
    ToolBinding,
    rag_provider_tool_bindings,
)
from opensquilla.rag_provider.protocol import (
    CapabilitiesSnapshot,
    ProviderAuthenticationError,
    ProviderBudgetViolation,
    ProviderIncompatible,
    ProviderNotFound,
    ProviderProtocolViolation,
    ProviderUnavailable,
    SearchBudget,
)
from opensquilla.tools.registry import ToolRegistry


class RagProviderState(StrEnum):
    DISABLED = "DISABLED"
    CONNECTING = "CONNECTING"
    READY = "READY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    INCOMPATIBLE = "INCOMPATIBLE"
    LEGACY = "LEGACY"


@dataclass(frozen=True)
class RuntimeSnapshot:
    state: RagProviderState
    capabilities: CapabilitiesSnapshot | None = None
    last_success_at: float | None = None
    last_error_code: str | None = None
    consecutive_failures: int = 0

    def to_wire(self) -> dict[str, Any]:
        capabilities = self.capabilities
        return {
            "connectionState": self.state.value,
            "provider": (
                {
                    "name": capabilities.provider_name,
                    "version": capabilities.provider_version,
                    "instanceId": capabilities.instance_id,
                }
                if capabilities
                else None
            ),
            "protocolVersion": capabilities.protocol_version if capabilities else None,
            "capabilities": (
                {"search": True, "get": capabilities.supports_get}
                if capabilities
                else None
            ),
            "effectiveLimits": (
                {
                    "maxSearchResults": capabilities.limits.max_search_results,
                    "maxSnippetChars": capabilities.limits.max_snippet_chars,
                    "maxSearchResponseChars": capabilities.limits.max_search_response_chars,
                    "maxGetContentChars": capabilities.limits.max_get_content_chars,
                }
                if capabilities
                else None
            ),
            "searchOptions": (
                {
                    "supportsCollectionScope": capabilities.supports_collection_scope,
                    "retrievalProfiles": [
                        {"id": profile_id, "label": label}
                        for profile_id, label in capabilities.retrieval_profiles
                    ],
                    "defaultRetrievalProfile": capabilities.default_retrieval_profile,
                }
                if capabilities
                else None
            ),
            "links": (
                {"management": capabilities.management_url}
                if capabilities and capabilities.management_url
                else {}
            ),
            "lastSuccessAt": self.last_success_at,
            "lastErrorCode": self.last_error_code,
            "consecutiveFailures": self.consecutive_failures,
            "legacyConfigPresent": self.state is RagProviderState.LEGACY,
            "warning": (
                _legacy_warning() if self.state is RagProviderState.LEGACY else None
            ),
        }


class RagProviderRuntime:
    def __init__(
        self,
        config: Any,
        client: Any,
        registry: ToolRegistry,
        *,
        monotonic_clock: Any = time.monotonic,
        wall_clock: Any = time.time,
    ) -> None:
        self.config = config
        self.client = client
        self.registry = registry
        self._monotonic_clock = monotonic_clock
        self._wall_clock = wall_clock
        self._last_success_monotonic: float | None = None
        self._snapshot = RuntimeSnapshot(RagProviderState.DISABLED)
        self._bindings: dict[str, ToolBinding] = rag_provider_tool_bindings(self)
        self._registered: set[str] = set()
        self._probe_task: asyncio.Task[None] | None = None

    def snapshot(self) -> RuntimeSnapshot:
        return self._snapshot

    def apply_retrieval_profile_override(self, profile: str | None) -> None:
        """Apply the persisted OpenSquilla search override to future calls."""
        self.config.retrieval_profile_override = profile

    async def start(self, *, start_probe_loop: bool = True) -> None:
        if not bool(self.config.enabled):
            self._snapshot = RuntimeSnapshot(RagProviderState.DISABLED)
            return
        self._snapshot = RuntimeSnapshot(RagProviderState.CONNECTING)
        await self.refresh()
        if start_probe_loop:
            self._probe_task = asyncio.create_task(self._probe_loop())

    async def _probe_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(float(self.config.probe_interval_seconds))
                await self.refresh()
        except asyncio.CancelledError:
            raise

    async def refresh(self) -> None:
        previous = self._snapshot
        try:
            capabilities = await self.client.capabilities()
        except ProviderIncompatible:
            self._snapshot = RuntimeSnapshot(
                RagProviderState.INCOMPATIBLE,
                last_success_at=previous.last_success_at,
                last_error_code="provider_incompatible",
                consecutive_failures=previous.consecutive_failures + 1,
            )
            self._sync_tools()
            return
        except Exception as error:  # capability schemas fail closed
            failures = previous.consecutive_failures + 1
            last_success = previous.last_success_at
            elapsed = (
                self._monotonic_clock() - self._last_success_monotonic
                if self._last_success_monotonic is not None
                else None
            )
            unavailable = (
                previous.state in {RagProviderState.CONNECTING, RagProviderState.UNAVAILABLE}
                or failures >= int(self.config.max_consecutive_failures)
                or (elapsed is not None and elapsed >= float(self.config.unavailable_after_seconds))
            )
            state = RagProviderState.UNAVAILABLE if unavailable else RagProviderState.DEGRADED
            self._snapshot = RuntimeSnapshot(
                state,
                capabilities=previous.capabilities,
                last_success_at=last_success,
                last_error_code=_safe_error_code(error),
                consecutive_failures=failures,
            )
            self._sync_tools()
            return
        self._last_success_monotonic = self._monotonic_clock()
        state = (
            RagProviderState.LEGACY
            if bool(getattr(self.config, "legacy_knowledge_adapter", False))
            else RagProviderState.READY
        )
        self._snapshot = RuntimeSnapshot(
            state,
            capabilities=capabilities,
            last_success_at=self._wall_clock(),
        )
        self._sync_tools()

    def _sync_tools(self) -> None:
        snapshot = self._snapshot
        target: set[str] = set()
        if snapshot.state in {
            RagProviderState.READY,
            RagProviderState.DEGRADED,
            RagProviderState.LEGACY,
        }:
            target.add("knowledge_search")
            if snapshot.capabilities and snapshot.capabilities.supports_get:
                target.add("knowledge_get")
        for name in sorted(self._registered - target):
            self.registry.unregister(name)
            self._registered.remove(name)
        for name in sorted(target - self._registered):
            binding = self._bindings[name]
            self.registry.register(binding.spec, binding.handler)
            self._registered.add(name)

    async def search(self, *, query: str, limit: int):
        snapshot = self._snapshot
        if snapshot.state not in {RagProviderState.READY, RagProviderState.LEGACY}:
            raise RuntimeError("knowledge_provider_unavailable")
        capabilities = snapshot.capabilities
        if capabilities is None:
            raise RuntimeError("knowledge_provider_unavailable")
        effective_limit = min(limit, capabilities.limits.max_search_results)
        collections = tuple(self.config.collection_scope)
        if collections and not capabilities.supports_collection_scope:
            raise RuntimeError("collection_scope_unsupported")
        profile = self.config.retrieval_profile_override
        available = {item[0] for item in capabilities.retrieval_profiles}
        if profile and profile not in available:
            raise RuntimeError("retrieval_profile_unavailable")
        return await self.client.search(
            query=query,
            limit=effective_limit,
            budget=SearchBudget(
                max_snippet_chars=capabilities.limits.max_snippet_chars,
                max_total_chars=capabilities.limits.max_search_response_chars,
                max_results=effective_limit,
            ),
            collection_ids=collections,
            retrieval_profile=profile,
        )

    async def get(self, *, evidence_id: str, cursor: str | None):
        snapshot = self._snapshot
        capabilities = snapshot.capabilities
        if (
            snapshot.state not in {RagProviderState.READY, RagProviderState.LEGACY}
            or capabilities is None
            or not capabilities.supports_get
        ):
            raise RuntimeError("knowledge_get_unavailable")
        return await self.client.get(
            evidence_id=evidence_id,
            cursor=cursor,
            max_content_chars=capabilities.limits.max_get_content_chars,
        )

    async def stop(self) -> None:
        if self._probe_task is not None:
            self._probe_task.cancel()
            try:
                await self._probe_task
            except asyncio.CancelledError:
                pass
            self._probe_task = None
        for name in tuple(self._registered):
            self.registry.unregister(name)
        self._registered.clear()
        await self.client.close()


def create_rag_provider_runtime(config: Any, registry: ToolRegistry) -> RagProviderRuntime:
    """Build the one explicitly configured Provider runtime.

    Callers must gate this factory on ``config.knowledge.enabled``.  Keeping
    disabled construction out of this function makes the no-network/no-client
    boot invariant straightforward to audit.
    """
    settings = config.knowledge
    if bool(settings.legacy_knowledge_adapter):
        from opensquilla.knowledge.manager import manager_from_config
        from opensquilla.rag_provider.legacy import LegacyKnowledgeAdapter

        client: Any = LegacyKnowledgeAdapter(manager_from_config(config))
    else:
        from opensquilla.rag_provider.client import RagProviderClient

        client = RagProviderClient(
            base_url=settings.provider_base_url,
            token_env=settings.authentication_token_env,
            connect_timeout_seconds=settings.connect_timeout_seconds,
            request_timeout_seconds=settings.request_timeout_seconds,
        )
    return RagProviderRuntime(settings, client, registry)


def _safe_error_code(error: Exception) -> str:
    if isinstance(error, ProviderAuthenticationError):
        return "provider_authentication_error"
    if isinstance(error, ProviderBudgetViolation):
        return "provider_budget_violation"
    if isinstance(error, ProviderProtocolViolation):
        return "provider_protocol_violation"
    if isinstance(error, ProviderNotFound):
        return "provider_not_found"
    if isinstance(error, ProviderUnavailable):
        return "provider_unavailable"
    return "provider_unavailable"


def _legacy_warning() -> str:
    from opensquilla.rag_provider.legacy import LEGACY_WARNING

    return LEGACY_WARNING
