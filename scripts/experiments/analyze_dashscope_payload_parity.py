#!/usr/bin/env python3
"""Check Qwen/DashScope provider payload parity invariants from raw traces."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

DASHSCOPE_CACHE_MARKER_LIMIT = 4


def _iter_json_values(path: Path) -> Iterator[Any]:
    if path.is_dir():
        for child in sorted(path.rglob("*")):
            if child.is_file() and child.suffix.lower() in {".json", ".jsonl"}:
                yield from _iter_json_values(child)
        return
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return
    if path.suffix.lower() == ".jsonl":
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            yield {"__source_path": str(path), "__value": value}
        return
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return
    yield {"__source_path": str(path), "__value": value}


def _walk_dicts(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _payloads_from_value(source_path: str, value: Any) -> Iterator[dict[str, Any]]:
    seen_payload_ids: set[int] = set()
    for obj in _walk_dicts(value):
        payload = obj.get("payload")
        if isinstance(payload, dict) and payload.get("model") and isinstance(
            payload.get("messages"),
            list,
        ):
            seen_payload_ids.add(id(payload))
            yield {
                "source_path": source_path,
                "instance_id": _instance_id_from_path(source_path),
                "payload": payload,
            }
        elif (
            id(obj) not in seen_payload_ids
            and obj.get("model")
            and isinstance(obj.get("messages"), list)
        ):
            yield {
                "source_path": source_path,
                "instance_id": _instance_id_from_path(source_path),
                "payload": obj,
            }


def _instance_id_from_path(source_path: str) -> str:
    path = Path(source_path)
    if path.name in {"llm_calls.jsonl", "provider_trace.jsonl", "request_proof.jsonl"}:
        return path.parent.name
    if path.parent.name:
        return path.parent.name
    return ""


def _extra_body(payload: dict[str, Any]) -> dict[str, Any]:
    extra = payload.get("extra_body")
    return extra if isinstance(extra, dict) else {}


def _thinking_enabled(payload: dict[str, Any]) -> bool:
    extra = _extra_body(payload)
    return bool(
        extra.get("enable_thinking")
        or payload.get("enable_thinking")
        or payload.get("thinking")
        or payload.get("reasoning")
    )


def _message_reasoning_replayed(payload: dict[str, Any]) -> bool:
    for message in payload.get("messages") or []:
        if isinstance(message, dict) and message.get("role") == "assistant":
            reasoning = message.get("reasoning_content")
            if isinstance(reasoning, str) and reasoning.strip():
                return True
    return False


def _tool_call_pairing_ok(payload: dict[str, Any]) -> tuple[bool, str]:
    pending: list[str] = []
    for message in payload.get("messages") or []:
        if not isinstance(message, dict):
            continue
        if message.get("role") == "assistant":
            for call in message.get("tool_calls") or []:
                if isinstance(call, dict) and call.get("id"):
                    pending.append(str(call["id"]))
        elif message.get("role") == "tool":
            tool_call_id = message.get("tool_call_id")
            if tool_call_id in pending:
                pending.remove(tool_call_id)
    if pending:
        return False, f"unpaired assistant tool_call ids: {','.join(pending[:5])}"
    return True, "assistant tool calls and tool results are paired"


_BOOLEAN_SCHEMA_KEYWORD_ALLOWLIST = {
    "additionalProperties",
    "deprecated",
    "nullable",
    "strict",
    "uniqueItems",
}


def _boolean_schema_paths(value: Any, prefix: str = "$", *, key: str | None = None) -> list[str]:
    if isinstance(value, bool):
        if key in _BOOLEAN_SCHEMA_KEYWORD_ALLOWLIST:
            return []
        return [prefix]
    if isinstance(value, dict):
        paths: list[str] = []
        for key, child in value.items():
            paths.extend(_boolean_schema_paths(child, f"{prefix}.{key}", key=key))
        return paths
    if isinstance(value, list):
        paths: list[str] = []
        for index, child in enumerate(value):
            paths.extend(_boolean_schema_paths(child, f"{prefix}[{index}]"))
        return paths
    return []


def _cache_marker_count(payload: dict[str, Any]) -> int:
    count = 0
    for obj in _walk_dicts(payload.get("messages") or []):
        if "cache_control" in obj:
            count += 1
    return count


def _row(
    *,
    source_path: str,
    instance_id: str,
    model: str,
    check: str,
    status: str,
    detail: str,
) -> dict[str, str]:
    return {
        "source_path": source_path,
        "instance_id": instance_id,
        "model": model,
        "check": check,
        "status": status,
        "detail": detail,
    }


def _check_payload(
    source_path: str,
    instance_id: str,
    payload: dict[str, Any],
) -> list[dict[str, str]]:
    model = str(payload.get("model") or "")
    model_lower = model.lower()
    qwen_flash = "qwen3.6-flash" in model_lower
    thinking = _thinking_enabled(payload)
    extra = _extra_body(payload)
    rows: list[dict[str, str]] = []

    def add(check: str, status: str, detail: str) -> None:
        rows.append(
            _row(
                source_path=source_path,
                instance_id=instance_id,
                model=model,
                check=check,
                status=status,
                detail=detail,
            )
        )

    if thinking:
        add(
            "dashscope_enable_thinking",
            "pass"
            if extra.get("enable_thinking") is True or payload.get("enable_thinking") is True
            else "fail",
            "enable_thinking is true"
            if extra.get("enable_thinking") is True or payload.get("enable_thinking") is True
            else "thinking appears enabled but enable_thinking is not true",
        )
        add(
            "dashscope_max_completion_tokens",
            "pass" if "max_completion_tokens" in payload else "fail",
            "max_completion_tokens present"
            if "max_completion_tokens" in payload
            else "DashScope reasoning payload should use max_completion_tokens",
        )
        forced_tool_choice = payload.get("tool_choice")
        forced_tool_choice_allowed = forced_tool_choice is None or forced_tool_choice == "auto"
        add(
            "dashscope_thinking_no_forced_tool_choice",
            "pass" if forced_tool_choice_allowed else "fail",
            "no forced tool_choice during thinking"
            if forced_tool_choice_allowed
            else "forced tool_choice present during thinking",
        )
    else:
        add("dashscope_enable_thinking", "skip", "thinking not detected")
        add("dashscope_max_completion_tokens", "skip", "thinking not detected")
        add("dashscope_thinking_no_forced_tool_choice", "skip", "thinking not detected")

    if qwen_flash:
        add(
            "qwen_flash_no_reasoning_replay",
            "fail" if _message_reasoning_replayed(payload) else "pass",
            "historical assistant reasoning_content replayed"
            if _message_reasoning_replayed(payload)
            else "no historical reasoning_content replay",
        )
        preserve_thinking = bool(extra.get("preserve_thinking") or payload.get("preserve_thinking"))
        add(
            "qwen_flash_no_preserve_thinking",
            "fail" if preserve_thinking else "pass",
            "preserve_thinking present for qwen3.6-flash"
            if preserve_thinking
            else "preserve_thinking absent for qwen3.6-flash",
        )
    else:
        add("qwen_flash_no_reasoning_replay", "skip", "not qwen3.6-flash")
        add("qwen_flash_no_preserve_thinking", "skip", "not qwen3.6-flash")

    stream_options = payload.get("stream_options")
    if payload.get("stream") is False:
        add("stream_include_usage", "skip", "non-stream request")
    else:
        include_usage = (
            isinstance(stream_options, dict) and stream_options.get("include_usage") is True
        )
        add(
            "stream_include_usage",
            "pass" if include_usage else "fail",
            "stream_options.include_usage is true"
            if include_usage
            else "stream_options.include_usage is missing or false",
        )

    marker_count = _cache_marker_count(payload)
    if marker_count == 0:
        add("cache_marker_limit", "warn", "no cache markers found")
    else:
        add(
            "cache_marker_limit",
            "pass" if marker_count <= DASHSCOPE_CACHE_MARKER_LIMIT else "fail",
            f"cache markers={marker_count}, limit={DASHSCOPE_CACHE_MARKER_LIMIT}",
        )

    paired, detail = _tool_call_pairing_ok(payload)
    add("tool_call_pairing", "pass" if paired else "fail", detail)

    boolean_paths = _boolean_schema_paths(payload.get("tools") or [])
    add(
        "tool_schema_no_boolean_values",
        "pass" if not boolean_paths else "fail",
        "no boolean schema values"
        if not boolean_paths
        else "boolean schema values at " + ",".join(boolean_paths[:5]),
    )
    return rows


def analyze_paths(paths: Iterable[Path]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    rows: list[dict[str, str]] = []
    checked_payloads = 0
    for path in paths:
        for wrapped in _iter_json_values(path):
            source_path = str(wrapped.get("__source_path") or path)
            for item in _payloads_from_value(source_path, wrapped.get("__value")):
                checked_payloads += 1
                rows.extend(
                    _check_payload(
                        item["source_path"],
                        item["instance_id"],
                        item["payload"],
                    )
                )
    failures = Counter(row["check"] for row in rows if row["status"] == "fail")
    warnings = Counter(row["check"] for row in rows if row["status"] == "warn")
    summary = {
        "checked_payloads": checked_payloads,
        "rows": len(rows),
        "failed_checks": sum(failures.values()),
        "warning_checks": sum(warnings.values()),
        "failed_checks_by_name": dict(sorted(failures.items())),
        "warnings_by_name": dict(sorted(warnings.items())),
    }
    return summary, rows


def write_outputs(
    summary: dict[str, Any],
    rows: list[dict[str, str]],
    *,
    json_path: Path,
    csv_path: Path,
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    fields = ["source_path", "instance_id", "model", "check", "status", "detail"]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--json-output", type=Path, default=Path("qwen_payload_parity.json"))
    parser.add_argument("--csv-output", type=Path, default=Path("qwen_payload_parity.csv"))
    args = parser.parse_args()
    summary, rows = analyze_paths(args.paths)
    write_outputs(summary, rows, json_path=args.json_output, csv_path=args.csv_output)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 1 if summary["failed_checks"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
