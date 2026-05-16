"""Reusable sensitive payload guards for tool and search adapters."""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qsl, urlparse

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


def sensitive_body_marker(body: str | None) -> str | None:
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


def sensitive_url_marker(url: str) -> str | None:
    parsed = urlparse(url)
    for segment in parsed.path.split("/"):
        if sensitive_body_marker(segment) is not None:
            return "sensitive_url_path"
    if not parsed.query:
        return None
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if sensitive_body_marker(f"{key}={value}") is not None:
            return "sensitive_query"
    return None


def sensitive_headers_marker(headers: dict[str, str] | None) -> str | None:
    if not headers:
        return None
    for key, value in headers.items():
        normalized_key = key.strip()
        if _SECRET_NAME_RE.search(normalized_key):
            return "sensitive_header"
        if sensitive_body_marker(f"{normalized_key}={value}") is not None:
            return "sensitive_header"
        if normalized_key.lower() in {"authorization", "cookie", "proxy-authorization"}:
            return "sensitive_header"
    return None


def sensitive_body_block(tool_name: str, marker: str) -> str:
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
