#!/usr/bin/env python3
"""Audit DRACO result shards and materialize retry/final JSONL artifacts."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

GROUPS = ("B0", "B1", "B2", "B3", "B4", "G1")
FIXED_MODELS = {
    "B0": "anthropic/claude-opus-4.8",
    "B4": "openai/gpt-5.5",
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"JSONL row is not an object at {path}:{line_number}")
            value["_audit_source"] = str(path)
            value["_audit_source_line"] = line_number
            rows.append(value)
    return rows


def invalid_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if row.get("error"):
        reasons.append("error")
    if not str(row.get("final_text") or "").strip():
        reasons.append("empty_final_text")
    if row.get("quality_total") is None:
        reasons.append("missing_quality_total")

    judge = row.get("judge") or {}
    if judge.get("score_status") != "complete":
        reasons.append("judge_incomplete")
    if judge.get("judge_error_count") != 0:
        reasons.append("judge_errors")

    trace = row.get("ensemble_trace") or {}
    total = trace.get("total_candidates")
    successful = trace.get("successful_proposers")
    if total is not None and (successful is None or successful < total):
        reasons.append("incomplete_ensemble")

    group = str(row.get("group") or "")
    expected_model = FIXED_MODELS.get(group)
    if expected_model is not None:
        actual_model = ((row.get("provider_spec") or {}).get("model"))
        if actual_model != expected_model:
            reasons.append("wrong_fixed_model")
    return reasons


def clean_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if not key.startswith("_audit_")}


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--result", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--prefix", default="draco_audit")
    parser.add_argument(
        "--skip-final",
        action="store_true",
        help="Skip writing the large merged final JSONL during intermediate retry audits.",
    )
    args = parser.parse_args()

    input_rows = read_jsonl(args.input)
    task_ids = [str(row.get("id") or "") for row in input_rows]
    if not task_ids or any(not task_id for task_id in task_ids):
        raise ValueError("input contains a missing task id")
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("input contains duplicate task ids")
    expected_keys = {(group, task_id) for group in GROUPS for task_id in task_ids}

    rows: list[dict[str, Any]] = []
    for path in args.result:
        rows.extend(read_jsonl(path))

    rows_by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    unexpected_rows: list[dict[str, Any]] = []
    for row in rows:
        key = (str(row.get("group") or ""), str(row.get("task_id") or ""))
        if key not in expected_keys:
            unexpected_rows.append(row)
        else:
            rows_by_key[key].append(row)
    observed_keys = set(rows_by_key)

    chosen: dict[tuple[str, str], dict[str, Any]] = {}
    latest_reasons: dict[tuple[str, str], list[str]] = {}
    reason_counts: Counter[str] = Counter()
    attempt_reason_counts: Counter[str] = Counter()
    for key, attempts in rows_by_key.items():
        valid_attempts = [row for row in attempts if not invalid_reasons(row)]
        if valid_attempts:
            chosen[key] = valid_attempts[-1]
        else:
            reasons = invalid_reasons(attempts[-1])
            latest_reasons[key] = reasons
            reason_counts.update(reasons)
        for attempt in attempts:
            attempt_reason_counts.update(invalid_reasons(attempt))

    unresolved_keys = sorted(
        expected_keys - set(chosen),
        key=lambda item: (GROUPS.index(item[0]), task_ids.index(item[1])),
    )
    retry_rows = [{"group": group, "task_id": task_id} for group, task_id in unresolved_keys]
    final_rows = [
        clean_row(chosen[(group, task_id)])
        for group in GROUPS
        for task_id in task_ids
        if (group, task_id) in chosen
    ]

    per_group = {}
    for group in GROUPS:
        expected = {(group, task_id) for task_id in task_ids}
        valid = expected & set(chosen)
        per_group[group] = {
            "expected": len(expected),
            "raw_attempts": sum(len(rows_by_key.get(key, [])) for key in expected),
            "present_unique": len(expected & observed_keys),
            "valid_unique": len(valid),
            "unresolved": len(expected - valid),
        }

    report = {
        "groups": list(GROUPS),
        "input_task_count": len(task_ids),
        "expected_unique": len(expected_keys),
        "raw_attempts": len(rows),
        "raw_unique_expected": len(observed_keys),
        "raw_duplicate_attempts": sum(
            max(0, len(attempts) - 1) for attempts in rows_by_key.values()
        ),
        "unexpected_rows": len(unexpected_rows),
        "valid_unique": len(chosen),
        "unresolved_unique": len(unresolved_keys),
        "unresolved_missing": sum(1 for key in unresolved_keys if key not in observed_keys),
        "unresolved_present_but_invalid": sum(1 for key in unresolved_keys if key in observed_keys),
        "latest_invalid_reason_counts": dict(sorted(reason_counts.items())),
        "all_attempt_invalid_reason_counts": dict(sorted(attempt_reason_counts.items())),
        "per_group": per_group,
        "complete": (
            len(chosen) == len(expected_keys)
            and not unresolved_keys
            and not unexpected_rows
            and len(final_rows) == len(expected_keys)
        ),
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.output_dir / f"{args.prefix}.json"
    retry_path = args.output_dir / f"{args.prefix}.retry_keys.jsonl"
    final_path = args.output_dir / f"{args.prefix}.final.jsonl"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_jsonl(retry_path, retry_rows)
    if not args.skip_final:
        write_jsonl(final_path, final_rows)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"report={report_path}")
    print(f"retry_keys={retry_path}")
    if not args.skip_final:
        print(f"final={final_path}")
    return 0 if report["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
