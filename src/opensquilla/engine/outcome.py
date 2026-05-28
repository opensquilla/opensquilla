"""Normalized turn outcome taxonomy."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

TurnOutcomeKind = Literal[
    "completed",
    "partial",
    "budgetLimited",
    "blocked",
    "failed",
    "interrupted",
]

_BUDGET_CODES = frozenset(
    {
        "current_turn_context_exhausted",
        "provider_request_too_large",
        "provider_request_budget_exhausted",
        "provider_output_limit",
        "tool_run_budget_exhausted",
        "llm_budget_exhausted",
    }
)
_PARTIAL_CODES = frozenset({"max_iterations", "output_truncated", "provider_output_truncated"})
_INTERRUPTED_CODES = frozenset({"cancelled", "interrupted", "timeout", "iteration_timeout"})
_BLOCKED_CODES = frozenset(
    {
        "human_decision_required",
        "approval_required",
        "external_dependency",
        "provider_unavailable",
    }
)


@dataclass(frozen=True)
class TurnOutcome:
    kind: TurnOutcomeKind
    reason: str
    error_class: str | None = None
    error_message: str | None = None
    retryable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


def completed_outcome(reason: str = "done") -> TurnOutcome:
    return TurnOutcome(kind="completed", reason=reason)


def outcome_from_error(
    *,
    code: str | None,
    message: str | None = None,
    error_class: str | None = None,
) -> TurnOutcome:
    normalized = _normalize_code(code)
    text = message or None
    if normalized in _BUDGET_CODES:
        return TurnOutcome(
            kind="budgetLimited",
            reason=normalized,
            error_class=error_class or normalized,
            error_message=text,
            retryable=True,
        )
    if normalized in _PARTIAL_CODES:
        return TurnOutcome(
            kind="partial",
            reason=normalized,
            error_class=error_class or normalized,
            error_message=text,
            retryable=normalized == "provider_output_truncated",
        )
    if normalized in _INTERRUPTED_CODES:
        return TurnOutcome(
            kind="interrupted",
            reason=normalized,
            error_class=error_class or normalized,
            error_message=text,
            retryable=True,
        )
    if normalized in _BLOCKED_CODES:
        return TurnOutcome(
            kind="blocked",
            reason=normalized,
            error_class=error_class or normalized,
            error_message=text,
            retryable=True,
        )
    return TurnOutcome(
        kind="failed",
        reason=normalized or "error",
        error_class=error_class or normalized or "error",
        error_message=text,
    )


def outcome_from_error_event(event: Any) -> TurnOutcome:
    return outcome_from_error(
        code=getattr(event, "code", None),
        message=getattr(event, "message", None),
    )


def turn_outcome_details(outcome: TurnOutcome) -> dict[str, Any]:
    return {"turn_outcome": outcome.to_dict()}


def _normalize_code(value: str | None) -> str:
    return str(value or "").strip().lower().replace("-", "_")
