from __future__ import annotations

import base64

import pytest

from opensquilla.contracts.attachments import SNIFF_PEEK_BYTES
from opensquilla.gateway.attachment_ingest import ingest_attachments


@pytest.mark.asyncio
async def test_channel_bytes_attachment_normalizes_to_engine_shape() -> None:
    result = await ingest_attachments(
        "read it",
        [{"name": "note.txt", "mime_type": "text/plain", "data": b"hello"}],
        failure_mode="mark",
        mark_bytes_as_staged=True,
    )

    assert result.text == "read it"
    assert result.failures == []
    assert result.attachments == [
        {
            "name": "note.txt",
            "type": "text/plain",
            "data": base64.b64encode(b"hello").decode("ascii"),
            "_was_staged": True,
        }
    ]


@pytest.mark.asyncio
async def test_url_only_channel_attachment_degrades_with_marker() -> None:
    result = await ingest_attachments(
        "read it",
        [{"name": "remote.pdf", "mime_type": "application/pdf", "url": "https://example.test/x.pdf"}],
        failure_mode="mark",
        mark_bytes_as_staged=True,
    )

    assert result.attachments == []
    assert result.failures[0].reason == "missing_data"
    assert "[attachment unavailable: remote.pdf: missing_data]" in result.text


@pytest.mark.asyncio
async def test_download_failure_raises_in_rpc_mode() -> None:
    with pytest.raises(ValueError, match="download_failed: boom"):
        await ingest_attachments(
            "read it",
            [{"name": "remote.pdf", "mime_type": "application/pdf", "_ingest_error": "boom"}],
            failure_mode="raise",
        )


@pytest.mark.asyncio
async def test_failure_marker_sanitizes_attachment_name() -> None:
    result = await ingest_attachments(
        "read it",
        [{"name": "bad\nname.pdf", "mime_type": "application/pdf", "_ingest_error": "boom"}],
        failure_mode="mark",
    )

    assert "[attachment unavailable: bad name.pdf: download_failed]" in result.text


_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _docx_bytes(paragraph: str = "Hello DOCX") -> bytes:
    import io

    from docx import Document

    document = Document()
    document.add_paragraph(paragraph)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_docx_bytes_sniffed_and_accepted() -> None:
    result = await ingest_attachments(
        "read it",
        [{"name": "report.docx", "mime_type": _DOCX_MIME, "data": _docx_bytes()}],
        failure_mode="mark",
    )

    assert result.failures == []
    assert len(result.attachments) == 1
    assert result.attachments[0]["type"] == _DOCX_MIME


@pytest.mark.asyncio
async def test_fake_docx_rejected_on_mime_mismatch() -> None:
    # A plain-text payload claiming to be a Word document must be fail-closed:
    # the bytes are not an OOXML zip, so the sniffer cannot confirm the claim.
    result = await ingest_attachments(
        "read it",
        [{"name": "fake.docx", "mime_type": _DOCX_MIME, "data": b"just text, not a zip"}],
        failure_mode="mark",
    )

    assert result.attachments == []
    assert result.failures[0].reason == "mime_mismatch"


_EML_MIME = "message/rfc822"
_MSG_MIME = "application/vnd.ms-outlook"


def _eml_bytes() -> bytes:
    from email.message import EmailMessage

    message = EmailMessage()
    message["From"] = "alice@example.com"
    message["To"] = "bob@example.com"
    message["Subject"] = "Hi"
    message["Date"] = "Mon, 01 Jan 2026 00:00:00 +0000"
    message.set_content("Body.")
    return message.as_bytes()


@pytest.mark.asyncio
async def test_eml_bytes_sniffed_and_accepted() -> None:
    result = await ingest_attachments(
        "read it",
        [{"name": "note.eml", "mime_type": _EML_MIME, "data": _eml_bytes()}],
        failure_mode="mark",
    )

    assert result.failures == []
    assert result.attachments[0]["type"] == _EML_MIME


@pytest.mark.asyncio
async def test_unknown_textual_upload_accepted_via_utf8_fallback() -> None:
    # An unsupported claimed mime whose bytes are clean UTF-8 text degrades to
    # text/plain instead of being rejected.
    result = await ingest_attachments(
        "read it",
        [
            {
                "name": "trace.log",
                "mime_type": "application/x-logfile",
                "data": b"line one\nline two\n",
            }
        ],
        failure_mode="mark",
    )

    assert result.failures == []
    assert result.attachments[0]["type"] == "text/plain"


@pytest.mark.asyncio
async def test_unknown_binary_upload_stays_rejected() -> None:
    # NUL bytes mark the payload as binary; the UTF-8 fallback must not fire.
    result = await ingest_attachments(
        "read it",
        [
            {
                "name": "blob.bin",
                "mime_type": "application/x-unknown",
                "data": b"\x00\x01\x02\x03binary",
            }
        ],
        failure_mode="mark",
    )

    assert result.attachments == []
    assert result.failures[0].reason == "unsupported_mime"


@pytest.mark.asyncio
async def test_unknown_text_head_with_binary_tail_rejected() -> None:
    # The head (peek window) is clean ASCII but the tail is binary. The fallback
    # validates the whole payload, so this must stay fail-closed.
    clean_head = b"a" * (SNIFF_PEEK_BYTES + 64)
    for tail in (b"\x00\x01\x02", b"\xff\xfe\xfd"):  # NUL tail, then invalid-UTF-8 tail
        result = await ingest_attachments(
            "read it",
            [
                {
                    "name": "sneaky.dat",
                    "mime_type": "application/x-unknown",
                    "data": clean_head + tail,
                }
            ],
            failure_mode="mark",
        )
        assert result.attachments == []
        assert result.failures[0].reason == "unsupported_mime"


@pytest.mark.asyncio
async def test_text_fallback_does_not_override_claimed_type() -> None:
    # CSV content sniffs as text/plain, but the weak fallback must not downgrade
    # the more specific claimed text/csv type.
    result = await ingest_attachments(
        "read it",
        [{"name": "data.csv", "mime_type": "text/csv", "data": b"a,b\n1,2\n"}],
        failure_mode="mark",
    )

    assert result.failures == []
    assert result.attachments[0]["type"] == "text/csv"


@pytest.mark.asyncio
async def test_plain_text_claiming_email_rejected() -> None:
    # Arbitrary text must not claim message/rfc822 to inherit the larger email
    # size ceiling instead of the 2MB text cap; without email structure it is
    # rejected rather than accepted under the email label.
    result = await ingest_attachments(
        "read it",
        [
            {
                "name": "notes.eml",
                "mime_type": _EML_MIME,
                "data": b"just some plain notes, definitely not an email\n",
            }
        ],
        failure_mode="mark",
    )

    assert result.attachments == []
    assert result.failures[0].reason == "mime_mismatch"


_MBOX_MIME = "application/mbox"


def _mbox_bytes() -> bytes:
    return b"From alice@example.com Mon Jan  1 00:00:00 2026\n" + _eml_bytes() + b"\n"


@pytest.mark.asyncio
async def test_prose_starting_with_from_claiming_mbox_rejected() -> None:
    # A bare "From " prefix is not an mbox: prose must not inherit the email cap.
    result = await ingest_attachments(
        "read it",
        [
            {
                "name": "story.mbox",
                "mime_type": _MBOX_MIME,
                "data": b"From the very start this was prose.\nStill prose here.\n",
            }
        ],
        failure_mode="mark",
    )

    assert result.attachments == []
    assert result.failures[0].reason == "mime_mismatch"


@pytest.mark.asyncio
async def test_real_mbox_sniffed_and_accepted() -> None:
    result = await ingest_attachments(
        "read it",
        [{"name": "inbox.mbox", "mime_type": _MBOX_MIME, "data": _mbox_bytes()}],
        failure_mode="mark",
    )

    assert result.failures == []
    assert result.attachments[0]["type"] == _MBOX_MIME


@pytest.mark.asyncio
async def test_fake_msg_rejected_on_mime_mismatch() -> None:
    result = await ingest_attachments(
        "read it",
        [{"name": "fake.msg", "mime_type": _MSG_MIME, "data": b"not an OLE compound file"}],
        failure_mode="mark",
    )

    assert result.attachments == []
    assert result.failures[0].reason == "mime_mismatch"
