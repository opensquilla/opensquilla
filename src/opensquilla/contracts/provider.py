"""Provider port contracts."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

from .events import TurnEvent


@dataclass(frozen=True)
class ProviderMessage:
    role: str
    content: str | list[dict[str, Any]]
    name: str | None = None


@dataclass(frozen=True)
class ProviderToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    execution_timeout_seconds: float | None = None


@dataclass(frozen=True)
class ProviderChatOptions:
    model: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderModelInfo:
    id: str
    name: str = ""
    capabilities: frozenset[str] = frozenset()
    metadata: dict[str, Any] = field(default_factory=dict)


class ProviderPort(Protocol):
    """Streams a single model turn behind a stable application-facing contract."""

    provider_name: str

    def chat(
        self,
        messages: list[ProviderMessage],
        tools: list[ProviderToolDefinition] | None = None,
        options: ProviderChatOptions | None = None,
    ) -> AsyncIterator[TurnEvent]: ...

    async def list_models(self) -> list[ProviderModelInfo]: ...


class ProviderFactoryPort(Protocol):
    """Builds provider instances from adapter-owned configuration."""

    def build_provider(self, provider_id: str, config: dict[str, Any]) -> ProviderPort: ...


__all__ = [
    "ProviderChatOptions",
    "ProviderFactoryPort",
    "ProviderMessage",
    "ProviderModelInfo",
    "ProviderPort",
    "ProviderToolDefinition",
]
