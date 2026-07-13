from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal, overload

import httpx

from opensquilla.knowledge.backend import KnowledgeBackendError

_SAFE_ERROR_MESSAGES = {
    "knowledge_error": "knowledge service request failed",
    "invalid_retrieval_profile": "invalid retrieval profile",
    "retrieval_profile_unavailable": "retrieval profile unavailable",
    "no_retrieval_profile_available": "no retrieval profile available",
    "settings_persist_failed": "failed to persist retrieval settings",
    "artifact_access_error": "knowledge artifact access failed",
    "source_file_access_error": "knowledge source file access failed",
    "not_found": "knowledge resource not found",
}


def _payload_path(value: Path | str | None) -> str | None:
    return str(value) if value else None


class HttpKnowledgeBackend:
    """HTTP adapter for the standalone opensquilla-knowledge service."""

    def __init__(
        self,
        endpoint: str,
        *,
        api_key: str | None = None,
        api_key_env: str | None = None,
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        resolved_key = api_key or (os.environ.get(api_key_env) if api_key_env else None)
        self.headers = {"Accept": "application/json"}
        if resolved_key:
            self.headers["Authorization"] = f"Bearer {resolved_key}"
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def status(self) -> dict[str, Any]:
        return self._request("GET", "/v1/status")

    def collections(self) -> dict[str, Any]:
        return self._request("GET", "/v1/collections")

    def settings(self) -> dict[str, Any]:
        return self._request("GET", "/v1/settings")

    def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PATCH", "/v1/settings", json=payload)

    def prepare_sample(
        self,
        *,
        source_root: Path | str | None = None,
        limit: int = 60,
        collection_name: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/prepare-sample",
            json={
                "sourceRoot": _payload_path(source_root),
                "limit": limit,
                "collectionName": collection_name,
            },
        )

    def ingest_collection(
        self,
        *,
        source_root: Path | str | None = None,
        limit: int = 60,
        collection_name: str | None = None,
        collection_id: str | None = None,
        index_profiles: list[str] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/ingest",
            json={
                "sourceRoot": _payload_path(source_root),
                "limit": limit,
                "collectionName": collection_name,
                "collectionId": collection_id,
                "indexProfiles": index_profiles,
            },
        )

    def search(
        self,
        query: str,
        *,
        top_k: int = 8,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/search",
            json={"query": query, "topK": top_k, "filters": filters or {}},
        )

    def get(
        self,
        *,
        chunk_id: str | None = None,
        document_id: str | None = None,
    ) -> dict[str, Any] | None:
        if chunk_id:
            return self._request("GET", f"/v1/chunks/{chunk_id}", missing_ok=True)
        if document_id:
            return self._request(
                "GET",
                "/v1/item",
                params={"documentId": document_id},
                missing_ok=True,
            )
        raise ValueError("chunk_id or document_id is required")

    def questions(self) -> dict[str, Any]:
        return self._request("GET", "/v1/questions")

    def record_judgment(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/judgments", json=payload)

    @overload
    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        missing_ok: Literal[False] = False,
    ) -> dict[str, Any]: ...

    @overload
    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        missing_ok: Literal[True],
    ) -> dict[str, Any] | None: ...

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        missing_ok: bool = False,
    ) -> dict[str, Any] | None:
        try:
            with httpx.Client(
                base_url=self.endpoint,
                headers=self.headers,
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.request(method, path, json=json, params=params)
        except httpx.HTTPError:
            backend_error = KnowledgeBackendError(
                status_code=None,
                code="knowledge_backend_unavailable",
                message="knowledge service request failed",
            )
        else:
            if response.status_code == 404 and missing_ok:
                return None
            if response.status_code >= 400:
                raise _response_error(response)
            payload = _json_object(response)
            if payload is None:
                raise KnowledgeBackendError(
                    status_code=response.status_code,
                    code=None,
                    message="knowledge service returned invalid response",
                )
            return payload
        raise backend_error


def _response_error(response: httpx.Response) -> KnowledgeBackendError:
    status_code = response.status_code
    generic_error = KnowledgeBackendError(
        status_code=status_code,
        code=None,
        message=f"knowledge service request failed with status {status_code}",
    )
    payload = _json_object(response)
    if payload is None:
        return generic_error
    error = payload.get("error")
    if not isinstance(error, dict):
        return generic_error
    raw_code = error.get("code")
    if not isinstance(raw_code, str):
        return generic_error
    message = _SAFE_ERROR_MESSAGES.get(raw_code)
    if message is None:
        return generic_error
    return KnowledgeBackendError(
        status_code=status_code,
        code=raw_code,
        message=message,
    )


def _json_object(response: httpx.Response) -> dict[str, Any] | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None
