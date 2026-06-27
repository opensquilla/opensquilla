"""Attachment policy shared by gateway and channel runtime boundaries."""

from __future__ import annotations

from typing import Any

# Modern Office Open XML (OOXML) document MIME types. These are zip containers,
# so they are extracted to text server-side rather than sent to a provider raw.
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

# Email message formats. .eml/.mbox are text (RFC 5322); .msg is an OLE
# compound file. All are extracted to bounded text server-side.
EML_MIME = "message/rfc822"
MBOX_MIME = "application/mbox"
MSG_MIME = "application/vnd.ms-outlook"

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
        DOCX_MIME,
        XLSX_MIME,
        PPTX_MIME,
        EML_MIME,
        MBOX_MIME,
        MSG_MIME,
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
OFFICE_ATTACHMENT_MIMES: frozenset[str] = frozenset(
    {
        DOCX_MIME,
        XLSX_MIME,
        PPTX_MIME,
    }
)
EMAIL_ATTACHMENT_MIMES: frozenset[str] = frozenset(
    {
        EML_MIME,
        MBOX_MIME,
        MSG_MIME,
    }
)

MAX_ATTACHMENTS = 10
INLINE_ATTACHMENT_BYTES = 2 * 1000 * 1000
TEXT_ATTACHMENT_BYTES = INLINE_ATTACHMENT_BYTES
IMAGE_ATTACHMENT_BYTES = 5 * 1024 * 1024
MAX_ATTACHMENT_BYTES = IMAGE_ATTACHMENT_BYTES
MAX_STAGED_PDF_BYTES = 30 * 1024 * 1024
# Office documents are zip containers extracted to bounded text; the raw upload
# is never forwarded to a provider, so a generous ceiling is safe.
OFFICE_ATTACHMENT_BYTES = 30 * 1024 * 1024
# Email is held to the text cap, NOT a larger ceiling. Only bounded body text +
# headers + an attachment-name listing are extracted (embedded attachment bytes
# are never read), so a large raw email buys nothing — and since email is plain
# text whose headers are trivially forgeable, a larger cap would just let
# arbitrary content claim an email mime to bypass the text limit.
EMAIL_ATTACHMENT_BYTES = TEXT_ATTACHMENT_BYTES
MAX_TOTAL_ATTACHMENT_BYTES = 60 * 1024 * 1024
SNIFF_PEEK_BYTES = 1024
PDF_MAGIC = b"%PDF-"
# Local file header signature shared by all zip-based formats (OOXML, ODF…).
ZIP_MAGIC = b"PK\x03\x04"
# OLE2 / Compound File Binary signature (Outlook .msg, legacy Office).
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def normalize_attachment_mime(mime: Any) -> str | None:
    if not isinstance(mime, str):
        return None
    normalized = mime.split(";", 1)[0].strip().lower()
    return normalized or None


def can_stage_attachment_mime(mime: Any) -> bool:
    # Email is intentionally NOT stageable: it is capped at the text limit, so it
    # never exceeds the inline threshold and has no staged path to abuse.
    normalized = normalize_attachment_mime(mime)
    return (
        normalized == "application/pdf"
        or normalized in IMAGE_ATTACHMENT_MIMES
        or normalized in OFFICE_ATTACHMENT_MIMES
    )


def attachment_size_limit_for_mime(mime: Any, *, staged: bool = False) -> int:
    normalized = normalize_attachment_mime(mime)
    if normalized == "application/pdf":
        return MAX_STAGED_PDF_BYTES if staged else MAX_ATTACHMENT_BYTES
    if normalized in TEXT_ATTACHMENT_MIMES:
        return TEXT_ATTACHMENT_BYTES
    if normalized in IMAGE_ATTACHMENT_MIMES:
        return IMAGE_ATTACHMENT_BYTES
    if normalized in OFFICE_ATTACHMENT_MIMES:
        return OFFICE_ATTACHMENT_BYTES
    if normalized in EMAIL_ATTACHMENT_MIMES:
        return EMAIL_ATTACHMENT_BYTES
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
