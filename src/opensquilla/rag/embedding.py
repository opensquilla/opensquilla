"""Embedding resolution for local document RAG."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from opensquilla.gateway.config import GatewayConfig
from opensquilla.memory.embedding import EmbeddingProvider
from opensquilla.memory.embedding_resolver import (
    create_embedding_provider,
    local_bge_available,
    resolve_memory_embedding,
)


@dataclass(frozen=True, slots=True)
class RagEmbeddingDecision:
    requested_provider: str
    effective_provider: str
    model: str
    fingerprint: str
    reason: str | None
    dimensions: int | None
    base_url: str | None
    enabled: bool


class _RagMemoryConfigAdapter:
    def __init__(self, rag_config: Any) -> None:
        self.retrieval_mode = "fts_only" if rag_config.retrieval_mode == "fts" else "hybrid"
        self.embedding = rag_config.embedding


def resolve_rag_embedding(
    config: GatewayConfig,
    *,
    local_available: Callable[[str, str | None], bool] | None = None,
) -> RagEmbeddingDecision:
    decision = resolve_memory_embedding(
        _RagMemoryConfigAdapter(config.rag),
        local_available=local_available or local_bge_available,
    )
    return RagEmbeddingDecision(
        requested_provider=decision.requested_provider,
        effective_provider=decision.effective_provider,
        model=decision.model,
        fingerprint=decision.fingerprint,
        reason=decision.reason,
        dimensions=decision.dimensions,
        base_url=decision.remote_base_url or decision.ollama_base_url,
        enabled=decision.effective_provider != "none",
    )


def create_rag_embedding_provider(config: GatewayConfig) -> EmbeddingProvider | None:
    memory_decision = resolve_memory_embedding(_RagMemoryConfigAdapter(config.rag))
    if memory_decision.effective_provider == "none":
        return None
    return create_embedding_provider(memory_decision)
