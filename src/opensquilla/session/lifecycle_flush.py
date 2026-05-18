"""Session-domain flush receipts and failure payloads for lifecycle actions."""

from __future__ import annotations

from collections.abc import Container, Sized
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from opensquilla.session.rpc_payload import (
    session_flush_error_details,
    session_flush_unavailable_details,
    session_permission_denied_details,
)

LifecycleFlushAction = Literal["reset", "compact"]
LifecycleFlushMode = Literal["skipped", "error"]
_FLUSH_OBLIGATION_POLICY_VERSION = "temporal-source-obligation-v1"


def _zero_lifecycle_usage() -> dict[str, Any]:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "reasoning_tokens": 0,
        "cached_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_usd": 0.0,
        "billed_cost": 0.0,
        "estimated_cost_usd": 0.0,
        "model": "",
        "request_count": 0,
        "cost_source": "none",
    }


@dataclass(frozen=True)
class SessionLifecycleFlushFailure:
    code: str
    message: str
    details: dict[str, Any]
    cause: BaseException | None = field(default=None, compare=False)


@dataclass(frozen=True)
class SessionLifecycleFlushAttempt:
    receipt: Any
    failure: SessionLifecycleFlushFailure | None = None


@dataclass(frozen=True)
class LifecycleFlushReceipt:
    mode: LifecycleFlushMode
    flushed_paths: list[str]
    slug: str | None
    message_count: int
    duration_ms: int
    raw_reason: None
    error: str | None
    usage: dict[str, Any] = field(default_factory=_zero_lifecycle_usage)
    raw_error_type: str | None = None
    raw_error_message: str | None = None
    raw_error_code: str | None = None
    input_message_count: int = 0
    prompt_message_count: int = 0
    prompt_char_count: int = 0
    truncated: bool = False
    truncation_policy: str = ""
    first_included_message: int | None = None
    last_included_message: int | None = None
    source_coverage: float = 0.0
    segment_mode: str = "off"
    segment_count: int = 0
    segments: list[dict[str, Any]] = field(default_factory=list)
    total_prompt_char_count: int = 0
    integrity_status: str = "unverified"
    indexed_chunk_count: int = 0
    candidate_count: int = 0
    candidate_covered_count: int = 0
    candidate_missing_ids: list[str] = field(default_factory=list)
    candidate_source_coverage: float = 0.0
    prompt_message_source_coverage: float = 0.0
    output_coverage_status: str = "unverifiable"
    invalid_candidate_count: int = 0
    invalid_candidate_errors: list[str] = field(default_factory=list)
    obligation_count: int = 0
    obligation_covered_count: int = 0
    obligation_missing_ids: list[str] = field(default_factory=list)
    obligation_coverage: float = 0.0
    obligation_backfilled_count: int = 0
    obligation_status: str = "unverifiable"
    obligation_policy_version: str = _FLUSH_OBLIGATION_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.mode == "skipped" and self.error is not None:
            raise ValueError("skipped lifecycle flush receipt cannot include an error")
        if self.mode == "error" and self.error is None:
            raise ValueError("error lifecycle flush receipt requires an error")
        if self.mode == "skipped" and (self.flushed_paths or self.message_count):
            raise ValueError("skipped lifecycle flush receipt must have no paths or messages")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


LifecycleFlushFailure = SessionLifecycleFlushFailure


def skipped_flush_receipt() -> LifecycleFlushReceipt:
    return LifecycleFlushReceipt(
        mode="skipped",
        flushed_paths=[],
        slug=None,
        message_count=0,
        duration_ms=0,
        raw_reason=None,
        error=None,
    )


def error_flush_receipt(*, message_count: int, error: str) -> LifecycleFlushReceipt:
    return LifecycleFlushReceipt(
        mode="error",
        flushed_paths=[],
        slug=None,
        message_count=message_count,
        duration_ms=0,
        raw_reason=None,
        error=error,
    )


def flush_unavailable_failure(
    action: LifecycleFlushAction,
    key: str,
    session_id: str | None,
    *,
    message_count: int,
) -> LifecycleFlushFailure:
    verb = _action_title(action)
    disposition = "discard" if action == "reset" else "truncate"
    return LifecycleFlushFailure(
        code="flush_unavailable",
        message=(
            f"{verb} aborted: flush service is unavailable and the transcript is "
            f"non-empty. Re-run with force=true (admin) to {disposition} without backup."
        ),
        details=session_flush_unavailable_details(
            key,
            session_id,
            message_count=message_count,
        ),
    )


def force_requires_admin_failure(
    action: LifecycleFlushAction,
    key: str,
    session_id: str | None,
) -> LifecycleFlushFailure:
    return LifecycleFlushFailure(
        code="permission_denied",
        message=f"force=true on sessions.{action} requires operator.admin scope.",
        details=session_permission_denied_details(key, session_id),
    )


def unavailable_flush_failure_for_transcript(
    action: LifecycleFlushAction,
    key: str,
    session_id: str | None,
    transcript: Sized,
    *,
    force: bool,
    principal_scopes: Container[str],
) -> LifecycleFlushFailure | None:
    if len(transcript) == 0:
        return None
    if not force:
        return flush_unavailable_failure(
            action,
            key,
            session_id,
            message_count=len(transcript),
        )
    if "operator.admin" not in principal_scopes:
        return force_requires_admin_failure(action, key, session_id)
    return None


def flush_disk_failure(
    action: LifecycleFlushAction,
    key: str,
    session_id: str | None,
    receipt: Any,
    *,
    unknown_error_fallback: bool = True,
) -> LifecycleFlushFailure:
    error = receipt.error
    if unknown_error_fallback:
        error = error or "unknown error"
    return LifecycleFlushFailure(
        code="flush_disk_error",
        message=f"{_action_title(action)} aborted: flush failed ({error})",
        details=session_flush_error_details(key, session_id, receipt),
    )


async def execute_lifecycle_flush(
    action: LifecycleFlushAction,
    flush_service: Any,
    transcript: Sized,
    key: str,
    *,
    agent_id: str,
    session_id: str | None,
) -> SessionLifecycleFlushAttempt:
    if len(transcript) == 0:
        return SessionLifecycleFlushAttempt(receipt=skipped_flush_receipt())

    try:
        receipt = await flush_service.execute(
            transcript,
            key,
            agent_id=agent_id,
            timeout=30.0,
            message_window=0,
            segment_mode="auto",
        )
    except Exception as exc:  # noqa: BLE001
        receipt = error_flush_receipt(message_count=len(transcript), error=str(exc))
        failure = flush_disk_failure(
            action,
            key,
            session_id,
            receipt,
            unknown_error_fallback=False,
        )
        return SessionLifecycleFlushAttempt(
            receipt=receipt,
            failure=SessionLifecycleFlushFailure(
                code=failure.code,
                message=failure.message,
                details=failure.details,
                cause=exc,
            ),
        )

    if receipt.mode == "error":
        return SessionLifecycleFlushAttempt(
            receipt=receipt,
            failure=flush_disk_failure(action, key, session_id, receipt),
        )
    return SessionLifecycleFlushAttempt(receipt=receipt)


def _action_title(action: LifecycleFlushAction) -> str:
    return "Reset" if action == "reset" else "Compact"


__all__ = [
    "LifecycleFlushAction",
    "LifecycleFlushFailure",
    "LifecycleFlushReceipt",
    "SessionLifecycleFlushAttempt",
    "SessionLifecycleFlushFailure",
    "error_flush_receipt",
    "execute_lifecycle_flush",
    "flush_disk_failure",
    "flush_unavailable_failure",
    "force_requires_admin_failure",
    "skipped_flush_receipt",
    "unavailable_flush_failure_for_transcript",
]
