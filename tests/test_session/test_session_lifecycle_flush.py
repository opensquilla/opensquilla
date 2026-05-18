from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from opensquilla.memory.session_flush import FlushReceipt
from opensquilla.session.lifecycle_flush import (
    error_flush_receipt,
    execute_lifecycle_flush,
    flush_disk_failure,
    flush_unavailable_failure,
    force_requires_admin_failure,
    skipped_flush_receipt,
    unavailable_flush_failure_for_transcript,
)


def test_reset_flush_unavailable_failure_owns_error_wire_shape() -> None:
    failure = flush_unavailable_failure(
        "reset",
        "agent:main:webchat:abc123",
        "abc123",
        message_count=3,
    )

    assert failure.code == "flush_unavailable"
    assert failure.message == (
        "Reset aborted: flush service is unavailable and the transcript is non-empty. "
        "Re-run with force=true (admin) to discard without backup."
    )
    assert failure.details == {
        "key": "agent:main:webchat:abc123",
        "session_id": "abc123",
        "reason": "flush_service_disabled",
        "message_count": 3,
    }


def test_compact_force_requires_admin_failure_owns_error_wire_shape() -> None:
    failure = force_requires_admin_failure(
        "compact",
        "agent:main:webchat:abc123",
        "abc123",
    )

    assert failure.code == "permission_denied"
    assert failure.message == "force=true on sessions.compact requires operator.admin scope."
    assert failure.details == {
        "key": "agent:main:webchat:abc123",
        "session_id": "abc123",
    }


def test_unavailable_flush_policy_owns_force_and_scope_decisions() -> None:
    assert (
        unavailable_flush_failure_for_transcript(
            "reset",
            "agent:main:webchat:abc123",
            "abc123",
            [],
            force=False,
            principal_scopes={"operator.write"},
        )
        is None
    )
    assert (
        unavailable_flush_failure_for_transcript(
            "compact",
            "agent:main:webchat:abc123",
            "abc123",
            [object()],
            force=True,
            principal_scopes={"operator.write", "operator.admin"},
        )
        is None
    )

    failure = unavailable_flush_failure_for_transcript(
        "compact",
        "agent:main:webchat:abc123",
        "abc123",
        [object()],
        force=True,
        principal_scopes={"operator.write"},
    )

    assert failure is not None
    assert failure.code == "permission_denied"
    assert failure.message == "force=true on sessions.compact requires operator.admin scope."


def test_flush_disk_failure_owns_receipt_error_wire_shape() -> None:
    receipt = error_flush_receipt(message_count=2, error="disk no")
    failure = flush_disk_failure("reset", "agent:main:webchat:abc123", "abc123", receipt)

    assert receipt.mode == "error"
    assert receipt.message_count == 2
    assert receipt.error == "disk no"
    assert failure.code == "flush_disk_error"
    assert failure.message == "Reset aborted: flush failed (disk no)"
    assert failure.details["key"] == "agent:main:webchat:abc123"
    assert failure.details["session_id"] == "abc123"
    assert failure.details["flush_receipt"]["mode"] == "error"
    assert failure.details["flush_receipt"]["message_count"] == 2
    assert failure.details["flush_receipt"]["error"] == "disk no"


def test_flush_disk_failure_uses_unknown_error_for_error_receipt_without_message() -> None:
    receipt = error_flush_receipt(message_count=2, error="")
    failure = flush_disk_failure("compact", "agent:main:webchat:abc123", "abc123", receipt)

    assert failure.code == "flush_disk_error"
    assert failure.message == "Compact aborted: flush failed (unknown error)"


def test_skipped_flush_receipt_owns_empty_transcript_shape() -> None:
    receipt = skipped_flush_receipt()

    assert receipt.mode == "skipped"
    assert receipt.flushed_paths == []
    assert receipt.slug is None
    assert receipt.message_count == 0
    assert receipt.duration_ms == 0
    assert receipt.raw_reason is None
    assert receipt.error is None


def test_lifecycle_receipts_match_memory_flush_receipt_wire_shape() -> None:
    assert skipped_flush_receipt().to_dict() == FlushReceipt(
        mode="skipped",
        flushed_paths=[],
        slug=None,
        message_count=0,
        duration_ms=0,
        raw_reason=None,
        error=None,
    ).to_dict()
    assert error_flush_receipt(message_count=2, error="disk no").to_dict() == FlushReceipt(
        mode="error",
        flushed_paths=[],
        slug=None,
        message_count=2,
        duration_ms=0,
        raw_reason=None,
        error="disk no",
    ).to_dict()


@pytest.mark.asyncio
async def test_execute_lifecycle_flush_owns_empty_transcript_skip() -> None:
    flush_service = SimpleNamespace(execute=AsyncMock())

    attempt = await execute_lifecycle_flush(
        "reset",
        flush_service,
        [],
        "agent:main:webchat:abc123",
        agent_id="main",
        session_id="abc123",
    )

    flush_service.execute.assert_not_called()
    assert attempt.failure is None
    assert attempt.receipt.mode == "skipped"


@pytest.mark.asyncio
async def test_execute_lifecycle_flush_owns_service_call_contract() -> None:
    receipt = skipped_flush_receipt()
    flush_service = SimpleNamespace(execute=AsyncMock(return_value=receipt))
    transcript = [object()]

    attempt = await execute_lifecycle_flush(
        "compact",
        flush_service,
        transcript,
        "agent:main:webchat:abc123",
        agent_id="main",
        session_id="abc123",
    )

    flush_service.execute.assert_awaited_once_with(
        transcript,
        "agent:main:webchat:abc123",
        agent_id="main",
        timeout=30.0,
        message_window=0,
        segment_mode="auto",
    )
    assert attempt.receipt is receipt
    assert attempt.failure is None


@pytest.mark.asyncio
async def test_execute_lifecycle_flush_owns_exception_to_failure_mapping() -> None:
    exc = RuntimeError("disk no")
    flush_service = SimpleNamespace(execute=AsyncMock(side_effect=exc))

    attempt = await execute_lifecycle_flush(
        "reset",
        flush_service,
        [object(), object()],
        "agent:main:webchat:abc123",
        agent_id="main",
        session_id="abc123",
    )

    assert attempt.receipt.mode == "error"
    assert attempt.receipt.message_count == 2
    assert attempt.receipt.error == "disk no"
    assert attempt.failure is not None
    assert attempt.failure.code == "flush_disk_error"
    assert attempt.failure.message == "Reset aborted: flush failed (disk no)"
    assert attempt.failure.cause is exc
