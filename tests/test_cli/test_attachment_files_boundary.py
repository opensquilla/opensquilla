from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pytest

from opensquilla.cli import attachment_files


def _write(tmp_path: Path, name: str, payload: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(payload)
    return path


def test_attachment_files_exports_file_and_image_boundary_symbols() -> None:
    expected = {
        "CLI_INLINE_THRESHOLD_BYTES",
        "CLI_TEXT_ATTACHMENT_BYTES",
        "CLI_IMAGE_ATTACHMENT_BYTES",
        "CLI_ENGINE_ATTACHMENT_BYTES",
        "CLI_STAGED_PDF_BYTES",
        "CLI_IMAGE_MIMES",
        "CLI_ALLOWED_FILE_MIMES",
        "CLI_TEXT_FAMILY_MIMES",
        "UploadCallable",
        "AsyncUploadCallable",
        "attachment_size_limit_for_mime",
        "mime_for_path",
        "build_file_attachment",
        "build_file_attachment_async",
        "file_prompt_and_attachments",
        "async_file_prompt_and_attachments",
        "attachments_from_paths",
        "image_prompt_from_command",
        "image_prompt_and_attachments",
    }

    assert expected <= set(attachment_files.__all__)
    for name in expected:
        assert hasattr(attachment_files, name)

    for name in (
        "attachment_size_limit_for_mime",
        "mime_for_path",
        "build_file_attachment",
        "build_file_attachment_async",
        "file_prompt_and_attachments",
        "async_file_prompt_and_attachments",
        "attachments_from_paths",
        "image_prompt_from_command",
        "image_prompt_and_attachments",
    ):
        assert getattr(attachment_files, name).__module__ == "opensquilla.cli.attachment_files"


def test_file_prompt_inlines_small_csv_payload(tmp_path: Path) -> None:
    csv_bytes = b"col_a,col_b\n1,2\n3,4\n"
    path = _write(tmp_path, "data.csv", csv_bytes)

    prompt, attachments = attachment_files.file_prompt_and_attachments(
        f"/file {path} summarise this",
        upload_callable=None,
    )

    assert prompt == "summarise this"
    assert attachments == [
        {
            "type": "text/csv",
            "data": base64.b64encode(csv_bytes).decode("ascii"),
            "name": "data.csv",
        }
    ]


def test_large_pdf_uses_sync_bridge_upload_payload(tmp_path: Path) -> None:
    big_pdf = b"%PDF-1.4\n" + b"a" * (3 * 1024 * 1024)
    path = _write(tmp_path, "big.pdf", big_pdf)
    captured: dict[str, Any] = {}

    def fake_upload(local_path: Path, mime: str, name: str) -> str:
        captured.update({"local_path": local_path, "mime": mime, "name": name})
        return "u-fake-uuid-1234"

    prompt, attachments = attachment_files.file_prompt_and_attachments(
        f"/file {path}",
        upload_callable=fake_upload,
    )

    assert prompt == "Read this file"
    assert attachments == [
        {
            "type": "application/pdf",
            "file_uuid": "u-fake-uuid-1234",
            "name": "big.pdf",
            "mime": "application/pdf",
        }
    ]
    assert captured == {
        "local_path": path,
        "mime": "application/pdf",
        "name": "big.pdf",
    }


@pytest.mark.asyncio
async def test_large_pdf_uses_async_bridge_upload_payload(tmp_path: Path) -> None:
    big_pdf = b"%PDF-1.4\n" + b"a" * (3 * 1024 * 1024)
    path = _write(tmp_path, "big.pdf", big_pdf)
    captured: dict[str, Any] = {}

    async def fake_upload(local_path: Path, mime: str, name: str) -> str:
        captured.update({"local_path": local_path, "mime": mime, "name": name})
        return "u-async-uuid"

    prompt, attachments = await attachment_files.async_file_prompt_and_attachments(
        f"/file {path} inspect",
        upload_callable=fake_upload,
    )

    assert prompt == "inspect"
    assert attachments == [
        {
            "type": "application/pdf",
            "file_uuid": "u-async-uuid",
            "name": "big.pdf",
            "mime": "application/pdf",
        }
    ]
    assert captured == {
        "local_path": path,
        "mime": "application/pdf",
        "name": "big.pdf",
    }


def test_text_family_above_inline_limit_is_not_staged(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "large.csv",
        b"a" * (attachment_files.CLI_TEXT_ATTACHMENT_BYTES + 1),
    )
    called = False

    def fake_upload(local_path: Path, mime: str, name: str) -> str:
        nonlocal called
        called = True
        return "u-should-not-upload"

    with pytest.raises(ValueError, match=r"text-family|/path|too large"):
        attachment_files.file_prompt_and_attachments(
            f"/file {path}",
            upload_callable=fake_upload,
        )

    assert called is False


def test_image_prompt_payload_and_prompt_defaults(tmp_path: Path) -> None:
    image_bytes = b"\x89PNG\r\n\x1a\nsmall image"
    path = _write(tmp_path, "sample.png", image_bytes)

    prompt, attachments = attachment_files.image_prompt_and_attachments(f"/image {path}")

    assert prompt == "Describe this image"
    assert attachments == [
        {
            "type": "image/png",
            "data": base64.b64encode(image_bytes).decode("ascii"),
            "name": "sample.png",
        }
    ]
    assert attachment_files.image_prompt_from_command(f"/image {path} describe it") == (
        "describe it"
    )


def test_image_command_rejects_unsupported_format_with_existing_text(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path, "sample.bmp", b"BMnot supported")

    with pytest.raises(ValueError, match=r"Unsupported format: bmp. Use png/jpg/gif/webp"):
        attachment_files.image_prompt_and_attachments(f"/image {path}")
