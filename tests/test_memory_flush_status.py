from __future__ import annotations

from types import SimpleNamespace

from opensquilla.memory.flush_status import classify_flush_receipt


def _receipt(**overrides):
    values = {
        "mode": "llm",
        "result_status": "ok_candidates_written",
        "indexed_chunk_count": 1,
        "integrity_status": "ok",
        "output_coverage_status": "ok",
        "invalid_candidate_count": 0,
        "candidate_missing_ids": [],
        "obligation_count": 0,
        "obligation_missing_ids": [],
        "raw_reason": None,
        "flushed_paths": ["memory/2026-05-29-note.md"],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_flush_status_classifies_safe_semantic_receipt() -> None:
    status = classify_flush_receipt(_receipt())

    assert status.receipt_status == "safe"
    assert status.safety_status == "safe"
    assert status.semantic_status == "healthy"
    assert status.repair_status == "none"
    assert status.allows_destructive_compaction is True
    assert status.successful_flush is True
    assert status.has_raw_archive is False


def test_flush_status_classifies_archived_parse_failure_as_repair_pending() -> None:
    status = classify_flush_receipt(
        _receipt(
            mode="raw",
            result_status="parse_failed_archived",
            raw_reason="llm_error",
            indexed_chunk_count=0,
            integrity_status="unverified",
            output_coverage_status="unverified",
            content_hash="sha256:abc",
            flushed_paths=["memory/.raw_fallbacks/2026-05-29-flush.md"],
        )
    )

    assert status.receipt_status == "degraded_forensic"
    assert status.safety_status == "degraded_archive"
    assert status.semantic_status == "failed"
    assert status.repair_status == "pending"
    assert status.allows_destructive_compaction is True
    assert status.successful_flush is False
    assert status.has_raw_archive is True
    assert status.raw_reason == "llm_error"


def test_flush_status_classifies_noop_as_success_without_destructive_safety() -> None:
    status = classify_flush_receipt(
        _receipt(
            result_status="ok_noop_no_memory",
            indexed_chunk_count=0,
            flushed_paths=[],
        )
    )

    assert status.receipt_status == "noop_no_memory"
    assert status.safety_status == "unsafe"
    assert status.semantic_status == "healthy"
    assert status.allows_destructive_compaction is False
    assert status.successful_flush is True
