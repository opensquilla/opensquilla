from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlsplit

import httpx

from opensquilla.rag_provider.protocol import (
    CapabilitiesSnapshot,
    ProviderAuthenticationError,
    ProviderNotFound,
    ProviderProtocolViolation,
    ProviderUnavailable,
    SearchBudget,
    ValidatedSearchResponse,
    validate_capabilities,
    validate_get_response,
    validate_search_response,
)

MAX_RESPONSE_BYTES = 64 * 1024


class RagProviderClient:
    def __init__(
        self,
        *,
        base_url: str,
        token_env: str | None,
        connect_timeout_seconds: float,
        request_timeout_seconds: float,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("provider_base_url must be an HTTP URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("provider_base_url cannot contain credentials, query, or fragment")
        self.base_url = base_url.rstrip("/")
        self.token_env = token_env
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(
                request_timeout_seconds,
                connect=connect_timeout_seconds,
            )
        )

    def _headers(self) -> dict[str, str]:
        headers = {"accept": "application/json"}
        if self.token_env:
            token = os.environ.get(self.token_env)
            if token:
                headers["authorization"] = f"Bearer {token}"
        return headers

    async def _json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        try:
            async with self._http.stream(
                method,
                f"{self.base_url}{path}",
                headers=self._headers(),
                json=payload,
            ) as response:
                if response.status_code in {401, 403}:
                    raise ProviderAuthenticationError("provider authentication failed")
                if response.status_code == 404:
                    raise ProviderNotFound("provider item was not found")
                if response.status_code == 429 or response.status_code >= 500:
                    raise ProviderUnavailable("provider is temporarily unavailable")
                if response.status_code >= 400:
                    raise ProviderProtocolViolation("provider rejected the request")
                content_type = response.headers.get("content-type", "")
                if "application/json" not in content_type.lower():
                    raise ProviderProtocolViolation("provider response is not JSON")
                content_length = response.headers.get("content-length")
                if content_length:
                    try:
                        declared_length = int(content_length)
                    except ValueError as error:
                        raise ProviderProtocolViolation(
                            "provider response Content-Length is invalid"
                        ) from error
                    if declared_length < 0:
                        raise ProviderProtocolViolation(
                            "provider response Content-Length is invalid"
                        )
                    if declared_length > MAX_RESPONSE_BYTES:
                        raise ProviderProtocolViolation(
                            "provider response body exceeds limit"
                        )
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise ProviderProtocolViolation("provider response body exceeds limit")
                    chunks.append(chunk)
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise ProviderUnavailable("provider is temporarily unavailable") from error
        try:
            return json.loads(b"".join(chunks))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ProviderProtocolViolation("provider response is invalid JSON") from error

    async def capabilities(self) -> CapabilitiesSnapshot:
        return validate_capabilities(await self._json("GET", "/v1/capabilities"))

    async def search(
        self,
        *,
        query: str,
        limit: int,
        budget: SearchBudget,
        collection_ids: tuple[str, ...] = (),
        retrieval_profile: str | None = None,
    ) -> ValidatedSearchResponse:
        body: dict[str, Any] = {
            "query": query,
            "limit": limit,
            "budget": {
                "maxSnippetChars": budget.max_snippet_chars,
                "maxTotalChars": budget.max_total_chars,
            },
        }
        if collection_ids:
            body["scope"] = {"collectionIds": list(collection_ids)}
        if retrieval_profile:
            body["retrievalProfile"] = retrieval_profile
        return validate_search_response(
            await self._json("POST", "/v1/search", body), budget=budget
        )

    async def get(
        self,
        *,
        evidence_id: str,
        cursor: str | None,
        max_content_chars: int,
    ) -> dict[str, Any]:
        body = {
            "evidenceId": evidence_id,
            "cursor": cursor,
            "budget": {"maxContentChars": max_content_chars},
        }
        return validate_get_response(
            await self._json("POST", "/v1/get", body),
            evidence_id=evidence_id,
            max_content_chars=max_content_chars,
        )

    async def close(self) -> None:
        if self._owns_http:
            await self._http.aclose()
