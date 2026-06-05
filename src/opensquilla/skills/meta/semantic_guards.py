"""Semantic retrieval guardrails for high-value meta-skills."""

from __future__ import annotations

_COMPETITIVE_INTEL_CUES = (
    "competitive",
    "competitor",
    "rival",
    "baseline",
    "account signal",
    "sales brief",
    "strategy brief",
    "竞品",
    "竞争情报",
    "对手",
    "对标",
    "基线",
    "账户信号",
    "竞对",
)


def semantic_meta_skill_allowed(skill_name: str, query: str) -> bool:
    """Return whether a semantic-only match may surface this meta-skill.

    Deterministic triggers remain the high-precision path. This guard only
    handles retrieval/embedding similarity, where a generic company-profile
    request can look close to competitive-intel because both mention companies,
    product signals, funding, or leadership.
    """

    if skill_name != "meta-competitive-intel":
        return True

    text = (query or "").lower()
    return any(cue in text for cue in _COMPETITIVE_INTEL_CUES)


__all__ = ["semantic_meta_skill_allowed"]
