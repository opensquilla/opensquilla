from __future__ import annotations

from types import SimpleNamespace

from opensquilla.session.compaction_lifecycle import (
    compaction_memory_status,
    compaction_safety_allows_destructive_compaction,
    durable_receipt_allows_destructive_compaction,
    flush_compaction_decision,
    flush_receipt_allows_destructive_compaction,
    flush_receipt_status_for_compaction,
    flush_trigger_enabled,
    normalize_flush_triggers,
    pre_compaction_flush_enabled,
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


def test_flush_enabled_does_not_imply_pre_compaction_trigger() -> None:
    config = SimpleNamespace(memory=SimpleNamespace(flush_enabled=True))

    assert flush_trigger_enabled(config, "session_reset") is True
    assert pre_compaction_flush_enabled(config) is False


def test_pre_compaction_flush_accepts_explicit_trigger_or_legacy_flag() -> None:
    trigger_config = SimpleNamespace(
        memory=SimpleNamespace(
            flush_enabled=True,
            flush_triggers=["manual", "pre_compaction"],
        )
    )
    legacy_config = SimpleNamespace(
        memory=SimpleNamespace(
            flush_enabled=True,
            flush_pre_compaction=True,
        )
    )

    assert pre_compaction_flush_enabled(trigger_config) is True
    assert pre_compaction_flush_enabled(legacy_config) is True


def test_flush_triggers_normalize_aliases_and_strings() -> None:
    assert normalize_flush_triggers("reset, inline_overflow") == frozenset(
        {"session_reset", "pre_compaction"}
    )


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


def test_deterministic_safety_evidence_makes_semantic_flush_failure_non_fatal() -> None:
    receipt = _receipt(
        mode="raw",
        result_status="parse_failed_archived",
        flushed_paths=["memory/.raw_fallbacks/raw.md"],
        content_hash="h1",
        indexed_chunk_count=0,
        integrity_status="unverified",
        output_coverage_status="unverified",
        obligation_status="unverified",
    )

    status = compaction_memory_status(
        receipt,
        deterministic_receipt_safe=True,
    )

    assert status.safety_status == "safe"
    assert status.semantic_status == "failed"
    assert status.allows_destructive_compaction is True


def test_raw_archive_receipt_is_degraded_archive_safety_evidence() -> None:
    receipt = _receipt(
        mode="raw",
        result_status="ok_archive_only",
        flushed_paths=["memory/.raw_fallbacks/raw.md"],
        content_hash="h1",
        indexed_chunk_count=0,
        integrity_status="unverified",
        output_coverage_status="unverified",
        obligation_status="unverified",
    )

    status = compaction_memory_status(receipt)

    assert status.safety_status == "degraded_archive"
    assert status.semantic_status == "degraded"
    assert status.allows_destructive_compaction is True
    assert compaction_safety_allows_destructive_compaction(receipt) is True


def test_raw_archive_receipt_without_content_hash_is_unsafe() -> None:
    receipt = _receipt(
        mode="raw",
        result_status="ok_archive_only",
        flushed_paths=["memory/.raw_fallbacks/raw.md"],
        content_hash="",
        indexed_chunk_count=0,
        integrity_status="unverified",
        output_coverage_status="unverified",
        obligation_status="unverified",
    )

    status = compaction_memory_status(receipt)

    assert status.safety_status == "unsafe"
    assert status.semantic_status == "degraded"
    assert status.allows_destructive_compaction is False
    assert compaction_safety_allows_destructive_compaction(receipt) is False


def test_raw_archive_receipt_accepts_string_flushed_path() -> None:
    receipt = _receipt(
        mode="raw",
        result_status="ok_archive_only",
        flushed_paths="memory/.raw_fallbacks/raw.md",
        content_hash="h1",
        indexed_chunk_count=0,
        integrity_status="unverified",
        output_coverage_status="unverified",
        obligation_status="unverified",
    )

    status = compaction_memory_status(receipt)

    assert status.safety_status == "degraded_archive"
    assert status.semantic_status == "degraded"
    assert status.allows_destructive_compaction is True
    assert compaction_safety_allows_destructive_compaction(receipt) is True


def test_archive_failed_without_deterministic_evidence_is_unsafe() -> None:
    receipt = _receipt(
        mode="error",
        result_status="archive_failed",
        flushed_paths=[],
        content_hash="h1",
        indexed_chunk_count=0,
        integrity_status="unverified",
        output_coverage_status="unverified",
        obligation_status="unverified",
    )

    status = compaction_memory_status(receipt)

    assert status.safety_status == "unsafe"
    assert status.semantic_status == "failed"
    assert status.allows_destructive_compaction is False


def test_durable_preimage_receipt_allows_destructive_compaction() -> None:
    receipt = _receipt(
        scope="preimage",
        status="preimage_saved",
        target_path="memory/.raw_fallbacks/raw.md",
        content_hash="h1",
    )

    assert durable_receipt_allows_destructive_compaction(receipt) is True


def test_durable_repair_pending_archive_receipt_allows_destructive_compaction() -> None:
    receipt = _receipt(
        scope="repair",
        status="repair_pending",
        reason="apply_failed_archived",
        target_path="memory/.raw_fallbacks/raw.md",
        content_hash="h1",
    )

    assert durable_receipt_allows_destructive_compaction(receipt) is True


def test_durable_preimage_receipt_without_archive_hash_is_unsafe() -> None:
    receipt = _receipt(
        scope="preimage",
        status="preimage_saved",
        target_path="memory/.raw_fallbacks/raw.md",
        content_hash="",
    )

    assert durable_receipt_allows_destructive_compaction(receipt) is False
