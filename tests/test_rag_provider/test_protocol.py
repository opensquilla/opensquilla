from __future__ import annotations

import json

import pytest

from opensquilla.rag_provider import protocol as rag_protocol
from opensquilla.rag_provider.protocol import (
    ProviderBudgetViolation,
    ProviderIncompatible,
    ProviderProtocolViolation,
    SearchBudget,
    validate_capabilities,
    validate_get_response,
    validate_search_response,
)


def capabilities(*, version: str = "1.0", get: bool = True) -> dict:
    payload = {
        "protocol": {"name": "opensquilla-rag-provider", "version": version},
        "provider": {"name": "Test", "version": "1", "instanceId": "test"},
        "capabilities": {"search": True, "get": get},
        "limits": {
            "maxSearchResults": 20,
            "maxSnippetChars": 800,
            "maxSearchResponseChars": 12000,
            "maxGetContentChars": 8000,
        },
    }
    if version == "1.1":
        payload["limits"]["maxChunkChars"] = 8000
    return payload


def result(index: int, *, snippet: str = "evidence") -> dict:
    return {
        "evidenceId": f"ev_{index}",
        "snippet": snippet,
        "snippetTruncated": False,
        "citation": {"title": f"Doc {index}", "locator": "page 1"},
    }


def result_v11(index: int, *, content: str = "complete evidence") -> dict:
    document_uri = f"knowledge://documents/doc_{index}"
    return {
        "evidenceId": f"ev_{index}",
        "rank": index,
        "document": {
            "id": f"doc_{index}",
            "title": f"Doc {index}",
            "source": "datasets",
            "fileName": f"doc-{index}.md",
            "sourcePath": f"datasets/doc-{index}.md",
            "mediaType": "text/markdown",
            "revision": f"sha256:{index}",
            "uri": document_uri,
            "openUrl": f"/knowledge/files/sf_{index}?chunkId=chunk_{index}",
            "providerPrivate": "drop-me",
        },
        "chunk": {
            "id": f"chunk_{index}",
            "content": content,
            "contentChars": len(content),
            "providerPrivate": "drop-me",
        },
        "snippet": "evidence",
        "snippetTruncated": False,
        "citation": {
            "title": f"Doc {index}",
            "locator": "page 1",
            "uri": f"{document_uri}#chunk=chunk_{index}",
            "providerPrivate": "drop-me",
        },
        "providerPrivate": "drop-me",
    }


def search_v11(results: list[dict]) -> dict:
    return {
        "query": "NAND capacity",
        "returnedCount": len(results),
        "totalMatched": 20,
        "resultsTruncated": False,
        "retrieval": {"profile": "hybrid", "providerPrivate": "drop-me"},
        "results": results,
        "providerBudgetViolation": False,
        "providerPrivate": "drop-me",
    }


def test_capabilities_accept_only_exact_supported_versions() -> None:
    assert rag_protocol.SUPPORTED_PROTOCOL_VERSIONS == frozenset({"1.0", "1.1"})
    snapshot = validate_capabilities(capabilities(version="1.1"))
    assert snapshot.protocol_version == "1.1"
    assert snapshot.supports_get is True
    for version in ("1", "1.x", "1.2", "2.0", "latest", "1.1.0"):
        with pytest.raises(ProviderIncompatible):
            validate_capabilities(capabilities(version=version))


def test_capabilities_negotiate_chunk_limit_by_version() -> None:
    payload = capabilities(version="1.1")
    payload["limits"]["maxChunkChars"] = 12_000
    snapshot = validate_capabilities(payload)
    assert snapshot.limits.max_chunk_chars == rag_protocol.LOCAL_MAX_CHUNK_CHARS
    assert (
        snapshot.effective_search_budget.max_chunk_chars
        == rag_protocol.LOCAL_MAX_CHUNK_CHARS
    )

    missing = capabilities(version="1.1")
    del missing["limits"]["maxChunkChars"]
    with pytest.raises(ProviderProtocolViolation):
        validate_capabilities(missing)

    compatible = validate_capabilities(capabilities(version="1.0"))
    assert compatible.limits.max_chunk_chars == rag_protocol.LOCAL_MAX_CHUNK_CHARS


@pytest.mark.parametrize("value", [True, 0, -1, "8000"])
def test_capabilities_reject_invalid_v11_chunk_limit(value: object) -> None:
    payload = capabilities(version="1.1")
    payload["limits"]["maxChunkChars"] = value

    with pytest.raises(ProviderProtocolViolation):
        validate_capabilities(payload)


def test_capabilities_validate_default_profile_with_1_0_compatibility() -> None:
    valid = capabilities(version="1.1")
    valid["searchOptions"] = {
        "retrievalProfiles": [{"id": "hybrid", "label": "Hybrid"}],
        "defaultRetrievalProfile": "hybrid",
    }
    assert validate_capabilities(valid).default_retrieval_profile == "hybrid"

    invalid = capabilities(version="1.1")
    invalid["searchOptions"] = {
        "retrievalProfiles": [{"id": "hybrid", "label": "Hybrid"}],
        "defaultRetrievalProfile": "historical-missing-profile",
    }
    with pytest.raises(ProviderProtocolViolation):
        validate_capabilities(invalid)

    legacy = capabilities(version="1.0")
    legacy["searchOptions"] = invalid["searchOptions"]
    assert validate_capabilities(legacy).default_retrieval_profile is None


def test_capabilities_rejects_non_boolean_scope_support_and_boolean_limits() -> None:
    invalid_scope = capabilities()
    invalid_scope["searchOptions"] = {"supportsCollectionScope": "yes"}
    with pytest.raises(ProviderProtocolViolation):
        validate_capabilities(invalid_scope)

    invalid_limit = capabilities()
    invalid_limit["limits"]["maxSearchResults"] = True
    with pytest.raises(ProviderProtocolViolation):
        validate_capabilities(invalid_limit)


def test_effective_search_budget_includes_provider_result_limit() -> None:
    payload = capabilities()
    payload["limits"]["maxSearchResults"] = 5

    snapshot = validate_capabilities(payload)

    assert snapshot.effective_search_budget.max_results == 5


def test_search_rejects_count_mismatch() -> None:
    with pytest.raises(ProviderProtocolViolation):
        validate_search_response(
            {
                "returnedCount": 20,
                "totalMatched": 20,
                "resultsTruncated": True,
                "results": [result(1)],
            },
            budget=SearchBudget(800, 12_000),
        )


def test_valid_oversized_search_is_structurally_salvaged() -> None:
    validated = validate_search_response(
        {
            "returnedCount": 3,
            "totalMatched": None,
            "resultsTruncated": False,
            "results": [result(i, snippet="证据" * 500) for i in range(3)],
        },
        budget=SearchBudget(120, 700),
    )
    assert validated.provider_budget_violation is True
    assert validated.payload["returnedCount"] == len(validated.payload["results"])
    assert validated.payload["resultsTruncated"] is True
    assert all(len(item["snippet"]) <= 120 for item in validated.payload["results"])


def test_search_never_delivers_more_results_than_the_effective_request_limit() -> None:
    validated = validate_search_response(
        {
            "returnedCount": 3,
            "totalMatched": 3,
            "resultsTruncated": False,
            "results": [result(index) for index in range(3)],
        },
        budget=SearchBudget(800, 12_000, max_results=2),
    )

    assert validated.payload["returnedCount"] == 2
    assert validated.payload["resultsTruncated"] is True
    assert validated.provider_budget_violation is True


def test_search_v11_normalizes_full_response_and_filters_private_fields() -> None:
    payload = search_v11([result_v11(1)])

    validated = validate_search_response(
        payload,
        protocol_version="1.1",
        budget=SearchBudget(800, 12_000, max_chunk_chars=8_000),
    )

    assert validated.provider_budget_violation is False
    assert validated.payload == {
        "query": "NAND capacity",
        "returnedCount": 1,
        "totalMatched": 20,
        "resultsTruncated": False,
        "retrieval": {"profile": "hybrid"},
        "results": [
            {
                "evidenceId": "ev_1",
                "rank": 1,
                "document": {
                    "id": "doc_1",
                    "title": "Doc 1",
                    "source": "datasets",
                    "fileName": "doc-1.md",
                    "sourcePath": "datasets/doc-1.md",
                    "mediaType": "text/markdown",
                    "revision": "sha256:1",
                    "uri": "knowledge://documents/doc_1",
                    "openUrl": "/knowledge/files/sf_1?chunkId=chunk_1",
                },
                "chunk": {
                    "id": "chunk_1",
                    "content": "complete evidence",
                    "contentChars": 17,
                },
                "snippet": "evidence",
                "snippetTruncated": False,
                "citation": {
                    "title": "Doc 1",
                    "locator": "page 1",
                    "uri": "knowledge://documents/doc_1#chunk=chunk_1",
                },
            }
        ],
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sourcePath", "/etc/passwd"),
        ("sourcePath", "a/../../secret"),
        ("sourcePath", "C:\\secret"),
        ("sourcePath", "safe/\x85secret"),
        ("openUrl", "//evil.example/path"),
        ("openUrl", "javascript:alert(1)"),
        ("openUrl", "http://[broken"),
        ("uri", "/knowledge/files/doc_1"),
        ("uri", "knowledge://[broken"),
    ],
)
def test_search_v11_rejects_unsafe_document_locations(field: str, value: str) -> None:
    payload = search_v11([result_v11(1)])
    payload["results"][0]["document"][field] = value

    with pytest.raises(ProviderProtocolViolation):
        validate_search_response(
            payload,
            protocol_version="1.1",
            budget=SearchBudget(800, 12_000, max_chunk_chars=8_000),
        )


def test_search_v11_rejects_invalid_rank_content_count_and_citation_uri() -> None:
    for mutation in ("rank", "contentChars", "citationUri"):
        payload = search_v11([result_v11(1)])
        if mutation == "rank":
            payload["results"][0]["rank"] = 2
        elif mutation == "contentChars":
            payload["results"][0]["chunk"]["contentChars"] += 1
        else:
            payload["results"][0]["citation"]["uri"] = "knowledge://documents/doc_1"
        with pytest.raises(ProviderProtocolViolation):
            validate_search_response(
                payload,
                protocol_version="1.1",
                budget=SearchBudget(800, 12_000, max_chunk_chars=8_000),
            )


def test_search_v11_skips_oversized_chunk_and_regenerates_ranks() -> None:
    payload = search_v11(
        [
            result_v11(1, content="too long"),
            result_v11(2, content="ok"),
            result_v11(3, content="later"),
        ]
    )

    validated = validate_search_response(
        payload,
        protocol_version="1.1",
        budget=SearchBudget(800, 12_000, max_chunk_chars=5),
    )

    assert validated.provider_budget_violation is True
    assert [item["evidenceId"] for item in validated.payload["results"]] == [
        "ev_2",
        "ev_3",
    ]
    assert [item["rank"] for item in validated.payload["results"]] == [1, 2]
    assert [item["chunk"]["content"] for item in validated.payload["results"]] == [
        "ok",
        "later",
    ]
    assert validated.payload["resultsTruncated"] is True


def test_search_v11_total_budget_removes_current_and_all_later_results() -> None:
    first = result_v11(1, content="first")
    expected = search_v11([first])
    expected["resultsTruncated"] = True
    expected.pop("providerBudgetViolation")
    expected.pop("providerPrivate")
    expected["retrieval"].pop("providerPrivate")
    for value in expected["results"]:
        value.pop("providerPrivate")
        value["document"].pop("providerPrivate")
        value["chunk"].pop("providerPrivate")
        value["citation"].pop("providerPrivate")
    maximum = len(json.dumps(expected, ensure_ascii=False, separators=(",", ":"))) + 1

    validated = validate_search_response(
        search_v11(
            [
                first,
                result_v11(2, content="second"),
                result_v11(3, content="third"),
            ]
        ),
        protocol_version="1.1",
        budget=SearchBudget(800, maximum, max_chunk_chars=8_000),
    )

    assert [item["evidenceId"] for item in validated.payload["results"]] == ["ev_1"]
    assert validated.payload["resultsTruncated"] is True
    assert validated.provider_budget_violation is True


def test_search_v11_bounds_snippet_without_slicing_chunk_content() -> None:
    item = result_v11(1, content="完整知识块")
    item["snippet"] = "摘录" * 20
    payload = search_v11([item])

    validated = validate_search_response(
        payload,
        protocol_version="1.1",
        budget=SearchBudget(7, 12_000, max_chunk_chars=8_000),
    )

    assert validated.payload["results"][0]["snippet"] == ("摘录" * 20)[:7]
    assert validated.payload["results"][0]["snippetTruncated"] is True
    assert validated.payload["results"][0]["chunk"]["content"] == "完整知识块"
    assert validated.provider_budget_violation is True


def test_search_v11_allows_omitted_total_matched() -> None:
    payload = search_v11([result_v11(1)])
    del payload["totalMatched"]

    validated = validate_search_response(
        payload,
        protocol_version="1.1",
        budget=SearchBudget(800, 12_000, max_chunk_chars=8_000),
    )

    assert "totalMatched" not in validated.payload


def test_get_rejects_oversized_content_instead_of_creating_a_paging_gap() -> None:
    response = {
        "evidenceId": "ev_1",
        "document": {"title": "Document", "source": "datasets"},
        "content": "x" * 101,
        "previousCursor": None,
        "nextCursor": "next",
        "citation": {"title": "Document"},
    }

    with pytest.raises(ProviderBudgetViolation):
        validate_get_response(response, evidence_id="ev_1", max_content_chars=100)


def test_get_v11_validates_full_document_content_chars_and_citation() -> None:
    response = {
        "evidenceId": "ev_1",
        "document": result_v11(1)["document"],
        "content": "完整窗口",
        "contentChars": 4,
        "previousCursor": None,
        "nextCursor": "next",
        "citation": result_v11(1)["citation"],
        "providerPrivate": "drop-me",
    }

    validated = validate_get_response(
        response,
        protocol_version="1.1",
        evidence_id="ev_1",
        max_content_chars=100,
    )

    assert validated["contentChars"] == len(validated["content"])
    assert validated["document"]["id"] == "doc_1"
    assert "providerPrivate" not in validated
    assert "providerPrivate" not in validated["document"]

    response["contentChars"] = 5
    with pytest.raises(ProviderProtocolViolation):
        validate_get_response(
            response,
            protocol_version="1.1",
            evidence_id="ev_1",
            max_content_chars=100,
        )
