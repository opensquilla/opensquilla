"""Project routing model-preferences out of Dream-consolidated memory.

The user profile that Step-2 ranking scores against (``S_user``) is not an
accumulator of its own. Preferences ride the memory pipeline: a thumb is
transcribed into a preference line in ``memory/routing-preferences.md``, Dream
consolidates it into ``MEMORY.md``, and this module projects the consolidated
lines back into the ``history.positive_model_ids`` / ``negative_model_ids`` /
``feedback_count`` shape that ``ranking_router._user_score`` consumes.

Two consumers constrain the line format, and the verbs are chosen to satisfy
both at once:

* Dream's ``classify_signal`` (``memory/dream/candidates.py``) tags a line by
  keyword — ``"prefers"`` → positive, ``"do not"``/``"don't"`` → correction —
  which is how a raw thumb becomes evidence Dream will promote.
* This projection matches the same verbs to decide the list, and reads the
  model id from a backticked ``model:<id>`` marker rather than from prose. The
  marker is the load-bearing part: Dream promotes via an LLM patch that may
  reword a bullet, so the id must survive as an inline-code token the promotion
  prompt is told to keep verbatim — matching prose would silently lose the id
  the moment it was paraphrased.

Pure string functions only: no ``provider``, ``agents``, or ``memory`` imports,
so the module stays on the clean side of the ``self_learning`` layering rule and
the engine seam owns path resolution.
"""

from __future__ import annotations

import re
from typing import Any

# The scanned note a thumb is transcribed into. NOT ``MEMORY.md`` — Dream skips
# that file as a scan source and treats it as the consolidation target, so a
# preference written straight there would never become evidence.
ROUTING_PREF_FILENAME = "routing-preferences.md"

# The enum ranking reads for provenance when a real projection was produced.
PROFILE_SOURCE = "dream_memory"

# ``model:<id>`` inside inline-code backticks. Same id alphabet as the profile
# store used, so a token that would never be a model id cannot be extracted.
_MARKER_RE = re.compile(r"`model:([A-Za-z0-9._:/@-]{1,200})`")

# Substrings that make a line a preference, split by direction. Kept in sync
# with Dream's ``classify_signal`` so a transcribed line is classified the same
# way on both sides of the pipeline.
_PREFER_MARKERS = ("prefers", "prefer ")
_AVOID_MARKERS = ("do not", "don't")


def transcribe_thumb(model: str | None, rating: str) -> str | None:
    """Render one thumb as a memory bullet, or ``None`` if it says nothing.

    ``neutral`` revokes rather than asserts, and an unresolvable model cannot be
    credited — both produce ``None`` so the caller writes no line. The verb is
    chosen to land in Dream's positive/correction buckets; the id rides in a
    backticked marker so it survives consolidation.
    """
    token = (model or "").strip()
    if not token or _MARKER_RE.search(f"`model:{token}`") is None:
        return None
    if rating == "up":
        return f"- prefers routing to `model:{token}`"
    if rating == "down":
        return f"- do not route to `model:{token}`"
    return None


def _direction(line: str) -> str | None:
    lowered = line.lower()
    # Avoid wins a tie: "do not prefer X" is an avoidance, not a preference.
    if any(marker in lowered for marker in _AVOID_MARKERS):
        return "negative"
    if any(marker in lowered for marker in _PREFER_MARKERS):
        return "positive"
    return None


def project_history(memory_text: str) -> dict[str, Any]:
    """Derive the ranking-visible history from consolidated memory text.

    A model asserted in both directions lands in neither list — the same honest
    encoding ``_user_score`` would compute anyway, since a +1/-1 signal cancels
    to zero. ``feedback_count`` is the number of preference lines seen, so
    confidence ramps with how much the memory actually says about routing.
    """
    positive: set[str] = set()
    negative: set[str] = set()
    seen = 0
    for raw_line in memory_text.splitlines():
        marker = _MARKER_RE.search(raw_line)
        if marker is None:
            continue
        direction = _direction(raw_line)
        if direction is None:
            continue
        seen += 1
        model_id = marker.group(1)
        (positive if direction == "positive" else negative).add(model_id)
    contradictory = positive & negative
    positive -= contradictory
    negative -= contradictory
    return {
        "positive_model_ids": sorted(positive),
        "negative_model_ids": sorted(negative),
        "feedback_count": seen,
    }


__all__ = [
    "PROFILE_SOURCE",
    "ROUTING_PREF_FILENAME",
    "project_history",
    "transcribe_thumb",
]
