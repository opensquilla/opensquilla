from __future__ import annotations

import json
from typing import Any


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _projectors():
    from opensquilla.rag_provider import projections

    return projections


def _document(index: int = 1) -> dict[str, Any]:
    return {
        "id": f"doc_{index}",
        "title": f"文档 {index}",
        "source": "datasets",
        "fileName": f"doc-{index}.md",
        "sourcePath": f"datasets/doc-{index}.md",
        "mediaType": "text/markdown",
        "revision": f"sha256:{index}",
        "uri": f"knowledge://documents/doc_{index}",
        "openUrl": f"/knowledge/files/sf_{index}",
    }


def _citation(index: int = 1) -> dict[str, Any]:
    return {
        "title": f"文档 {index}",
        "locator": f"chunk {index}",
        "uri": f"knowledge://documents/doc_{index}#chunk=chunk_{index}",
    }


def _result_v11(
    index: int = 1,
    *,
    content: str = "完整知识块",
    snippet: str = "提供者摘录",
) -> dict[str, Any]:
    return {
        "evidenceId": f"ev_{index}",
        "rank": index,
        "document": _document(index),
        "chunk": {
            "id": f"chunk_{index}",
            "content": content,
            "contentChars": len(content),
        },
        "snippet": snippet,
        "snippetTruncated": False,
        "citation": _citation(index),
    }


def _search_v11(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "query": "NAND capacity",
        "returnedCount": len(results),
        "totalMatched": 99,
        "resultsTruncated": False,
        "retrieval": {
            "profile": "opaque-provider-profile",
            "bm25Score": 8.2,
            "vectorDiagnostics": {"score": 0.91},
        },
        "results": results,
        "providerBudgetViolation": False,
    }


def _get_v11(*, content: str = "完整窗口") -> dict[str, Any]:
    return {
        "evidenceId": "ev_1",
        "document": _document(),
        "content": content,
        "contentChars": len(content),
        "previousCursor": None,
        "nextCursor": "next-page",
        "citation": _citation(),
        "providerBudgetViolation": False,
    }


def _assert_sidecar_is_isolated(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            folded = "".join(character for character in key.lower() if character.isalnum())
            assert folded not in {"chunk", "content"}
            assert "score" not in folded
            assert not any(
                diagnostic in folded
                for diagnostic in ("bm25", "vector", "rrf", "fusion", "pair")
            )
            _assert_sidecar_is_isolated(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_sidecar_is_isolated(nested)


def test_search_v11_model_projection_is_an_exact_compact_allowlist() -> None:
    projections = _projectors()
    item = _result_v11()
    item["document"]["internalScore"] = 0.9
    item["chunk"]["pairId"] = "private-pair"
    item["citation"]["source"] = "duplicate-source"
    item["rrfScore"] = 0.7
    raw_json = _compact(_search_v11([item]))

    projected = projections.project_search_response_for_model(raw_json)

    expected = {
        "returnedCount": 1,
        "resultsTruncated": False,
        "retrieval": {"profile": "opaque-provider-profile"},
        "results": [
            {
                "evidenceId": "ev_1",
                "rank": 1,
                "document": {
                    "title": "文档 1",
                    "fileName": "doc-1.md",
                    "sourcePath": "datasets/doc-1.md",
                    "source": "datasets",
                },
                "chunk": {"content": "完整知识块"},
                "citation": _citation(),
            }
        ],
    }
    assert projected == _compact(expected)
    assert "完整知识块" in projected
    assert "\\u5b8c" not in projected


def test_empty_search_discriminates_version_from_top_level_retrieval() -> None:
    projections = _projectors()
    v11 = _search_v11([])
    v10 = {
        "returnedCount": 0,
        "totalMatched": 0,
        "resultsTruncated": False,
        "results": [],
    }

    projected_v11 = json.loads(
        projections.project_search_response_for_model(_compact(v11))
    )
    projected_v10 = json.loads(
        projections.project_search_response_for_model(_compact(v10))
    )

    assert projected_v11 == {
        "returnedCount": 0,
        "resultsTruncated": False,
        "retrieval": {"profile": "opaque-provider-profile"},
        "results": [],
    }
    assert projected_v10 == v10
    assert projections.project_search_response_for_sources(_compact(v11)) == []
    assert projections.project_search_response_for_sources(_compact(v10)) == []


def test_search_v10_keeps_snippet_evidence_without_fabricating_v11_fields() -> None:
    projections = _projectors()
    raw = {
        "returnedCount": 1,
        "totalMatched": None,
        "resultsTruncated": True,
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
        "providerBudgetViolation": True,
    }

    projected = json.loads(
        projections.project_search_response_for_model(_compact(raw))
    )

    assert projected == raw
    assert "document" not in projected["results"][0]
    assert "chunk" not in projected["results"][0]


def test_search_v10_sources_assign_rank_without_fabricating_document() -> None:
    projections = _projectors()
    raw = {
        "returnedCount": 1,
        "totalMatched": 1,
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

    sources = projections.project_search_response_for_sources(_compact(raw))

    assert sources == [
        {
            "kind": "knowledge",
            "evidenceId": "legacy-ev",
            "rank": 1,
            "citation": {"title": "Legacy", "locator": "page 1"},
            "snippet": "legacy evidence",
            "snippetTruncated": False,
        }
    ]
    _assert_sidecar_is_isolated(sources)


def test_search_sources_bound_unicode_snippet_and_remove_diagnostics_recursively() -> None:
    projections = _projectors()
    item = _result_v11(snippet="证" * 401)
    item["snippetTruncated"] = False
    item["document"]["nested"] = {
        "content": "must not escape",
        "internalScore": 1.0,
    }
    item["citation"]["fusionDiagnostics"] = {"vectorScore": 0.8}
    item["bm25Score"] = 5.0

    sources = projections.project_search_response_for_sources(
        _compact(_search_v11([item]))
    )

    assert sources == [
        {
            "kind": "knowledge",
            "evidenceId": "ev_1",
            "rank": 1,
            "document": _document(),
            "citation": _citation(),
            "snippet": "证" * 400,
            "snippetTruncated": True,
        }
    ]
    assert len(sources[0]["snippet"]) == projections.SOURCE_SNIPPET_MAX_CHARS == 400
    _assert_sidecar_is_isolated(sources)


def test_search_sources_are_locally_capped_at_twelve() -> None:
    projections = _projectors()
    results = [_result_v11(index) for index in range(1, 14)]

    sources = projections.project_search_response_for_sources(
        _compact(_search_v11(results))
    )

    assert len(sources) == 12
    assert [source["evidenceId"] for source in sources] == [
        f"ev_{index}" for index in range(1, 13)
    ]


def test_get_v11_model_projection_keeps_complete_content_and_model_metadata() -> None:
    projections = _projectors()
    raw = _get_v11(content="完整内容" * 120)
    raw["document"]["vectorScore"] = 0.4
    raw["citation"]["pairId"] = "private"

    projected = projections.project_get_response_for_model(_compact(raw))

    assert projected == _compact(
        {
            "evidenceId": "ev_1",
            "document": {
                "title": "文档 1",
                "fileName": "doc-1.md",
                "sourcePath": "datasets/doc-1.md",
                "source": "datasets",
            },
            "content": "完整内容" * 120,
            "previousCursor": None,
            "nextCursor": "next-page",
            "citation": _citation(),
        }
    )


def test_get_sources_derive_unicode_snippet_without_full_content_or_scores() -> None:
    projections = _projectors()
    raw = _get_v11(content="🙂" * 401)
    raw["internalScore"] = 1.0
    raw["document"]["rrfDiagnostics"] = {"score": 0.5}
    raw["citation"]["content"] = "must not escape"

    sources = projections.project_get_response_for_sources(_compact(raw))

    assert sources == [
        {
            "kind": "knowledge",
            "evidenceId": "ev_1",
            "document": _document(),
            "citation": _citation(),
            "snippet": "🙂" * 400,
            "snippetTruncated": True,
        }
    ]
    assert len(sources[0]["snippet"]) == 400
    _assert_sidecar_is_isolated(sources)


def test_get_v10_uses_legacy_metadata_without_fabricating_v11_fields() -> None:
    projections = _projectors()
    raw = {
        "evidenceId": "legacy-ev",
        "document": {"title": "Legacy", "source": "legacy-source"},
        "content": "legacy content",
        "previousCursor": None,
        "nextCursor": None,
        "citation": {
            "title": "Legacy",
            "source": "legacy-source",
            "locator": "page 1",
        },
    }

    model = json.loads(projections.project_get_response_for_model(_compact(raw)))
    sources = projections.project_get_response_for_sources(_compact(raw))

    assert model == raw
    assert sources == [
        {
            "kind": "knowledge",
            "evidenceId": "legacy-ev",
            "document": {"title": "Legacy", "source": "legacy-source"},
            "citation": {
                "title": "Legacy",
                "locator": "page 1",
            },
            "snippet": "legacy content",
            "snippetTruncated": False,
        }
    ]
    _assert_sidecar_is_isolated(sources)
