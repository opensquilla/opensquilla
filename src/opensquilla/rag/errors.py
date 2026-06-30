"""RAG-specific errors and stable error codes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class RagError(Exception):
    """Base class for local document RAG errors."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})
        self.retryable = retryable

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "retryable": self.retryable,
        }


class RagDisabledError(RagError):
    def __init__(self) -> None:
        super().__init__("rag_disabled", "Local document RAG is disabled")


class RagValidationError(RagError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__("invalid_request", message, details=details)


class RagNotFoundError(RagError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__("not_found", message, details=details)


class RagConflictError(RagError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__("conflict", message, details=details)


class RagStorageError(RagError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__("storage_error", message, details=details, retryable=True)


class RagEmbeddingError(RagError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(code, message, details=details, retryable=True)
