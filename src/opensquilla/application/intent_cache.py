"""Session-scoped cache of approved action intents.

The per-approval queue treats every tool invocation as a fresh request. That
means approving ``rm /tmp/x`` does nothing for a subsequent
``os.remove("/tmp/x")`` or ``Path("/tmp/x").unlink()`` — the model can paraphrase
its way past approval prompts and the user has to press y repeatedly. This
module normalizes destructive actions to a semantic key (intent kind + target)
and remembers approvals for a short window, so paraphrased retries of the same
intent proceed without another prompt.

Scope: only *delete* intents for now, since that is the bulk of user-observed
pain. Extend ``_extract_intent`` if other classes (write-outside-workspace,
network egress) need intent-level memory.
"""

from __future__ import annotations

import re
import shlex
import threading
import time
from pathlib import Path

_DEFAULT_TTL_SECONDS = 30 * 60
_ALWAYS_TTL_SECONDS = 365 * 24 * 3600  # effectively never expires within a session


def _norm_path(raw: str) -> str:
    """Best-effort absolute-path normalization.

    Leaves non-path tokens alone (so ``*`` or variable references don't get
    expanded into something wrong).
    """
    if not raw or raw.startswith(("$", "`")) or raw in {"*", "-"}:
        return raw
    try:
        return str(Path(raw).expanduser().resolve(strict=False))
    except (OSError, ValueError):
        return raw


# Regex-based single-capture extractors for Python-flavoured deletes. Each
# regex uses ``finditer`` so ``shutil.rmtree("a"); os.remove("b")`` yields
# both paths.
_PY_DELETE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bos\.(?:remove|unlink|rmdir|removedirs)\s*\(\s*[\"']([^\"']+)[\"']"),
    re.compile(r"\bshutil\.rmtree\s*\(\s*[\"']([^\"']+)[\"']"),
    re.compile(
        r"\b(?:pathlib\.)?Path\s*\(\s*[\"']([^\"']+)[\"']\s*\)\s*\.(?:unlink|rmdir)\s*\("
    ),
)

# Shell command separators that terminate a single ``rm`` invocation.
_SHELL_SEPARATORS = (";", "&&", "||", "|", "&")


def _extract_rm_targets(command: str) -> list[str]:
    """Pull every non-flag argument out of an ``rm`` invocation.

    Handles ``rm a b c``, ``rm -rf /a /b``, quoted paths, and stops at shell
    separators. Does not try to be a full shell parser — falls back to
    whitespace split on shlex errors (unbalanced quotes).
    """
    match = re.search(r"\brm\b([^\n]*)", command)
    if not match:
        return []
    tail = match.group(1)

    # Cut at the first shell separator so ``rm foo; ls bar`` doesn't pick ``ls``/``bar``.
    cut = len(tail)
    for sep in _SHELL_SEPARATORS:
        idx = tail.find(sep)
        if idx != -1 and idx < cut:
            cut = idx
    tail = tail[:cut].strip()
    if not tail:
        return []

    try:
        tokens = shlex.split(tail)
    except ValueError:
        tokens = tail.split()

    return [t for t in tokens if t and not t.startswith("-")]


def _extract_intents(command: str) -> list[tuple[str, str]]:
    """Return every recognized destructive intent, deduped and normalized.

    ``rm /a /b /c`` -> three tuples; ``shutil.rmtree('a'); os.remove('b')`` ->
    two tuples; a plain echo returns an empty list.
    """
    if not command:
        return []
    paths: list[str] = []
    paths.extend(_extract_rm_targets(command))
    for pattern in _PY_DELETE_PATTERNS:
        paths.extend(m.group(1) for m in pattern.finditer(command))

    result: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw in paths:
        intent = ("delete", _norm_path(raw))
        if intent in seen:
            continue
        seen.add(intent)
        result.append(intent)
    return result


def _extract_intent(command: str) -> tuple[str, str] | None:
    """First extracted intent, or None. Convenience for single-target callers."""
    intents = _extract_intents(command)
    return intents[0] if intents else None


class IntentApprovalCache:
    """In-memory cache keyed by ``(kind, target)`` with scope-aware expiry.

    Two scopes exist so the approval prompt's ``once`` and ``always`` mean
    what they say:

    * ``once``  — covers only paraphrased retries within the same user turn
                  (rm → os.remove within one model response). Cleared at the
                  start of every new user message via :meth:`clear_scope`.
    * ``always`` — persists for the full session TTL; re-prompts won't appear
                  for the same intent until the process restarts.
    """

    def __init__(self, default_ttl: float = _DEFAULT_TTL_SECONDS) -> None:
        self._default_ttl = default_ttl
        # intent -> (expires_monotonic, scope)
        self._entries: dict[tuple[str, str], tuple[float, str]] = {}
        self._lock = threading.Lock()

    def record(
        self, command: str, ttl: float | None = None, *, scope: str = "once"
    ) -> list[tuple[str, str]]:
        """Mark every intent extracted from *command* as approved.

        Handles multi-target commands like ``rm a b c`` — each path becomes its
        own cache entry. Returns the list of recorded intents (empty if none
        could be extracted).
        """
        intents = _extract_intents(command)
        if not intents:
            return []
        expires = time.monotonic() + (ttl if ttl is not None else self._default_ttl)
        with self._lock:
            for intent in intents:
                self._entries[intent] = (expires, scope)
        return intents

    def record_always(self, command: str) -> list[tuple[str, str]]:
        """Remember every intent in *command* for the session lifetime."""
        return self.record(command, ttl=_ALWAYS_TTL_SECONDS, scope="always")

    def check(self, command: str) -> bool:
        """Return True only when **every** extracted intent is still approved.

        Multi-target commands must have approval for *all* targets — one
        missing path means the whole command needs fresh approval.
        """
        intents = _extract_intents(command)
        if not intents:
            return False
        now = time.monotonic()
        with self._lock:
            for intent in intents:
                entry = self._entries.get(intent)
                if entry is None:
                    return False
                expires, _scope = entry
                if expires < now:
                    self._entries.pop(intent, None)
                    return False
        return True

    def forget(self, command: str) -> None:
        intents = _extract_intents(command)
        if not intents:
            return
        with self._lock:
            for intent in intents:
                self._entries.pop(intent, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def clear_scope(self, scope: str) -> None:
        """Drop every entry whose scope matches, leaving other scopes intact."""
        with self._lock:
            self._entries = {
                intent: data
                for intent, data in self._entries.items()
                if data[1] != scope
            }


_cache: IntentApprovalCache | None = None


def get_intent_cache() -> IntentApprovalCache:
    global _cache
    if _cache is None:
        _cache = IntentApprovalCache()
    return _cache


def reset_intent_cache() -> None:
    """Test hook — drop the singleton."""
    global _cache
    _cache = None
