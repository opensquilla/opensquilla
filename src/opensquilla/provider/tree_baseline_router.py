"""Frozen local-tree ensemble baseline used for comparative evaluation.

This module preserves the model-selection behavior that ``router_dynamic``
used before the profile-driven Step2 ranker replaced it. SquillaRouter's local
LightGBM/ONNX decision supplies the tier and anchor model; this selector only
fills the remaining proposer slots and the aggregator slot.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any

TREE_BASELINE_SELECTION_MODE = "router_tree_baseline"
TREE_BASELINE_CONFIG_SCHEMA_VERSION = "router-tree-baseline-config-v1"

_SCORE_COMPONENTS = frozenset({"quality", "affinity", "diversity", "cost", "role"})
_ROLE_FEATURES = frozenset(
    {
        "adjacent",
        "contrast",
        "cost_latency",
        "diversity",
        "quality",
        "relative_tier_target",
        "tier_target",
    }
)
_DIVERSITY_DIMENSIONS = ("family", "vendor", "provider", "tier", "architecture")
_CONFIG_KEYS = frozenset(
    {
        "aggregator_slots",
        "algorithm_version",
        "config_version",
        "default_model_options",
        "default_provider",
        "default_tier",
        "model_catalog",
        "schema_version",
        "scoring",
        "slot_templates",
        "tiers",
        "trace",
    }
)
_SCORING_KEYS = frozenset(
    {
        "adjacent_scores",
        "contrast",
        "default_selected_penalty",
        "default_thinking",
        "diversity",
        "family_name_parts",
        "role_match",
        "router_affinity",
        "selected_penalties",
        "slot_weights",
        "tier_cost_latency_priors",
        "tier_distance_divisor",
        "tier_quality_priors",
        "weight_sum_tolerance",
    }
)
_TRACE_KEYS = frozenset(
    {"candidate_decimal_places", "score_decimal_places", "top_candidates"}
)
_MODEL_PROFILE_REQUIRED_KEYS = frozenset(
    {"architecture", "cost_latency", "family", "quality", "tier", "vendor"}
)
_MODEL_PROFILE_OPTIONAL_KEYS = frozenset({"supports_vision"})


class TreeBaselineError(ValueError):
    """The frozen tree-baseline config or candidate pool is unusable."""


class _ValidatedTreeBaselineConfig(dict[str, Any]):
    pass


@dataclass(frozen=True)
class TreeBaselineCandidate:
    provider: str
    model: str
    tier_prior: str
    quality_prior: float
    cost_latency_prior: float
    family: str
    vendor: str
    architecture: str
    thinking: str | None
    supports_vision: bool
    source: str
    pool_index: int

    @property
    def identity(self) -> tuple[str, str]:
        return self.provider, self.model


@dataclass(frozen=True)
class TreeBaselineSlotSelection:
    slot: str
    candidate: TreeBaselineCandidate


@dataclass(frozen=True)
class TreeBaselineDecision:
    routed_tier: str
    routing_confidence: float
    proposers: tuple[TreeBaselineSlotSelection, ...]
    aggregator: TreeBaselineSlotSelection
    trace: dict[str, Any]


def _canonical_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _mapping(value: Mapping[str, Any], *path: str) -> Mapping[str, Any]:
    current: Any = value
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            raise TreeBaselineError(f"router_tree_baseline config lacks {'.'.join(path)}")
        current = current[key]
    if not isinstance(current, Mapping):
        raise TreeBaselineError(f"router_tree_baseline config {'.'.join(path)} must be an object")
    return current


def _number(value: Mapping[str, Any], *path: str) -> float:
    current: Any = value
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            raise TreeBaselineError(f"router_tree_baseline config lacks {'.'.join(path)}")
        current = current[key]
    if isinstance(current, bool) or not isinstance(current, (int, float)):
        raise TreeBaselineError(f"router_tree_baseline config {'.'.join(path)} must be numeric")
    result = float(current)
    if not math.isfinite(result):
        raise TreeBaselineError(f"router_tree_baseline config {'.'.join(path)} must be finite")
    return result


def _integer(value: Mapping[str, Any], *path: str) -> int:
    result = _number(value, *path)
    if not result.is_integer():
        raise TreeBaselineError(f"router_tree_baseline config {'.'.join(path)} must be an integer")
    return int(result)


def _string(value: Mapping[str, Any], *path: str) -> str:
    current: Any = value
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            raise TreeBaselineError(f"router_tree_baseline config lacks {'.'.join(path)}")
        current = current[key]
    if not isinstance(current, str) or not current.strip():
        raise TreeBaselineError(
            f"router_tree_baseline config {'.'.join(path)} must be a non-empty string"
        )
    return current.strip()


def _string_list(value: Mapping[str, Any], *path: str) -> list[str]:
    current: Any = value
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            raise TreeBaselineError(f"router_tree_baseline config lacks {'.'.join(path)}")
        current = current[key]
    if (
        not isinstance(current, Sequence)
        or isinstance(current, (str, bytes))
        or any(not isinstance(item, str) or not item.strip() for item in current)
    ):
        raise TreeBaselineError(
            f"router_tree_baseline config {'.'.join(path)} must be a string list"
        )
    return [item.strip() for item in current]


def _integer_list(value: Mapping[str, Any], *path: str) -> list[int]:
    current: Any = value
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            raise TreeBaselineError(f"router_tree_baseline config lacks {'.'.join(path)}")
        current = current[key]
    if (
        not isinstance(current, Sequence)
        or isinstance(current, (str, bytes))
        or not current
        or any(isinstance(item, bool) or not isinstance(item, int) for item in current)
    ):
        raise TreeBaselineError(
            f"router_tree_baseline config {'.'.join(path)} must be a non-empty integer list"
        )
    return list(current)


def _validate_unit_interval(value: float, dotted: str) -> None:
    if not 0.0 <= value <= 1.0:
        raise TreeBaselineError(f"router_tree_baseline config {dotted} must be between 0 and 1")


def _validate_tree_baseline_config(
    payload: Mapping[str, Any],
) -> _ValidatedTreeBaselineConfig:
    if not isinstance(payload, Mapping):
        raise TreeBaselineError("router_tree_baseline config must be an object")
    config = copy.deepcopy(dict(payload))
    if set(config) != _CONFIG_KEYS:
        raise TreeBaselineError("router_tree_baseline config has missing or unknown fields")
    if _string(config, "schema_version") != TREE_BASELINE_CONFIG_SCHEMA_VERSION:
        raise TreeBaselineError("router_tree_baseline config schema_version is unsupported")
    _string(config, "config_version")
    _string(config, "algorithm_version")
    _string(config, "default_provider")
    default_model_options = _string_list(config, "default_model_options")
    if len(set(default_model_options)) != len(default_model_options):
        raise TreeBaselineError(
            "router_tree_baseline default_model_options cannot contain duplicates"
        )
    tiers = _string_list(config, "tiers")
    if tiers != ["c0", "c1", "c2", "c3"]:
        raise TreeBaselineError("router_tree_baseline tiers must be c0 through c3")
    if _string(config, "default_tier") not in tiers:
        raise TreeBaselineError("router_tree_baseline default_tier is invalid")

    templates = _mapping(config, "slot_templates")
    aggregators = _mapping(config, "aggregator_slots")
    if set(templates) != set(tiers) or set(aggregators) != set(tiers):
        raise TreeBaselineError("router_tree_baseline slot templates must cover every tier")
    proposer_slots: set[str] = set()
    for tier in tiers:
        slots = _string_list(config, "slot_templates", tier)
        if not slots or slots[0] != "anchor" or len(set(slots)) != len(slots):
            raise TreeBaselineError(
                f"router_tree_baseline slot_templates.{tier} must start with anchor"
            )
        proposer_slots.update(slots[1:])
    aggregator_slots = {_string(config, "aggregator_slots", tier) for tier in tiers}
    scored_slots = proposer_slots | aggregator_slots

    scoring = _mapping(config, "scoring")
    if set(scoring) != _SCORING_KEYS:
        raise TreeBaselineError("router_tree_baseline scoring has missing or unknown fields")
    tolerance = _number(config, "scoring", "weight_sum_tolerance")
    if tolerance < 0.0:
        raise TreeBaselineError(
            "router_tree_baseline scoring.weight_sum_tolerance cannot be negative"
        )
    if _number(config, "scoring", "tier_distance_divisor") <= 0.0:
        raise TreeBaselineError(
            "router_tree_baseline scoring.tier_distance_divisor must be positive"
        )
    if _integer(config, "scoring", "family_name_parts") <= 0:
        raise TreeBaselineError("router_tree_baseline scoring.family_name_parts must be positive")
    _string(config, "scoring", "default_thinking")
    _validate_unit_interval(
        _number(config, "scoring", "default_selected_penalty"),
        "scoring.default_selected_penalty",
    )

    slot_weights = _mapping(scoring, "slot_weights")
    penalties = _mapping(scoring, "selected_penalties")
    role_match = _mapping(scoring, "role_match")
    if set(slot_weights) != scored_slots or set(penalties) != scored_slots:
        raise TreeBaselineError("router_tree_baseline scoring slots do not match the templates")
    if set(role_match) != scored_slots:
        raise TreeBaselineError("router_tree_baseline role_match slots do not match the templates")
    for slot in sorted(scored_slots):
        weights = _mapping(slot_weights, slot)
        if set(weights) != _SCORE_COMPONENTS:
            raise TreeBaselineError(
                f"router_tree_baseline slot_weights.{slot} has invalid components"
            )
        values = [_number(slot_weights, slot, component) for component in _SCORE_COMPONENTS]
        if any(value < 0.0 for value in values) or abs(sum(values) - 1.0) > tolerance:
            raise TreeBaselineError(
                f"router_tree_baseline slot_weights.{slot} must be non-negative and sum to 1"
            )
        _validate_unit_interval(_number(penalties, slot), f"scoring.selected_penalties.{slot}")

        features = _mapping(role_match, slot)
        if not features or not set(features).issubset(_ROLE_FEATURES):
            raise TreeBaselineError(f"router_tree_baseline role_match.{slot} has invalid features")
        feature_weight_sum = 0.0
        for feature, raw_spec in features.items():
            if not isinstance(raw_spec, Mapping):
                raise TreeBaselineError(
                    f"router_tree_baseline role_match.{slot}.{feature} must be an object"
                )
            weight = _number(role_match, slot, str(feature), "weight")
            if weight < 0.0:
                raise TreeBaselineError(
                    f"router_tree_baseline role_match.{slot}.{feature}.weight cannot be negative"
                )
            feature_weight_sum += weight
            if feature == "tier_target":
                if set(raw_spec) != {"weight", "targets"}:
                    raise TreeBaselineError(
                        f"router_tree_baseline role_match.{slot}.tier_target has invalid fields"
                    )
                targets = _integer_list(role_match, slot, str(feature), "targets")
                if any(target < 0 or target >= len(tiers) for target in targets):
                    raise TreeBaselineError(
                        f"router_tree_baseline role_match.{slot}.tier_target is out of range"
                    )
            elif feature == "relative_tier_target":
                if set(raw_spec) != {"weight", "offsets"}:
                    raise TreeBaselineError(
                        "router_tree_baseline "
                        f"role_match.{slot}.relative_tier_target has invalid fields"
                    )
                _integer_list(role_match, slot, str(feature), "offsets")
            elif set(raw_spec) != {"weight"}:
                raise TreeBaselineError(
                    f"router_tree_baseline role_match.{slot}.{feature} has invalid fields"
                )
        if abs(feature_weight_sum - 1.0) > tolerance:
            raise TreeBaselineError(f"router_tree_baseline role_match.{slot} weights must sum to 1")

    for prior_name in ("tier_quality_priors", "tier_cost_latency_priors"):
        priors = _mapping(scoring, prior_name)
        if set(priors) != set(tiers):
            raise TreeBaselineError(
                f"router_tree_baseline scoring.{prior_name} must cover every tier"
            )
        for tier in tiers:
            _validate_unit_interval(_number(priors, tier), f"scoring.{prior_name}.{tier}")

    contrast = _mapping(scoring, "contrast")
    if set(contrast) != {"different_scores", "same_scores", "weights"}:
        raise TreeBaselineError("router_tree_baseline contrast has invalid fields")
    contrast_weights = _mapping(contrast, "weights")
    if set(contrast_weights) != {"family", "vendor", "provider"}:
        raise TreeBaselineError("router_tree_baseline contrast weights are invalid")
    contrast_weight_values = [
        _number(contrast_weights, dimension) for dimension in contrast_weights
    ]
    if (
        any(value < 0.0 for value in contrast_weight_values)
        or abs(sum(contrast_weight_values) - 1.0) > tolerance
    ):
        raise TreeBaselineError(
            "router_tree_baseline contrast weights must be non-negative and sum to 1"
        )
    for score_name in ("different_scores", "same_scores"):
        scores = _mapping(contrast, score_name)
        if set(scores) != set(contrast_weights):
            raise TreeBaselineError(f"router_tree_baseline contrast.{score_name} is invalid")
        for dimension in scores:
            _validate_unit_interval(
                _number(scores, dimension),
                f"scoring.contrast.{score_name}.{dimension}",
            )

    diversity = _mapping(scoring, "diversity")
    _validate_unit_interval(
        _number(diversity, "empty_selected_score"),
        "scoring.diversity.empty_selected_score",
    )
    if set(diversity) != {"empty_selected_score", *_DIVERSITY_DIMENSIONS}:
        raise TreeBaselineError("router_tree_baseline diversity dimensions are invalid")
    for dimension in _DIVERSITY_DIMENSIONS:
        diversity_values = _mapping(diversity, dimension)
        if set(diversity_values) != {"new", "existing"}:
            raise TreeBaselineError(f"router_tree_baseline diversity.{dimension} is invalid")
        for state in diversity_values:
            _validate_unit_interval(
                _number(diversity_values, state),
                f"scoring.diversity.{dimension}.{state}",
            )

    adjacent_scores = _mapping(scoring, "adjacent_scores")
    if set(adjacent_scores) != {"distance_one", "distance_zero", "other"}:
        raise TreeBaselineError("router_tree_baseline adjacent_scores has invalid fields")
    for key in adjacent_scores:
        _validate_unit_interval(
            _number(adjacent_scores, key),
            f"scoring.adjacent_scores.{key}",
        )
    router_affinity = _mapping(scoring, "router_affinity")
    if set(router_affinity) != {
        "confidence_penalty_scale",
        "low_confidence_penalty_scale",
    }:
        raise TreeBaselineError("router_tree_baseline router_affinity has invalid fields")
    for key in router_affinity:
        _validate_unit_interval(
            _number(router_affinity, key),
            f"scoring.router_affinity.{key}",
        )

    trace = _mapping(config, "trace")
    if set(trace) != _TRACE_KEYS:
        raise TreeBaselineError("router_tree_baseline trace has missing or unknown fields")
    if _integer(trace, "top_candidates") <= 0:
        raise TreeBaselineError("router_tree_baseline trace.top_candidates must be positive")
    for key in ("candidate_decimal_places", "score_decimal_places"):
        if _integer(trace, key) < 0:
            raise TreeBaselineError(f"router_tree_baseline trace.{key} cannot be negative")

    catalog = _mapping(config, "model_catalog")
    normalized_model_ids: set[str] = set()
    for model_id, raw_profile in catalog.items():
        if (
            not isinstance(model_id, str)
            or not model_id.strip()
            or not isinstance(raw_profile, Mapping)
        ):
            raise TreeBaselineError("router_tree_baseline model_catalog is malformed")
        normalized_model_id = model_id.strip().lower()
        if normalized_model_id != model_id or normalized_model_id in normalized_model_ids:
            raise TreeBaselineError(
                "router_tree_baseline model_catalog ids must be unique normalized strings"
            )
        normalized_model_ids.add(normalized_model_id)
        profile_keys = set(raw_profile)
        if not _MODEL_PROFILE_REQUIRED_KEYS.issubset(profile_keys) or not profile_keys.issubset(
            _MODEL_PROFILE_REQUIRED_KEYS | _MODEL_PROFILE_OPTIONAL_KEYS
        ):
            raise TreeBaselineError(
                f"router_tree_baseline model_catalog.{model_id} has invalid fields"
            )
        if _string(catalog, model_id, "tier") not in tiers:
            raise TreeBaselineError(
                f"router_tree_baseline model_catalog.{model_id}.tier is invalid"
            )
        for key in ("quality", "cost_latency"):
            _validate_unit_interval(
                _number(catalog, model_id, key),
                f"model_catalog.{model_id}.{key}",
            )
        for key in ("family", "vendor", "architecture"):
            _string(catalog, model_id, key)
        if "supports_vision" in raw_profile and not isinstance(
            raw_profile["supports_vision"], bool
        ):
            raise TreeBaselineError(
                f"router_tree_baseline model_catalog.{model_id}.supports_vision must be boolean"
            )
    missing_default_models = [
        model for model in default_model_options if model.lower() not in catalog
    ]
    if missing_default_models:
        raise TreeBaselineError(
            "router_tree_baseline default_model_options must exist in model_catalog"
        )
    return _ValidatedTreeBaselineConfig(config)


@cache
def _packaged_tree_baseline_config() -> _ValidatedTreeBaselineConfig:
    try:
        path = resources.files("opensquilla.provider").joinpath("router_tree_baseline_config.json")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - surfaced as a routing error
        raise TreeBaselineError("router_tree_baseline config unavailable") from exc
    return _validate_tree_baseline_config(payload)


def load_tree_baseline_config() -> dict[str, Any]:
    """Return an isolated copy of the frozen baseline parameters."""

    return copy.deepcopy(dict(_packaged_tree_baseline_config()))


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _normalize_tier(value: object, config: Mapping[str, Any]) -> str | None:
    raw = str(value or "").strip().lower()
    tiers = _string_list(config, "tiers")
    if raw in tiers:
        return raw
    if raw.startswith("t") and raw[1:].isdigit():
        converted = f"c{int(raw[1:])}"
        if converted in tiers:
            return converted
    return None


def _tier_index(value: object, config: Mapping[str, Any]) -> int:
    tiers = _string_list(config, "tiers")
    default_tier = _string(config, "default_tier")
    tier = _normalize_tier(value, config) or default_tier
    return tiers.index(tier)


def _tier_target_score(
    tier: str,
    targets: Sequence[int],
    config: Mapping[str, Any],
) -> float:
    if not targets:
        return 0.0
    distance = min(abs(_tier_index(tier, config) - target) for target in targets)
    divisor = _number(config, "scoring", "tier_distance_divisor")
    return _clamp(1.0 - (distance / divisor))


def _coerce_thinking(value: object, config: Mapping[str, Any]) -> str | None:
    raw = str(value or "").strip().lower()
    if not raw:
        return _string(config, "scoring", "default_thinking")
    if raw in {"none", "false", "0"}:
        return "off"
    return raw


def _split_model_identity(
    provider: str,
    model: str,
    config: Mapping[str, Any],
) -> tuple[str, str, str]:
    model_lower = model.strip().lower()
    if "/" in model_lower:
        vendor, name = model_lower.split("/", 1)
    else:
        vendor, name = provider.strip().lower() or "unknown", model_lower
    pieces = name.replace("_", "-").split("-")
    name_parts = _integer(config, "scoring", "family_name_parts")
    family = "-".join(pieces[:name_parts]) if pieces else name or vendor
    architecture = pieces[0] if pieces and pieces[0] else family
    return vendor or "unknown", family or vendor or "unknown", architecture or "unknown"


def _candidate(
    *,
    provider: str,
    model: str,
    tier_hint: object,
    thinking: object,
    source: str,
    pool_index: int,
    config: Mapping[str, Any],
) -> TreeBaselineCandidate:
    provider_normalized = provider.strip().lower() or _string(config, "default_provider")
    model_normalized = model.strip()
    catalog = _mapping(config, "model_catalog")
    raw_profile = catalog.get(model_normalized.lower())
    profile = raw_profile if isinstance(raw_profile, Mapping) else {}
    tier = (
        _normalize_tier(tier_hint, config)
        or _normalize_tier(profile.get("tier"), config)
        or _string(config, "default_tier")
    )
    vendor, family, architecture = _split_model_identity(
        provider_normalized, model_normalized, config
    )
    quality = float(
        profile.get(
            "quality",
            _number(config, "scoring", "tier_quality_priors", tier),
        )
    )
    cost_latency = float(
        profile.get(
            "cost_latency",
            _number(config, "scoring", "tier_cost_latency_priors", tier),
        )
    )
    return TreeBaselineCandidate(
        provider=provider_normalized,
        model=model_normalized,
        tier_prior=tier,
        quality_prior=quality,
        cost_latency_prior=cost_latency,
        family=str(profile.get("family") or family),
        vendor=str(profile.get("vendor") or vendor),
        architecture=str(profile.get("architecture") or architecture),
        thinking=_coerce_thinking(thinking, config),
        supports_vision=bool(profile.get("supports_vision", False)),
        source=source,
        pool_index=pool_index,
    )


def _candidate_pool(
    *,
    anchor_provider: str,
    anchor_model: str,
    routed_tier: str,
    structured_candidates: Sequence[Mapping[str, Any]],
    model_options: Sequence[str],
    router_tiers: Mapping[str, Any],
    config: Mapping[str, Any],
) -> list[TreeBaselineCandidate]:
    pool: list[TreeBaselineCandidate] = []
    seen: set[tuple[str, str]] = set()

    def add(item: TreeBaselineCandidate) -> None:
        if not item.model or item.identity in seen:
            return
        seen.add(item.identity)
        pool.append(item)

    add(
        _candidate(
            provider=anchor_provider,
            model=anchor_model,
            tier_hint=routed_tier,
            thinking=None,
            source="router_anchor",
            pool_index=len(pool),
            config=config,
        )
    )
    for entry in structured_candidates:
        if entry.get("enabled", True) is False:
            continue
        provider = str(entry.get("provider") or "").strip()
        model = str(entry.get("model") or "").strip()
        if not provider or not model:
            continue
        add(
            _candidate(
                provider=provider,
                model=model,
                tier_hint=None,
                thinking=None,
                source=str(entry.get("source") or "custom"),
                pool_index=len(pool),
                config=config,
            )
        )

    for raw_model in model_options:
        model = str(raw_model or "").strip()
        if not model:
            continue
        provider = _string(config, "default_provider") if "/" in model else anchor_provider
        add(
            _candidate(
                provider=provider,
                model=model,
                tier_hint=None,
                thinking=None,
                source="model_options",
                pool_index=len(pool),
                config=config,
            )
        )

    for tier_name, raw_tier in router_tiers.items():
        if not isinstance(raw_tier, Mapping):
            continue
        model = str(raw_tier.get("model") or "").strip()
        if not model:
            continue
        add(
            _candidate(
                provider=str(raw_tier.get("provider") or anchor_provider),
                model=model,
                tier_hint=tier_name,
                thinking=raw_tier.get("thinking_level"),
                source=f"router_tier:{tier_name}",
                pool_index=len(pool),
                config=config,
            )
        )
    return pool


def _router_affinity_score(
    candidate: TreeBaselineCandidate,
    *,
    routed_tier: str,
    routing_confidence: float,
    config: Mapping[str, Any],
) -> float:
    distance = abs(_tier_index(candidate.tier_prior, config) - _tier_index(routed_tier, config))
    confidence = _clamp(routing_confidence)
    penalty_scale = (
        _number(
            config,
            "scoring",
            "router_affinity",
            "low_confidence_penalty_scale",
        )
        + _number(
            config,
            "scoring",
            "router_affinity",
            "confidence_penalty_scale",
        )
        * confidence
    )
    divisor = _number(config, "scoring", "tier_distance_divisor")
    return _clamp(1.0 - ((distance / divisor) * penalty_scale))


def _contrast_score(
    candidate: TreeBaselineCandidate,
    anchor: TreeBaselineCandidate,
    config: Mapping[str, Any],
) -> float:
    contrast = _mapping(config, "scoring", "contrast")
    weights = _mapping(contrast, "weights")
    different = _mapping(contrast, "different_scores")
    same = _mapping(contrast, "same_scores")
    return sum(
        _number(weights, dimension)
        * _number(
            different if getattr(candidate, dimension) != getattr(anchor, dimension) else same,
            dimension,
        )
        for dimension in ("family", "vendor", "provider")
    )


def _diversity_score(
    candidate: TreeBaselineCandidate,
    selected: Sequence[TreeBaselineCandidate],
    config: Mapping[str, Any],
) -> float:
    diversity = _mapping(config, "scoring", "diversity")
    if not selected:
        return _number(diversity, "empty_selected_score")
    attributes = {
        "family": "family",
        "vendor": "vendor",
        "provider": "provider",
        "tier": "tier_prior",
        "architecture": "architecture",
    }
    score = 0.0
    for dimension, attribute in attributes.items():
        represented = {getattr(item, attribute) for item in selected}
        state = "existing" if getattr(candidate, attribute) in represented else "new"
        score += _number(diversity, dimension, state)
    return score


def _role_match_score(
    slot: str,
    candidate: TreeBaselineCandidate,
    *,
    routed_tier: str,
    anchor: TreeBaselineCandidate,
    selected: Sequence[TreeBaselineCandidate],
    config: Mapping[str, Any],
) -> float:
    role = _mapping(config, "scoring", "role_match", slot)
    routed_index = _tier_index(routed_tier, config)
    candidate_index = _tier_index(candidate.tier_prior, config)
    distance = abs(candidate_index - routed_index)
    adjacent_key = (
        "distance_one" if distance == 1 else "distance_zero" if distance == 0 else "other"
    )
    values = {
        "adjacent": _number(config, "scoring", "adjacent_scores", adjacent_key),
        "contrast": _contrast_score(candidate, anchor, config),
        "cost_latency": candidate.cost_latency_prior,
        "diversity": _diversity_score(candidate, selected, config),
        "quality": candidate.quality_prior,
    }
    tiers = _string_list(config, "tiers")
    score = 0.0
    for feature, raw_spec in role.items():
        spec = raw_spec if isinstance(raw_spec, Mapping) else {}
        weight = float(spec["weight"])
        if feature == "tier_target":
            targets = [int(value) for value in spec.get("targets") or []]
            value = _tier_target_score(candidate.tier_prior, targets, config)
        elif feature == "relative_tier_target":
            offsets = [int(value) for value in spec.get("offsets") or []]
            targets = [max(0, min(len(tiers) - 1, routed_index + offset)) for offset in offsets]
            value = _tier_target_score(candidate.tier_prior, targets, config)
        else:
            value = values[feature]
        score += weight * value
    return score


def _score_candidate(
    candidate: TreeBaselineCandidate,
    *,
    slot: str,
    routed_tier: str,
    routing_confidence: float,
    anchor: TreeBaselineCandidate,
    selected: Sequence[TreeBaselineCandidate],
    selected_counts: Mapping[tuple[str, str], int],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    weights = _mapping(config, "scoring", "slot_weights", slot)
    affinity = _router_affinity_score(
        candidate,
        routed_tier=routed_tier,
        routing_confidence=routing_confidence,
        config=config,
    )
    diversity = _diversity_score(candidate, selected, config)
    role_match = _role_match_score(
        slot,
        candidate,
        routed_tier=routed_tier,
        anchor=anchor,
        selected=selected,
        config=config,
    )
    duplicate_count = int(selected_counts.get(candidate.identity, 0))
    penalties = _mapping(config, "scoring", "selected_penalties")
    penalty_rate = float(
        penalties.get(
            slot,
            _number(config, "scoring", "default_selected_penalty"),
        )
    )
    duplicate_penalty = penalty_rate * duplicate_count
    components = {
        "quality": candidate.quality_prior,
        "router_affinity": affinity,
        "diversity": diversity,
        "cost_latency": candidate.cost_latency_prior,
        "role_match": role_match,
    }
    score = (
        _number(weights, "quality") * components["quality"]
        + _number(weights, "affinity") * components["router_affinity"]
        + _number(weights, "diversity") * components["diversity"]
        + _number(weights, "cost") * components["cost_latency"]
        + _number(weights, "role") * components["role_match"]
        - duplicate_penalty
    )
    return {
        "candidate": candidate,
        "score": score,
        "duplicate_count": duplicate_count,
        "duplicate_penalty": duplicate_penalty,
        "components": components,
        "weights": dict(weights),
    }


def _candidate_trace(
    candidate: TreeBaselineCandidate,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    places = _integer(config, "trace", "candidate_decimal_places")
    return {
        "provider": candidate.provider,
        "model": candidate.model,
        "tier_prior": candidate.tier_prior,
        "quality_prior": round(candidate.quality_prior, places),
        "cost_latency_prior": round(candidate.cost_latency_prior, places),
        "family": candidate.family,
        "vendor": candidate.vendor,
        "architecture": candidate.architecture,
        "source": candidate.source,
    }


def _score_trace(row: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    places = _integer(config, "trace", "score_decimal_places")
    candidate = row["candidate"]
    return {
        "selected": _candidate_trace(candidate, config),
        "score": round(float(row["score"]), places),
        "duplicate_count": int(row.get("duplicate_count") or 0),
        "duplicate_penalty": round(float(row.get("duplicate_penalty") or 0.0), places),
        "components": {
            key: round(float(value), places)
            for key, value in dict(row.get("components") or {}).items()
        },
        "weights": {
            key: round(float(value), places)
            for key, value in dict(row.get("weights") or {}).items()
        },
    }


def _select_candidate(
    *,
    slot: str,
    pool: Sequence[TreeBaselineCandidate],
    routed_tier: str,
    routing_confidence: float,
    anchor: TreeBaselineCandidate,
    selected: Sequence[TreeBaselineCandidate],
    selected_counts: Mapping[tuple[str, str], int],
    config: Mapping[str, Any],
) -> tuple[TreeBaselineCandidate, dict[str, Any]]:
    scored = [
        _score_candidate(
            candidate,
            slot=slot,
            routed_tier=routed_tier,
            routing_confidence=routing_confidence,
            anchor=anchor,
            selected=selected,
            selected_counts=selected_counts,
            config=config,
        )
        for candidate in pool
    ]
    if not scored:
        raise TreeBaselineError("router_tree_baseline candidate pool is empty")
    scored.sort(
        key=lambda row: (
            float(row["score"]),
            row["candidate"].quality_prior,
            row["candidate"].cost_latency_prior,
            -row["candidate"].pool_index,
        ),
        reverse=True,
    )
    best = scored[0]
    trace = _score_trace(best, config)
    trace["slot"] = slot
    limit = _integer(config, "trace", "top_candidates")
    trace["top_candidates"] = [_score_trace(row, config) for row in scored[:limit]]
    return best["candidate"], trace


def select_tree_baseline(
    *,
    anchor_provider: str,
    anchor_model: str,
    routed_tier: object,
    routing_confidence: object,
    structured_candidates: Sequence[Mapping[str, Any]] = (),
    model_options: Sequence[str] | None = None,
    router_tiers: Mapping[str, Any] | None = None,
    router_source: str = "squilla_router_local_tree",
    baseline_config: Mapping[str, Any] | None = None,
) -> TreeBaselineDecision:
    """Select the legacy tier-template proposer set and aggregator."""

    config = (
        _validate_tree_baseline_config(baseline_config)
        if baseline_config is not None
        else _packaged_tree_baseline_config()
    )
    effective_tier = _normalize_tier(routed_tier, config) or _string(config, "default_tier")
    raw_confidence: Any = routing_confidence
    try:
        confidence = float(raw_confidence or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    if not math.isfinite(confidence):
        confidence = 0.0
    effective_model_options = (
        list(model_options)
        if model_options is not None
        else _string_list(config, "default_model_options")
    )
    pool = _candidate_pool(
        anchor_provider=anchor_provider,
        anchor_model=anchor_model,
        routed_tier=effective_tier,
        structured_candidates=structured_candidates,
        model_options=effective_model_options,
        router_tiers=router_tiers or {},
        config=config,
    )
    if not pool:
        raise TreeBaselineError("router_tree_baseline candidate pool is empty")

    anchor = pool[0]
    slots = _string_list(config, "slot_templates", effective_tier)
    selected: list[TreeBaselineCandidate] = [anchor]
    selected_counts: dict[tuple[str, str], int] = {anchor.identity: 1}
    proposer_selections = [TreeBaselineSlotSelection("anchor", anchor)]
    slot_traces: list[dict[str, Any]] = [
        {
            "slot": "anchor",
            "selected": _candidate_trace(anchor, config),
            "reason": "tree_router_selected_model",
        }
    ]
    for slot in slots[1:]:
        candidate, trace = _select_candidate(
            slot=slot,
            pool=pool,
            routed_tier=effective_tier,
            routing_confidence=confidence,
            anchor=anchor,
            selected=selected,
            selected_counts=selected_counts,
            config=config,
        )
        selected.append(candidate)
        selected_counts[candidate.identity] = selected_counts.get(candidate.identity, 0) + 1
        proposer_selections.append(TreeBaselineSlotSelection(slot, candidate))
        slot_traces.append(trace)

    aggregator_slot = _string(config, "aggregator_slots", effective_tier)
    aggregator_candidate, aggregator_trace = _select_candidate(
        slot=aggregator_slot,
        pool=pool,
        routed_tier=effective_tier,
        routing_confidence=confidence,
        anchor=anchor,
        selected=selected,
        selected_counts=selected_counts,
        config=config,
    )
    aggregator_selection = TreeBaselineSlotSelection(aggregator_slot, aggregator_candidate)
    selected_p = [
        f"{selection.candidate.provider}:{selection.candidate.model}"
        for selection in proposer_selections
    ]
    selected_a = f"{aggregator_candidate.provider}:{aggregator_candidate.model}"
    trace = {
        "strategy": TREE_BASELINE_SELECTION_MODE,
        "algorithm_version": _string(config, "algorithm_version"),
        "config_version": _string(config, "config_version"),
        "config_hash": _canonical_hash(config),
        "router_source": str(router_source or "unknown"),
        "uses_remote_task_analyzer": False,
        "routed_tier": effective_tier,
        "routing_confidence": confidence,
        "anchor": _candidate_trace(anchor, config),
        "slot_template": slots,
        "slots": slot_traces,
        "aggregator_slot": aggregator_slot,
        "aggregator": aggregator_trace,
        "candidate_pool_size": len(pool),
        "candidate_pool": [_candidate_trace(candidate, config) for candidate in pool],
        "model_options_source": ("configured" if model_options is not None else "frozen_default"),
        "proposer_count": len(proposer_selections),
        "selected_P": selected_p,
        "selected_A": selected_a,
        "duplicate_policy": "selected_penalty",
        "tier_index": _tier_index(effective_tier, config),
    }
    return TreeBaselineDecision(
        routed_tier=effective_tier,
        routing_confidence=confidence,
        proposers=tuple(proposer_selections),
        aggregator=aggregator_selection,
        trace=trace,
    )
