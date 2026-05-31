"""Provider context-state and prompt-cache capability profiles."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

ANTHROPIC_COMPACTION_STATE_KIND = "anthropic_compaction_block"
OPENAI_RESPONSES_COMPACTED_WINDOW_STATE_KIND = "openai_responses_compacted_window"


class PromptCacheSupport(StrEnum):
    NONE = "none"
    IMPLICIT = "implicit"
    EXPLICIT = "explicit"
    AUTOMATIC = "automatic"


class NativeCompactionSupport(StrEnum):
    NONE = "none"
    STANDALONE = "standalone"


class ProviderStateContinuityDecision(StrEnum):
    KEEP_PROVIDER = "keep_provider"
    USE_PORTABLE_FALLBACK = "use_portable_fallback"
    DISCARD_PROVIDER_STATE = "discard_provider_state"
    REBUILD_FROM_CANONICAL_TRANSCRIPT = "rebuild_from_canonical_transcript"


@dataclass(frozen=True)
class ProviderContextCapabilities:
    provider: str
    model: str
    prompt_cache: PromptCacheSupport = PromptCacheSupport.NONE
    native_compaction: NativeCompactionSupport = NativeCompactionSupport.NONE
    native_compaction_state_kind: str | None = None
    supports_cache_breakpoints: bool = False
    state_portable_across_providers: bool = False
    min_cache_tokens: int | None = None
    cache_ttl_options: tuple[int, ...] = ()

    @property
    def supports_explicit_prompt_cache(self) -> bool:
        return self.prompt_cache == PromptCacheSupport.EXPLICIT and self.supports_cache_breakpoints


@dataclass(frozen=True)
class ProviderStateContinuityDiagnostic:
    decision: ProviderStateContinuityDecision
    candidate_provider: str
    candidate_model: str
    provider_state_loss_risk: bool = False
    active_state_kind: str | None = None
    active_state_provider: str | None = None
    portable_fallback_available: bool = False
    reason: str = ""

    def as_metadata(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "candidate_provider": self.candidate_provider,
            "candidate_model": self.candidate_model,
            "provider_state_loss_risk": self.provider_state_loss_risk,
            "active_state_kind": self.active_state_kind,
            "active_state_provider": self.active_state_provider,
            "portable_fallback_available": self.portable_fallback_available,
            "reason": self.reason,
        }


def _openrouter_prompt_cache_support(model_l: str) -> PromptCacheSupport:
    if model_l.startswith(("anthropic/", "google/", "deepseek/", "x-ai/")):
        return PromptCacheSupport.EXPLICIT
    if model_l.startswith("z-ai/"):
        return PromptCacheSupport.IMPLICIT
    return PromptCacheSupport.IMPLICIT


def _gemini_min_cache_tokens(model_l: str) -> int | None:
    if "flash" in model_l:
        return 1024
    if "pro" in model_l:
        return 4096
    return None


def provider_context_capabilities(
    *,
    provider_kind: str,
    model: str,
    base_url: str = "",
) -> ProviderContextCapabilities:
    provider = provider_kind.strip().lower()
    model_l = model.strip().lower()
    base_l = base_url.strip().lower()

    if provider == "openrouter":
        prompt_cache = _openrouter_prompt_cache_support(model_l)
        return ProviderContextCapabilities(
            provider=provider,
            model=model,
            prompt_cache=prompt_cache,
            supports_cache_breakpoints=prompt_cache == PromptCacheSupport.EXPLICIT,
            state_portable_across_providers=False,
        )

    if provider == "anthropic":
        return ProviderContextCapabilities(
            provider=provider,
            model=model,
            prompt_cache=PromptCacheSupport.EXPLICIT,
            native_compaction=NativeCompactionSupport.NONE,
            supports_cache_breakpoints=True,
            state_portable_across_providers=False,
        )

    if provider == "gemini" or "generativelanguage.googleapis.com" in base_l:
        return ProviderContextCapabilities(
            provider=provider,
            model=model,
            prompt_cache=PromptCacheSupport.IMPLICIT,
            native_compaction=NativeCompactionSupport.NONE,
            min_cache_tokens=_gemini_min_cache_tokens(model_l),
            state_portable_across_providers=False,
        )

    if provider == "openai_responses":
        return ProviderContextCapabilities(
            provider=provider,
            model=model,
            prompt_cache=PromptCacheSupport.AUTOMATIC,
            native_compaction=NativeCompactionSupport.STANDALONE,
            native_compaction_state_kind=OPENAI_RESPONSES_COMPACTED_WINDOW_STATE_KIND,
            state_portable_across_providers=False,
        )

    if provider == "openai" and "api.openai.com" in base_l:
        return ProviderContextCapabilities(
            provider=provider,
            model=model,
            prompt_cache=PromptCacheSupport.AUTOMATIC,
            state_portable_across_providers=False,
        )

    return ProviderContextCapabilities(provider=provider, model=model)


def supports_openrouter_explicit_prompt_cache(model: str) -> bool:
    return provider_context_capabilities(
        provider_kind="openrouter",
        model=model,
    ).supports_explicit_prompt_cache


def _state_value(state: Any, field: str, default: Any = None) -> Any:
    if isinstance(state, dict):
        return state.get(field, default)
    return getattr(state, field, default)


def _state_int_value(state: Any, field: str) -> int | None:
    value = _state_value(state, field, None)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _state_order_key(index: int, state: Any) -> tuple[int, int, int]:
    created_at = _state_int_value(state, "created_at")
    state_id = _state_int_value(state, "id")
    return (
        created_at if created_at is not None else -1,
        state_id if state_id is not None else -1,
        index,
    )


def _active_context_states(
    context_states: list[Any],
    *,
    now_ms: int | None = None,
) -> list[Any]:
    indexed = [
        (index, state)
        for index, state in enumerate(context_states)
        if _is_active_context_state(state, now_ms=now_ms)
    ]
    indexed.sort(key=lambda item: _state_order_key(item[0], item[1]))
    return [state for _, state in indexed]


def _latest_portable_context_state(active_states: list[Any]) -> Any | None:
    return next(
        (
            state
            for state in reversed(active_states)
            if bool(_state_value(state, "portable", False))
        ),
        None,
    )


def _latest_native_context_state(active_states: list[Any]) -> Any | None:
    return next(
        (
            state
            for state in reversed(active_states)
            if not bool(_state_value(state, "portable", False))
        ),
        None,
    )


def _is_active_context_state(state: Any, *, now_ms: int | None = None) -> bool:
    if not bool(_state_value(state, "valid", True)):
        return False
    expires_at = _state_int_value(state, "expires_at")
    return not (now_ms is not None and expires_at is not None and expires_at <= now_ms)


def provider_state_continuity_diagnostic(
    *,
    context_states: list[Any],
    candidate_provider: str,
    candidate_model: str,
    now_ms: int | None = None,
) -> ProviderStateContinuityDiagnostic:
    provider = candidate_provider.strip().lower()
    model = candidate_model.strip()
    active_states = _active_context_states(context_states, now_ms=now_ms)
    if not active_states:
        return ProviderStateContinuityDiagnostic(
            decision=ProviderStateContinuityDecision.REBUILD_FROM_CANONICAL_TRANSCRIPT,
            candidate_provider=provider,
            candidate_model=model,
            reason="no_active_context_state",
        )

    portable_state = _latest_portable_context_state(active_states)
    native_state = _latest_native_context_state(active_states)
    if native_state is None:
        return ProviderStateContinuityDiagnostic(
            decision=ProviderStateContinuityDecision.USE_PORTABLE_FALLBACK,
            candidate_provider=provider,
            candidate_model=model,
            portable_fallback_available=portable_state is not None,
            reason="portable_context_state_available",
        )

    state_provider = str(_state_value(native_state, "provider", "")).strip().lower()
    state_kind = str(_state_value(native_state, "state_kind", "") or "")
    if state_provider == provider:
        return ProviderStateContinuityDiagnostic(
            decision=ProviderStateContinuityDecision.KEEP_PROVIDER,
            candidate_provider=provider,
            candidate_model=model,
            active_state_kind=state_kind,
            active_state_provider=state_provider,
            portable_fallback_available=portable_state is not None,
            reason="candidate_provider_matches_latest_native_state",
        )

    if portable_state is not None:
        return ProviderStateContinuityDiagnostic(
            decision=ProviderStateContinuityDecision.USE_PORTABLE_FALLBACK,
            candidate_provider=provider,
            candidate_model=model,
            provider_state_loss_risk=True,
            active_state_kind=state_kind,
            active_state_provider=state_provider,
            portable_fallback_available=True,
            reason="latest_native_state_provider_switch_with_portable_fallback",
        )

    return ProviderStateContinuityDiagnostic(
        decision=ProviderStateContinuityDecision.DISCARD_PROVIDER_STATE,
        candidate_provider=provider,
        candidate_model=model,
        provider_state_loss_risk=True,
        active_state_kind=state_kind,
        active_state_provider=state_provider,
        reason="latest_native_state_provider_switch_without_portable_fallback",
    )
