"""Memory source path rules shared by tools and gateway RPCs."""

from __future__ import annotations

from pathlib import Path


def is_memory_archive_path(path: str) -> bool:
    rel = Path(path)
    return (
        not rel.is_absolute()
        and not any(part in {"", ".", ".."} for part in rel.parts)
        and rel.parts[:2] == ("memory", "archive")
    )


def is_memory_source_path(path: str, *, allow_archive: bool = False) -> bool:
    """Return True for OpenSquilla memory source files."""
    rel = Path(path)
    if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
        return False
    if rel.parts == ("MEMORY.md",):
        return True
    if rel.parts[:2] == ("memory", "archive") and not allow_archive:
        return False
    return (
        len(rel.parts) >= 2
        and rel.parts[0] == "memory"
        and rel.suffix == ".md"
        and not any(part.startswith(".") for part in rel.parts[1:])
    )


def is_raw_fallback_save_path(path: str) -> bool:
    """Return True for paths under the ``memory/.raw_fallbacks/`` sidecar.

    Raw-dump fallback files (written by ``SessionFlushService._raw_dump_fallback``
    when both LLM flush and the curated path fail) live under a dot-prefix
    sidecar so the memory sync_manager scanner skips them, but the writer
    itself still goes through ``memory_save`` for unified file-write
    semantics. This predicate carves a narrow exception in the source-path
    gate for that single sidecar; nothing else dot-prefixed is writable.
    """
    rel = Path(path)
    return (
        not rel.is_absolute()
        and not any(part in {"", ".", ".."} for part in rel.parts)
        and len(rel.parts) >= 3
        and rel.parts[:2] == ("memory", ".raw_fallbacks")
        and rel.suffix == ".md"
    )


def is_memory_save_path(path: str) -> bool:
    """Return True for writable memory files.

    Save targets must be readable/searchable memory sources OR the raw-dump
    fallback sidecar (``memory/.raw_fallbacks/``). Bootstrap profile files
    such as USER.md and AGENTS.md are edited through agent-file or
    filesystem surfaces, not memory_save.
    """
    return is_memory_source_path(path) or is_raw_fallback_save_path(path)


def private_archive_error() -> str:
    return (
        "Error: memory archive is private turn-capture storage. Use durable memory "
        "sources returned by memory_search. Enable index_captured_turns only when "
        "raw captured turns are intentionally part of the product contract."
    )
