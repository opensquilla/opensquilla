"""Synthesize a decisions-*.jsonl file containing skills_invoked patterns."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path


def synth_decision_log(log_dir: Path, patterns: list[list[str]]) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    day = datetime.now(UTC).strftime("%Y%m%d")
    path = log_dir / f"decisions-{day}.jsonl"
    lines: list[str] = []
    for i, skills in enumerate(patterns):
        lines.append(json.dumps({
            "turn_id": f"synth-{i}", "session_key": "s",
            "prompt_hash": "0" * 16, "system_prompt_hash": "1" * 16,
            "tool_list_hash": "2" * 16, "tool_choice": "auto",
            "tokens_input": 1, "tokens_output": 1,
            "model": "x", "provider": "y", "latency_ms": 1,
            "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "schema_version": 10, "skills_invoked": skills,
        }))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
