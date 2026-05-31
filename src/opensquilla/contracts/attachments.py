"""Attachment policy shared by gateway and channel runtime boundaries."""

from __future__ import annotations

from typing import Any

ALLOWED_MEDIA_TYPES: frozenset[str] = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "application/pdf",
        "text/plain",
        "text/markdown",
        "text/html",
        "text/csv",
        "application/json",
    }
)

IMAGE_ATTACHMENT_MIMES: frozenset[str] = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
    }
)
TEXT_ATTACHMENT_MIMES: frozenset[str] = frozenset(
    {
        "text/plain",
        "text/markdown",
        "text/html",
        "text/csv",
        "application/json",
    }
)

MAX_ATTACHMENTS = 10
INLINE_ATTACHMENT_BYTES = 2 * 1000 * 1000
TEXT_ATTACHMENT_BYTES = INLINE_ATTACHMENT_BYTES
IMAGE_ATTACHMENT_BYTES = 5 * 1024 * 1024
MAX_ATTACHMENT_BYTES = IMAGE_ATTACHMENT_BYTES
MAX_STAGED_PDF_BYTES = 30 * 1024 * 1024
MAX_TOTAL_ATTACHMENT_BYTES = 60 * 1024 * 1024
SNIFF_PEEK_BYTES = 1024
PDF_MAGIC = b"%PDF-"


def normalize_attachment_mime(mime: Any) -> str | None:
    if not isinstance(mime, str):
        return None
    normalized = mime.split(";", 1)[0].strip().lower()
    return normalized or None


def can_stage_attachment_mime(mime: Any) -> bool:
    normalized = normalize_attachment_mime(mime)
    return normalized == "application/pdf" or normalized in IMAGE_ATTACHMENT_MIMES


def attachment_size_limit_for_mime(mime: Any, *, staged: bool = False) -> int:
    normalized = normalize_attachment_mime(mime)
    if normalized == "application/pdf":
        return MAX_STAGED_PDF_BYTES if staged else MAX_ATTACHMENT_BYTES
    if normalized in TEXT_ATTACHMENT_MIMES:
        return TEXT_ATTACHMENT_BYTES
    if normalized in IMAGE_ATTACHMENT_MIMES:
        return IMAGE_ATTACHMENT_BYTES
    return MAX_ATTACHMENT_BYTES


__all__ = [
    "ALLOWED_MEDIA_TYPES",
    "IMAGE_ATTACHMENT_BYTES",
    "IMAGE_ATTACHMENT_MIMES",
    "INLINE_ATTACHMENT_BYTES",
    "MAX_ATTACHMENT_BYTES",
    "MAX_ATTACHMENTS",
    "MAX_STAGED_PDF_BYTES",
    "MAX_TOTAL_ATTACHMENT_BYTES",
    "PDF_MAGIC",
    "SNIFF_PEEK_BYTES",
    "TEXT_ATTACHMENT_BYTES",
    "TEXT_ATTACHMENT_MIMES",
    "attachment_size_limit_for_mime",
    "can_stage_attachment_mime",
    "normalize_attachment_mime",
]
