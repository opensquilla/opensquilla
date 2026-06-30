"""Path normalization and safety helpers for local document RAG."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from opensquilla.gateway.config import GatewayConfig

from .errors import RagValidationError

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


def validate_identifier(value: str, *, field: str = "identifier") -> str:
    cleaned = (value or "").strip()
    if not _IDENTIFIER_RE.match(cleaned):
        raise RagValidationError(
            f"Invalid {field}",
            details={field: value, "allowed": "letters, digits, '.', '_' and '-'"},
        )
    return cleaned


def validate_db_name(value: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned or "/" in cleaned or "\\" in cleaned or cleaned in {".", ".."}:
        raise RagValidationError("RAG database name must be a simple file name")
    if ".." in Path(cleaned).parts:
        raise RagValidationError("RAG database name must be a simple file name")
    return cleaned


def rag_state_dir(config: GatewayConfig) -> Path:
    state_dir = Path(str(getattr(config, "state_dir", "") or "~/.opensquilla/state"))
    return state_dir.expanduser() / "rag"


def rag_db_path(config: GatewayConfig) -> Path:
    return rag_state_dir(config) / validate_db_name(config.rag.db_name)


def normalize_source_root(path: str | Path) -> Path:
    raw = str(path).strip()
    if not raw:
        raise RagValidationError("RAG source path must not be empty")
    expanded = Path(raw).expanduser()
    absolute = expanded if expanded.is_absolute() else expanded.resolve()
    if str(absolute) == "/":
        raise RagValidationError("RAG source root '/' is not allowed")
    if absolute.exists():
        return absolute.resolve()
    return absolute.absolute()


def safe_relative_path(root: Path, candidate: Path) -> str:
    root_resolved = root.resolve()
    candidate_resolved = candidate.resolve()
    try:
        relative = candidate_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise RagValidationError(
            "Path escapes RAG source root",
            details={"root": str(root_resolved), "path": str(candidate_resolved)},
        ) from exc
    value = relative.as_posix()
    if not value or value == "." or value.startswith("../") or "/../" in value:
        raise RagValidationError("Invalid relative source path", details={"path": value})
    return value


def normalize_relative_path(value: str, *, field: str = "path") -> str:
    cleaned = value.strip().replace("\\", "/")
    if not cleaned or cleaned.startswith("/") or cleaned == "..":
        raise RagValidationError(f"Invalid relative {field}", details={field: value})
    if cleaned.startswith("../") or "/../" in cleaned:
        raise RagValidationError(f"Invalid relative {field}", details={field: value})
    if cleaned == ".":
        raise RagValidationError(f"Invalid relative {field}", details={field: value})
    return cleaned


def normalize_globs(values: Any) -> tuple[str, ...]:
    if not values:
        return ()
    if isinstance(values, str):
        values = [values]
    result: list[str] = []
    for raw in values:
        value = str(raw).strip().replace("\\", "/")
        if not value:
            continue
        result.append(normalize_relative_path(value, field="glob"))
    return tuple(result)


def is_hidden_relative_path(relative_path: str) -> bool:
    return any(part.startswith(".") for part in relative_path.split("/") if part)


def is_supported_text_extension(extension: str) -> bool:
    return extension.lower() in {".md", ".markdown", ".txt"}


DEFAULT_EXCLUDE_GLOBS: tuple[str, ...] = (
    ".git/**",
    ".hg/**",
    ".svn/**",
    ".DS_Store",
    "node_modules/**",
    ".venv/**",
    "venv/**",
    "__pycache__/**",
    "*.pyc",
    "*.sqlite",
    "*.sqlite3",
    "*.db",
    "*.db-wal",
    "*.db-shm",
    "*.log",
    ".env",
    ".env.*",
)
