"""Provider failure classification and runtime recovery decisions."""

from __future__ import annotations

import re
from enum import StrEnum


class ProviderFailureKind(StrEnum):
    RATE_LIMITED = "rate_limited"
    PROVIDER_OVERLOADED = "provider_overloaded"
    AUTH_INVALID = "auth_invalid"
    CONTEXT_OVERFLOW = "context_overflow"
    UNSUPPORTED_FEATURE = "unsupported_feature"
    INSUFFICIENT_CREDITS = "insufficient_credits"
    MODEL_NOT_FOUND = "model_not_found"
    TRANSPORT_TRANSIENT = "transport_transient"
    POLICY_REFUSAL = "policy_refusal"
    EMPTY_RESPONSE = "empty_response"
    MALFORMED_RESPONSE = "malformed_response"
    BAD_REQUEST = "bad_request"
    UNKNOWN = "unknown"


class ProviderRecoveryAction(StrEnum):
    RETRY = "retry"
    RETRY_THEN_FALLBACK = "retry_then_fallback"
    FALLBACK_PROVIDER = "fallback_provider"
    COMPACT_AND_RETRY = "compact_and_retry"
    FAIL_CONFIG = "fail_config"
    SURFACE = "surface"


_OPENAI_COMPAT_PROVIDERS = {
    "openrouter",
    "openai",
    "azure",
    "deepseek",
    "gemini",
    "dashscope",
    "bailian_coding",
    "moonshot",
    "mistral",
    "groq",
    "zhipu",
    "qianfan",
    "siliconflow",
    "aihubmix",
    "minimax_openai",
    "volcengine",
    "byteplus",
    "vllm",
    "lm_studio",
    "ovms",
}

_GATEWAY_TRANSIENT_STATUS_CODES = {499, 500, 502, 503, 504, 520, 521, 522, 523, 524, 529}
_GATEWAY_CODES = r"(?:499|500|502|503|504|520|521|522|523|524|529)"
_GATEWAY_CONTEXT = r"(?:cloudflare|openrouter|upstream|gateway|backend)"
_GATEWAY_ERROR_TERMS = (
    r"(?:error|returned|returning|failed|failure|unreachable|timeout|timed out|"
    r"overload(?:ed)?|bad gateway|origin)"
)
_GATEWAY_TRANSIENT_RE = re.compile(
    r"\b(?:http(?: status)?|status(?:[_ -]?code)?|error code|code)\s*[:=]?\s*"
    rf"{_GATEWAY_CODES}\b"
    rf"|\b{_GATEWAY_CONTEXT}\b[^\n]{{0,80}}\b{_GATEWAY_ERROR_TERMS}\b[^\n]{{0,80}}\b{_GATEWAY_CODES}\b"
    rf"|\b{_GATEWAY_CONTEXT}\b[^\n]{{0,80}}\b{_GATEWAY_CODES}\b[^\n]{{0,80}}\b{_GATEWAY_ERROR_TERMS}\b"
    rf"|\b{_GATEWAY_CODES}\b[^\n]{{0,80}}\b{_GATEWAY_CONTEXT}\b[^\n]{{0,80}}\b{_GATEWAY_ERROR_TERMS}\b"
)


def _joined(status_code: int | None, raw_code: str, message: str) -> str:
    return f"{status_code or ''} {raw_code or ''} {message or ''}".lower()


def _is_context_overflow(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "context length",
            "context window",
            "maximum context",
            "prompt is too long",
            "input is too long",
            "input exceeds",
            "provider_request_budget_exhausted",
            "too many tokens",
        )
    )


def _is_policy_refusal(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "content policy",
            "policy violation",
            "safety policy",
            "moderation",
            "refusal",
            "blocked by policy",
        )
    )


def _is_empty_response(raw_code: str, message: str) -> bool:
    normalized_code = (raw_code or "").strip().lower()
    normalized_message = (message or "").strip().lower()
    return normalized_code == "empty_response" or normalized_message in {
        "empty_response",
        "empty response",
        "provider returned an empty response",
    }


def _is_model_unavailable(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "no endpoints found",
            "model not found",
            "model is not available",
            "model not available",
            "not available in your region",
            "not available in the requested region",
        )
    )


def _is_gateway_transient(text: str) -> bool:
    return bool(_GATEWAY_TRANSIENT_RE.search(text))


def classify_provider_error(
    provider_name: str,
    status_code: int | None,
    raw_code: str = "",
    message: str = "",
) -> ProviderFailureKind:
    """Classify a provider error into a stable runtime failure kind."""

    provider = (provider_name or "").lower()
    text = _joined(status_code, raw_code, message)

    if _is_context_overflow(text):
        return ProviderFailureKind.CONTEXT_OVERFLOW
    if _is_policy_refusal(text):
        return ProviderFailureKind.POLICY_REFUSAL
    if _is_empty_response(raw_code, message):
        return ProviderFailureKind.EMPTY_RESPONSE

    if provider in _OPENAI_COMPAT_PROVIDERS:
        if _is_model_unavailable(text):
            return ProviderFailureKind.MODEL_NOT_FOUND
        if status_code in {401, 403} or "invalid api key" in text or "unauthorized" in text:
            return ProviderFailureKind.AUTH_INVALID
        if status_code == 402 or "insufficient credits" in text or "no credits" in text:
            return ProviderFailureKind.INSUFFICIENT_CREDITS
        if status_code == 429 or "rate limit" in text or "rate_limit" in text:
            return ProviderFailureKind.RATE_LIMITED
        if "does not support" in text or "unsupported" in text:
            return ProviderFailureKind.UNSUPPORTED_FEATURE
        if (
            status_code in _GATEWAY_TRANSIENT_STATUS_CODES
            or "overloaded" in text
            or _is_gateway_transient(text)
        ):
            return ProviderFailureKind.PROVIDER_OVERLOADED
        if status_code == 400 or "invalid_request" in text:
            return ProviderFailureKind.BAD_REQUEST

    if provider in {"anthropic", "minimax", "minimax_cn", "minimax_global"}:
        if status_code in {401, 403} or "authentication_error" in text:
            return ProviderFailureKind.AUTH_INVALID
        if status_code == 429 or "rate_limit_error" in text:
            return ProviderFailureKind.RATE_LIMITED
        if status_code in _GATEWAY_TRANSIENT_STATUS_CODES or "overloaded_error" in text:
            return ProviderFailureKind.PROVIDER_OVERLOADED
        if "invalid_request_error" in text:
            return ProviderFailureKind.BAD_REQUEST

    if provider == "ollama":
        if "model not found" in text or "pull" in text and "model" in text:
            return ProviderFailureKind.MODEL_NOT_FOUND
        if (
            "connection refused" in text
            or "connection error" in text
            or "request error" in text
            or "timeout" in text
        ):
            return ProviderFailureKind.TRANSPORT_TRANSIENT

    if status_code == 429 or "rate limit" in text:
        return ProviderFailureKind.RATE_LIMITED
    if status_code in _GATEWAY_TRANSIENT_STATUS_CODES or _is_gateway_transient(text):
        return ProviderFailureKind.PROVIDER_OVERLOADED
    if "malformed" in text or "invalid json" in text:
        return ProviderFailureKind.MALFORMED_RESPONSE
    if "timeout" in text or "request error" in text:
        return ProviderFailureKind.TRANSPORT_TRANSIENT

    return ProviderFailureKind.UNKNOWN


def decide_recovery_action(kind: ProviderFailureKind) -> ProviderRecoveryAction:
    """Map classified provider failure to the first runtime recovery action."""

    if kind is ProviderFailureKind.CONTEXT_OVERFLOW:
        return ProviderRecoveryAction.COMPACT_AND_RETRY
    if kind in {
        ProviderFailureKind.PROVIDER_OVERLOADED,
        ProviderFailureKind.TRANSPORT_TRANSIENT,
    }:
        return ProviderRecoveryAction.RETRY_THEN_FALLBACK
    if kind in {
        ProviderFailureKind.RATE_LIMITED,
        ProviderFailureKind.INSUFFICIENT_CREDITS,
        ProviderFailureKind.MODEL_NOT_FOUND,
        ProviderFailureKind.UNSUPPORTED_FEATURE,
    }:
        return ProviderRecoveryAction.FALLBACK_PROVIDER
    if kind is ProviderFailureKind.AUTH_INVALID:
        return ProviderRecoveryAction.FAIL_CONFIG
    return ProviderRecoveryAction.SURFACE
