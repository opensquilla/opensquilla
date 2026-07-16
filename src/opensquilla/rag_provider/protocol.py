from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

PROTOCOL_NAME = "opensquilla-rag-provider"
SUPPORTED_PROTOCOL_MAJOR = 1
SUPPORTED_PROTOCOL_VERSIONS = frozenset({"1.0", "1.1"})
LOCAL_MAX_SEARCH_RESULTS = 20
LOCAL_MAX_SNIPPET_CHARS = 800
LOCAL_MAX_SEARCH_RESPONSE_CHARS = 12_000
LOCAL_MAX_GET_CONTENT_CHARS = 8_000
LOCAL_MAX_CHUNK_CHARS = 8_000

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_URI_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*$")
_UNSAFE_RESOURCE_SCHEMES = frozenset({"data", "file", "javascript", "vbscript"})


class ProviderProtocolViolation(ValueError):  # noqa: N818 - protocol contract name
    pass


class ProviderIncompatible(ProviderProtocolViolation):
    pass


class ProviderBudgetViolation(ProviderProtocolViolation):
    pass


class ProviderUnavailable(RuntimeError):  # noqa: N818 - protocol contract name
    pass


class ProviderAuthenticationError(ProviderUnavailable):
    pass


class ProviderNotFound(LookupError):  # noqa: N818 - protocol contract name
    pass


@dataclass(frozen=True)
class SearchBudget:
    max_snippet_chars: int
    max_total_chars: int
    max_results: int = LOCAL_MAX_SEARCH_RESULTS
    max_chunk_chars: int = LOCAL_MAX_CHUNK_CHARS


@dataclass(frozen=True)
class EffectiveLimits:
    max_search_results: int
    max_snippet_chars: int
    max_search_response_chars: int
    max_get_content_chars: int
    max_chunk_chars: int = LOCAL_MAX_CHUNK_CHARS


@dataclass(frozen=True)
class CapabilitiesSnapshot:
    protocol_version: str
    provider_name: str
    provider_version: str
    instance_id: str
    supports_get: bool
    limits: EffectiveLimits
    supports_collection_scope: bool
    retrieval_profiles: tuple[tuple[str, str], ...]
    default_retrieval_profile: str | None
    management_url: str | None

    @property
    def effective_search_budget(self) -> SearchBudget:
        return SearchBudget(
            max_snippet_chars=self.limits.max_snippet_chars,
            max_total_chars=self.limits.max_search_response_chars,
            max_results=self.limits.max_search_results,
            max_chunk_chars=self.limits.max_chunk_chars,
        )


@dataclass(frozen=True)
class ValidatedSearchResponse:
    payload: dict[str, Any]
    provider_budget_violation: bool


def _dict(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProviderProtocolViolation(f"{name} must be an object")
    return value


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProviderProtocolViolation(f"{name} must be a positive integer")
    return value


def _non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProviderProtocolViolation(f"{name} must be a non-negative integer")
    return value


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProviderProtocolViolation(f"{name} is required")
    result = value.strip()
    if _CONTROL_CHAR_RE.search(result):
        raise ProviderProtocolViolation(f"{name} is invalid")
    return result


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, name)


def _validate_protocol_version(version: Any) -> str:
    if not isinstance(version, str):
        raise ProviderProtocolViolation("provider protocol version is missing")
    if version not in SUPPORTED_PROTOCOL_VERSIONS:
        raise ProviderIncompatible("provider protocol version is incompatible")
    return version


def validate_capabilities(raw: Any) -> CapabilitiesSnapshot:
    payload = _dict(raw, "capabilities")
    protocol = _dict(payload.get("protocol"), "protocol")
    if protocol.get("name") != PROTOCOL_NAME:
        raise ProviderIncompatible("provider protocol name is incompatible")
    version = _validate_protocol_version(protocol.get("version"))
    provider = _dict(payload.get("provider"), "provider")
    for key in ("name", "version", "instanceId"):
        if not isinstance(provider.get(key), str) or not provider[key]:
            raise ProviderProtocolViolation(f"provider.{key} is required")
    capabilities = _dict(payload.get("capabilities"), "capabilities")
    if capabilities.get("search") is not True:
        raise ProviderProtocolViolation("provider search capability is required")
    if not isinstance(capabilities.get("get", False), bool):
        raise ProviderProtocolViolation("provider get capability is invalid")
    limits = _dict(payload.get("limits"), "limits")
    raw_chunk_limit = limits.get("maxChunkChars")
    if version == "1.1" or raw_chunk_limit is not None:
        max_chunk_chars = min(
            _positive_int(raw_chunk_limit, "maxChunkChars"),
            LOCAL_MAX_CHUNK_CHARS,
        )
    else:
        max_chunk_chars = LOCAL_MAX_CHUNK_CHARS
    effective = EffectiveLimits(
        max_search_results=min(
            _positive_int(limits.get("maxSearchResults"), "maxSearchResults"),
            LOCAL_MAX_SEARCH_RESULTS,
        ),
        max_snippet_chars=min(
            _positive_int(limits.get("maxSnippetChars"), "maxSnippetChars"),
            LOCAL_MAX_SNIPPET_CHARS,
        ),
        max_search_response_chars=min(
            _positive_int(limits.get("maxSearchResponseChars"), "maxSearchResponseChars"),
            LOCAL_MAX_SEARCH_RESPONSE_CHARS,
        ),
        max_get_content_chars=min(
            _positive_int(limits.get("maxGetContentChars"), "maxGetContentChars"),
            LOCAL_MAX_GET_CONTENT_CHARS,
        ),
        max_chunk_chars=max_chunk_chars,
    )
    options = payload.get("searchOptions")
    supports_scope = False
    profiles: list[tuple[str, str]] = []
    default_profile = None
    if options is not None:
        options = _dict(options, "searchOptions")
        raw_supports_scope = options.get("supportsCollectionScope", False)
        if not isinstance(raw_supports_scope, bool):
            raise ProviderProtocolViolation("supportsCollectionScope is invalid")
        supports_scope = raw_supports_scope
        raw_profiles = options.get("retrievalProfiles", [])
        if not isinstance(raw_profiles, list):
            raise ProviderProtocolViolation("retrievalProfiles must be an array")
        for item in raw_profiles:
            item = _dict(item, "retrievalProfile")
            profile_id = item.get("id")
            label = item.get("label")
            if (
                not isinstance(profile_id, str)
                or not profile_id.strip()
                or not isinstance(label, str)
                or not label.strip()
            ):
                raise ProviderProtocolViolation("retrieval profile is invalid")
            profiles.append((profile_id, label))
        candidate = options.get("defaultRetrievalProfile")
        if candidate is not None and not isinstance(candidate, str):
            raise ProviderProtocolViolation("defaultRetrievalProfile is invalid")
        advertised_profile_ids = {profile_id for profile_id, _ in profiles}
        if candidate is not None and candidate not in advertised_profile_ids:
            if version == "1.0":
                candidate = None
            else:
                raise ProviderProtocolViolation(
                    "defaultRetrievalProfile is not advertised"
                )
        default_profile = candidate
    links = payload.get("links")
    management = None
    if links is not None:
        links = _dict(links, "links")
        candidate = links.get("management")
        if candidate is not None and not isinstance(candidate, str):
            raise ProviderProtocolViolation("management link is invalid")
        management = candidate
    return CapabilitiesSnapshot(
        protocol_version=version,
        provider_name=provider["name"],
        provider_version=provider["version"],
        instance_id=provider["instanceId"],
        supports_get=capabilities.get("get", False),
        limits=effective,
        supports_collection_scope=supports_scope,
        retrieval_profiles=tuple(profiles),
        default_retrieval_profile=default_profile,
        management_url=management,
    )


def _compact_chars(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def _validate_source_path(value: Any) -> str:
    path = _required_text(value, "document.sourcePath")
    if (
        path.startswith(("/", "\\"))
        or "\\" in path
        or any(part in {"", ".", ".."} for part in path.split("/"))
        or re.match(r"^[A-Za-z]:", path)
    ):
        raise ProviderProtocolViolation("document.sourcePath is invalid")
    return path


def _safe_urlsplit(value: str, name: str) -> Any:
    try:
        return urlsplit(value)
    except ValueError as error:
        raise ProviderProtocolViolation(f"{name} is invalid") from error


def _validate_open_url(value: Any) -> str:
    url = _required_text(value, "document.openUrl")
    if "\\" in url or any(character.isspace() for character in url):
        raise ProviderProtocolViolation("document.openUrl is invalid")
    parsed = _safe_urlsplit(url, "document.openUrl")
    if url.startswith("/") and not url.startswith("//"):
        if parsed.scheme or parsed.netloc:
            raise ProviderProtocolViolation("document.openUrl is invalid")
        return url
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ProviderProtocolViolation("document.openUrl is invalid")
    if parsed.username is not None or parsed.password is not None:
        raise ProviderProtocolViolation("document.openUrl is invalid")
    return url


def _validate_resource_uri(value: Any, name: str) -> str:
    uri = _required_text(value, name)
    if "\\" in uri or any(character.isspace() for character in uri):
        raise ProviderProtocolViolation(f"{name} is invalid")
    parsed = _safe_urlsplit(uri, name)
    scheme = parsed.scheme.lower()
    if (
        not scheme
        or not _URI_SCHEME_RE.fullmatch(parsed.scheme)
        or scheme in _UNSAFE_RESOURCE_SCHEMES
        or (not parsed.netloc and not parsed.path)
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ProviderProtocolViolation(f"{name} is invalid")
    return uri


def _validate_citation_uri(value: Any, *, document_uri: str | None) -> str:
    uri = _validate_resource_uri(value, "citation.uri")
    parsed = _safe_urlsplit(uri, "citation.uri")
    if not parsed.query and not parsed.fragment:
        raise ProviderProtocolViolation("citation.uri must locate evidence")
    if document_uri is not None and uri == document_uri:
        raise ProviderProtocolViolation("citation.uri must locate evidence")
    return uri


def _validate_document(value: Any) -> dict[str, str]:
    document = _dict(value, "document")
    result = {
        "id": _required_text(document.get("id"), "document.id"),
        "title": _required_text(document.get("title"), "document.title"),
    }
    for key in ("source", "fileName", "mediaType", "revision"):
        candidate = _optional_text(document.get(key), f"document.{key}")
        if candidate is not None:
            result[key] = candidate
    source_path = document.get("sourcePath")
    if source_path is not None:
        result["sourcePath"] = _validate_source_path(source_path)
    uri = document.get("uri")
    if uri is not None:
        result["uri"] = _validate_resource_uri(uri, "document.uri")
    open_url = document.get("openUrl")
    if open_url is not None:
        result["openUrl"] = _validate_open_url(open_url)
    return result


def _validate_citation_v1_0(value: Any) -> dict[str, str]:
    citation = _dict(value, "citation")
    title = citation.get("title")
    if not isinstance(title, str) or not title:
        raise ProviderProtocolViolation("citation.title is required")
    result = {"title": title}
    for key in ("source", "locator", "uri"):
        candidate = citation.get(key)
        if candidate is not None:
            if not isinstance(candidate, str):
                raise ProviderProtocolViolation(f"citation.{key} is invalid")
            result[key] = candidate
    return result


def _validate_citation_v1_1(
    value: Any,
    *,
    document_uri: str | None,
) -> dict[str, str]:
    citation = _dict(value, "citation")
    result = {
        "title": _required_text(citation.get("title"), "citation.title"),
        "locator": _required_text(citation.get("locator"), "citation.locator"),
        "uri": _validate_citation_uri(
            citation.get("uri"),
            document_uri=document_uri,
        ),
    }
    source = _optional_text(citation.get("source"), "citation.source")
    if source is not None:
        result["source"] = source
    return result


def _validate_search_envelope(
    raw: Any,
) -> tuple[dict[str, Any], list[Any], bool, int | None, bool]:
    payload = _dict(raw, "search response")
    results = payload.get("results")
    count = payload.get("returnedCount")
    if not isinstance(results, list):
        raise ProviderProtocolViolation("results must be an array")
    if isinstance(count, bool) or not isinstance(count, int) or count != len(results):
        raise ProviderProtocolViolation("returnedCount does not match results")
    total_present = "totalMatched" in payload
    total = payload.get("totalMatched")
    if total is not None:
        total = _non_negative_int(total, "totalMatched")
    truncated = payload.get("resultsTruncated")
    if not isinstance(truncated, bool):
        raise ProviderProtocolViolation("resultsTruncated is invalid")
    return payload, results, total_present, total, truncated


def _validate_search_response_v1_0(
    raw: Any,
    *,
    budget: SearchBudget,
) -> ValidatedSearchResponse:
    payload, results, _total_present, total, provider_truncated = (
        _validate_search_envelope(raw)
    )
    normalized: list[dict[str, Any]] = []
    violation = False
    if len(results) > budget.max_results:
        violation = True
    for value in results[: budget.max_results]:
        item = _dict(value, "result")
        evidence_id = item.get("evidenceId")
        snippet = item.get("snippet")
        snippet_truncated = item.get("snippetTruncated")
        if not isinstance(evidence_id, str) or not evidence_id:
            raise ProviderProtocolViolation("evidenceId is required")
        if not isinstance(snippet, str) or not isinstance(snippet_truncated, bool):
            raise ProviderProtocolViolation("result snippet is invalid")
        if len(snippet) > budget.max_snippet_chars:
            snippet = snippet[: budget.max_snippet_chars]
            snippet_truncated = True
            violation = True
        candidate = {
            "evidenceId": evidence_id,
            "snippet": snippet,
            "snippetTruncated": snippet_truncated,
            "citation": _validate_citation_v1_0(item.get("citation")),
        }
        proposed = {
            "returnedCount": len(normalized) + 1,
            "totalMatched": total,
            "resultsTruncated": provider_truncated,
            "results": [*normalized, candidate],
        }
        if _compact_chars(proposed) > budget.max_total_chars:
            violation = True
            break
        normalized.append(candidate)
    truncated = provider_truncated or len(normalized) < len(results)
    normalized_payload = {
        "returnedCount": len(normalized),
        "totalMatched": total,
        "resultsTruncated": truncated,
        "results": normalized,
    }
    return ValidatedSearchResponse(normalized_payload, violation)


def _validate_search_result_v1_1(
    value: Any,
    *,
    expected_rank: int,
    budget: SearchBudget,
) -> tuple[dict[str, Any], bool]:
    item = _dict(value, "result")
    rank = item.get("rank")
    if (
        isinstance(rank, bool)
        or not isinstance(rank, int)
        or rank != expected_rank
    ):
        raise ProviderProtocolViolation("result rank is invalid")
    evidence_id = _required_text(item.get("evidenceId"), "evidenceId")
    document = _validate_document(item.get("document"))
    chunk = _dict(item.get("chunk"), "chunk")
    chunk_id = _required_text(chunk.get("id"), "chunk.id")
    content = chunk.get("content")
    if not isinstance(content, str):
        raise ProviderProtocolViolation("chunk.content is invalid")
    content_chars = _non_negative_int(chunk.get("contentChars"), "chunk.contentChars")
    if content_chars != len(content):
        raise ProviderProtocolViolation("chunk.contentChars does not match content")
    snippet = item.get("snippet")
    snippet_truncated = item.get("snippetTruncated")
    if not isinstance(snippet, str) or not isinstance(snippet_truncated, bool):
        raise ProviderProtocolViolation("result snippet is invalid")
    snippet_violation = len(snippet) > budget.max_snippet_chars
    if snippet_violation:
        snippet = snippet[: budget.max_snippet_chars]
        snippet_truncated = True
    document_uri = document.get("uri")
    candidate = {
        "evidenceId": evidence_id,
        "rank": rank,
        "document": document,
        "chunk": {
            "id": chunk_id,
            "content": content,
            "contentChars": content_chars,
        },
        "snippet": snippet,
        "snippetTruncated": snippet_truncated,
        "citation": _validate_citation_v1_1(
            item.get("citation"),
            document_uri=document_uri,
        ),
    }
    return candidate, snippet_violation


def _search_payload_v1_1(
    *,
    query: str,
    total_present: bool,
    total: int | None,
    results_truncated: bool,
    profile: str | None,
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query": query,
        "returnedCount": len(results),
    }
    if total_present:
        payload["totalMatched"] = total
    payload.update(
        {
            "resultsTruncated": results_truncated,
            "retrieval": {"profile": profile},
            "results": results,
        }
    )
    return payload


def _validate_search_response_v1_1(
    raw: Any,
    *,
    budget: SearchBudget,
) -> ValidatedSearchResponse:
    payload, results, total_present, total, provider_truncated = (
        _validate_search_envelope(raw)
    )
    query = _required_text(payload.get("query"), "query")
    retrieval = _dict(payload.get("retrieval"), "retrieval")
    raw_profile = retrieval.get("profile")
    if raw_profile is None:
        profile = None
    else:
        profile = _required_text(raw_profile, "retrieval.profile")

    candidates: list[dict[str, Any]] = []
    violation = False
    for index, value in enumerate(results, start=1):
        candidate, snippet_violation = _validate_search_result_v1_1(
            value,
            expected_rank=index,
            budget=budget,
        )
        candidates.append(candidate)
        violation = violation or snippet_violation

    normalized: list[dict[str, Any]] = []
    for candidate in candidates:
        if len(normalized) >= budget.max_results:
            violation = True
            break
        if candidate["chunk"]["contentChars"] > budget.max_chunk_chars:
            violation = True
            continue
        candidate = dict(candidate)
        candidate["rank"] = len(normalized) + 1
        proposed_results = [*normalized, candidate]
        proposed = _search_payload_v1_1(
            query=query,
            total_present=total_present,
            total=total,
            results_truncated=provider_truncated,
            profile=profile,
            results=proposed_results,
        )
        if _compact_chars(proposed) > budget.max_total_chars:
            violation = True
            break
        normalized.append(candidate)

    truncated = provider_truncated or len(normalized) < len(results)
    normalized_payload = _search_payload_v1_1(
        query=query,
        total_present=total_present,
        total=total,
        results_truncated=truncated,
        profile=profile,
        results=normalized,
    )
    if _compact_chars(normalized_payload) > budget.max_total_chars:
        violation = True
    return ValidatedSearchResponse(normalized_payload, violation)


def validate_search_response(
    raw: Any,
    *,
    budget: SearchBudget,
    protocol_version: str = "1.0",
) -> ValidatedSearchResponse:
    version = _validate_protocol_version(protocol_version)
    if version == "1.0":
        return _validate_search_response_v1_0(raw, budget=budget)
    return _validate_search_response_v1_1(raw, budget=budget)


def _validate_cursors(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    values: list[str | None] = []
    for key in ("previousCursor", "nextCursor"):
        value = payload.get(key)
        if value is not None and (not isinstance(value, str) or not value):
            raise ProviderProtocolViolation(f"{key} is invalid")
        values.append(value)
    return values[0], values[1]


def _validate_get_response_v1_0(
    raw: Any,
    *,
    evidence_id: str,
    max_content_chars: int,
) -> dict[str, Any]:
    payload = _dict(raw, "get response")
    if payload.get("evidenceId") != evidence_id:
        raise ProviderProtocolViolation("get evidenceId does not match request")
    content = payload.get("content")
    if not isinstance(content, str):
        raise ProviderProtocolViolation("get content is invalid")
    if len(content) > max_content_chars:
        raise ProviderBudgetViolation("get content exceeds requested budget")
    document = _dict(payload.get("document"), "document")
    if not isinstance(document.get("title"), str):
        raise ProviderProtocolViolation("document.title is required")
    if not isinstance(document.get("source"), str):
        raise ProviderProtocolViolation("document.source is required")
    previous_cursor, next_cursor = _validate_cursors(payload)
    return {
        "evidenceId": evidence_id,
        "document": {
            "title": document["title"],
            "source": document["source"],
        },
        "content": content,
        "previousCursor": previous_cursor,
        "nextCursor": next_cursor,
        "citation": _validate_citation_v1_0(payload.get("citation")),
    }


def _validate_get_response_v1_1(
    raw: Any,
    *,
    evidence_id: str,
    max_content_chars: int,
) -> dict[str, Any]:
    payload = _dict(raw, "get response")
    if payload.get("evidenceId") != evidence_id:
        raise ProviderProtocolViolation("get evidenceId does not match request")
    document = _validate_document(payload.get("document"))
    content = payload.get("content")
    if not isinstance(content, str):
        raise ProviderProtocolViolation("get content is invalid")
    content_chars = _non_negative_int(payload.get("contentChars"), "contentChars")
    if content_chars != len(content):
        raise ProviderProtocolViolation("contentChars does not match content")
    if content_chars > max_content_chars:
        raise ProviderBudgetViolation("get content exceeds requested budget")
    previous_cursor, next_cursor = _validate_cursors(payload)
    return {
        "evidenceId": evidence_id,
        "document": document,
        "content": content,
        "contentChars": content_chars,
        "previousCursor": previous_cursor,
        "nextCursor": next_cursor,
        "citation": _validate_citation_v1_1(
            payload.get("citation"),
            document_uri=document.get("uri"),
        ),
    }


def validate_get_response(
    raw: Any,
    *,
    evidence_id: str,
    max_content_chars: int,
    protocol_version: str = "1.0",
) -> dict[str, Any]:
    version = _validate_protocol_version(protocol_version)
    if version == "1.0":
        return _validate_get_response_v1_0(
            raw,
            evidence_id=evidence_id,
            max_content_chars=max_content_chars,
        )
    return _validate_get_response_v1_1(
        raw,
        evidence_id=evidence_id,
        max_content_chars=max_content_chars,
    )
