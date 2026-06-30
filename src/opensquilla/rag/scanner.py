"""Safe source scanner for local document RAG."""

from __future__ import annotations

import fnmatch
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from opensquilla.gateway.config import RagConfig

from .paths import (
    DEFAULT_EXCLUDE_GLOBS,
    is_supported_text_extension,
    normalize_source_root,
    safe_relative_path,
)
from .types import RagSource


@dataclass(slots=True)
class ScanCandidate:
    path: Path
    relative_path: str
    size_bytes: int
    mtime_ns: int
    extension: str


@dataclass(slots=True)
class ScanSkip:
    relative_path: str
    reason: str
    details: dict[str, object] = field(default_factory=dict)


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def _iter_files(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file() or path.is_symlink():
            yield path


def scan_source(source: RagSource, *, config: RagConfig) -> list[ScanCandidate | ScanSkip]:
    root = normalize_source_root(source.root_path)
    if not root.exists():
        return [ScanSkip("", "source_missing", {"root": str(root)})]
    include = tuple(source.include)
    exclude = (*DEFAULT_EXCLUDE_GLOBS, *source.exclude)
    max_file_size = int(config.max_file_size_kb) * 1024
    max_source_size = int(config.max_source_size_mb) * 1024 * 1024
    results: list[ScanCandidate | ScanSkip] = []
    files_seen = 0
    total_size = 0
    root_resolved = root.resolve()
    for path in _iter_files(root):
        try:
            if path.is_symlink():
                resolved = path.resolve(strict=True)
                if not resolved.is_file():
                    results.append(ScanSkip(path.name, "symlink_not_file"))
                    continue
                try:
                    resolved.relative_to(root_resolved)
                except ValueError:
                    rel = path.relative_to(root).as_posix()
                    results.append(ScanSkip(rel, "symlink_outside_root"))
                    continue
            rel = safe_relative_path(root, path)
            if _matches(rel, exclude):
                results.append(ScanSkip(rel, "excluded"))
                continue
            extension = path.suffix.lower()
            if not is_supported_text_extension(extension):
                results.append(ScanSkip(rel, "unsupported_extension", {"extension": extension}))
                continue
            if include and not _matches(rel, include):
                results.append(ScanSkip(rel, "not_included"))
                continue
            stat = path.stat()
            if stat.st_size > max_file_size:
                results.append(ScanSkip(rel, "file_too_large", {"sizeBytes": stat.st_size}))
                continue
            files_seen += 1
            total_size += stat.st_size
            if files_seen > config.max_source_files:
                results.append(ScanSkip(rel, "source_file_limit"))
                break
            if total_size > max_source_size:
                results.append(ScanSkip(rel, "source_size_limit", {"sizeBytes": total_size}))
                break
            results.append(
                ScanCandidate(
                    path=path,
                    relative_path=rel,
                    size_bytes=stat.st_size,
                    mtime_ns=stat.st_mtime_ns,
                    extension=extension,
                )
            )
        except FileNotFoundError:
            results.append(ScanSkip(path.name, "file_disappeared"))
        except Exception as exc:  # noqa: BLE001
            results.append(ScanSkip(path.name, "scan_error", {"error": str(exc)}))
    return results
