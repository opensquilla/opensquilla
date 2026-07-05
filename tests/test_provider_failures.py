from __future__ import annotations

import pytest
import structlog

from opensquilla.provider.failures import (
    FailureMatcher,
    ProviderFailureKind,
    classify_provider_error,
)


def test_provider_request_budget_exhausted_is_context_overflow() -> None:
    assert (
        classify_provider_error(
            provider_name="openrouter",
            status_code=None,
            raw_code="provider_request_budget_exhausted",
            message='{"fallback_reason":"provider_request_budget_exhausted"}',
        )
        is ProviderFailureKind.CONTEXT_OVERFLOW
    )


def test_unknown_classification_emits_redacted_fingerprint_event() -> None:
    with structlog.testing.capture_logs() as captured:
        kind = classify_provider_error(
            "openrouter",
            None,
            raw_code="strange_code",
            message="novel backend exploded: Bearer abc123def456",
        )

    assert kind is ProviderFailureKind.UNKNOWN
    events = [entry for entry in captured if entry["event"] == "provider_failure.unclassified"]
    assert len(events) == 1
    event = events[0]
    assert event["provider"] == "openrouter"
    assert event["failure_family"] == "openai_compat"
    assert event["status_code"] is None
    assert event["raw_code"] == "strange_code"
    assert "novel backend exploded" in event["message_head"]
    assert "abc123def456" not in event["message_head"]


def test_classified_errors_do_not_emit_the_unclassified_event() -> None:
    with structlog.testing.capture_logs() as captured:
        kind = classify_provider_error("openrouter", 429, message="rate limit")

    assert kind is ProviderFailureKind.RATE_LIMITED
    assert not [e for e in captured if e["event"] == "provider_failure.unclassified"]


def test_constraint_free_matcher_rows_are_rejected() -> None:
    # A row with no constraints would match every error; the table refuses it.
    with pytest.raises(ValueError, match="at least one constraint"):
        FailureMatcher(ProviderFailureKind.UNKNOWN)
