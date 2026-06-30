"""Collection/source registry rules for local document RAG."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from pathlib import Path

from .errors import RagConflictError
from .paths import normalize_globs, normalize_source_root, validate_identifier
from .store import RagStore
from .types import RagCollection, RagSource, RagSourceMode, RagSourceStatus


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-._")
    return cleaned[:48] or "source"


def source_id_for(collection_id: str, root_path: str, name: str | None = None) -> str:
    digest = hashlib.sha256(f"{collection_id}\0{root_path}".encode()).hexdigest()[:8]
    return f"src_{_slug(name or Path(root_path).name or 'source')}_{digest}"


class SourceRegistry:
    def __init__(self, store: RagStore) -> None:
        self.store = store

    async def ensure_collection(self, collection_id: str = "default") -> RagCollection:
        validate_identifier(collection_id, field="collection_id")
        if collection_id == "default":
            return await self.store.ensure_default_collection()
        existing = await self.store.get_collection(collection_id)
        if existing:
            return existing
        collection = RagCollection(collection_id=collection_id, name=collection_id)
        return await self.store.upsert_collection(collection)

    async def add_source(
        self,
        *,
        path: str,
        collection_id: str = "default",
        source_id: str | None = None,
        name: str | None = None,
        include: Sequence[str] = (),
        exclude: Sequence[str] = (),
        enabled: bool = True,
        mode: RagSourceMode = RagSourceMode.REFERENCE,
    ) -> tuple[RagSource, bool]:
        collection_id = validate_identifier(collection_id, field="collection_id")
        await self.ensure_collection(collection_id)
        root = normalize_source_root(path)
        root_path = str(root)
        display_name = (name or root.name or root_path).strip()
        include_tuple = normalize_globs(include)
        exclude_tuple = normalize_globs(exclude)
        existing = await self.store.find_source_by_root(collection_id, root_path)
        if existing is not None:
            if source_id and source_id != existing.source_id:
                raise RagConflictError(
                    "A RAG source already exists for this collection and path",
                    details={
                        "existingSourceId": existing.source_id,
                        "requestedSourceId": source_id,
                        "path": root_path,
                    },
                )
            updated = RagSource(
                source_id=existing.source_id,
                collection_id=collection_id,
                mode=existing.mode,
                root_path=root_path,
                display_name=display_name or existing.display_name,
                include=include_tuple or existing.include,
                exclude=exclude_tuple or existing.exclude,
                enabled=enabled,
                status=RagSourceStatus.MISSING if not root.exists() else RagSourceStatus.STALE,
                stale_reason="source_updated",
                created_at=existing.created_at,
            )
            return await self.store.upsert_source(updated), False

        resolved_source_id = validate_identifier(
            source_id or source_id_for(collection_id, root_path, display_name),
            field="source_id",
        )
        source = RagSource(
            source_id=resolved_source_id,
            collection_id=collection_id,
            mode=mode,
            root_path=root_path,
            display_name=display_name,
            include=include_tuple,
            exclude=exclude_tuple,
            enabled=enabled,
            status=RagSourceStatus.MISSING if not root.exists() else RagSourceStatus.STALE,
            stale_reason="source_added",
        )
        return await self.store.upsert_source(source), True

    async def disable_source(self, source_id: str) -> RagSource | None:
        source = await self.store.get_source(validate_identifier(source_id, field="source_id"))
        if source is None:
            return None
        disabled = RagSource(
            source_id=source.source_id,
            collection_id=source.collection_id,
            mode=source.mode,
            root_path=source.root_path,
            display_name=source.display_name,
            include=source.include,
            exclude=source.exclude,
            enabled=False,
            status=RagSourceStatus.DISABLED,
            created_at=source.created_at,
        )
        return await self.store.upsert_source(disabled)

    async def enable_source(self, source_id: str) -> RagSource | None:
        source = await self.store.get_source(validate_identifier(source_id, field="source_id"))
        if source is None:
            return None
        root = Path(source.root_path)
        enabled = RagSource(
            source_id=source.source_id,
            collection_id=source.collection_id,
            mode=source.mode,
            root_path=source.root_path,
            display_name=source.display_name,
            include=source.include,
            exclude=source.exclude,
            enabled=True,
            status=RagSourceStatus.MISSING if not root.exists() else RagSourceStatus.STALE,
            stale_reason="source_enabled",
            created_at=source.created_at,
        )
        return await self.store.upsert_source(enabled)
