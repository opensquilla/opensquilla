from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request

from opensquilla.gateway.app import create_gateway_app
from opensquilla.gateway.config import GatewayConfig
from opensquilla.gateway.knowledge_management import (
    KnowledgeManagementProxy,
    register_knowledge_management_routes,
)
from opensquilla.gateway.middleware import AuthMiddleware

UPLOAD_ID = "upload-01"
JOB_ID = "job-01"


def _config() -> GatewayConfig:
    return GatewayConfig.model_validate(
        {
            "knowledge": {
                "enabled": True,
                "provider_base_url": ("https://knowledge.internal.example/opensquilla-rag"),
                "authentication_token_env": "KNOWLEDGE_SERVICE_TOKEN",
            }
        }
    )


def _upload_payload(**updates: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "uploadId": UPLOAD_ID,
        "filename": "handbook.pdf",
        "sizeBytes": 1024,
        "uploadedBytes": 0,
        "indexTypes": ["fts", "vector"],
        "chunkSizeBytes": 16 * 1024 * 1024,
        "serverExtension": {"kept": True},
    }
    payload.update(updates)
    return payload


def _job_payload(**updates: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "jobId": JOB_ID,
        "uploadId": UPLOAD_ID,
        "state": "running",
        "phase": "vector_indexing",
        "overallProgress": 72.5,
        "upload": {
            "uploadedBytes": 1024,
            "sizeBytes": 1024,
            "percent": 100,
            "extra": "kept",
        },
        "files": {
            "total": 3,
            "processed": 2,
            "skipped": 0,
            "failed": 0,
        },
        "chunks": {
            "total": 10,
            "ftsIndexed": 10,
            "vectorIndexed": 4,
        },
        "warnings": ["one file has no extractable text"],
        "error": None,
        "serverExtension": {"kept": True},
    }
    payload.update(updates)
    return payload


def _json_response(
    payload: dict[str, Any],
    *,
    status_code: int,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload,
        headers=headers,
    )


class _StreamingMockTransport(httpx.AsyncBaseTransport):
    """Test transport that preserves the request iterator's chunking."""

    def __init__(self, handler: Any) -> None:
        self._handler = handler

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self._handler(request)


async def _browser_client(
    app: Starlette,
) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_provider_protocol_path_is_not_reused_for_management_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KNOWLEDGE_SERVICE_TOKEN", "service-secret")
    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("authorization")
        seen["body"] = json.loads((await request.aread()).decode())
        return _json_response(
            _upload_payload(),
            status_code=201,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        app = Starlette()
        register_knowledge_management_routes(
            app,
            config=_config(),
            http_client=upstream,
        )
        async for client in _browser_client(app):
            response = await client.post(
                "/api/v1/knowledge/uploads",
                headers={"authorization": "Bearer browser-gateway-token"},
                json={
                    "filename": "handbook.pdf",
                    "sizeBytes": 1024,
                    "indexTypes": ["fts", "vector"],
                },
            )

    assert response.status_code == 201
    assert response.json()["serverExtension"] == {"kept": True}
    assert seen == {
        "method": "POST",
        "url": ("https://knowledge.internal.example/v1/management/uploads"),
        "authorization": "Bearer service-secret",
        "body": {
            "filename": "handbook.pdf",
            "sizeBytes": 1024,
            "indexTypes": ["fts", "vector"],
        },
    }


@pytest.mark.asyncio
async def test_stats_route_returns_only_validated_file_and_chunk_totals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KNOWLEDGE_SERVICE_TOKEN", "service-secret")
    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("authorization")
        return _json_response(
            {
                "ok": True,
                "filesIndexed": 21_622,
                "chunksIndexed": 224_066,
                "rootDir": "/private/provider/path",
            },
            status_code=200,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        app = Starlette()
        register_knowledge_management_routes(
            app,
            config=_config(),
            http_client=upstream,
        )
        async for client in _browser_client(app):
            response = await client.get("/api/v1/knowledge/stats")

    assert response.status_code == 200
    assert response.json() == {
        "filesIndexed": 21_622,
        "chunksIndexed": 224_066,
    }
    assert seen == {
        "method": "GET",
        "url": "https://knowledge.internal.example/v1/status",
        "authorization": "Bearer service-secret",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"chunksIndexed": 1},
        {"filesIndexed": 1},
        {"filesIndexed": -1, "chunksIndexed": 1},
        {"filesIndexed": True, "chunksIndexed": 1},
    ],
)
async def test_stats_route_rejects_invalid_upstream_counters(
    payload: dict[str, Any],
) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return _json_response(payload, status_code=200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        app = Starlette()
        register_knowledge_management_routes(
            app,
            config=_config(),
            http_client=upstream,
        )
        async for client in _browser_client(app):
            response = await client.get("/api/v1/knowledge/stats")

    assert response.status_code == 502
    assert response.json()["code"] == "KNOWLEDGE_UPSTREAM_INVALID_RESPONSE"


@pytest.mark.asyncio
async def test_get_complete_and_job_routes_validate_minimum_and_keep_extras() -> None:
    seen: list[tuple[str, str, bytes]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        seen.append((request.method, request.url.path, body))
        if request.url.path.endswith(f"/uploads/{UPLOAD_ID}"):
            return _json_response(
                _upload_payload(uploadedBytes=512),
                status_code=200,
            )
        if request.url.path.endswith(f"/uploads/{UPLOAD_ID}/complete"):
            return _json_response(
                {
                    "uploadId": UPLOAD_ID,
                    "jobId": JOB_ID,
                    "state": "queued",
                    "serverExtension": True,
                },
                status_code=202,
            )
        if request.url.path.endswith(f"/jobs/{JOB_ID}"):
            return _json_response(
                _job_payload(),
                status_code=200,
            )
        raise AssertionError(request.url)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        app = Starlette()
        register_knowledge_management_routes(
            app,
            config=_config(),
            http_client=upstream,
        )
        async for client in _browser_client(app):
            upload = await client.get(f"/api/v1/knowledge/uploads/{UPLOAD_ID}")
            complete = await client.post(f"/api/v1/knowledge/uploads/{UPLOAD_ID}/complete")
            job = await client.get(f"/api/v1/knowledge/jobs/{JOB_ID}")

    assert upload.status_code == 200
    assert upload.json()["uploadedBytes"] == 512
    assert upload.json()["serverExtension"] == {"kept": True}
    assert complete.status_code == 202
    assert complete.json()["serverExtension"] is True
    assert job.status_code == 200
    assert job.json()["serverExtension"] == {"kept": True}
    assert seen == [
        (
            "GET",
            f"/v1/management/uploads/{UPLOAD_ID}",
            b"",
        ),
        (
            "POST",
            f"/v1/management/uploads/{UPLOAD_ID}/complete",
            b"",
        ),
        (
            "GET",
            f"/v1/management/jobs/{JOB_ID}",
            b"",
        ),
    ]


@pytest.mark.asyncio
async def test_patch_is_incrementally_streamed_without_request_body_buffering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunks = [bytes([index]) * (64 * 1024) for index in range(1, 5)]
    events: list[tuple[str, int]] = []

    async def forbidden_body(_request: Request) -> bytes:
        raise AssertionError("PATCH must not call Request.body()")

    monkeypatch.setattr(Request, "body", forbidden_body)

    messages = [
        {
            "type": "http.request",
            "body": chunk,
            "more_body": index < len(chunks) - 1,
        }
        for index, chunk in enumerate(chunks)
    ]
    next_message = 0

    async def receive() -> dict[str, Any]:
        nonlocal next_message
        message = messages[next_message]
        events.append(("produced", next_message))
        next_message += 1
        return message

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert request.headers["content-length"] == str(sum(map(len, chunks)))
        assert request.headers["upload-offset"] == "128"
        assert request.headers["content-type"] == "application/octet-stream"
        received: list[bytes] = []
        async for chunk in request.stream:
            index = len(received)
            events.append(("consumed", index))
            received.append(chunk)
        assert received == chunks
        return _json_response(
            _upload_payload(
                uploadedBytes=128 + sum(map(len, chunks)),
                sizeBytes=1024 * 1024,
            ),
            status_code=200,
            headers={"Upload-Offset": str(128 + sum(map(len, chunks)))},
        )

    async with httpx.AsyncClient(transport=_StreamingMockTransport(handler)) as upstream:
        proxy = KnowledgeManagementProxy(
            _config(),
            http_client=upstream,
        )
        path = f"/api/v1/knowledge/uploads/{UPLOAD_ID}"
        request = Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "PATCH",
                "scheme": "http",
                "path": path,
                "raw_path": path.encode(),
                "query_string": b"",
                "headers": [
                    (b"host", b"gateway.test"),
                    (b"content-type", b"application/octet-stream"),
                    (
                        b"content-length",
                        str(sum(map(len, chunks))).encode(),
                    ),
                    (b"upload-offset", b"128"),
                ],
                "client": ("127.0.0.1", 1234),
                "server": ("gateway.test", 80),
                "path_params": {"upload_id": UPLOAD_ID},
            },
            receive,
        )
        response = await proxy.patch_upload(request)

    assert response.status_code == 200
    assert response.headers["upload-offset"] == str(128 + sum(map(len, chunks)))
    assert events == [
        ("produced", 0),
        ("consumed", 0),
        ("produced", 1),
        ("consumed", 1),
        ("produced", 2),
        ("consumed", 2),
        ("produced", 3),
        ("consumed", 3),
    ]


@pytest.mark.asyncio
async def test_create_metadata_is_strictly_validated_before_upstream() -> None:
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("invalid metadata must not reach upstream")

    invalid_payloads = [
        {
            "filename": "ok.pdf",
            "sizeBytes": 1,
            "indexTypes": ["hybrid"],
        },
        {
            "filename": "ok.pdf",
            "sizeBytes": 1,
            "indexTypes": ["vector", "fts"],
        },
        {
            "filename": "../escape.pdf",
            "sizeBytes": 1,
            "indexTypes": ["fts"],
        },
        {
            "filename": "ok.pdf",
            "sizeBytes": True,
            "indexTypes": ["fts"],
        },
        {
            "filename": "ok.pdf",
            "sizeBytes": 1,
            "indexTypes": ["fts"],
            "collectionId": "customer_shared",
        },
    ]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        app = Starlette()
        register_knowledge_management_routes(
            app,
            config=_config(),
            http_client=upstream,
        )
        async for client in _browser_client(app):
            for payload in invalid_payloads:
                response = await client.post(
                    "/api/v1/knowledge/uploads",
                    json=payload,
                )
                assert response.status_code == 400

    assert calls == 0


@pytest.mark.asyncio
async def test_patch_rejects_invalid_headers_before_upstream() -> None:
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("invalid headers must not reach upstream")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        app = Starlette()
        register_knowledge_management_routes(
            app,
            config=_config(),
            http_client=upstream,
        )
        async for client in _browser_client(app):
            missing_offset = await client.patch(
                f"/api/v1/knowledge/uploads/{UPLOAD_ID}",
                headers={"content-type": "application/octet-stream"},
                content=b"abc",
            )
            noncanonical_length = await client.patch(
                f"/api/v1/knowledge/uploads/{UPLOAD_ID}",
                headers={
                    "content-type": "application/octet-stream",
                    "content-length": "03",
                    "upload-offset": "0",
                },
                content=b"abc",
            )
            wrong_type = await client.patch(
                f"/api/v1/knowledge/uploads/{UPLOAD_ID}",
                headers={
                    "content-type": "text/plain",
                    "upload-offset": "0",
                },
                content=b"abc",
            )

    assert missing_offset.status_code == 400
    assert noncanonical_length.status_code == 400
    assert wrong_type.status_code == 415
    assert calls == 0


@pytest.mark.asyncio
async def test_patch_detects_short_body_against_content_length() -> None:
    async def source() -> AsyncIterator[bytes]:
        yield b"abc"

    async def handler(request: httpx.Request) -> httpx.Response:
        async for _chunk in request.stream:
            pass
        raise AssertionError("length mismatch must abort upstream request")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        app = Starlette()
        register_knowledge_management_routes(
            app,
            config=_config(),
            http_client=upstream,
        )
        async for client in _browser_client(app):
            response = await client.patch(
                f"/api/v1/knowledge/uploads/{UPLOAD_ID}",
                headers={
                    "content-type": "application/octet-stream",
                    "content-length": "4",
                    "upload-offset": "0",
                },
                content=source(),
            )

    assert response.status_code == 400
    assert response.json()["code"] == "CONTENT_LENGTH_MISMATCH"


@pytest.mark.asyncio
async def test_offset_conflict_is_structured_and_upstream_error_is_sanitized() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return _json_response(
            {
                "error": {
                    "code": "upload_offset_mismatch",
                    "message": "service-secret at /mnt/data/private",
                    "expectedOffset": 4096,
                    "private": "do not forward",
                }
            },
            status_code=409,
            headers={"Upload-Offset": "4096"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        app = Starlette()
        register_knowledge_management_routes(
            app,
            config=_config(),
            http_client=upstream,
        )
        async for client in _browser_client(app):
            response = await client.patch(
                f"/api/v1/knowledge/uploads/{UPLOAD_ID}",
                headers={
                    "content-type": "application/octet-stream",
                    "upload-offset": "0",
                },
                content=b"abc",
            )

    assert response.status_code == 409
    assert response.headers["upload-offset"] == "4096"
    assert response.json() == {
        "error": {
            "code": "upload_offset_mismatch",
            "message": "upload offset does not match server state",
            "expectedOffset": 4096,
        }
    }
    assert "service-secret" not in response.text
    assert "/mnt/data/private" not in response.text


@pytest.mark.asyncio
async def test_timeout_and_invalid_success_response_do_not_leak_details() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout(
                "service-secret https://private.internal",
                request=request,
            )
        return _json_response(
            {
                "uploadId": UPLOAD_ID,
                "filename": "handbook.pdf",
                "sizeBytes": 1024,
                "uploadedBytes": 0,
                "indexTypes": ["fts"],
            },
            status_code=200,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        app = Starlette()
        register_knowledge_management_routes(
            app,
            config=_config(),
            http_client=upstream,
        )
        async for client in _browser_client(app):
            timeout = await client.get(f"/api/v1/knowledge/uploads/{UPLOAD_ID}")
            invalid = await client.get(f"/api/v1/knowledge/uploads/{UPLOAD_ID}")

    assert timeout.status_code == 504
    assert timeout.json()["code"] == "KNOWLEDGE_UPSTREAM_TIMEOUT"
    assert "service-secret" not in timeout.text
    assert "private.internal" not in timeout.text
    assert invalid.status_code == 502
    assert invalid.json()["code"] == "KNOWLEDGE_UPSTREAM_INVALID_RESPONSE"


@pytest.mark.asyncio
async def test_job_nested_contract_rejects_bad_warnings_and_error() -> None:
    responses = [
        _job_payload(warnings=[{"message": "not a string"}]),
        _job_payload(error={"code": "parse_failed"}),
        _job_payload(
            upload={
                "uploadedBytes": 2,
                "sizeBytes": 1,
                "percent": 100,
            }
        ),
    ]

    async def handler(_request: httpx.Request) -> httpx.Response:
        return _json_response(
            responses.pop(0),
            status_code=200,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        app = Starlette()
        register_knowledge_management_routes(
            app,
            config=_config(),
            http_client=upstream,
        )
        async for client in _browser_client(app):
            for _ in range(3):
                response = await client.get(f"/api/v1/knowledge/jobs/{JOB_ID}")
                assert response.status_code == 502


@pytest.mark.asyncio
async def test_client_disconnect_during_patch_is_mapped_to_499() -> None:
    messages = [
        {
            "type": "http.request",
            "body": b"abc",
            "more_body": True,
        },
        {"type": "http.disconnect"},
    ]

    async def receive() -> dict[str, Any]:
        return messages.pop(0)

    async def handler(request: httpx.Request) -> httpx.Response:
        async for _chunk in request.stream:
            pass
        raise AssertionError("disconnect must abort upstream request")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        proxy = KnowledgeManagementProxy(
            _config(),
            http_client=upstream,
        )
        request = Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "PATCH",
                "scheme": "http",
                "path": f"/api/v1/knowledge/uploads/{UPLOAD_ID}",
                "raw_path": (f"/api/v1/knowledge/uploads/{UPLOAD_ID}".encode()),
                "query_string": b"",
                "headers": [
                    (b"host", b"gateway.test"),
                    (b"content-type", b"application/octet-stream"),
                    (b"content-length", b"6"),
                    (b"upload-offset", b"0"),
                ],
                "client": ("127.0.0.1", 1234),
                "server": ("gateway.test", 80),
                "path_params": {"upload_id": UPLOAD_ID},
            },
            receive,
        )
        response = await proxy.patch_upload(request)

    assert response.status_code == 499
    assert json.loads(response.body)["code"] == "CLIENT_DISCONNECTED"


@pytest.mark.asyncio
async def test_same_origin_guard_and_existing_auth_mode_are_preserved() -> None:
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("request should not reach upstream")

    token_config = GatewayConfig.model_validate(
        {
            "auth": {"mode": "token", "token": "gateway-secret"},
            "knowledge": {"enabled": False},
        }
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        app = Starlette(
            middleware=[
                Middleware(
                    AuthMiddleware,
                    config=token_config,
                )
            ]
        )
        register_knowledge_management_routes(
            app,
            config=token_config,
            http_client=upstream,
        )
        async for client in _browser_client(app):
            unauthorized = await client.get(f"/api/v1/knowledge/uploads/{UPLOAD_ID}")
            configured_off = await client.get(
                f"/api/v1/knowledge/uploads/{UPLOAD_ID}",
                headers={"authorization": "Bearer gateway-secret"},
            )

    assert unauthorized.status_code == 401
    assert configured_off.status_code == 503

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        app = Starlette()
        register_knowledge_management_routes(
            app,
            config=_config(),
            http_client=upstream,
        )
        async for client in _browser_client(app):
            forbidden = await client.post(
                "/api/v1/knowledge/uploads",
                headers={"origin": "https://evil.example"},
                json={
                    "filename": "handbook.pdf",
                    "sizeBytes": 1,
                    "indexTypes": ["fts"],
                },
            )

    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "FORBIDDEN_ORIGIN"
    assert calls == 0


def test_gateway_factory_registers_exact_management_routes() -> None:
    app = create_gateway_app(GatewayConfig())

    registered = {
        (route.path, frozenset(route.methods or set()))
        for route in app.routes
        if route.path.startswith("/api/v1/knowledge/")
    }

    assert registered == {
        ("/api/v1/knowledge/stats", frozenset({"GET", "HEAD"})),
        ("/api/v1/knowledge/uploads", frozenset({"POST"})),
        (
            "/api/v1/knowledge/uploads/{upload_id}",
            frozenset({"GET", "HEAD"}),
        ),
        (
            "/api/v1/knowledge/uploads/{upload_id}",
            frozenset({"PATCH"}),
        ),
        (
            "/api/v1/knowledge/uploads/{upload_id}/complete",
            frozenset({"POST"}),
        ),
        (
            "/api/v1/knowledge/jobs/{job_id}",
            frozenset({"GET", "HEAD"}),
        ),
    }
