"""Step 2: Squilla router — classify message complexity and route to appropriate model.

Runs 2-level ThinkingController + PromptController on top of the routing
output.  Rollout is gated via ``squilla_router.rollout_phase`` so existing
deployments see no behavioral change until the operator opts in.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from inspect import Parameter, signature
from typing import Any, Protocol, cast

import structlog

from opensquilla.engine.pipeline import TurnContext
from opensquilla.engine.pricing import lookup_price
from opensquilla.provider.context_capabilities import provider_state_continuity_diagnostic
from opensquilla.router_control import RouterControlHoldStore
from opensquilla.router_tiers import (
    DEFAULT_TEXT_TIER,
    HIGHEST_TEXT_TIER,
    ROUTE_CLASS_TO_TIER,
    TIER_TO_ROUTE_CLASS,
    normalize_text_tier,
)
from opensquilla.squilla_router.controller import (
    derive_prompt_policy,
    derive_thinking_mode,
    get_prompt_hint,
    normalize_decisions,
    synthetic_one_hot,
    thinking_mode_to_level,
)

log = structlog.get_logger(__name__)
_log_std = logging.getLogger(__name__)


class RouterStrategy(Protocol):
    async def classify(
        self,
        message: str,
        valid_tiers: list[str],
        routing_history: list[dict] | None = None,
        **kwargs: object,
    ) -> tuple[str, float, str, dict]: ...


_strategy: RouterStrategy | None = None
_strategy_key: tuple | None = None
_strategy_lock = threading.Lock()
_router_runtime_warning_lock = threading.Lock()
_router_runtime_warning_emitted = False
_MAX_ROUTING_HISTORY = 5
_ROUTING_HISTORY_WINDOW = 1800
_ROUTER_RUNTIME_FALLBACK_MESSAGE = (
    "OpenSquilla router fallback active: bundled ONNX router failed to load. "
    "OpenSquilla can still start with safe router fallback, but bundled ONNX "
    "model routing is disabled until the router runtime is available. On Windows, "
    "Microsoft Visual C++ Redistributable 2015-2022 x64 is required for the "
    "bundled ONNX router. If automatic installation fails, install it manually: "
    "https://aka.ms/vs/17/release/vc_redist.x64.exe. After installing, reopen "
    "PowerShell and restart OpenSquilla."
)


class RoutingHistoryStore:
    """Per-session routing history with bounded size and eviction.

    Wraps the previous module-level dict so the gateway can drop entries when
    a session terminates, preventing unbounded growth in long-running
    deployments.
    """

    def __init__(self, max_entries: int = _MAX_ROUTING_HISTORY) -> None:
        self._entries: dict[str, list[dict]] = {}
        self._max_entries = max_entries

    def get(self, session_key: str) -> list[dict] | None:
        return self._entries.get(session_key)

    def set(self, session_key: str, value: list[dict]) -> None:
        self._entries[session_key] = value

    def setdefault(self, session_key: str, default: list[dict]) -> list[dict]:
        return self._entries.setdefault(session_key, default)

    def length(self, session_key: str) -> int:
        return len(self._entries.get(session_key, []))

    def clear(self) -> None:
        self._entries.clear()

    def evict(self, session_key: str) -> bool:
        return self._entries.pop(session_key, None) is not None


_history_store = RoutingHistoryStore()
_DEFER_ROUTING_HISTORY_KEY = "_defer_squilla_router_history"
_PENDING_ROUTING_HISTORY_ENTRY_KEY = "_pending_squilla_router_history_entry"
_PENDING_ROUTING_HISTORY_SESSION_KEY = "_pending_squilla_router_history_session"
_THINKING_LEVELS = {"minimal", "low", "medium", "high", "xhigh", "adaptive"}
_TIER_TO_ROUTE_CLASS = dict(TIER_TO_ROUTE_CLASS)
_ROUTE_CLASS_TO_TIER = dict(ROUTE_CLASS_TO_TIER)
_THINKING_MODE_ORDER = {"T0": 0, "T1": 1, "T2": 2, "T3": 3}
_LARGE_CONTEXT_T2_FLOOR_TOKENS = 25_000
_LARGE_CONTEXT_T3_FLOOR_TOKENS = 80_000
_LARGE_CONTEXT_T3_CONTEXT_RATIO = 0.40
_DEFAULT_CONTEXT_WINDOW_TOKENS = 200_000
_COMPLAINT_TERMS = (
    "不对",
    "不行",
    "不对劲",
    "还是不对",
    "完全不对",
    "不是这样",
    "你搞错了",
    "你说错了",
    "回答错了",
    "理解错了",
    "搞错重点了",
    "错了",
    "答非所问",
    "没理解",
    "没听懂",
    "太差",
    "太敷衍",
    "敷衍",
    "没用",
    "废话",
    "离谱",
    "乱说",
    "瞎说",
    "胡扯",
    "答得太差",
    "质量太差",
    "不满意",
    "胡说",
    "漏了",
    "遗漏了",
    "没提到",
    "没覆盖",
    "跑题了",
    "偏题了",
    "不是我要的",
    "没按要求",
    "没有按要求",
    "重写",
    "重新来",
    "重新回答",
    "再来一版",
    "换个说法",
    "重新组织",
    "按我说的重来",
    "你没有回答",
    "垃圾",
    "傻逼",
    "sb",
    "蠢",
    "废物",
    "滚",
    "妈的",
    "操",
    "艹",
    "wrong",
    "incorrect",
    "not correct",
    "you are wrong",
    "completely wrong",
    "totally wrong",
    "not what i asked",
    "you misunderstood",
    "that's not right",
    "this is not right",
    "bad answer",
    "terrible answer",
    "awful answer",
    "horrible answer",
    "poor answer",
    "lazy answer",
    "low quality",
    "poor quality",
    "try again",
    "redo",
    "rewrite",
    "start over",
    "answer again",
    "you missed",
    "missed the point",
    "off topic",
    "irrelevant",
    "not helpful",
    "garbage",
    "trash",
    "crap",
    "sucks",
    "stupid",
    "idiot",
    "moron",
    "dumb",
    "pathetic",
    "ridiculous",
    "fuck",
    "fucking",
    "shit",
    "damn",
    "wtf",
    "asshole",
    "bullshit",
    "nonsense",
    "useless",
)


def _routing_history_entry(
    *,
    text: str,
    extra: dict,
    decision: RoutingDecision,
) -> dict:
    return {
        "text": text,
        **extra,
        "base_tier": extra.get("base_tier", decision.tier),
        "final_tier": extra.get("final_tier", decision.tier),
        "final_route_class": extra.get("final_route_class"),
    }


def _append_routing_history(session_key: str, entry_payload: dict) -> list[dict]:
    history = _history_store.setdefault(session_key, [])
    entry = {
        "turn_index": len(history),
        "_ts": time.monotonic(),
        **entry_payload,
    }
    history.append(entry)
    if len(history) > _MAX_ROUTING_HISTORY:
        _history_store.set(session_key, history[-_MAX_ROUTING_HISTORY:])
    log.debug(
        "squilla_router.history_appended",
        session=session_key,
        turn_index=entry["turn_index"],
        route_class=entry.get("route_class"),
        total_history=_history_store.length(session_key),
    )
    return _history_store.get(session_key) or []


def commit_deferred_router_history(ctx: TurnContext) -> TurnContext:
    """Commit deferred routing history after a bounded router step succeeds."""

    entry_payload = ctx.metadata.pop(_PENDING_ROUTING_HISTORY_ENTRY_KEY, None)
    session_key = ctx.metadata.pop(_PENDING_ROUTING_HISTORY_SESSION_KEY, ctx.session_key)
    ctx.metadata.pop(_DEFER_ROUTING_HISTORY_KEY, None)
    if isinstance(entry_payload, dict):
        ctx.metadata["routing_history"] = _append_routing_history(session_key, entry_payload)
    return ctx


_RESPONSE_POLICY_OPEN = "[RESPONSE_POLICY:"


@dataclass
class RoutingDecision:
    """Result of squilla router classification."""

    tier: str
    model: str
    confidence: float
    source: str  # "image_route" | "v4_phase3" | "v4_unavailable" | "default"


class _UnavailableV4Strategy:
    source = "v4_unavailable"
    requires_history = True

    def __init__(self, error: Exception) -> None:
        self.error = error

    async def classify(
        self,
        message: str,
        valid_tiers: list[str],
        routing_history: list[dict] | None = None,
        **kwargs: object,
    ) -> tuple[str, float, str, dict]:
        tier = (
            DEFAULT_TEXT_TIER
            if DEFAULT_TEXT_TIER in valid_tiers
            else (valid_tiers[0] if valid_tiers else DEFAULT_TEXT_TIER)
        )
        return (
            tier,
            0.0,
            "v4_unavailable",
            {
                "route_class": "R1",
                "top1_label": "R1",
                "thinking_mode": "T1",
                "prompt_policy": "P1",
                "model_version": "unavailable",
                "error": str(self.error),
            },
        )


def _strategy_cache_key(config: object) -> tuple:
    strategy_name = _strategy_name(config)
    confidence = getattr(config, "confidence_threshold", 0.5)
    return (
        strategy_name,
        getattr(config, "v4_bundle_dir", None),
        getattr(config, "v4_use_aux_head", None),
        getattr(config, "require_router_runtime", False),
        confidence,
    )


def _strategy_name(config: object) -> str:
    configured = str(getattr(config, "strategy", "v4_phase3") or "v4_phase3")
    if configured != "v4_phase3":
        log.warning(
            "squilla_router.removed_strategy_ignored",
            strategy=configured,
            using="v4_phase3",
        )
    return "v4_phase3"


def _is_history_strategy(strategy_name: str) -> bool:
    return strategy_name == "v4_phase3"


def _warn_router_runtime_fallback_once(error: Exception | str) -> None:
    global _router_runtime_warning_emitted  # noqa: PLW0603
    with _router_runtime_warning_lock:
        if _router_runtime_warning_emitted:
            return
        _router_runtime_warning_emitted = True
    _log_std.warning("%s Error: %s", _ROUTER_RUNTIME_FALLBACK_MESSAGE, error)


def _get_strategy(config: object) -> RouterStrategy:
    global _strategy, _strategy_key  # noqa: PLW0603
    with _strategy_lock:
        key = _strategy_cache_key(config)
        if _strategy is not None and _strategy_key == key:
            return _strategy
        if _strategy_key is not None and _strategy_key != key:
            _history_store.clear()
        from opensquilla.squilla_router.v4_phase3 import V4Phase3Strategy

        try:
            strategy = cast(
                RouterStrategy,
                V4Phase3Strategy(
                    bundle_dir=getattr(config, "v4_bundle_dir", None),
                    confidence_threshold=getattr(config, "confidence_threshold", 0.5),
                    require_router_runtime=getattr(config, "require_router_runtime", False),
                    use_aux_head=getattr(config, "v4_use_aux_head", None),
                ),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("squilla_router.strategy_unavailable", error=str(exc))
            _warn_router_runtime_fallback_once(exc)
            strategy = _UnavailableV4Strategy(exc)
        else:
            if getattr(strategy, "source", "") == "v4_phase3" and not getattr(
                strategy, "_available", True
            ):
                _warn_router_runtime_fallback_once("V4 Phase 3 router did not become available")
        _strategy = strategy
        _strategy_key = key
        return strategy


def preload_strategy(config: object) -> RouterStrategy:
    return _get_strategy(config)


def _classify_context_kwargs(strategy: object, values: dict[str, object]) -> dict[str, object]:
    classify = getattr(strategy, "classify", None)
    if not callable(classify):
        return {}
    try:
        params = signature(classify).parameters
    except (TypeError, ValueError):
        return {key: value for key, value in values.items() if value is not None}
    accepts_arbitrary_kwargs = any(param.kind == Parameter.VAR_KEYWORD for param in params.values())
    return {
        key: value
        for key, value in values.items()
        if value is not None and (accepts_arbitrary_kwargs or key in params)
    }


def _normalize_thinking_level(raw: object) -> str | None:
    if isinstance(raw, bool):
        return "medium" if raw else None
    if raw is None:
        return None
    level = str(raw).strip().lower().replace("_", "-")
    aliases = {
        "x-high": "xhigh",
        "extra-high": "xhigh",
        "extra high": "xhigh",
        "max": "high",
        "highest": "high",
        "on": "low",
        "true": "medium",
        "off": "",
        "false": "",
        "none": "",
    }
    level = aliases.get(level, level)
    if not level:
        return None
    if level not in _THINKING_LEVELS:
        log.warning("squilla_router.invalid_thinking_level", value=raw)
        return None
    return level


def _tier_thinking_level(tier_cfg: dict) -> str | None:
    explicit = _normalize_thinking_level(tier_cfg.get("thinking_level", tier_cfg.get("thinking")))
    if explicit:
        return explicit
    if tier_cfg.get("supports_thinking", False):
        return "medium"
    return None


def _compute_savings(routed_model: str, tiers: dict) -> dict:
    """Return savings metadata: pct display + raw prices for per-turn USD computation.

    This intentionally follows 49b7e08: savings are the input-price delta
    between the routed model and the most-expensive configured tier. Runtime
    multiplies the same delta by the turn's input tokens to get USD savings.
    """
    text_tiers = [v for v in tiers.values() if not v.get("image_only", False)]
    priced_tiers = text_tiers or list(tiers.values())
    prices = [lookup_price(v.get("model", "")).input_per_m for v in priced_tiers]
    max_price = max(prices) if prices else 0.0
    routed_price = lookup_price(routed_model).input_per_m
    pct = (
        0.0
        if max_price <= 0 or routed_price >= max_price
        else round((max_price - routed_price) / max_price * 100, 1)
    )
    return {
        "savings_pct": pct,
        "savings_max_price_per_m": max_price,
        "savings_routed_price_per_m": routed_price,
    }


def _record_thinking_metadata(ctx: TurnContext, router_cfg: object, tier_cfg: dict) -> None:
    if not getattr(router_cfg, "auto_thinking", True):
        return
    level = _tier_thinking_level(tier_cfg)
    if level is None:
        return
    ctx.metadata["thinking_requested"] = True
    ctx.metadata["thinking_level"] = level


def _record_controller_thinking_metadata(
    ctx: TurnContext,
    router_cfg: object,
    tier_cfg: dict,
    thinking_mode: str | None,
) -> None:
    if not getattr(router_cfg, "auto_thinking", True):
        return
    if thinking_mode is not None:
        level = thinking_mode_to_level(thinking_mode)
    else:
        level = _tier_thinking_level(tier_cfg)
    if level is None:
        return
    ctx.metadata["thinking_requested"] = True
    ctx.metadata["thinking_level"] = level


def _inject_prompt_hint(message: str, hint: str) -> str:
    """Append a ``[RESPONSE_POLICY: ...]`` hint after the message; idempotent.

    Single-bracket format (not XML tags) following caveman-style guidance:
    models treat ``[Label: ...]`` as meta-instruction more reliably.
    Placed at the end with a ``---`` separator so recency bias maximises
    instruction adherence.
    """
    if _RESPONSE_POLICY_OPEN in message or not hint:
        return message
    return f"{message}\n\n---\n[RESPONSE_POLICY: {hint}]"


def _tier_index(tier: str, valid_tiers: list[str]) -> int:
    normalized = normalize_text_tier(tier) or tier
    return valid_tiers.index(normalized) if normalized in valid_tiers else -1


def _token_estimate(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return max(value, 0)
    return None


def _material_estimated_tokens(ctx: TurnContext, semantic_message: str) -> int:
    metadata = getattr(ctx, "metadata", {}) or {}
    candidates: list[int] = [max(len(semantic_message) // 4, 0)]

    top_level = _token_estimate(metadata.get("material_estimated_tokens"))
    if top_level is not None:
        candidates.append(top_level)

    normalization = metadata.get("input_normalization")
    if isinstance(normalization, dict):
        nested = _token_estimate(normalization.get("material_estimated_tokens"))
        if nested is not None:
            candidates.append(nested)

    return max(candidates)


def _context_window_tokens(ctx: TurnContext, router_cfg: object) -> int:
    for candidate in (
        getattr(router_cfg, "context_window_tokens", None),
        getattr(getattr(ctx, "config", None), "context_window_tokens", None),
        getattr(getattr(getattr(ctx, "config", None), "llm", None), "context_window_tokens", None),
    ):
        tokens = _token_estimate(candidate)
        if tokens and tokens > 0:
            return tokens
    return _DEFAULT_CONTEXT_WINDOW_TOKENS


def _large_context_min_tier(
    ctx: TurnContext,
    *,
    router_cfg: object,
    semantic_message: str,
) -> tuple[str, int] | None:
    material_tokens = _material_estimated_tokens(ctx, semantic_message)
    context_window = _context_window_tokens(ctx, router_cfg)
    if (
        material_tokens >= _LARGE_CONTEXT_T3_FLOOR_TOKENS
        or material_tokens >= int(context_window * _LARGE_CONTEXT_T3_CONTEXT_RATIO)
    ):
        return HIGHEST_TEXT_TIER, material_tokens
    if material_tokens >= _LARGE_CONTEXT_T2_FLOOR_TOKENS:
        return "c2", material_tokens
    return None


def _tier_config_value(tier_cfg: object, key: str, default: object = None) -> object:
    if isinstance(tier_cfg, dict):
        return tier_cfg.get(key, default)
    return getattr(tier_cfg, key, default)


def _upgrade_tier(tier: str, valid_tiers: list[str], steps: int) -> str:
    idx = _tier_index(tier, valid_tiers)
    if idx < 0:
        return tier
    return valid_tiers[min(idx + max(steps, 0), len(valid_tiers) - 1)]


def _confidence_protected_tier(
    tier: str,
    *,
    confidence: float,
    router_cfg: object,
    valid_tiers: list[str],
    tiers: dict | None = None,
) -> tuple[str, bool, float, str | None]:
    threshold = float(getattr(router_cfg, "confidence_threshold", 0.5))
    default_tier = getattr(router_cfg, "default_tier", None)
    if default_tier is None:
        return tier, False, threshold, None
    default_tier = normalize_text_tier(default_tier) or str(default_tier)
    selected_cfg = tiers.get(tier, {}) if isinstance(tiers, dict) else {}
    if bool(_tier_config_value(selected_cfg, "image_only", False)):
        return tier, False, threshold, default_tier
    if (
        confidence < threshold
        and tier in valid_tiers
        and default_tier in valid_tiers
        and tier != default_tier
    ):
        return default_tier, True, threshold, default_tier
    return tier, False, threshold, default_tier


def _detect_complaint(message: str, max_chars: int | None = None) -> list[str]:
    text = message.strip()
    if max_chars and max_chars > 0 and len(text) > max_chars:
        return []
    lowered = text.lower()
    return [term for term in _COMPLAINT_TERMS if term in lowered]


def _route_class_for_tier(tier: str) -> str | None:
    normalized = normalize_text_tier(tier) or tier
    return _TIER_TO_ROUTE_CLASS.get(normalized)


def _apply_large_context_floor(
    decision: RoutingDecision,
    *,
    ctx: TurnContext,
    router_cfg: object,
    tiers: dict,
    valid_tiers: list[str],
    semantic_message: str,
    extra: dict | None,
) -> RoutingDecision:
    if decision.tier not in valid_tiers:
        return decision

    floor = _large_context_min_tier(
        ctx,
        router_cfg=router_cfg,
        semantic_message=semantic_message,
    )
    if floor is None:
        return decision

    min_tier, material_tokens = floor
    if min_tier not in valid_tiers:
        return decision
    if _tier_index(decision.tier, valid_tiers) >= _tier_index(min_tier, valid_tiers):
        return decision

    floored = RoutingDecision(
        tier=min_tier,
        model=tiers[min_tier].get("model", decision.model),
        confidence=decision.confidence,
        source="large_context_floor",
    )
    ctx.metadata["large_context_floor_from_tier"] = decision.tier
    ctx.metadata["large_context_material_tokens"] = material_tokens

    if extra is not None:
        extra.setdefault("base_tier", decision.tier)
        extra["large_context_floor_applied"] = True
        extra["large_context_floor_from_tier"] = decision.tier
        extra["large_context_floor_min_tier"] = min_tier
        extra["large_context_material_tokens"] = material_tokens
        extra["large_context_pre_floor_source"] = decision.source
        extra["final_tier"] = min_tier
        extra["final_route_class"] = _route_class_for_tier(min_tier)

    return floored


def _tier_for_route_class(route_class: object) -> str | None:
    if route_class is None:
        return None
    return _ROUTE_CLASS_TO_TIER.get(str(route_class))


def _min_thinking_mode_for_tier(tier: str | None) -> str | None:
    tier = normalize_text_tier(tier)
    if tier == HIGHEST_TEXT_TIER:
        return "T3"
    if tier == "c2":
        return "T2"
    if tier == DEFAULT_TEXT_TIER:
        return "T1"
    return None


def _promote_thinking_mode(current: str | None, minimum: str | None) -> str | None:
    if minimum is None:
        return current
    if current not in _THINKING_MODE_ORDER:
        return minimum
    if _THINKING_MODE_ORDER[current] < _THINKING_MODE_ORDER[minimum]:
        return minimum
    return current


def _reconcile_controller_with_final_tier(
    thinking_mode: str | None,
    prompt_policy: str | None,
    extra: dict,
) -> tuple[str | None, str | None]:
    """Keep controller output consistent with OpenSquilla's final tier overrides."""
    final_tier = normalize_text_tier(extra.get("final_tier")) or extra.get("final_tier")
    base_tier = normalize_text_tier(extra.get("base_tier")) or extra.get("base_tier")
    if not final_tier or final_tier == base_tier:
        return thinking_mode, prompt_policy

    original_thinking = thinking_mode
    original_prompt = prompt_policy

    thinking_mode = _promote_thinking_mode(
        thinking_mode,
        _min_thinking_mode_for_tier(str(final_tier)),
    )
    if prompt_policy == "P0" and (
        str(final_tier) in {"c2", HIGHEST_TEXT_TIER} or extra.get("complaint_detected")
    ):
        prompt_policy = "P1"
    if thinking_mode is not None and prompt_policy is not None:
        thinking_mode, prompt_policy = normalize_decisions(thinking_mode, prompt_policy)

    if thinking_mode != original_thinking or prompt_policy != original_prompt:
        extra.setdefault("base_thinking_mode", original_thinking)
        extra.setdefault("base_prompt_policy", original_prompt)
        extra["thinking_mode"] = thinking_mode
        extra["prompt_policy"] = prompt_policy
        extra["controller_reconciled"] = True
    else:
        extra.setdefault("controller_reconciled", False)
    return thinking_mode, prompt_policy


def _previous_final_entry(
    routing_history: list[dict] | None,
    now: float,
    window: float,
) -> dict | None:
    if not routing_history:
        return None
    cutoff = now - window
    for entry in reversed(routing_history):
        if entry.get("_ts", now) >= cutoff:
            return entry
    return None


def _previous_final_tier(entry: dict | None) -> str | None:
    if not entry:
        return None
    tier = entry.get("final_tier")
    if tier:
        return normalize_text_tier(tier) or str(tier)
    return _tier_for_route_class(entry.get("final_route_class") or entry.get("route_class"))


def _finalize_decision(
    decision: RoutingDecision,
    *,
    router_cfg: object,
    tiers: dict,
    valid_tiers: list[str],
    message: str,
    routing_history: list[dict] | None,
    strategy_name: str,
    extra: dict,
) -> RoutingDecision:
    if not _is_history_strategy(strategy_name):
        return decision

    base_tier = normalize_text_tier(decision.tier) or decision.tier
    final_tier = base_tier
    base_route_class = extra.get("route_class") or _route_class_for_tier(base_tier)
    if base_route_class is not None:
        extra["route_class"] = base_route_class
        extra.setdefault("top1_label", base_route_class)

    pre_confidence_tier = final_tier
    (
        final_tier,
        confidence_gate_applied,
        confidence_threshold,
        confidence_default_tier,
    ) = _confidence_protected_tier(
        final_tier,
        confidence=decision.confidence,
        router_cfg=router_cfg,
        valid_tiers=valid_tiers,
        tiers=tiers,
    )

    now = time.monotonic()
    window = float(getattr(router_cfg, "kv_cache_anti_downgrade_window_seconds", 600))
    previous_entry = _previous_final_entry(
        routing_history,
        now,
        window,
    )
    previous_tier = _previous_final_tier(previous_entry)
    previous_route_class = None
    if previous_entry:
        previous_route_class = previous_entry.get("final_route_class") or previous_entry.get(
            "route_class"
        )

    complaint_terms: list[str] = []
    complaint_upgrade_applied = False
    if getattr(router_cfg, "complaint_upgrade_enabled", True):
        complaint_terms = _detect_complaint(
            message,
            max_chars=int(getattr(router_cfg, "complaint_upgrade_max_chars", 160)),
        )
        if complaint_terms:
            upgrade_start_tier = final_tier
            if previous_tier in valid_tiers and _tier_index(
                previous_tier, valid_tiers
            ) > _tier_index(upgrade_start_tier, valid_tiers):
                upgrade_start_tier = previous_tier
            upgraded_tier = _upgrade_tier(
                upgrade_start_tier,
                valid_tiers,
                int(getattr(router_cfg, "complaint_upgrade_steps", 1)),
            )
            complaint_upgrade_applied = upgraded_tier != final_tier
            final_tier = upgraded_tier

    anti_downgrade_applied = False
    if (
        getattr(router_cfg, "kv_cache_anti_downgrade_enabled", True)
        and previous_tier in valid_tiers
        and _tier_index(final_tier, valid_tiers) >= 0
        and _tier_index(previous_tier, valid_tiers) > _tier_index(final_tier, valid_tiers)
    ):
        final_tier = previous_tier
        anti_downgrade_applied = True

    final_route_class = _route_class_for_tier(final_tier)
    extra.update(
        {
            "base_tier": base_tier,
            "pre_confidence_tier": normalize_text_tier(pre_confidence_tier)
            or pre_confidence_tier,
            "confidence_threshold": confidence_threshold,
            "confidence_default_tier": confidence_default_tier,
            "confidence_gate_applied": confidence_gate_applied,
            "final_tier": final_tier,
            "final_route_class": final_route_class,
            "complaint_detected": bool(complaint_terms),
            "complaint_terms": complaint_terms,
            "complaint_upgrade_applied": complaint_upgrade_applied,
            "complaint_upgrade_steps": int(getattr(router_cfg, "complaint_upgrade_steps", 1)),
            "complaint_upgrade_max_chars": int(
                getattr(router_cfg, "complaint_upgrade_max_chars", 160)
            ),
            "anti_downgrade_applied": anti_downgrade_applied,
            "previous_tier": normalize_text_tier(previous_tier) or previous_tier,
            "previous_route_class": previous_route_class,
            "kv_cache_window_seconds": window,
        }
    )

    return RoutingDecision(
        tier=final_tier,
        model=tiers[final_tier].get("model", decision.model),
        confidence=decision.confidence,
        source=decision.source,
    )


def _apply_controller(
    ctx: TurnContext,
    router_cfg: object,
    tier_cfg: dict,
    thinking_mode: str | None,
    prompt_policy: str | None,
    prompt_hint: str | None,
    rollout_phase: str,
) -> None:
    """Apply controller decisions based on rollout phase."""
    ctx.metadata["thinking_mode"] = thinking_mode
    ctx.metadata["prompt_policy"] = prompt_policy

    if rollout_phase == "observe":
        _record_controller_thinking_metadata(ctx, router_cfg, tier_cfg, thinking_mode)
        return

    # prompt_only or full: inject prompt hint. P2 is tracked for observability
    # and thinking control, but intentionally not injected into the user text.
    if prompt_policy == "P2":
        hint = None
    else:
        hint = prompt_hint or get_prompt_hint(prompt_policy, ctx.message)
    if hint:
        ctx.message = _inject_prompt_hint(ctx.message, hint)

    if rollout_phase == "full" and getattr(router_cfg, "auto_thinking", True):
        _record_controller_thinking_metadata(ctx, router_cfg, tier_cfg, thinking_mode)
    else:
        _record_thinking_metadata(ctx, router_cfg, tier_cfg)


def _attachments_include_image(attachments: list[dict[str, Any]] | None) -> bool:
    if not attachments:
        return False
    for att in attachments:
        for key in ("type", "mime", "media_type", "mime_type"):
            media_type = att.get(key)
            if isinstance(media_type, str) and media_type.startswith("image/"):
                return True
    return False


async def apply_squilla_router(ctx: TurnContext) -> TurnContext:
    router_cfg = getattr(ctx.config, "squilla_router", None) if ctx.config else None
    if not router_cfg or not getattr(router_cfg, "enabled", False):
        return ctx

    tiers = getattr(router_cfg, "tiers", {})
    if not tiers:
        return ctx

    semantic_message = getattr(ctx, "semantic_message", None)
    if semantic_message is None:
        semantic_message = getattr(ctx, "raw_message", None)
    if semantic_message is None:
        semantic_message = ctx.message
    if not semantic_message.strip():
        return ctx
    if ":subagent:" in ctx.session_key:
        return ctx

    rollout_phase: str = getattr(router_cfg, "rollout_phase", "observe")

    # Image-aware routing: skip ML, pick directly from supports_image tiers
    # only for the current turn's uploaded attachments. Historical images are
    # reduced to text-only markers by TurnRunner._load_history and must not
    # keep later follow-ups on a vision route.
    if _attachments_include_image(ctx.attachments):
        import random

        image_tiers = {k: v for k, v in tiers.items() if v.get("supports_image", False)}
        if not image_tiers:
            log.warning(
                "squilla_router.no_image_tier",
                note="image detected but no supports_image tier",
            )
            raise RuntimeError(
                "No image-capable SquillaRouter tier is configured for this image request. "
                "Configure squilla_router.tiers.image_model with supports_image=true."
            )
        tier_name = random.choice(list(image_tiers.keys()))
        decision = RoutingDecision(
            tier=tier_name,
            model=image_tiers[tier_name].get("model", ctx.model),
            confidence=1.0,
            source="image_route",
        )
        # Vision turns are not just a text-tier routing decision: they require a
        # model that can consume image blocks. Apply this route even during
        # observe rollout so multimodal requests do not remain on a text tier.
        routing_applied = True
        ctx.metadata["baseline_model"] = ctx.model
        if routing_applied:
            ctx.model = decision.model
        ctx.metadata["routed_tier"] = decision.tier
        ctx.metadata["routed_model"] = decision.model
        ctx.metadata["routing_applied"] = routing_applied
        ctx.metadata["rollout_phase"] = rollout_phase
        ctx.metadata["applied_model"] = ctx.model
        ctx.metadata["routing_confidence"] = decision.confidence
        ctx.metadata["routing_source"] = decision.source
        ctx.metadata["route_max_history_turns"] = 1
        ctx.metadata.update(_compute_savings(decision.model, tiers))
        _record_thinking_metadata(ctx, router_cfg, image_tiers[tier_name])
        log.debug("squilla_router.image_routed", tier=decision.tier, model=decision.model)
        return ctx

    valid_tiers = [name for name, tier in tiers.items() if not tier.get("image_only", False)]
    if not valid_tiers:
        return ctx

    hold_store = ctx.metadata.get("router_control_hold_store")
    if isinstance(hold_store, RouterControlHoldStore):
        hold = hold_store.get_valid(ctx.session_key, decrement=True)
        if hold is not None and hold.tier in tiers and hold.tier in valid_tiers:
            decision = RoutingDecision(
                tier=hold.tier,
                model=hold.model,
                confidence=1.0,
                source="router_control_hold",
            )
            ctx.metadata["baseline_model"] = ctx.model
            ctx.model = decision.model
            ctx.metadata["routed_tier"] = decision.tier
            ctx.metadata["routed_model"] = decision.model
            ctx.metadata["routing_applied"] = True
            ctx.metadata["applied_model"] = ctx.model
            ctx.metadata["routing_confidence"] = decision.confidence
            ctx.metadata["routing_source"] = decision.source
            ctx.metadata["router_control_hold_applied"] = True
            ctx.metadata["router_control_action"] = "set_hold"
            ctx.metadata["router_control_target_tier"] = hold.tier
            ctx.metadata["router_control_target_model"] = hold.model
            ctx.metadata["router_control_target_provider"] = hold.provider
            ctx.metadata["router_control_evidence"] = hold.evidence
            ctx.metadata.update(_compute_savings(decision.model, tiers))
            _record_thinking_metadata(ctx, router_cfg, tiers[decision.tier])
            log.debug(
                "squilla_router.router_control_hold_applied",
                tier=decision.tier,
                model=decision.model,
                session=ctx.session_key,
            )
            return ctx

    strategy = _get_strategy(router_cfg)
    strategy_name = _strategy_name(router_cfg)
    defer_history = bool(ctx.metadata.get(_DEFER_ROUTING_HISTORY_KEY))

    # History-aware routers load accumulated routing history for this session.
    routing_history = None
    if _is_history_strategy(strategy_name):
        stored_history = _history_store.get(ctx.session_key)
        routing_history = [dict(entry) for entry in stored_history or []] or None
        if not routing_history:
            persisted = ctx.metadata.get("routing_history")
            if persisted:
                now = time.monotonic()
                routing_history = [
                    {**dict(entry), "_ts": now} if "_ts" not in entry else dict(entry)
                    for entry in persisted
                    if isinstance(entry, dict)
                ]
                if not defer_history:
                    _history_store.set(ctx.session_key, routing_history)
                    log.debug(
                        "squilla_router.history_cold_start",
                        session=ctx.session_key,
                        restored=len(routing_history),
                    )
        if routing_history:
            cutoff = time.monotonic() - _ROUTING_HISTORY_WINDOW
            routing_history = [e for e in routing_history if e.get("_ts", 0) > cutoff]
            routing_history = routing_history[-_MAX_ROUTING_HISTORY:]
            if not defer_history:
                _history_store.set(ctx.session_key, routing_history)
        log.debug(
            "squilla_router.history_loaded",
            session=ctx.session_key,
            history_len=len(routing_history) if routing_history else 0,
        )

    # --- Classification ---
    thinking_mode: str | None = None
    prompt_policy: str | None = None
    extra: dict | None = None
    probs: list[float] | None = None

    classify_context = _classify_context_kwargs(
        strategy,
        {
            "prev_assistant_text": ctx.metadata.get("router_prev_assistant_text"),
            "prev_assistant_usage": ctx.metadata.get("router_prev_assistant_usage"),
            "history_user_texts": ctx.metadata.get("router_history_user_texts"),
            "flags_text_override": ctx.metadata.get("router_flags_text_override"),
        },
    )
    tier_name, confidence, source, extra = await strategy.classify(
        semantic_message,
        valid_tiers,
        routing_history=routing_history,
        **classify_context,
    )
    tier_name = normalize_text_tier(tier_name) or tier_name
    if extra:
        ctx.metadata["routing_extra"] = extra
        thinking_mode = extra.get("thinking_mode")
        prompt_policy = extra.get("prompt_policy")

    if tier_name is None or tier_name not in tiers:
        default = normalize_text_tier(getattr(router_cfg, "default_tier", DEFAULT_TEXT_TIER))
        if default is None:
            default = DEFAULT_TEXT_TIER
        tier_name = default if default in tiers else next(iter(tiers), None)
        if tier_name is None:
            return ctx
        confidence = 0.0
        source = "default"
        probs = synthetic_one_hot(tier_name)

    decision = RoutingDecision(
        tier=tier_name,
        model=tiers[tier_name].get("model", ctx.model),
        confidence=confidence,
        source=source,
    )

    ctx.metadata["baseline_model"] = ctx.model

    # --- Controller: derive thinking_mode / prompt_policy if v4 returned no head decisions ---
    if thinking_mode is None and probs is not None:
        try:
            flags = extra.get("flags") if extra else None
            thinking_mode = derive_thinking_mode(probs, flags)
            prompt_policy = derive_prompt_policy(probs, flags)
            thinking_mode, prompt_policy = normalize_decisions(thinking_mode, prompt_policy)
            if decision.source in {"v4_unavailable", "default"} and prompt_policy == "P0":
                prompt_policy = "P1"
        except Exception:
            log.warning("squilla_router.controller_error", exc_info=True)
            thinking_mode = None
            prompt_policy = None

    # --- Apply decisions ---
    if _is_history_strategy(strategy_name):
        routing_extra = ctx.metadata.setdefault("routing_extra", extra or {})
        decision = _finalize_decision(
            decision,
            router_cfg=router_cfg,
            tiers=tiers,
            valid_tiers=valid_tiers,
            message=semantic_message,
            routing_history=routing_history,
            strategy_name=strategy_name,
            extra=routing_extra,
        )
        thinking_mode, prompt_policy = _reconcile_controller_with_final_tier(
            thinking_mode,
            prompt_policy,
            routing_extra,
        )

    routing_extra = ctx.metadata.get("routing_extra")
    decision = _apply_large_context_floor(
        decision,
        ctx=ctx,
        router_cfg=router_cfg,
        tiers=tiers,
        valid_tiers=valid_tiers,
        semantic_message=semantic_message,
        extra=routing_extra if isinstance(routing_extra, dict) else None,
    )
    if decision.source == "large_context_floor" and isinstance(routing_extra, dict):
        thinking_mode, prompt_policy = _reconcile_controller_with_final_tier(
            thinking_mode,
            prompt_policy,
            routing_extra,
        )

    routing_applied = rollout_phase != "observe"
    if routing_applied:
        ctx.model = decision.model
    ctx.metadata["routed_tier"] = decision.tier
    ctx.metadata["routed_model"] = decision.model
    ctx.metadata["routing_applied"] = routing_applied
    ctx.metadata["rollout_phase"] = rollout_phase
    ctx.metadata["applied_model"] = ctx.model
    ctx.metadata["routing_confidence"] = decision.confidence
    ctx.metadata["routing_source"] = decision.source
    ctx.metadata.update(_compute_savings(decision.model, tiers))

    context_states = ctx.metadata.get("session_context_states") or ctx.metadata.get(
        "active_context_states"
    )
    if isinstance(context_states, list):
        tier_cfg = tiers[decision.tier]
        candidate_provider = str(
            tier_cfg.get("provider") or getattr(router_cfg, "tier_profile", "") or ""
        )
        ctx.metadata["provider_state_continuity"] = provider_state_continuity_diagnostic(
            context_states=context_states,
            candidate_provider=candidate_provider,
            candidate_model=decision.model,
            now_ms=int(time.time() * 1000),
        ).as_metadata()

    try:
        _apply_controller(
            ctx,
            router_cfg,
            tiers[decision.tier],
            thinking_mode,
            prompt_policy,
            prompt_hint=(ctx.metadata.get("routing_extra") or {}).get("prompt_hint"),
            rollout_phase=rollout_phase,
        )
    except Exception:
        log.warning("squilla_router.controller_apply_error", exc_info=True)
        _record_thinking_metadata(ctx, router_cfg, tiers[decision.tier])

    # History-aware routers accumulate routing_extra into per-session history.
    if _is_history_strategy(strategy_name):
        extra = ctx.metadata.get("routing_extra")
        if extra:
            entry_payload = _routing_history_entry(
                text=semantic_message,
                extra=extra,
                decision=decision,
            )
            if defer_history:
                ctx.metadata[_PENDING_ROUTING_HISTORY_ENTRY_KEY] = entry_payload
                ctx.metadata[_PENDING_ROUTING_HISTORY_SESSION_KEY] = ctx.session_key
                local_history = list(routing_history or [])
                local_entry = {
                    "turn_index": len(local_history),
                    "_ts": time.monotonic(),
                    **entry_payload,
                }
                ctx.metadata["routing_history"] = [*local_history, local_entry][
                    -_MAX_ROUTING_HISTORY:
                ]
            else:
                ctx.metadata["routing_history"] = _append_routing_history(
                    ctx.session_key,
                    entry_payload,
                )

    # Pull observability fields from routing_extra so operators can see
    # what the model raw-believed (probabilities) vs what was selected
    # (route_class). With probabilities present the difference between
    # "model strongly chose this class" and "post-processing forced it"
    # is visible in the log without re-running the router.
    routing_extra = ctx.metadata.get("routing_extra") or {}
    log.debug(
        "squilla_router.routed",
        tier=decision.tier,
        routed_model=decision.model,
        applied_model=ctx.model,
        routing_applied=routing_applied,
        confidence=decision.confidence,
        source=decision.source,
        thinking_mode=thinking_mode,
        prompt_policy=prompt_policy,
        thinking_level=ctx.metadata.get("thinking_level"),
        rollout_phase=rollout_phase,
        route_class=routing_extra.get("route_class"),
        base_tier=routing_extra.get("base_tier"),
        pre_confidence_tier=routing_extra.get("pre_confidence_tier"),
        final_tier=routing_extra.get("final_tier"),
        final_route_class=routing_extra.get("final_route_class"),
        confidence_threshold=routing_extra.get("confidence_threshold"),
        confidence_gate_applied=routing_extra.get("confidence_gate_applied"),
        anti_downgrade_applied=routing_extra.get("anti_downgrade_applied"),
        probabilities=routing_extra.get("probabilities"),
        margin=routing_extra.get("margin"),
        provider_state_continuity=ctx.metadata.get("provider_state_continuity"),
    )
    return ctx
