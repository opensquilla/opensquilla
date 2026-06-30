"""Persistent zip import helpers for local document RAG."""

from __future__ import annotations

import fnmatch
import io
import re
import shutil
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from opensquilla.gateway.config import RagConfig

from .errors import RagValidationError
from .paths import DEFAULT_EXCLUDE_GLOBS, is_hidden_relative_path, is_supported_text_extension

_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:/")
_SOURCE_SLUG_RE = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(slots=True)
class _ImportCandidate:
    info: zipfile.ZipInfo
    relative_path: str


def safe_archive_name(archive_name: str | None) -> str:
    cleaned = (archive_name or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    return cleaned or "source.zip"


def imported_source_id(name: str | None, archive_name: str, unique: str) -> str:
    base = (name or Path(safe_archive_name(archive_name)).stem or "upload").strip()
    slug = _SOURCE_SLUG_RE.sub("-", base).strip("-._")[:48] or "upload"
    suffix = _SOURCE_SLUG_RE.sub("", unique)[:12] or "import"
    return f"src_import_{slug}_{suffix}"


def import_zip_bytes(
    *,
    archive_name: str,
    payload: bytes,
    target_dir: Path,
    config: RagConfig,
) -> dict[str, Any]:
    """Validate and extract supported zip members into ``target_dir``.

    The function never calls ``ZipFile.extract``. It normalizes every member
    path first, rejects archive escape attempts, and then writes only supported
    text-like files into a caller-owned directory.
    """

    archive_file_name = safe_archive_name(archive_name)
    if not isinstance(payload, bytes) or not payload:
        raise RagValidationError("RAG zip upload is empty")

    max_source_bytes = int(config.max_source_size_mb) * 1024 * 1024
    max_file_bytes = int(config.max_file_size_kb) * 1024
    if len(payload) > max_source_bytes:
        raise RagValidationError(
            "RAG zip archive is too large",
            details={"sizeBytes": len(payload), "maxBytes": max_source_bytes},
        )
    if not zipfile.is_zipfile(io.BytesIO(payload)):
        raise RagValidationError("RAG upload must be a valid zip archive")

    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise RagValidationError("RAG upload must be a valid zip archive") from exc

    with archive:
        candidates: list[_ImportCandidate] = []
        skipped: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        files_seen = 0
        declared_total_bytes = 0
        imported_total_bytes = 0

        for info in archive.infolist():
            if info.is_dir():
                _normalize_zip_member_path(info.filename)
                continue
            files_seen += 1
            declared_total_bytes += int(info.file_size)
            if declared_total_bytes > max_source_bytes:
                raise RagValidationError(
                    "RAG zip archive is too large",
                    details={
                        "archiveName": archive_file_name,
                        "sizeBytes": declared_total_bytes,
                        "maxBytes": max_source_bytes,
                    },
                )
            _reject_special_zip_member(info)
            relative_path = _normalize_zip_member_path(info.filename)
            if relative_path in seen_paths:
                raise RagValidationError(
                    "RAG zip archive contains duplicate normalized paths",
                    details={"path": relative_path},
                )
            seen_paths.add(relative_path)

            skip_reason = _skip_reason(relative_path)
            if skip_reason is not None:
                skipped.append({"path": relative_path, "reason": skip_reason})
                continue

            if info.file_size > max_file_bytes:
                raise RagValidationError(
                    "RAG zip member is too large",
                    details={
                        "path": relative_path,
                        "sizeBytes": info.file_size,
                        "maxBytes": max_file_bytes,
                    },
                )
            candidates.append(_ImportCandidate(info=info, relative_path=relative_path))
            imported_total_bytes += int(info.file_size)
            if len(candidates) > config.max_source_files:
                raise RagValidationError(
                    "RAG zip archive has too many supported files",
                    details={"maxFiles": config.max_source_files},
                )
            if imported_total_bytes > max_source_bytes:
                raise RagValidationError(
                    "RAG zip archive is too large",
                    details={"sizeBytes": imported_total_bytes, "maxBytes": max_source_bytes},
                )

        if not candidates:
            raise RagValidationError(
                "RAG zip archive contains no supported files",
                details={"archiveName": archive_file_name, "filesSeen": files_seen},
            )

        target = Path(target_dir)
        if target.exists() and any(target.iterdir()):
            raise RagValidationError(
                "RAG import target directory must be empty",
                details={"targetDir": str(target)},
            )
        target.mkdir(parents=True, exist_ok=True)
        target_root = target.resolve()

        for candidate in candidates:
            destination = _safe_destination(target_root, candidate.relative_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                data = archive.read(candidate.info)
            except RuntimeError as exc:
                raise RagValidationError(
                    "RAG zip member could not be read",
                    details={"path": candidate.relative_path},
                ) from exc
            if len(data) > max_file_bytes:
                raise RagValidationError(
                    "RAG zip member is too large",
                    details={
                        "path": candidate.relative_path,
                        "sizeBytes": len(data),
                        "maxBytes": max_file_bytes,
                    },
                )
            destination.write_bytes(data)

    return {
        "archiveName": archive_file_name,
        "filesSeen": files_seen,
        "filesImported": len(candidates),
        "filesSkipped": len(skipped),
        "bytesImported": imported_total_bytes,
        "skipped": skipped[:50],
    }


def replace_directory(src: Path, dest: Path) -> None:
    """Move ``src`` to ``dest``, replacing an existing import directory."""

    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    src.replace(dest)


def _normalize_zip_member_path(raw_name: str) -> str:
    cleaned = raw_name.replace("\\", "/").strip()
    if "\x00" in cleaned:
        raise RagValidationError("RAG zip member path contains a NUL byte")
    if not cleaned or cleaned.startswith("/") or _WINDOWS_DRIVE_RE.match(cleaned):
        raise RagValidationError(
            "RAG zip member path must be relative",
            details={"path": raw_name},
        )
    path = PurePosixPath(cleaned)
    parts = path.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise RagValidationError(
            "RAG zip member path must stay within the archive root",
            details={"path": raw_name},
        )
    normalized = path.as_posix()
    if normalized in {".", ".."} or normalized.startswith("../") or "/../" in normalized:
        raise RagValidationError(
            "RAG zip member path must stay within the archive root",
            details={"path": raw_name},
        )
    return normalized


def _reject_special_zip_member(info: zipfile.ZipInfo) -> None:
    unix_mode = info.external_attr >> 16
    if stat.S_ISLNK(unix_mode):
        raise RagValidationError(
            "RAG zip archive must not contain symlinks",
            details={"path": info.filename},
        )


def _skip_reason(relative_path: str) -> str | None:
    if relative_path.split("/", 1)[0] == "__MACOSX":
        return "macos_metadata"
    if is_hidden_relative_path(relative_path):
        return "hidden_path"
    if any(fnmatch.fnmatch(relative_path, pattern) for pattern in DEFAULT_EXCLUDE_GLOBS):
        return "excluded"
    extension = Path(relative_path).suffix.lower()
    if not is_supported_text_extension(extension):
        return "unsupported_extension"
    return None


def _safe_destination(target_root: Path, relative_path: str) -> Path:
    destination = (target_root / relative_path).resolve()
    try:
        destination.relative_to(target_root)
    except ValueError as exc:
        raise RagValidationError(
            "RAG zip member path escapes import target",
            details={"path": relative_path},
        ) from exc
    return destination
