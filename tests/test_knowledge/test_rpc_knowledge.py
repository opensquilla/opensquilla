from __future__ import annotations

import pytest

from opensquilla.gateway.config import GatewayConfig
from opensquilla.gateway.rpc import RpcContext, RpcHandlerError, get_dispatcher
from opensquilla.gateway.rpc_knowledge import (
    _handle_knowledge_get,
    _handle_knowledge_search,
    _handle_knowledge_status,
)
from opensquilla.rag_provider.protocol import ValidatedSearchResponse


class Snapshot:
    def to_wire(self) -> dict[str, object]:
        return {
            "connectionState": "READY",
            "provider": {"name": "provider", "version": "1", "instanceId": "instance"},
            "protocolVersion": "1.0",
            "capabilities": {"search": True, "get": True},
        }


class Runtime:
    def __init__(self) -> None:
        self.search_args: dict[str, object] | None = None
        self.get_args: dict[str, object] | None = None

    def snapshot(self) -> Snapshot:
        return Snapshot()

    async def search(self, *, query: str, limit: int) -> ValidatedSearchResponse:
        self.search_args = {"query": query, "limit": limit}
        return ValidatedSearchResponse(
            {
                "returnedCount": 1,
                "totalMatched": 1,
                "resultsTruncated": False,
                "results": [],
            },
            provider_budget_violation=True,
        )

    async def get(self, *, evidence_id: str, cursor: str | None) -> dict[str, object]:
        self.get_args = {"evidence_id": evidence_id, "cursor": cursor}
        return {"evidenceId": evidence_id, "content": "source"}


def _ctx(runtime: Runtime | None, config: GatewayConfig | None = None) -> RpcContext:
    return RpcContext(
        conn_id="test",
        config=config or GatewayConfig(),
        rag_provider_runtime=runtime,
    )


@pytest.mark.asyncio
async def test_status_returns_disabled_without_constructing_a_provider() -> None:
    result = await _handle_knowledge_status({}, _ctx(None))

    assert result["connectionState"] == "DISABLED"
    assert result["enabled"] is False
    assert result["collectionScope"] == []


@pytest.mark.asyncio
async def test_status_combines_runtime_snapshot_with_read_only_admin_config() -> None:
    config = GatewayConfig.model_validate(
        {
            "knowledge": {
                "enabled": True,
                "collection_scope": ["datasets"],
                "retrieval_profile_override": "hybrid",
            }
        }
    )

    result = await _handle_knowledge_status({}, _ctx(Runtime(), config))

    assert result["connectionState"] == "READY"
    assert result["collectionScope"] == ["datasets"]
    assert result["retrievalProfileOverride"] == "hybrid"
    assert "providerBaseUrl" not in result
    assert "authenticationTokenEnv" not in result


@pytest.mark.asyncio
async def test_search_and_get_accept_only_minimal_contract_parameters() -> None:
    runtime = Runtime()
    ctx = _ctx(runtime)

    search = await _handle_knowledge_search({"query": " NAND ", "limit": 8}, ctx)
    get = await _handle_knowledge_get(
        {"evidenceId": " ev_a ", "cursor": "next-page"}, ctx
    )

    assert runtime.search_args == {"query": "NAND", "limit": 8}
    assert search["providerBudgetViolation"] is True
    assert runtime.get_args == {"evidence_id": "ev_a", "cursor": "next-page"}
    assert get["evidenceId"] == "ev_a"

    with pytest.raises(ValueError, match="unexpected params"):
        await _handle_knowledge_search({"query": "NAND", "topK": 20}, ctx)
    with pytest.raises(ValueError, match="unexpected params"):
        await _handle_knowledge_get({"evidenceId": "ev_a", "documentId": "doc"}, ctx)


@pytest.mark.asyncio
async def test_calls_are_unavailable_when_provider_is_disabled() -> None:
    with pytest.raises(RpcHandlerError) as error:
        await _handle_knowledge_search({"query": "NAND"}, _ctx(None))
    assert error.value.code == "KNOWLEDGE_PROVIDER_UNAVAILABLE"
    assert error.value.retryable is True


def test_old_provider_management_rpc_methods_are_not_registered() -> None:
    methods = set(get_dispatcher().methods())

    assert {"knowledge.status", "knowledge.search", "knowledge.get"}.issubset(methods)
    assert methods.isdisjoint(
        {
            "knowledge.settings.get",
            "knowledge.settings.patch",
            "knowledge.collections",
            "knowledge.prepare_sample",
            "knowledge.ingest",
            "knowledge.questions",
            "knowledge.judgment",
        }
    )
