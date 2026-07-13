from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True, kw_only=True)
class KnowledgeBackendError(RuntimeError):
    status_code: int | None
    code: str | None
    message: str

    def __post_init__(self) -> None:
        RuntimeError.__init__(self, self.message)


class KnowledgeBackend(Protocol):
    def status(self) -> dict[str, Any]: ...

    def collections(self) -> dict[str, Any]: ...

    def settings(self) -> dict[str, Any]: ...

    def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def prepare_sample(
        self,
        *,
        source_root: Path | str | None = None,
        limit: int = 60,
        collection_name: str | None = None,
    ) -> dict[str, Any]: ...

    def ingest_collection(
        self,
        *,
        source_root: Path | str | None = None,
        limit: int = 60,
        collection_name: str | None = None,
        collection_id: str | None = None,
        index_profiles: list[str] | None = None,
    ) -> dict[str, Any]: ...

    def search(
        self,
        query: str,
        *,
        top_k: int = 8,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def get(
        self,
        *,
        chunk_id: str | None = None,
        document_id: str | None = None,
    ) -> dict[str, Any] | None: ...

    def questions(self) -> dict[str, Any]: ...

    def record_judgment(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class DisabledKnowledgeBackend:
    def status(self) -> dict[str, Any]:
        return {"ok": False, "enabled": False, "reason": "knowledge backend is disabled"}

    def collections(self) -> dict[str, Any]:
        return {"collections": []}

    def settings(self) -> dict[str, Any]:
        raise RuntimeError("knowledge backend is disabled")

    def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("knowledge backend is disabled")

    def prepare_sample(
        self,
        *,
        source_root: Path | str | None = None,
        limit: int = 60,
        collection_name: str | None = None,
    ) -> dict[str, Any]:
        raise RuntimeError("knowledge backend is disabled")

    def ingest_collection(
        self,
        *,
        source_root: Path | str | None = None,
        limit: int = 60,
        collection_name: str | None = None,
        collection_id: str | None = None,
        index_profiles: list[str] | None = None,
    ) -> dict[str, Any]:
        raise RuntimeError("knowledge backend is disabled")

    def search(
        self,
        query: str,
        *,
        top_k: int = 8,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {"query": query, "retrieval": "disabled", "results": [], "count": 0}

    def get(
        self,
        *,
        chunk_id: str | None = None,
        document_id: str | None = None,
    ) -> dict[str, Any] | None:
        return None

    def questions(self) -> dict[str, Any]:
        return {"questions": [], "count": 0}

    def record_judgment(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"ok": False, "enabled": False, "reason": "knowledge backend is disabled"}
