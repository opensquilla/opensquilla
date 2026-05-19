"""Output helpers for the agent CLI command."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.panel import Panel
from rich.text import Text

from opensquilla.cli.ui import console


@dataclass
class AgentRunResult:
    status: str
    agent_id: str
    session_key: str
    text: str
    usage: dict[str, Any]
    errors: list[dict[str, str]]
    workspace: str | None = None
    workspace_strict: bool = False
    thinking: str | None = None
    transcript_path: str | None = None
    usage_path: str | None = None
    artifacts: list[dict[str, Any]] | None = None


def _public_artifacts(artifacts: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    from opensquilla.artifacts import artifact_payload

    return [artifact_payload(artifact) for artifact in artifacts or []]


def _usage_from_done(done: Any | None, model: str | None) -> dict[str, Any]:
    return {
        "input_tokens": done.input_tokens if done else 0,
        "output_tokens": done.output_tokens if done else 0,
        "total_tokens": (done.input_tokens + done.output_tokens) if done else 0,
        "reasoning_tokens": done.reasoning_tokens if done else 0,
        "cached_tokens": done.cached_tokens if done else 0,
        "cost_usd": done.cost_usd if done else 0.0,
        "billed_cost": done.billed_cost if done else 0.0,
        "model": (done.model or model or "") if done else (model or ""),
        "request_count": done.iterations if done else 0,
    }


def _to_benchmark_transcript(
    entries: list[Any], usage: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Convert OpenSquilla transcript rows into benchmark-friendly JSONL events."""
    output: list[dict[str, Any]] = []
    for entry in entries:
        role = getattr(entry, "role", "")
        content = getattr(entry, "content", "") or ""
        tool_calls = getattr(entry, "tool_calls", None) or []
        timestamp = _entry_timestamp(entry)
        if role == "assistant" and tool_calls:
            assistant_blocks: list[dict[str, Any]] = []
            for segment in tool_calls:
                segment_type = segment.get("type")
                if segment_type == "text":
                    text = segment.get("text", "")
                    if text:
                        assistant_blocks.append({"type": "text", "text": text})
                elif segment_type == "tool_use":
                    assistant_blocks.append(
                        {
                            "type": "toolCall",
                            "name": segment.get("name", ""),
                            "id": segment.get("tool_use_id", ""),
                            "arguments": segment.get("input") or {},
                        }
                    )
                elif segment_type == "tool_result":
                    if assistant_blocks:
                        output.append(
                            _message_event("assistant", assistant_blocks, timestamp=timestamp)
                        )
                        assistant_blocks = []
                    output.append(
                        _message_event(
                            "toolResult",
                            [{"type": "text", "text": str(segment.get("result", ""))}],
                            timestamp=timestamp,
                            tool_call_id=segment.get("tool_use_id", ""),
                            tool_name=segment.get("name", ""),
                            is_error=bool(segment.get("is_error", False)),
                        )
                    )
            if assistant_blocks:
                output.append(_message_event("assistant", assistant_blocks, timestamp=timestamp))
            continue

        output.append(
            _message_event(
                role,
                [{"type": "text", "text": content}] if content else [],
                timestamp=timestamp,
            )
        )
    if usage is not None:
        for event in reversed(output):
            message = event.get("message", {})
            if message.get("role") == "assistant":
                message["usage"] = usage
                break
    return output


def _message_event(
    role: str,
    content: list[dict[str, Any]],
    *,
    timestamp: str | None = None,
    tool_call_id: str | None = None,
    tool_name: str | None = None,
    is_error: bool | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {"type": "message", "message": {"role": role, "content": content}}
    message = event["message"]
    if tool_call_id is not None:
        message["toolCallId"] = tool_call_id
    if tool_name is not None:
        message["toolName"] = tool_name
    if is_error is not None:
        message["isError"] = is_error
    if timestamp:
        event["timestamp"] = timestamp
    return event


def _entry_timestamp(entry: Any) -> str | None:
    value = getattr(entry, "created_at", None)
    if not isinstance(value, int | float):
        return None
    return datetime.fromtimestamp(value / 1000, UTC).isoformat().replace("+00:00", "Z")


def _to_transcript_usage(usage: dict[str, Any]) -> dict[str, Any]:
    return {
        "input": usage["input_tokens"],
        "output": usage["output_tokens"],
        "cacheRead": usage["cached_tokens"],
        "cacheWrite": 0,
        "totalTokens": usage["total_tokens"],
        "cost": {
            "input": 0.0,
            "output": 0.0,
            "cacheRead": 0.0,
            "cacheWrite": 0.0,
            "total": usage["cost_usd"],
            "billed": usage["billed_cost"],
        },
    }


def _write_jsonl(path: str, rows: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_json(path: str, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")


def _print_no_provider_error() -> None:
    """Print a three-section diagnostic panel when no LLM provider is configured."""
    body = Text.assemble(
        ("Symptom\n", "bold red"),
        "No LLM provider configured.\n\n",
        ("Cause\n", "bold yellow"),
        (
            "No API key was found. The following environment variables were all empty:\n"
            "  OPENROUTER_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY,\n"
            "  DEEPSEEK_API_KEY, GEMINI_API_KEY, DASHSCOPE_API_KEY, and others.\n"
            "The config file ~/.opensquilla/config.toml also has no [llm].api_key set.\n\n"
        ),
        ("Next steps\n", "bold green"),
        (
            "Option 1 (recommended) — run the interactive setup wizard:\n"
            "  opensquilla onboard\n\n"
            "Option 2 — set an environment variable for your provider:\n"
            "  export OPENROUTER_API_KEY=sk-or-...        # POSIX / macOS / Linux\n"
            "  setx OPENROUTER_API_KEY \"sk-or-...\"  "
            "# Windows cmd: set OPENROUTER_API_KEY=...\n\n"
            "Option 3 — edit ~/.opensquilla/config.toml and add:\n"
            "  [llm]\n"
            "  api_key = \"your-key-here\"\n"
        ),
    )
    console.print(Panel(body, title="No Provider Configured", border_style="red"))
