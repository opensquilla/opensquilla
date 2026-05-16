"""Provider-facing reasoning control levels."""

from __future__ import annotations

from enum import StrEnum


class ThinkingLevel(StrEnum):
    OFF = "off"
    MINIMAL = "minimal"  # 1024 tokens
    LOW = "low"  # 4096 tokens
    MEDIUM = "medium"  # 10000 tokens
    HIGH = "high"  # 20000 tokens
    XHIGH = "xhigh"  # 50000 tokens
    ADAPTIVE = "adaptive"  # auto-scale based on prompt


THINKING_BUDGETS: dict[ThinkingLevel, int] = {
    ThinkingLevel.OFF: 0,
    ThinkingLevel.MINIMAL: 1024,
    ThinkingLevel.LOW: 4096,
    ThinkingLevel.MEDIUM: 10000,
    ThinkingLevel.HIGH: 20000,
    ThinkingLevel.XHIGH: 50000,
}
