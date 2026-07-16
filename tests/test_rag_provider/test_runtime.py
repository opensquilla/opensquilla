from __future__ import annotations

from dataclasses import dataclass

import pytest

from opensquilla.gateway.rag_provider_runtime import RagProviderRuntime, RagProviderState
from opensquilla.rag_provider.protocol import (
    ProviderIncompatible,
    SearchBudget,
    ValidatedSearchResponse,
    validate_capabilities,
)
from opensquilla.tools.registry import ToolRegistry

from .test_protocol import capabilities


@dataclass
class Config:
    enabled: bool = True
    probe_interval_seconds: float = 60
    unavailable_after_seconds: float = 300
    max_consecutive_failures: int = 3
    retrieval_profile_override: str | None = None
    collection_scope: list[str] = None  # type: ignore[assignment]
    legacy_knowledge_adapter: bool = False

    def __post_init__(self) -> None:
        if self.collection_scope is None:
            self.collection_scope = []


class FakeClient:
    def __init__(self) -> None:
        self.fail = False
        self.supports_get = True
        self.closed = False
        self.capability_calls = 0
        self.incompatible = False
        self.max_chunk_chars = 4_096
        self.retrieval_profiles = [
            ("vector", "Vector"),
            ("hybrid", "Hybrid"),
        ]
        self.default_retrieval_profile: str | None = "hybrid"
        self.search_calls: list[dict[str, object]] = []
        self.get_calls: list[dict[str, object]] = []

    async def capabilities(self):
        self.capability_calls += 1
        if self.incompatible:
            raise ProviderIncompatible("unsupported major")
        if self.fail:
            raise RuntimeError("offline")
        payload = capabilities(version="1.1", get=self.supports_get)
        payload["limits"]["maxChunkChars"] = self.max_chunk_chars
        payload["searchOptions"] = {
            "supportsCollectionScope": False,
            "retrievalProfiles": [
                {"id": profile_id, "label": label}
                for profile_id, label in self.retrieval_profiles
            ],
            "defaultRetrievalProfile": self.default_retrieval_profile,
        }
        return validate_capabilities(payload)

    async def search(self, **kwargs):
        self.search_calls.append(dict(kwargs))
        return ValidatedSearchResponse(
            {
                "returnedCount": 0,
                "totalMatched": 0,
                "resultsTruncated": False,
                "results": [],
            },
            provider_budget_violation=False,
        )

    async def get(self, **kwargs):
        self.get_calls.append(dict(kwargs))
        return {"evidenceId": kwargs["evidence_id"]}

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_disabled_runtime_never_probes_or_registers() -> None:
    client = FakeClient()
    registry = ToolRegistry()
    runtime = RagProviderRuntime(Config(enabled=False), client, registry)
    await runtime.start(start_probe_loop=False)
    assert runtime.snapshot().state is RagProviderState.DISABLED
    assert client.capability_calls == 0
    assert client.search_calls == []
    assert client.get_calls == []
    assert registry.list_names() == []


@pytest.mark.asyncio
async def test_runtime_status_includes_effective_max_chunk_chars() -> None:
    client = FakeClient()
    runtime = RagProviderRuntime(Config(), client, ToolRegistry())

    await runtime.start(start_probe_loop=False)

    assert runtime.snapshot().to_wire()["effectiveLimits"]["maxChunkChars"] == 4_096


@pytest.mark.asyncio
async def test_runtime_search_uses_negotiated_chunk_budget_and_protocol_version() -> None:
    client = FakeClient()
    runtime = RagProviderRuntime(Config(), client, ToolRegistry())
    await runtime.start(start_probe_loop=False)

    await runtime.search(query="NAND", limit=8)

    call = client.search_calls[0]
    budget = call["budget"]
    assert isinstance(budget, SearchBudget)
    assert budget.max_chunk_chars == 4_096
    assert call["protocol_version"] == "1.1"


@pytest.mark.asyncio
async def test_runtime_get_uses_snapshot_protocol_version() -> None:
    client = FakeClient()
    runtime = RagProviderRuntime(Config(), client, ToolRegistry())
    await runtime.start(start_probe_loop=False)

    await runtime.get(evidence_id="ev_1", cursor=None)

    assert client.get_calls[0]["protocol_version"] == "1.1"


@pytest.mark.asyncio
async def test_runtime_registers_by_capability_and_unavailable_threshold() -> None:
    client = FakeClient()
    registry = ToolRegistry()
    runtime = RagProviderRuntime(Config(), client, registry)
    await runtime.start(start_probe_loop=False)
    assert runtime.snapshot().state is RagProviderState.READY
    assert {"knowledge_search", "knowledge_get"}.issubset(registry.list_names())

    client.fail = True
    await runtime.refresh()
    assert runtime.snapshot().state is RagProviderState.DEGRADED
    assert "knowledge_search" in registry.list_names()
    await runtime.refresh()
    await runtime.refresh()
    assert runtime.snapshot().state is RagProviderState.UNAVAILABLE
    assert "knowledge_search" not in registry.list_names()

    client.fail = False
    client.supports_get = False
    await runtime.refresh()
    assert runtime.snapshot().state is RagProviderState.READY
    assert "knowledge_search" in registry.list_names()
    assert "knowledge_get" not in registry.list_names()
    await runtime.stop()
    assert client.closed is True


@pytest.mark.asyncio
async def test_incompatible_provider_is_distinct_and_registers_no_tools() -> None:
    client = FakeClient()
    client.incompatible = True
    registry = ToolRegistry()
    runtime = RagProviderRuntime(Config(), client, registry)

    await runtime.start(start_probe_loop=False)

    assert runtime.snapshot().state is RagProviderState.INCOMPATIBLE
    assert runtime.snapshot().last_error_code == "provider_incompatible"
    assert registry.list_names() == []


@pytest.mark.asyncio
async def test_elapsed_unavailable_threshold_uses_monotonic_clock() -> None:
    now = [10.0]
    client = FakeClient()
    registry = ToolRegistry()
    runtime = RagProviderRuntime(
        Config(max_consecutive_failures=99, unavailable_after_seconds=300),
        client,
        registry,
        monotonic_clock=lambda: now[0],
        wall_clock=lambda: 1_700_000_000 + now[0],
    )
    await runtime.start(start_probe_loop=False)
    assert runtime.snapshot().last_success_at == 1_700_000_010

    client.fail = True
    now[0] = 309.9
    await runtime.refresh()
    assert runtime.snapshot().state is RagProviderState.DEGRADED
    now[0] = 310.0
    await runtime.refresh()

    assert runtime.snapshot().state is RagProviderState.UNAVAILABLE
    assert "knowledge_search" not in registry.list_names()


@pytest.mark.asyncio
async def test_degraded_tool_call_fails_without_stale_provider_request() -> None:
    client = FakeClient()
    registry = ToolRegistry()
    runtime = RagProviderRuntime(Config(), client, registry)
    await runtime.start(start_probe_loop=False)
    client.fail = True
    await runtime.refresh()

    with pytest.raises(RuntimeError, match="knowledge_provider_unavailable"):
        await runtime.search(query="NAND", limit=8)


@pytest.mark.asyncio
async def test_configured_collection_scope_is_never_silently_dropped() -> None:
    client = FakeClient()
    registry = ToolRegistry()
    runtime = RagProviderRuntime(Config(collection_scope=["private-dataset"]), client, registry)
    await runtime.start(start_probe_loop=False)
    assert runtime.snapshot().capabilities is not None
    assert runtime.snapshot().capabilities.supports_collection_scope is False

    with pytest.raises(RuntimeError, match="collection_scope_unsupported"):
        await runtime.search(query="NAND", limit=8)


@pytest.mark.asyncio
async def test_valid_profile_override_then_provider_default_apply_to_future_searches() -> None:
    client = FakeClient()
    runtime = RagProviderRuntime(Config(), client, ToolRegistry())
    await runtime.start(start_probe_loop=False)

    runtime.apply_retrieval_profile_override("vector")
    await runtime.search(query="NAND", limit=8)
    runtime.apply_retrieval_profile_override(None)
    await runtime.search(query="DRAM", limit=8)

    assert client.search_calls[0]["retrieval_profile"] == "vector"
    assert client.search_calls[1]["retrieval_profile"] == "hybrid"


@pytest.mark.asyncio
async def test_invalid_profile_override_falls_back_to_provider_default() -> None:
    client = FakeClient()
    runtime = RagProviderRuntime(
        Config(retrieval_profile_override="retired-profile"),
        client,
        ToolRegistry(),
    )
    await runtime.start(start_probe_loop=False)

    await runtime.search(query="NAND", limit=8)

    assert client.search_calls[0]["retrieval_profile"] == "hybrid"


@pytest.mark.asyncio
async def test_null_profile_is_used_when_no_valid_override_or_provider_default() -> None:
    client = FakeClient()
    client.default_retrieval_profile = None
    runtime = RagProviderRuntime(Config(), client, ToolRegistry())
    await runtime.start(start_probe_loop=False)

    await runtime.search(query="NAND", limit=8)

    assert client.search_calls[0]["retrieval_profile"] is None


@pytest.mark.asyncio
async def test_refreshed_provider_profiles_and_default_remain_authoritative() -> None:
    client = FakeClient()
    runtime = RagProviderRuntime(
        Config(retrieval_profile_override="vector"),
        client,
        ToolRegistry(),
    )
    await runtime.start(start_probe_loop=False)
    await runtime.search(query="NAND", limit=8)

    client.retrieval_profiles = [("provider-new-default", "Provider new default")]
    client.default_retrieval_profile = "provider-new-default"
    await runtime.refresh()
    await runtime.search(query="DRAM", limit=8)

    assert client.search_calls[0]["retrieval_profile"] == "vector"
    assert (
        client.search_calls[1]["retrieval_profile"]
        == "provider-new-default"
    )
