"""Deterministic integrity helpers for DRACO result and trace artifacts."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

RESULT_EVIDENCE_SCHEMA = "opensquilla.draco.result-evidence/v1"
RESULT_EVIDENCE_SHA256_FIELD = "result_evidence_sha256"


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def result_evidence_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": RESULT_EVIDENCE_SCHEMA,
        "result": {
            key: value
            for key, value in row.items()
            if key != RESULT_EVIDENCE_SHA256_FIELD
        },
    }


def seal_result_row(row: dict[str, Any]) -> dict[str, Any]:
    """Return a copy whose hash commits to the complete final result row."""

    sealed = dict(row)
    sealed["result_evidence_schema"] = RESULT_EVIDENCE_SCHEMA
    sealed.pop(RESULT_EVIDENCE_SHA256_FIELD, None)
    sealed[RESULT_EVIDENCE_SHA256_FIELD] = canonical_json_sha256(
        result_evidence_payload(sealed)
    )
    return sealed


def verify_result_row_evidence(row: dict[str, Any]) -> bool:
    if row.get("result_evidence_schema") != RESULT_EVIDENCE_SCHEMA:
        return False
    actual = row.get(RESULT_EVIDENCE_SHA256_FIELD)
    if not isinstance(actual, str):
        return False
    try:
        expected = canonical_json_sha256(result_evidence_payload(row))
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(actual, expected)


def compact_tool_result_diagnostic(content: Any) -> dict[str, Any]:
    """Retain a bounded, non-content summary of a local web-tool envelope."""

    if not isinstance(content, str):
        return {}
    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    result: dict[str, Any] = {"error_present": bool(payload.get("error"))}
    for key in (
        "ok",
        "error_class",
        "status",
        "reason",
        "reason_code",
        "http_status",
        "blocked_domain",
    ):
        value = payload.get(key)
        if value is None or isinstance(value, bool | int | float):
            result[key] = value
        elif isinstance(value, str):
            result[key] = value[:160]
    return result


def compact_judge_summary(
    judge: Any, *, quality_total_value: Any = None
) -> dict[str, Any]:
    if not isinstance(judge, dict):
        return {}
    return {
        "mode": judge.get("mode"),
        "score_status": judge.get("score_status"),
        "quality_total": quality_total_value,
        "pass_rate": judge.get("pass_rate"),
        "valid_pass_rate": judge.get("valid_pass_rate"),
        "judge_error_count": judge.get("judge_error_count"),
        "criteria_count": judge.get("criteria_count"),
        "valid_criteria_count": judge.get("valid_criteria_count"),
        "invalid_criteria_count": judge.get("invalid_criteria_count"),
    }


def trace_row_from_result(row: dict[str, Any]) -> dict[str, Any]:
    """Return the sole valid compact trace representation of ``row``."""

    return {
        "trace_schema": RESULT_EVIDENCE_SCHEMA,
        RESULT_EVIDENCE_SHA256_FIELD: row.get(RESULT_EVIDENCE_SHA256_FIELD),
        "row_index": row.get("row_index"),
        "task_id": row.get("task_id"),
        "group": row.get("group"),
        "domain": row.get("domain"),
        "runner_mode": row.get("runner_mode"),
        "tools_enabled": row.get("tools_enabled"),
        "tool_policy": row.get("tool_policy") or {},
        "generation_policy": row.get("generation_policy") or {},
        "generation_config": row.get("generation_config") or {},
        "routing_trace": row.get("routing_trace") or {},
        "started_at": row.get("started_at"),
        "completed_at": row.get("completed_at"),
        "prompt_sha256": row.get("prompt_sha256"),
        "task_input_sha256": row.get("task_input_sha256"),
        "run_compatibility_fingerprint": row.get("run_compatibility_fingerprint"),
        "final_text_sha256": row.get("final_text_sha256"),
        "final_text_chars": row.get("final_text_chars"),
        "error": row.get("error"),
        "stream_tool_call_count": row.get("stream_tool_call_count"),
        "server_tool_call_count": row.get("server_tool_call_count"),
        "server_tool_use": row.get("server_tool_use") or {},
        "total_tool_call_count": row.get("total_tool_call_count"),
        "trajectory_steps": row.get("trajectory_steps"),
        "llm_request_count": row.get("llm_request_count"),
        "generation_attempt_count": row.get("generation_attempt_count"),
        "generation_max_attempts": row.get("generation_max_attempts"),
        "generation_retry_backoff_s": row.get("generation_retry_backoff_s"),
        "generation_attempt_total_billed_cost": row.get(
            "generation_attempt_total_billed_cost"
        ),
        "generation_retry_reasons": row.get("generation_retry_reasons") or [],
        "execution": row.get("execution") or {},
        "usage": row.get("usage") or {},
        "cost_accounting": row.get("cost_accounting") or {},
        "openrouter_non_byok_audit": row.get("openrouter_non_byok_audit") or {},
        "run_trace": row.get("run_trace") or {},
        "ensemble_trace": row.get("ensemble_trace") or {},
        "judge": compact_judge_summary(
            row.get("judge"), quality_total_value=row.get("quality_total")
        ),
        "candidate_judge_count": len(row.get("candidate_judges") or []),
        "fusion_delta": row.get("fusion_delta"),
    }
