"""Human approval contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


@dataclass(frozen=True)
class ApprovalRequest:
    namespace: str
    action: str
    parameters: dict[str, Any] = field(default_factory=dict)
    session_key: str | None = None


@dataclass(frozen=True)
class ApprovalDecision:
    request_id: str
    status: ApprovalStatus
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class ApprovalPort(Protocol):
    async def request(self, request: ApprovalRequest) -> str: ...

    async def wait(self, request_id: str, timeout: float | None = None) -> ApprovalDecision: ...


__all__ = [
    "ApprovalDecision",
    "ApprovalPort",
    "ApprovalRequest",
    "ApprovalStatus",
]
