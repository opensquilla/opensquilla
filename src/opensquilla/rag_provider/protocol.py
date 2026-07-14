from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

PROTOCOL_NAME = "opensquilla-rag-provider"
SUPPORTED_PROTOCOL_MAJOR = 1
LOCAL_MAX_SEARCH_RESULTS = 20
LOCAL_MAX_SNIPPET_CHARS = 800
LOCAL_MAX_SEARCH_RESPONSE_CHARS = 12_000
LOCAL_MAX_GET_CONTENT_CHARS = 8_000


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


@dataclass(frozen=True)
class EffectiveLimits:
    max_search_results: int
    max_snippet_chars: int
    max_search_response_chars: int
    max_get_content_chars: int


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
            self.limits.max_snippet_chars,
            self.limits.max_search_response_chars,
            self.limits.max_search_results,
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


def validate_capabilities(raw: Any) -> CapabilitiesSnapshot:
    payload = _dict(raw, "capabilities")
    protocol = _dict(payload.get("protocol"), "protocol")
    if protocol.get("name") != PROTOCOL_NAME:
        raise ProviderIncompatible("provider protocol name is incompatible")
    version = protocol.get("version")
    if not isinstance(version, str):
        raise ProviderProtocolViolation("provider protocol version is missing")
    try:
        major = int(version.split(".", 1)[0])
    except (TypeError, ValueError) as error:
        raise ProviderProtocolViolation("provider protocol version is invalid") from error
    if major != SUPPORTED_PROTOCOL_MAJOR:
        raise ProviderIncompatible("provider protocol major version is incompatible")
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
    effective = EffectiveLimits(
        min(
            _positive_int(limits.get("maxSearchResults"), "maxSearchResults"),
            LOCAL_MAX_SEARCH_RESULTS,
        ),
        min(
            _positive_int(limits.get("maxSnippetChars"), "maxSnippetChars"),
            LOCAL_MAX_SNIPPET_CHARS,
        ),
        min(
            _positive_int(limits.get("maxSearchResponseChars"), "maxSearchResponseChars"),
            LOCAL_MAX_SEARCH_RESPONSE_CHARS,
        ),
        min(
            _positive_int(limits.get("maxGetContentChars"), "maxGetContentChars"),
            LOCAL_MAX_GET_CONTENT_CHARS,
        ),
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
            if not isinstance(profile_id, str) or not isinstance(label, str):
                raise ProviderProtocolViolation("retrieval profile is invalid")
            profiles.append((profile_id, label))
        candidate = options.get("defaultRetrievalProfile")
        if candidate is not None and not isinstance(candidate, str):
            raise ProviderProtocolViolation("defaultRetrievalProfile is invalid")
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


def _validate_citation(value: Any) -> dict[str, str]:
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


def validate_search_response(raw: Any, *, budget: SearchBudget) -> ValidatedSearchResponse:
    payload = _dict(raw, "search response")
    results = payload.get("results")
    count = payload.get("returnedCount")
    if not isinstance(results, list):
        raise ProviderProtocolViolation("results must be an array")
    if isinstance(count, bool) or not isinstance(count, int) or count != len(results):
        raise ProviderProtocolViolation("returnedCount does not match results")
    total = payload.get("totalMatched")
    if total is not None and (
        isinstance(total, bool) or not isinstance(total, int) or total < 0
    ):
        raise ProviderProtocolViolation("totalMatched is invalid")
    if not isinstance(payload.get("resultsTruncated"), bool):
        raise ProviderProtocolViolation("resultsTruncated is invalid")
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
            "citation": _validate_citation(item.get("citation")),
        }
        proposed = {
            "returnedCount": len(normalized) + 1,
            "totalMatched": total,
            "resultsTruncated": payload["resultsTruncated"],
            "results": [*normalized, candidate],
        }
        if _compact_chars(proposed) > budget.max_total_chars:
            violation = True
            break
        normalized.append(candidate)
    truncated = payload["resultsTruncated"] or len(normalized) < len(results)
    normalized_payload = {
        "returnedCount": len(normalized),
        "totalMatched": total,
        "resultsTruncated": truncated,
        "results": normalized,
    }
    return ValidatedSearchResponse(normalized_payload, violation)


def validate_get_response(raw: Any, *, evidence_id: str, max_content_chars: int) -> dict[str, Any]:
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
    for key in ("previousCursor", "nextCursor"):
        value = payload.get(key)
        if value is not None and (not isinstance(value, str) or not value):
            raise ProviderProtocolViolation(f"{key} is invalid")
    return {
        "evidenceId": evidence_id,
        "document": {
            "title": document["title"],
            "source": document["source"],
        },
        "content": content,
        "previousCursor": payload.get("previousCursor"),
        "nextCursor": payload.get("nextCursor"),
        "citation": _validate_citation(payload.get("citation")),
    }
