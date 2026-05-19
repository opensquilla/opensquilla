"""CLI helpers for local file and image attachment commands."""

from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from opensquilla.gateway.attachment_ingest import (
    IMAGE_ATTACHMENT_BYTES,
    MAX_STAGED_PDF_BYTES,
    TEXT_ATTACHMENT_BYTES,
    can_stage_attachment_mime,
)
from opensquilla.gateway.attachment_ingest import (
    attachment_size_limit_for_mime as _policy_attachment_size_limit_for_mime,
)

CLI_INLINE_THRESHOLD_BYTES = TEXT_ATTACHMENT_BYTES
CLI_TEXT_ATTACHMENT_BYTES = TEXT_ATTACHMENT_BYTES
CLI_IMAGE_ATTACHMENT_BYTES = IMAGE_ATTACHMENT_BYTES
CLI_ENGINE_ATTACHMENT_BYTES = IMAGE_ATTACHMENT_BYTES
CLI_STAGED_PDF_BYTES = MAX_STAGED_PDF_BYTES

CLI_IMAGE_MIMES: dict[str, str] = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
}

CLI_ALLOWED_FILE_MIMES: dict[str, str] = {
    **CLI_IMAGE_MIMES,
    "pdf": "application/pdf",
    "txt": "text/plain",
    "md": "text/markdown",
    "markdown": "text/markdown",
    "html": "text/html",
    "htm": "text/html",
    "csv": "text/csv",
    "json": "application/json",
}
CLI_TEXT_FAMILY_MIMES: frozenset[str] = frozenset(
    {
        "text/plain",
        "text/markdown",
        "text/html",
        "text/csv",
        "application/json",
    }
)

UploadCallable = Callable[[Path, str, str], str]
AsyncUploadCallable = Callable[[Path, str, str], Awaitable[str]]

__all__ = (
    "AsyncUploadCallable",
    "CLI_ALLOWED_FILE_MIMES",
    "CLI_ENGINE_ATTACHMENT_BYTES",
    "CLI_IMAGE_ATTACHMENT_BYTES",
    "CLI_IMAGE_MIMES",
    "CLI_INLINE_THRESHOLD_BYTES",
    "CLI_STAGED_PDF_BYTES",
    "CLI_TEXT_ATTACHMENT_BYTES",
    "CLI_TEXT_FAMILY_MIMES",
    "UploadCallable",
    "async_file_prompt_and_attachments",
    "attachment_size_limit_for_mime",
    "attachments_from_paths",
    "build_file_attachment",
    "build_file_attachment_async",
    "file_prompt_and_attachments",
    "image_prompt_and_attachments",
    "image_prompt_from_command",
    "mime_for_path",
)


def attachment_size_limit_for_mime(mime: str) -> int:
    return _policy_attachment_size_limit_for_mime(mime, staged=True)


def _can_stage_mime(mime: str) -> bool:
    return can_stage_attachment_mime(mime)


def _allowed_label() -> str:
    return ", ".join(sorted(set(CLI_ALLOWED_FILE_MIMES.values())))


def mime_for_path(path: Path) -> str:
    ext = path.suffix.lower().lstrip(".")
    mime = CLI_ALLOWED_FILE_MIMES.get(ext)
    if not mime:
        raise ValueError(f"Unsupported format: .{ext}. Allowed: {_allowed_label()}")
    return mime


def _ensure_existing_file(path: Path) -> None:
    if not path.exists():
        raise ValueError(f"File not found: {path}")
    if not path.is_file():
        raise ValueError(f"Not a file: {path}")


def _inline_attachment(path: Path, mime: str) -> dict[str, Any]:
    return {
        "type": mime,
        "data": base64.b64encode(path.read_bytes()).decode("ascii"),
        "name": path.name,
    }


def _check_size_policy(path: Path, mime: str) -> int:
    size = path.stat().st_size
    limit = attachment_size_limit_for_mime(mime)
    if size > limit:
        if mime == "application/pdf":
            detail = f"{CLI_STAGED_PDF_BYTES} byte PDF limit"
        elif mime in CLI_TEXT_FAMILY_MIMES:
            detail = (
                f"{CLI_TEXT_ATTACHMENT_BYTES} byte text-family direct attachment limit; "
                "use /path for bounded local reads"
            )
        elif mime in CLI_IMAGE_MIMES.values():
            detail = f"{CLI_IMAGE_ATTACHMENT_BYTES} byte image attachment limit"
        else:
            detail = f"{CLI_ENGINE_ATTACHMENT_BYTES} byte attachment limit"
        raise ValueError(f"File too large: {path.name} is {size} bytes; max is {detail}")
    return size


def build_file_attachment(
    path: str | Path,
    *,
    upload_callable: UploadCallable | None = None,
) -> dict[str, Any]:
    local = Path(path).expanduser()
    _ensure_existing_file(local)
    mime = mime_for_path(local)
    size = _check_size_policy(local, mime)
    if size <= CLI_INLINE_THRESHOLD_BYTES:
        return _inline_attachment(local, mime)
    if not _can_stage_mime(mime):
        raise ValueError(
            f"File too large to attach directly ({size} bytes > "
            f"{CLI_TEXT_ATTACHMENT_BYTES}); text-family attachments are not staged. "
            "Use /path for bounded local reads."
        )
    if upload_callable is None:
        raise ValueError(
            f"File too large to inline ({size} bytes > {CLI_INLINE_THRESHOLD_BYTES}); "
            "gateway bridge upload is required for this file"
        )
    try:
        file_uuid = upload_callable(local, mime, local.name)
    except Exception as exc:  # noqa: BLE001 - caller gets a CLI-facing error
        raise ValueError(
            f"File too large to inline ({size} bytes); gateway upload endpoint unavailable: {exc}"
        ) from exc
    return {"type": mime, "file_uuid": file_uuid, "name": local.name, "mime": mime}


async def build_file_attachment_async(
    path: str | Path,
    *,
    upload_callable: AsyncUploadCallable | None = None,
) -> dict[str, Any]:
    local = Path(path).expanduser()
    _ensure_existing_file(local)
    mime = mime_for_path(local)
    size = _check_size_policy(local, mime)
    if size <= CLI_INLINE_THRESHOLD_BYTES:
        return _inline_attachment(local, mime)
    if not _can_stage_mime(mime):
        raise ValueError(
            f"File too large to attach directly ({size} bytes > "
            f"{CLI_TEXT_ATTACHMENT_BYTES}); text-family attachments are not staged. "
            "Use /path for bounded local reads."
        )
    if upload_callable is None:
        raise ValueError(
            f"File too large to inline ({size} bytes > {CLI_INLINE_THRESHOLD_BYTES}); "
            "gateway bridge upload is required for this file"
        )
    try:
        file_uuid = await upload_callable(local, mime, local.name)
    except Exception as exc:  # noqa: BLE001 - caller gets a CLI-facing error
        raise ValueError(
            f"File too large to inline ({size} bytes); gateway upload endpoint unavailable: {exc}"
        ) from exc
    return {"type": mime, "file_uuid": file_uuid, "name": local.name, "mime": mime}


def file_prompt_and_attachments(
    command: str,
    *,
    upload_callable: UploadCallable | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    parts = command[len("/file ") :].strip().split(None, 1)
    if not parts:
        raise ValueError("Usage: /file <path> [prompt]")
    path = Path(parts[0]).expanduser()
    prompt = parts[1] if len(parts) > 1 else "Read this file"
    return prompt, [build_file_attachment(path, upload_callable=upload_callable)]


async def async_file_prompt_and_attachments(
    command: str,
    *,
    upload_callable: AsyncUploadCallable | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    parts = command[len("/file ") :].strip().split(None, 1)
    if not parts:
        raise ValueError("Usage: /file <path> [prompt]")
    path = Path(parts[0]).expanduser()
    prompt = parts[1] if len(parts) > 1 else "Read this file"
    return prompt, [await build_file_attachment_async(path, upload_callable=upload_callable)]


def attachments_from_paths(paths: list[str] | tuple[str, ...]) -> list[dict[str, Any]]:
    return [build_file_attachment(path) for path in paths]


def image_prompt_from_command(command: str) -> str:
    parts = command[len("/image ") :].strip().split(None, 1)
    return parts[1] if len(parts) > 1 else "Describe this image"


def image_prompt_and_attachments(command: str) -> tuple[str, list[dict[str, str]]]:
    parts = command[len("/image ") :].strip().split(None, 1)
    if not parts:
        raise ValueError("Usage: /image <path> [prompt]")

    path = Path(parts[0]).expanduser()
    prompt = parts[1] if len(parts) > 1 else "Describe this image"
    _ensure_existing_file(path)

    ext = path.suffix.lower().lstrip(".")
    media_type = CLI_IMAGE_MIMES.get(ext)
    if not media_type:
        raise ValueError(f"Unsupported format: {ext}. Use png/jpg/gif/webp")
    _check_size_policy(path, media_type)

    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return prompt, [{"type": media_type, "data": data, "name": path.name}]
