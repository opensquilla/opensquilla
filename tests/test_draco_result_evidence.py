from __future__ import annotations

from opensquilla.eval.draco_artifact_integrity import (
    RESULT_EVIDENCE_SCHEMA,
    compact_tool_result_diagnostic,
    seal_result_row,
    trace_row_from_result,
    verify_result_row_evidence,
)


def test_result_evidence_commits_to_every_nested_field() -> None:
    sealed = seal_result_row(
        {
            "row_index": 1,
            "group": "B2",
            "task_id": "task-1",
            "execution": {"generation_attempts": [{"attempt": 1}]},
            "judge": {"score_status": "complete"},
        }
    )

    assert sealed["result_evidence_schema"] == RESULT_EVIDENCE_SCHEMA
    assert verify_result_row_evidence(sealed) is True

    sealed["execution"]["generation_attempts"][0]["attempt"] = 2
    assert verify_result_row_evidence(sealed) is False


def test_trace_is_an_exact_projection_bound_to_the_sealed_result() -> None:
    first = seal_result_row(
        {
            "row_index": 1,
            "group": "B2",
            "task_id": "task-1",
            "final_text_sha256": "a" * 64,
            "judge": {"mode": "draco_criterion_judgments"},
            "quality_total": 100.0,
        }
    )
    first_trace = trace_row_from_result(first)
    second = seal_result_row({**first, "quality_total": 0.0})
    second_trace = trace_row_from_result(second)

    assert first_trace["result_evidence_sha256"] == first["result_evidence_sha256"]
    assert first_trace != second_trace
    assert second_trace["judge"]["quality_total"] == 0.0


def test_tool_diagnostic_retains_status_without_copying_error_body() -> None:
    diagnostic = compact_tool_result_diagnostic(
        '{"ok":false,"error":{"message":"private response body"},'
        '"error_class":"ConnectTimeout","reason":"network timeout"}'
    )

    assert diagnostic["error_present"] is True
    assert diagnostic["ok"] is False
    assert diagnostic["error_class"] == "ConnectTimeout"
    assert diagnostic["reason"] == "network timeout"
    assert "private response body" not in repr(diagnostic)
