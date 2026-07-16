from __future__ import annotations

import json
from typing import Any

import pytest

from opensquilla.engine.types import ToolCall
from opensquilla.gateway.rag_provider_tools import rag_provider_tool_bindings
from opensquilla.rag_provider.projections import (
    SOURCE_SNIPPET_MAX_CHARS,
    project_get_response_for_model,
    project_get_response_for_sources,
    project_search_response_for_model,
    project_search_response_for_sources,
)
from opensquilla.rag_provider.protocol import (
    ProviderNotFound,
    ProviderProtocolViolation,
    ProviderUnavailable,
    ValidatedSearchResponse,
)
from opensquilla.tools.dispatch import build_tool_handler
from opensquilla.tools.registry import ToolRegistry
from opensquilla.tools.types import ToolContext, ToolError


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _document() -> dict[str, Any]:
    return {
        "id": "doc_1",
        "title": "NAND handbook",
        "source": "datasets",
        "fileName": "nand.md",
        "sourcePath": "datasets/nand.md",
        "mediaType": "text/markdown",
        "revision": "sha256:one",
        "uri": "knowledge://documents/doc_1",
        "openUrl": "/knowledge/files/doc_1",
    }


def _citation() -> dict[str, Any]:
    return {
        "title": "NAND handbook",
        "locator": "chunk 1",
        "uri": "knowledge://documents/doc_1#chunk=chunk_1",
    }


def _search_v11(
    *,
    content: str = "complete NAND chunk",
    snippet: str = "provider snippet",
) -> dict[str, Any]:
    return {
        "query": "NAND",
        "returnedCount": 1,
        "totalMatched": 7,
        "resultsTruncated": False,
        "retrieval": {
            "profile": "hybrid",
            "vectorScore": 0.99,
        },
        "results": [
            {
                "evidenceId": "ev_1",
                "rank": 1,
                "document": {
                    **_document(),
                    "internalScore": 0.88,
                },
                "chunk": {
                    "id": "chunk_1",
                    "content": content,
                    "contentChars": len(content),
                    "pairScore": 0.77,
                },
                "snippet": snippet,
                "snippetTruncated": False,
                "citation": {
                    **_citation(),
                    "fusionScore": 0.66,
                },
                "bm25Score": 12.0,
            }
        ],
    }


def _get_v11(*, content: str = "complete source window") -> dict[str, Any]:
    return {
        "evidenceId": "ev_1",
        "document": {
            **_document(),
            "vectorScore": 0.5,
        },
        "content": content,
        "contentChars": len(content),
        "previousCursor": None,
        "nextCursor": "next-page",
        "citation": {
            **_citation(),
            "pairScore": 0.4,
        },
        "providerBudgetViolation": False,
        "internalScore": 1.0,
    }


def _assert_source_isolated(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            folded = "".join(character for character in key.lower() if character.isalnum())
            assert folded not in {"chunk", "content"}
            assert "score" not in folded
            _assert_source_isolated(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_source_isolated(nested)


class Runtime:
    def __init__(
        self,
        *,
        search_payload: dict[str, Any] | None = None,
        get_payload: dict[str, Any] | None = None,
        provider_budget_violation: bool = False,
    ) -> None:
        self.search_payload = search_payload or {
            "returnedCount": 0,
            "totalMatched": None,
            "resultsTruncated": False,
            "results": [],
        }
        self.get_payload = get_payload or {
            "evidenceId": "ev_1",
            "content": "source",
        }
        self.provider_budget_violation = provider_budget_violation

    async def search(self, *, query: str, limit: int):
        assert query == "NAND"
        assert limit == 8
        return ValidatedSearchResponse(
            payload=self.search_payload,
            provider_budget_violation=self.provider_budget_violation,
        )

    async def get(self, *, evidence_id: str, cursor: str | None):
        assert evidence_id == "ev_1"
        assert cursor is None
        return self.get_payload


def _dispatch(runtime: Runtime):
    registry = ToolRegistry()
    for binding in rag_provider_tool_bindings(runtime).values():
        registry.register(binding.spec, binding.handler)
    return build_tool_handler(registry, ToolContext(run_mode="full"))


@pytest.mark.asyncio
async def test_tool_specs_are_minimal_external_network_tools() -> None:
    bindings = rag_provider_tool_bindings(Runtime())
    search = bindings["knowledge_search"]
    get = bindings["knowledge_get"]
    assert search.spec.name == "knowledge_search"
    assert search.spec.description == (
        "Search the configured external knowledge provider and return citable evidence."
    )
    assert search.spec.parameters == {
        "query": {"type": "string", "minLength": 1},
        "limit": {"type": "integer", "minimum": 1, "maximum": 20},
    }
    assert search.spec.required == ["query"]
    assert search.spec.model_result_projector is project_search_response_for_model
    assert search.spec.result_sources_projector is project_search_response_for_sources

    assert get.spec.name == "knowledge_get"
    assert get.spec.description == (
        "Read normalized source text around evidence returned by knowledge_search."
    )
    assert get.spec.parameters == {
        "evidence_id": {"type": "string", "minLength": 1},
        "cursor": {"type": "string", "minLength": 1},
    }
    assert get.spec.required == ["evidence_id"]
    assert get.spec.model_result_projector is project_get_response_for_model
    assert get.spec.result_sources_projector is project_get_response_for_sources

    for binding, kind, argument in (
        (search, "knowledge.search", {"query": "NAND", "limit": 8}),
        (get, "knowledge.get", {"evidence_id": "ev_1", "cursor": None}),
    ):
        assert binding.spec.result_budget_class == "external"
        assert binding.spec.sandbox.domain == "network"
        assert binding.spec.sandbox.kind == kind
        assert binding.spec.sandbox.enforce is True
        assert binding.spec.sandbox.record_payload is False
        assert binding.spec.sandbox.approval.required is False
        assert binding.spec.sandbox.argv_factory is not None
        assert binding.spec.sandbox.argv_factory(argument) == (
            kind,
            "NAND" if binding is search else "ev_1",
        )

    payload = json.loads(await search.handler(query="NAND", limit=8))
    assert payload["providerBudgetViolation"] is False


@pytest.mark.asyncio
async def test_handlers_return_complete_validated_payload_before_finalize() -> None:
    search_payload = _search_v11()
    get_payload = _get_v11()
    bindings = rag_provider_tool_bindings(
        Runtime(
            search_payload=search_payload,
            get_payload=get_payload,
            provider_budget_violation=True,
        )
    )

    search_result = await bindings["knowledge_search"].handler(query="NAND", limit=8)
    get_result = await bindings["knowledge_get"].handler(evidence_id="ev_1")

    assert search_result == _compact(
        {
            **search_payload,
            "providerBudgetViolation": True,
        }
    )
    assert json.loads(search_result)["results"][0]["chunk"]["id"] == "chunk_1"
    assert json.loads(search_result)["results"][0]["snippet"] == "provider snippet"
    assert get_result == _compact(get_payload)
    assert json.loads(get_result)["contentChars"] == len("complete source window")


@pytest.mark.asyncio
async def test_search_v11_dispatch_projects_complete_chunk_and_isolated_sources() -> None:
    source_snippet = "证" * (SOURCE_SNIPPET_MAX_CHARS + 1)
    raw = _search_v11(content="完整知识块", snippet=source_snippet)

    result = await _dispatch(Runtime(search_payload=raw))(
        ToolCall("tc-search-v11", "knowledge_search", {"query": "NAND"})
    )

    model = json.loads(result.content)
    assert model == {
        "returnedCount": 1,
        "resultsTruncated": False,
        "retrieval": {"profile": "hybrid"},
        "results": [
            {
                "evidenceId": "ev_1",
                "rank": 1,
                "document": {
                    "title": "NAND handbook",
                    "fileName": "nand.md",
                    "sourcePath": "datasets/nand.md",
                    "source": "datasets",
                },
                "chunk": {"content": "完整知识块"},
                "citation": _citation(),
            }
        ],
    }
    assert "snippet" not in model["results"][0]
    assert result.sources == [
        {
            "kind": "knowledge",
            "evidenceId": "ev_1",
            "rank": 1,
            "document": _document(),
            "citation": _citation(),
            "snippet": "证" * SOURCE_SNIPPET_MAX_CHARS,
            "snippetTruncated": True,
        }
    ]
    _assert_source_isolated(result.sources)


@pytest.mark.asyncio
async def test_search_v10_dispatch_retains_legacy_snippet() -> None:
    raw = {
        "returnedCount": 1,
        "totalMatched": None,
        "resultsTruncated": False,
        "results": [
            {
                "evidenceId": "legacy-ev",
                "snippet": "legacy evidence",
                "snippetTruncated": False,
                "citation": {
                    "title": "Legacy",
                    "source": "legacy-source",
                    "locator": "page 1",
                },
            }
        ],
    }

    result = await _dispatch(
        Runtime(search_payload=raw, provider_budget_violation=True)
    )(
        ToolCall("tc-search-v10", "knowledge_search", {"query": "NAND"})
    )

    assert json.loads(result.content) == {
        "returnedCount": 1,
        "resultsTruncated": False,
        "results": [
            {
                "evidenceId": "legacy-ev",
                "snippet": "legacy evidence",
                "snippetTruncated": False,
                "citation": {
                    "title": "Legacy",
                    "locator": "page 1",
                },
            }
        ],
    }
    assert "totalMatched" not in json.loads(result.content)
    assert "providerBudgetViolation" not in json.loads(result.content)
    assert json.loads(result.content)["results"][0]["snippet"] == "legacy evidence"
    assert result.sources == [
        {
            "kind": "knowledge",
            "evidenceId": "legacy-ev",
            "rank": 1,
            "citation": {"title": "Legacy", "locator": "page 1"},
            "snippet": "legacy evidence",
            "snippetTruncated": False,
        }
    ]
    _assert_source_isolated(result.sources)


@pytest.mark.asyncio
async def test_get_dispatch_projects_full_content_and_isolated_source() -> None:
    content = "🙂" * (SOURCE_SNIPPET_MAX_CHARS + 1)

    result = await _dispatch(Runtime(get_payload=_get_v11(content=content)))(
        ToolCall("tc-get-v11", "knowledge_get", {"evidence_id": "ev_1"})
    )

    model = json.loads(result.content)
    assert model["content"] == content
    assert model["document"] == {
        "title": "NAND handbook",
        "fileName": "nand.md",
        "sourcePath": "datasets/nand.md",
        "source": "datasets",
    }
    assert "contentChars" not in model
    assert result.sources == [
        {
            "kind": "knowledge",
            "evidenceId": "ev_1",
            "document": _document(),
            "citation": _citation(),
            "snippet": "🙂" * SOURCE_SNIPPET_MAX_CHARS,
            "snippetTruncated": True,
        }
    ]
    _assert_source_isolated(result.sources)


@pytest.mark.asyncio
async def test_get_dispatch_preserves_multiline_model_content_with_safe_source_preview() -> None:
    content = "# Heading\r\n\nParagraph one\twith detail.\n- item one\n- item two"

    result = await _dispatch(Runtime(get_payload=_get_v11(content=content)))(
        ToolCall("tc-get-v11-multiline", "knowledge_get", {"evidence_id": "ev_1"})
    )

    assert result.is_error is False
    assert json.loads(result.content)["content"] == content
    assert result.sources == [
        {
            "kind": "knowledge",
            "evidenceId": "ev_1",
            "document": _document(),
            "citation": _citation(),
            "snippet": "# Heading Paragraph one with detail. - item one - item two",
            "snippetTruncated": False,
        }
    ]
    _assert_source_isolated(result.sources)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "safe_code"),
    [
        (ProviderUnavailable("secret upstream body"), "knowledge_provider_unavailable"),
        (ProviderProtocolViolation("secret malformed body"), "provider_protocol_violation"),
        (ProviderNotFound("secret document path"), "provider_not_found"),
    ],
)
async def test_tool_errors_are_stable_and_do_not_leak_provider_details(
    error: Exception,
    safe_code: str,
) -> None:
    class FailingRuntime:
        async def search(self, **_: object):
            raise error

        async def get(self, **_: object):
            raise error

    bindings = rag_provider_tool_bindings(FailingRuntime())
    handler = (
        bindings["knowledge_get"].handler
        if isinstance(error, ProviderNotFound)
        else bindings["knowledge_search"].handler
    )
    arguments = (
        {"evidence_id": "ev_a"}
        if isinstance(error, ProviderNotFound)
        else {"query": "NAND"}
    )

    with pytest.raises(ToolError) as caught:
        await handler(**arguments)

    assert str(caught.value) == safe_code
    assert "secret" not in str(caught.value)
