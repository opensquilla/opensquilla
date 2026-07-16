from __future__ import annotations

import json
from typing import Any

SOURCE_SNIPPET_MAX_CHARS = 400
_SOURCE_RESULT_MAX_ITEMS = 12

_MODEL_DOCUMENT_KEYS = ("title", "fileName", "sourcePath", "source")
_SOURCE_DOCUMENT_KEYS = (
    "id",
    "title",
    "source",
    "fileName",
    "sourcePath",
    "mediaType",
    "revision",
    "uri",
    "openUrl",
)
_CITATION_KEYS = ("title", "locator", "uri")


def _compact(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _select(payload: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: payload[key] for key in keys if key in payload}


def _model_document(document: dict[str, Any]) -> dict[str, Any]:
    return _select(document, _MODEL_DOCUMENT_KEYS)


def _source_document(document: dict[str, Any]) -> dict[str, Any]:
    return _select(document, _SOURCE_DOCUMENT_KEYS)


def _citation(citation: dict[str, Any]) -> dict[str, Any]:
    return _select(citation, _CITATION_KEYS)


def _project_search_result_for_model(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "evidenceId": item["evidenceId"],
        "rank": item["rank"],
        "document": _model_document(item["document"]),
        "chunk": {"content": item["chunk"]["content"]},
        "citation": _citation(item["citation"]),
    }


def _project_search_result_for_model_v10(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "evidenceId": item["evidenceId"],
        "snippet": item["snippet"],
        "snippetTruncated": item["snippetTruncated"],
        "citation": _citation(item["citation"]),
    }


def project_search_response_for_model(raw_json: str) -> str:
    payload: dict[str, Any] = json.loads(raw_json)
    if "retrieval" not in payload:
        return _compact(
            {
                "returnedCount": payload["returnedCount"],
                "resultsTruncated": payload["resultsTruncated"],
                "results": [
                    _project_search_result_for_model_v10(item)
                    for item in payload["results"]
                ],
            }
        )

    projected = {
        "returnedCount": payload["returnedCount"],
        "resultsTruncated": payload["resultsTruncated"],
        "retrieval": {"profile": payload["retrieval"]["profile"]},
        "results": [
            _project_search_result_for_model(item) for item in payload["results"]
        ],
    }
    return _compact(projected)


def _project_search_result_for_sources(
    item: dict[str, Any],
    *,
    rank: int,
    is_v11: bool,
) -> dict[str, Any]:
    snippet = item["snippet"]
    projected: dict[str, Any] = {
        "kind": "knowledge",
        "evidenceId": item["evidenceId"],
        "rank": item["rank"] if is_v11 else rank,
    }
    if is_v11:
        projected["document"] = _source_document(item["document"])
    projected.update(
        {
            "citation": _citation(item["citation"]),
            "snippet": snippet[:SOURCE_SNIPPET_MAX_CHARS],
            "snippetTruncated": (
                item["snippetTruncated"]
                or len(snippet) > SOURCE_SNIPPET_MAX_CHARS
            ),
        }
    )
    return projected


def project_search_response_for_sources(raw_json: str) -> list[dict[str, Any]]:
    payload: dict[str, Any] = json.loads(raw_json)
    is_v11 = "retrieval" in payload
    return [
        _project_search_result_for_sources(
            item,
            rank=rank,
            is_v11=is_v11,
        )
        for rank, item in enumerate(
            payload["results"][:_SOURCE_RESULT_MAX_ITEMS],
            start=1,
        )
    ]


def _project_get_response_for_model_v11(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "evidenceId": payload["evidenceId"],
        "document": _model_document(payload["document"]),
        "content": payload["content"],
        "previousCursor": payload["previousCursor"],
        "nextCursor": payload["nextCursor"],
        "citation": _citation(payload["citation"]),
    }


def project_get_response_for_model(raw_json: str) -> str:
    payload: dict[str, Any] = json.loads(raw_json)
    if "contentChars" not in payload:
        return _compact(payload)
    return _compact(_project_get_response_for_model_v11(payload))


def project_get_response_for_sources(raw_json: str) -> list[dict[str, Any]]:
    payload: dict[str, Any] = json.loads(raw_json)
    content = payload["content"]
    normalized_content = " ".join(content.split())
    projected = {
        "kind": "knowledge",
        "evidenceId": payload["evidenceId"],
        "document": _source_document(payload["document"]),
        "citation": _citation(payload["citation"]),
        "snippet": normalized_content[:SOURCE_SNIPPET_MAX_CHARS],
        "snippetTruncated": len(normalized_content) > SOURCE_SNIPPET_MAX_CHARS,
    }
    return [projected]
