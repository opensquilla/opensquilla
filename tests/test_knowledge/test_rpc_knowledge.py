from __future__ import annotations

from types import SimpleNamespace

import pytest

from opensquilla.gateway.config import GatewayConfig
from opensquilla.gateway.rag_provider_runtime import (
    RagProviderRuntime,
    RagProviderState,
)
from opensquilla.gateway.rpc import RpcContext, RpcHandlerError, get_dispatcher
from opensquilla.gateway.rpc_knowledge import (
    _handle_knowledge_get,
    _handle_knowledge_profile_set,
    _handle_knowledge_search,
    _handle_knowledge_status,
)
from opensquilla.rag_provider.protocol import (
    ProviderAuthenticationError,
    ProviderBudgetViolation,
    ProviderNotFound,
    ProviderProtocolViolation,
    ValidatedSearchResponse,
)
from opensquilla.tools.registry import ToolRegistry


def _full_search_payload() -> dict[str, object]:
    content = "Complete normalized NAND evidence."
    return {
        "returnedCount": 1,
        "totalMatched": 7,
        "resultsTruncated": True,
        "retrieval": {"profile": "provider-profile"},
        "results": [
            {
                "evidenceId": "ev_a",
                "rank": 1,
                "document": {
                    "id": "doc_a",
                    "title": "NAND architecture",
                    "source": "datasets",
                    "fileName": "nand.md",
                    "sourcePath": "datasets/nand.md",
                    "mediaType": "text/markdown",
                    "revision": "sha256:abc",
                    "uri": "knowledge://documents/doc_a",
                    "openUrl": "/knowledge/files/doc_a?chunkId=chunk_a",
                },
                "chunk": {
                    "id": "chunk_a",
                    "content": content,
                    "contentChars": len(content),
                },
                "snippet": "Complete normalized",
                "snippetTruncated": True,
                "citation": {
                    "title": "NAND architecture",
                    "source": "datasets",
                    "locator": "section 2",
                    "uri": "knowledge://documents/doc_a#chunk=chunk_a",
                },
            }
        ],
    }


def _full_get_payload(evidence_id: str = "ev_a") -> dict[str, object]:
    content = "Complete paged NAND evidence."
    return {
        "evidenceId": evidence_id,
        "document": {
            "id": "doc_a",
            "title": "NAND architecture",
            "source": "datasets",
            "fileName": "nand.md",
            "sourcePath": "datasets/nand.md",
            "mediaType": "text/markdown",
            "revision": "sha256:abc",
            "uri": "knowledge://documents/doc_a",
            "openUrl": "/knowledge/files/doc_a?chunkId=chunk_a",
        },
        "content": content,
        "contentChars": len(content),
        "previousCursor": "previous-page",
        "nextCursor": "next-page",
        "citation": {
            "title": "NAND architecture",
            "source": "datasets",
            "locator": "section 2",
            "uri": "knowledge://documents/doc_a#chunk=chunk_a",
        },
    }


class Snapshot:
    state = RagProviderState.READY
    capabilities = SimpleNamespace(
        protocol_version="1.1",
        retrieval_profiles=(("vector", "Vector"), ("hybrid", "Hybrid")),
        default_retrieval_profile="hybrid",
        supports_collection_scope=True,
        limits=SimpleNamespace(
            max_search_results=20,
            max_snippet_chars=800,
            max_search_response_chars=12000,
            max_get_content_chars=8000,
            max_chunk_chars=4096,
        ),
    )

    def to_wire(self) -> dict[str, object]:
        return {
            "connectionState": "READY",
            "provider": {"name": "provider", "version": "1", "instanceId": "instance"},
            "protocolVersion": "1.1",
            "capabilities": {"search": True, "get": True},
            "effectiveLimits": {
                "maxSearchResults": 20,
                "maxSnippetChars": 800,
                "maxSearchResponseChars": 12000,
                "maxGetContentChars": 8000,
                "maxChunkChars": 4096,
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
            _full_search_payload(),
            provider_budget_violation=True,
        )

    async def get(self, *, evidence_id: str, cursor: str | None) -> dict[str, object]:
        self.get_args = {"evidence_id": evidence_id, "cursor": cursor}
        return _full_get_payload(evidence_id)

    def apply_retrieval_profile_override(self, profile: str | None) -> None:
        self.applied_profiles.append(profile)


class RecordingProviderClient:
    def __init__(self) -> None:
        self.search_calls: list[dict[str, object]] = []

    async def search(self, **kwargs) -> ValidatedSearchResponse:
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


def _ctx(
    runtime: Runtime | RagProviderRuntime | None,
    config: GatewayConfig | None = None,
) -> RpcContext:
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
    assert result["effectiveRetrievalProfile"] is None
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
    assert result["effectiveRetrievalProfile"] == "hybrid"
    assert result["effectiveLimits"]["maxChunkChars"] == 4096
    assert result["searchOptions"] == {
        "supportsCollectionScope": True,
        "retrievalProfiles": [
            {"id": "vector", "label": "Vector"},
            {"id": "hybrid", "label": "Hybrid"},
        ],
        "defaultRetrievalProfile": "hybrid",
    }
    assert "providerBaseUrl" not in result
    assert "authenticationTokenEnv" not in result


@pytest.mark.asyncio
async def test_status_falls_back_to_provider_default_for_unadvertised_override() -> None:
    config = GatewayConfig.model_validate(
        {
            "knowledge": {
                "enabled": True,
                "retrieval_profile_override": "retired-profile",
            }
        }
    )

    result = await _handle_knowledge_status({}, _ctx(Runtime(), config))

    assert result["retrievalProfileOverride"] == "retired-profile"
    assert result["effectiveRetrievalProfile"] == "hybrid"


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
async def test_search_returns_complete_v11_runtime_payload_without_query() -> None:
    result = await _handle_knowledge_search(
        {"query": " NAND ", "limit": 8},
        _ctx(Runtime()),
    )

    assert result == {
        **_full_search_payload(),
        "providerBudgetViolation": True,
    }
    assert "query" not in result


@pytest.mark.asyncio
async def test_search_does_not_add_optional_total_matched() -> None:
    class RuntimeWithoutTotal(Runtime):
        async def search(self, *, query: str, limit: int) -> ValidatedSearchResponse:
            return ValidatedSearchResponse(
                {
                    "returnedCount": 0,
                    "resultsTruncated": False,
                    "retrieval": {"profile": None},
                    "results": [],
                },
                provider_budget_violation=False,
            )

    result = await _handle_knowledge_search(
        {"query": "NAND"},
        _ctx(RuntimeWithoutTotal()),
    )

    assert result == {
        "returnedCount": 0,
        "resultsTruncated": False,
        "retrieval": {"profile": None},
        "results": [],
        "providerBudgetViolation": False,
    }
    assert "totalMatched" not in result


@pytest.mark.asyncio
async def test_get_returns_complete_v11_runtime_payload() -> None:
    result = await _handle_knowledge_get(
        {"evidenceId": " ev_a ", "cursor": "next-page"},
        _ctx(Runtime()),
    )

    assert result == _full_get_payload()


@pytest.mark.asyncio
async def test_rpc_does_not_run_model_or_source_projectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensquilla.rag_provider import projections

    def fail_projection(*args, **kwargs):
        raise AssertionError("RPC must not run ToolSpec projectors")

    monkeypatch.setattr(projections, "project_search_response_for_model", fail_projection)
    monkeypatch.setattr(projections, "project_search_response_for_sources", fail_projection)
    monkeypatch.setattr(projections, "project_get_response_for_model", fail_projection)
    monkeypatch.setattr(projections, "project_get_response_for_sources", fail_projection)

    search = await _handle_knowledge_search({"query": "NAND"}, _ctx(Runtime()))
    get = await _handle_knowledge_get({"evidenceId": "ev_a"}, _ctx(Runtime()))

    assert search["results"][0]["chunk"]["id"] == "chunk_a"
    assert search["results"][0]["document"]["openUrl"].startswith("/knowledge/")
    assert get["contentChars"] == len(get["content"])


@pytest.mark.asyncio
async def test_legacy_search_and_get_payloads_remain_unchanged() -> None:
    class LegacyRuntime(Runtime):
        async def search(self, *, query: str, limit: int) -> ValidatedSearchResponse:
            self.search_args = {"query": query, "limit": limit}
            return ValidatedSearchResponse(
                {
                    "returnedCount": 1,
                    "totalMatched": None,
                    "resultsTruncated": False,
                    "results": [
                        {
                            "evidenceId": "ev_legacy",
                            "snippet": "legacy evidence",
                            "snippetTruncated": False,
                            "citation": {
                                "title": "Legacy document",
                                "source": "legacy",
                                "locator": "page 1",
                            },
                        }
                    ],
                },
                provider_budget_violation=False,
            )

        async def get(
            self, *, evidence_id: str, cursor: str | None
        ) -> dict[str, object]:
            self.get_args = {"evidence_id": evidence_id, "cursor": cursor}
            return {
                "evidenceId": evidence_id,
                "document": {"title": "Legacy document", "source": "legacy"},
                "content": "legacy content",
                "previousCursor": None,
                "nextCursor": None,
                "citation": {
                    "title": "Legacy document",
                    "source": "legacy",
                    "locator": "page 1",
                },
            }

    runtime = LegacyRuntime()

    search = await _handle_knowledge_search({"query": "legacy"}, _ctx(runtime))
    get = await _handle_knowledge_get({"evidenceId": "ev_legacy"}, _ctx(runtime))

    assert search == {
        "returnedCount": 1,
        "totalMatched": None,
        "resultsTruncated": False,
        "results": [
            {
                "evidenceId": "ev_legacy",
                "snippet": "legacy evidence",
                "snippetTruncated": False,
                "citation": {
                    "title": "Legacy document",
                    "source": "legacy",
                    "locator": "page 1",
                },
            }
        ],
        "providerBudgetViolation": False,
    }
    assert get == {
        "evidenceId": "ev_legacy",
        "document": {"title": "Legacy document", "source": "legacy"},
        "content": "legacy content",
        "previousCursor": None,
        "nextCursor": None,
        "citation": {
            "title": "Legacy document",
            "source": "legacy",
            "locator": "page 1",
        },
    }


@pytest.mark.asyncio
async def test_calls_are_unavailable_when_provider_is_disabled() -> None:
    with pytest.raises(RpcHandlerError) as error:
        await _handle_knowledge_search({"query": "NAND"}, _ctx(None))
    assert error.value.code == "KNOWLEDGE_PROVIDER_UNAVAILABLE"
    assert error.value.retryable is True

    with pytest.raises(RpcHandlerError) as get_error:
        await _handle_knowledge_get({"evidenceId": "ev_a"}, _ctx(None))
    assert get_error.value.code == "KNOWLEDGE_PROVIDER_UNAVAILABLE"
    assert get_error.value.retryable is True


@pytest.mark.parametrize(
    ("provider_error", "expected_code", "retryable"),
    [
        (
            ProviderAuthenticationError("bad credentials"),
            "KNOWLEDGE_PROVIDER_AUTHENTICATION_ERROR",
            False,
        ),
        (ProviderNotFound("missing"), "KNOWLEDGE_NOT_FOUND", False),
        (
            ProviderBudgetViolation("too large"),
            "KNOWLEDGE_PROVIDER_BUDGET_VIOLATION",
            False,
        ),
        (
            ProviderProtocolViolation("invalid"),
            "KNOWLEDGE_PROVIDER_PROTOCOL_VIOLATION",
            False,
        ),
        (RuntimeError("offline"), "KNOWLEDGE_PROVIDER_UNAVAILABLE", True),
    ],
)
@pytest.mark.asyncio
async def test_search_error_mapping_is_unchanged(
    provider_error: Exception,
    expected_code: str,
    retryable: bool,
) -> None:
    class FailingRuntime(Runtime):
        async def search(self, *, query: str, limit: int) -> ValidatedSearchResponse:
            raise provider_error

    with pytest.raises(RpcHandlerError) as raised:
        await _handle_knowledge_search({"query": "NAND"}, _ctx(FailingRuntime()))

    assert raised.value.code == expected_code
    assert raised.value.retryable is retryable


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
async def test_profile_set_keeps_real_runtime_in_sync_after_config_object_swap(
    tmp_path,
) -> None:
    config = GatewayConfig.model_validate(
        {
            "config_path": str(tmp_path / "config.toml"),
            "knowledge": {"enabled": True},
        }
    )
    client = RecordingProviderClient()
    runtime = RagProviderRuntime(config.knowledge, client, ToolRegistry())
    runtime._snapshot = Snapshot()
    runtime_settings = runtime.config
    ctx = _ctx(runtime, config)

    await _handle_knowledge_profile_set(
        {"retrievalProfileOverride": "vector"},
        ctx,
    )

    assert ctx.config.knowledge is not runtime_settings
    assert ctx.config.knowledge.retrieval_profile_override == "vector"
    assert runtime.config.retrieval_profile_override == "vector"
    await runtime.search(query="NAND", limit=8)
    assert client.search_calls[-1]["retrieval_profile"] == "vector"

    await _handle_knowledge_profile_set(
        {"retrievalProfileOverride": None},
        ctx,
    )

    assert ctx.config.knowledge.retrieval_profile_override is None
    assert runtime.config.retrieval_profile_override is None
    await runtime.search(query="DRAM", limit=8)
    assert client.search_calls[-1]["retrieval_profile"] == "hybrid"


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
