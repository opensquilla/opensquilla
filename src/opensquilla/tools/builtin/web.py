"""Web built-in tools: http_request, web_search."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

import httpx

from opensquilla.env import trust_env as _trust_env
from opensquilla.safety.sensitive_payloads import (
    sensitive_body_block as _sensitive_body_block,
)
from opensquilla.safety.sensitive_payloads import (
    sensitive_body_marker as _sensitive_body_marker,
)
from opensquilla.safety.sensitive_payloads import (
    sensitive_headers_marker as _sensitive_headers_marker,
)
from opensquilla.safety.sensitive_payloads import (
    sensitive_url_marker as _sensitive_url_marker,
)
from opensquilla.sandbox.integration import sandboxed
from opensquilla.search import runtime as search_runtime
from opensquilla.search.execution import (
    run_search_payload,
)
from opensquilla.search.execution import (
    search_runtime_status as _search_runtime_status,
)
from opensquilla.tools.registry import tool
from opensquilla.tools.ssrf import validate_http_url_scheme
from opensquilla.tools.types import ToolError, current_tool_context

_SENSITIVE_HTTP_METHODS = {"POST", "PUT", "PATCH"}
_TEXT_BODY_LIMIT = 10_000
_BINARY_BODY_LIMIT = 1_000_000
_LARGE_RESPONSE_SAVE_THRESHOLD = 50_000
_FETCH_DIR_NAME = ".fetch"


def _is_text_response_content_type(content_type: str) -> bool:
    normalized = content_type.lower().split(";", 1)[0].strip()
    if normalized.startswith("text/"):
        return True
    return (
        normalized in {"application/json", "application/xml", "application/xhtml+xml"}
        or normalized.endswith("+json")
        or normalized.endswith("+xml")
        or "json" in normalized
        or "xml" in normalized
    )


def _fetch_workspace_dir() -> Path:
    ctx = current_tool_context.get()
    if ctx is not None and ctx.workspace_dir:
        return Path(ctx.workspace_dir).expanduser().resolve()
    return Path.cwd().resolve()


def _fetch_root() -> Path:
    return (_fetch_workspace_dir() / _FETCH_DIR_NAME).resolve()


def _resolve_fetch_output_path(digest: str, output_path: str | None) -> Path:
    root = _fetch_root()
    if output_path is None:
        return root / f"{digest}.bin"

    raw = output_path.strip()
    if not raw:
        raise ToolError("output_path must not be empty")

    requested = Path(raw).expanduser()
    if requested.drive and not requested.is_absolute():
        raise ToolError("output_path must be an absolute path or a relative .fetch path")
    candidate = requested if requested.is_absolute() else root / requested
    resolved = candidate.resolve(strict=False)
    if resolved == root or not resolved.is_relative_to(root):
        raise ToolError(f"output_path must stay inside {root}")
    if resolved.exists() and resolved.is_dir():
        raise ToolError("output_path must name a file, not a directory")
    return resolved


def _save_http_response_body(raw_body: bytes, output_path: str | None) -> tuple[Path, str]:
    digest = hashlib.sha256(raw_body).hexdigest()
    path = _resolve_fetch_output_path(digest, output_path)
    if output_path is not None and path.exists():
        raise ToolError("output_path already exists")
    if output_path is None and path.exists():
        return path, digest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw_body)
    return path, digest


@tool(
    name="http_request",
    description=(
        "Make an HTTP request. Large responses are saved under the workspace .fetch "
        "directory and returned as metadata."
    ),
    params={
        "url": {"type": "string", "description": "HTTP or HTTPS URL."},
        "method": {"type": "string", "description": "HTTP method (default: GET)."},
        "headers": {
            "type": "object",
            "description": "Request headers.",
            "additionalProperties": {"type": "string"},
        },
        "body": {"type": "string", "description": "Request body (for POST/PUT/PATCH)."},
        "timeout": {"type": "number", "description": "Request timeout in seconds (default 30)."},
        "output_path": {
            "type": "string",
            "description": "Optional file name/path inside the workspace .fetch directory.",
        },
    },
    required=["url"],
    owner_only=True,
)
@sandboxed(
    kind="network.http",
    argv_factory=lambda a: (
        "http_request",
        str(a.get("method", "GET")).upper(),
        str(a.get("url", "")),
        str(a.get("output_path", "")),
    ),
    record_payload=False,
)
async def http_request(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: str | None = None,
    timeout: float = 30.0,
    output_path: str | None = None,
) -> str:
    validate_http_url_scheme(url, error_message=url)
    marker = _sensitive_url_marker(url)
    if marker is not None:
        return _sensitive_body_block("http_request", marker)
    marker = _sensitive_headers_marker(headers)
    if marker is not None:
        return _sensitive_body_block("http_request", marker)
    method_upper = method.upper()
    if method_upper in _SENSITIVE_HTTP_METHODS:
        marker = _sensitive_body_marker(body)
        if marker is not None:
            return _sensitive_body_block("http_request", marker)

    content: bytes | None = body.encode() if body else None

    async with httpx.AsyncClient(timeout=timeout, trust_env=_trust_env()) as client:
        response = await client.request(
            method=method_upper,
            url=url,
            headers=headers or {},
            content=content,
        )

    content_type = response.headers.get("content-type", "")
    is_text = _is_text_response_content_type(content_type)
    raw_body = response.content
    should_save = output_path is not None or len(raw_body) > _LARGE_RESPONSE_SAVE_THRESHOLD
    if should_save:
        saved_path, digest = _save_http_response_body(raw_body, output_path)
        preview = response.text[:_TEXT_BODY_LIMIT] if is_text else None
        result = {
            "status": response.status_code,
            "url": str(response.url),
            "headers": dict(response.headers),
            "content_type": content_type,
            "body": None,
            "body_base64": None,
            "body_truncated": False,
            "body_base64_truncated": False,
            "body_saved": True,
            "body_omitted_reason": "saved_to_file",
            "body_preview": preview,
            "path": str(saved_path),
            "size": len(raw_body),
            "sha256": digest,
        }
        return json.dumps(result, ensure_ascii=False, indent=2)

    capped = raw_body[:_BINARY_BODY_LIMIT]
    body_base64 = base64.b64encode(capped).decode("ascii")
    body_base64_truncated = len(raw_body) > _BINARY_BODY_LIMIT
    if is_text:
        text_body = response.text
        body = text_body[:_TEXT_BODY_LIMIT]
        body_truncated = len(text_body) > _TEXT_BODY_LIMIT
    else:
        body = None
        body_truncated = False

    result = {
        "status": response.status_code,
        "url": str(response.url),
        "headers": dict(response.headers),
        "content_type": content_type,
        "body": body,
        "body_base64": body_base64,
        "body_truncated": body_truncated,
        "body_base64_truncated": body_base64_truncated,
        "body_saved": False,
        "path": None,
        "size": len(raw_body),
        "sha256": hashlib.sha256(raw_body).hexdigest(),
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


def configure_search(
    provider_name: str,
    max_results: int = 5,
    *,
    api_key: str = "",
    proxy: str = "",
    use_env_proxy: bool = False,
    fallback_policy: str = "off",
    diagnostics: bool = False,
) -> None:
    search_runtime.configure_search(
        provider_name,
        max_results=max_results,
        api_key=api_key,
        proxy=proxy,
        use_env_proxy=use_env_proxy,
        fallback_policy=fallback_policy,
        diagnostics=diagnostics,
    )


def reset_search_runtime() -> None:
    """Restore process-wide search configuration to boot defaults."""
    search_runtime.reset_search_runtime()


def get_active_provider() -> str:
    return search_runtime.get_active_provider()


def is_search_api_key_configured(provider_name: str | None = None) -> bool:
    return search_runtime.is_search_api_key_configured(provider_name)


def get_search_proxy() -> str:
    return search_runtime.get_search_proxy()


def get_search_use_env_proxy() -> bool:
    return search_runtime.get_search_use_env_proxy()


def get_search_fallback_policy() -> str:
    return search_runtime.get_search_fallback_policy()


def get_search_diagnostics() -> bool:
    return search_runtime.get_search_diagnostics()


def _search_provider_kwargs(provider_name: str) -> dict[str, object]:
    return search_runtime.search_provider_kwargs(provider_name)


def search_runtime_status(provider_name: str | None = None) -> dict[str, Any]:
    return _search_runtime_status(provider_name)


async def run_web_search_payload(
    query: str,
    max_results: int | None = None,
    *,
    provider_name: str | None = None,
) -> dict[str, Any]:
    return await run_search_payload(
        query,
        max_results,
        provider_name=provider_name,
    )


@tool(
    name="web_search",
    description="Search the web and return results with titles, URLs, and snippets.",
    params={
        "query": {"type": "string", "description": "Search query."},
        "max_results": {
            "type": "integer",
            "description": "Maximum number of results to return.",
        },
    },
    required=["query"],
)
@sandboxed(
    kind="web.fetch",
    argv_factory=lambda a: ("web_search", str(a.get("query", "")), str(a.get("max_results", ""))),
    record_payload=False,
)
async def web_search(query: str, max_results: int | None = None) -> str:
    payload = await run_web_search_payload(query, max_results)
    tool_payload = dict(payload)
    tool_payload.pop("ok", None)
    tool_payload.pop("fallbackFrom", None)
    tool_payload.pop("errorMessage", None)
    if isinstance(tool_payload.get("error"), dict):
        tool_payload["error"] = tool_payload["error"].get("message", "")
    return json.dumps(tool_payload, ensure_ascii=False, indent=2)
