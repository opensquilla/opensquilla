"""Local document RAG package."""

from __future__ import annotations

__all__ = [
    "RagError",
    "RagManager",
    "RagStore",
]

try:
    from .errors import RagError
    from .manager import RagManager
    from .store import RagStore
except Exception:  # pragma: no cover - keep package import light during partial boot
    pass
