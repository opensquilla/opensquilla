from __future__ import annotations

from types import SimpleNamespace

import pytest

from opensquilla.gateway.config import GatewayConfig
from opensquilla.gateway.rpc import RpcContext, RpcHandlerError, get_dispatcher
from opensquilla.gateway.rpc_knowledge import (
    _handle_knowledge_get,
    _handle_knowledge_profile_set,
    _handle_knowledge_search,
    _handle_knowledge_status,
)
from opensquilla.gateway.rag_provider_runtime import RagProviderState
from opensquilla.rag_provider.protocol import ValidatedSearchResponse


class Snapshot:
    state = RagProviderState.READY
    capabilities = SimpleNamespace(
        retrieval_profiles=(("vector", "Vector"), ("hybrid", "Hybrid")),
        default_retrieval_profile="hybrid",
    )

    def to_wire(self) -> dict[str, object]:
        return {
            "connectionState": "READY",
            "provider": {"name": "provider", "version": "1", "instanceId": "instance"},
            "protocolVersion": "1.0",
            "capabilities": {"search": True, "get": True},
            "effectiveLimits": {
                "maxSearchResults": 20,
                "maxSnippetChars": 800,
                "maxSearchResponseChars": 12000,
                "maxGetContentChars": 8000,
            },
            "searchOptions": {
                "supportsCollectionScope": True,
                "retrievalProfiles": [
                    {"id": "vector", "label": "Vector"},
                    {"id": "hybrid", "label": "Hybrid"},
                ],
                "defaultRetrievalProfile": "hybrid",
            },
            "links": {},
            "lastSuccessAt": None,
            "lastErrorCode": None,
            "consecutiveFailures": 0,
            "warning": None,
        }


class Runtime:
    def __init__(self) -> None:
        self.search_args: dict[str, object] | None = None
        self.get_args: dict[str, object] | None = None
        self.applied_profiles: list[str | None] = []

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

    def apply_retrieval_profile_override(self, profile: str | None) -> None:
        self.applied_profiles.append(profile)


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


@pytest.mark.asyncio
async def test_profile_set_persists_and_hot_applies(tmp_path) -> None:
    runtime = Runtime()
    config = GatewayConfig.model_validate(
        {
            "config_path": str(tmp_path / "config.toml"),
            "knowledge": {"enabled": True},
        }
    )
    ctx = _ctx(runtime, config)

    result = await _handle_knowledge_profile_set(
        {"retrievalProfileOverride": "vector"},
        ctx,
    )

    assert config.knowledge.retrieval_profile_override == "vector"
    assert runtime.applied_profiles == ["vector"]
    assert result == {
        "retrievalProfileOverride": "vector",
        "providerDefaultRetrievalProfile": "hybrid",
        "effectiveRetrievalProfile": "vector",
        "restartRequired": False,
    }

    cleared = await _handle_knowledge_profile_set(
        {"retrievalProfileOverride": None},
        ctx,
    )
    assert runtime.applied_profiles[-1] is None
    assert cleared["effectiveRetrievalProfile"] == "hybrid"


@pytest.mark.asyncio
async def test_profile_set_rejects_unadvertised_profile_without_mutation(
    tmp_path,
) -> None:
    runtime = Runtime()
    config = GatewayConfig.model_validate(
        {
            "config_path": str(tmp_path / "config.toml"),
            "knowledge": {"enabled": True},
        }
    )

    with pytest.raises(RpcHandlerError) as error:
        await _handle_knowledge_profile_set(
            {"retrievalProfileOverride": "missing"},
            _ctx(runtime, config),
        )

    assert error.value.code == "KNOWLEDGE_RETRIEVAL_PROFILE_UNAVAILABLE"
    assert config.knowledge.retrieval_profile_override is None
    assert runtime.applied_profiles == []


@pytest.mark.parametrize(
    "params",
    [
        None,
        [],
        {},
        {"retrievalProfileOverride": ""},
        {"retrievalProfileOverride": True},
        {"retrievalProfileOverride": "hybrid", "extra": 1},
    ],
)
@pytest.mark.asyncio
async def test_profile_set_rejects_invalid_params(params) -> None:
    with pytest.raises(ValueError):
        await _handle_knowledge_profile_set(params, _ctx(Runtime()))


@pytest.mark.asyncio
async def test_profile_set_persist_failure_does_not_change_runtime(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = Runtime()
    config = GatewayConfig.model_validate(
        {
            "config_path": str(tmp_path / "config.toml"),
            "knowledge": {"enabled": True},
        }
    )

    import opensquilla.onboarding.config_store as config_store

    def fail_replace(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(config_store.os, "replace", fail_replace)

    with pytest.raises(OSError, match="disk full"):
        await _handle_knowledge_profile_set(
            {"retrievalProfileOverride": "vector"},
            _ctx(runtime, config),
        )

    assert runtime.applied_profiles == []
    assert config.knowledge.retrieval_profile_override is None


@pytest.mark.asyncio
async def test_profile_clear_is_allowed_while_provider_is_unavailable(tmp_path) -> None:
    runtime = Runtime()
    runtime.snapshot = lambda: SimpleNamespace(
        state=RagProviderState.UNAVAILABLE,
        capabilities=None,
    )
    config = GatewayConfig.model_validate(
        {
            "config_path": str(tmp_path / "config.toml"),
            "knowledge": {
                "enabled": True,
                "retrieval_profile_override": "vector",
            },
        }
    )

    result = await _handle_knowledge_profile_set(
        {"retrievalProfileOverride": None},
        _ctx(runtime, config),
    )

    assert config.knowledge.retrieval_profile_override is None
    assert runtime.applied_profiles == [None]
    assert result == {
        "retrievalProfileOverride": None,
        "providerDefaultRetrievalProfile": None,
        "effectiveRetrievalProfile": None,
        "restartRequired": False,
    }


def test_old_provider_management_rpc_methods_are_not_registered() -> None:
    methods = set(get_dispatcher().methods())

    assert {
        "knowledge.status",
        "knowledge.search",
        "knowledge.get",
        "knowledge.profile.set",
    }.issubset(methods)
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
