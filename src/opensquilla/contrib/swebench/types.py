"""Shared data types used across modules."""

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class InstanceState(StrEnum):
    """Lifecycle state of a single SWE-bench instance."""

    PENDING = "pending"
    RUNNING = "running"
    PATCH_COLLECTED = "patch_collected"
    EVAL_DONE = "eval_done"
    FAILED = "failed"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


@dataclass
class AgentResult:
    """Structured result from a single OpenSquilla agent run."""

    success: bool
    timeout: bool
    exit_code: int
    finish_reason: str  # "stop" / "timeout" / "error" / "empty"
    stdout_path: Path | None = None
    stderr_path: Path | None = None
    session_id: str | None = None
    duration_seconds: float = 0.0
    usage: dict = field(default_factory=dict)  # token usage from agent meta


@dataclass
class InstanceRecord:
    """State record for a single instance, written to state.jsonl."""

    instance_id: str
    state: InstanceState
    model: str
    run_id: str
    started_at: str | None = None
    finished_at: str | None = None
    duration_seconds: float | None = None
    patch_empty: bool | None = None
    error: str | None = None
