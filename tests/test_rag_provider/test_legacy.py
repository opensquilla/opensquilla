from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from opensquilla.gateway.rag_provider_runtime import RagProviderRuntime, RagProviderState
from opensquilla.rag_provider import legacy as legacy_module
from opensquilla.rag_provider.legacy import LEGACY_WARNING, LegacyKnowledgeAdapter
from opensquilla.rag_provider.protocol import (
    ProviderNotFound,
    ProviderProtocolViolation,
    ProviderUnavailable,
    SearchBudget,
    validate_capabilities,
    validate_get_response,
    validate_search_response,
)
from opensquilla.tools.registry import ToolRegistry


class Backend:
    def __init__(self) -> None:
        self.search_calls = 0

    def search(self, query: str, *, top_k: int, filters: dict | None):
        self.search_calls += 1
        return {
            "count": 1,
            "results": [
                {
                    "chunkId": "chunk-a",
                    "documentId": "doc-a",
                    "title": "Legacy document",
                    "source": "legacy-source",
                    "citation": "legacy/path.md#page=1",
                    "snippet": "matching legacy evidence",
                    "score": 99.0,
                    "vectorScore": 0.9,
                }
            ],
        }

    def get(self, *, chunk_id: str | None, document_id: str | None):
        if chunk_id != "chunk-a":
            return None
        return {
            "chunkId": "chunk-a",
            "documentId": "doc-a",
            "title": "Legacy document",
            "source": "legacy-source",
            "citation": "legacy/path.md#page=1",
            "text": "legacy chunk text, not guaranteed full document text",
        }


class UnavailableBackend(Backend):
    def search(self, query: str, *, top_k: int, filters: dict | None):
        raise OSError("offline")


@dataclass
class Config:
    enabled: bool = True
    legacy_knowledge_adapter: bool = True
    probe_interval_seconds: float = 60
    unavailable_after_seconds: float = 300
    max_consecutive_failures: int = 3
    retrieval_profile_override: str | None = None
    collection_scope: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.collection_scope is None:
            self.collection_scope = []


@pytest.mark.asyncio
async def test_legacy_capabilities_use_exact_protocol_1_0_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validated_versions: list[str] = []

    def validate(raw: Any):
        validated_versions.append(raw["protocol"]["version"])
        return validate_capabilities(raw)

    monkeypatch.setattr(
        legacy_module,
        "validate_capabilities",
        validate,
        raising=False,
    )

    snapshot = await LegacyKnowledgeAdapter(Backend()).capabilities()

    assert validated_versions == ["1.0"]
    assert snapshot.protocol_version == "1.0"
    assert snapshot.retrieval_profiles == ()
    assert snapshot.default_retrieval_profile is None


@pytest.mark.asyncio
async def test_legacy_search_maps_to_minimal_standard_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validated_versions: list[str] = []

    def validate(
        raw: Any,
        *,
        budget: SearchBudget,
        protocol_version: str,
    ):
        validated_versions.append(protocol_version)
        return validate_search_response(
            raw,
            budget=budget,
            protocol_version=protocol_version,
        )

    monkeypatch.setattr(legacy_module, "validate_search_response", validate)
    adapter = LegacyKnowledgeAdapter(Backend())

    first = await adapter.search(
        query="NAND",
        limit=8,
        budget=SearchBudget(max_snippet_chars=800, max_total_chars=12_000),
    )
    second = await adapter.search(
        query="NAND",
        limit=8,
        budget=SearchBudget(max_snippet_chars=800, max_total_chars=12_000),
    )

    assert first.payload == second.payload
    assert validated_versions == ["1.0", "1.0"]
    item = first.payload["results"][0]
    assert set(item) == {"evidenceId", "snippet", "snippetTruncated", "citation"}
    assert "score" not in item

    with pytest.raises(ProviderProtocolViolation, match="only supports protocol 1.0"):
        await adapter.search(
            query="NAND",
            limit=8,
            budget=SearchBudget(max_snippet_chars=800, max_total_chars=12_000),
            protocol_version="1.1",
        )


@pytest.mark.asyncio
async def test_legacy_get_is_explicitly_limited_and_does_not_invent_cursors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validated_versions: list[str] = []

    def validate(
        raw: Any,
        *,
        evidence_id: str,
        max_content_chars: int,
        protocol_version: str,
    ):
        validated_versions.append(protocol_version)
        return validate_get_response(
            raw,
            evidence_id=evidence_id,
            max_content_chars=max_content_chars,
            protocol_version=protocol_version,
        )

    monkeypatch.setattr(
        legacy_module,
        "validate_get_response",
        validate,
        raising=False,
    )
    adapter = LegacyKnowledgeAdapter(Backend())
    search = await adapter.search(
        query="NAND",
        limit=8,
        budget=SearchBudget(max_snippet_chars=800, max_total_chars=12_000),
    )
    evidence_id = search.payload["results"][0]["evidenceId"]

    payload = await adapter.get(
        evidence_id=evidence_id,
        cursor=None,
        max_content_chars=8_000,
    )

    assert validated_versions == ["1.0"]
    assert payload["previousCursor"] is None
    assert payload["nextCursor"] is None
    assert payload["legacyLimitedGet"] is True
    assert payload["document"] == {
        "title": "Legacy document",
        "source": "legacy-source",
    }
    assert payload["citation"] == {
        "title": "Legacy document",
        "source": "legacy-source",
        "locator": "legacy/path.md#page=1",
    }
    assert "contentChars" not in payload
    with pytest.raises(ProviderNotFound):
        await adapter.get(evidence_id="unknown", cursor=None, max_content_chars=8_000)
    with pytest.raises(ProviderProtocolViolation, match="only supports protocol 1.0"):
        await adapter.get(
            evidence_id=evidence_id,
            cursor=None,
            max_content_chars=8_000,
            protocol_version="1.1",
        )


@pytest.mark.asyncio
async def test_legacy_tool_model_projection_remains_snippet_based() -> None:
    registry = ToolRegistry()
    runtime = RagProviderRuntime(
        Config(),
        LegacyKnowledgeAdapter(Backend()),
        registry,
    )
    await runtime.start(start_probe_loop=False)
    registered = registry.get("knowledge_search")

    assert registered is not None
    raw_result = await registered.handler(query="NAND", limit=8)
    assert registered.spec.model_result_projector is not None
    projected = json.loads(registered.spec.model_result_projector(raw_result))

    item = projected["results"][0]
    assert item["snippet"] == "matching legacy evidence"
    assert not {
        "document",
        "chunk",
        "rank",
        "retrieval",
        "contentChars",
    }.intersection(item)
    assert "retrieval" not in projected


@pytest.mark.asyncio
async def test_legacy_error_mapping_and_disabled_switch_remain_compatible() -> None:
    unavailable = LegacyKnowledgeAdapter(UnavailableBackend())
    with pytest.raises(ProviderUnavailable, match="legacy knowledge backend"):
        await unavailable.search(
            query="NAND",
            limit=8,
            budget=SearchBudget(max_snippet_chars=800, max_total_chars=12_000),
        )

    registry = ToolRegistry()
    runtime = RagProviderRuntime(
        Config(enabled=False),
        LegacyKnowledgeAdapter(Backend()),
        registry,
    )
    await runtime.start(start_probe_loop=False)

    assert runtime.snapshot().state is RagProviderState.DISABLED
    assert runtime.snapshot().to_wire()["warning"] is None
    assert registry.list_names() == []


@pytest.mark.asyncio
async def test_runtime_reports_legacy_and_fixed_warning() -> None:
    adapter = LegacyKnowledgeAdapter(Backend())
    registry = ToolRegistry()
    runtime = RagProviderRuntime(Config(), adapter, registry)

    await runtime.start(start_probe_loop=False)

    assert runtime.snapshot().state is RagProviderState.LEGACY
    assert runtime.snapshot().to_wire()["warning"] == LEGACY_WARNING
    assert {"knowledge_search", "knowledge_get"}.issubset(registry.list_names())
