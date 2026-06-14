"""Canonical router tier identifiers and legacy aliases."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

TEXT_TIERS: tuple[str, str, str, str] = ("c0", "c1", "c2", "c3")
DEFAULT_TEXT_TIER = "c1"
HIGHEST_TEXT_TIER = "c3"
IMAGE_TIER = "image_model"

LEGACY_TEXT_TIER_ALIASES: dict[str, str] = {
    "t0": "c0",
    "t1": "c1",
    "t2": "c2",
    "t3": "c3",
}

ROUTE_CLASS_TO_TIER: dict[str, str] = {
    "R0": "c0",
    "R1": "c1",
    "R2": "c2",
    "R3": "c3",
}
TIER_TO_ROUTE_CLASS: dict[str, str] = {tier: route for route, tier in ROUTE_CLASS_TO_TIER.items()}

# turn.metadata keys shared by the squilla_router step, meta_resolution,
# the prompt-assembler explicit-model pin (writers) and the runtime /
# harness / router_decision / stream-consumer readers. Writers normalize
# the provider with .strip().lower() before storing.
ROUTED_TIER_KEY = "routed_tier"
ROUTED_MODEL_KEY = "routed_model"
ROUTED_PROVIDER_KEY = "routed_provider"
ROUTING_SOURCE_KEY = "routing_source"
ROUTING_CONFIDENCE_KEY = "routing_confidence"
ROUTING_APPLIED_KEY = "routing_applied"


def routing_selection_effective(metadata: Mapping[str, Any]) -> bool:
    """True when the routed_* selection should bear effect on execution."""
    if str(metadata.get(ROUTING_SOURCE_KEY) or "") == "explicit_model":
        return True
    applied = metadata.get(ROUTING_APPLIED_KEY)
    return True if applied is None else bool(applied)


def normalize_text_tier(value: object) -> str | None:
    """Return the canonical text tier id for *value*, accepting legacy t0-t3."""

    if value is None:
        return None
    tier = str(value).strip().lower()
    if not tier:
        return None
    if tier in TEXT_TIERS:
        return tier
    return LEGACY_TEXT_TIER_ALIASES.get(tier)


def normalize_tier_id(value: object) -> str | None:
    """Normalize any known tier id, preserving the image tier."""

    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if raw == IMAGE_TIER:
        return IMAGE_TIER
    return normalize_text_tier(raw)


def normalize_target_id(value: object) -> str:
    """Normalize router-control target ids such as tier:t3 -> tier:c3."""

    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith("tier:"):
        tier = normalize_text_tier(raw.removeprefix("tier:"))
        return f"tier:{tier}" if tier else raw
    return raw


def normalize_tier_mapping(mapping: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a copy of a tier mapping with legacy text tier keys canonicalized."""

    if not isinstance(mapping, Mapping):
        return {}
    normalized: dict[str, Any] = {}
    for key, value in mapping.items():
        tier = normalize_tier_id(key)
        out_key = tier or str(key)
        if out_key in normalized and str(key).strip().lower() not in TEXT_TIERS:
            continue
        normalized[out_key] = value
    return normalized


def tier_index(value: object) -> int:
    """Return 0-3 for known text tiers; -1 for unknown values."""

    tier = normalize_text_tier(value)
    if tier is None:
        return -1
    try:
        return TEXT_TIERS.index(tier)
    except ValueError:
        return -1
