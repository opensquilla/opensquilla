"""Tests for the CLI ``/file`` command.

The ``/file`` command:

  - Accepts the broader allow-list (PDF, text-family, JSON, plus images).
  - Routes by size: <= 2 MB inlines as base64 (same shape as /image today).
  - > 2 MB uploads to /api/v1/files/upload via the gateway bridge and
    references the returned ``file_uuid`` in the chat.send payload.
  - Hard-fails with a clear, actionable error when the bridge is
    unreachable AND the file exceeds the inline cap.

These tests target the helper directly so the contract is locked
without requiring a live gateway. The hooks the helper accepts (an
``upload_callable`` parameter) make it trivial to inject a fake
bridge in tests.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pytest

from opensquilla.cli import chat_cmd
from opensquilla.cli.attachments import (
    CLI_IMAGE_ATTACHMENT_BYTES,
    CLI_INLINE_THRESHOLD_BYTES,
    CLI_STAGED_PDF_BYTES,
    CLI_TEXT_ATTACHMENT_BYTES,
)
from opensquilla.cli.chat_cmd import (
    _file_prompt_and_attachments,
    _image_prompt_and_attachments,
    _image_prompt_from_command,
)
from opensquilla.cli.repl import input_bridge


def _write(tmp_path: Path, name: str, payload: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(payload)
    return path


# ---------------------------------------------------------------------------
# Test 1 — small CSV inlines as base64.
# ---------------------------------------------------------------------------

def test_file_command_inline_for_small_csv(tmp_path: Path) -> None:
    csv_bytes = b"col_a,col_b\n1,2\n3,4\n"
    path = _write(tmp_path, "data.csv", csv_bytes)

    prompt, attachments = _file_prompt_and_attachments(
        f"/file {path} summarise this", upload_callable=None
    )
    assert prompt == "summarise this"
    assert len(attachments) == 1
    att = attachments[0]
    assert att["type"] == "text/csv"
    assert att["name"] == "data.csv"
    assert "data" in att and "file_uuid" not in att
    assert base64.b64decode(att["data"]) == csv_bytes


def test_file_command_parses_quoted_path_with_spaces(tmp_path: Path) -> None:
    csv_bytes = b"col_a,col_b\n1,2\n"
    path = _write(tmp_path, "data set.csv", csv_bytes)

    prompt, attachments = _file_prompt_and_attachments(
        f'/file "{path}" summarise this', upload_callable=None
    )

    assert prompt == "summarise this"
    assert attachments[0]["name"] == "data set.csv"
    assert attachments[0]["type"] == "text/csv"
    assert base64.b64decode(attachments[0]["data"]) == csv_bytes


def test_file_command_rejects_unclosed_quoted_path() -> None:
    with pytest.raises(ValueError, match=r"Usage: /file"):
        _file_prompt_and_attachments('/file "unterminated', upload_callable=None)


def test_image_command_parses_quoted_path_with_spaces(tmp_path: Path) -> None:
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"payload"
    path = _write(tmp_path, "screen shot.png", png_bytes)

    prompt, attachments = _image_prompt_and_attachments(f'/image "{path}" describe it')

    assert _image_prompt_from_command(f'/image "{path}" describe it') == "describe it"
    assert prompt == "describe it"
    assert attachments[0]["name"] == "screen shot.png"
    assert attachments[0]["type"] == "image/png"
    assert base64.b64decode(attachments[0]["data"]) == png_bytes


def test_image_command_reports_attachment_size(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"payload"
    path = _write(tmp_path, "screen shot.png", png_bytes)
    prints: list[str] = []

    class FakeConsole:
        def print(self, message: str) -> None:
            prints.append(message)

    monkeypatch.setattr(input_bridge, "console", FakeConsole())

    chat_cmd._image_prompt_and_attachments(f'/image "{path}" describe it')

    assert prints == ["[dim]Sending image: screen shot.png (0KB base64)[/dim]"]


# ---------------------------------------------------------------------------
# Test 2 — large PDF goes through the bridge upload callable.
# ---------------------------------------------------------------------------

def test_file_command_uses_bridge_for_large_pdf(tmp_path: Path) -> None:
    big_pdf = b"%PDF-1.4\n" + b"a" * (3 * 1024 * 1024)  # 3 MB > 2 MB threshold
    path = _write(tmp_path, "big.pdf", big_pdf)

    captured: dict[str, Any] = {}

    def fake_upload(local_path: Path, mime: str, name: str) -> str:
        captured["local_path"] = Path(local_path)
        captured["mime"] = mime
        captured["name"] = name
        return "u-fake-uuid-1234"

    prompt, attachments = _file_prompt_and_attachments(
        f"/file {path}", upload_callable=fake_upload
    )
    assert prompt  # default prompt assigned by the helper
    assert len(attachments) == 1
    att = attachments[0]
    assert att["type"] == "application/pdf"
    assert att["name"] == "big.pdf"
    assert att["file_uuid"] == "u-fake-uuid-1234"
    assert "data" not in att
    assert captured["local_path"] == path
    assert captured["mime"] == "application/pdf"


# ---------------------------------------------------------------------------
# Test 3 — bridge unreachable AND file > inline cap → hard-fail.
# ---------------------------------------------------------------------------

def test_file_command_hard_fails_when_bridge_unreachable_and_file_too_large(
    tmp_path: Path,
) -> None:
    big_pdf = b"%PDF-1.4\n" + b"a" * (3 * 1024 * 1024)
    path = _write(tmp_path, "big.pdf", big_pdf)

    def unreachable(local_path: Path, mime: str, name: str) -> str:
        raise ConnectionError("gateway upload endpoint unavailable: connection refused")

    with pytest.raises(ValueError, match=r"too large|gateway upload"):
        _file_prompt_and_attachments(f"/file {path}", upload_callable=unreachable)


def test_file_command_unreachable_bridge_falls_back_to_inline_for_small_file(
    tmp_path: Path,
) -> None:
    """When the bridge is unreachable but the file is below the inline cap,
    the helper still inlines the bytes — never silently truncates, never fails.
    """
    small_csv = b"a,b\n1,2\n"
    path = _write(tmp_path, "small.csv", small_csv)

    def unreachable(local_path: Path, mime: str, name: str) -> str:
        raise ConnectionError("would not be invoked for inline size")

    prompt, attachments = _file_prompt_and_attachments(
        f"/file {path} read", upload_callable=unreachable
    )
    assert prompt == "read"
    assert attachments[0]["type"] == "text/csv"
    assert "data" in attachments[0]


def test_file_command_rejects_unsupported_binary_mime(tmp_path: Path) -> None:
    # Unknown extension + binary content (NUL byte) stays fail-closed.
    path = _write(tmp_path, "x.bin", b"\x00\x01\x02\x03 binary blob")
    with pytest.raises(ValueError, match=r"(unsupported|not allowed|format)"):
        _file_prompt_and_attachments(f"/file {path}", upload_callable=None)


def test_file_command_accepts_unknown_utf8_text_as_plain(tmp_path: Path) -> None:
    # Unknown extension whose bytes are clean UTF-8 text is accepted as
    # text/plain, so the gateway's unknown-text fallback is reachable from the
    # CLI rather than rejected at the client.
    body = b"#!/bin/sh\necho hi\n"
    path = _write(tmp_path, "script.sh", body)

    prompt, attachments = _file_prompt_and_attachments(
        f"/file {path} run this", upload_callable=None
    )
    assert prompt == "run this"
    assert len(attachments) == 1
    att = attachments[0]
    assert att["type"] == "text/plain"
    assert att["name"] == "script.sh"
    assert base64.b64decode(att["data"]) == body


def test_file_command_rejects_large_text_family_before_upload(tmp_path: Path) -> None:
    path = _write(tmp_path, "large.csv", b"a" * (CLI_TEXT_ATTACHMENT_BYTES + 1))
    called = False

    def fake_upload(local_path: Path, mime: str, name: str) -> str:
        nonlocal called
        called = True
        return "u-should-not-upload"

    with pytest.raises(ValueError, match=r"text-family|/path|too large"):
        _file_prompt_and_attachments(f"/file {path}", upload_callable=fake_upload)

    assert called is False


def test_file_command_stages_large_image_within_image_cap(tmp_path: Path) -> None:
    payload = b"\x89PNG\r\n\x1a\n" + b"a" * CLI_INLINE_THRESHOLD_BYTES
    assert CLI_INLINE_THRESHOLD_BYTES < len(payload) <= CLI_IMAGE_ATTACHMENT_BYTES
    path = _write(tmp_path, "large.png", payload)
    captured: dict[str, Any] = {}

    def fake_upload(local_path: Path, mime: str, name: str) -> str:
        captured.update({"local_path": local_path, "mime": mime, "name": name})
        return "u-image"

    _prompt, attachments = _file_prompt_and_attachments(
        f"/file {path}",
        upload_callable=fake_upload,
    )

    assert attachments == [
        {"type": "image/png", "file_uuid": "u-image", "name": "large.png", "mime": "image/png"}
    ]
    assert captured["local_path"] == path
    assert captured["mime"] == "image/png"


def test_file_command_rejects_image_above_image_cap_before_upload(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "too-large.png",
        b"\x89PNG\r\n\x1a\n" + b"a" * CLI_IMAGE_ATTACHMENT_BYTES,
    )
    called = False

    def fake_upload(local_path: Path, mime: str, name: str) -> str:
        nonlocal called
        called = True
        return "u-should-not-upload"

    with pytest.raises(ValueError, match=r"image attachment limit|too large"):
        _file_prompt_and_attachments(f"/file {path}", upload_callable=fake_upload)

    assert called is False


def test_file_command_rejects_pdf_above_staged_cap_before_upload(tmp_path: Path) -> None:
    path = _write(tmp_path, "too-large.pdf", b"%PDF-1.4\n" + b"a" * CLI_STAGED_PDF_BYTES)
    called = False

    def fake_upload(local_path: Path, mime: str, name: str) -> str:
        nonlocal called
        called = True
        return "u-should-not-upload"

    with pytest.raises(ValueError, match=r"PDF limit|too large"):
        _file_prompt_and_attachments(f"/file {path}", upload_callable=fake_upload)

    assert called is False
