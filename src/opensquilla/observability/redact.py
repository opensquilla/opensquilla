"""Text scrubbing for user-shareable diagnostic artifacts.

Belt-and-braces layer under the structured config redaction
(``gateway.config.redact_public_config``): free text (tracebacks, log lines)
can echo secrets in ``key=value`` or header form, so shareable artifacts pass
through :func:`scrub_text` before leaving the machine.
"""

from __future__ import annotations

import re
from pathlib import Path

_REDACTED = "[redacted]"

# key=value / key: value / "key": "value" where the key looks secret-shaped.
# Mirrors gateway.config._PUBLIC_SECRET_EXACT_KEYS + suffixes for free text.
_SECRET_KEY = (
    r"(?:api[_-]?key|token|secret|password|authorization|signing[_-]?secret"
    r"|app[_-]?secret|verification[_-]?token|encrypt[_-]?key|encoding[_-]?aes[_-]?key"
    r"|[a-z0-9_]*(?:_token|_secret|_password|_api_key))"
)
_ASSIGNMENT_RE = re.compile(
    rf"""(?ix)
    (?P<prefix>["']?{_SECRET_KEY}["']?\s*[=:]\s*)
    (?P<quote>["']?)
    (?P<value>(?:bearer\s+)?[^"'\s,}}\]]+)
    """,
)
_BEARER_RE = re.compile(r"(?i)(?P<prefix>bearer\s+)(?P<value>[a-z0-9._\-]+)")


def scrub_text(text: str) -> str:
    """Mask secret-shaped values and normalize the home directory to ``~``."""
    scrubbed = _ASSIGNMENT_RE.sub(
        lambda m: f"{m.group('prefix')}{m.group('quote')}{_REDACTED}", text
    )
    scrubbed = _BEARER_RE.sub(lambda m: f"{m.group('prefix')}{_REDACTED}", scrubbed)
    home = str(Path.home())
    if home and home != "/":
        scrubbed = scrubbed.replace(home, "~")
    return scrubbed
