from __future__ import annotations

import ast
from pathlib import Path

from opensquilla.contracts import attachments
from opensquilla.gateway import attachment_ingest


def test_attachment_policy_is_shared_with_gateway_ingest() -> None:
    assert attachment_ingest.ALLOWED_MEDIA_TYPES is attachments.ALLOWED_MEDIA_TYPES
    assert attachment_ingest.MAX_ATTACHMENT_BYTES == attachments.MAX_ATTACHMENT_BYTES
    assert (
        attachment_ingest.attachment_size_limit_for_mime("application/pdf", staged=True)
        == attachments.MAX_STAGED_PDF_BYTES
    )


def test_office_documents_are_stageable_above_the_inline_threshold() -> None:
    # Office docs commonly exceed the 2MB inline threshold; they must be
    # stageable so primary clients route them through the upload endpoint
    # instead of rejecting them as "too large".
    for mime in (attachments.DOCX_MIME, attachments.XLSX_MIME, attachments.PPTX_MIME):
        assert attachments.can_stage_attachment_mime(mime) is True
        assert (
            attachments.attachment_size_limit_for_mime(mime, staged=True)
            == attachments.OFFICE_ATTACHMENT_BYTES
        )
        assert attachments.OFFICE_ATTACHMENT_BYTES > attachments.INLINE_ATTACHMENT_BYTES


def test_email_is_capped_at_the_text_limit_and_not_stageable() -> None:
    # Email is plain text whose headers are forgeable, and only bounded body
    # text is extracted, so it must NOT get a larger cap or a staged path that
    # arbitrary content could claim to bypass the 2MB text limit.
    assert attachments.EMAIL_ATTACHMENT_BYTES == attachments.TEXT_ATTACHMENT_BYTES
    for mime in (attachments.EML_MIME, attachments.MBOX_MIME, attachments.MSG_MIME):
        assert mime in attachments.ALLOWED_MEDIA_TYPES
        assert attachments.can_stage_attachment_mime(mime) is False
        assert (
            attachments.attachment_size_limit_for_mime(mime, staged=True)
            == attachments.TEXT_ATTACHMENT_BYTES
        )


def test_channel_attachment_io_does_not_import_gateway_policy() -> None:
    imports = _imports_from(Path("src/opensquilla/channels/_attachment_io.py"))

    assert "opensquilla.gateway.attachment_ingest" not in imports
    assert "opensquilla.contracts.attachments" in imports


def test_policy_only_consumers_do_not_import_gateway_ingest() -> None:
    for relative in [
        "src/opensquilla/cli/attachments.py",
        "src/opensquilla/engine/runtime.py",
        "src/opensquilla/gateway/uploads.py",
    ]:
        imports = _imports_from(Path(relative))
        assert "opensquilla.gateway.attachment_ingest" not in imports
        assert "opensquilla.contracts.attachments" in imports


def _imports_from(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
