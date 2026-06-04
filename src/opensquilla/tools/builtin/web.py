"""Web built-in tools: http_request, web_search."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlparse

import httpx

from opensquilla.sandbox.integration import (
    current_managed_network_proxy_url,
    managed_network_httpx_kwargs,
    sandboxed,
)
from opensquilla.search.types import SearchProviderError, SearchResult
from opensquilla.tools.path_policy import reject_foreign_host_path
from opensquilla.tools.registry import tool
from opensquilla.tools.types import ToolError, UnsupportedURLSchemeError, current_tool_context


def _validate_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise UnsupportedURLSchemeError(url)


_SECRET_KEY_PATTERN = (
    r"API[_-]?KEY|SECRET|TOKEN|PASSWORD|PASSWD|PRIVATE[_-]?KEY|"
    r"ACCESS[_-]?KEY|AUTHORIZATION|BEARER"
)
_SECRET_NAME_RE = re.compile(_SECRET_KEY_PATTERN, re.IGNORECASE)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?im)(?:^|[\s\"'{,])(?:\d+\t)?"
    rf"[A-Z0-9_]*(?:{_SECRET_KEY_PATTERN})[A-Z0-9_]*\s*[:=]"
)
_SECRET_JSON_KEY_RE = re.compile(
    rf"(?im)(?:^|[\s{{,])['\"][^'\"\n]{{0,80}}(?:{_SECRET_KEY_PATTERN})"
    r"[^'\"\n]{0,80}['\"]\s*:"
)
_PEM_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----",
    re.IGNORECASE,
)
_PASSWD_ENTRY_RE = re.compile(r"(?m)^(?:\d+\t)?[a-z_][a-z0-9_-]*:x?:\d+:\d+:")
_SENSITIVE_HTTP_METHODS = {"POST", "PUT", "PATCH"}
_TEXT_BODY_LIMIT = 10_000
_BINARY_BODY_LIMIT = 1_000_000
_FETCH_DIR_NAME = ".fetch"


def _sensitive_body_marker(body: str | None) -> str | None:
    if not body:
        return None
    if _PEM_PRIVATE_KEY_RE.search(body):
        return "private_key"
    if _PASSWD_ENTRY_RE.search(body):
        return "passwd_entry"
    if _SECRET_ASSIGNMENT_RE.search(body):
        return "secret_assignment"
    if _SECRET_JSON_KEY_RE.search(body):
        return "secret_json_key"
    return None


def _sensitive_url_marker(url: str) -> str | None:
    parsed = urlparse(url)
    for segment in parsed.path.split("/"):
        if _sensitive_body_marker(segment) is not None:
            return "sensitive_url_path"
    if not parsed.query:
        return None
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if _sensitive_body_marker(f"{key}={value}") is not None:
            return "sensitive_query"
    return None


def _sensitive_headers_marker(headers: dict[str, str] | None) -> str | None:
    if not headers:
        return None
    for key, value in headers.items():
        normalized_key = key.strip()
        if _SECRET_NAME_RE.search(normalized_key):
            return "sensitive_header"
        if _sensitive_body_marker(f"{normalized_key}={value}") is not None:
            return "sensitive_header"
        if normalized_key.lower() in {"authorization", "cookie", "proxy-authorization"}:
            return "sensitive_header"
    return None


def _sensitive_body_block(tool_name: str, marker: str) -> str:
    payload = {
        "status": "blocked",
        "reason": "sensitive_payload",
        "tool": tool_name,
        "sensitive_payload": marker,
        "message": (
            "Refusing to send an HTTP request body that appears to contain "
            "secrets or host account data. Remove the sensitive content or use "
            "an explicit operator-approved transfer path."
        ),
        "retryable": False,
    }
    return json.dumps(payload, ensure_ascii=False)


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
    if output_path is None:
        root = _fetch_root()
        return root / f"{digest}.bin"

    raw = output_path.strip()
    if not raw:
        raise ToolError("output_path must not be empty")

    reject_foreign_host_path(raw, platform=os.name)
    root = _fetch_root()
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
        "Make an HTTP request. Use output_path to save a response under the workspace "
        ".fetch directory; otherwise responses are returned as bounded metadata."
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
    result_budget_class="external",
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
    _validate_http_url(url)
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

    try:
        import httpx
    except ImportError:
        return "[error] httpx not installed. Run: pip install httpx"

    content: bytes | None = body.encode() if body else None

    async with httpx.AsyncClient(
        timeout=timeout,
        **managed_network_httpx_kwargs(),
    ) as client:
        response = await client.request(
            method=method_upper,
            url=url,
            headers=headers or {},
            content=content,
        )

    content_type = response.headers.get("content-type", "")
    is_text = _is_text_response_content_type(content_type)
    raw_body = response.content
    should_save = output_path is not None
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


# Active search provider name — set during boot
_active_provider: str = "duckduckgo"
_active_max_results: int = 5
_active_search_proxy: str = ""
_active_search_api_key: str = ""
_active_search_use_env_proxy: bool = False
_active_search_fallback_policy: str = "off"
_active_search_diagnostics: bool = False


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
    global _active_provider, _active_max_results, _active_search_proxy
    global _active_search_api_key, _active_search_use_env_proxy, _active_search_fallback_policy
    global _active_search_diagnostics
    _active_provider = provider_name
    _active_max_results = max_results
    _active_search_api_key = api_key.strip()
    _active_search_proxy = proxy.strip()
    _active_search_use_env_proxy = bool(use_env_proxy)
    _active_search_fallback_policy = (
        fallback_policy if fallback_policy in {"off", "network"} else "off"
    )
    _active_search_diagnostics = bool(diagnostics)


def reset_search_runtime() -> None:
    """Restore process-wide search configuration to boot defaults."""
    configure_search("duckduckgo")


def get_active_provider() -> str:
    return _active_provider


def is_search_api_key_configured(provider_name: str | None = None) -> bool:
    provider = provider_name or _active_provider
    if provider == _active_provider and _active_search_api_key:
        return True
    try:
        from opensquilla.search.registry import get_provider_spec

        spec = get_provider_spec(provider)
    except Exception:
        return False
    return bool(spec.env_key and os.environ.get(spec.env_key))


def get_search_proxy() -> str:
    return _active_search_proxy


def get_search_use_env_proxy() -> bool:
    return _active_search_use_env_proxy


def get_search_fallback_policy() -> str:
    return _active_search_fallback_policy


def get_search_diagnostics() -> bool:
    return _active_search_diagnostics


def _format_search_error(provider_name: str, exc: Exception) -> tuple[str, str]:
    error_class = type(exc).__name__
    raw = str(exc).strip()
    if raw:
        return error_class, raw
    if error_class == "ConnectTimeout":
        return (
            error_class,
            (
                f"{provider_name} search request timed out. Configure search_proxy "
                "or switch search_provider to duckduckgo."
            ),
        )
    return error_class, f"{provider_name} search failed with {error_class}."


def _search_provider_kwargs(provider_name: str) -> dict[str, object]:
    managed_proxy = current_managed_network_proxy_url()
    kwargs: dict[str, object] = {
        "proxy": managed_proxy or _active_search_proxy,
        "use_env_proxy": False if managed_proxy else _active_search_use_env_proxy,
    }
    if provider_name == "brave" and _active_search_api_key:
        kwargs["api_key"] = _active_search_api_key
    if _active_search_diagnostics or provider_name == "duckduckgo":
        kwargs["diagnostics"] = _active_search_diagnostics
    return kwargs


def _ensure_builtin_search_providers() -> None:
    import opensquilla.search.providers.brave  # noqa: F401
    import opensquilla.search.providers.duckduckgo  # noqa: F401


def _search_success_payload(payload: dict) -> dict:
    result = dict(payload)
    result["ok"] = True
    if "fallback_from" in result:
        result["fallbackFrom"] = result["fallback_from"]
    return result


def _search_failure_payload(payload: dict, *, retryable: bool = False) -> dict:
    result = dict(payload)
    message = str(result.get("error") or "")
    error_kind = str(result.get("error_kind") or "unknown")
    error_class = str(result.get("error_class") or "")
    result["ok"] = False
    result["errorMessage"] = message
    result["error"] = {
        "kind": error_kind,
        "class": error_class,
        "message": message,
        "retryable": retryable,
    }
    return result


def search_runtime_status(provider_name: str | None = None) -> dict:
    from opensquilla.search.registry import get_provider, get_provider_spec

    _ensure_builtin_search_providers()
    provider = provider_name or _active_provider
    spec = get_provider_spec(provider)
    api_key_configured = is_search_api_key_configured(provider)
    configured = (not spec.requires_api_key) or api_key_configured
    error: str | None = None
    buildable = False
    try:
        get_provider(provider, **_search_provider_kwargs(provider))
        buildable = True
    except Exception as exc:  # noqa: BLE001 - diagnostic surface
        error = str(exc)
    return {
        "activeProvider": _active_provider,
        "provider": provider,
        "configured": configured,
        "runtimeSupported": spec.runtime_supported,
        "requiresApiKey": spec.requires_api_key,
        "apiKeyConfigured": api_key_configured,
        "maxResults": _active_max_results,
        "proxyConfigured": bool(_active_search_proxy),
        "useEnvProxy": bool(_active_search_use_env_proxy),
        "fallbackPolicy": _active_search_fallback_policy,
        "diagnostics": bool(_active_search_diagnostics),
        "buildable": buildable,
        "error": error,
    }


async def run_web_search_payload(
    query: str,
    max_results: int | None = None,
    *,
    provider_name: str | None = None,
) -> dict:
    from opensquilla.search.registry import get_provider

    _ensure_builtin_search_providers()
    provider_name = provider_name or _active_provider
    marker = _sensitive_body_marker(query)
    if marker is not None:
        return _search_failure_payload(
            {
                "query": "[redacted]",
                "provider": provider_name,
                "results": [],
                "error_class": "SensitiveInput",
                "error": _sensitive_body_block("web_search", marker),
                "error_kind": "invalid_request",
            },
            retryable=False,
        )

    limit = max_results or _active_max_results
    attempts: list[dict[str, str]] | None = [] if _active_search_diagnostics else None
    try:
        provider = get_provider(
            provider_name,
            **_search_provider_kwargs(provider_name),
        )
        results = await provider.search(query, max_results=limit)
        if attempts is not None:
            attempts.append({"provider": provider_name, "status": "success"})
        return _search_success_payload(_search_payload(query, provider_name, results))
    except Exception as exc:
        classified = _classify_search_error(provider_name, exc)
        if attempts is not None:
            attempts.append(
                {
                    "provider": provider_name,
                    "status": "error",
                    "error_kind": classified.kind if classified else "unknown",
                }
            )

        should_fallback = (
            _active_search_fallback_policy == "network"
            and provider_name != "duckduckgo"
            and classified is not None
            and classified.kind in {"timeout", "network"}
        )
        if should_fallback:
            try:
                fallback_provider = get_provider(
                    "duckduckgo",
                    **_search_provider_kwargs("duckduckgo"),
                )
                results = await fallback_provider.search(query, max_results=limit)
                if attempts is not None:
                    attempts.append({"provider": "duckduckgo", "status": "success"})
                return _search_success_payload(
                    _search_payload(
                        query,
                        "duckduckgo",
                        fallback_from=provider_name,
                        attempts=attempts,
                        results=results,
                    )
                )
            except Exception as fallback_exc:
                if attempts is not None:
                    fallback_classified = _classify_search_error("duckduckgo", fallback_exc)
                    attempts.append(
                        {
                            "provider": "duckduckgo",
                            "status": "error",
                            "error_kind": (
                                fallback_classified.kind if fallback_classified else "unknown"
                            ),
                        }
                    )

        return _search_failure_payload(
            _search_error_payload(query, provider_name, exc, attempts=attempts),
            retryable=bool(classified and classified.retryable),
        )


def _classify_search_error(provider_name: str, exc: Exception) -> SearchProviderError | None:
    if isinstance(exc, SearchProviderError):
        return exc
    if isinstance(exc, httpx.TimeoutException):
        return SearchProviderError(
            provider=provider_name,
            kind="timeout",
            message=str(exc) or "Search request timed out.",
            retryable=True,
        )
    if isinstance(exc, httpx.NetworkError):
        return SearchProviderError(
            provider=provider_name,
            kind="network",
            message=str(exc) or "Search network request failed.",
            retryable=True,
        )
    return None


def _search_payload(
    query: str,
    provider_name: str,
    results: list[SearchResult],
    *,
    fallback_from: str = "",
    attempts: list[dict[str, str]] | None = None,
) -> dict:
    payload = {
        "query": query,
        "provider": provider_name,
        "results": [{"title": r.title, "url": r.url, "snippet": r.snippet} for r in results],
    }
    if fallback_from:
        payload["fallback_from"] = fallback_from
    if attempts is not None:
        payload["attempts"] = attempts
    return payload


def _search_error_payload(
    query: str,
    provider_name: str,
    exc: Exception,
    *,
    attempts: list[dict[str, str]] | None = None,
) -> dict:
    error_class, error_message = _format_search_error(provider_name, exc)
    payload: dict[str, Any] = {
        "query": query,
        "provider": provider_name,
        "results": [],
        "error_class": error_class,
        "error": error_message,
    }
    classified = _classify_search_error(provider_name, exc)
    if classified is not None:
        payload["error_kind"] = classified.kind
    if attempts is not None:
        payload["attempts"] = attempts
    return payload


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
    result_budget_class="external",
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
