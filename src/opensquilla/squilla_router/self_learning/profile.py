"""The learned user profile that Step-2 ranking scores models against.

One file, one user. OpenSquilla runs locally for a single operator, so there
is no per-agent or per-identity split: every thumb feeds the same profile, and
``S_user`` reads it on every dynamic-ranking turn.

The file is hand-editable on purpose — ``deny_models`` is the only way to say
"never route to this" — so reads invalidate on mtime rather than on write.

Privacy contract, identical to ``feedback.jsonl``: model identity tokens, enum
tokens, and integers only. No prompt text, no response text, ever. The profile
is derived from ratings, and a rating is a thumb, not a transcript.

Layering: this module knows nothing about ``opensquilla.provider``. The mock
fallback and the ranking-config defaults compose one layer up, at the engine
read seam, which keeps the provider/self_learning edge count at zero.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opensquilla.squilla_router.self_learning.store import router_data_root

PROFILE_SCHEMA_VERSION = 1
PROFILE_FILENAME = "profile.json"

# The enum ranking reads on the plan. The engine seam substitutes
# ``fallback_mock`` when there is no usable file to read.
PROFILE_SOURCE = "global_json"

# Provenance: derived by the read seam, never stored. A hand-edited file must
# not be able to name the source ranking chose or stamp a version for content
# it does not have. Stripped on write so a file that somehow carries them
# cannot keep asserting them.
_DERIVED_AT_READ = frozenset({"profile_source", "profile_version"})

# Model ids are identity tokens (``anthropic/claude-sonnet-4-5``, ``qwen3:4b``).
# Anything outside this alphabet is not a model id and never reaches the file.
_SAFE_MODEL_RE = re.compile(r"^[A-Za-z0-9._:/@-]{1,200}$")

# Outer lock: an update is read-modify-write, so concurrent thumbs would
# otherwise lose one another's counts. Reentrant because a caller folding a
# rating in holds it across its own read (see ``profile_update_lock``) and
# ``update_profile_for_rating`` takes it again underneath.
#
# Lock order is load-bearing: this one is outer, the feedback log's is inner,
# and _cache_lock below is innermost. Taking them in another order risks a
# deadlock.
_profile_lock = threading.RLock()

# path -> ((st_mtime_ns, st_size), parsed profile). An os.stat per turn costs
# microseconds against a turn that already spends seconds in LLM calls.
_cache: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}
_cache_lock = threading.Lock()


def profile_path(home: Path | None = None) -> Path:
    """The single global profile file."""

    return router_data_root(home) / PROFILE_FILENAME


@contextmanager
def profile_update_lock() -> Iterator[None]:
    """Hold the profile across a read-decide-write that spans other files.

    Folding a rating in is not one step: the caller must read the rating this
    decision already carried, append the new one, and only then fold the
    delta. ``update_profile_for_rating`` locking its own read-modify-write is
    not enough — two thumbs on one decision can both read "no previous
    rating", and both then increment. One click becomes two ratings, and the
    model can land in neither list.

    That is unrecoverable rather than merely wrong, and not because
    reconciliation is unimplemented — it is impossible. ``feedback.jsonl`` is
    pruned by ``retention_days`` while ``model_counts`` accumulates forever, so
    the log is lossy by design and can never rebuild the tally. This file is the
    system of record, not a cache of the log. Wrap the whole sequence:

        with profile_update_lock():
            previous = load_feedback_map(agent_id).get(decision_id)
            write_feedback(...)
            update_profile_for_rating(..., previous_rating=...)

    The read must stay inside the lock *and* before the append — reading after
    would return the row just written and the decrement would no-op.
    """

    with _profile_lock:
        yield


def _safe_model(model: Any) -> str | None:
    token = str(model or "").strip()
    return token if _SAFE_MODEL_RE.match(token) else None


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
    ``deny_models`` never touches the write path that would refresh it.
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


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    """Replace the file in one step so a reader never sees a partial profile."""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _derive_history(counts: dict[str, dict[str, int]], *, stamp: str) -> dict[str, Any]:
    """Recompute the ranking-visible lists from the counts.

    A model with ``up == down`` lands in neither list: ``_user_score`` computes
    ``signal`` as ``int(in_positive) - int(in_negative)``, so listing it twice
    would cancel to zero anyway — saying nothing is the honest encoding.
    """
    positive = sorted(m for m, c in counts.items() if c.get("up", 0) > c.get("down", 0))
    negative = sorted(m for m, c in counts.items() if c.get("down", 0) > c.get("up", 0))
    total = sum(c.get("up", 0) + c.get("down", 0) for c in counts.values())
    return {
        "positive_model_ids": positive,
        "negative_model_ids": negative,
        "feedback_count": total,
        "last_updated_at": stamp,
    }


def _apply(counts: dict[str, dict[str, int]], model: str, rating: str, delta: int) -> None:
    if rating not in ("up", "down"):
        return
    bucket = counts.setdefault(model, {"up": 0, "down": 0})
    bucket[rating] = max(0, int(bucket.get(rating, 0)) + delta)
    if bucket["up"] == 0 and bucket["down"] == 0:
        counts.pop(model, None)


def update_profile_for_rating(
    *,
    model: str | None,
    new_rating: str,
    previous_rating: str | None = None,
    previous_model: str | None = None,
    home: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Fold one rating into the profile as a delta, and return the new profile.

    Call under :func:`profile_update_lock`, holding it across the read of
    ``previous_rating`` as well.

    ``previous_rating`` is the effective rating this decision already carried,
    read *before* the new row was appended. Without it a thumb toggled back to
    ``neutral`` could never be revoked, and a flip from up to down would count
    twice.

    ``previous_model`` names the model that rating was credited to, and must
    be passed whenever ``previous_rating`` is a vote. An unresolvable value is
    not "the same model as ``model``": it means that rating was never folded
    in, so there is nothing to take away and the decrement is skipped. Guessing
    ``model`` instead would decrement a count some *other* decision earned,
    flipping a model the user likes into one ranking avoids.

    Returns ``None`` without touching the file when ``model`` is unresolvable —
    attribution fails closed, because crediting the wrong model is worse than
    learning nothing from this turn.
    """

    token = _safe_model(model)
    if token is None:
        return None
    previous_token = _safe_model(previous_model)
    stamp = (now or datetime.now(UTC)).strftime("%Y-%m-%d")

    with _profile_lock:
        current = load_profile(home) or {}
        raw_counts = current.get("model_counts")
        counts: dict[str, dict[str, int]] = {}
        if isinstance(raw_counts, dict):
            for key, value in raw_counts.items():
                safe_key = _safe_model(key)
                if safe_key is None or not isinstance(value, dict):
                    continue
                counts[safe_key] = {
                    "up": max(0, int(value.get("up") or 0)),
                    "down": max(0, int(value.get("down") or 0)),
                }

        if previous_rating in ("up", "down") and previous_token is not None:
            _apply(counts, previous_token, previous_rating, -1)
        _apply(counts, token, new_rating, +1)

        # No provenance in the file. ``profile_source`` and ``profile_version``
        # describe a read — which profile ranking got, and what was in it — so
        # the read seam derives them. Storing them here would put a second,
        # differently-computed value under the same name: this body hashes
        # ``model_counts``, the resolved profile hashes an overlay onto the mock
        # baseline. An operator matching a decision's version against the file
        # would find a mismatch for an unchanged profile.
        updated = {
            k: v for k, v in current.items() if k not in _DERIVED_AT_READ
        }
        updated["schema_version"] = PROFILE_SCHEMA_VERSION
        updated["model_counts"] = counts
        updated["history"] = _derive_history(counts, stamp=stamp)

        path = profile_path(home)
        _atomic_write(path, updated)
        with _cache_lock:
            _cache.pop(str(path), None)
        return updated


__all__ = [
    "PROFILE_FILENAME",
    "PROFILE_SCHEMA_VERSION",
    "PROFILE_SOURCE",
    "content_version",
    "load_profile",
    "profile_path",
    "profile_update_lock",
    "update_profile_for_rating",
]
