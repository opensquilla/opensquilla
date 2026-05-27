from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

CheckpointRole = Literal[
    "user",
    "assistant",
    "tool_call",
    "tool_result",
    "system_notice",
    "error",
]
CheckpointContentType = Literal["text", "json", "binary_ref", "redacted"]
CheckpointStatus = Literal["ok", "error", "truncated", "redacted"]


@dataclass(frozen=True)
class CheckpointEvent:
    schema_version: int
    event_id: str
    session_key: str
    session_id: str
    turn_id: str
    sequence: int
    timestamp_ms: int
    role: CheckpointRole
    content_type: CheckpointContentType
    content: str
    summary: str | None
    tool_name: str | None
    tool_call_id: str | None
    status: CheckpointStatus
    token_estimate: int
    source: str
    attachments: list[dict]
    content_hash: str

    def to_json_dict(self) -> dict:
        payload = asdict(self)
        if not payload["content_hash"]:
            payload["content_hash"] = checkpoint_event_hash(self.content)
        return payload


def checkpoint_event_hash(content: str) -> str:
    normalized = str(content or "").strip().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def _safe_path_component(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    if safe in {"", ".", ".."}:
        return "unknown"
    return safe


def checkpoint_relative_path(*, session_key: str, turn_id: str) -> Path:
    return (
        Path("memory")
        / ".checkpoints"
        / _safe_path_component(session_key)
        / f"{_safe_path_component(turn_id)}.jsonl"
    )


def serialize_checkpoint_event(event: CheckpointEvent) -> str:
    return json.dumps(event.to_json_dict(), ensure_ascii=False, sort_keys=True)
