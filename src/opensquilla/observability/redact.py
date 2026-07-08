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
# No blanket `_key` suffix: benign identifiers like `session_key` must stay
# readable in diagnostics.
# The suffix branch anchors its `[a-z0-9_]*` prefix with a negative lookbehind
# so it is only attempted at word-run starts: without the anchor the engine
# rescans the run once per character (quadratic — megabyte base64/hex runs in
# log tails take hours). Matches are unchanged since the star can always start
# from the run boundary.
_SECRET_KEY = (
    r"(?:api[_-]?key|token|secret[_-]?access[_-]?key|secret[_-]?key|secret|password"
    r"|authorization|signing[_-]?secret|private[_-]?key"
    r"|app[_-]?secret|verification[_-]?token|encrypt[_-]?key|encoding[_-]?aes[_-]?key"
    r"|(?<![a-z0-9_])[a-z0-9_]*(?:_token|_secret|_password|_api_key))"
)
# Common Authorization credential schemes; the scheme word plus its payload is
# masked as one value (Basic base64, opaque Token blobs, Digest params, ...).
_AUTH_SCHEME = r"(?:bearer|basic|token|digest)"
# Notes on shape:
# - Separators use [ \t]* (never \s*) so a bare trailing label like
#   "password:\n" cannot swallow the first word of the next line.
# - <quote> is an *optional group* (not a group matching an optional char) so
#   the (?(quote)...) conditional can pick the quote-aware branch: a quoted
#   value runs to the closing quote or newline, spaces included.
# - The value alternation matches the [redacted] sentinel wholly first, making
#   scrubbing idempotent (re-scrubbing an already-scrubbed artifact is a no-op
#   instead of stacking stray "]" characters).
_ASSIGNMENT_RE = re.compile(
    rf"""(?ix)
    (?P<prefix>["']?{_SECRET_KEY}["']?[ \t]*[=:][ \t]*)
    (?P<quote>["'])?
    (?P<value>
        \[redacted\](?![^"'\s,}}\]])
        |(?(quote)[^"'\n]+|(?:{_AUTH_SCHEME}[ \t]+)?[^"'\s,}}\]]+)
    )
    """,
)
# Bare bearer tokens outside key/value form. The class includes +/= so base64
# payloads are masked in full (over-masking a trailing "=" is fine; leaking a
# token suffix is not).
_BEARER_RE = re.compile(r"(?i)(?P<prefix>bearer\s+)(?P<value>[a-z0-9._\-+/=]+)")


def scrub_text(text: str) -> str:
    """Mask secret-shaped values and normalize the home directory to ``~``."""
    scrubbed = _ASSIGNMENT_RE.sub(
        lambda m: f"{m.group('prefix')}{m.group('quote') or ''}{_REDACTED}", text
    )
    scrubbed = _BEARER_RE.sub(lambda m: f"{m.group('prefix')}{_REDACTED}", scrubbed)
    home = str(Path.home())
    if home and home != "/":
        scrubbed = scrubbed.replace(home, "~")
    return scrubbed
