from __future__ import annotations

import pytest

from opensquilla.rag_provider.protocol import (
    ProviderBudgetViolation,
    ProviderProtocolViolation,
    SearchBudget,
    validate_capabilities,
    validate_get_response,
    validate_search_response,
)


def capabilities(*, version: str = "1.0", get: bool = True) -> dict:
    return {
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


def result(index: int, *, snippet: str = "evidence") -> dict:
    return {
        "evidenceId": f"ev_{index}",
        "snippet": snippet,
        "snippetTruncated": False,
        "citation": {"title": f"Doc {index}", "locator": "page 1"},
    }


def test_capabilities_accept_same_major_and_reject_other_major() -> None:
    snapshot = validate_capabilities(capabilities(version="1.1"))
    assert snapshot.protocol_version == "1.1"
    assert snapshot.supports_get is True
    with pytest.raises(ProviderProtocolViolation):
        validate_capabilities(capabilities(version="2.0"))


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
