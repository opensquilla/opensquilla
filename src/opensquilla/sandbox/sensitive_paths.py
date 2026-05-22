"""Denylist of host paths that should never be touched without explicit operator trust.

Certain host paths are classed as sensitive (SSH keys, cloud credentials,
system configuration) and must not fall under the ordinary "requires
approval" flow. Users clicking *approve* under pressure have been a reliable
source of incidents, so these paths are hard-blocked at the tool boundary and
only the explicit ``/elevated full`` operator mode can override them.

The list is a best-effort floor — add more entries as production surface
grows. It is not a substitute for OS-level permissions.
"""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

# Operator escape hatch — set OPENSQUILLA_SENSITIVE_PATHS_DISABLED=1 to no-op
# the entire sensitive-path block layer. ONLY for trusted single-operator
# environments / E2E testing where sandbox=false + sensitive_path checks
# block valid agent commands like ``ls /etc/...``. Default off.
_DISABLED = os.environ.get(
    "OPENSQUILLA_SENSITIVE_PATHS_DISABLED", ""
).lower() in ("1", "true", "yes", "on")


# Directory prefixes whose contents must not be read/written/deleted by the agent
# in default mode. Strings starting with ``~`` expand to the current user's
# home at check time.
_SENSITIVE_PREFIXES: tuple[str, ...] = (
    "~/.ssh",
    "~/.aws",
    "~/.azure",
    "~/.config/gcloud",
    "~/.docker/config",
    "~/.kube",
    "~/.npmrc",
    "~/.pypirc",
    "~/.netrc",
    "~/.gnupg",
    "~/.password-store",
    "/etc",
    "/boot",
    "/sys",
    "/proc",
    "/dev",
    "/root",
    "/var/log",
    "/lib/systemd",
    "/usr/lib/systemd",
)

# Exact filename tails we never want mutated, regardless of parent directory.
# Covers cases like moving an id_rsa out of ~/.ssh into /tmp.
_SENSITIVE_SUFFIXES: tuple[str, ...] = (
    "/id_rsa",
    "/id_ed25519",
    "/id_ecdsa",
    "/id_dsa",
    "/known_hosts",
    "/authorized_keys",
    "/.env",
    "/.env.local",
    "/.env.development",
    "/.env.production",
    "/.env.test",
    "/.bash_history",
    "/.zsh_history",
    "/.mysql_history",
    "/.psql_history",
)

_TOKEN_EDGE_CHARS = " \t\r\n'\"`$(){}[]<>;,|&"
_ABSOLUTE_OR_TILDE_PATH_RE = re.compile(r"(?:~)?/(?:[^\s'\"`$(){}\[\]<>;,|&]+)")
_DOTENV_LITERAL_RE = re.compile(
    r"(?i)(?:^|[\s'\"`$(){}\[\]<>;,|&])"
    r"(?P<path>(?:[^\s'\"`$(){}\[\]<>;,|&]*/)?\.env(?:\.[A-Za-z0-9_.-]+)?)"
    r"(?=$|[\s'\"`$(){}\[\]<>;,|&])"
)


def _expand(path: str) -> str:
    """Expand ``~`` and resolve to absolute without requiring existence."""
    try:
        return str(Path(path).expanduser().resolve(strict=False))
    except (OSError, RuntimeError):
        return path


def _comparison_path(path: str) -> str:
    normalized = _expand(path).replace("\\", "/")
    return normalized.casefold() if os.name == "nt" else normalized


def is_sensitive_path(path: str) -> str | None:
    """Return the matched sensitive marker, or None.

    Accepts any absolute or tilde-prefixed path. Relative paths are returned
    as-is without match — callers should resolve beforehand if needed.

    Honors :data:`_DISABLED` (env var ``OPENSQUILLA_SENSITIVE_PATHS_DISABLED``).
    """
    if _DISABLED:
        return None
    if not path:
        return None
    expanded = _comparison_path(path)
    for prefix in _SENSITIVE_PREFIXES:
        normalized = _comparison_path(prefix)
        if expanded == normalized or expanded.startswith(normalized + "/"):
            return prefix
    for suffix in _SENSITIVE_SUFFIXES:
        normalized_suffix = suffix.replace("\\", "/")
        if os.name == "nt":
            normalized_suffix = normalized_suffix.casefold()
        if expanded.endswith(normalized_suffix):
            return suffix
    name = Path(expanded).name.lower()
    if name == ".env" or name.startswith(".env."):
        return "/.env*"
    return None


def sensitive_path_in_text(text: str) -> str | None:
    """Return the first sensitive path marker appearing in free-form text.

    This is intentionally conservative glue for shell/Python-code scanners.
    Structured callers should still resolve concrete paths and call
    :func:`is_sensitive_path` directly.

    Honors :data:`_DISABLED` (env var ``OPENSQUILLA_SENSITIVE_PATHS_DISABLED``).
    """
    if _DISABLED:
        return None
    if not text:
        return None

    candidates: list[str] = []
    with_context: list[tuple[str, int]] = []
    try:
        candidates.extend(shlex.split(text))
    except ValueError:
        candidates.extend(text.split())
    candidates.extend(text.split())
    with_context.extend(
        (match.group(0), match.start()) for match in _ABSOLUTE_OR_TILDE_PATH_RE.finditer(text)
    )
    with_context.extend(
        (match.group("path"), match.start("path"))
        for match in _DOTENV_LITERAL_RE.finditer(text)
    )

    for raw in candidates:
        if "://" in raw:
            continue
        candidate = raw.strip(_TOKEN_EDGE_CHARS)
        if not candidate:
            continue
        marker = is_sensitive_path(candidate)
        if marker is not None:
            return marker

    for raw, start in with_context:
        candidate = raw.strip(_TOKEN_EDGE_CHARS)
        if not candidate or candidate.startswith("//") or "://" in candidate:
            continue
        if start >= 2 and text[max(0, start - 3) : start] == "://":
            continue
        marker = is_sensitive_path(candidate)
        if marker is not None:
            return marker

    return None


def sensitive_target_in_command(command: str) -> str | None:
    """Return the first sensitive marker for any destructive target, or None.

    Multi-target commands (``rm /tmp/ok /etc/bad``) are each checked — the
    presence of a single sensitive path is enough to block the whole command.

    Honors :data:`_DISABLED` (env var ``OPENSQUILLA_SENSITIVE_PATHS_DISABLED``).
    """
    if _DISABLED:
        return None
    from opensquilla.sandbox.intent_cache import _extract_intents

    for _kind, target in _extract_intents(command):
        marker = is_sensitive_path(target)
        if marker is not None:
            return marker
    return None


def build_block_envelope(
    command: str,
    sensitive_marker: str,
    *,
    tool_name: str = "",
) -> dict[str, object]:
    """Shape of a hard-block result returned to the caller / model.

    The model-facing ``message`` is intentionally terse and tells the agent
    not to retry — ``retryable=False`` should be enough for a well-behaved
    model to stop paraphrasing the same dangerous intent.
    """
    return {
        "status": "blocked",
        "reason": "sensitive_path",
        "tool": tool_name or None,
        "command": command,
        "sensitive_path": sensitive_marker,
        "message": (
            f"Refusing to operate on sensitive host path: {sensitive_marker}. "
            "This is a hard-block regardless of user approval. If this is "
            "truly intended, the operator must set /elevated full and retry."
        ),
        "retryable": False,
    }
