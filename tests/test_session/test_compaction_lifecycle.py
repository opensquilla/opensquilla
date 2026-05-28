from __future__ import annotations

from types import SimpleNamespace

from opensquilla.session.compaction_lifecycle import (
    durable_receipt_allows_destructive_compaction,
    flush_compaction_decision,
    flush_receipt_allows_destructive_compaction,
    flush_receipt_status_for_compaction,
)


def _receipt(**overrides):
    payload = {
        "mode": "llm",
        "indexed_chunk_count": 1,
        "integrity_status": "ok",
        "output_coverage_status": "ok",
        "invalid_candidate_count": 0,
        "candidate_missing_ids": [],
        "obligation_status": "ok",
        "obligation_missing_ids": [],
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def test_unverifiable_flush_receipt_is_not_destructive_safe() -> None:
    receipt = _receipt(output_coverage_status="unverifiable")

    assert flush_receipt_allows_destructive_compaction(receipt) is False
    assert flush_compaction_decision(receipt, safety_mode="protect") == "degraded_forensic"


def test_backfilled_obligations_remain_destructive_safe() -> None:
    receipt = _receipt(obligation_status="backfilled")

    assert flush_receipt_allows_destructive_compaction(receipt) is True
    assert flush_compaction_decision(receipt, safety_mode="protect") == "safe_destructive"


def test_checkpoint_receipt_allows_destructive_compaction() -> None:
    receipt = {
        "scope": "checkpoint",
        "status": "checkpoint_saved",
        "source_path": "memory/.checkpoints/agent-main-webchat-abc/turn-1.jsonl",
        "content_hash": "h1",
    }

    assert durable_receipt_allows_destructive_compaction(receipt) is True


def test_orphaned_checkpoint_receipt_is_not_destructive_safe() -> None:
    receipt = {"scope": "checkpoint", "status": "receipt_orphaned"}

    assert durable_receipt_allows_destructive_compaction(receipt) is False


def test_checkpoint_failed_receipt_is_not_destructive_safe() -> None:
    receipt = {
        "scope": "checkpoint",
        "status": "checkpoint_failed",
        "source_path": "memory/.checkpoints/agent-main-webchat-abc/turn-1.jsonl",
        "content_hash": "h1",
    }

    assert durable_receipt_allows_destructive_compaction(receipt) is False


def test_checkpoint_receipt_without_evidence_is_not_destructive_safe() -> None:
    receipt = {
        "scope": "checkpoint",
        "status": "checkpoint_saved",
        "source_path": "memory/.checkpoints/agent-main-webchat-abc/turn-1.jsonl",
        "content_hash": "",
    }

    assert durable_receipt_allows_destructive_compaction(receipt) is False


def test_missing_or_raw_receipt_enters_degraded_forensic_in_protect_mode() -> None:
    assert flush_compaction_decision(None, safety_mode="protect") == "degraded_forensic"
    assert (
        flush_compaction_decision(
            _receipt(mode="raw", indexed_chunk_count=0),
            safety_mode="protect",
        )
        == "degraded_forensic"
    )


def test_disabled_flush_decision_is_explicit() -> None:
    assert flush_compaction_decision(None, safety_mode="off") == "disabled"


def test_noop_flush_receipt_has_distinct_compaction_status() -> None:
    config = SimpleNamespace(
        memory=SimpleNamespace(
            flush_compaction_safety_mode="protect",
            flush_compaction_requires_safe_receipt=False,
        )
    )
    receipt = _receipt(
        indexed_chunk_count=0,
        integrity_status="unverified",
        output_coverage_status="unverifiable",
        obligation_status="unverifiable",
        result_status="ok_noop_no_memory",
    )

    assert flush_receipt_allows_destructive_compaction(receipt) is False
    assert flush_receipt_status_for_compaction(receipt, config) == "noop_no_memory"


def test_raw_archive_flush_receipt_has_distinct_compaction_status() -> None:
    config = SimpleNamespace(
        memory=SimpleNamespace(
            flush_compaction_safety_mode="protect",
            flush_compaction_requires_safe_receipt=False,
        )
    )
    receipt = _receipt(
        mode="raw",
        indexed_chunk_count=0,
        integrity_status="unverified",
        output_coverage_status="unverifiable",
        obligation_status="unverifiable",
        result_status="ok_archive_only",
    )

    assert flush_receipt_allows_destructive_compaction(receipt) is False
    assert flush_receipt_status_for_compaction(receipt, config) == "archive_only"
