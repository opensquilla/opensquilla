"""Boundary tests for agent CLI output/result helpers."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace

from opensquilla.cli import agent_cmd, agent_outputs

ROOT = Path(__file__).resolve().parents[2]
AGENT_CMD = ROOT / "src" / "opensquilla" / "cli" / "agent_cmd.py"
AGENT_OUTPUTS = ROOT / "src" / "opensquilla" / "cli" / "agent_outputs.py"

MOVED_OUTPUT_SYMBOLS = {
    "AgentRunResult",
    "_public_artifacts",
    "_usage_from_done",
    "_to_benchmark_transcript",
    "_message_event",
    "_entry_timestamp",
    "_to_transcript_usage",
    "_write_jsonl",
    "_write_json",
    "_print_no_provider_error",
}


def _module_tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _top_level_symbols(path: Path) -> set[str]:
    tree = _module_tree(path)
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _imports_from_agent_outputs(path: Path) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(_module_tree(path)):
        if isinstance(node, ast.ImportFrom) and node.module == "opensquilla.cli.agent_outputs":
            imported.update(alias.name for alias in node.names)
    return imported


def test_agent_outputs_module_owns_output_result_helpers() -> None:
    assert AGENT_OUTPUTS.exists()

    output_symbols = _top_level_symbols(AGENT_OUTPUTS)
    command_symbols = _top_level_symbols(AGENT_CMD)

    assert MOVED_OUTPUT_SYMBOLS <= output_symbols
    assert MOVED_OUTPUT_SYMBOLS.isdisjoint(command_symbols)


def test_agent_cmd_keeps_compatibility_aliases_for_moved_helpers() -> None:
    assert MOVED_OUTPUT_SYMBOLS <= _imports_from_agent_outputs(AGENT_CMD)

    for symbol in MOVED_OUTPUT_SYMBOLS:
        assert getattr(agent_cmd, symbol) is getattr(agent_outputs, symbol)


def test_agent_output_helpers_preserve_payload_shapes(tmp_path: Path) -> None:
    done = SimpleNamespace(
        input_tokens=3,
        output_tokens=5,
        reasoning_tokens=2,
        cached_tokens=1,
        cost_usd=0.25,
        billed_cost=0.5,
        model="provider/model",
        iterations=4,
    )

    usage = agent_outputs._usage_from_done(done, "fallback/model")
    assert usage == {
        "input_tokens": 3,
        "output_tokens": 5,
        "total_tokens": 8,
        "reasoning_tokens": 2,
        "cached_tokens": 1,
        "cost_usd": 0.25,
        "billed_cost": 0.5,
        "model": "provider/model",
        "request_count": 4,
    }
    assert agent_outputs._to_transcript_usage(usage) == {
        "input": 3,
        "output": 5,
        "cacheRead": 1,
        "cacheWrite": 0,
        "totalTokens": 8,
        "cost": {
            "input": 0.0,
            "output": 0.0,
            "cacheRead": 0.0,
            "cacheWrite": 0.0,
            "total": 0.25,
            "billed": 0.5,
        },
    }

    rows = [
        agent_outputs._message_event(
            "assistant",
            [{"type": "text", "text": "ok"}],
            timestamp="2026-05-19T00:00:00Z",
        )
    ]
    jsonl_path = tmp_path / "nested" / "transcript.jsonl"
    json_path = tmp_path / "nested" / "usage.json"

    agent_outputs._write_jsonl(str(jsonl_path), rows)
    agent_outputs._write_json(str(json_path), usage)

    written_rows = [
        json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()
    ]
    assert written_rows == rows
    assert json.loads(json_path.read_text(encoding="utf-8")) == usage


def test_benchmark_transcript_shape_stays_benchmark_compatible() -> None:
    entries = [
        SimpleNamespace(
            role="user",
            content="hello",
            tool_calls=None,
            created_at=1_785_000_000_000,
        ),
        SimpleNamespace(
            role="assistant",
            content="",
            created_at=1_785_000_001_000,
            tool_calls=[
                {"type": "text", "text": "checking"},
                {
                    "type": "tool_use",
                    "name": "shell",
                    "tool_use_id": "call-1",
                    "input": {"cmd": "pwd"},
                },
                {
                    "type": "tool_result",
                    "name": "shell",
                    "tool_use_id": "call-1",
                    "result": "/tmp",
                    "is_error": False,
                },
                {"type": "text", "text": "done"},
            ],
        ),
    ]
    usage = {
        "input": 3,
        "output": 5,
        "cacheRead": 1,
        "cacheWrite": 0,
        "totalTokens": 8,
        "cost": {
            "input": 0.0,
            "output": 0.0,
            "cacheRead": 0.0,
            "cacheWrite": 0.0,
            "total": 0.25,
            "billed": 0.5,
        },
    }

    assert agent_outputs._to_benchmark_transcript(entries, usage) == [
        {
            "type": "message",
            "message": {"role": "user", "content": [{"type": "text", "text": "hello"}]},
            "timestamp": "2026-07-25T17:20:00Z",
        },
        {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "checking"},
                    {
                        "type": "toolCall",
                        "name": "shell",
                        "id": "call-1",
                        "arguments": {"cmd": "pwd"},
                    },
                ],
            },
            "timestamp": "2026-07-25T17:20:01Z",
        },
        {
            "type": "message",
            "message": {
                "role": "toolResult",
                "content": [{"type": "text", "text": "/tmp"}],
                "toolCallId": "call-1",
                "toolName": "shell",
                "isError": False,
            },
            "timestamp": "2026-07-25T17:20:01Z",
        },
        {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "done"}],
                "usage": usage,
            },
            "timestamp": "2026-07-25T17:20:01Z",
        },
    ]
