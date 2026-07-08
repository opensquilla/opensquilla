from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path


def _load_script():
    path = Path(__file__).parents[2] / "scripts" / "experiments" / (
        "analyze_dashscope_payload_parity.py"
    )
    spec = importlib.util.spec_from_file_location("analyze_dashscope_payload_parity", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_qwen_payload_parity_reports_hard_failures(tmp_path: Path) -> None:
    mod = _load_script()
    trace = tmp_path / "artifacts" / "case-1" / "llm_calls.jsonl"
    trace.parent.mkdir(parents=True)
    payload = {
        "model": "qwen3.6-flash",
        "extra_body": {"enable_thinking": True, "preserve_thinking": True},
        "max_tokens": 2048,
        "stream": True,
        "tool_choice": {
            "type": "function",
            "function": {"name": "read_source"},
        },
        "stream_options": {"include_usage": False},
        "messages": [
            {
                "role": "assistant",
                "reasoning_content": "historical reasoning should not replay",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "read_source", "arguments": "{}"},
                    }
                ],
            }
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "read_source",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": False},
                    },
                },
            }
        ],
    }
    trace.write_text(
        json.dumps({"event": "llm.request", "call_index": 1, "payload": payload}) + "\n",
        encoding="utf-8",
    )

    summary, rows = mod.analyze_paths([tmp_path / "artifacts"])
    json_path = tmp_path / "summary.json"
    csv_path = tmp_path / "rows.csv"
    mod.write_outputs(summary, rows, json_path=json_path, csv_path=csv_path)

    assert summary["checked_payloads"] == 1
    assert summary["failed_checks"] >= 6
    failed = {row["check"] for row in rows if row["status"] == "fail"}
    assert {
        "dashscope_max_completion_tokens",
        "qwen_flash_no_reasoning_replay",
        "qwen_flash_no_preserve_thinking",
        "dashscope_thinking_no_forced_tool_choice",
        "stream_include_usage",
        "tool_schema_no_boolean_values",
        "tool_call_pairing",
    } <= failed
    csv_rows = list(csv.DictReader(csv_path.open()))
    assert csv_rows[0]["instance_id"] == "case-1"
    assert json.loads(json_path.read_text())["failed_checks_by_name"]["stream_include_usage"] == 1


def test_qwen_payload_parity_accepts_live_dashscope_request_shape(tmp_path: Path) -> None:
    mod = _load_script()
    trace = tmp_path / "artifacts" / "case-2" / "llm_calls.jsonl"
    trace.parent.mkdir(parents=True)
    payload = {
        "model": "qwen3.6-flash",
        "enable_thinking": True,
        "max_completion_tokens": 32768,
        "stream_options": {"include_usage": True},
        "messages": [
            {"role": "system", "content": "tools available"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "read_source", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": "ok"},
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "read_source",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                        "additionalProperties": False,
                    },
                },
            }
        ],
    }
    trace.write_text(
        json.dumps({"event": "llm.request", "call_index": 1, "payload": payload}) + "\n",
        encoding="utf-8",
    )

    summary, rows = mod.analyze_paths([tmp_path / "artifacts"])

    assert summary["checked_payloads"] == 1
    assert summary["failed_checks"] == 0
    checks = {row["check"]: row for row in rows}
    assert checks["dashscope_enable_thinking"]["status"] == "pass"
    assert checks["tool_schema_no_boolean_values"]["status"] == "pass"


def test_qwen_payload_parity_skips_stream_usage_check_for_non_stream_fallback(
    tmp_path: Path,
) -> None:
    mod = _load_script()
    trace = tmp_path / "artifacts" / "case-3" / "llm_calls.jsonl"
    trace.parent.mkdir(parents=True)
    payload = {
        "model": "qwen3.6-flash",
        "enable_thinking": True,
        "max_completion_tokens": 32768,
        "stream": False,
        "messages": [{"role": "user", "content": "fix this"}],
        "tools": [],
    }
    trace.write_text(
        json.dumps({"event": "llm.request", "call_index": 1, "payload": payload}) + "\n",
        encoding="utf-8",
    )

    summary, rows = mod.analyze_paths([tmp_path / "artifacts"])

    assert summary["checked_payloads"] == 1
    assert summary["failed_checks"] == 0
    checks = {row["check"]: row for row in rows}
    assert checks["stream_include_usage"]["status"] == "skip"
