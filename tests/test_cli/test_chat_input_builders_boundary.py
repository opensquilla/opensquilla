from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pytest

from opensquilla.cli import chat_cmd, chat_input_builders


def test_chat_cmd_keeps_compatibility_aliases_for_input_builders() -> None:
    for name in (
        "_image_prompt_from_command",
        "_image_prompt_and_attachments",
        "_gateway_client_is_local",
        "_parse_path_command",
        "_path_strategy_hint",
        "_path_prompt_and_attachments",
        "_file_prompt_and_attachments",
        "_async_file_prompt_and_attachments",
    ):
        assert getattr(chat_cmd, name) is getattr(chat_input_builders, name)


def test_image_prompt_builder_preserves_payload_and_status_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    image = tmp_path / "sample.png"
    payload = b"\x89PNG\r\n\x1a\nsmall image"
    image.write_bytes(payload)

    prompt, attachments = chat_input_builders._image_prompt_and_attachments(
        f"/image {image} describe it"
    )

    assert prompt == "describe it"
    assert attachments == [
        {
            "type": "image/png",
            "data": base64.b64encode(payload).decode("ascii"),
            "name": "sample.png",
        }
    ]
    captured = capsys.readouterr()
    assert "Sending image: sample.png" in captured.out
    assert "KB base64" in captured.out


def test_gateway_client_local_detection_preserves_callable_and_attribute_semantics() -> None:
    class CallableLocal:
        def is_local_gateway(self) -> bool:
            return True

    class CallableTypeError:
        def is_local_gateway(self, unexpected: object) -> bool:
            raise AssertionError("should not be called with arguments")

    class AttributeRemote:
        is_local_gateway = False

    assert chat_input_builders._gateway_client_is_local(CallableLocal()) is True
    assert chat_input_builders._gateway_client_is_local(CallableTypeError()) is False
    assert chat_input_builders._gateway_client_is_local(AttributeRemote()) is False


def test_path_prompt_builder_preserves_no_upload_contract(tmp_path: Path) -> None:
    notes = tmp_path / "notes.md"
    notes.write_text("# Notes\n", encoding="utf-8")

    prompt, attachments = chat_input_builders._path_prompt_and_attachments(
        f"/path {notes} summarize"
    )

    assert "summarize" in prompt
    assert str(notes.resolve(strict=False)) in prompt
    assert "The CLI did not upload or attach file bytes" in prompt
    assert attachments == []


@pytest.mark.asyncio
async def test_async_file_prompt_builder_preserves_upload_behavior(tmp_path: Path) -> None:
    pdf = tmp_path / "large.pdf"
    pdf.write_bytes(b"%PDF-1.4\n" + b"x" * (3 * 1024 * 1024))
    captured: dict[str, Any] = {}

    async def upload(path: Path, mime: str, name: str) -> str:
        captured.update({"path": path, "mime": mime, "name": name})
        return "u-boundary"

    prompt, attachments = await chat_input_builders._async_file_prompt_and_attachments(
        f"/file {pdf} inspect",
        upload_callable=upload,
    )

    assert prompt == "inspect"
    assert attachments == [
        {
            "type": "application/pdf",
            "file_uuid": "u-boundary",
            "name": "large.pdf",
            "mime": "application/pdf",
        }
    ]
    assert captured == {
        "path": pdf,
        "mime": "application/pdf",
        "name": "large.pdf",
    }
