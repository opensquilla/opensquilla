"""Fallback policy for provider retry and model failover."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import StrEnum

from opensquilla.provider.failures import ProviderFailureKind, classify_provider_error


class ProviderErrorKind(StrEnum):
    RATE_LIMIT = "rate_limit"
    AUTH_FAILURE = "auth_failure"
    OVERLOADED = "overloaded"
    CONTEXT_OVERFLOW = "context_overflow"
    TRANSPORT_TRANSIENT = "transport_transient"
    EMPTY_RESPONSE = "empty_response"
    UNKNOWN = "unknown"


_FAILURE_KIND_MAP: dict[ProviderFailureKind, ProviderErrorKind] = {
    ProviderFailureKind.PROVIDER_OVERLOADED: ProviderErrorKind.TRANSPORT_TRANSIENT,
    ProviderFailureKind.TRANSPORT_TRANSIENT: ProviderErrorKind.TRANSPORT_TRANSIENT,
    ProviderFailureKind.RATE_LIMITED: ProviderErrorKind.RATE_LIMIT,
    ProviderFailureKind.AUTH_INVALID: ProviderErrorKind.AUTH_FAILURE,
    ProviderFailureKind.CONTEXT_OVERFLOW: ProviderErrorKind.CONTEXT_OVERFLOW,
    ProviderFailureKind.EMPTY_RESPONSE: ProviderErrorKind.EMPTY_RESPONSE,
}


@dataclass
class FallbackPolicy:
    """Policy for retrying failed provider calls and falling back to alternate models."""

    max_retries: int = 3
    fallback_models: list[str] = field(default_factory=list)
    base_backoff_ms: int = 1000
    max_backoff_ms: int = 30_000

    @staticmethod
    def classify_error(
        message: str,
        *,
        provider_name: str = "openrouter",
        status_code: int | None = None,
        raw_code: str = "",
    ) -> ProviderErrorKind:
        """Classify a provider error message into a retry category."""
        kind = classify_provider_error(
            provider_name,
            status_code,
            raw_code=raw_code,
            message=message,
        )
        return _FAILURE_KIND_MAP.get(kind, ProviderErrorKind.UNKNOWN)

    def should_retry(self, kind: ProviderErrorKind, attempt: int) -> bool:
        """Whether to retry after this error kind at this attempt number."""
        if attempt >= self.max_retries:
            return False
        if kind == ProviderErrorKind.AUTH_FAILURE:
            return False  # Don't retry auth errors
        retryable = (
            ProviderErrorKind.RATE_LIMIT,
            ProviderErrorKind.OVERLOADED,
            ProviderErrorKind.CONTEXT_OVERFLOW,
            ProviderErrorKind.TRANSPORT_TRANSIENT,
        )
        if kind in retryable:
            return True
        return False  # Unknown errors: don't retry by default

    def get_fallback_model(self, current_model: str) -> str | None:
        """Return the next fallback model after current_model, or None if exhausted."""
        if not self.fallback_models:
            return None
        try:
            idx = self.fallback_models.index(current_model)
            if idx + 1 < len(self.fallback_models):
                return self.fallback_models[idx + 1]
        except ValueError:
            # Current model not in fallback list; use first fallback
            if self.fallback_models:
                return self.fallback_models[0]
        return None


def backoff_sleep(
    attempt: int,
    base_ms: int = 1000,
    max_ms: int = 30_000,
    _fake: bool = False,
) -> float:
    """Calculate exponential backoff delay with jitter.

    Args:
        attempt: 0-indexed retry attempt number.
        base_ms: Base delay in milliseconds.
        max_ms: Maximum delay cap in milliseconds.
        _fake: If True, return the delay without actually sleeping (for testing).

    Returns:
        Calculated delay in seconds.
    """
    import structlog

    jitter = random.randint(0, base_ms // 2)  # noqa: S311
    delay_ms = min(base_ms * (2**attempt) + jitter, max_ms)
    delay_s = delay_ms / 1000.0

    if not _fake:
        structlog.get_logger().info("backoff_sleep", delay_s=round(delay_s, 2), attempt=attempt)

    return float(delay_s)
