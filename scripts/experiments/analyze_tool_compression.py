#!/usr/bin/env python3
"""Summarize tool-result compression diagnostics from run artifacts."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from opensquilla.result_budget import exec_command_invokes_source_context_read

HUGE_OUTPUT_CHARS = 1_000_000
SCRATCH_PATCH_NAMES = {
    "analysis.py",
    "analyze.py",
    "analyze_issue.py",
    "apply.py",
    "apply_fix.py",
    "fix.py",
    "patch.py",
    "reproduce.py",
    "reproduce_issue.py",
}
AUXILIARY_ARTIFACT_DIR_NAMES = {
    "empty_patch_recovery",
}
EVAL_STATUS_ID_FIELDS: tuple[tuple[str, str], ...] = (
    ("resolved", "resolved_ids"),
    ("empty_patch", "empty_patch_ids"),
    ("error", "error_ids"),
    ("unresolved", "unresolved_ids"),
    ("incomplete", "incomplete_ids"),
    ("completed", "completed_ids"),
    ("submitted", "submitted_ids"),
)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    rows.append(payload)
    except OSError:
        pass
    return rows


def _instance_dirs(paths: list[Path]) -> list[Path]:
    found: set[Path] = set()
    for raw_path in paths:
        path = raw_path.expanduser().resolve()
        if not path.exists():
            continue
        if _looks_like_instance_dir(path):
            found.add(path)
            continue
        for child in path.rglob("runtime_events.jsonl"):
            if _looks_like_instance_dir(child.parent):
                found.add(child.parent)
    return sorted(found)


def _looks_like_instance_dir(path: Path) -> bool:
    if path.name in AUXILIARY_ARTIFACT_DIR_NAMES:
        return False
    return (path / "runtime_events.jsonl").exists() or (path / "metadata.json").exists()


def _counter_dict(counter: Counter[str]) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}


def _eval_statuses_from_report(path: Path) -> dict[str, str]:
    data = _read_json(path)
    statuses: dict[str, str] = {}
    for status, key in EVAL_STATUS_ID_FIELDS:
        values = data.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, str) or not value:
                continue
            statuses.setdefault(value, status)
    return statuses


def _load_eval_reports(paths: list[Path]) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for path in paths:
        resolved = path.expanduser().resolve()
        if not resolved.exists():
            continue
        statuses = _eval_statuses_from_report(resolved)
        if statuses:
            reports.append({"path": str(resolved), "name": resolved.name, "statuses": statuses})
    return reports


def _eval_status_for_instance(
    instance: dict[str, Any],
    eval_reports: list[dict[str, Any]],
) -> dict[str, Any]:
    if not eval_reports:
        return {"status": "not_provided"}
    instance_id = str(instance.get("instance_id") or "")
    run_id = str(instance.get("run_id") or "")
    matching_reports = [
        report for report in eval_reports if run_id and run_id in str(report.get("name") or "")
    ]
    if not matching_reports:
        matching_reports = eval_reports
    statuses = {
        str(report.get("statuses", {}).get(instance_id))
        for report in matching_reports
        if report.get("statuses", {}).get(instance_id)
    }
    statuses.discard("")
    statuses.discard("None")
    if not statuses:
        return {"status": "not_evaluated"}
    if len(statuses) == 1:
        return {"status": next(iter(statuses))}
    return {"status": "conflict", "statuses": sorted(statuses)}


def _annotate_eval_status(
    instances: list[dict[str, Any]],
    eval_reports: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not eval_reports:
        for item in instances:
            item["eval"] = {"status": "not_provided"}
        return instances
    for item in instances:
        item["eval"] = _eval_status_for_instance(item, eval_reports)
    return instances


def _patch_paths(patch_path: Path) -> list[str]:
    paths: list[str] = []
    try:
        for line in patch_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.startswith("diff --git "):
                continue
            parts = line.split()
            if len(parts) >= 4:
                paths.append(parts[2].removeprefix("a/"))
    except OSError:
        pass
    return paths


def _scratch_patch_paths(paths: list[str]) -> list[str]:
    flagged: list[str] = []
    for path in paths:
        basename = path.rsplit("/", 1)[-1]
        if "/" not in path and (
            basename in SCRATCH_PATCH_NAMES
            or basename.startswith(
                (
                    "analysis_",
                    "analyze_",
                    "apply_",
                    "fix_",
                    "patch_",
                    "reproduce_",
                )
            )
        ):
            flagged.append(path)
    return flagged


def _read_raw_store_payload(meta_path: Path, meta: dict[str, Any]) -> bytes | None:
    content_name = str(meta.get("content_file") or "content.txt")
    content_path = meta_path.parent / content_name
    try:
        payload = content_path.read_bytes()
    except OSError:
        return None
    if str(meta.get("storage_encoding") or "utf-8") == "gzip+utf-8":
        try:
            return gzip.decompress(payload)
        except OSError:
            return None
    return payload


def _raw_store_stats(instance_dir: Path, events: list[dict[str, Any]]) -> dict[str, Any]:
    roots = [
        instance_dir / "opensquilla_state" / "media" / "tool-results",
        instance_dir / "tool-results",
    ]
    metas: list[dict[str, Any]] = []
    handle_counts: Counter[str] = Counter()
    tool_use_counts: Counter[str] = Counter()
    handle_payload_sha256: dict[str, str] = {}
    handle_payload_size_bytes: dict[str, int] = {}
    handle_payload_chars: dict[str, int] = {}
    invalid_meta = 0
    content_missing = 0
    hash_mismatches = 0
    size_mismatches = 0
    for root in roots:
        if not root.exists():
            continue
        for meta_path in root.rglob("meta.json"):
            meta = _read_json(meta_path)
            if not meta:
                invalid_meta += 1
                continue
            metas.append(meta)
            handle = str(meta.get("handle") or "")
            tool_use_id = str(meta.get("tool_use_id") or "")
            if handle:
                handle_counts[handle] += 1
            if tool_use_id:
                tool_use_counts[tool_use_id] += 1
            payload = _read_raw_store_payload(meta_path, meta)
            if payload is None:
                content_missing += 1
                continue
            actual_sha = hashlib.sha256(payload).hexdigest()
            if handle:
                handle_payload_sha256[handle] = actual_sha
                handle_payload_size_bytes[handle] = len(payload)
                handle_payload_chars[handle] = len(
                    payload.decode("utf-8", errors="replace")
                )
            expected_sha = str(meta.get("sha256") or "")
            if expected_sha and actual_sha != expected_sha:
                hash_mismatches += 1
            try:
                expected_size = int(meta.get("size_bytes") or 0)
            except (TypeError, ValueError):
                expected_size = 0
            if expected_size and expected_size != len(payload):
                size_mismatches += 1
    projection_tool_use_ids = {
        str(event.get("tool_use_id") or "")
        for event in events
        if event.get("feature") == "tool_result_projection" and event.get("tool_use_id")
    }
    projection_handles = {
        str(event.get("tool_result_handle") or "")
        for event in events
        if event.get("feature") == "tool_result_projection"
        and event.get("tool_result_handle")
    }
    handles = set(handle_counts)
    tool_use_ids = set(tool_use_counts)
    return {
        "records": len(metas),
        "handles": sorted(handles),
        "handle_payload_sha256": handle_payload_sha256,
        "handle_payload_size_bytes": handle_payload_size_bytes,
        "handle_payload_chars": handle_payload_chars,
        "unique_handles": len(handle_counts),
        "duplicate_handle_records": sum(
            max(0, count - 1) for count in handle_counts.values()
        ),
        "unique_tool_use_ids": len(tool_use_counts),
        "duplicate_tool_use_records": sum(
            max(0, count - 1) for count in tool_use_counts.values()
        ),
        "compressed_records": sum(
            1 for meta in metas if meta.get("storage_encoding") == "gzip+utf-8"
        ),
        "raw_size_bytes": sum(int(meta.get("size_bytes") or 0) for meta in metas),
        "stored_size_bytes": sum(int(meta.get("stored_size_bytes") or 0) for meta in metas),
        "invalid_meta": invalid_meta,
        "content_missing": content_missing,
        "hash_mismatches": hash_mismatches,
        "size_mismatches": size_mismatches,
        "projection_tool_use_ids": len(projection_tool_use_ids),
        "projection_tool_use_ids_covered": len(projection_tool_use_ids & tool_use_ids),
        "projection_tool_use_ids_missing": len(projection_tool_use_ids - tool_use_ids),
        "projection_handles": len(projection_handles),
        "projection_handles_covered": len(projection_handles & handles),
        "projection_handles_missing": len(projection_handles - handles),
    }


def _dispatch_truncation_summary(
    transcript_path: Path,
    *,
    raw_store_handles: set[str],
) -> dict[str, Any]:
    events = 0
    huge_events = 0
    handle_present = 0
    handles_missing = 0
    original_chars = 0
    returned_chars = 0
    tools: Counter[str] = Counter()
    categories: Counter[str] = Counter()
    for row in _iter_jsonl(transcript_path):
        message = row.get("message")
        if not isinstance(message, dict) or message.get("role") != "toolResult":
            continue
        tool_name = str(message.get("toolName") or "")
        for block in message.get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            text = block.get("text")
            if not isinstance(text, str):
                continue
            try:
                payload = json.loads(text)
            except (TypeError, ValueError):
                continue
            if not isinstance(payload, dict) or payload.get("result_truncated") is not True:
                continue
            if "preview" not in payload and "tool_result_handle" not in payload:
                continue
            events += 1
            if tool_name:
                tools[tool_name] += 1
            try:
                original = int(payload.get("result_original_chars") or 0)
            except (TypeError, ValueError):
                original = 0
            original_chars += original
            returned_chars += len(text)
            handle = str(payload.get("tool_result_handle") or "")
            if handle:
                handle_present += 1
                if handle not in raw_store_handles:
                    handles_missing += 1
                    categories["dispatch_truncation_handle_missing"] += 1
            else:
                handles_missing += 1
                categories["dispatch_truncation_handle_missing"] += 1
            if (
                original >= HUGE_OUTPUT_CHARS
                and tool_name
                in {"background_process", "exec_command", "execute_code", "process"}
            ):
                huge_events += 1
                categories["dispatch_huge_exec_log"] += 1
    return {
        "events": events,
        "huge_events": huge_events,
        "handle_present": handle_present,
        "handles_missing": handles_missing,
        "original_chars": original_chars,
        "returned_chars": returned_chars,
        "tools": _counter_dict(tools),
        "categories": _counter_dict(categories),
    }


def _projection_envelope_metadata(text: str) -> dict[str, str] | None:
    if not text.startswith(
        ("[tool_result_projection]\n", "[aggregate_tool_result_compacted]\n")
    ):
        return None
    metadata: dict[str, str] = {}
    for line in text.splitlines()[1:20]:
        key, separator, value = line.partition(":")
        if not separator:
            continue
        key = key.strip()
        if key in {"tool_result_handle", "sha256", "original_chars"}:
            metadata[key] = value.strip()
    return metadata


def _transcript_projection_summary(
    transcript_path: Path,
    *,
    raw_store: dict[str, Any],
) -> dict[str, Any]:
    events = 0
    handle_present = 0
    handles_missing = 0
    sha_missing = 0
    sha_mismatches = 0
    size_mismatches = 0
    categories: Counter[str] = Counter()
    raw_sha = raw_store.get("handle_payload_sha256")
    raw_chars = raw_store.get("handle_payload_chars")
    sha_by_handle = raw_sha if isinstance(raw_sha, dict) else {}
    chars_by_handle = raw_chars if isinstance(raw_chars, dict) else {}

    for row in _iter_jsonl(transcript_path):
        message = row.get("message")
        if not isinstance(message, dict) or message.get("role") != "toolResult":
            continue
        for block in message.get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            text = block.get("text")
            if not isinstance(text, str):
                continue
            metadata = _projection_envelope_metadata(text)
            if metadata is None:
                continue
            events += 1
            handle = metadata.get("tool_result_handle") or ""
            if not handle:
                handles_missing += 1
                categories["transcript_projection_handle_missing"] += 1
                continue
            handle_present += 1
            actual_sha = sha_by_handle.get(handle)
            actual_chars = chars_by_handle.get(handle)
            if not actual_sha or actual_chars is None:
                handles_missing += 1
                categories["transcript_projection_handle_missing"] += 1
                continue
            expected_sha = metadata.get("sha256") or ""
            if not expected_sha:
                sha_missing += 1
            elif expected_sha != actual_sha:
                sha_mismatches += 1
                categories["transcript_projection_sha_mismatch"] += 1
            try:
                expected_chars = int(metadata.get("original_chars") or 0)
            except (TypeError, ValueError):
                expected_chars = 0
            if expected_chars and expected_chars != int(actual_chars):
                size_mismatches += 1
                categories["transcript_projection_size_mismatch"] += 1
    return {
        "events": events,
        "handle_present": handle_present,
        "handles_missing": handles_missing,
        "sha_missing": sha_missing,
        "sha_mismatches": sha_mismatches,
        "size_mismatches": size_mismatches,
        "replay_bad": handles_missing + sha_mismatches + size_mismatches,
        "categories": _counter_dict(categories),
    }


def _retrieval_result_metadata(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        return {}
    try:
        payload = json.loads(stripped)
    except (TypeError, ValueError):
        payload = None
    if isinstance(payload, dict):
        continuation = payload.get("continuation")
        strategy = ""
        if isinstance(continuation, dict):
            strategy = str(continuation.get("next_call_strategy") or "")
        return {
            "mode": str(payload.get("retrieval_mode") or payload.get("mode") or ""),
            "truncated": bool(payload.get("results_limited") or payload.get("next_offset")),
            "continuation": bool(
                isinstance(continuation, dict) and continuation.get("next_call")
            ),
            "continuation_strategy": strategy,
        }

    mode = ""
    continuation_strategy = ""
    for line in stripped.splitlines()[:20]:
        key, separator, value = line.partition(":")
        if not separator:
            continue
        key = key.strip()
        value = value.strip()
        if key == "mode":
            mode = value
        elif key == "continuation.next_call_strategy":
            continuation_strategy = value
    return {
        "mode": mode,
        "truncated": "[retrieve_tool_result truncated:" in stripped,
        "continuation": bool("continuation.next_call:" in stripped),
        "continuation_strategy": continuation_strategy,
    }


def _retrieval_summary(transcript_path: Path) -> dict[str, Any]:
    calls = 0
    modes: Counter[str] = Counter()
    results = 0
    result_modes: Counter[str] = Counter()
    truncated_results = 0
    continuation_suggestions = 0
    continuation_strategies: Counter[str] = Counter()
    categories: Counter[str] = Counter()
    for row in _iter_jsonl(transcript_path):
        message = row.get("message")
        if not isinstance(message, dict):
            continue
        for block in message.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "toolCall" or block.get("name") != "retrieve_tool_result":
                if (
                    message.get("role") == "toolResult"
                    and message.get("toolName") == "retrieve_tool_result"
                    and block.get("type") == "text"
                    and isinstance(block.get("text"), str)
                ):
                    results += 1
                    metadata = _retrieval_result_metadata(block["text"])
                    result_mode = str(metadata.get("mode") or "unknown")
                    result_modes[result_mode] += 1
                    if metadata.get("truncated"):
                        truncated_results += 1
                    if metadata.get("continuation"):
                        continuation_suggestions += 1
                        strategy = str(metadata.get("continuation_strategy") or "unknown")
                        continuation_strategies[strategy] += 1
                continue
            calls += 1
            args = block.get("arguments") if isinstance(block.get("arguments"), dict) else {}
            mode = str(args.get("mode") or ("query" if args.get("query") else "metadata"))
            modes[mode] += 1
    if calls > results:
        categories["retrieval_result_missing"] += calls - results
    if truncated_results > continuation_suggestions:
        categories["retrieval_truncated_without_continuation"] += (
            truncated_results - continuation_suggestions
        )
    return {
        "calls": calls,
        "modes": _counter_dict(modes),
        "results": results,
        "result_modes": _counter_dict(result_modes),
        "truncated_results": truncated_results,
        "continuation_suggestions": continuation_suggestions,
        "continuation_strategies": _counter_dict(continuation_strategies),
        "categories": _counter_dict(categories),
    }


def _usage(instance_dir: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    usage = _read_json(instance_dir / "usage.json")
    if not usage:
        agent = metadata.get("agent") if isinstance(metadata.get("agent"), dict) else {}
        usage = agent.get("usage") if isinstance(agent.get("usage"), dict) else {}
    input_tokens = int(usage.get("input_tokens") or 0)
    cached_tokens = int(usage.get("cached_tokens") or 0)
    return {
        "input_tokens": input_tokens,
        "cached_tokens": cached_tokens,
        "kv_cache_hit_rate": (cached_tokens / input_tokens) if input_tokens > 0 else None,
        "request_count": int(usage.get("request_count") or 0),
        "cost_usd": float(usage.get("cost_usd") or 0.0),
    }


def _projection_event_command(event: dict[str, Any]) -> str | None:
    command = event.get("command")
    if isinstance(command, str) and command:
        return command
    arguments = event.get("tool_arguments")
    if isinstance(arguments, dict):
        for key in ("command", "cmd"):
            value = arguments.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _projection_summary(events: list[dict[str, Any]], retrieve_calls: int) -> dict[str, Any]:
    projection_events = [row for row in events if row.get("feature") == "tool_result_projection"]
    reasons: Counter[str] = Counter()
    tools: Counter[str] = Counter()
    categories: Counter[str] = Counter()
    original_chars = 0
    projected_chars = 0
    saved_chars = 0
    applied = 0
    noop = 0
    handle_present = 0
    semantic_preserves = 0
    huge_events = 0

    for event in projection_events:
        reason = str(event.get("reason") or "")
        tool_name = str(event.get("tool_name") or "")
        outcome = str(event.get("outcome") or "")
        original = int(event.get("original_chars") or 0)
        projected = int(event.get("projected_chars") or 0)
        saved = int(event.get("saved_chars") or 0)
        has_handle = bool(event.get("tool_result_handle_present"))

        if reason:
            reasons[reason] += 1
        if tool_name:
            tools[tool_name] += 1
        original_chars += original
        projected_chars += projected
        saved_chars += saved

        if outcome == "applied":
            applied += 1
            if tool_name == "read_file" or (
                tool_name == "exec_command"
                and exec_command_invokes_source_context_read(
                    _projection_event_command(event),
                    content="",
                    content_chars=original,
                )
            ):
                categories["source_lost"] += 1
            if tool_name == "git_diff" or reason == "semantic_git_diff_preserved":
                categories["diff_lost"] += 1
            if not has_handle:
                categories["store_missing"] += 1
        else:
            noop += 1

        if has_handle:
            handle_present += 1
        if reason.startswith("semantic_"):
            semantic_preserves += 1
        if "store" in reason and outcome != "applied":
            categories["store_budget_exceeded"] += 1
        if reason in {"non_shrinking_after_envelope", "no_reduction"}:
            categories["compression_overhead_no_benefit"] += 1
        if (
            original >= HUGE_OUTPUT_CHARS
            and tool_name in {"grep_search", "exec_command", "process"}
        ):
            huge_events += 1
            categories["huge_grep_log"] += 1
            if outcome == "applied" and not has_handle:
                categories["store_missing"] += 1

    if handle_present and retrieve_calls == 0:
        categories["retrieval_unused"] += handle_present
    if retrieve_calls and handle_present and retrieve_calls < handle_present:
        categories["retrieval_insufficient"] += handle_present - retrieve_calls
    if applied and handle_present and retrieve_calls == 0:
        categories["projection_without_retrieve"] += applied

    return {
        "events": len(projection_events),
        "applied": applied,
        "noop": noop,
        "handle_present": handle_present,
        "semantic_preserves": semantic_preserves,
        "huge_events": huge_events,
        "original_chars": original_chars,
        "projected_chars": projected_chars,
        "saved_chars": saved_chars,
        "reasons": _counter_dict(reasons),
        "tools": _counter_dict(tools),
        "categories": _counter_dict(categories),
    }


def summarize_instance(instance_dir: Path) -> dict[str, Any]:
    metadata = _read_json(instance_dir / "metadata.json")
    usage = _usage(instance_dir, metadata)
    retrieval = _retrieval_summary(instance_dir / "transcript.jsonl")
    runtime_events = _iter_jsonl(instance_dir / "runtime_events.jsonl")
    patch_paths = _patch_paths(instance_dir / "git.patch")
    patch_empty = bool(metadata.get("patch_empty", not bool(patch_paths)))
    projection = _projection_summary(runtime_events, int(retrieval["calls"]))
    raw_store = _raw_store_stats(instance_dir, runtime_events)
    dispatch_truncation = _dispatch_truncation_summary(
        instance_dir / "transcript.jsonl",
        raw_store_handles=set(raw_store.get("handles") or []),
    )
    transcript_projection = _transcript_projection_summary(
        instance_dir / "transcript.jsonl",
        raw_store=raw_store,
    )
    raw_store_output = dict(raw_store)
    raw_store_output.pop("handle_payload_sha256", None)
    raw_store_output.pop("handle_payload_size_bytes", None)
    raw_store_output.pop("handle_payload_chars", None)

    return {
        "instance_id": metadata.get("instance_id") or instance_dir.name,
        "run_id": metadata.get("run_id") or instance_dir.parent.name,
        "model": metadata.get("model"),
        "state": metadata.get("state"),
        "patch_empty": patch_empty,
        "duration_seconds": metadata.get("duration_seconds"),
        "error": metadata.get("error"),
        "usage": usage,
        "projection": projection,
        "dispatch_truncation": dispatch_truncation,
        "transcript_projection": transcript_projection,
        "retrieval": retrieval,
        "raw_store": raw_store_output,
        "patch": {
            "paths": patch_paths,
            "scratch_paths": _scratch_patch_paths(patch_paths),
        },
    }


def aggregate(instances: list[dict[str, Any]]) -> dict[str, Any]:
    categories: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    raw_records = 0
    raw_unique_tool_use_ids = 0
    raw_duplicate_tool_use_records = 0
    raw_content_missing = 0
    raw_hash_mismatches = 0
    raw_size_mismatches = 0
    raw_projection_tool_use_ids_missing = 0
    raw_projection_handles_missing = 0
    projection_events = 0
    projection_applied = 0
    dispatch_truncation_events = 0
    dispatch_truncation_huge_events = 0
    dispatch_truncation_handles_missing = 0
    dispatch_truncation_original_chars = 0
    dispatch_truncation_returned_chars = 0
    transcript_projection_events = 0
    transcript_projection_replay_bad = 0
    transcript_projection_handles_missing = 0
    transcript_projection_sha_mismatches = 0
    transcript_projection_size_mismatches = 0
    retrieve_calls = 0
    retrieve_results = 0
    retrieve_truncated_results = 0
    retrieve_continuation_suggestions = 0
    retrieve_continuation_strategies: Counter[str] = Counter()
    input_tokens = 0
    cached_tokens = 0
    empty_patches = 0
    scratch_patch_instances = 0
    eval_statuses: Counter[str] = Counter()
    for item in instances:
        projection = item["projection"]
        categories.update(projection["categories"])
        reasons.update(projection["reasons"])
        raw_records += int(item["raw_store"]["records"])
        raw_unique_tool_use_ids += int(item["raw_store"]["unique_tool_use_ids"])
        raw_duplicate_tool_use_records += int(
            item["raw_store"]["duplicate_tool_use_records"]
        )
        raw_content_missing += int(item["raw_store"]["content_missing"])
        raw_hash_mismatches += int(item["raw_store"]["hash_mismatches"])
        raw_size_mismatches += int(item["raw_store"]["size_mismatches"])
        raw_projection_tool_use_ids_missing += int(
            item["raw_store"]["projection_tool_use_ids_missing"]
        )
        raw_projection_handles_missing += int(
            item["raw_store"]["projection_handles_missing"]
        )
        projection_events += int(projection["events"])
        projection_applied += int(projection["applied"])
        truncation = item.get("dispatch_truncation") or {}
        dispatch_truncation_events += int(truncation.get("events") or 0)
        dispatch_truncation_huge_events += int(truncation.get("huge_events") or 0)
        dispatch_truncation_handles_missing += int(
            truncation.get("handles_missing") or 0
        )
        dispatch_truncation_original_chars += int(
            truncation.get("original_chars") or 0
        )
        dispatch_truncation_returned_chars += int(
            truncation.get("returned_chars") or 0
        )
        categories.update(truncation.get("categories") or {})
        transcript_projection = item.get("transcript_projection") or {}
        transcript_projection_events += int(transcript_projection.get("events") or 0)
        transcript_projection_replay_bad += int(
            transcript_projection.get("replay_bad") or 0
        )
        transcript_projection_handles_missing += int(
            transcript_projection.get("handles_missing") or 0
        )
        transcript_projection_sha_mismatches += int(
            transcript_projection.get("sha_mismatches") or 0
        )
        transcript_projection_size_mismatches += int(
            transcript_projection.get("size_mismatches") or 0
        )
        categories.update(transcript_projection.get("categories") or {})
        retrieval = item.get("retrieval") or {}
        retrieve_calls += int(retrieval.get("calls") or 0)
        retrieve_results += int(retrieval.get("results") or 0)
        retrieve_truncated_results += int(retrieval.get("truncated_results") or 0)
        retrieve_continuation_suggestions += int(
            retrieval.get("continuation_suggestions") or 0
        )
        retrieve_continuation_strategies.update(
            retrieval.get("continuation_strategies") or {}
        )
        categories.update(retrieval.get("categories") or {})
        input_tokens += int(item["usage"]["input_tokens"])
        cached_tokens += int(item["usage"]["cached_tokens"])
        empty_patches += int(bool(item["patch_empty"]))
        scratch_patch_instances += int(bool(item["patch"]["scratch_paths"]))
        eval_status = str((item.get("eval") or {}).get("status") or "not_provided")
        eval_statuses[eval_status] += 1
    eval_total = sum(
        count
        for status, count in eval_statuses.items()
        if status not in {"not_provided", "not_evaluated"}
    )
    eval_resolved = int(eval_statuses.get("resolved") or 0)
    return {
        "instances": len(instances),
        "empty_patches": empty_patches,
        "scratch_patch_instances": scratch_patch_instances,
        "projection_events": projection_events,
        "projection_applied": projection_applied,
        "dispatch_truncation_events": dispatch_truncation_events,
        "dispatch_truncation_huge_events": dispatch_truncation_huge_events,
        "dispatch_truncation_handles_missing": dispatch_truncation_handles_missing,
        "dispatch_truncation_original_chars": dispatch_truncation_original_chars,
        "dispatch_truncation_returned_chars": dispatch_truncation_returned_chars,
        "transcript_projection_events": transcript_projection_events,
        "transcript_projection_replay_bad": transcript_projection_replay_bad,
        "transcript_projection_handles_missing": transcript_projection_handles_missing,
        "transcript_projection_sha_mismatches": transcript_projection_sha_mismatches,
        "transcript_projection_size_mismatches": transcript_projection_size_mismatches,
        "raw_store_records": raw_records,
        "raw_store_unique_tool_use_ids": raw_unique_tool_use_ids,
        "raw_store_duplicate_tool_use_records": raw_duplicate_tool_use_records,
        "raw_store_content_missing": raw_content_missing,
        "raw_store_hash_mismatches": raw_hash_mismatches,
        "raw_store_size_mismatches": raw_size_mismatches,
        "raw_store_integrity_bad": (
            raw_content_missing + raw_hash_mismatches + raw_size_mismatches
        ),
        "raw_store_projection_tool_use_ids_missing": raw_projection_tool_use_ids_missing,
        "raw_store_projection_handles_missing": raw_projection_handles_missing,
        "raw_store_projection_links_missing": (
            raw_projection_tool_use_ids_missing + raw_projection_handles_missing
        ),
        "retrieve_calls": retrieve_calls,
        "retrieve_results": retrieve_results,
        "retrieve_truncated_results": retrieve_truncated_results,
        "retrieve_continuation_suggestions": retrieve_continuation_suggestions,
        "retrieve_continuation_strategies": _counter_dict(
            retrieve_continuation_strategies
        ),
        "eval_total": eval_total,
        "eval_resolved": eval_resolved,
        "eval_resolved_rate": (eval_resolved / eval_total) if eval_total > 0 else None,
        "eval_statuses": _counter_dict(eval_statuses),
        "input_tokens": input_tokens,
        "cached_tokens": cached_tokens,
        "kv_cache_hit_rate": (cached_tokens / input_tokens) if input_tokens > 0 else None,
        "categories": _counter_dict(categories),
        "projection_reasons": _counter_dict(reasons),
    }


def _combined_instance_categories(item: dict[str, Any]) -> dict[str, int]:
    categories: Counter[str] = Counter()
    projection = item.get("projection") or {}
    categories.update(projection.get("categories") or {})
    dispatch_truncation = item.get("dispatch_truncation") or {}
    categories.update(dispatch_truncation.get("categories") or {})
    transcript_projection = item.get("transcript_projection") or {}
    categories.update(transcript_projection.get("categories") or {})
    retrieval = item.get("retrieval") or {}
    categories.update(retrieval.get("categories") or {})
    return _counter_dict(categories)


def _print_table(instances: list[dict[str, Any]]) -> None:
    header = (
        "instance_id",
        "state",
        "empty",
        "eval",
        "kv%",
        "proj",
        "applied",
        "trunc",
        "trunc_missing",
        "raw",
        "raw_unique",
        "raw_dupes",
        "raw_bad",
        "raw_link_missing",
        "replay_bad",
        "retrieve",
        "retrieval_results",
        "retrieval_continuations",
        "categories",
    )
    print("\t".join(header))
    for item in instances:
        usage = item["usage"]
        projection = item["projection"]
        truncation = item.get("dispatch_truncation") or {}
        transcript_projection = item.get("transcript_projection") or {}
        eval_status = str((item.get("eval") or {}).get("status") or "")
        kv = usage["kv_cache_hit_rate"]
        kv_text = "" if kv is None else f"{kv * 100:.2f}"
        categories = ",".join(
            f"{key}:{value}" for key, value in _combined_instance_categories(item).items()
        )
        raw_bad = (
            item["raw_store"]["content_missing"]
            + item["raw_store"]["hash_mismatches"]
            + item["raw_store"]["size_mismatches"]
        )
        raw_link_missing = (
            item["raw_store"]["projection_tool_use_ids_missing"]
            + item["raw_store"]["projection_handles_missing"]
        )
        print(
            "\t".join(
                [
                    str(item["instance_id"]),
                    str(item["state"] or ""),
                    "yes" if item["patch_empty"] else "no",
                    eval_status,
                    kv_text,
                    str(projection["events"]),
                    str(projection["applied"]),
                    str(truncation.get("events") or 0),
                    str(truncation.get("handles_missing") or 0),
                    str(item["raw_store"]["records"]),
                    str(item["raw_store"]["unique_tool_use_ids"]),
                    str(item["raw_store"]["duplicate_tool_use_records"]),
                    str(raw_bad),
                    str(raw_link_missing),
                    str(transcript_projection.get("replay_bad") or 0),
                    str(item["retrieval"]["calls"]),
                    str(item["retrieval"].get("results") or 0),
                    str(item["retrieval"].get("continuation_suggestions") or 0),
                    categories,
                ]
            )
        )


def _gate_violations(
    aggregate_payload: dict[str, Any],
    *,
    min_kv_cache_hit_rate: float | None = None,
    max_raw_bad: int | None = None,
    max_raw_link_missing: int | None = None,
    max_empty_patches: int | None = None,
    max_dispatch_truncation_missing: int | None = None,
    max_transcript_replay_bad: int | None = None,
    min_eval_resolved_rate: float | None = None,
    max_categories: dict[str, int] | None = None,
) -> list[str]:
    violations: list[str] = []
    kv_cache_hit_rate = aggregate_payload.get("kv_cache_hit_rate")
    if min_kv_cache_hit_rate is not None:
        if kv_cache_hit_rate is None:
            violations.append("kv_cache_hit_rate missing")
        elif float(kv_cache_hit_rate) < min_kv_cache_hit_rate:
            violations.append(
                "kv_cache_hit_rate "
                f"{float(kv_cache_hit_rate):.4f} < {min_kv_cache_hit_rate:.4f}"
            )
    checks = (
        ("raw_store_integrity_bad", max_raw_bad),
        ("raw_store_projection_links_missing", max_raw_link_missing),
        ("empty_patches", max_empty_patches),
        ("dispatch_truncation_handles_missing", max_dispatch_truncation_missing),
        ("transcript_projection_replay_bad", max_transcript_replay_bad),
    )
    for key, limit in checks:
        if limit is None:
            continue
        value = int(aggregate_payload.get(key) or 0)
        if value > limit:
            violations.append(f"{key} {value} > {limit}")
    eval_resolved_rate = aggregate_payload.get("eval_resolved_rate")
    if min_eval_resolved_rate is not None:
        if eval_resolved_rate is None:
            violations.append("eval_resolved_rate missing")
        elif float(eval_resolved_rate) < min_eval_resolved_rate:
            violations.append(
                "eval_resolved_rate "
                f"{float(eval_resolved_rate):.4f} < {min_eval_resolved_rate:.4f}"
            )
    categories = aggregate_payload.get("categories")
    category_counts = categories if isinstance(categories, dict) else {}
    for category, limit in sorted((max_categories or {}).items()):
        value = int(category_counts.get(category) or 0)
        if value > limit:
            violations.append(f"category {category} {value} > {limit}")
    return violations


def _parse_max_categories(values: list[str]) -> dict[str, int]:
    parsed: dict[str, int] = {}
    for value in values:
        category, separator, raw_limit = value.partition("=")
        category = category.strip()
        if separator != "=" or not category:
            raise argparse.ArgumentTypeError(
                f"expected CATEGORY=COUNT for --max-category, got {value!r}"
            )
        try:
            limit = int(raw_limit)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                f"expected integer COUNT for --max-category, got {value!r}"
            ) from exc
        parsed[category] = limit
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyze OpenSquilla tool-result compression artifacts."
    )
    parser.add_argument("paths", nargs="+", type=Path, help="Run or instance artifact dirs.")
    parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format.",
    )
    parser.add_argument(
        "--eval-report",
        action="append",
        default=[],
        type=Path,
        help="Optional eval summary JSON to merge by instance id.",
    )
    parser.add_argument(
        "--min-kv-cache-hit-rate",
        type=float,
        help="Fail if aggregate cached/input ratio is below this value.",
    )
    parser.add_argument(
        "--max-raw-bad",
        type=int,
        help="Fail if raw content/hash/size integrity failures exceed this value.",
    )
    parser.add_argument(
        "--max-raw-link-missing",
        type=int,
        help="Fail if projection events missing raw tool_use_id/handle links exceed this value.",
    )
    parser.add_argument(
        "--max-empty-patches",
        type=int,
        help="Fail if empty patch instances exceed this value.",
    )
    parser.add_argument(
        "--max-dispatch-truncation-missing",
        type=int,
        help="Fail if dispatch truncation handles missing exceed this value.",
    )
    parser.add_argument(
        "--max-transcript-replay-bad",
        type=int,
        help="Fail if transcript projection envelopes cannot replay from raw store.",
    )
    parser.add_argument(
        "--min-eval-resolved-rate",
        type=float,
        help="Fail if merged eval resolved/total ratio is below this value.",
    )
    parser.add_argument(
        "--max-category",
        action="append",
        default=[],
        metavar="CATEGORY=COUNT",
        help="Fail if an aggregate projection category exceeds COUNT.",
    )
    args = parser.parse_args(argv)

    instance_dirs = _instance_dirs(args.paths)
    if not instance_dirs:
        print("No SWE instance artifact directories found.", file=sys.stderr)
        return 2
    eval_reports = _load_eval_reports(args.eval_report)
    instances = _annotate_eval_status(
        [summarize_instance(path) for path in instance_dirs],
        eval_reports,
    )
    aggregate_payload = aggregate(instances)
    payload = {
        "aggregate": aggregate_payload,
        "eval_reports": [{"path": report["path"]} for report in eval_reports],
        "instances": instances,
    }
    if args.format == "table":
        _print_table(instances)
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    violations = _gate_violations(
        aggregate_payload,
        min_kv_cache_hit_rate=args.min_kv_cache_hit_rate,
        max_raw_bad=args.max_raw_bad,
        max_raw_link_missing=args.max_raw_link_missing,
        max_empty_patches=args.max_empty_patches,
        max_dispatch_truncation_missing=args.max_dispatch_truncation_missing,
        max_transcript_replay_bad=args.max_transcript_replay_bad,
        min_eval_resolved_rate=args.min_eval_resolved_rate,
        max_categories=_parse_max_categories(args.max_category),
    )
    for violation in violations:
        print(f"gate violation: {violation}", file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
