from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from opensquilla.knowledge import http_backend as http_backend_module
from opensquilla.knowledge.backend import (
    DisabledKnowledgeBackend,
    KnowledgeBackendError,
)
from opensquilla.knowledge.http_backend import HttpKnowledgeBackend
from opensquilla.knowledge.manager import manager_from_config


def test_http_knowledge_backend_calls_standalone_api() -> None:
    requests: list[tuple[str, str, dict | None, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else None
        requests.append(
            (
                request.method,
                request.url.path,
                body,
                request.headers.get("authorization"),
            )
        )
        if request.url.path == "/v1/status":
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/v1/ingest":
            return httpx.Response(200, json={"ok": True, "collectionId": body["collectionId"]})
        if request.url.path == "/v1/search":
            return httpx.Response(200, json={"query": body["query"], "results": [], "count": 0})
        if request.url.path == "/v1/chunks/missing":
            return httpx.Response(404, json={"error": {"code": "not_found"}})
        if request.url.path == "/v1/settings" and request.method == "GET":
            return httpx.Response(200, json={"defaultRetrievalProfile": "sqlite_fts5_default"})
        if request.url.path == "/v1/settings" and request.method == "PATCH":
            return httpx.Response(
                200,
                json={
                    "configuredDefaultRetrievalProfile": body["defaultRetrievalProfile"],
                    "effectiveDefaultRetrievalProfile": body["defaultRetrievalProfile"],
                    "capabilitiesVersion": "0123456789abcdef",
                },
            )
        return httpx.Response(500, json={"error": {"message": "unexpected path"}})

    backend = HttpKnowledgeBackend(
        "http://knowledge.local",
        api_key="test-key",
        transport=httpx.MockTransport(handler),
    )

    assert backend.status()["ok"] is True
    ingest = backend.ingest_collection(source_root="/tmp/source", collection_id="research")
    assert ingest["collectionId"] == "research"
    assert (
        backend.search(
            "AI 光模块",
            top_k=3,
            filters={
                "collectionId": "datasets",
                "retrievalProfile": "hybrid_rrf_bge_m3_fts5",
                "embeddingModel": "baai/bge-m3",
                "embeddingDimensions": 1024,
            },
        )["query"]
        == "AI 光模块"
    )
    assert backend.get(chunk_id="missing") is None
    assert backend.settings() == {"defaultRetrievalProfile": "sqlite_fts5_default"}
    settings_payload = {"defaultRetrievalProfile": "hybrid_rrf_bge_m3_fts5"}
    assert backend.update_settings(settings_payload) == {
        "configuredDefaultRetrievalProfile": "hybrid_rrf_bge_m3_fts5",
        "effectiveDefaultRetrievalProfile": "hybrid_rrf_bge_m3_fts5",
        "capabilitiesVersion": "0123456789abcdef",
    }
    assert requests == [
        ("GET", "/v1/status", None, "Bearer test-key"),
        (
            "POST",
            "/v1/ingest",
            {
                "sourceRoot": "/tmp/source",
                "limit": 60,
                "collectionName": None,
                "collectionId": "research",
                "indexProfiles": None,
            },
            "Bearer test-key",
        ),
        (
            "POST",
            "/v1/search",
            {
                "query": "AI 光模块",
                "topK": 3,
                "filters": {
                    "collectionId": "datasets",
                    "retrievalProfile": "hybrid_rrf_bge_m3_fts5",
                    "embeddingModel": "baai/bge-m3",
                    "embeddingDimensions": 1024,
                },
            },
            "Bearer test-key",
        ),
        ("GET", "/v1/chunks/missing", None, "Bearer test-key"),
        ("GET", "/v1/settings", None, "Bearer test-key"),
        (
            "PATCH",
            "/v1/settings",
            {"defaultRetrievalProfile": "hybrid_rrf_bge_m3_fts5"},
            "Bearer test-key",
        ),
    ]


def test_manager_from_config_selects_disabled_backend() -> None:
    config = SimpleNamespace(knowledge=SimpleNamespace(enabled=False))

    assert isinstance(manager_from_config(config), DisabledKnowledgeBackend)


def test_disabled_knowledge_backend_rejects_settings_operations() -> None:
    backend = DisabledKnowledgeBackend()

    with pytest.raises(RuntimeError, match="^knowledge backend is disabled$"):
        backend.settings()
    with pytest.raises(RuntimeError, match="^knowledge backend is disabled$"):
        backend.update_settings({"defaultRetrievalProfile": "sqlite_fts5_default"})


@pytest.mark.parametrize(
    ("status_code", "code", "canonical_message"),
    [
        (400, "knowledge_error", "knowledge service request failed"),
        (400, "invalid_retrieval_profile", "invalid retrieval profile"),
        (409, "retrieval_profile_unavailable", "retrieval profile unavailable"),
        (503, "no_retrieval_profile_available", "no retrieval profile available"),
        (500, "settings_persist_failed", "failed to persist retrieval settings"),
        (403, "artifact_access_error", "knowledge artifact access failed"),
        (403, "source_file_access_error", "knowledge source file access failed"),
        (404, "not_found", "knowledge resource not found"),
    ],
)
def test_http_knowledge_backend_uses_canonical_structured_errors(
    status_code: int,
    code: str,
    canonical_message: str,
) -> None:
    upstream_message = (
        "response-body-secret Bearer test-api-key endpoint-password query-credential"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json={
                "error": {
                    "code": code,
                    "message": upstream_message,
                }
            },
            headers={"x-secret": "response-header-secret"},
        )

    backend = HttpKnowledgeBackend(
        "https://endpoint-user:endpoint-password@knowledge.local"
        "?credential=query-credential",
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(KnowledgeBackendError) as raised:
        backend.update_settings({"defaultRetrievalProfile": "missing_profile"})

    error = raised.value
    assert error.status_code == status_code
    assert error.code == code
    assert error.message == canonical_message
    rendered_error = f"{error!r} {error!s} {error.args!r} {error.code!r}"
    assert "secret" not in rendered_error
    assert not hasattr(error, "request")
    assert not hasattr(error, "response")


def test_knowledge_backend_error_fields_are_immutable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={
                "error": {
                    "code": "retrieval_profile_unavailable",
                    "message": "profile unavailable",
                }
            },
        )

    backend = HttpKnowledgeBackend(
        "http://knowledge.local",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(Exception) as raised:
        backend.settings()
    error = raised.value

    for field, replacement in (
        ("status_code", 500),
        ("code", "replacement"),
        ("message", "replacement"),
    ):
        with pytest.raises(AttributeError):
            setattr(error, field, replacement)


@pytest.mark.parametrize("error_body_kind", ["malformed", "non-object"])
def test_http_knowledge_backend_sanitizes_unstructured_error_responses(
    error_body_kind: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if error_body_kind == "malformed":
            return httpx.Response(
                502,
                content=b'{"error":"response-body-secret"',
                headers={"x-secret": "response-header-secret"},
            )
        return httpx.Response(
            502,
            json=["response-body-secret"],
            headers={"x-secret": "response-header-secret"},
        )

    backend = HttpKnowledgeBackend(
        "https://endpoint-user:endpoint-password@knowledge.local"
        "?credential=query-credential",
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(Exception) as raised:
        backend.settings()

    error = raised.value
    assert type(error) is http_backend_module.KnowledgeBackendError
    assert error.status_code == 502
    assert error.code is None
    assert error.message == "knowledge service request failed with status 502"
    rendered_error = f"{error!r} {error!s} {error.args!r}"
    for secret in (
        "response-body-secret",
        "response-header-secret",
        "endpoint-password",
        "query-credential",
        "test-api-key",
    ):
        assert secret not in rendered_error


def test_http_knowledge_backend_sanitizes_timeout_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(
            "timeout for endpoint-password query-credential test-api-key",
            request=request,
        )

    backend = HttpKnowledgeBackend(
        "https://endpoint-user:endpoint-password@knowledge.local"
        "?credential=query-credential",
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(Exception) as raised:
        backend.settings()

    error = raised.value
    assert type(error) is http_backend_module.KnowledgeBackendError
    assert error.status_code is None
    assert error.code == "knowledge_backend_unavailable"
    assert error.message == "knowledge service request failed"
    rendered_error = f"{error!r} {error!s} {error.args!r}"
    for secret in ("endpoint-password", "query-credential", "test-api-key"):
        assert secret not in rendered_error


@pytest.mark.parametrize(
    "raw_code",
    [
        None,
        "unknown-code-secret",
        ("x" * 500) + "overlong-code-secret",
    ],
)
def test_http_knowledge_backend_rejects_untrusted_structured_error_codes(
    raw_code: str | None,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        error_payload = {
            "message": "response-body-secret Bearer test-api-key",
        }
        if raw_code is not None:
            error_payload["code"] = raw_code
        return httpx.Response(
            409,
            json={"error": error_payload},
            headers={"x-secret": "response-header-secret"},
        )

    backend = HttpKnowledgeBackend(
        "https://endpoint-user:endpoint-password@knowledge.local"
        "?credential=query-credential",
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(KnowledgeBackendError) as raised:
        backend.settings()

    error = raised.value
    assert error.status_code == 409
    assert error.code is None
    assert error.message == "knowledge service request failed with status 409"
    rendered_error = f"{error!r} {error!s} {error.args!r} {error.code!r}"
    assert "secret" not in rendered_error
    assert not hasattr(error, "request")
    assert not hasattr(error, "response")


@pytest.mark.parametrize("payload_kind", ["malformed", "non-object"])
def test_http_knowledge_backend_sanitizes_invalid_success_payloads(
    payload_kind: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if payload_kind == "malformed":
            return httpx.Response(
                200,
                content=b'{"response-body-secret":',
                headers={"x-secret": "response-header-secret"},
            )
        return httpx.Response(
            200,
            json=["response-body-secret"],
            headers={"x-secret": "response-header-secret"},
        )

    backend = HttpKnowledgeBackend(
        "https://endpoint-user:endpoint-password@knowledge.local"
        "?credential=query-credential",
        api_key="test-api-key",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(KnowledgeBackendError) as raised:
        backend.settings()

    error = raised.value
    assert error.status_code == 200
    assert error.code is None
    assert error.message == "knowledge service returned invalid response"
    assert error.__context__ is None
    assert error.__cause__ is None
    assert not hasattr(error, "doc")
    assert not hasattr(error, "request")
    assert not hasattr(error, "response")
    rendered_error = f"{error!r} {error!s} {error.args!r} {error.code!r}"
    assert "secret" not in rendered_error
