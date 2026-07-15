"""Profile-driven model ranking for the ``router_dynamic`` ensemble mode.

The module implements the Step2 ranking contract as a deterministic, replayable
pipeline.  Task analysis, user profiles, and the model registry are deliberately
small adapters for now; the ranking core does not depend on how those inputs are
produced and can be replaced by trained services later.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import hashlib
import json
import math
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from typing import Any

import structlog

from .protocol import LLMProvider
from .types import ChatConfig, DoneEvent, ErrorEvent, Message, TextDeltaEvent

log = structlog.get_logger(__name__)

RANKING_VERSION = "step2-ranking-v1"
RANKING_CONFIG_SCHEMA_VERSION = "step2-ranking-config-v2"
TASK_ANALYZER_PROVIDER_ID = "openrouter"
TASK_ANALYZER_MODEL_ID = "anthropic/claude-opus-4.8"
TASK_ANALYZER_VERSION = "opus-4.8-json-v1"
TASK_PROFILE_SCHEMA_VERSION = "step2-task-profile-v1"

CAPABILITIES = (
    "reasoning",
    "code_generation",
    "code_review",
    "tool_use",
    "planning",
    "retrieval",
    "summarization",
    "writing",
    "math",
    "data_analysis",
    "visual_understanding",
    "audio_understanding",
    "long_context",
    "format_following",
    "safety_judgment",
)
DOMAINS = (
    "software_engineering",
    "data_science",
    "document_processing",
    "business_analysis",
    "creative_writing",
    "education",
    "research",
    "customer_support",
    "legal",
    "finance",
    "medical",
    "technical_writing",
    "general",
)
TIERS = ("1", "2", "3", "4")
MODALITIES = ("text", "image", "audio", "video", "file")
FORMATS = (
    "plain_text",
    "structured_text",
    "json",
    "table",
    "patch",
    "patch_and_explanation",
    "report",
    "slides",
    "code_only",
)

_CONSTRAINT_VALUES = {
    "cost": {"low", "medium", "high", "hard_limit"},
    "latency": {"interactive", "normal", "batch", "hard_timeout"},
    "risk": {"low", "medium", "high"},
}
_SESSION_INTENTS = {"new_task", "continue", "redo"}
_DEFAULT_SESSION_INTENT = "new_task"
_CONTEXT_BUCKET_ORDER = ("short", "medium", "long", "extra_long")
_CONTEXT_BUCKETS = set(_CONTEXT_BUCKET_ORDER)
_ROUTER_TIERS = {"c0", "c1", "c2", "c3"}
_USER_COST_SENSITIVITIES = {"low", "medium", "high", "hard_limit"}
_USER_TRADEOFFS = {"balanced", "latency_first", "quality_first"}

class DynamicRankingError(ValueError):
    """Raised when no feasible Step2 ``(P, A)`` decision can be built."""


class _ValidatedRankingConfig(dict[str, Any]):
    """Internal marker for a detached config that already passed full validation."""


@dataclass(frozen=True)
class TaskAnalysisResult:
    """Validated task profile plus provenance for the route trace."""

    profile: dict[str, Any]
    source: str
    schema_valid: bool
    confidence: float
    analyzer_version: str = TASK_ANALYZER_VERSION
    fallback_reason: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    provider_id: str = ""
    model_id: str = ""

    def trace(
        self, ranking_config: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        decimal_places = _ranking_int(
            _resolve_ranking_config(ranking_config),
            "trace",
            "profile_decimal_places",
        )
        return {
            "source": self.source,
            "schema_valid": self.schema_valid,
            "confidence": round(self.confidence, decimal_places),
            "analyzer_version": self.analyzer_version,
            "provider": self.provider_id,
            "model": self.model_id,
            "fallback_reason": self.fallback_reason,
            "usage": copy.deepcopy(self.usage),
        }


@dataclass(frozen=True)
class RankedModel:
    """Normalized model-registry row used by the ranking core."""

    provider: str
    model_id: str
    version: str
    source: str
    registry_facts: dict[str, Any]
    static_profile: dict[str, Any]
    online_profile: dict[str, Any]
    thinking: str | None = "xhigh"

    @property
    def identity(self) -> str:
        return f"{self.provider}:{self.model_id}"

    @property
    def family(self) -> str:
        return str(self.registry_facts.get("family") or self.model_id).lower()

    @property
    def vendor(self) -> str:
        return str(self.registry_facts.get("vendor") or self.provider).lower()

    def trace(self) -> dict[str, Any]:
        facts = self.registry_facts
        return {
            "identity": self.identity,
            "provider": self.provider,
            "model": self.model_id,
            "version": self.version,
            "source": self.source,
            "vendor": self.vendor,
            "family": self.family,
            "status": str(facts.get("status") or ""),
            "roles": list(facts.get("roles") or []),
            "context_window": _as_int(facts.get("context_window"), 0),
            "modalities": list(facts.get("modalities") or []),
            "health": facts.get("health"),
            "credential_available": bool(facts.get("credential_available", True)),
            "profile_hash": _canonical_hash(
                {
                    "registry_facts": self.registry_facts,
                    "static_profile": self.static_profile,
                    "online_profile": self.online_profile,
                    "thinking": self.thinking,
                }
            ),
        }


@dataclass(frozen=True)
class RankingDecision:
    """Selected proposer set, aggregator, and replayable ranking trace."""

    proposers: tuple[RankedModel, ...]
    aggregator: RankedModel
    effective_tier: int
    trace: dict[str, Any]


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _ranking_value(config: Mapping[str, Any], *path: str) -> Any:
    value: Any = config
    for key in path:
        if not isinstance(value, Mapping) or key not in value:
            dotted = ".".join(path)
            raise DynamicRankingError(f"router_dynamic ranking config lacks {dotted}")
        value = value[key]
    return value


def _ranking_mapping(config: Mapping[str, Any], *path: str) -> Mapping[str, Any]:
    value = _ranking_value(config, *path)
    if not isinstance(value, Mapping):
        dotted = ".".join(path)
        raise DynamicRankingError(f"router_dynamic ranking config {dotted} must be an object")
    return value


def _ranking_number(config: Mapping[str, Any], *path: str) -> float:
    value = _ranking_value(config, *path)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        dotted = ".".join(path)
        raise DynamicRankingError(f"router_dynamic ranking config {dotted} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        dotted = ".".join(path)
        raise DynamicRankingError(f"router_dynamic ranking config {dotted} must be finite")
    return number


def _ranking_int(config: Mapping[str, Any], *path: str) -> int:
    number = _ranking_number(config, *path)
    integer = int(number)
    if number != integer:
        dotted = ".".join(path)
        raise DynamicRankingError(f"router_dynamic ranking config {dotted} must be an integer")
    return integer


def _ranking_string_set(config: Mapping[str, Any], *path: str) -> set[str]:
    return set(_ranking_string_list(config, *path))


def _ranking_string_list(config: Mapping[str, Any], *path: str) -> list[str]:
    value = _ranking_value(config, *path)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        dotted = ".".join(path)
        raise DynamicRankingError(f"router_dynamic ranking config {dotted} must be a list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            dotted = ".".join(path)
            raise DynamicRankingError(
                f"router_dynamic ranking config {dotted} must contain non-empty strings"
            )
        result.append(item.strip())
    if len(set(result)) != len(result):
        dotted = ".".join(path)
        raise DynamicRankingError(
            f"router_dynamic ranking config {dotted} cannot contain duplicates"
        )
    return result


def _ranking_string(config: Mapping[str, Any], *path: str) -> str:
    value = _ranking_value(config, *path)
    if not isinstance(value, str) or not value.strip():
        dotted = ".".join(path)
        raise DynamicRankingError(
            f"router_dynamic ranking config {dotted} must be a non-empty string"
        )
    return value.strip()


def _ranking_bool(config: Mapping[str, Any], *path: str) -> bool:
    value = _ranking_value(config, *path)
    if not isinstance(value, bool):
        dotted = ".".join(path)
        raise DynamicRankingError(f"router_dynamic ranking config {dotted} must be boolean")
    return value


def _context_bucket_min_tokens(config: Mapping[str, Any]) -> dict[str, int]:
    values = _ranking_mapping(config, "context", "bucket_min_tokens")
    return {
        str(bucket): _ranking_int(config, "context", "bucket_min_tokens", str(bucket))
        for bucket in values
    }


def _router_tier_mapping(config: Mapping[str, Any]) -> dict[str, int]:
    values = _ranking_mapping(config, "routing_tiers", "mapping")
    return {
        str(router_tier): _ranking_int(
            config, "routing_tiers", "mapping", str(router_tier)
        )
        for router_tier in values
    }


def _require_exact_config_keys(
    config: Mapping[str, Any],
    path: tuple[str, ...],
    expected: set[str],
) -> None:
    values = _ranking_mapping(config, *path)
    actual = set(values)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    raise DynamicRankingError(
        "router_dynamic ranking config "
        f"{'.'.join(path)} has unknown or missing keys "
        f"(missing={missing}, unknown={unknown})"
    )


def _validate_ranking_config(raw: Any) -> _ValidatedRankingConfig:
    if not isinstance(raw, Mapping):
        raise DynamicRankingError("router_dynamic ranking config must be an object")
    config = copy.deepcopy(dict(raw))
    required_sections = (
        "validation",
        "trace",
        "routing_tiers",
        "context",
        "task_profile_schema",
        "task_analyzer",
        "fallback_task_profile",
        "mock_user_profile",
        "synthetic_model",
        "hard_filter",
        "exploration",
        "normalization",
        "task_match",
        "user_score",
        "quality",
        "penalties",
        "session",
        "proposer_count",
        "rerank",
        "aggregator",
    )
    for key in required_sections:
        _ranking_mapping(config, key)
    if set(config) != {"schema_version", "config_version", *required_sections}:
        raise DynamicRankingError(
            "router_dynamic ranking config has unknown or missing top-level keys"
        )
    fixed_object_keys = {
        ("validation",): {"weight_sum_tolerance"},
        ("trace",): {
            "profile_decimal_places",
            "score_decimal_places",
            "session_nonzero_epsilon",
        },
        ("routing_tiers",): {"default_router_tier", "mapping"},
        ("context",): {
            "bucket_min_tokens",
            "default_bucket",
            "request_limits",
            "token_estimation",
            "output_budget",
        },
        ("context", "request_limits"): {
            "role_max_chars",
            "max_recent_turns",
            "fallback_history_max_turns",
            "turn_max_chars",
            "summary_max_chars",
            "state_max_items",
            "item_max_chars",
            "tool_summary_max_chars",
            "test_results_max_chars",
            "intermediate_max_items",
            "intermediate_max_chars",
            "attachment_max_items",
            "last_route_max_models",
            "max_scanned_items_multiplier",
        },
        ("context", "token_estimation"): {
            "utf8_bytes_per_token",
            "candidate_chars_per_token",
        },
        ("context", "output_budget"): {"default_tokens", "minimum_tokens"},
        ("task_profile_schema",): {
            "constraint_values",
            "session_intents",
            "default_session_intent",
        },
        ("task_analyzer",): {
            "timeout_seconds",
            "input_max_chars",
            "response_max_chars",
            "max_output_tokens",
            "temperature",
            "thinking",
            "default_confidence",
            "truncation_head_fraction",
        },
        ("fallback_task_profile",): {
            "capability_dist",
            "domain_dist",
            "constraints",
            "risk_by_tier",
            "session_intent",
        },
        ("fallback_task_profile", "constraints"): {"cost", "latency"},
        ("fallback_task_profile", "risk_by_tier"): set(TIERS),
        ("fallback_task_profile", "session_intent"): {"type", "confidence"},
        ("mock_user_profile",): {
            "profile_version",
            "profile_source",
            "permission",
            "preference",
            "history",
        },
        ("mock_user_profile", "permission"): {
            "allow_models",
            "deny_models",
            "allow_tools",
            "risk_allowlist",
        },
        ("mock_user_profile", "preference"): {
            "quality_latency_tradeoff",
            "cost_sensitivity",
            "preferred_formats",
        },
        ("mock_user_profile", "history"): {
            "capability_prior",
            "positive_model_ids",
            "negative_model_ids",
            "feedback_count",
            "last_updated_at",
        },
        ("synthetic_model",): {
            "family_name_parts",
            "thinking",
            "version",
            "status",
            "context_window",
            "effective_context_bucket",
            "price_input_per_million",
            "price_output_per_million",
            "latency_p50_ms",
            "latency_p95_ms",
            "quota",
            "rate_limit",
            "health",
            "base_strength_by_tier",
            "tier_strength_penalty_per_level",
            "aggregator_role_fit_minimum",
            "aggregator_role_fit_penalty",
        },
        ("hard_filter",): {
            "eligible_statuses",
            "unavailable_health_states",
            "unavailable_quota_states",
            "unavailable_rate_limit_states",
            "default_health",
            "default_quota",
            "default_rate_limit",
            "default_required_modalities",
        },
        ("exploration",): {"enabled", "decision_propensity"},
        ("normalization",): {
            "price_reference_usd_per_million",
            "latency_reference_ms",
            "price_input_weight",
            "price_output_weight",
        },
        ("task_match",): {
            "capability_weight",
            "domain_weight",
            "tier_weight",
            "proposer_task_weight",
            "proposer_role_fit_weight",
            "context_underqualified_multiplier",
            "format_base_multiplier",
            "format_strength_multiplier",
            "missing_strength_default",
            "missing_role_fit_default",
        },
        ("user_score",): {
            "neutral_score",
            "history_signal_weight",
            "feedback_saturation_count",
            "preferred_format_bonus",
        },
        ("quality",): {"task_match_weight", "user_score_weight"},
        ("penalties",): {
            "task_cost_weights",
            "task_latency_weights",
            "user_cost_sensitivity_weights",
            "default_cost_weight",
            "default_latency_weight",
            "latency_first_adjustment",
            "quality_first_latency_reduction",
            "quality_first_cost_reduction",
            "quality_first_minimum_weight",
        },
        ("session",): {
            "intent_confidence_threshold",
            "score_delta",
            "max_escalation_level",
            "default_quality_feedback",
            "route_cache_max_entries",
        },
        ("proposer_count",): {
            "effective_tier_rounding_offset",
            "by_tier",
            "high_risk",
            "constrained_max",
            "constrained_cost_values",
            "constrained_latency_values",
            "constrained_user_cost_values",
            "constrained_user_tradeoffs",
        },
        ("proposer_count", "high_risk"): {"min", "max"},
        ("rerank",): {
            "top_l_min",
            "top_l_multiplier",
            "quality_floor_margin_by_risk",
            "default_quality_floor_margin",
            "quality_weight",
            "coverage_gain_weight",
            "error_complementarity_weight",
            "similarity_penalty_weight",
            "stop_threshold",
            "trace_top_candidates",
            "similarity",
            "error_dimensions",
        },
        ("rerank", "similarity"): {
            "capability_weight",
            "lineage_weight",
            "same_family_score",
            "same_vendor_score",
            "unrelated_score",
        },
        ("aggregator",): {
            "task_match_weight",
            "role_fit_weight",
            "same_model_penalty",
            "same_family_or_vendor_penalty",
        },
    }
    for object_path, expected_keys in fixed_object_keys.items():
        _require_exact_config_keys(config, object_path, expected_keys)
    schema_version = _ranking_string(config, "schema_version")
    if schema_version != RANKING_CONFIG_SCHEMA_VERSION:
        raise DynamicRankingError(
            "router_dynamic ranking config schema_version must be "
            f"{RANKING_CONFIG_SCHEMA_VERSION}"
        )
    _ranking_string(config, "config_version")

    weight_sum_tolerance = _ranking_number(
        config, "validation", "weight_sum_tolerance"
    )
    if not 0.0 < weight_sum_tolerance < 1.0:
        raise DynamicRankingError(
            "router_dynamic validation.weight_sum_tolerance must be between 0 and 1"
        )

    weight_groups = (
        (
            ("normalization", "price_input_weight"),
            ("normalization", "price_output_weight"),
        ),
        (
            ("task_match", "capability_weight"),
            ("task_match", "domain_weight"),
            ("task_match", "tier_weight"),
        ),
        (
            ("task_match", "proposer_task_weight"),
            ("task_match", "proposer_role_fit_weight"),
        ),
        (
            ("task_match", "format_base_multiplier"),
            ("task_match", "format_strength_multiplier"),
        ),
        (
            ("quality", "task_match_weight"),
            ("quality", "user_score_weight"),
        ),
        (
            ("rerank", "similarity", "capability_weight"),
            ("rerank", "similarity", "lineage_weight"),
        ),
        (
            ("aggregator", "task_match_weight"),
            ("aggregator", "role_fit_weight"),
        ),
    )
    for group in weight_groups:
        weight_values = [_ranking_number(config, *weight_path) for weight_path in group]
        if any(value < 0.0 for value in weight_values) or not math.isclose(
            sum(weight_values), 1.0, abs_tol=weight_sum_tolerance
        ):
            dotted = ", ".join(".".join(weight_path) for weight_path in group)
            raise DynamicRankingError(
                f"router_dynamic ranking weights must be non-negative and sum to 1: {dotted}"
            )

    for path in (
        ("trace", "profile_decimal_places"),
        ("trace", "score_decimal_places"),
    ):
        if _ranking_int(config, *path) < 0:
            raise DynamicRankingError(
                f"router_dynamic ranking config {'.'.join(path)} cannot be negative"
            )
    session_nonzero_epsilon = _ranking_number(
        config, "trace", "session_nonzero_epsilon"
    )
    if not 0.0 < session_nonzero_epsilon <= 1.0:
        raise DynamicRankingError(
            "router_dynamic trace.session_nonzero_epsilon must be between 0 and 1"
        )

    router_tier_mapping = _router_tier_mapping(config)
    if (
        set(router_tier_mapping) != _ROUTER_TIERS
        or len(set(router_tier_mapping.values())) != len(router_tier_mapping)
        or set(str(value) for value in router_tier_mapping.values()) != set(TIERS)
    ):
        raise DynamicRankingError(
            "router_dynamic routing_tiers.mapping must map c0-c3 one-to-one to task tiers"
        )
    default_router_tier = _ranking_string(
        config, "routing_tiers", "default_router_tier"
    )
    if default_router_tier not in router_tier_mapping:
        raise DynamicRankingError(
            "router_dynamic routing_tiers.default_router_tier is invalid"
        )

    bucket_min_tokens = _context_bucket_min_tokens(config)
    if (
        set(bucket_min_tokens) != _CONTEXT_BUCKETS
        or any(value < 0 for value in bucket_min_tokens.values())
        or len(set(bucket_min_tokens.values())) != len(bucket_min_tokens)
        or [bucket_min_tokens[name] for name in _CONTEXT_BUCKET_ORDER]
        != sorted(bucket_min_tokens.values())
    ):
        raise DynamicRankingError(
            "router_dynamic context.bucket_min_tokens must define unique short-to-extra-long "
            "thresholds"
        )
    default_bucket = _ranking_string(config, "context", "default_bucket")
    if default_bucket not in bucket_min_tokens:
        raise DynamicRankingError(
            "router_dynamic context.default_bucket must exist in bucket_min_tokens"
        )
    if bucket_min_tokens[default_bucket] != min(bucket_min_tokens.values()):
        raise DynamicRankingError(
            "router_dynamic context.default_bucket must have the lowest token threshold"
        )
    for key in (
        "role_max_chars",
        "max_recent_turns",
        "fallback_history_max_turns",
        "turn_max_chars",
        "summary_max_chars",
        "state_max_items",
        "item_max_chars",
        "tool_summary_max_chars",
        "test_results_max_chars",
        "intermediate_max_items",
        "intermediate_max_chars",
        "attachment_max_items",
        "last_route_max_models",
        "max_scanned_items_multiplier",
    ):
        if _ranking_int(config, "context", "request_limits", key) <= 0:
            raise DynamicRankingError(
                f"router_dynamic context.request_limits.{key} must be positive"
            )
    for key in ("utf8_bytes_per_token", "candidate_chars_per_token"):
        if _ranking_number(config, "context", "token_estimation", key) <= 0.0:
            raise DynamicRankingError(
                f"router_dynamic context.token_estimation.{key} must be positive"
            )
    for key in ("default_tokens", "minimum_tokens"):
        if _ranking_int(config, "context", "output_budget", key) <= 0:
            raise DynamicRankingError(
                f"router_dynamic context.output_budget.{key} must be positive"
            )
    if _ranking_int(
        config, "context", "output_budget", "default_tokens"
    ) < _ranking_int(config, "context", "output_budget", "minimum_tokens"):
        raise DynamicRankingError(
            "router_dynamic context.output_budget.default_tokens cannot be below minimum_tokens"
        )

    constraint_values = _ranking_mapping(
        config, "task_profile_schema", "constraint_values"
    )
    for key, expected_values in _CONSTRAINT_VALUES.items():
        configured_values = _ranking_string_set(
            config, "task_profile_schema", "constraint_values", key
        )
        if configured_values != expected_values:
            raise DynamicRankingError(
                "router_dynamic task_profile_schema.constraint_values."
                f"{key} must match the supported protocol values"
            )
    if set(constraint_values) != set(_CONSTRAINT_VALUES):
        raise DynamicRankingError(
            "router_dynamic task_profile_schema.constraint_values has invalid keys"
        )
    session_intents = _ranking_string_set(
        config, "task_profile_schema", "session_intents"
    )
    default_intent = _ranking_string(
        config, "task_profile_schema", "default_session_intent"
    )
    if session_intents != _SESSION_INTENTS or default_intent != _DEFAULT_SESSION_INTENT:
        raise DynamicRankingError(
            "router_dynamic task_profile_schema session intents must match the supported "
            "protocol values"
        )

    for key in (
        "input_max_chars",
        "response_max_chars",
        "max_output_tokens",
    ):
        if _ranking_int(config, "task_analyzer", key) <= 0:
            raise DynamicRankingError(
                f"router_dynamic task_analyzer.{key} must be positive"
            )
    if _ranking_number(config, "task_analyzer", "timeout_seconds") <= 0.0:
        raise DynamicRankingError(
            "router_dynamic task_analyzer.timeout_seconds must be positive"
        )
    analyzer_temperature = _ranking_number(config, "task_analyzer", "temperature")
    if analyzer_temperature < 0.0:
        raise DynamicRankingError(
            "router_dynamic task_analyzer.temperature cannot be negative"
        )
    _ranking_bool(config, "task_analyzer", "thinking")

    def validate_distribution(path: tuple[str, ...], allowed: set[str]) -> None:
        distribution = _ranking_mapping(config, *path)
        if not distribution or not set(distribution).issubset(allowed):
            raise DynamicRankingError(
                f"router_dynamic ranking config {'.'.join(path)} has invalid dimensions"
            )
        total = 0.0
        for key in distribution:
            value = _ranking_number(config, *path, str(key))
            if value < 0.0:
                raise DynamicRankingError(
                    f"router_dynamic ranking config {'.'.join(path)}.{key} cannot be negative"
                )
            total += value
        if not math.isclose(total, 1.0, abs_tol=weight_sum_tolerance):
            raise DynamicRankingError(
                f"router_dynamic ranking config {'.'.join(path)} must sum to 1"
            )

    validate_distribution(
        ("fallback_task_profile", "capability_dist"), set(CAPABILITIES)
    )
    validate_distribution(("fallback_task_profile", "domain_dist"), set(DOMAINS))
    fallback_constraints = _ranking_mapping(
        config, "fallback_task_profile", "constraints"
    )
    for key in ("cost", "latency"):
        if _ranking_string(config, "fallback_task_profile", "constraints", key) not in {
            str(value)
            for value in _ranking_value(
                config, "task_profile_schema", "constraint_values", key
            )
        }:
            raise DynamicRankingError(
                f"router_dynamic fallback_task_profile.constraints.{key} is invalid"
            )
    if set(fallback_constraints) != {"cost", "latency"}:
        raise DynamicRankingError(
            "router_dynamic fallback_task_profile.constraints has invalid keys"
        )
    risk_values = _ranking_string_set(
        config, "task_profile_schema", "constraint_values", "risk"
    )
    for tier in TIERS:
        if _ranking_string(
            config, "fallback_task_profile", "risk_by_tier", tier
        ) not in risk_values:
            raise DynamicRankingError(
                f"router_dynamic fallback_task_profile.risk_by_tier.{tier} is invalid"
            )
    if _ranking_string(
        config, "fallback_task_profile", "session_intent", "type"
    ) not in session_intents:
        raise DynamicRankingError(
            "router_dynamic fallback_task_profile.session_intent.type is invalid"
        )

    for key in ("allow_models", "deny_models", "allow_tools"):
        _ranking_string_list(config, "mock_user_profile", "permission", key)
    if not _ranking_string_set(
        config, "mock_user_profile", "permission", "risk_allowlist"
    ).issubset(risk_values):
        raise DynamicRankingError(
            "router_dynamic mock_user_profile.permission.risk_allowlist is invalid"
        )

    if _ranking_string(
        config, "mock_user_profile", "preference", "quality_latency_tradeoff"
    ) not in _USER_TRADEOFFS:
        raise DynamicRankingError(
            "router_dynamic mock_user_profile.preference.quality_latency_tradeoff is invalid"
        )
    cost_sensitivity = _ranking_string(
        config, "mock_user_profile", "preference", "cost_sensitivity"
    )
    if cost_sensitivity not in _ranking_mapping(
        config, "penalties", "user_cost_sensitivity_weights"
    ):
        raise DynamicRankingError(
            "router_dynamic mock_user_profile.preference.cost_sensitivity is invalid"
        )
    if not set(
        _ranking_string_list(
            config, "mock_user_profile", "preference", "preferred_formats"
        )
    ).issubset(set(FORMATS)):
        raise DynamicRankingError(
            "router_dynamic mock_user_profile.preference.preferred_formats is invalid"
        )

    capability_prior = _ranking_mapping(
        config, "mock_user_profile", "history", "capability_prior"
    )
    if not set(capability_prior).issubset(set(CAPABILITIES)):
        raise DynamicRankingError(
            "router_dynamic mock_user_profile.history.capability_prior is invalid"
        )
    for capability in capability_prior:
        prior = _ranking_number(
            config,
            "mock_user_profile",
            "history",
            "capability_prior",
            str(capability),
        )
        if not 0.0 <= prior <= 1.0:
            raise DynamicRankingError(
                "router_dynamic mock_user_profile.history.capability_prior values "
                "must be between 0 and 1"
            )
    _ranking_string_list(config, "mock_user_profile", "history", "positive_model_ids")
    _ranking_string_list(config, "mock_user_profile", "history", "negative_model_ids")
    if _ranking_int(config, "mock_user_profile", "history", "feedback_count") < 0:
        raise DynamicRankingError(
            "router_dynamic mock_user_profile.history.feedback_count cannot be negative"
        )
    _ranking_string(config, "mock_user_profile", "history", "last_updated_at")
    _ranking_string(config, "mock_user_profile", "profile_version")
    _ranking_string(config, "mock_user_profile", "profile_source")

    for key in (
        "family_name_parts",
        "context_window",
        "latency_p50_ms",
        "latency_p95_ms",
    ):
        if _ranking_int(config, "synthetic_model", key) <= 0:
            raise DynamicRankingError(
                f"router_dynamic synthetic_model.{key} must be positive"
            )
    for key in (
        "price_input_per_million",
        "price_output_per_million",
        "tier_strength_penalty_per_level",
        "aggregator_role_fit_minimum",
        "aggregator_role_fit_penalty",
    ):
        if _ranking_number(config, "synthetic_model", key) < 0.0:
            raise DynamicRankingError(
                f"router_dynamic synthetic_model.{key} cannot be negative"
            )
    for key in (
        "thinking",
        "version",
        "status",
        "effective_context_bucket",
        "quota",
        "rate_limit",
        "health",
    ):
        _ranking_string(config, "synthetic_model", key)
    for tier in TIERS:
        strength = _ranking_number(
            config, "synthetic_model", "base_strength_by_tier", tier
        )
        if not 0.0 <= strength <= 1.0:
            raise DynamicRankingError(
                f"router_dynamic synthetic_model.base_strength_by_tier.{tier} is invalid"
            )
    if set(
        _ranking_mapping(config, "synthetic_model", "base_strength_by_tier")
    ) != set(TIERS):
        raise DynamicRankingError(
            "router_dynamic synthetic_model.base_strength_by_tier has invalid keys"
        )

    for key in (
        "eligible_statuses",
        "unavailable_health_states",
        "unavailable_quota_states",
        "unavailable_rate_limit_states",
        "default_required_modalities",
    ):
        if not _ranking_string_set(config, "hard_filter", key):
            raise DynamicRankingError(
                f"router_dynamic hard_filter.{key} cannot be empty"
            )
    default_modalities = _ranking_string_set(
        config, "hard_filter", "default_required_modalities"
    )
    if not default_modalities.issubset(set(MODALITIES)):
        raise DynamicRankingError(
            "router_dynamic hard_filter.default_required_modalities is invalid"
        )
    for key in ("default_health", "default_quota", "default_rate_limit"):
        _ranking_string(config, "hard_filter", key)
    exploration_enabled = _ranking_bool(config, "exploration", "enabled")
    if _ranking_string(
        config, "synthetic_model", "effective_context_bucket"
    ) not in bucket_min_tokens:
        raise DynamicRankingError(
            "router_dynamic synthetic_model.effective_context_bucket is invalid"
        )
    synthetic_bucket = _ranking_string(
        config, "synthetic_model", "effective_context_bucket"
    )
    if _ranking_int(config, "synthetic_model", "context_window") < bucket_min_tokens[
        synthetic_bucket
    ]:
        raise DynamicRankingError(
            "router_dynamic synthetic_model.context_window is smaller than its context bucket"
        )
    if _ranking_int(
        config, "synthetic_model", "latency_p50_ms"
    ) > _ranking_int(config, "synthetic_model", "latency_p95_ms"):
        raise DynamicRankingError(
            "router_dynamic synthetic_model latency p50 cannot exceed p95"
        )

    unit_interval_paths = (
        ("task_analyzer", "default_confidence"),
        ("task_analyzer", "truncation_head_fraction"),
        ("fallback_task_profile", "session_intent", "confidence"),
        ("task_match", "context_underqualified_multiplier"),
        ("task_match", "format_base_multiplier"),
        ("task_match", "format_strength_multiplier"),
        ("task_match", "missing_strength_default"),
        ("task_match", "missing_role_fit_default"),
        ("user_score", "neutral_score"),
        ("user_score", "history_signal_weight"),
        ("user_score", "preferred_format_bonus"),
        ("session", "intent_confidence_threshold"),
        ("session", "default_quality_feedback"),
        ("session", "score_delta"),
        ("proposer_count", "effective_tier_rounding_offset"),
        ("rerank", "default_quality_floor_margin"),
        ("rerank", "similarity", "same_family_score"),
        ("rerank", "similarity", "same_vendor_score"),
        ("rerank", "similarity", "unrelated_score"),
        ("aggregator", "same_model_penalty"),
        ("aggregator", "same_family_or_vendor_penalty"),
        ("synthetic_model", "tier_strength_penalty_per_level"),
        ("synthetic_model", "aggregator_role_fit_minimum"),
        ("synthetic_model", "aggregator_role_fit_penalty"),
        ("exploration", "decision_propensity"),
    )
    for unit_path in unit_interval_paths:
        unit_value = _ranking_number(config, *unit_path)
        if not 0.0 <= unit_value <= 1.0:
            raise DynamicRankingError(
                f"router_dynamic ranking config {'.'.join(unit_path)} must be between 0 and 1"
            )
    decision_propensity = _ranking_number(
        config, "exploration", "decision_propensity"
    )
    if exploration_enabled or decision_propensity != 1.0:
        raise DynamicRankingError(
            "router_dynamic exploration is reserved and must remain disabled with propensity 1"
        )

    nonnegative_paths = (
        ("penalties", "default_cost_weight"),
        ("penalties", "default_latency_weight"),
        ("penalties", "latency_first_adjustment"),
        ("penalties", "quality_first_latency_reduction"),
        ("penalties", "quality_first_cost_reduction"),
        ("penalties", "quality_first_minimum_weight"),
        ("rerank", "quality_weight"),
        ("rerank", "coverage_gain_weight"),
        ("rerank", "error_complementarity_weight"),
        ("rerank", "similarity_penalty_weight"),
    )
    for nonnegative_path in nonnegative_paths:
        if _ranking_number(config, *nonnegative_path) < 0.0:
            raise DynamicRankingError(
                "router_dynamic ranking config "
                f"{'.'.join(nonnegative_path)} cannot be negative"
            )

    numeric_mapping_keys = {
        ("penalties", "task_cost_weights"): _CONSTRAINT_VALUES["cost"],
        ("penalties", "task_latency_weights"): _CONSTRAINT_VALUES["latency"],
        ("penalties", "user_cost_sensitivity_weights"): _USER_COST_SENSITIVITIES,
        ("rerank", "quality_floor_margin_by_risk"): _CONSTRAINT_VALUES["risk"],
    }
    for mapping_path, expected_keys in numeric_mapping_keys.items():
        mapping_values = _ranking_mapping(config, *mapping_path)
        if set(mapping_values) != expected_keys:
            raise DynamicRankingError(
                "router_dynamic ranking config "
                f"{'.'.join(mapping_path)} must define the supported protocol values"
            )
        for mapping_key in mapping_values:
            numeric_value = _ranking_number(
                config, *mapping_path, str(mapping_key)
            )
            if numeric_value < 0.0:
                raise DynamicRankingError(
                    "router_dynamic ranking config "
                    f"{'.'.join(mapping_path)}.{mapping_key} must be a non-negative number"
                )
            if (
                mapping_path == ("rerank", "quality_floor_margin_by_risk")
                and numeric_value > 1.0
            ):
                raise DynamicRankingError(
                    "router_dynamic rerank quality-floor margins cannot exceed 1"
                )
    for tier in TIERS:
        tier_bounds = _ranking_mapping(config, "proposer_count", "by_tier", tier)
        if set(tier_bounds) != {"min", "max"}:
            raise DynamicRankingError(
                f"router_dynamic proposer_count.by_tier.{tier} has invalid keys"
            )
        minimum = _ranking_int(config, "proposer_count", "by_tier", tier, "min")
        maximum = _ranking_int(config, "proposer_count", "by_tier", tier, "max")
        if minimum < 1 or maximum < minimum:
            raise DynamicRankingError(
                f"router_dynamic proposer_count.by_tier.{tier} has invalid bounds"
            )
    if set(_ranking_mapping(config, "proposer_count", "by_tier")) != set(TIERS):
        raise DynamicRankingError(
            "router_dynamic proposer_count.by_tier has invalid keys"
        )
    high_risk_minimum = _ranking_int(
        config, "proposer_count", "high_risk", "min"
    )
    high_risk_maximum = _ranking_int(
        config, "proposer_count", "high_risk", "max"
    )
    if high_risk_minimum < 1 or high_risk_maximum < high_risk_minimum:
        raise DynamicRankingError("router_dynamic proposer_count.high_risk has invalid bounds")
    if _ranking_int(config, "proposer_count", "constrained_max") < 1:
        raise DynamicRankingError(
            "router_dynamic proposer_count.constrained_max must be positive"
        )
    if _ranking_int(config, "session", "max_escalation_level") < 0:
        raise DynamicRankingError(
            "router_dynamic session.max_escalation_level cannot be negative"
        )
    if _ranking_int(config, "session", "route_cache_max_entries") <= 0:
        raise DynamicRankingError(
            "router_dynamic session.route_cache_max_entries must be positive"
        )
    for path in (
        ("normalization", "price_reference_usd_per_million"),
        ("normalization", "latency_reference_ms"),
    ):
        if _ranking_number(config, *path) <= 0.0:
            raise DynamicRankingError(
                f"router_dynamic ranking config {'.'.join(path)} must be positive"
            )
    for path in (
        ("user_score", "feedback_saturation_count"),
        ("rerank", "top_l_min"),
        ("rerank", "top_l_multiplier"),
        ("rerank", "trace_top_candidates"),
    ):
        if _ranking_int(config, *path) <= 0:
            raise DynamicRankingError(
                f"router_dynamic ranking config {'.'.join(path)} must be a positive integer"
            )
    _ranking_number(config, "rerank", "stop_threshold")
    constrained_cost_values = _ranking_string_set(
        config, "proposer_count", "constrained_cost_values"
    )
    constrained_latency_values = _ranking_string_set(
        config, "proposer_count", "constrained_latency_values"
    )
    constrained_user_cost_values = _ranking_string_set(
        config, "proposer_count", "constrained_user_cost_values"
    )
    constrained_user_tradeoffs = _ranking_string_set(
        config, "proposer_count", "constrained_user_tradeoffs"
    )
    if not constrained_cost_values.issubset(_CONSTRAINT_VALUES["cost"]):
        raise DynamicRankingError(
            "router_dynamic proposer_count.constrained_cost_values is invalid"
        )
    if not constrained_latency_values.issubset(_CONSTRAINT_VALUES["latency"]):
        raise DynamicRankingError(
            "router_dynamic proposer_count.constrained_latency_values is invalid"
        )
    if not constrained_user_cost_values.issubset(
        set(_ranking_mapping(config, "penalties", "user_cost_sensitivity_weights"))
    ):
        raise DynamicRankingError(
            "router_dynamic proposer_count.constrained_user_cost_values is invalid"
        )
    if not constrained_user_tradeoffs.issubset(
        _USER_TRADEOFFS
    ):
        raise DynamicRankingError(
            "router_dynamic proposer_count.constrained_user_tradeoffs is invalid"
        )
    error_dimensions = _ranking_string_list(config, "rerank", "error_dimensions")
    if not error_dimensions:
        raise DynamicRankingError("router_dynamic rerank.error_dimensions cannot be empty")
    return _ValidatedRankingConfig(config)


@cache
def _packaged_ranking_config() -> _ValidatedRankingConfig:
    try:
        path = resources.files("opensquilla.provider").joinpath(
            "router_dynamic_ranking_config.json"
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - surfaced as a precise routing error
        raise DynamicRankingError("router_dynamic ranking config unavailable") from exc
    return _validate_ranking_config(payload)


def load_ranking_config() -> dict[str, Any]:
    """Return an isolated copy of the versioned Step2 ranking parameters."""

    return copy.deepcopy(dict(_packaged_ranking_config()))


def ranking_config_snapshot() -> Mapping[str, Any]:
    """Return the process-cached, validated config for internal routing calls."""

    return _packaged_ranking_config()


def _resolve_ranking_config(
    ranking_config: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    if isinstance(ranking_config, _ValidatedRankingConfig):
        return ranking_config
    return (
        _validate_ranking_config(ranking_config)
        if ranking_config is not None
        else _packaged_ranking_config()
    )


def default_session_quality_feedback() -> float:
    """Return the configured neutral feedback stored for a completed route."""

    return _clamp(
        _ranking_number(_packaged_ranking_config(), "session", "default_quality_feedback")
    )


def router_dynamic_route_cache_max_entries() -> int:
    """Return the configured per-process dynamic-route cache bound."""

    return _ranking_int(_packaged_ranking_config(), "session", "route_cache_max_entries")


def _normalize_distribution(
    raw: Any,
    allowed: Sequence[str],
    fallback: Mapping[str, float],
) -> tuple[dict[str, float], bool]:
    if not isinstance(raw, Mapping):
        return dict(fallback), False
    values: dict[str, float] = {}
    valid = True
    for name, value in raw.items():
        key = str(name)
        if key not in allowed:
            valid = False
            continue
        number = _as_float(value, -1.0)
        if number < 0.0:
            valid = False
            continue
        if number > 0.0:
            values[key] = number
    total = sum(values.values())
    if total <= 0.0:
        return dict(fallback), False
    return {key: value / total for key, value in values.items()}, valid


def _router_tier(value: Any, ranking_config: Mapping[str, Any]) -> str:
    mapping = _router_tier_mapping(ranking_config)
    default = _ranking_string(
        ranking_config, "routing_tiers", "default_router_tier"
    )
    raw = str(value or "").strip().lower()
    if raw in mapping:
        return raw
    if raw.startswith("t") and raw[1:].isdigit():
        tier = int(raw[1:])
        inverse = {value: key for key, value in mapping.items()}
        if tier in inverse:
            return inverse[tier]
    return default


def _context_bucket_for_tokens(
    tokens: int, ranking_config: Mapping[str, Any]
) -> str:
    thresholds = _context_bucket_min_tokens(ranking_config)
    for bucket, minimum in sorted(
        thresholds.items(), key=lambda item: item[1], reverse=True
    ):
        if tokens >= minimum:
            return bucket
    return _ranking_string(ranking_config, "context", "default_bucket")


def _bounded_recent_turn(value: Any, ranking_config: Mapping[str, Any]) -> Any:
    role_max_chars = _ranking_int(
        ranking_config, "context", "request_limits", "role_max_chars"
    )
    turn_max_chars = _ranking_int(
        ranking_config, "context", "request_limits", "turn_max_chars"
    )
    if isinstance(value, Mapping):
        role = str(value.get("role") or "")[:role_max_chars]
        content = value.get("content", value.get("text", ""))
        return {
            "role": role,
            "content": str(content)[:turn_max_chars],
        }
    return str(value)[:turn_max_chars]


def dynamic_output_token_budgets(
    *,
    configured_output_tokens: int,
    candidate_max_chars: int,
    ranking_config: Mapping[str, Any] | None = None,
) -> tuple[int, int]:
    """Return conservative candidate and aggregator output-token budgets."""

    effective_config = _resolve_ranking_config(ranking_config)
    minimum_tokens = _ranking_int(
        effective_config, "context", "output_budget", "minimum_tokens"
    )
    default_tokens = _ranking_int(
        effective_config, "context", "output_budget", "default_tokens"
    )
    aggregator_tokens = max(
        minimum_tokens,
        configured_output_tokens
        if configured_output_tokens > 0
        else default_tokens,
    )
    if candidate_max_chars <= 0:
        return aggregator_tokens, aggregator_tokens
    # A character cap is not four ASCII characters per token for CJK and other
    # dense scripts. One token per retained character is a safer routing bound.
    # Ensemble members resolve their own generation caps, so the routed anchor's
    # configured cap must not reduce this candidate-text bound.
    chars_per_token = _ranking_number(
        effective_config, "context", "token_estimation", "candidate_chars_per_token"
    )
    candidate_tokens = math.ceil(candidate_max_chars / chars_per_token)
    return max(minimum_tokens, candidate_tokens), aggregator_tokens


def _bounded_text(value: Any, max_chars: int) -> str:
    if isinstance(value, str):
        return value[:max_chars]
    if value is None:
        return ""
    if isinstance(value, (Mapping, list, tuple)):
        try:
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)[
                :max_chars
            ]
        except (TypeError, ValueError):
            pass
    return str(value)[:max_chars]


def _bounded_string_list(
    value: Any,
    *,
    max_items: int,
    max_chars: int,
    max_scanned_items_multiplier: int,
) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    result: list[str] = []
    seen: set[str] = set()
    max_scanned_items = max_items * max_scanned_items_multiplier
    for scanned_items, item in enumerate(value, start=1):
        if scanned_items > max_scanned_items:
            break
        text = _bounded_text(item, max_chars).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= max_items:
            break
    return result


def _sanitize_last_route(
    value: Any, ranking_config: Mapping[str, Any]
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    last_route_max_models = _ranking_int(
        ranking_config, "context", "request_limits", "last_route_max_models"
    )
    item_max_chars = _ranking_int(
        ranking_config, "context", "request_limits", "item_max_chars"
    )
    scan_multiplier = _ranking_int(
        ranking_config,
        "context",
        "request_limits",
        "max_scanned_items_multiplier",
    )
    selected_p = _bounded_string_list(
        value.get("selected_P"),
        max_items=last_route_max_models,
        max_chars=item_max_chars,
        max_scanned_items_multiplier=scan_multiplier,
    )
    selected_a = _bounded_text(value.get("selected_A"), item_max_chars).strip()
    if not selected_p and not selected_a:
        return {}
    default_feedback = _ranking_number(
        ranking_config, "session", "default_quality_feedback"
    )
    max_escalation = _ranking_int(
        ranking_config, "session", "max_escalation_level"
    )
    route: dict[str, Any] = {
        "selected_P": selected_p,
        "selected_A": selected_a,
        "quality_feedback": _clamp(
            _as_float(value.get("quality_feedback"), default_feedback)
        ),
        "escalation_level": max(
            0,
            min(max_escalation, _as_int(value.get("escalation_level"), 0)),
        ),
    }
    return route


def _estimated_tokens_from_text(
    value: str, ranking_config: Mapping[str, Any]
) -> int:
    bytes_per_token = _ranking_number(
        ranking_config, "context", "token_estimation", "utf8_bytes_per_token"
    )
    return math.ceil(len(value.encode("utf-8")) / bytes_per_token)


def mock_user_profile(
    ranking_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the replaceable Step2 chapter-4 global default profile."""

    effective_config = _resolve_ranking_config(ranking_config)
    return copy.deepcopy(dict(_ranking_mapping(effective_config, "mock_user_profile")))


def build_request_context(
    *,
    message: str,
    turn_metadata: Mapping[str, Any] | None,
    attachments: Sequence[Mapping[str, Any]] | None,
    candidate_output_tokens: int,
    aggregator_output_tokens: int,
    ranking_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the temporary chapter-2 request context without logging raw input."""

    effective_config = _resolve_ranking_config(ranking_config)
    limits = _ranking_mapping(effective_config, "context", "request_limits")
    max_recent_turns = _as_int(limits["max_recent_turns"])
    fallback_history_max_turns = _as_int(limits["fallback_history_max_turns"])
    turn_max_chars = _as_int(limits["turn_max_chars"])
    summary_max_chars = _as_int(limits["summary_max_chars"])
    state_max_items = _as_int(limits["state_max_items"])
    item_max_chars = _as_int(limits["item_max_chars"])
    tool_summary_max_chars = _as_int(limits["tool_summary_max_chars"])
    test_results_max_chars = _as_int(limits["test_results_max_chars"])
    intermediate_max_items = _as_int(limits["intermediate_max_items"])
    intermediate_max_chars = _as_int(limits["intermediate_max_chars"])
    attachment_max_items = _as_int(limits["attachment_max_items"])
    scan_multiplier = _as_int(limits["max_scanned_items_multiplier"])
    minimum_tokens = _ranking_int(
        effective_config, "context", "output_budget", "minimum_tokens"
    )
    default_modalities = _ranking_string_list(
        effective_config, "hard_filter", "default_required_modalities"
    )
    metadata = dict(turn_metadata or {})
    supplied = metadata.get("router_dynamic_request_context") or metadata.get("request_context")
    supplied_map = supplied if isinstance(supplied, Mapping) else {}
    supplied_conversation = supplied_map.get("conversation")
    conversation_raw = supplied_conversation if isinstance(supplied_conversation, Mapping) else {}
    conversation: dict[str, Any] = {
        "summary": _bounded_text(conversation_raw.get("summary"), summary_max_chars)
    }
    recent_turns = conversation_raw.get("recent_turns")
    if not isinstance(recent_turns, Sequence) or isinstance(recent_turns, str):
        recent_turns = []
    conversation["recent_turns"] = [
        _bounded_recent_turn(value, effective_config)
        for value in deque(recent_turns, maxlen=max_recent_turns)
    ]
    if not conversation["recent_turns"]:
        history = metadata.get("router_history_user_texts")
        if isinstance(history, Sequence) and not isinstance(history, str):
            conversation["recent_turns"] = [
                f"user: {str(value)[:turn_max_chars]}"
                for value in deque(history, maxlen=fallback_history_max_turns)
            ]
        previous_assistant = str(metadata.get("router_prev_assistant_text") or "").strip()
        if previous_assistant:
            conversation["recent_turns"].append(
                f"assistant: {previous_assistant[:turn_max_chars]}"
            )

    supplied_tool_state = supplied_map.get("tool_state")
    tool_raw = supplied_tool_state if isinstance(supplied_tool_state, Mapping) else {}
    tool_state = {
        "called_tools": _bounded_string_list(
            tool_raw.get("called_tools"),
            max_items=state_max_items,
            max_chars=item_max_chars,
            max_scanned_items_multiplier=scan_multiplier,
        ),
        "tool_results_summary": _bounded_text(
            tool_raw.get("tool_results_summary"),
            tool_summary_max_chars,
        ),
        "failed_tools": _bounded_string_list(
            tool_raw.get("failed_tools"),
            max_items=state_max_items,
            max_chars=item_max_chars,
            max_scanned_items_multiplier=scan_multiplier,
        ),
    }
    supplied_workspace = supplied_map.get("workspace_state")
    workspace_raw = supplied_workspace if isinstance(supplied_workspace, Mapping) else {}
    workspace_state = {
        "referenced_files": _bounded_string_list(
            workspace_raw.get("referenced_files"),
            max_items=state_max_items,
            max_chars=item_max_chars,
            max_scanned_items_multiplier=scan_multiplier,
        ),
        "changed_files": _bounded_string_list(
            workspace_raw.get("changed_files"),
            max_items=state_max_items,
            max_chars=item_max_chars,
            max_scanned_items_multiplier=scan_multiplier,
        ),
        "test_results": _bounded_text(
            workspace_raw.get("test_results") or "unknown",
            test_results_max_chars,
        ),
    }
    supplied_intermediate = supplied_map.get("intermediate_outputs")
    intermediate_raw = supplied_intermediate if isinstance(supplied_intermediate, Mapping) else {}
    intermediate_outputs = {
        "previous_candidates": _bounded_string_list(
            intermediate_raw.get("previous_candidates"),
            max_items=intermediate_max_items,
            max_chars=intermediate_max_chars,
            max_scanned_items_multiplier=scan_multiplier,
        ),
        "current_errors": _bounded_string_list(
            intermediate_raw.get("current_errors"),
            max_items=intermediate_max_items,
            max_chars=intermediate_max_chars,
            max_scanned_items_multiplier=scan_multiplier,
        ),
    }
    supplied_last_route = supplied_map.get("last_route")
    if not isinstance(supplied_last_route, Mapping):
        supplied_last_route = metadata.get("router_dynamic_last_route") or metadata.get(
            "last_route"
        )
    last_route = _sanitize_last_route(supplied_last_route, effective_config)

    modalities = list(default_modalities)
    attachment_refs: list[str] = []
    for index, attachment_value in enumerate(attachments or []):
        if index >= attachment_max_items:
            break
        attachment = attachment_value if isinstance(attachment_value, Mapping) else {}
        media_type = ""
        for key in ("type", "mime", "media_type", "mime_type"):
            value = attachment.get(key)
            if isinstance(value, str) and value:
                media_type = value.lower()
                break
        media_family = media_type.split("/", 1)[0]
        modality = media_family if media_family in {"image", "audio", "video"} else "file"
        if modality not in modalities:
            modalities.append(modality)
        attachment_refs.append(
            _bounded_text(
                attachment.get("name") or attachment.get("filename") or f"attachment-{index + 1}",
                item_max_chars,
            )
        )
    attachment_refs = _bounded_string_list(
        attachment_refs,
        max_items=attachment_max_items,
        max_chars=item_max_chars,
        max_scanned_items_multiplier=scan_multiplier,
    )
    if attachment_refs:
        workspace_state["referenced_files"] = _bounded_string_list(
            [*attachment_refs, *workspace_state["referenced_files"]],
            max_items=state_max_items,
            max_chars=item_max_chars,
            max_scanned_items_multiplier=scan_multiplier,
        )

    normalization = metadata.get("input_normalization")
    normalization_map = normalization if isinstance(normalization, Mapping) else {}
    supplied_budget = supplied_map.get("routing_budget")
    supplied_budget_map = supplied_budget if isinstance(supplied_budget, Mapping) else {}
    auxiliary_context = {
        "workspace_state": workspace_state,
        "intermediate_outputs": intermediate_outputs,
        "last_route": last_route,
        "input_modalities": modalities,
        "attachment_refs": attachment_refs,
    }
    estimated_from_content = _estimated_tokens_from_text(
        message
        + json.dumps(
            {"conversation": conversation, **auxiliary_context},
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ),
        effective_config,
    )
    estimated_input_tokens = max(
        _as_int(metadata.get("input_tokens"), 0),
        _as_int(metadata.get("material_estimated_tokens"), 0),
        _as_int(normalization_map.get("material_estimated_tokens"), 0),
        _as_int(supplied_budget_map.get("estimated_input_tokens"), 0),
        estimated_from_content,
        minimum_tokens,
    )
    has_tool_state = bool(
        tool_state["called_tools"]
        or tool_state["tool_results_summary"]
        or tool_state["failed_tools"]
    )
    estimated_tool_tokens = (
        _estimated_tokens_from_text(
            json.dumps(
                tool_state,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            ),
            effective_config,
        )
        if has_tool_state
        else 0
    )
    routing_budget = {
        "estimated_input_tokens": estimated_input_tokens,
        "tool_log_tokens": max(
            0,
            _as_int(metadata.get("tool_log_tokens"), 0),
            _as_int(supplied_budget_map.get("tool_log_tokens"), 0),
            estimated_tool_tokens,
        ),
        "candidate_output_tokens": max(minimum_tokens, candidate_output_tokens),
        "aggregator_output_tokens": max(minimum_tokens, aggregator_output_tokens),
    }
    context = {
        "conversation": conversation,
        "tool_state": tool_state,
        "workspace_state": workspace_state,
        "intermediate_outputs": intermediate_outputs,
        "last_route": last_route,
        "routing_budget": routing_budget,
        "input_modalities": modalities,
        "attachment_refs": attachment_refs,
    }
    context["snapshot_hash"] = _canonical_hash(
        {
            "conversation": conversation,
            "tool_state": context.get("tool_state"),
            "workspace_state": context.get("workspace_state"),
            "intermediate_outputs": context.get("intermediate_outputs"),
            "last_route": context.get("last_route"),
            "routing_budget": routing_budget,
            "input_modalities": modalities,
            "attachment_refs": attachment_refs,
        }
    )
    return context


def fallback_task_profile(
    *,
    routed_tier: str,
    request_context: Mapping[str, Any],
    ranking_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a conservative, schema-valid profile when task analysis fails."""

    effective_config = _resolve_ranking_config(ranking_config)
    router_tier_mapping = _router_tier_mapping(effective_config)
    tier = router_tier_mapping[_router_tier(routed_tier, effective_config)]
    budget = request_context.get("routing_budget")
    budget_map = budget if isinstance(budget, Mapping) else {}
    input_tokens = _as_int(budget_map.get("estimated_input_tokens"), 0)
    default_modalities = _ranking_string_list(
        effective_config, "hard_filter", "default_required_modalities"
    )
    modalities = [
        item
        for item in request_context.get("input_modalities", default_modalities)
        if str(item) in MODALITIES
    ]
    if not modalities:
        modalities = list(default_modalities)
    fallback_constraints = _ranking_mapping(
        effective_config, "fallback_task_profile", "constraints"
    )
    risk = _ranking_string(
        effective_config, "fallback_task_profile", "risk_by_tier", str(tier)
    )
    return {
        "capability_dist": copy.deepcopy(
            dict(
                _ranking_mapping(
                    effective_config, "fallback_task_profile", "capability_dist"
                )
            )
        ),
        "domain_dist": copy.deepcopy(
            dict(
                _ranking_mapping(
                    effective_config, "fallback_task_profile", "domain_dist"
                )
            )
        ),
        "tier_dist": {str(tier): 1.0},
        "constraints": {
            "cost": str(fallback_constraints["cost"]),
            "latency": str(fallback_constraints["latency"]),
            "context": _context_bucket_for_tokens(input_tokens, effective_config),
            "modality": modalities,
            "risk": risk,
        },
        "optional_constraints": {},
        "session_intent": copy.deepcopy(
            dict(
                _ranking_mapping(
                    effective_config, "fallback_task_profile", "session_intent"
                )
            )
        ),
    }


def normalize_task_profile(
    raw_profile: Any,
    *,
    routed_tier: str,
    request_context: Mapping[str, Any],
    ranking_config: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], bool, list[str]]:
    """Validate and normalize a task-analyzer payload into the Step2 schema."""

    effective_config = _resolve_ranking_config(ranking_config)
    fallback = fallback_task_profile(
        routed_tier=routed_tier,
        request_context=request_context,
        ranking_config=effective_config,
    )
    if not isinstance(raw_profile, Mapping):
        return fallback, False, ["profile_not_object"]

    errors: list[str] = []
    capability, valid_capability = _normalize_distribution(
        raw_profile.get("capability_dist"), CAPABILITIES, fallback["capability_dist"]
    )
    domain, valid_domain = _normalize_distribution(
        raw_profile.get("domain_dist"), DOMAINS, fallback["domain_dist"]
    )
    tier, valid_tier = _normalize_distribution(
        raw_profile.get("tier_dist"), TIERS, fallback["tier_dist"]
    )
    if not valid_capability:
        errors.append("invalid_capability_dist")
    if not valid_domain:
        errors.append("invalid_domain_dist")
    if not valid_tier:
        errors.append("invalid_tier_dist")

    constraints_raw = raw_profile.get("constraints")
    if not isinstance(constraints_raw, Mapping):
        constraints_raw = {}
        errors.append("invalid_constraints")
    configured_constraint_values = _ranking_mapping(
        effective_config, "task_profile_schema", "constraint_values"
    )
    allowed_values = {
        key: {str(item) for item in value}
        for key, value in configured_constraint_values.items()
    }
    allowed_values["context"] = set(_context_bucket_min_tokens(effective_config))
    constraints: dict[str, Any] = {}
    for key, allowed in allowed_values.items():
        value = str(constraints_raw.get(key) or "").strip().lower()
        if value not in allowed:
            value = str(fallback["constraints"][key])
            errors.append(f"invalid_constraint_{key}")
        constraints[key] = value
    raw_modalities = constraints_raw.get("modality")
    if isinstance(raw_modalities, Sequence) and not isinstance(raw_modalities, str):
        modalities = list(dict.fromkeys(str(item).lower() for item in raw_modalities))
        modalities = [item for item in modalities if item in MODALITIES]
    else:
        modalities = []
    if not modalities:
        modalities = list(fallback["constraints"]["modality"])
        errors.append("invalid_constraint_modality")
    context_modalities_raw = request_context.get("input_modalities")
    default_modalities = _ranking_string_list(
        effective_config, "hard_filter", "default_required_modalities"
    )
    context_modalities = (
        [
            str(item).strip().lower()
            for item in context_modalities_raw
            if str(item).strip().lower() in MODALITIES
        ]
        if isinstance(context_modalities_raw, Sequence)
        and not isinstance(context_modalities_raw, str)
        else default_modalities
    )
    missing_context_modalities = [
        modality for modality in context_modalities if modality not in modalities
    ]
    if missing_context_modalities:
        modalities.extend(missing_context_modalities)
        errors.append("missing_request_modality")
    constraints["modality"] = modalities

    optional: dict[str, Any] = {}
    optional_raw = raw_profile.get("optional_constraints")
    if isinstance(optional_raw, Mapping) and optional_raw.get("format") is not None:
        output_format = str(optional_raw.get("format") or "").strip().lower()
        if output_format in FORMATS:
            optional["format"] = output_format
        else:
            errors.append("invalid_optional_format")

    intent_raw = raw_profile.get("session_intent")
    if not isinstance(intent_raw, Mapping):
        intent_raw = {}
        errors.append("invalid_session_intent")
    default_intent = _ranking_string(
        effective_config, "task_profile_schema", "default_session_intent"
    )
    allowed_intents = _ranking_string_set(
        effective_config, "task_profile_schema", "session_intents"
    )
    intent_type = str(intent_raw.get("type") or default_intent).strip().lower()
    if intent_type not in allowed_intents:
        intent_type = default_intent
        errors.append("invalid_session_intent_type")
    intent_confidence = _clamp(_as_float(intent_raw.get("confidence"), 0.0))
    last_route = request_context.get("last_route")
    if intent_type != default_intent and not isinstance(last_route, Mapping):
        intent_type = default_intent
        intent_confidence = 0.0
    elif intent_type != default_intent and not last_route:
        intent_type = default_intent
        intent_confidence = 0.0

    profile = {
        "capability_dist": capability,
        "domain_dist": domain,
        "tier_dist": tier,
        "constraints": constraints,
        "optional_constraints": optional,
        "session_intent": {"type": intent_type, "confidence": intent_confidence},
    }
    required_valid = not errors
    return profile, required_valid, errors


def _extract_json_object(text: str) -> Any:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        return value
    raise ValueError("task analyzer returned no JSON object")


async def analyze_task_with_provider(
    *,
    provider: LLMProvider | None,
    message: str,
    user_profile: Mapping[str, Any],
    request_context: Mapping[str, Any],
    routed_tier: str,
    routing_confidence: float,
    timeout_seconds: float | None = None,
    usage_tracker: Any | None = None,
    session_key: str | None = None,
    analyzer_provider_id: str = "",
    analyzer_model_id: str = "",
    ranking_config: Mapping[str, Any] | None = None,
) -> TaskAnalysisResult:
    """Use the caller-supplied dedicated provider as the task analyzer."""

    effective_config = _resolve_ranking_config(ranking_config)
    analyzer_input_max_chars = _ranking_int(
        effective_config, "task_analyzer", "input_max_chars"
    )
    analyzer_response_max_chars = _ranking_int(
        effective_config, "task_analyzer", "response_max_chars"
    )
    analyzer_max_output_tokens = _ranking_int(
        effective_config, "task_analyzer", "max_output_tokens"
    )
    analyzer_temperature = _ranking_number(
        effective_config, "task_analyzer", "temperature"
    )
    analyzer_thinking = _ranking_bool(
        effective_config, "task_analyzer", "thinking"
    )
    effective_timeout = (
        _ranking_number(effective_config, "task_analyzer", "timeout_seconds")
        if timeout_seconds is None
        else timeout_seconds
    )
    profile_decimal_places = _ranking_int(
        effective_config, "trace", "profile_decimal_places"
    )
    fallback = fallback_task_profile(
        routed_tier=routed_tier,
        request_context=request_context,
        ranking_config=effective_config,
    )
    provider_id = analyzer_provider_id.strip() or str(
        getattr(provider, "provider_name", "") or ""
    )
    model_id = analyzer_model_id.strip() or str(getattr(provider, "model", "") or "")
    if provider is None:
        return TaskAnalysisResult(
            profile=fallback,
            source="router_fallback",
            schema_valid=False,
            confidence=_clamp(routing_confidence),
            fallback_reason="provider_unavailable",
            provider_id=provider_id,
            model_id=model_id,
        )

    system_prompt = (
        "You are a task-profile classifier. Return one JSON object only. "
        "Required keys: capability_dist, domain_dist, tier_dist, constraints, "
        "session_intent. Distributions must use only the supplied enum values, "
        "contain non-negative numbers, and each sum to 1. constraints requires "
        "cost, latency, context, modality, and risk. You may add an "
        "optional_constraints object containing format and an "
        "analysis_confidence number from 0 to 1. Do not answer the user's task."
    )
    analysis_message = message
    if len(analysis_message) > analyzer_input_max_chars:
        truncation_marker = "\n[task input truncated for classification]\n"[
            :analyzer_input_max_chars
        ]
        retained_chars = analyzer_input_max_chars - len(truncation_marker)
        head_fraction = _ranking_number(
            effective_config, "task_analyzer", "truncation_head_fraction"
        )
        head_chars = math.floor(retained_chars * head_fraction)
        tail_chars = retained_chars - head_chars
        tail = analysis_message[-tail_chars:] if tail_chars else ""
        analysis_message = analysis_message[:head_chars] + truncation_marker + tail
    constraint_values = _ranking_mapping(
        effective_config, "task_profile_schema", "constraint_values"
    )
    analyzer_input = {
        "task": analysis_message,
        "allowed_capabilities": list(CAPABILITIES),
        "allowed_domains": list(DOMAINS),
        "allowed_tiers": list(TIERS),
        "allowed_modalities": list(MODALITIES),
        "allowed_constraints": {
            "cost": list(constraint_values["cost"]),
            "latency": list(constraint_values["latency"]),
            "context": list(_context_bucket_min_tokens(effective_config)),
            "risk": list(constraint_values["risk"]),
        },
        "allowed_formats": list(FORMATS),
        "allowed_session_intents": _ranking_string_list(
            effective_config, "task_profile_schema", "session_intents"
        ),
        "request_context": request_context,
        "user_profile": user_profile,
    }
    log.info(
        "llm_ensemble.router_dynamic.task_analyzer_started",
        analyzer_version=TASK_ANALYZER_VERSION,
        provider=provider_id or "unknown",
        model=model_id,
        input_chars=len(message),
        input_truncated=len(analysis_message) < len(message),
        request_context_hash=request_context.get("snapshot_hash"),
    )
    usage: dict[str, Any] = {}
    try:
        stream = provider.chat(
            [Message(role="user", content=json.dumps(analyzer_input, ensure_ascii=True))],
            tools=None,
            config=ChatConfig(
                max_tokens=analyzer_max_output_tokens,
                temperature=analyzer_temperature,
                system=system_prompt,
                thinking=analyzer_thinking,
                timeout=effective_timeout,
            ),
        )
        text_parts: list[str] = []
        total_chars = 0
        got_done = False
        try:
            async with asyncio.timeout(effective_timeout):
                async for event in stream:
                    if isinstance(event, TextDeltaEvent):
                        total_chars += len(event.text)
                        if total_chars > analyzer_response_max_chars:
                            raise ValueError("task analyzer response exceeded size limit")
                        text_parts.append(event.text)
                    elif isinstance(event, DoneEvent):
                        got_done = True
                        usage = {
                            "model": event.model,
                            "input_tokens": event.input_tokens,
                            "output_tokens": event.output_tokens,
                            "reasoning_tokens": event.reasoning_tokens,
                            "cached_tokens": event.cached_tokens,
                            "cache_write_tokens": event.cache_write_tokens,
                            "billed_cost": event.billed_cost,
                            "cost_source": event.cost_source,
                        }
                        if usage_tracker is not None and session_key:
                            try:
                                usage_tracker.add(
                                    session_key,
                                    input_tokens=event.input_tokens,
                                    output_tokens=event.output_tokens,
                                    model_id=event.model,
                                    provider=provider_id,
                                    cache_read_tokens=event.cached_tokens,
                                    cache_write_tokens=event.cache_write_tokens,
                                    billed_cost=event.billed_cost,
                                )
                            except Exception:  # noqa: BLE001 - accounting cannot break routing
                                log.warning(
                                    "llm_ensemble.router_dynamic.task_analyzer_usage_failed",
                                    provider=provider_id or "unknown",
                                    model=model_id,
                                )
                        break
                    elif isinstance(event, ErrorEvent):
                        raise RuntimeError(f"provider_error:{event.code or 'unknown'}")
        finally:
            aclose = getattr(stream, "aclose", None)
            if callable(aclose):
                with contextlib.suppress(Exception):
                    await aclose()
        if not got_done:
            raise RuntimeError("task analyzer stream ended before DoneEvent")
        payload = _extract_json_object("".join(text_parts))
        profile, schema_valid, errors = normalize_task_profile(
            payload,
            routed_tier=routed_tier,
            request_context=request_context,
            ranking_config=effective_config,
        )
        if not schema_valid:
            raise ValueError(";".join(errors) or "invalid task profile")
    except Exception as exc:  # noqa: BLE001 - analysis must fail open to a safe profile
        reason = type(exc).__name__
        log.warning(
            "llm_ensemble.router_dynamic.task_analyzer_fallback",
            analyzer_version=TASK_ANALYZER_VERSION,
            reason=reason,
            provider=provider_id or "unknown",
            model=model_id,
            routed_tier=_router_tier(routed_tier, effective_config),
        )
        return TaskAnalysisResult(
            profile=fallback,
            source="router_fallback",
            schema_valid=False,
            confidence=_clamp(routing_confidence),
            fallback_reason=reason,
            usage=usage,
            provider_id=provider_id,
            model_id=model_id,
        )

    payload_map = payload if isinstance(payload, Mapping) else {}
    default_confidence = _ranking_number(
        effective_config, "task_analyzer", "default_confidence"
    )
    confidence = _clamp(
        _as_float(payload_map.get("analysis_confidence"), default_confidence)
    )
    log.info(
        "llm_ensemble.router_dynamic.task_analyzer_completed",
        analyzer_version=TASK_ANALYZER_VERSION,
        provider=provider_id,
        model=model_id,
        schema_valid=True,
        confidence=round(confidence, profile_decimal_places),
        profile_hash=_canonical_hash(profile),
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        billed_cost=usage.get("billed_cost", 0.0),
    )
    return TaskAnalysisResult(
        profile=profile,
        source="llm_provider",
        schema_valid=True,
        confidence=confidence,
        usage=usage,
        provider_id=provider_id,
        model_id=model_id,
    )


def _validate_registry_snapshot(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise DynamicRankingError("router_dynamic model registry snapshot must be an object")
    snapshot = copy.deepcopy(dict(raw))
    models = snapshot.get("models")
    if not isinstance(models, list):
        raise DynamicRankingError("router_dynamic model registry snapshot is malformed")
    if not str(snapshot.get("schema_version") or "").strip() or not str(
        snapshot.get("snapshot_version") or ""
    ).strip():
        raise DynamicRankingError(
            "router_dynamic model registry snapshot requires schema and snapshot versions"
        )

    identities: set[tuple[str, str]] = set()
    for index, row in enumerate(models):
        if not isinstance(row, Mapping):
            raise DynamicRankingError(
                f"router_dynamic model registry row {index} must be an object"
            )
        facts = row.get("registry_facts")
        static_profile = row.get("static_profile")
        if not isinstance(facts, Mapping) or not isinstance(static_profile, Mapping):
            raise DynamicRankingError(
                f"router_dynamic model registry row {index} lacks facts or static profile"
            )
        provider = str(facts.get("provider") or "").strip().lower()
        model_id = str(facts.get("model_id") or "").strip().lower()
        if not provider or not model_id:
            raise DynamicRankingError(
                f"router_dynamic model registry row {index} lacks provider/model_id"
            )
        identity = (provider, model_id)
        if identity in identities:
            raise DynamicRankingError(
                "router_dynamic model registry snapshot contains duplicate model identities"
            )
        identities.add(identity)
        for optional_object in ("runtime", "online_profile"):
            value = row.get(optional_object)
            if value is not None and not isinstance(value, Mapping):
                raise DynamicRankingError(
                    "router_dynamic model registry row "
                    f"{index} has invalid {optional_object}"
                )
    return snapshot


@cache
def _packaged_registry_snapshot() -> dict[str, Any]:
    try:
        path = resources.files("opensquilla.provider").joinpath(
            "router_dynamic_model_profiles.json"
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - surfaced as a precise startup/build error
        raise DynamicRankingError("router_dynamic model registry snapshot unavailable") from exc
    return _validate_registry_snapshot(payload)


def load_model_registry_snapshot() -> dict[str, Any]:
    """Return an isolated copy of the packaged mock chapter-5 snapshot."""

    return copy.deepcopy(_packaged_registry_snapshot())


def _split_model_identity(
    provider: str,
    model_id: str,
    ranking_config: Mapping[str, Any],
) -> tuple[str, str]:
    model_lower = model_id.lower()
    if "/" in model_lower:
        vendor, name = model_lower.split("/", 1)
    else:
        vendor, name = provider.lower(), model_lower
    pieces = name.replace("_", "-").split("-")
    family_name_parts = _ranking_int(
        ranking_config, "synthetic_model", "family_name_parts"
    )
    family = (
        "-".join(pieces[:family_name_parts])
        if len(pieces) >= family_name_parts
        else name
    )
    return vendor or provider.lower(), family or model_lower


def _synthesized_model(
    *,
    provider: str,
    model_id: str,
    source: str,
    routed_tier: str,
    roles: Sequence[str] = ("proposer", "aggregator"),
    modalities: Sequence[str] = ("text",),
    ranking_config: Mapping[str, Any],
) -> dict[str, Any]:
    router_tier_mapping = _router_tier_mapping(ranking_config)
    tier = router_tier_mapping[_router_tier(routed_tier, ranking_config)]
    vendor, family = _split_model_identity(provider, model_id, ranking_config)
    base_strength = _ranking_number(
        ranking_config, "synthetic_model", "base_strength_by_tier", str(tier)
    )
    tier_penalty = _ranking_number(
        ranking_config, "synthetic_model", "tier_strength_penalty_per_level"
    )
    aggregator_fit_minimum = _ranking_number(
        ranking_config, "synthetic_model", "aggregator_role_fit_minimum"
    )
    aggregator_fit_penalty = _ranking_number(
        ranking_config, "synthetic_model", "aggregator_role_fit_penalty"
    )
    return {
        "source": source,
        "runtime": {
            "thinking": _ranking_string(
                ranking_config, "synthetic_model", "thinking"
            )
        },
        "registry_facts": {
            "model_id": model_id,
            "version": _ranking_string(
                ranking_config, "synthetic_model", "version"
            ),
            "provider": provider,
            "vendor": vendor,
            "family": family,
            "status": _ranking_string(ranking_config, "synthetic_model", "status"),
            "roles": list(dict.fromkeys(roles)),
            "context_window": _ranking_int(
                ranking_config, "synthetic_model", "context_window"
            ),
            "effective_context_bucket": _ranking_string(
                ranking_config, "synthetic_model", "effective_context_bucket"
            ),
            "modalities": list(dict.fromkeys(modalities)),
            "tools": [],
            "price": {
                "input_per_million": _ranking_number(
                    ranking_config, "synthetic_model", "price_input_per_million"
                ),
                "output_per_million": _ranking_number(
                    ranking_config, "synthetic_model", "price_output_per_million"
                ),
            },
            "latency_p50_ms": _ranking_int(
                ranking_config, "synthetic_model", "latency_p50_ms"
            ),
            "latency_p95_ms": _ranking_int(
                ranking_config, "synthetic_model", "latency_p95_ms"
            ),
            "quota": _ranking_string(ranking_config, "synthetic_model", "quota"),
            "rate_limit": _ranking_string(
                ranking_config, "synthetic_model", "rate_limit"
            ),
            "health": _ranking_string(ranking_config, "synthetic_model", "health"),
        },
        "static_profile": {
            "capability_dist_prior": {name: base_strength for name in CAPABILITIES},
            "domain_dist_prior": {name: base_strength for name in DOMAINS},
            "tier_dist_prior": {
                tier_name: _clamp(
                    base_strength
                    - tier_penalty * max(0, _as_int(tier_name) - tier)
                )
                for tier_name in TIERS
            },
            "role_fit_prior": {
                "proposer": base_strength,
                "aggregator": max(
                    aggregator_fit_minimum,
                    base_strength - aggregator_fit_penalty,
                ),
            },
        },
        "online_profile": {"error_rates": {}},
    }


def _template_for_model(
    templates: Sequence[Mapping[str, Any]], model_id: str
) -> dict[str, Any] | None:
    target = model_id.strip().lower()
    target_basename = target.rsplit("/", 1)[-1]
    basename_matches: list[Mapping[str, Any]] = []
    for row in templates:
        facts = row.get("registry_facts")
        if not isinstance(facts, Mapping):
            continue
        candidate = str(facts.get("model_id") or "").strip().lower()
        if candidate == target:
            return copy.deepcopy(dict(row))
        if "/" not in target and candidate.rsplit("/", 1)[-1] == target_basename:
            basename_matches.append(row)
    if len(basename_matches) == 1:
        return copy.deepcopy(dict(basename_matches[0]))
    return None


def build_model_registry_snapshot(
    *,
    inherited_provider: str,
    inherited_model: str,
    routed_tier: str,
    anchor_modalities: Sequence[str] = ("text",),
    operator_candidates: Sequence[Mapping[str, Any]] = (),
    legacy_model_options: Sequence[str] = (),
    router_tiers: Mapping[str, Any] | None = None,
    packaged_snapshot: Mapping[str, Any] | None = None,
    ranking_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose the mock snapshot with runtime and operator-defined deployments."""

    effective_config = _resolve_ranking_config(ranking_config)
    base = (
        _validate_registry_snapshot(packaged_snapshot)
        if packaged_snapshot is not None
        else load_model_registry_snapshot()
    )
    templates_raw = base.get("models")
    if not isinstance(templates_raw, list):
        raise DynamicRankingError("router_dynamic model registry has no models list")
    templates = list(templates_raw)
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    rows_by_identity: dict[tuple[str, str], dict[str, Any]] = {}

    def add(
        *,
        provider: str,
        model_id: str,
        source: str,
        roles: Sequence[str] = ("proposer", "aggregator"),
        modalities: Sequence[str] = ("text",),
        thinking: str | None = "xhigh",
        override_existing_roles: bool = False,
    ) -> None:
        provider_normalized = provider.strip().lower()
        model_normalized = model_id.strip()
        identity = (provider_normalized, model_normalized.lower())
        if not provider_normalized or not model_normalized:
            return
        if identity in seen:
            if override_existing_roles:
                existing_facts = rows_by_identity[identity].get("registry_facts")
                if isinstance(existing_facts, dict):
                    existing_facts["roles"] = list(dict.fromkeys(roles))
            return
        row = _template_for_model(templates, model_normalized) or _synthesized_model(
            provider=provider_normalized,
            model_id=model_normalized,
            source=source,
            routed_tier=routed_tier,
            roles=roles,
            modalities=modalities,
            ranking_config=effective_config,
        )
        facts = row.setdefault("registry_facts", {})
        facts["provider"] = provider_normalized
        facts["model_id"] = model_normalized
        facts["roles"] = list(dict.fromkeys(roles or facts.get("roles") or []))
        row["source"] = source
        runtime = row.setdefault("runtime", {})
        runtime["thinking"] = thinking
        seen.add(identity)
        rows_by_identity[identity] = row
        rows.append(row)

    add(
        provider=inherited_provider,
        model_id=inherited_model,
        source="router_anchor",
        modalities=anchor_modalities,
        thinking=None,
    )
    for candidate in operator_candidates:
        if candidate.get("enabled", True) is False:
            continue
        role = str(candidate.get("role") or "").strip().lower()
        roles = ("aggregator",) if role == "aggregator" else ("proposer",)
        add(
            provider=str(candidate.get("provider") or inherited_provider),
            model_id=str(candidate.get("model") or ""),
            source=str(candidate.get("source") or "custom"),
            roles=roles,
            override_existing_roles=True,
        )
    for model_id in legacy_model_options:
        model = str(model_id or "").strip()
        add(
            provider="openrouter" if "/" in model else inherited_provider,
            model_id=model,
            source="legacy_model_options",
        )
    for tier_name, tier_config in (router_tiers or {}).items():
        if not isinstance(tier_config, Mapping):
            continue
        add(
            provider=str(tier_config.get("provider") or inherited_provider),
            model_id=str(tier_config.get("model") or ""),
            source=f"router_tier:{tier_name}",
            thinking=str(tier_config.get("thinking_level") or "xhigh"),
        )
    for template in templates:
        facts = template.get("registry_facts")
        if not isinstance(facts, Mapping):
            continue
        add(
            provider=str(facts.get("provider") or "openrouter"),
            model_id=str(facts.get("model_id") or ""),
            source=str(template.get("source") or "mock_registry"),
            roles=[str(item) for item in facts.get("roles") or []],
            modalities=[str(item) for item in facts.get("modalities") or ["text"]],
            thinking=str((template.get("runtime") or {}).get("thinking") or "xhigh"),
        )

    return {
        "snapshot_version": str(base.get("snapshot_version") or "mock-unknown"),
        "schema_version": str(base.get("schema_version") or "step2-model-registry-v1"),
        "models": rows,
    }


def _normalize_model(
    row: Mapping[str, Any], ranking_config: Mapping[str, Any]
) -> RankedModel:
    facts_raw = row.get("registry_facts")
    profile_raw = row.get("static_profile")
    if not isinstance(facts_raw, Mapping) or not isinstance(profile_raw, Mapping):
        raise DynamicRankingError("model registry row lacks facts or static profile")
    facts = copy.deepcopy(dict(facts_raw))
    model_id = str(facts.get("model_id") or "").strip()
    provider = str(facts.get("provider") or "").strip().lower()
    if not model_id or not provider:
        raise DynamicRankingError("model registry row lacks provider/model_id")
    online = row.get("online_profile")
    runtime = row.get("runtime")
    default_thinking = _ranking_string(
        ranking_config, "synthetic_model", "thinking"
    )
    thinking_value = (
        runtime.get("thinking") if isinstance(runtime, Mapping) else default_thinking
    )
    return RankedModel(
        provider=provider,
        model_id=model_id,
        version=str(
            facts.get("version")
            or _ranking_string(ranking_config, "synthetic_model", "version")
        ),
        source=str(row.get("source") or "registry"),
        registry_facts=facts,
        static_profile=copy.deepcopy(dict(profile_raw)),
        online_profile=copy.deepcopy(dict(online)) if isinstance(online, Mapping) else {},
        thinking=None if thinking_value is None else str(thinking_value),
    )


def _permission_matches(model: RankedModel, values: Sequence[Any]) -> bool:
    normalized = {str(value).strip().lower() for value in values}
    return model.model_id.lower() in normalized or model.identity.lower() in normalized


def _routing_budget(
    request_context: Mapping[str, Any], ranking_config: Mapping[str, Any]
) -> dict[str, int]:
    raw = request_context.get("routing_budget")
    values = raw if isinstance(raw, Mapping) else {}
    default_output_tokens = _ranking_int(
        ranking_config, "context", "output_budget", "default_tokens"
    )
    minimum_tokens = _ranking_int(
        ranking_config, "context", "output_budget", "minimum_tokens"
    )
    return {
        "input": max(0, _as_int(values.get("estimated_input_tokens"), 0)),
        "tools": max(0, _as_int(values.get("tool_log_tokens"), 0)),
        "candidate": max(
            minimum_tokens,
            _as_int(values.get("candidate_output_tokens"), default_output_tokens),
        ),
        "aggregator": max(
            minimum_tokens,
            _as_int(values.get("aggregator_output_tokens"), default_output_tokens),
        ),
    }


def _context_need(
    *,
    role: str,
    task_profile: Mapping[str, Any],
    request_context: Mapping[str, Any],
    proposer_count: int,
    ranking_config: Mapping[str, Any],
) -> int:
    constraints = task_profile.get("constraints")
    constraint_map = constraints if isinstance(constraints, Mapping) else {}
    default_bucket = _ranking_string(ranking_config, "context", "default_bucket")
    bucket = str(constraint_map.get("context") or default_bucket)
    budget = _routing_budget(request_context, ranking_config)
    bucket_min_tokens = _context_bucket_min_tokens(ranking_config)
    input_tokens = max(
        budget["input"],
        bucket_min_tokens.get(bucket, bucket_min_tokens[default_bucket]),
    )
    if role == "aggregator":
        return (
            input_tokens
            + budget["tools"]
            + proposer_count * budget["candidate"]
            + budget["aggregator"]
        )
    return input_tokens + budget["tools"] + budget["candidate"]


def _availability_reasons(
    model: RankedModel, role: str, ranking_config: Mapping[str, Any]
) -> list[str]:
    facts = model.registry_facts
    reasons: list[str] = []
    eligible_statuses = {
        value.lower()
        for value in _ranking_string_set(
            ranking_config, "hard_filter", "eligible_statuses"
        )
    }
    if str(facts.get("status") or "").lower() not in eligible_statuses:
        reasons.append("status_unavailable")
    if not bool(facts.get("credential_available", True)):
        reasons.append("credential_unavailable")
    default_health = _ranking_string(ranking_config, "hard_filter", "default_health")
    unavailable_health = {
        value.lower()
        for value in _ranking_string_set(
            ranking_config, "hard_filter", "unavailable_health_states"
        )
    }
    if str(facts.get("health") or default_health).lower() in unavailable_health:
        reasons.append("health_unavailable")
    default_quota = _ranking_string(ranking_config, "hard_filter", "default_quota")
    unavailable_quota = {
        value.lower()
        for value in _ranking_string_set(
            ranking_config, "hard_filter", "unavailable_quota_states"
        )
    }
    quota = facts.get("quota", default_quota)
    if (isinstance(quota, (int, float)) and quota <= 0) or str(
        quota
    ).lower() in unavailable_quota:
        reasons.append("quota_exhausted")
    default_rate_limit = _ranking_string(
        ranking_config, "hard_filter", "default_rate_limit"
    )
    unavailable_rate_limits = {
        value.lower()
        for value in _ranking_string_set(
            ranking_config, "hard_filter", "unavailable_rate_limit_states"
        )
    }
    rate_limit = str(facts.get("rate_limit") or default_rate_limit).lower()
    if rate_limit in unavailable_rate_limits:
        reasons.append("rate_limited")
    if role.lower() not in {str(value).strip().lower() for value in facts.get("roles") or []}:
        reasons.append(f"role_{role}_unsupported")
    return reasons


def _hard_filter_reasons(
    model: RankedModel,
    *,
    role: str,
    task_profile: Mapping[str, Any],
    user_profile: Mapping[str, Any],
    request_context: Mapping[str, Any],
    proposer_count: int,
    ranking_config: Mapping[str, Any],
) -> tuple[list[str], int]:
    reasons = _availability_reasons(model, role, ranking_config)
    permission = user_profile.get("permission")
    permission_map = permission if isinstance(permission, Mapping) else {}
    allowed = permission_map.get("allow_models")
    denied = permission_map.get("deny_models")
    allowed_values = (
        allowed if isinstance(allowed, Sequence) and not isinstance(allowed, str) else []
    )
    denied_values = denied if isinstance(denied, Sequence) and not isinstance(denied, str) else []
    if allowed_values and not _permission_matches(model, allowed_values):
        reasons.append("no_permission")
    if denied_values and _permission_matches(model, denied_values):
        reasons.append("no_permission")

    constraints = task_profile.get("constraints")
    constraint_map = constraints if isinstance(constraints, Mapping) else {}
    risk_allowlist = permission_map.get("risk_allowlist")
    if isinstance(risk_allowlist, Sequence) and not isinstance(risk_allowlist, str):
        allowed_risks = {str(value).strip().lower() for value in risk_allowlist}
        task_risk = str(constraint_map.get("risk") or "low").strip().lower()
        if allowed_risks and task_risk not in allowed_risks:
            reasons.append("risk_not_allowed")
    default_modalities = _ranking_string_list(
        ranking_config, "hard_filter", "default_required_modalities"
    )
    required_modalities = {
        str(value).strip().lower()
        for value in constraint_map.get("modality") or default_modalities
    }
    supported_modalities = {
        str(value).strip().lower() for value in model.registry_facts.get("modalities") or []
    }
    if not required_modalities.issubset(supported_modalities):
        reasons.append("modality_mismatch")

    context_need = _context_need(
        role=role,
        task_profile=task_profile,
        request_context=request_context,
        proposer_count=proposer_count,
        ranking_config=ranking_config,
    )
    if _as_int(model.registry_facts.get("context_window"), 0) < context_need:
        reasons.append("context_exceeded")
    return list(dict.fromkeys(reasons)), context_need


def _strength(
    model: RankedModel,
    profile_key: str,
    dimension: str,
    ranking_config: Mapping[str, Any],
) -> float:
    raw = model.static_profile.get(profile_key)
    values = raw if isinstance(raw, Mapping) else {}
    default = _ranking_number(ranking_config, "task_match", "missing_strength_default")
    return _clamp(_as_float(values.get(dimension), default))


def _expectation(
    model: RankedModel,
    distribution: Mapping[str, Any],
    profile_key: str,
    ranking_config: Mapping[str, Any],
) -> float:
    return sum(
        _as_float(weight)
        * _strength(model, profile_key, str(dimension), ranking_config)
        for dimension, weight in distribution.items()
    )


def _role_fit(
    model: RankedModel, role: str, ranking_config: Mapping[str, Any]
) -> float:
    raw = model.static_profile.get("role_fit_prior")
    values = raw if isinstance(raw, Mapping) else {}
    default = _ranking_number(ranking_config, "task_match", "missing_role_fit_default")
    return _clamp(_as_float(values.get(role), default))


def _task_match(
    model: RankedModel,
    task_profile: Mapping[str, Any],
    ranking_config: Mapping[str, Any],
    *,
    role: str | None,
) -> float:
    capability = task_profile.get("capability_dist")
    domain = task_profile.get("domain_dist")
    tier = task_profile.get("tier_dist")
    capability_map = capability if isinstance(capability, Mapping) else {}
    domain_map = domain if isinstance(domain, Mapping) else {}
    tier_map = tier if isinstance(tier, Mapping) else {}
    parts = [
        (
            _ranking_number(ranking_config, "task_match", "capability_weight"),
            _expectation(
                model, capability_map, "capability_dist_prior", ranking_config
            ),
        ),
        (
            _ranking_number(ranking_config, "task_match", "domain_weight"),
            _expectation(model, domain_map, "domain_dist_prior", ranking_config),
        ),
        (
            _ranking_number(ranking_config, "task_match", "tier_weight"),
            _expectation(model, tier_map, "tier_dist_prior", ranking_config),
        ),
    ]
    match = sum(weight * value for weight, value in parts)
    if role is not None:
        match = (
            _ranking_number(ranking_config, "task_match", "proposer_task_weight")
            * match
            + _ranking_number(
                ranking_config, "task_match", "proposer_role_fit_weight"
            )
            * _role_fit(model, role, ranking_config)
        )

    constraints = task_profile.get("constraints")
    constraints_map = constraints if isinstance(constraints, Mapping) else {}
    default_bucket = _ranking_string(ranking_config, "context", "default_bucket")
    requested_bucket = str(constraints_map.get("context") or default_bucket)
    available_bucket = str(
        model.registry_facts.get("effective_context_bucket") or default_bucket
    )
    bucket_min_tokens = _context_bucket_min_tokens(ranking_config)
    default_bucket_minimum = bucket_min_tokens[default_bucket]
    if bucket_min_tokens.get(
        available_bucket, default_bucket_minimum
    ) < bucket_min_tokens.get(requested_bucket, default_bucket_minimum):
        match *= _ranking_number(
            ranking_config, "task_match", "context_underqualified_multiplier"
        )
    optional = task_profile.get("optional_constraints")
    if isinstance(optional, Mapping) and optional.get("format"):
        format_strength = _strength(
            model, "capability_dist_prior", "format_following", ranking_config
        )
        match *= _ranking_number(
            ranking_config, "task_match", "format_base_multiplier"
        ) + _ranking_number(
            ranking_config, "task_match", "format_strength_multiplier"
        ) * format_strength
    return _clamp(match)


def _user_score(
    model: RankedModel,
    user_profile: Mapping[str, Any],
    task_profile: Mapping[str, Any],
    ranking_config: Mapping[str, Any],
) -> float:
    history = user_profile.get("history")
    history_map = history if isinstance(history, Mapping) else {}
    positive = history_map.get("positive_model_ids")
    negative = history_map.get("negative_model_ids")
    positive_values = (
        positive if isinstance(positive, Sequence) and not isinstance(positive, str) else []
    )
    negative_values = (
        negative if isinstance(negative, Sequence) and not isinstance(negative, str) else []
    )
    signal = int(_permission_matches(model, positive_values)) - int(
        _permission_matches(model, negative_values)
    )
    saturation = _ranking_number(
        ranking_config, "user_score", "feedback_saturation_count"
    )
    confidence = min(
        1.0, max(0, _as_int(history_map.get("feedback_count"), 0)) / saturation
    )
    score = _ranking_number(
        ranking_config, "user_score", "neutral_score"
    ) + _ranking_number(
        ranking_config, "user_score", "history_signal_weight"
    ) * signal * confidence
    optional = task_profile.get("optional_constraints")
    preference = user_profile.get("preference")
    preference_map = preference if isinstance(preference, Mapping) else {}
    if not isinstance(optional, Mapping) or not optional.get("format"):
        preferred = preference_map.get("preferred_formats")
        if isinstance(preferred, Sequence) and preferred:
            score += _ranking_number(
                ranking_config, "user_score", "preferred_format_bonus"
            ) * _strength(
                model, "capability_dist_prior", "format_following", ranking_config
            )
    return _clamp(score)


def _model_in_last_route(model: RankedModel, last_route: Mapping[str, Any]) -> bool:
    values: list[Any] = []
    selected_p = last_route.get("selected_P")
    if isinstance(selected_p, Sequence) and not isinstance(selected_p, str):
        values.extend(selected_p)
    selected_a = last_route.get("selected_A")
    if selected_a:
        values.append(selected_a)
    return _permission_matches(model, values)


def _session_score(
    model: RankedModel,
    task_profile: Mapping[str, Any],
    request_context: Mapping[str, Any],
    ranking_config: Mapping[str, Any],
) -> float:
    intent = task_profile.get("session_intent")
    intent_map = intent if isinstance(intent, Mapping) else {}
    if _as_float(intent_map.get("confidence"), 0.0) < _ranking_number(
        ranking_config, "session", "intent_confidence_threshold"
    ):
        return 0.0
    last_route = request_context.get("last_route")
    if not isinstance(last_route, Mapping) or not _model_in_last_route(model, last_route):
        return 0.0
    intent_type = str(intent_map.get("type") or "new_task")
    if intent_type == "continue":
        default_feedback = _ranking_number(
            ranking_config, "session", "default_quality_feedback"
        )
        feedback = _clamp(
            _as_float(last_route.get("quality_feedback"), default_feedback)
        )
        return _ranking_number(ranking_config, "session", "score_delta") * feedback
    if intent_type == "redo":
        return -_ranking_number(ranking_config, "session", "score_delta")
    return 0.0


def _model_price(model: RankedModel, ranking_config: Mapping[str, Any]) -> float:
    raw = model.registry_facts.get("price")
    if isinstance(raw, Mapping):
        input_price = _as_float(
            raw.get("input_per_million", raw.get("input", raw.get("prompt"))), 0.0
        )
        output_price = _as_float(
            raw.get("output_per_million", raw.get("output", raw.get("completion"))), 0.0
        )
        return (
            _ranking_number(
                ranking_config, "normalization", "price_input_weight"
            )
            * input_price
            + _ranking_number(
                ranking_config, "normalization", "price_output_weight"
            )
            * output_price
        )
    return max(0.0, _as_float(raw, 0.0))


def _cost_latency_weights(
    task_profile: Mapping[str, Any],
    user_profile: Mapping[str, Any],
    ranking_config: Mapping[str, Any],
) -> tuple[float, float]:
    constraints = task_profile.get("constraints")
    constraints_map = constraints if isinstance(constraints, Mapping) else {}
    default_cost = _ranking_number(ranking_config, "penalties", "default_cost_weight")
    default_latency = _ranking_number(
        ranking_config, "penalties", "default_latency_weight"
    )
    task_cost_weights = _ranking_mapping(
        ranking_config, "penalties", "task_cost_weights"
    )
    task_latency_weights = _ranking_mapping(
        ranking_config, "penalties", "task_latency_weights"
    )
    cost_weight = _as_float(
        task_cost_weights.get(str(constraints_map.get("cost") or "medium")),
        default_cost,
    )
    latency_weight = _as_float(
        task_latency_weights.get(str(constraints_map.get("latency") or "normal")),
        default_latency,
    )
    preference = user_profile.get("preference")
    preference_map = preference if isinstance(preference, Mapping) else {}
    sensitivity = str(preference_map.get("cost_sensitivity") or "medium")
    sensitivity_weights = _ranking_mapping(
        ranking_config, "penalties", "user_cost_sensitivity_weights"
    )
    cost_weight = max(
        cost_weight,
        _as_float(sensitivity_weights.get(sensitivity), default_cost),
    )
    tradeoff = str(preference_map.get("quality_latency_tradeoff") or "balanced")
    if tradeoff == "latency_first":
        latency_weight += _ranking_number(
            ranking_config, "penalties", "latency_first_adjustment"
        )
    elif tradeoff == "quality_first":
        minimum = _ranking_number(
            ranking_config, "penalties", "quality_first_minimum_weight"
        )
        latency_weight = max(
            minimum,
            latency_weight
            - _ranking_number(
                ranking_config, "penalties", "quality_first_latency_reduction"
            ),
        )
        cost_weight = max(
            minimum,
            cost_weight
            - _ranking_number(
                ranking_config, "penalties", "quality_first_cost_reduction"
            ),
        )
    return cost_weight, latency_weight


def _base_score_row(
    model: RankedModel,
    task_profile: Mapping[str, Any],
    user_profile: Mapping[str, Any],
    request_context: Mapping[str, Any],
    ranking_config: Mapping[str, Any],
) -> dict[str, Any]:
    task_match = _task_match(
        model, task_profile, ranking_config, role="proposer"
    )
    user_score = _user_score(model, user_profile, task_profile, ranking_config)
    session_score = _session_score(
        model, task_profile, request_context, ranking_config
    )
    quality_clean = (
        _ranking_number(ranking_config, "quality", "task_match_weight")
        * task_match
        + _ranking_number(ranking_config, "quality", "user_score_weight")
        * user_score
    )
    quality = _clamp(quality_clean + session_score)
    price_reference = _ranking_number(
        ranking_config, "normalization", "price_reference_usd_per_million"
    )
    latency_reference = _ranking_number(
        ranking_config, "normalization", "latency_reference_ms"
    )
    cost_normalized = _clamp(_model_price(model, ranking_config) / price_reference)
    latency = _as_float(
        model.registry_facts.get("latency_p95_ms", model.registry_facts.get("latency_p95")),
        latency_reference,
    )
    latency_normalized = _clamp(latency / latency_reference)
    cost_weight, latency_weight = _cost_latency_weights(
        task_profile, user_profile, ranking_config
    )
    return {
        "model": model,
        "task_match": task_match,
        "user_score": user_score,
        "session_score": session_score,
        "quality_clean": quality_clean,
        "quality": quality,
        "cost_normalized": cost_normalized,
        "latency_normalized": latency_normalized,
        "cost_weight": cost_weight,
        "latency_weight": latency_weight,
        "base_clean": quality_clean
        - cost_weight * cost_normalized
        - latency_weight * latency_normalized,
        "base": quality - cost_weight * cost_normalized - latency_weight * latency_normalized,
    }


def _score_trace(
    row: Mapping[str, Any], ranking_config: Mapping[str, Any]
) -> dict[str, Any]:
    model = row["model"]
    decimal_places = _ranking_int(
        ranking_config, "trace", "score_decimal_places"
    )
    return {
        "identity": model.identity,
        "model": model.model_id,
        "provider": model.provider,
        "S_match": round(_as_float(row.get("task_match")), decimal_places),
        "S_user": round(_as_float(row.get("user_score")), decimal_places),
        "S_session": round(_as_float(row.get("session_score")), decimal_places),
        "S_qual_clean": round(_as_float(row.get("quality_clean")), decimal_places),
        "S_qual": round(_as_float(row.get("quality")), decimal_places),
        "cost": round(_as_float(row.get("cost_normalized")), decimal_places),
        "latency": round(_as_float(row.get("latency_normalized")), decimal_places),
        "cost_weight": round(_as_float(row.get("cost_weight")), decimal_places),
        "latency_weight": round(_as_float(row.get("latency_weight")), decimal_places),
        "S_base_clean": round(_as_float(row.get("base_clean")), decimal_places),
        "S_base": round(_as_float(row.get("base")), decimal_places),
    }


def _shift_tier_distribution(
    tier_dist: Mapping[str, Any], ranking_config: Mapping[str, Any]
) -> dict[str, float]:
    shifted: dict[str, float] = {}
    tier_values = _router_tier_mapping(ranking_config).values()
    minimum_tier = min(tier_values)
    maximum_tier = max(tier_values)
    for tier, weight in tier_dist.items():
        destination = str(
            min(
                maximum_tier,
                max(minimum_tier, _as_int(tier, minimum_tier)) + 1,
            )
        )
        shifted[destination] = shifted.get(destination, 0.0) + _as_float(weight)
    total = sum(shifted.values()) or 1.0
    return {tier: weight / total for tier, weight in shifted.items()}


def _apply_session_adjustment(
    task_profile: Mapping[str, Any],
    request_context: Mapping[str, Any],
    ranking_config: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    before = copy.deepcopy(dict(task_profile))
    adjusted = copy.deepcopy(dict(task_profile))
    intent = adjusted.get("session_intent")
    intent_map = intent if isinstance(intent, Mapping) else {}
    intent_type = str(intent_map.get("type") or "new_task")
    intent_confidence = _as_float(intent_map.get("confidence"), 0.0)
    confidence_threshold = _ranking_number(
        ranking_config, "session", "intent_confidence_threshold"
    )
    max_escalation_level = _ranking_int(
        ranking_config, "session", "max_escalation_level"
    )
    profile_decimal_places = _ranking_int(
        ranking_config, "trace", "profile_decimal_places"
    )
    if intent_confidence < confidence_threshold:
        intent_type = "new_task"
    last_route = request_context.get("last_route")
    last_route_map = last_route if isinstance(last_route, Mapping) else {}
    if intent_type != "new_task" and not last_route_map:
        intent_type = "new_task"
    previous_escalation = max(0, _as_int(last_route_map.get("escalation_level"), 0))
    escalation_level = previous_escalation
    tier_shifted = False
    if intent_type == "redo" and previous_escalation < max_escalation_level:
        tier_dist = adjusted.get("tier_dist")
        if isinstance(tier_dist, Mapping):
            adjusted["tier_dist"] = _shift_tier_distribution(
                tier_dist, ranking_config
            )
            tier_shifted = True
        escalation_level += 1
    elif intent_type == "new_task":
        escalation_level = 0
    return adjusted, {
        "intent": intent_type,
        "intent_confidence": round(intent_confidence, profile_decimal_places),
        "sticky_applied": intent_type == "continue",
        "tier_shifted": tier_shifted,
        "previous_escalation_level": previous_escalation,
        "escalation_level": min(max_escalation_level, escalation_level),
        "task_profile_pre_escalation": before,
        "task_profile_post_escalation": copy.deepcopy(adjusted),
    }


def _effective_tier(
    task_profile: Mapping[str, Any], ranking_config: Mapping[str, Any]
) -> int:
    raw = task_profile.get("tier_dist")
    router_tier_mapping = _router_tier_mapping(ranking_config)
    default_router_tier = _ranking_string(
        ranking_config, "routing_tiers", "default_router_tier"
    )
    default_tier = router_tier_mapping[default_router_tier]
    tier_dist = raw if isinstance(raw, Mapping) else {str(default_tier): 1.0}
    expected = sum(
        _as_int(tier, default_tier) * _as_float(weight)
        for tier, weight in tier_dist.items()
    )
    rounding_offset = _ranking_number(
        ranking_config, "proposer_count", "effective_tier_rounding_offset"
    )
    tier_values = _router_tier_mapping(ranking_config).values()
    return max(
        min(tier_values),
        min(max(tier_values), math.floor(expected + rounding_offset)),
    )


def _proposer_bounds(
    task_profile: Mapping[str, Any],
    user_profile: Mapping[str, Any],
    ranking_config: Mapping[str, Any],
) -> tuple[int, int, list[str]]:
    tier = _effective_tier(task_profile, ranking_config)
    tier_key = str(tier)
    minimum = _ranking_int(
        ranking_config, "proposer_count", "by_tier", tier_key, "min"
    )
    maximum = _ranking_int(
        ranking_config, "proposer_count", "by_tier", tier_key, "max"
    )
    constraints = task_profile.get("constraints")
    constraints_map = constraints if isinstance(constraints, Mapping) else {}
    reasons = [f"tier_{tier}"]
    if str(constraints_map.get("risk") or "low") == "high":
        minimum = max(
            minimum,
            _ranking_int(ranking_config, "proposer_count", "high_risk", "min"),
        )
        maximum = max(
            maximum,
            _ranking_int(ranking_config, "proposer_count", "high_risk", "max"),
        )
        reasons.append("high_risk_cross_validation")
    preference = user_profile.get("preference")
    preference_map = preference if isinstance(preference, Mapping) else {}
    constrained = (
        str(constraints_map.get("cost"))
        in _ranking_string_set(
            ranking_config, "proposer_count", "constrained_cost_values"
        )
        or str(constraints_map.get("latency"))
        in _ranking_string_set(
            ranking_config, "proposer_count", "constrained_latency_values"
        )
        or str(preference_map.get("cost_sensitivity"))
        in _ranking_string_set(
            ranking_config, "proposer_count", "constrained_user_cost_values"
        )
        or str(preference_map.get("quality_latency_tradeoff"))
        in _ranking_string_set(
            ranking_config, "proposer_count", "constrained_user_tradeoffs"
        )
    )
    if constrained:
        maximum = min(
            maximum,
            _ranking_int(ranking_config, "proposer_count", "constrained_max"),
        )
        minimum = min(minimum, maximum)
        reasons.append("cost_or_latency_constrained")
    return minimum, maximum, reasons


def _capability_vector(
    model: RankedModel, ranking_config: Mapping[str, Any]
) -> list[float]:
    return [
        _strength(model, "capability_dist_prior", capability, ranking_config)
        for capability in CAPABILITIES
    ]


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    return _clamp(numerator / (left_norm * right_norm))


def _similarity(
    left: RankedModel,
    right: RankedModel,
    ranking_config: Mapping[str, Any],
) -> float:
    capability_similarity = _cosine(
        _capability_vector(left, ranking_config),
        _capability_vector(right, ranking_config),
    )
    if left.family == right.family:
        family_similarity = _ranking_number(
            ranking_config, "rerank", "similarity", "same_family_score"
        )
    elif left.vendor == right.vendor:
        family_similarity = _ranking_number(
            ranking_config, "rerank", "similarity", "same_vendor_score"
        )
    else:
        family_similarity = _ranking_number(
            ranking_config, "rerank", "similarity", "unrelated_score"
        )
    return _clamp(
        _ranking_number(
            ranking_config, "rerank", "similarity", "capability_weight"
        )
        * capability_similarity
        + _ranking_number(
            ranking_config, "rerank", "similarity", "lineage_weight"
        )
        * family_similarity
    )


def _coverage_gain(
    candidate: RankedModel,
    selected: Sequence[RankedModel],
    task_profile: Mapping[str, Any],
    ranking_config: Mapping[str, Any],
) -> float:
    raw = task_profile.get("capability_dist")
    capability_dist = raw if isinstance(raw, Mapping) else {}
    gain = 0.0
    for capability, weight in capability_dist.items():
        candidate_strength = _strength(
            candidate, "capability_dist_prior", str(capability), ranking_config
        )
        selected_max = max(
            (
                _strength(
                    model,
                    "capability_dist_prior",
                    str(capability),
                    ranking_config,
                )
                for model in selected
            ),
            default=0.0,
        )
        gain += _as_float(weight) * max(0.0, candidate_strength - selected_max)
    return gain


def _error_vector(
    model: RankedModel, ranking_config: Mapping[str, Any]
) -> list[float]:
    raw = model.online_profile.get("error_rates")
    values = raw if isinstance(raw, Mapping) else {}
    raw_dimensions = _ranking_value(ranking_config, "rerank", "error_dimensions")
    dimensions = [str(name) for name in raw_dimensions]
    return [_clamp(_as_float(values.get(name), 0.0)) for name in dimensions]


def _error_complementarity(
    candidate: RankedModel,
    selected: Sequence[RankedModel],
    ranking_config: Mapping[str, Any],
) -> float:
    if not selected:
        return 0.0
    vector = _error_vector(candidate, ranking_config)
    if not any(vector):
        return 0.0
    similarities = [
        _cosine(vector, other_vector)
        for model in selected
        if any(other_vector := _error_vector(model, ranking_config))
    ]
    return 1.0 - max(similarities, default=1.0)


def _aggregator_rows(
    models: Sequence[RankedModel],
    *,
    proposers: Sequence[RankedModel],
    task_profile: Mapping[str, Any],
    user_profile: Mapping[str, Any],
    request_context: Mapping[str, Any],
    ranking_config: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    scored: list[dict[str, Any]] = []
    filters: list[dict[str, Any]] = []
    cost_weight, latency_weight = _cost_latency_weights(
        task_profile, user_profile, ranking_config
    )
    task_weight = _ranking_number(
        ranking_config, "aggregator", "task_match_weight"
    )
    role_weight = _ranking_number(ranking_config, "aggregator", "role_fit_weight")
    same_model_penalty = _ranking_number(
        ranking_config, "aggregator", "same_model_penalty"
    )
    related_penalty = _ranking_number(
        ranking_config, "aggregator", "same_family_or_vendor_penalty"
    )
    price_reference = _ranking_number(
        ranking_config, "normalization", "price_reference_usd_per_million"
    )
    latency_reference = _ranking_number(
        ranking_config, "normalization", "latency_reference_ms"
    )
    for model in models:
        reasons, context_need = _hard_filter_reasons(
            model,
            role="aggregator",
            task_profile=task_profile,
            user_profile=user_profile,
            request_context=request_context,
            proposer_count=len(proposers),
            ranking_config=ranking_config,
        )
        filters.append(
            {
                "identity": model.identity,
                "model": model.model_id,
                "role": "aggregator",
                "eligible": not reasons,
                "reasons": reasons,
                "context_need_tokens": context_need,
            }
        )
        if reasons:
            continue
        task_match = _task_match(
            model, task_profile, ranking_config, role=None
        )
        role_fit = _role_fit(model, "aggregator", ranking_config)
        quality = task_weight * task_match + role_weight * role_fit
        session_score = _session_score(
            model, task_profile, request_context, ranking_config
        )
        self_overlap = any(model.identity == proposer.identity for proposer in proposers)
        family_overlap = any(model.family == proposer.family for proposer in proposers)
        vendor_overlap = any(model.vendor == proposer.vendor for proposer in proposers)
        related_overlap = family_overlap or vendor_overlap
        bias = same_model_penalty * int(self_overlap) + related_penalty * int(
            related_overlap
        )
        cost = _clamp(_model_price(model, ranking_config) / price_reference)
        latency = _clamp(
            _as_float(
                model.registry_facts.get("latency_p95_ms", model.registry_facts.get("latency_p95")),
                latency_reference,
            )
            / latency_reference
        )
        score = quality + session_score - bias - cost_weight * cost - latency_weight * latency
        scored.append(
            {
                "model": model,
                "score": score,
                "quality": quality,
                "task_match": task_match,
                "role_fit": role_fit,
                "session_score": session_score,
                "bias": bias,
                "self_overlap": self_overlap,
                "family_overlap": family_overlap,
                "vendor_overlap": vendor_overlap,
                "cost": cost,
                "latency": latency,
                "cost_weight": cost_weight,
                "latency_weight": latency_weight,
                "context_need_tokens": context_need,
            }
        )
    scored.sort(
        key=lambda row: (
            -_as_float(row["score"]),
            -_as_float(row["quality"]),
            row["model"].identity,
        )
    )
    return scored, filters


def _aggregator_score_trace(
    row: Mapping[str, Any], ranking_config: Mapping[str, Any]
) -> dict[str, Any]:
    model = row["model"]
    decimal_places = _ranking_int(
        ranking_config, "trace", "score_decimal_places"
    )
    return {
        "identity": model.identity,
        "model": model.model_id,
        "provider": model.provider,
        "Score_agg": round(_as_float(row.get("score")), decimal_places),
        "S_agg_qual": round(_as_float(row.get("quality")), decimal_places),
        "S_match": round(_as_float(row.get("task_match")), decimal_places),
        "role_fit": round(_as_float(row.get("role_fit")), decimal_places),
        "S_session": round(_as_float(row.get("session_score")), decimal_places),
        "bias_penalty": round(_as_float(row.get("bias")), decimal_places),
        "cost": round(_as_float(row.get("cost")), decimal_places),
        "latency": round(_as_float(row.get("latency")), decimal_places),
        "cost_weight": round(_as_float(row.get("cost_weight")), decimal_places),
        "latency_weight": round(_as_float(row.get("latency_weight")), decimal_places),
        "context_need_tokens": _as_int(row.get("context_need_tokens"), 0),
        "self_overlap": bool(row.get("self_overlap")),
        "family_overlap": bool(row.get("family_overlap")),
        "vendor_overlap": bool(row.get("vendor_overlap")),
    }


def rank_models(
    *,
    task_analysis: TaskAnalysisResult,
    user_profile: Mapping[str, Any],
    request_context: Mapping[str, Any],
    registry_snapshot: Mapping[str, Any],
    routed_tier: str,
    routing_confidence: float,
    ranking_config: Mapping[str, Any] | None = None,
) -> RankingDecision:
    """Select ``(P, A)`` using the Step2 chapter-6 ranking pipeline."""

    effective_ranking_config = _resolve_ranking_config(ranking_config)
    ranking_config_hash = _canonical_hash(effective_ranking_config)
    profile_decimal_places = _ranking_int(
        effective_ranking_config, "trace", "profile_decimal_places"
    )
    score_decimal_places = _ranking_int(
        effective_ranking_config, "trace", "score_decimal_places"
    )
    session_nonzero_epsilon = _ranking_number(
        effective_ranking_config, "trace", "session_nonzero_epsilon"
    )
    rows = registry_snapshot.get("models")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise DynamicRankingError("router_dynamic registry snapshot contains no models")
    if any(not isinstance(row, Mapping) for row in rows):
        raise DynamicRankingError(
            "router_dynamic registry snapshot contains a malformed model row"
        )
    models = [
        _normalize_model(row, effective_ranking_config)
        for row in rows
    ]
    if not models:
        raise DynamicRankingError("router_dynamic registry snapshot is empty")
    model_identities = [model.identity.lower() for model in models]
    if len(set(model_identities)) != len(model_identities):
        raise DynamicRankingError(
            "router_dynamic registry snapshot contains duplicate model identities"
        )
    registry_snapshot_hash = _canonical_hash(registry_snapshot)

    task_profile, session_trace = _apply_session_adjustment(
        task_analysis.profile, request_context, effective_ranking_config
    )
    effective_tier = _effective_tier(task_profile, effective_ranking_config)
    minimum, maximum, bound_reasons = _proposer_bounds(
        task_profile, user_profile, effective_ranking_config
    )

    proposer_filters: list[dict[str, Any]] = []
    eligible: list[RankedModel] = []
    for model in models:
        reasons, context_need = _hard_filter_reasons(
            model,
            role="proposer",
            task_profile=task_profile,
            user_profile=user_profile,
            request_context=request_context,
            proposer_count=1,
            ranking_config=effective_ranking_config,
        )
        proposer_filters.append(
            {
                "identity": model.identity,
                "model": model.model_id,
                "role": "proposer",
                "eligible": not reasons,
                "reasons": reasons,
                "context_need_tokens": context_need,
            }
        )
        if not reasons:
            eligible.append(model)
    if not eligible:
        no_eligible_reason_counts: dict[str, int] = {}
        for row in proposer_filters:
            for reason in row["reasons"]:
                no_eligible_reason_counts[reason] = no_eligible_reason_counts.get(reason, 0) + 1
        log.warning(
            "llm_ensemble.router_dynamic.no_eligible_proposer",
            registry_snapshot_version=registry_snapshot.get("snapshot_version"),
            filter_reason_counts=no_eligible_reason_counts,
        )
        raise DynamicRankingError("router_dynamic has no proposer after hard filtering")

    score_rows = [
        _base_score_row(
            model,
            task_profile,
            user_profile,
            request_context,
            effective_ranking_config,
        )
        for model in eligible
    ]
    score_rows.sort(
        key=lambda row: (
            -_as_float(row["base"]),
            -_as_float(row["quality"]),
            row["model"].identity,
        )
    )
    top_l = min(
        len(score_rows),
        max(
            _ranking_int(effective_ranking_config, "rerank", "top_l_min"),
            maximum
            * _ranking_int(effective_ranking_config, "rerank", "top_l_multiplier"),
        ),
    )
    candidate_rows = score_rows[:top_l]
    best_clean = max(_as_float(row["base_clean"]) for row in candidate_rows)
    constraints = task_profile.get("constraints")
    constraints_map = constraints if isinstance(constraints, Mapping) else {}
    floor_margins = _ranking_mapping(
        effective_ranking_config, "rerank", "quality_floor_margin_by_risk"
    )
    floor_margin = _as_float(
        floor_margins.get(str(constraints_map.get("risk") or "low")),
        _ranking_number(
            effective_ranking_config, "rerank", "default_quality_floor_margin"
        ),
    )
    quality_floor = best_clean - floor_margin
    rerank_quality_weight = _ranking_number(
        effective_ranking_config, "rerank", "quality_weight"
    )
    rerank_coverage_weight = _ranking_number(
        effective_ranking_config, "rerank", "coverage_gain_weight"
    )
    rerank_error_weight = _ranking_number(
        effective_ranking_config, "rerank", "error_complementarity_weight"
    )
    rerank_similarity_penalty = _ranking_number(
        effective_ranking_config, "rerank", "similarity_penalty_weight"
    )
    stop_threshold = _ranking_number(
        effective_ranking_config, "rerank", "stop_threshold"
    )
    trace_top_candidates = _ranking_int(
        effective_ranking_config, "rerank", "trace_top_candidates"
    )

    selected: list[RankedModel] = []
    selection_steps: list[dict[str, Any]] = []
    stop_reason = "n_max_reached"
    while len(selected) < min(maximum, len(candidate_rows)):
        marginal_rows: list[dict[str, Any]] = []
        rejected_for_aggregator = 0
        for row in candidate_rows:
            model = row["model"]
            if model in selected or _as_float(row["base_clean"]) < quality_floor:
                continue
            proposed = [*selected, model]
            feasible_aggregators, _ = _aggregator_rows(
                models,
                proposers=proposed,
                task_profile=task_profile,
                user_profile=user_profile,
                request_context=request_context,
                ranking_config=effective_ranking_config,
            )
            if not feasible_aggregators:
                rejected_for_aggregator += 1
                continue
            coverage = _coverage_gain(
                model, selected, task_profile, effective_ranking_config
            )
            similarity = max(
                (
                    _similarity(model, other, effective_ranking_config)
                    for other in selected
                ),
                default=0.0,
            )
            error_complementarity = _error_complementarity(
                model, selected, effective_ranking_config
            )
            marginal = (
                rerank_quality_weight * _as_float(row["quality"])
                + rerank_coverage_weight * coverage
                + rerank_error_weight * error_complementarity
                - rerank_similarity_penalty * similarity
            )
            marginal_rows.append(
                {
                    "model": model,
                    "marginal": marginal,
                    "quality": row["quality"],
                    "coverage_gain": coverage,
                    "max_similarity": similarity,
                    "error_complementarity": error_complementarity,
                    "base_clean": row["base_clean"],
                }
            )
        if not marginal_rows:
            stop_reason = (
                "aggregator_infeasible"
                if rejected_for_aggregator
                else "quality_floor_or_pool_exhausted"
            )
            break
        marginal_rows.sort(
            key=lambda row: (
                -_as_float(row["marginal"]),
                -_as_float(row["base_clean"]),
                -_as_float(row["quality"]),
                row["model"].identity,
            )
        )
        best = marginal_rows[0]
        if (
            len(selected) >= minimum
            and _as_float(best["marginal"]) < stop_threshold
        ):
            stop_reason = "marginal_below_threshold"
            break
        selected.append(best["model"])
        selection_steps.append(
            {
                "step": len(selected),
                "selected": best["model"].identity,
                "marginal_gain": round(
                    _as_float(best["marginal"]), score_decimal_places
                ),
                "quality": round(_as_float(best["quality"]), score_decimal_places),
                "coverage_gain": round(
                    _as_float(best["coverage_gain"]), score_decimal_places
                ),
                "max_similarity": round(
                    _as_float(best["max_similarity"]), score_decimal_places
                ),
                "error_complementarity": round(
                    _as_float(best["error_complementarity"]), score_decimal_places
                ),
                "top_candidates": [
                    {
                        "identity": candidate["model"].identity,
                        "marginal_gain": round(
                            _as_float(candidate["marginal"]), score_decimal_places
                        ),
                    }
                    for candidate in marginal_rows[:trace_top_candidates]
                ],
            }
        )

    if stop_reason == "n_max_reached" and len(selected) < maximum:
        stop_reason = "candidate_pool_exhausted"

    if not selected:
        raise DynamicRankingError(
            "router_dynamic cannot select a proposer with a feasible aggregator"
        )
    aggregator_rows, aggregator_filters = _aggregator_rows(
        models,
        proposers=selected,
        task_profile=task_profile,
        user_profile=user_profile,
        request_context=request_context,
        ranking_config=effective_ranking_config,
    )
    if not aggregator_rows:
        raise DynamicRankingError("router_dynamic has no feasible aggregator")
    aggregator_row = aggregator_rows[0]
    aggregator = aggregator_row["model"]
    coverage_shortfall = len(selected) < minimum
    session_adjusted_ids = sorted(
        {
            row["model"].identity
            for row in [*score_rows, *aggregator_rows]
            if abs(_as_float(row.get("session_score"))) > session_nonzero_epsilon
        }
    )
    session_trace["sticky_applied"] = session_trace["intent"] == "continue" and bool(
        session_adjusted_ids
    )
    session_trace["adjusted_model_ids"] = session_adjusted_ids

    reason_counts: dict[str, int] = {}
    for filter_row in [*proposer_filters, *aggregator_filters]:
        for reason in filter_row["reasons"]:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
    selected_ids = [model.identity for model in selected]
    overlap = bool(
        aggregator_row["self_overlap"]
        or aggregator_row["family_overlap"]
        or aggregator_row["vendor_overlap"]
    )
    router_tier_mapping = _router_tier_mapping(effective_ranking_config)
    router_tier_by_effective_tier = {
        tier: router_tier for router_tier, tier in router_tier_mapping.items()
    }
    trace = {
        "strategy": "router_dynamic",
        "ranking_version": RANKING_VERSION,
        "ranking_config_schema_version": str(
            effective_ranking_config["schema_version"]
        ),
        "ranking_config_version": str(effective_ranking_config["config_version"]),
        "ranking_config_hash": ranking_config_hash,
        "ranking_parameters": copy.deepcopy(dict(effective_ranking_config)),
        "task_profile_schema_version": TASK_PROFILE_SCHEMA_VERSION,
        "registry_snapshot_version": str(registry_snapshot.get("snapshot_version") or ""),
        "registry_snapshot_hash": registry_snapshot_hash,
        "routed_tier": _router_tier(routed_tier, effective_ranking_config),
        "routing_confidence": round(
            _clamp(routing_confidence), profile_decimal_places
        ),
        "effective_tier": effective_tier,
        "effective_router_tier": router_tier_by_effective_tier[effective_tier],
        "task_analyzer": task_analysis.trace(effective_ranking_config),
        "task_profile": copy.deepcopy(task_profile),
        "task_profile_hash": _canonical_hash(task_profile),
        "task_profile_pre_escalation": session_trace.pop("task_profile_pre_escalation"),
        "task_profile_post_escalation": session_trace.pop("task_profile_post_escalation"),
        "session": session_trace,
        "user_profile_version": str(user_profile.get("profile_version") or ""),
        "user_profile_source": str(user_profile.get("profile_source") or ""),
        "request_context_hash": request_context.get("snapshot_hash")
        or _canonical_hash(request_context),
        "candidate_pool_size": len(models),
        "candidate_pool": [model.trace() for model in models],
        "hard_filter": {
            "proposer_results": proposer_filters,
            "aggregator_results": aggregator_filters,
            "eligible_proposer_ids": [model.identity for model in eligible],
            "eligible_aggregator_ids": [row["model"].identity for row in aggregator_rows],
            "filter_reason_counts": reason_counts,
        },
        "model_scores": [
            _score_trace(row, effective_ranking_config) for row in score_rows
        ],
        "top_l": top_l,
        "quality_floor": round(quality_floor, score_decimal_places),
        "N_min": minimum,
        "N_max": maximum,
        "bound_reasons": bound_reasons,
        "selection_steps": selection_steps,
        "selected_P": selected_ids,
        "selected_A": aggregator.identity,
        "exploration": copy.deepcopy(
            dict(_ranking_mapping(effective_ranking_config, "exploration"))
        ),
        "proposer_count": len(selected),
        "coverage_shortfall": coverage_shortfall,
        "stop_reason": stop_reason,
        "aggregator": {
            "selected": _aggregator_score_trace(
                aggregator_row, effective_ranking_config
            ),
            "scores": [
                _aggregator_score_trace(row, effective_ranking_config)
                for row in aggregator_rows
            ],
            "overlap_flag": overlap,
            "candidate_anonymization": True,
            "requires_order_randomization": overlap,
        },
    }
    log.info(
        "llm_ensemble.router_dynamic.candidate_pool_recorded",
        registry_snapshot_version=trace["registry_snapshot_version"],
        registry_snapshot_hash=registry_snapshot_hash,
        candidate_pool_size=len(models),
        eligible_proposer_count=len(eligible),
        eligible_aggregator_count=len(aggregator_rows),
        filter_reason_counts=reason_counts,
    )
    log.info(
        "llm_ensemble.router_dynamic.model_scores_recorded",
        ranking_version=RANKING_VERSION,
        score_count=len(score_rows),
        top_l=top_l,
        quality_floor=round(quality_floor, score_decimal_places),
    )
    log.info(
        "llm_ensemble.router_dynamic.proposer_selection_recorded",
        selected_P=selected_ids,
        N_min=minimum,
        N_max=maximum,
        stop_reason=stop_reason,
        coverage_shortfall=coverage_shortfall,
    )
    log.info(
        "llm_ensemble.router_dynamic.aggregator_selection_recorded",
        selected_A=aggregator.identity,
        context_need_tokens=aggregator_row["context_need_tokens"],
        overlap_flag=overlap,
        bias_penalty=round(
            _as_float(aggregator_row["bias"]), score_decimal_places
        ),
    )
    log.info(
        "llm_ensemble.router_dynamic.router_decision_recorded",
        ranking_version=RANKING_VERSION,
        selected_P=selected_ids,
        selected_A=aggregator.identity,
        session_intent=session_trace["intent"],
        escalation_level=session_trace["escalation_level"],
        sticky_applied=session_trace["sticky_applied"],
    )
    return RankingDecision(
        proposers=tuple(selected),
        aggregator=aggregator,
        effective_tier=effective_tier,
        trace=trace,
    )
