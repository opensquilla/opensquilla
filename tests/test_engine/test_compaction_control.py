from __future__ import annotations

from opensquilla.engine.compaction_control import decide_compaction_continuation


def test_valid_compaction_receipt_continues_when_prompt_changed() -> None:
    decision = decide_compaction_continuation(
        receipt_safe=True,
        raw_session_durable=True,
        semantic_flush_ok=True,
        retry_count=0,
        max_retries=1,
        prompt_changed=True,
        finalization_attempted=False,
    )

    assert decision.action == "continue_after_compaction"


def test_semantic_flush_degradation_degrades_when_raw_session_is_durable() -> None:
    decision = decide_compaction_continuation(
        receipt_safe=True,
        raw_session_durable=True,
        semantic_flush_ok=False,
        retry_count=1,
        max_retries=1,
        prompt_changed=False,
        finalization_attempted=False,
    )

    assert decision.action == "degraded_continue_after_compaction"


def test_unsafe_receipt_blocks_as_context_unsalvageable() -> None:
    decision = decide_compaction_continuation(
        receipt_safe=False,
        raw_session_durable=True,
        semantic_flush_ok=True,
        retry_count=0,
        max_retries=1,
        prompt_changed=True,
        finalization_attempted=False,
    )

    assert decision.action == "blocked_after_compaction"
    assert decision.reason == "context_unsalvageable"


def test_retries_before_partial_or_failed_compaction_result() -> None:
    retry = decide_compaction_continuation(
        receipt_safe=True,
        raw_session_durable=True,
        semantic_flush_ok=True,
        retry_count=0,
        max_retries=1,
        prompt_changed=False,
        finalization_attempted=False,
    )
    partial = decide_compaction_continuation(
        receipt_safe=True,
        raw_session_durable=True,
        semantic_flush_ok=True,
        retry_count=1,
        max_retries=1,
        prompt_changed=False,
        finalization_attempted=False,
    )
    failed = decide_compaction_continuation(
        receipt_safe=True,
        raw_session_durable=True,
        semantic_flush_ok=True,
        retry_count=1,
        max_retries=1,
        prompt_changed=False,
        finalization_attempted=True,
    )

    assert retry.action == "retry_after_compaction"
    assert partial.action == "partial_after_compaction"
    assert failed.action == "failed_after_compaction"
