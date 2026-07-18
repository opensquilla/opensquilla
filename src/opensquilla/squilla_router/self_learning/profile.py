"""The hand-edited half of the profile Step-2 ranking scores models against.

One file, one user. OpenSquilla runs locally for a single operator, so there is
no per-agent or per-identity split: this file is the whole surface for the
``permission`` and ``preference`` sections, and ``S_user`` reads it on every
dynamic-ranking turn.

The file is hand-editable on purpose — ``deny_models`` is the only way to say
"never route to this", and it has no TOML key — so reads invalidate on mtime
rather than on write. Nothing writes it programmatically: the *learned* half of
the profile (``history``: which models the operator prefers or avoids) is no
longer accumulated here. It is derived at read time from Dream-consolidated
memory by :mod:`preference_projection`, so a thumb rides the memory pipeline
instead of folding into this file.

Privacy contract: model identity tokens, enum tokens, and integers only. No
prompt text, no response text, ever.

Layering: this module knows nothing about ``opensquilla.provider``. The mock
fallback and the ranking-config defaults compose one layer up, at the engine
read seam, which keeps the provider/self_learning edge count at zero.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from opensquilla.squilla_router.self_learning.store import router_data_root

PROFILE_SCHEMA_VERSION = 1
PROFILE_FILENAME = "profile.json"

# path -> ((st_mtime_ns, st_size), parsed profile). An os.stat per turn costs
# microseconds against a turn that already spends seconds in LLM calls.
_cache: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}
_cache_lock = threading.Lock()


def profile_path(home: Path | None = None) -> Path:
    """The single global profile file."""

    return router_data_root(home) / PROFILE_FILENAME


def content_version(payload: Mapping[str, Any]) -> str:
    """A hash of the profile body, so the version changes exactly when it does.

    A constant here would be worse than no version at all: every learned
    decision would log the same id, and a routing decision could not be traced
    back to the profile that produced it.

    ``profile_version`` is excluded — it is the output — and ``last_updated_at``
    with it, so re-rating the same way twice is recognisably the same profile
    rather than a new one that happens to route identically.

    Public because the read seam must hash the profile it actually ranked with,
    not this file's stored field: the file is hand-editable, and an edit to
    ``deny_models`` never touches a write path that would refresh it.
    """

    body = {k: v for k, v in payload.items() if k != "profile_version"}
    history = body.get("history")
    if isinstance(history, Mapping):
        body["history"] = {k: v for k, v in history.items() if k != "last_updated_at"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _read_raw(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def load_profile(home: Path | None = None) -> dict[str, Any] | None:
    """The stored profile, or ``None`` when there isn't a usable one.

    ``None`` covers every failure — absent file, malformed JSON, wrong shape —
    so the caller can degrade to the mock baseline. Never raises: a broken
    profile must not fail a turn.
    """

    path = profile_path(home)
    try:
        stat = path.stat()
    except OSError:
        return None
    key = str(path)
    stamp = (stat.st_mtime_ns, stat.st_size)
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and hit[0] == stamp:
            return json.loads(json.dumps(hit[1]))
    data = _read_raw(path)
    if data is None:
        return None
    with _cache_lock:
        _cache[key] = (stamp, data)
    return json.loads(json.dumps(data))


__all__ = [
    "PROFILE_FILENAME",
    "PROFILE_SCHEMA_VERSION",
    "content_version",
    "load_profile",
    "profile_path",
]
