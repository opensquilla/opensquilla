"""Shared attachment ingress normalization for RPC and external channels."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import structlog

from opensquilla.attachment_refs import make_attachment_ref, write_transcript_material
from opensquilla.contracts.attachments import (
    ALLOWED_MEDIA_TYPES,
    DOCX_MIME,
    EML_MIME,
    IMAGE_ATTACHMENT_BYTES,
    IMAGE_ATTACHMENT_MIMES,
    INLINE_ATTACHMENT_BYTES,
    MAX_ATTACHMENT_BYTES,
    MAX_ATTACHMENTS,
    MAX_STAGED_PDF_BYTES,
    MAX_TOTAL_ATTACHMENT_BYTES,
    MBOX_MIME,
    MSG_MIME,
    OFFICE_ATTACHMENT_MIMES,
    OLE_MAGIC,
    PDF_MAGIC,
    PPTX_MIME,
    SNIFF_PEEK_BYTES,
    TEXT_ATTACHMENT_BYTES,
    TEXT_ATTACHMENT_MIMES,
    XLSX_MIME,
    ZIP_MAGIC,
    attachment_size_limit_for_mime,
    can_stage_attachment_mime,
    normalize_attachment_mime,
)

log = structlog.get_logger(__name__)

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
    "AttachmentFailure",
    "AttachmentIngestResult",
    "AttachmentTotalTooLargeError",
    "attachment_media_type",
    "attachment_size_limit_for_mime",
    "can_stage_attachment_mime",
    "enforce_total_attachment_bytes",
    "ingest_attachments",
    "normalize_attachment_mime",
    "normalize_attachments",
    "resolve_attachments",
    "sniff_mime_from_bytes",
    "validate_attachments",
]


class AttachmentTotalTooLargeError(ValueError):
    pass


@dataclass(frozen=True)
class AttachmentFailure:
    index: int
    name: str
    reason: str
    detail: str

    @property
    def marker(self) -> str:
        return f"[attachment unavailable: {self.name}: {self.reason}]"


@dataclass
class AttachmentIngestResult:
    text: str
    attachments: list[dict[str, Any]] = field(default_factory=list)
    failures: list[AttachmentFailure] = field(default_factory=list)
    consumed_file_uuids: list[str] = field(default_factory=list)


def attachment_media_type(attachment: dict[str, Any]) -> str | None:
    """Return the claimed MIME if it is in the allow-list, else None."""

    candidates = [
        attachment.get("type"),
        attachment.get("mime"),
        attachment.get("media_type"),
        attachment.get("mime_type"),
    ]
    for candidate in candidates:
        normalized = normalize_attachment_mime(candidate)
        if normalized in ALLOWED_MEDIA_TYPES:
            return normalized
    return None


def _coerce_attachment_dict(attachment: Any) -> dict[str, Any] | None:
    if isinstance(attachment, dict):
        return dict(attachment)
    model_dump = getattr(attachment, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dict(dumped) if isinstance(dumped, dict) else None
    return None


def normalize_attachments(raw_attachments: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_attachments, list):
        return []

    normalized: list[dict[str, Any]] = []
    for attachment in raw_attachments:
        item = _coerce_attachment_dict(attachment)
        if item is None:
            continue
        media_type = attachment_media_type(item)
        if media_type is not None:
            item["type"] = media_type
        normalized.append(item)
    return normalized


def _sniff_ooxml_mime(raw: bytes) -> str | None:
    """Identify a specific OOXML subtype from a zip container's part names.

    Reads only the central directory (``namelist``); no member is decompressed,
    so this is not a zip-bomb vector. Returns ``None`` for non-OOXML zips.
    """

    import io
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = set(archive.namelist())
    except (zipfile.BadZipFile, OSError, ValueError):
        return None
    if "word/document.xml" in names:
        return DOCX_MIME
    if "xl/workbook.xml" in names:
        return XLSX_MIME
    if "ppt/presentation.xml" in names:
        return PPTX_MIME
    return None


def _looks_like_rfc5322_headers(text: str) -> bool:
    """True when ``text`` opens with an RFC 5322 header block carrying a strong
    email signal (Message-ID/Received/MIME-Version, or both From and Date)."""

    header_names: set[str] = set()
    for line in text.splitlines():
        if not line:
            break  # blank line terminates the header block
        if line[0] in " \t":
            continue  # folded continuation of the previous header
        name, sep, _ = line.partition(":")
        if not sep or not name or any(ch <= " " for ch in name):
            return False  # first non-header line and no email evidence yet
        header_names.add(name.strip().lower())
        if header_names & {"message-id", "received", "mime-version"} or {
            "from",
            "date",
        } <= header_names:
            return True
    return False


def _sniff_email_mime(text: str) -> str | None:
    """Detect a text-based email (.eml / .mbox) from the decoded head.

    Requires a strong RFC 5322 signal so ordinary prose is not misread as an
    email. An mbox must carry a real ``From `` envelope line *followed by* a
    header block — a bare ``From `` prefix (e.g. "From the start…") is not
    enough, so prose cannot inherit the larger email size cap.
    """

    if text.startswith("From "):
        newline = text.find("\n")
        if newline != -1 and _looks_like_rfc5322_headers(text[newline + 1 :]):
            return MBOX_MIME
        return None
    if _looks_like_rfc5322_headers(text):
        return EML_MIME
    return None


def sniff_mime_from_bytes(raw: bytes) -> str | None:
    """Detect MIME from authoritative magic bytes or complete JSON payloads."""

    head = raw[:SNIFF_PEEK_BYTES]
    if head.startswith(PDF_MAGIC):
        return "application/pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
        return "image/gif"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith(ZIP_MAGIC):
        ooxml = _sniff_ooxml_mime(raw)
        if ooxml is not None:
            return ooxml
    if head.startswith(OLE_MAGIC):
        # OLE2 compound file — treated as an Outlook .msg here; the extractor
        # degrades gracefully if it turns out to be another OLE format.
        return MSG_MIME

    try:
        text = head.decode("utf-8")
    except UnicodeDecodeError:
        return None

    email_mime = _sniff_email_mime(text)
    if email_mime is not None:
        return email_mime

    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            import json as _json

            _json.loads(raw.decode("utf-8"))
            return "application/json"
        except (UnicodeDecodeError, ValueError):
            pass

    # Last resort: a fully clean-UTF-8, NUL-free payload is treated as plain
    # text so unknown-but-textual uploads degrade to readable context instead of
    # a hard rejection. The ENTIRE payload is validated (not just the peek
    # window) so a text head with a binary tail is not misclassified. This is a
    # weak signal — callers never let it override a more specific claimed type.
    if b"\x00" in raw:
        return None
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return "text/plain"


def _display_attachment_name(raw: Any, fallback: str) -> str:
    if not isinstance(raw, str):
        return fallback
    collapsed = " ".join(raw.strip().split())
    if not collapsed:
        return fallback
    return collapsed[:160]


def _attachment_name(attachment: dict[str, Any], index: int) -> str:
    raw = attachment.get("name") or attachment.get("filename")
    return _display_attachment_name(raw, f"attachment-{index}")


def _failure(index: int, attachment: dict[str, Any], reason: str, detail: str) -> AttachmentFailure:
    return AttachmentFailure(
        index=index,
        name=_attachment_name(attachment, index),
        reason=reason,
        detail=detail,
    )


def _raise_or_mark(
    *,
    failure_mode: Literal["raise", "mark"],
    failures: list[AttachmentFailure],
    failure: AttachmentFailure,
) -> None:
    if failure_mode == "raise":
        raise ValueError(f"attachments[{failure.index}] {failure.detail}")
    failures.append(failure)


def _raw_bytes_from_data(data: Any, *, index: int) -> tuple[bytes, bool]:
    """Return bytes and whether the source was already bytes instead of base64."""

    if isinstance(data, bytes):
        return data, True
    if isinstance(data, bytearray):
        return bytes(data), True
    if isinstance(data, str) and data:
        try:
            return base64.b64decode(data, validate=True), False
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f"attachments[{index}].data must be valid base64") from exc
    raise ValueError(f"attachments[{index}].data is required")


def validate_attachments(
    raw_attachments: Any,
    *,
    failure_mode: Literal["raise", "mark"] = "raise",
    mark_bytes_as_staged: bool = False,
    logger: Any | None = None,
) -> tuple[list[dict[str, Any]], list[AttachmentFailure]]:
    normalized = normalize_attachments(raw_attachments)
    failures: list[AttachmentFailure] = []
    if len(normalized) > MAX_ATTACHMENTS:
        failure = AttachmentFailure(
            index=MAX_ATTACHMENTS + 1,
            name="attachments",
            reason="too_many",
            detail=f"supports at most {MAX_ATTACHMENTS} items",
        )
        if failure_mode == "raise":
            raise ValueError(f"attachments supports at most {MAX_ATTACHMENTS} items")
        failures.append(failure)
        normalized = normalized[:MAX_ATTACHMENTS]

    validated: list[dict[str, Any]] = []
    for index, attachment in enumerate(normalized, start=1):
        if attachment.get("_ingest_error"):
            _raise_or_mark(
                failure_mode=failure_mode,
                failures=failures,
                failure=_failure(
                    index,
                    attachment,
                    "download_failed",
                    f"download_failed: {attachment.get('_ingest_error')}",
                ),
            )
            continue

        data = attachment.get("data")
        has_data = (isinstance(data, str) and bool(data)) or isinstance(data, (bytes, bytearray))
        file_uuid = attachment.get("file_uuid")
        has_uuid = isinstance(file_uuid, str) and bool(file_uuid)

        if has_data and has_uuid:
            _raise_or_mark(
                failure_mode=failure_mode,
                failures=failures,
                failure=_failure(
                    index,
                    attachment,
                    "invalid_shape",
                    "must carry exactly one of data or file_uuid, not both",
                ),
            )
            continue

        claimed = attachment_media_type(attachment)

        if has_uuid:
            if claimed is None:
                _raise_or_mark(
                    failure_mode=failure_mode,
                    failures=failures,
                    failure=_failure(
                        index,
                        attachment,
                        "unsupported_mime",
                        "file_uuid reference must declare a supported mime / media_type",
                    ),
                )
                continue
            item = dict(attachment)
            item["type"] = claimed
            item["file_uuid"] = file_uuid
            item.pop("data", None)
            validated.append(item)
            continue

        if not has_data:
            _raise_or_mark(
                failure_mode=failure_mode,
                failures=failures,
                failure=_failure(
                    index,
                    attachment,
                    "missing_data",
                    "must carry either data or file_uuid",
                ),
            )
            continue

        try:
            raw_bytes, was_bytes = _raw_bytes_from_data(data, index=index)
        except ValueError as exc:
            _raise_or_mark(
                failure_mode=failure_mode,
                failures=failures,
                failure=_failure(index, attachment, "invalid_data", str(exc)),
            )
            continue

        sniffed = sniff_mime_from_bytes(raw_bytes)

        if claimed is None:
            # Unknown / unsupported claimed type: accept only if the bytes are
            # cleanly decodable text (UTF-8 fallback); everything binary stays
            # fail-closed.
            if sniffed == "text/plain":
                claimed = "text/plain"
            else:
                raw_claim = (
                    attachment.get("type")
                    or attachment.get("mime")
                    or attachment.get("media_type")
                    or attachment.get("mime_type")
                )
                _raise_or_mark(
                    failure_mode=failure_mode,
                    failures=failures,
                    failure=_failure(
                        index,
                        attachment,
                        "unsupported_mime",
                        "media type "
                        f"{raw_claim!r} is not allowed; must be one of "
                        f"{sorted(ALLOWED_MEDIA_TYPES)}",
                    ),
                )
                continue

        if claimed == "application/pdf" and sniffed != "application/pdf":
            _raise_or_mark(
                failure_mode=failure_mode,
                failures=failures,
                failure=_failure(
                    index,
                    attachment,
                    "mime_mismatch",
                    "claims application/pdf but lacks %PDF- magic bytes (415 equivalent)",
                ),
            )
            continue

        if claimed in OFFICE_ATTACHMENT_MIMES and sniffed != claimed:
            _raise_or_mark(
                failure_mode=failure_mode,
                failures=failures,
                failure=_failure(
                    index,
                    attachment,
                    "mime_mismatch",
                    f"claims {claimed} but the bytes are not a matching OOXML "
                    "document (415 equivalent)",
                ),
            )
            continue

        if claimed == MSG_MIME and sniffed != MSG_MIME:
            _raise_or_mark(
                failure_mode=failure_mode,
                failures=failures,
                failure=_failure(
                    index,
                    attachment,
                    "mime_mismatch",
                    "claims an Outlook .msg but is not an OLE compound file "
                    "(415 equivalent)",
                ),
            )
            continue

        # Text-based email (.eml/.mbox) carries the larger email size ceiling, so
        # the bytes must actually look like an email. Otherwise arbitrary text
        # could claim message/rfc822 to bypass the smaller text-attachment cap.
        if claimed in {EML_MIME, MBOX_MIME} and sniffed not in {EML_MIME, MBOX_MIME}:
            _raise_or_mark(
                failure_mode=failure_mode,
                failures=failures,
                failure=_failure(
                    index,
                    attachment,
                    "mime_mismatch",
                    "claims an email message but lacks RFC 5322 / mbox structure "
                    "(415 equivalent)",
                ),
            )
            continue

        if sniffed is not None and sniffed != claimed:
            # The UTF-8 text fallback is a weak signal: never let it downgrade a
            # claimed text-family type (e.g. .csv) we already accept. Larger-cap
            # types (email) are confirmed by the guards above, so by this point a
            # text/plain sniff can only co-occur with a same-cap text claim.
            if sniffed == "text/plain":
                resolved = claimed
            else:
                (logger or log).warning(
                    "attachment.mime_mismatch",
                    claimed=claimed,
                    sniffed=sniffed,
                    attachment_index=index,
                )
                resolved = sniffed if sniffed in ALLOWED_MEDIA_TYPES else claimed
        else:
            resolved = claimed

        max_bytes = attachment_size_limit_for_mime(
            resolved,
            staged=mark_bytes_as_staged and can_stage_attachment_mime(resolved),
        )
        if len(raw_bytes) > max_bytes:
            _raise_or_mark(
                failure_mode=failure_mode,
                failures=failures,
                failure=_failure(
                    index,
                    attachment,
                    "oversize",
                    f"exceeds the {max_bytes} byte limit",
                ),
            )
            continue

        item = dict(attachment)
        item["type"] = resolved
        item["data"] = base64.b64encode(raw_bytes).decode("ascii")
        item["name"] = _attachment_name(item, index)
        item.pop("mime_type", None)
        item.pop("url", None)
        item.pop("size", None)
        item.pop("metadata", None)
        if was_bytes and mark_bytes_as_staged:
            item["_was_staged"] = True
        validated.append(item)

    return validated, failures


def _attachment_raw_size(attachment: dict[str, Any], index: int) -> int:
    if attachment.get("kind") == "attachment_ref":
        size = attachment.get("size")
        if isinstance(size, int) and size >= 0:
            return size
        raise ValueError(f"attachments[{index}].size is required for attachment_ref")
    data = attachment.get("data")
    raw_bytes, _was_bytes = _raw_bytes_from_data(data, index=index)
    return len(raw_bytes)


def enforce_total_attachment_bytes(attachments: list[dict[str, Any]]) -> None:
    total = 0
    for index, attachment in enumerate(attachments, start=1):
        total += _attachment_raw_size(attachment, index)
        if total > MAX_TOTAL_ATTACHMENT_BYTES:
            raise AttachmentTotalTooLargeError(
                "attachments total raw bytes exceed "
                f"the {MAX_TOTAL_ATTACHMENT_BYTES} byte limit"
            )


async def resolve_attachments(
    validated: list[dict[str, Any]],
    store: Any | None = None,
    *,
    material_root: Path | None = None,
    session_id: str | None = None,
    disk_budget_bytes: int | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    if not any(isinstance(a, dict) and a.get("file_uuid") for a in validated):
        enforce_total_attachment_bytes(validated)
        return validated, []

    from opensquilla.gateway.uploads import (
        AttachmentLostInRestartError,
        AttachmentNotFoundError,
    )
    from opensquilla.gateway.uploads import get_upload_store as _default_store

    upload_store = store if store is not None else _default_store()
    resolved: list[dict[str, Any]] = []
    consumed: list[str] = []
    for index, attachment in enumerate(validated, start=1):
        ref = attachment.get("file_uuid") if isinstance(attachment, dict) else None
        if not isinstance(ref, str):
            resolved.append(attachment)
            continue
        try:
            payload, meta = await upload_store.get(ref)
        except AttachmentLostInRestartError as exc:
            raise ValueError(
                f"attachments[{index}] uuid lost in gateway restart; please re-upload"
            ) from exc
        except AttachmentNotFoundError as exc:
            raise ValueError(
                f"attachments[{index}] file_uuid {ref!r} is unknown or expired"
            ) from exc
        candidate = {k: v for k, v in attachment.items() if k != "file_uuid"}
        candidate["data"] = payload
        if "type" not in candidate or not isinstance(candidate.get("type"), str):
            candidate["type"] = meta["mime"]
        if "name" not in candidate or not isinstance(candidate.get("name"), str):
            candidate["name"] = meta["name"]
        materialized, _failures = validate_attachments(
            [candidate],
            failure_mode="raise",
            mark_bytes_as_staged=True,
        )
        item = materialized[0]
        if material_root is None or not session_id:
            raise ValueError(
                f"attachments[{index}] file_uuid resolution requires a material target"
            )
        raw_bytes, _was_bytes = _raw_bytes_from_data(item.get("data"), index=index)
        sha, _path, _wrote = write_transcript_material(
            media_root=material_root,
            session_id=session_id,
            payload=raw_bytes,
            disk_budget_bytes=disk_budget_bytes,
        )
        resolved.append(
            make_attachment_ref(
                sha256=sha,
                name=item["name"],
                mime=item["type"],
                size=len(raw_bytes),
                session_id=session_id,
                source="upload",
            )
        )
        consumed.append(ref)
    enforce_total_attachment_bytes(resolved)
    return resolved, consumed


async def ingest_attachments(
    text: str,
    raw_attachments: Any,
    *,
    store: Any | None = None,
    failure_mode: Literal["raise", "mark"] = "raise",
    mark_bytes_as_staged: bool = False,
    material_root: Path | None = None,
    session_id: str | None = None,
    disk_budget_bytes: int | None = None,
) -> AttachmentIngestResult:
    validated, failures = validate_attachments(
        raw_attachments,
        failure_mode=failure_mode,
        mark_bytes_as_staged=mark_bytes_as_staged,
    )
    resolved, consumed = await resolve_attachments(
        validated,
        store=store,
        material_root=material_root,
        session_id=session_id,
        disk_budget_bytes=disk_budget_bytes,
    )
    if failures:
        markers = [failure.marker for failure in failures]
        text = "\n".join([text, *markers]).strip()
    return AttachmentIngestResult(
        text=text,
        attachments=resolved,
        failures=failures,
        consumed_file_uuids=consumed,
    )
