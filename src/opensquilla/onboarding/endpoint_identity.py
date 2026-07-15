"""Endpoint identity checks for onboarding credential reuse.

Provider ids are not credential boundaries for configurable endpoints: the
same ``custom`` provider can point at unrelated servers.  Onboarding may reuse
an existing credential only while a candidate URL remains on the same HTTP
origin (scheme, host, and effective port).  Normal provider runtime behavior
does not depend on this module.
"""

from __future__ import annotations

from urllib.parse import urlsplit

_DEFAULT_PORTS = {"http": 80, "https": 443}


def _http_origin(value: str) -> tuple[str, str, int] | None:
    raw = str(value or "").strip()
    if not raw or any(char.isspace() or ord(char) < 0x20 for char in raw):
        return None
    try:
        parsed = urlsplit(raw)
        scheme = parsed.scheme.lower()
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except (UnicodeError, ValueError):
        return None
    if scheme not in _DEFAULT_PORTS or not host or "\\" in parsed.netloc:
        return None
    return scheme, host, port if port is not None else _DEFAULT_PORTS[scheme]


def base_url_allows_credential_reuse(
    stored_base_url: str,
    candidate_base_url: str | None,
) -> bool:
    """Return whether stored credentials may follow ``candidate_base_url``.

    An omitted/blank candidate means "use the stored endpoint" and is safe.
    Exact strings are also safe even if they predate today's URL validation.
    A changed value must parse as HTTP(S) on both sides and retain the same
    scheme, hostname, and effective port.  Any ambiguous parse fails closed.
    """
    candidate = str(candidate_base_url or "").strip()
    if not candidate:
        return True
    stored = str(stored_base_url or "").strip()
    if candidate == stored:
        return True
    stored_origin = _http_origin(stored)
    candidate_origin = _http_origin(candidate)
    return stored_origin is not None and candidate_origin == stored_origin
