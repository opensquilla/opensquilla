"""Streaming BFF for resumable customer knowledge uploads.

The browser-facing routes mirror the Knowledge management API while keeping
the Knowledge endpoint and bearer token on the Gateway side. Upload chunks
flow directly from Starlette's request stream into httpx's async request
stream; they are never materialized by the Gateway.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import AsyncIterable, AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from starlette.applications import Starlette
from starlette.requests import ClientDisconnect, Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from opensquilla.gateway.config import GatewayConfig
from opensquilla.gateway.origin_guard import (
    forbidden_origin_response,
    request_origin_allowed,
)

_MAX_METADATA_BYTES = 16 * 1024
_MAX_RESPONSE_BYTES = 256 * 1024
_MAX_SIGNED_64 = (1 << 63) - 1
_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_DECIMAL_RE = re.compile(r"(?:0|[1-9][0-9]*)\Z")
_INDEX_TYPES = {("fts",), ("vector",), ("fts", "vector")}
_JOB_STATES = {"queued", "running", "ready", "ready_with_warnings", "failed"}
_JOB_PHASES = {
    "validating",
    "extracting",
    "parsing",
    "fts_indexing",
    "vector_indexing",
    "complete",
}
_UPLOAD_FIELDS = {
    "uploadId",
    "filename",
    "sizeBytes",
    "uploadedBytes",
    "indexTypes",
    "chunkSizeBytes",
}
_JOB_FIELDS = {
    "jobId",
    "uploadId",
    "state",
    "phase",
    "overallProgress",
    "upload",
    "files",
    "chunks",
    "warnings",
    "error",
}


@dataclass(slots=True)
class _RequestError(Exception):
    status_code: int
    code: str
    message: str

    def response(self) -> JSONResponse:
        return _error_response(self.status_code, self.code, self.message)


class _RequestBodyError(Exception):
    pass


class _UpstreamProtocolError(Exception):
    pass


class _DuplicateJsonKeyError(ValueError):
    pass


class _StreamingRequestBody:
    """One-shot, length-checking iterator over the inbound ASGI body."""

    def __init__(self, request: Request, expected_length: int) -> None:
        self._request = request
        self.expected_length = expected_length
        self.bytes_seen = 0
        self.complete = False
        self.disconnected = False
        self.invalid = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        try:
            async for chunk in self._request.stream():
                if not chunk:
                    continue
                new_size = self.bytes_seen + len(chunk)
                if new_size > self.expected_length:
                    self.invalid = True
                    raise _RequestBodyError("request body exceeds Content-Length")
                self.bytes_seen = new_size
                yield chunk
        except ClientDisconnect:
            self.disconnected = True
            raise
        except _RequestBodyError:
            raise
        except Exception as error:
            self.invalid = True
            raise _RequestBodyError("request body stream failed") from error
        if self.bytes_seen != self.expected_length:
            self.invalid = True
            raise _RequestBodyError("request body does not match Content-Length")
        self.complete = True


class KnowledgeManagementProxy:
    """Validate and proxy the five browser-facing management routes."""

    def __init__(
        self,
        config: GatewayConfig,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._gateway_config = config
        self._settings = config.knowledge
        self._http_client = http_client
        provider_url = urlsplit(self._settings.provider_base_url)
        # Protocol 1.1 may be mounted below /opensquilla-rag, while the
        # management API is registered at the same origin's root.
        self._management_base_url = urlunsplit(
            (provider_url.scheme, provider_url.netloc, "", "", "")
        ).rstrip("/")

    async def create_upload(self, request: Request) -> Response:
        early = self._preflight(request, mutating=True)
        if early is not None:
            return early
        try:
            raw_body, payload = await _read_request_json(request)
            _validate_create_upload_request(payload)
        except _RequestError as error:
            return error.response()
        return await self._forward(
            method="POST",
            path="/v1/management/uploads",
            operation="create",
            expected_status=201,
            content=raw_body,
            request_headers={
                "content-type": "application/json",
                "content-length": str(len(raw_body)),
            },
            validate=lambda body: _validate_upload_response(
                body,
                expected_metadata=payload,
            ),
        )

    async def get_upload(self, request: Request) -> Response:
        early = self._preflight(request, mutating=False)
        if early is not None:
            return early
        try:
            upload_id = _validated_identifier(
                request.path_params.get("upload_id"),
                "uploadId",
            )
        except _RequestError as error:
            return error.response()
        return await self._forward(
            method="GET",
            path=f"/v1/management/uploads/{upload_id}",
            operation="upload",
            expected_status=200,
            validate=lambda body: _validate_upload_response(
                body,
                expected_upload_id=upload_id,
            ),
        )

    async def patch_upload(self, request: Request) -> Response:
        early = self._preflight(request, mutating=True)
        if early is not None:
            return early
        try:
            upload_id = _validated_identifier(
                request.path_params.get("upload_id"),
                "uploadId",
            )
            _reject_encoded_or_chunked_request(request)
            _require_content_type(request, "application/octet-stream")
            upload_offset = _required_decimal_header(request, "upload-offset")
            content_length = _required_decimal_header(request, "content-length")
        except _RequestError as error:
            return error.response()

        body_stream = _StreamingRequestBody(request, content_length)
        return await self._forward(
            method="PATCH",
            path=f"/v1/management/uploads/{upload_id}",
            operation="patch",
            expected_status=200,
            content=body_stream,
            request_headers={
                "content-type": "application/octet-stream",
                "content-length": str(content_length),
                "upload-offset": str(upload_offset),
            },
            validate=lambda body: _validate_upload_response(
                body,
                expected_upload_id=upload_id,
            ),
            require_upload_offset=True,
            body_stream=body_stream,
        )

    async def complete_upload(self, request: Request) -> Response:
        early = self._preflight(request, mutating=True)
        if early is not None:
            return early
        try:
            upload_id = _validated_identifier(
                request.path_params.get("upload_id"),
                "uploadId",
            )
            await _validate_empty_request(request)
        except _RequestError as error:
            return error.response()
        return await self._forward(
            method="POST",
            path=f"/v1/management/uploads/{upload_id}/complete",
            operation="complete",
            expected_status=202,
            content=b"",
            request_headers={"content-length": "0"},
            validate=lambda body: _validate_complete_response(body, upload_id),
        )

    async def get_job(self, request: Request) -> Response:
        early = self._preflight(request, mutating=False)
        if early is not None:
            return early
        try:
            job_id = _validated_identifier(
                request.path_params.get("job_id"),
                "jobId",
            )
        except _RequestError as error:
            return error.response()
        return await self._forward(
            method="GET",
            path=f"/v1/management/jobs/{job_id}",
            operation="job",
            expected_status=200,
            validate=lambda body: _validate_job_response(body, job_id),
        )

    def _preflight(self, request: Request, *, mutating: bool) -> Response | None:
        if mutating and not request_origin_allowed(request, self._gateway_config):
            return forbidden_origin_response()
        if not self._settings.enabled or self._settings.legacy_knowledge_adapter:
            return _error_response(
                503,
                "KNOWLEDGE_NOT_CONFIGURED",
                "knowledge management is not configured",
            )
        return None

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[httpx.AsyncClient]:
        if self._http_client is not None:
            yield self._http_client
            return
        timeout = httpx.Timeout(
            self._settings.request_timeout_seconds,
            connect=self._settings.connect_timeout_seconds,
        )
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            yield client

    def _upstream_headers(self) -> dict[str, str]:
        headers = {
            "accept": "application/json",
            "accept-encoding": "identity",
        }
        token_env = self._settings.authentication_token_env
        token = os.environ.get(token_env) if token_env else None
        if token:
            headers["authorization"] = f"Bearer {token}"
        return headers

    async def _forward(
        self,
        *,
        method: str,
        path: str,
        operation: str,
        expected_status: int,
        validate: Callable[[dict[str, Any]], None],
        content: bytes | AsyncIterable[bytes] | None = None,
        request_headers: dict[str, str] | None = None,
        require_upload_offset: bool = False,
        body_stream: _StreamingRequestBody | None = None,
    ) -> Response:
        headers = self._upstream_headers()
        if request_headers:
            headers.update(request_headers)
        url = f"{self._management_base_url}{path}"
        try:
            async with self._client() as client:
                async with client.stream(
                    method,
                    url,
                    headers=headers,
                    content=content,
                ) as upstream:
                    if upstream.status_code >= 400:
                        return await _safe_upstream_error(
                            upstream,
                            operation=operation,
                        )
                    if upstream.status_code != expected_status:
                        raise _UpstreamProtocolError("unexpected upstream status")
                    payload = await _read_upstream_json(upstream)
                    validate(payload)
                    response_headers: dict[str, str] = {}
                    if require_upload_offset:
                        offset = _required_upstream_offset(upstream)
                        if payload.get("uploadedBytes") != offset:
                            raise _UpstreamProtocolError(
                                "Upload-Offset does not match uploadedBytes"
                            )
                        response_headers["Upload-Offset"] = str(offset)
                    if body_stream is not None and not body_stream.complete:
                        raise _UpstreamProtocolError("upstream did not consume upload body")
                    return JSONResponse(
                        payload,
                        status_code=upstream.status_code,
                        headers=response_headers,
                    )
        except ClientDisconnect:
            return _error_response(
                499,
                "CLIENT_DISCONNECTED",
                "upload client disconnected",
            )
        except _RequestBodyError:
            return _content_length_mismatch_response()
        except httpx.TimeoutException:
            if body_stream is not None and body_stream.disconnected:
                return _error_response(
                    499,
                    "CLIENT_DISCONNECTED",
                    "upload client disconnected",
                )
            if body_stream is not None and body_stream.invalid:
                return _content_length_mismatch_response()
            return _error_response(
                504,
                "KNOWLEDGE_UPSTREAM_TIMEOUT",
                "knowledge service request timed out",
            )
        except httpx.RequestError:
            if body_stream is not None and body_stream.disconnected:
                return _error_response(
                    499,
                    "CLIENT_DISCONNECTED",
                    "upload client disconnected",
                )
            if body_stream is not None and body_stream.invalid:
                return _content_length_mismatch_response()
            return _error_response(
                502,
                "KNOWLEDGE_UPSTREAM_UNAVAILABLE",
                "knowledge service is unavailable",
            )
        except _UpstreamProtocolError:
            return _invalid_upstream_response()
        except Exception:
            # Do not let an upstream URL, token, or response body reach the
            # Gateway's generic exception logger/response surface.
            return _invalid_upstream_response()


def register_knowledge_management_routes(
    app: Starlette,
    *,
    config: GatewayConfig,
    http_client: httpx.AsyncClient | None = None,
) -> KnowledgeManagementProxy:
    """Register the isomorphic browser routes."""
    proxy = KnowledgeManagementProxy(config, http_client=http_client)
    app.router.routes.extend(
        [
            Route(
                "/api/v1/knowledge/uploads",
                proxy.create_upload,
                methods=["POST"],
            ),
            Route(
                "/api/v1/knowledge/uploads/{upload_id}",
                proxy.get_upload,
                methods=["GET"],
            ),
            Route(
                "/api/v1/knowledge/uploads/{upload_id}",
                proxy.patch_upload,
                methods=["PATCH"],
            ),
            Route(
                "/api/v1/knowledge/uploads/{upload_id}/complete",
                proxy.complete_upload,
                methods=["POST"],
            ),
            Route(
                "/api/v1/knowledge/jobs/{job_id}",
                proxy.get_job,
                methods=["GET"],
            ),
        ]
    )
    return proxy


async def _read_request_json(request: Request) -> tuple[bytes, dict[str, Any]]:
    _reject_encoded_or_chunked_request(request)
    _require_content_type(request, "application/json")
    content_length = _required_decimal_header(request, "content-length")
    if content_length > _MAX_METADATA_BYTES:
        raise _RequestError(
            413,
            "METADATA_TOO_LARGE",
            "upload metadata is too large",
        )
    body = bytearray()
    try:
        async for chunk in request.stream():
            if not chunk:
                continue
            body.extend(chunk)
            if len(body) > content_length:
                raise _RequestError(
                    400,
                    "CONTENT_LENGTH_MISMATCH",
                    "request body does not match Content-Length",
                )
    except ClientDisconnect as error:
        raise _RequestError(
            499,
            "CLIENT_DISCONNECTED",
            "upload client disconnected",
        ) from error
    if len(body) != content_length:
        raise _RequestError(
            400,
            "CONTENT_LENGTH_MISMATCH",
            "request body does not match Content-Length",
        )
    try:
        payload = _parse_json_object(bytes(body))
    except (UnicodeError, ValueError, _DuplicateJsonKeyError) as error:
        raise _RequestError(
            400,
            "INVALID_JSON",
            "request body must be valid JSON",
        ) from error
    return bytes(body), payload


async def _validate_empty_request(request: Request) -> None:
    _reject_encoded_or_chunked_request(request)
    raw_length = _single_request_header(request, "content-length")
    if raw_length is not None and _parse_decimal(raw_length, "Content-Length") != 0:
        raise _RequestError(
            400,
            "BODY_NOT_ALLOWED",
            "request body must be empty",
        )
    try:
        async for chunk in request.stream():
            if chunk:
                raise _RequestError(
                    400,
                    "BODY_NOT_ALLOWED",
                    "request body must be empty",
                )
    except ClientDisconnect as error:
        raise _RequestError(
            499,
            "CLIENT_DISCONNECTED",
            "upload client disconnected",
        ) from error


def _validate_create_upload_request(payload: dict[str, Any]) -> None:
    if set(payload) != {"filename", "sizeBytes", "indexTypes"}:
        raise _RequestError(
            400,
            "INVALID_UPLOAD_METADATA",
            "upload metadata must contain exactly filename, sizeBytes, and indexTypes",
        )
    _validated_filename(payload.get("filename"))
    _validated_nonnegative_int(payload.get("sizeBytes"), "sizeBytes")
    _validated_index_types(payload.get("indexTypes"))


def _validate_upload_response(
    payload: dict[str, Any],
    *,
    expected_upload_id: str | None = None,
    expected_metadata: dict[str, Any] | None = None,
) -> None:
    if not _UPLOAD_FIELDS.issubset(payload):
        raise _UpstreamProtocolError("upload response is missing required fields")
    upload_id = _validated_upstream_identifier(payload.get("uploadId"))
    if expected_upload_id is not None and upload_id != expected_upload_id:
        raise _UpstreamProtocolError("uploadId mismatch")
    try:
        filename = _validated_filename(payload.get("filename"))
        index_types = _validated_index_types(payload.get("indexTypes"))
    except _RequestError as error:
        raise _UpstreamProtocolError("invalid upload response") from error
    size_bytes = _validated_upstream_nonnegative_int(payload.get("sizeBytes"))
    uploaded_bytes = _validated_upstream_nonnegative_int(payload.get("uploadedBytes"))
    chunk_size = _validated_upstream_positive_int(payload.get("chunkSizeBytes"))
    if uploaded_bytes > size_bytes:
        raise _UpstreamProtocolError("uploadedBytes exceeds sizeBytes")
    if expected_metadata is not None:
        expected = (
            expected_metadata["filename"],
            expected_metadata["sizeBytes"],
            expected_metadata["indexTypes"],
        )
        if (filename, size_bytes, index_types) != expected:
            raise _UpstreamProtocolError("upload metadata mismatch")
    if chunk_size <= 0:
        raise _UpstreamProtocolError("invalid chunkSizeBytes")


def _validate_complete_response(
    payload: dict[str, Any],
    expected_upload_id: str,
) -> None:
    if not {"uploadId", "jobId", "state"}.issubset(payload):
        raise _UpstreamProtocolError("complete response is missing required fields")
    if _validated_upstream_identifier(payload.get("uploadId")) != expected_upload_id:
        raise _UpstreamProtocolError("uploadId mismatch")
    _validated_upstream_identifier(payload.get("jobId"))
    if payload.get("state") not in _JOB_STATES:
        raise _UpstreamProtocolError("invalid job state")


def _validate_job_response(
    payload: dict[str, Any],
    expected_job_id: str,
) -> None:
    if not _JOB_FIELDS.issubset(payload):
        raise _UpstreamProtocolError("job response is missing required fields")
    if _validated_upstream_identifier(payload.get("jobId")) != expected_job_id:
        raise _UpstreamProtocolError("jobId mismatch")
    _validated_upstream_identifier(payload.get("uploadId"))
    if payload.get("state") not in _JOB_STATES:
        raise _UpstreamProtocolError("invalid job state")
    if payload.get("phase") not in _JOB_PHASES:
        raise _UpstreamProtocolError("invalid job phase")
    _validated_upstream_percent(payload.get("overallProgress"))

    upload = _validated_upstream_mapping(payload.get("upload"), "upload")
    if not {"uploadedBytes", "sizeBytes", "percent"}.issubset(upload):
        raise _UpstreamProtocolError("upload progress is missing required fields")
    uploaded_bytes = _validated_upstream_nonnegative_int(upload.get("uploadedBytes"))
    size_bytes = _validated_upstream_nonnegative_int(upload.get("sizeBytes"))
    if uploaded_bytes > size_bytes:
        raise _UpstreamProtocolError("upload progress uploadedBytes exceeds sizeBytes")
    _validated_upstream_percent(upload.get("percent"))

    files = _validated_upstream_mapping(payload.get("files"), "files")
    for field in ("total", "processed", "skipped", "failed"):
        if field not in files:
            raise _UpstreamProtocolError("file progress is missing required fields")
        _validated_upstream_nonnegative_int(files[field])

    chunks = _validated_upstream_mapping(payload.get("chunks"), "chunks")
    for field in ("total", "ftsIndexed", "vectorIndexed"):
        if field not in chunks:
            raise _UpstreamProtocolError("chunk progress is missing required fields")
        _validated_upstream_nonnegative_int(chunks[field])

    warnings = payload.get("warnings")
    if not isinstance(warnings, list) or any(not isinstance(warning, str) for warning in warnings):
        raise _UpstreamProtocolError("warnings must be a string array")
    error = payload.get("error")
    if error is not None:
        error_payload = _validated_upstream_mapping(error, "error")
        if not {"code", "message"}.issubset(error_payload):
            raise _UpstreamProtocolError("error is missing code or message")
        _validated_upstream_short_string(error_payload.get("code"))
        _validated_upstream_message(error_payload.get("message"))


def _validated_index_types(value: Any) -> list[str]:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) for item in value)
        or tuple(value) not in _INDEX_TYPES
    ):
        raise _RequestError(
            400,
            "INVALID_INDEX_TYPES",
            'indexTypes must be ["fts"], ["vector"], or ["fts","vector"]',
        )
    return value


def _validated_filename(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or len(value.encode("utf-8")) > 1024
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise _RequestError(
            400,
            "INVALID_FILENAME",
            "filename must be a plain file name",
        )
    return value


def _validated_identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER_RE.fullmatch(value) is None:
        code_name = re.sub(r"(?<!^)(?=[A-Z])", "_", name).upper()
        raise _RequestError(
            400,
            f"INVALID_{code_name}",
            f"{name} is invalid",
        )
    return value


def _validated_nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= _MAX_SIGNED_64:
        raise _RequestError(
            400,
            f"INVALID_{name.upper()}",
            f"{name} must be a non-negative integer",
        )
    return value


def _validated_upstream_identifier(value: Any) -> str:
    if not isinstance(value, str) or _IDENTIFIER_RE.fullmatch(value) is None:
        raise _UpstreamProtocolError("invalid identifier")
    return value


def _validated_upstream_nonnegative_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= _MAX_SIGNED_64:
        raise _UpstreamProtocolError("invalid non-negative integer")
    return value


def _validated_upstream_positive_int(value: Any) -> int:
    parsed = _validated_upstream_nonnegative_int(value)
    if parsed == 0:
        raise _UpstreamProtocolError("invalid positive integer")
    return parsed


def _validated_upstream_percent(value: Any) -> float | int:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
        or value > 100
    ):
        raise _UpstreamProtocolError("invalid percentage")
    return value


def _validated_upstream_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _UpstreamProtocolError(f"{name} must be an object")
    return value


def _validated_upstream_short_string(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise _UpstreamProtocolError("invalid short string")
    return value


def _validated_upstream_message(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 4096:
        raise _UpstreamProtocolError("invalid message")
    return value


def _reject_encoded_or_chunked_request(request: Request) -> None:
    if _single_request_header(request, "transfer-encoding") is not None:
        raise _RequestError(
            400,
            "TRANSFER_ENCODING_NOT_ALLOWED",
            "Transfer-Encoding is not allowed",
        )
    content_encoding = _single_request_header(request, "content-encoding")
    if content_encoding is not None and content_encoding.lower() != "identity":
        raise _RequestError(
            415,
            "CONTENT_ENCODING_NOT_ALLOWED",
            "Content-Encoding is not allowed",
        )


def _require_content_type(request: Request, expected: str) -> None:
    raw = _single_request_header(request, "content-type")
    if raw is None:
        raise _RequestError(
            415,
            "INVALID_CONTENT_TYPE",
            f"Content-Type must be {expected}",
        )
    parts = [part.strip() for part in raw.split(";")]
    if not parts or parts[0].lower() != expected:
        raise _RequestError(
            415,
            "INVALID_CONTENT_TYPE",
            f"Content-Type must be {expected}",
        )
    for parameter in parts[1:]:
        if expected != "application/json" or parameter.lower() != "charset=utf-8":
            raise _RequestError(
                415,
                "INVALID_CONTENT_TYPE",
                f"Content-Type must be {expected}",
            )


def _single_request_header(request: Request, name: str) -> str | None:
    encoded_name = name.lower().encode("ascii")
    values = [
        value.decode("latin-1")
        for key, value in request.scope.get("headers", [])
        if key.lower() == encoded_name
    ]
    if len(values) > 1:
        raise _RequestError(
            400,
            "DUPLICATE_HEADER",
            f"{name} must appear exactly once",
        )
    return values[0] if values else None


def _required_decimal_header(request: Request, name: str) -> int:
    raw = _single_request_header(request, name)
    if raw is None:
        status = 411 if name == "content-length" else 400
        code_name = name.upper().replace("-", "_")
        raise _RequestError(
            status,
            f"MISSING_{code_name}",
            f"{name} is required",
        )
    return _parse_decimal(raw, name)


def _parse_decimal(raw: str, name: str) -> int:
    code_name = name.upper().replace("-", "_")
    if _DECIMAL_RE.fullmatch(raw) is None:
        raise _RequestError(
            400,
            f"INVALID_{code_name}",
            f"{name} must be a canonical non-negative decimal integer",
        )
    value = int(raw)
    if value > _MAX_SIGNED_64:
        raise _RequestError(
            400,
            f"INVALID_{code_name}",
            f"{name} is too large",
        )
    return value


async def _read_upstream_json(response: httpx.Response) -> dict[str, Any]:
    content_type = _single_upstream_header(response, "content-type")
    if content_type is None or content_type.split(";", 1)[0].strip().lower() != "application/json":
        raise _UpstreamProtocolError("upstream response is not JSON")
    content_encoding = _single_upstream_header(response, "content-encoding")
    if content_encoding is not None and content_encoding.lower() != "identity":
        raise _UpstreamProtocolError("encoded upstream response is not allowed")
    raw_length = _single_upstream_header(response, "content-length")
    declared_length: int | None = None
    if raw_length is not None:
        if _DECIMAL_RE.fullmatch(raw_length) is None:
            raise _UpstreamProtocolError("invalid upstream Content-Length")
        declared_length = int(raw_length)
        if declared_length > _MAX_RESPONSE_BYTES:
            raise _UpstreamProtocolError("upstream response is too large")
    chunks: list[bytes] = []
    size = 0
    if response.is_stream_consumed:
        loaded = response.content
        size = len(loaded)
        if size > _MAX_RESPONSE_BYTES:
            raise _UpstreamProtocolError("upstream response is too large")
        chunks.append(loaded)
    else:
        async for chunk in response.aiter_raw():
            size += len(chunk)
            if size > _MAX_RESPONSE_BYTES:
                raise _UpstreamProtocolError("upstream response is too large")
            chunks.append(chunk)
    if declared_length is not None and declared_length != size:
        raise _UpstreamProtocolError("upstream Content-Length mismatch")
    try:
        return _parse_json_object(b"".join(chunks))
    except (UnicodeError, ValueError, _DuplicateJsonKeyError) as error:
        raise _UpstreamProtocolError("upstream response is invalid JSON") from error


def _parse_json_object(raw: bytes) -> dict[str, Any]:
    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise _DuplicateJsonKeyError(key)
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise ValueError(value)

    payload = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=pairs_hook,
        parse_constant=reject_constant,
    )
    if not isinstance(payload, dict):
        raise ValueError("JSON object required")
    return payload


def _single_upstream_header(
    response: httpx.Response,
    name: str,
) -> str | None:
    encoded_name = name.lower().encode("ascii")
    values = [
        value.decode("latin-1")
        for key, value in response.headers.raw
        if key.lower() == encoded_name
    ]
    if len(values) > 1:
        raise _UpstreamProtocolError(f"duplicate upstream {name}")
    return values[0] if values else None


def _required_upstream_offset(response: httpx.Response) -> int:
    raw = _single_upstream_header(response, "upload-offset")
    if raw is None or _DECIMAL_RE.fullmatch(raw) is None:
        raise _UpstreamProtocolError("invalid upstream Upload-Offset")
    value = int(raw)
    if value > _MAX_SIGNED_64:
        raise _UpstreamProtocolError("invalid upstream Upload-Offset")
    return value


async def _safe_upstream_error(
    response: httpx.Response,
    *,
    operation: str,
) -> JSONResponse:
    status = response.status_code
    if status == 409 and operation == "patch":
        payload = await _read_upstream_json(response)
        error = _validated_upstream_mapping(payload.get("error"), "error")
        if error.get("code") != "upload_offset_mismatch":
            raise _UpstreamProtocolError("invalid offset conflict code")
        expected = _validated_upstream_nonnegative_int(error.get("expectedOffset"))
        _validated_upstream_message(error.get("message"))
        raw_offset = _single_upstream_header(response, "upload-offset")
        headers: dict[str, str] = {}
        if raw_offset is not None:
            if _DECIMAL_RE.fullmatch(raw_offset) is None or int(raw_offset) != expected:
                raise _UpstreamProtocolError("invalid offset conflict header")
            headers["Upload-Offset"] = raw_offset
        return JSONResponse(
            {
                "error": {
                    "code": "upload_offset_mismatch",
                    "message": "upload offset does not match server state",
                    "expectedOffset": expected,
                }
            },
            status_code=409,
            headers=headers,
        )
    if status in {400, 422}:
        return _error_response(
            400,
            "KNOWLEDGE_REQUEST_REJECTED",
            "knowledge service rejected the request",
        )
    if status in {401, 403}:
        return _error_response(
            502,
            "KNOWLEDGE_UPSTREAM_AUTH_FAILED",
            "knowledge service authentication failed",
        )
    if status == 404:
        code = "JOB_NOT_FOUND" if operation == "job" else "UPLOAD_NOT_FOUND"
        resource = "job" if operation == "job" else "upload"
        return _error_response(
            404,
            code,
            f"knowledge {resource} was not found",
        )
    if status == 409:
        return _error_response(
            409,
            "UPLOAD_CONFLICT",
            "knowledge upload state conflict",
        )
    if status == 413:
        return _error_response(
            413,
            "UPLOAD_TOO_LARGE",
            "knowledge upload is too large",
        )
    if status == 429:
        return _error_response(
            503,
            "KNOWLEDGE_BUSY",
            "knowledge service is busy",
        )
    if status in {408, 504}:
        return _error_response(
            504,
            "KNOWLEDGE_UPSTREAM_TIMEOUT",
            "knowledge service request timed out",
        )
    return _error_response(
        502,
        "KNOWLEDGE_UPSTREAM_ERROR",
        "knowledge service request failed",
    )


def _content_length_mismatch_response() -> JSONResponse:
    return _error_response(
        400,
        "CONTENT_LENGTH_MISMATCH",
        "request body does not match Content-Length",
    )


def _invalid_upstream_response() -> JSONResponse:
    return _error_response(
        502,
        "KNOWLEDGE_UPSTREAM_INVALID_RESPONSE",
        "knowledge service returned an invalid response",
    )


def _error_response(
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    return JSONResponse(
        {"error": message, "code": code},
        status_code=status_code,
    )


__all__ = [
    "KnowledgeManagementProxy",
    "register_knowledge_management_routes",
]
