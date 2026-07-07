"""Best-effort redaction for secret-looking text before persistence or LLM replay."""

from __future__ import annotations

import re
from typing import Any

_REDACTED = "[REDACTED]"

_SECRET_TOKEN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsk-or-v1-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
)
_AUTH_BEARER_RE = re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;'\")}\]]+")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b([A-Za-z0-9_.-]+)\s*([:=])\s*([^\s,;'\")}\]]+)"
)
# Second pass: values that start with a quote are invisible to the pattern above
# (its value class excludes quotes so nested assignments inside quoted strings can
# still be redacted individually). Match whole quoted values here so
# ``password: "hunter2"`` is masked; the trailing ``["']\S*`` arm covers
# unterminated quotes.
_SECRET_QUOTED_ASSIGNMENT_RE = re.compile(
    r"(?i)\b([A-Za-z0-9_.-]+)\s*([:=])\s*"
    r"(\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[\"']\S*)"
)

_SECRET_KEY_PARTS = (
    "authorization",
    "api-key",
    "apikey",
    "api_key",
    "x-api-key",
    "password",
    "secret",
    "credential",
)
_SECRET_KEY_EXACT = {
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "bearer_token",
}


def is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in _SECRET_KEY_EXACT or any(part in lowered for part in _SECRET_KEY_PARTS)


def _is_secret_assignment_key(key: str) -> bool:
    lowered = key.lower()
    if lowered == "authorization":
        return False
    return is_secret_key(lowered) or lowered.endswith(("token", ".token", "_token", "-token"))


def _redact_assignment(match: re.Match[str]) -> str:
    key, separator = match.group(1), match.group(2)
    if not _is_secret_assignment_key(key):
        return match.group(0)
    return f"{key}{separator}{_REDACTED}"


def redact_secret_text(text: str) -> str:
    redacted = text
    redacted = _AUTH_BEARER_RE.sub(lambda m: f"{m.group(1)}{_REDACTED}", redacted)
    redacted = _SECRET_ASSIGNMENT_RE.sub(_redact_assignment, redacted)
    redacted = _SECRET_QUOTED_ASSIGNMENT_RE.sub(_redact_assignment, redacted)
    for pattern in _SECRET_TOKEN_PATTERNS:
        redacted = pattern.sub(_REDACTED, redacted)
    return redacted


def redact_secret_value(value: Any, *, key: str | None = None) -> Any:
    if key and is_secret_key(key):
        return _REDACTED
    if isinstance(value, str):
        return redact_secret_text(value)
    if isinstance(value, dict):
        return {str(k): redact_secret_value(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_secret_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_secret_value(item) for item in value)
    return value
