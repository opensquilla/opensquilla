from __future__ import annotations

from opensquilla.cli.memory_flush_cmd import (
    MemoryFlushSessionResult,
    _emit_text_result,
    _receipt_is_complete_flush,
    _zero_usage,
)


def test_receipt_is_complete_flush_rejects_raw_and_degraded_llm() -> None:
    assert not _receipt_is_complete_flush(
        {
            "mode": "raw",
            "flushed_paths": ["memory/.raw_fallbacks/raw.md"],
            "raw_reason": "timeout",
        }
    )
    assert not _receipt_is_complete_flush(
        {
            "mode": "llm",
            "indexed_chunk_count": 1,
            "integrity_status": "missing_chunks",
            "output_coverage_status": "ok",
        }
    )
    assert _receipt_is_complete_flush(
        {
            "mode": "llm",
            "indexed_chunk_count": 1,
            "integrity_status": "ok",
            "output_coverage_status": "ok",
            "invalid_candidate_count": 0,
            "candidate_missing_ids": [],
            "obligation_status": "ok",
            "obligation_missing_ids": [],
        }
    )


def test_emit_text_result_labels_raw_fallback_as_degraded(capsys) -> None:
    result = MemoryFlushSessionResult(
        ok=False,
        key="agent:main:webchat:s1",
        agent_id="main",
        message_window="all",
        flush_max_chars="default",
        segment_mode="auto",
        segment_max_chars="default",
        segment_overlap_messages=0,
        flush_receipt={
            "mode": "raw",
            "flushed_paths": ["memory/.raw_fallbacks/raw.md"],
            "raw_reason": "timeout",
        },
        usage=_zero_usage(),
        usage_path=None,
    )

    _emit_text_result(result, success=False)

    captured = capsys.readouterr()
    assert "Flush degraded to raw backup" in captured.out
    assert "Backup path: memory/.raw_fallbacks/raw.md" in captured.out
    assert "not searchable durable memory" in captured.err
