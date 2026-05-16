"""Sandbox execution contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class SandboxRequest:
    argv: tuple[str, ...]
    cwd: Path | None = None
    env: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SandboxResult:
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    elapsed_ms: int = 0


class SandboxPort(Protocol):
    name: str

    async def run(self, request: SandboxRequest) -> SandboxResult: ...


__all__ = [
    "SandboxPort",
    "SandboxRequest",
    "SandboxResult",
]
