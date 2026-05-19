from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from opensquilla.cli import attachment_paths


def test_attachment_paths_owns_public_path_symbols() -> None:
    expected_names = (
        "PATH_REMOTE_GATEWAY_MESSAGE",
        "PATH_TEXT_EXTENSIONS",
        "PATH_SPREADSHEET_EXTENSIONS",
        "PATH_IMAGE_BINARY_EXTENSIONS",
        "PATH_OBVIOUS_BINARY_EXTENSIONS",
        "parse_path_command",
        "path_strategy_hint",
        "path_prompt_and_attachments",
    )

    for name in expected_names:
        assert hasattr(attachment_paths, name)

    assert attachment_paths.PATH_REMOTE_GATEWAY_MESSAGE == (
        "Use /file to upload from this CLI machine"
    )
    assert attachment_paths.PATH_TEXT_EXTENSIONS == {
        ".txt",
        ".log",
        ".md",
        ".markdown",
        ".json",
        ".html",
        ".htm",
    }
    assert attachment_paths.PATH_SPREADSHEET_EXTENSIONS == {".csv", ".tsv", ".xlsx"}
    assert ".png" in attachment_paths.PATH_IMAGE_BINARY_EXTENSIONS
    assert attachment_paths.PATH_IMAGE_BINARY_EXTENSIONS <= (
        attachment_paths.PATH_OBVIOUS_BINARY_EXTENSIONS
    )
    assert attachment_paths.parse_path_command.__module__ == (
        "opensquilla.cli.attachment_paths"
    )
    assert attachment_paths.path_strategy_hint.__module__ == (
        "opensquilla.cli.attachment_paths"
    )
    assert attachment_paths.path_prompt_and_attachments.__module__ == (
        "opensquilla.cli.attachment_paths"
    )


def test_parse_path_command_accepts_quoted_paths_with_prompt(tmp_path: Path) -> None:
    target = tmp_path / "file with spaces.md"
    target.write_text("# Notes\n", encoding="utf-8")

    path, prompt = attachment_paths.parse_path_command(
        f"/path '{target}' summarize this"
    )

    assert path == target
    assert prompt == "summarize this"


def test_parse_path_command_keeps_existing_unquoted_paths_with_spaces(
    tmp_path: Path,
) -> None:
    target = tmp_path / "file with spaces.log"
    target.write_text("hello\n", encoding="utf-8")

    path, prompt = attachment_paths.parse_path_command(f"/path {target} inspect it")

    assert path == target
    assert prompt == "inspect it"


@pytest.mark.parametrize("unsafe", ["<", ">", "\n", "\r"])
def test_parse_path_command_rejects_unsafe_path_tokens(unsafe: str) -> None:
    with pytest.raises(
        ValueError,
        match="Invalid /path path token: '<', '>', CR, and LF are not allowed.",
    ):
        attachment_paths.parse_path_command(f"/path bad{unsafe}name")


def test_path_prompt_and_attachments_preserves_no_upload_prompt_shape(
    tmp_path: Path,
) -> None:
    notes = tmp_path / "notes.md"
    notes.write_text("# Notes\n", encoding="utf-8")

    prompt, attachments = attachment_paths.path_prompt_and_attachments(
        f"/path {notes} summarize"
    )

    absolute = notes.resolve(strict=False)
    assert prompt == (
        "summarize\n\n"
        "Local path analysis request (no upload):\n"
        f"- Path: {absolute}\n"
        "- The CLI did not upload or attach file bytes; attachments=[] for this turn.\n"
        "- The path string above is sent in this chat prompt and may be stored in the "
        "conversation transcript.\n"
        "- Use local filesystem tools on this same machine only; prefer bounded reads "
        "for large files.\n"
        "- Suggested strategy: This looks like a text/log/markdown/json/html file. "
        "Use read_file(path=..., offset=..., limit=...) for bounded windows and "
        "grep_search(pattern=..., path=...) to find relevant lines."
    )
    assert attachments == []


def test_path_prompt_and_attachments_defaults_to_analyze_this_local_path(
    tmp_path: Path,
) -> None:
    notes = tmp_path / "notes.md"
    notes.write_text("# Notes\n", encoding="utf-8")

    prompt, attachments = attachment_paths.path_prompt_and_attachments(f"/path {notes}")

    assert prompt.startswith("Analyze this local path.\n\n")
    assert "attachments=[]" in prompt
    assert attachments == []


def test_path_strategy_directory_uses_local_listing_and_search(tmp_path: Path) -> None:
    hint = attachment_paths.path_strategy_hint(tmp_path)

    assert hint == (
        "This is a directory. Start with list_dir(path=...), then use "
        "glob_search(pattern=..., path=...) and grep_search(pattern=..., path=...) "
        "to inspect relevant files without uploading bytes."
    )


@pytest.mark.parametrize("suffix", [".csv", ".tsv", ".xlsx"])
def test_path_strategy_spreadsheet_uses_bounded_spreadsheet_reads(
    tmp_path: Path,
    suffix: str,
) -> None:
    spreadsheet = tmp_path / f"data{suffix}"
    spreadsheet.write_bytes(b"a,b\n1,2\n")

    assert attachment_paths.path_strategy_hint(spreadsheet) == (
        "This looks like a spreadsheet. Use read_spreadsheet(path=..., offset=..., "
        "limit=...) to inspect bounded rows."
    )


@pytest.mark.parametrize("suffix", [".txt", ".log", ".md", ".json", ".html", ".htm"])
def test_path_strategy_text_uses_bounded_file_reads(
    tmp_path: Path,
    suffix: str,
) -> None:
    text_file = tmp_path / f"notes{suffix}"
    text_file.write_text("hello\n", encoding="utf-8")

    assert attachment_paths.path_strategy_hint(text_file) == (
        "This looks like a text/log/markdown/json/html file. Use read_file(path=..., "
        "offset=..., limit=...) for bounded windows and grep_search(pattern=..., path=...) "
        "to find relevant lines."
    )


def test_path_strategy_unknown_text_uses_utf8_compatible_fallback(
    tmp_path: Path,
) -> None:
    target = tmp_path / "README"
    target.write_text("hello\n", encoding="utf-8")

    assert attachment_paths.path_strategy_hint(target) == (
        "This appears to be a local UTF-8-compatible file. Use read_file(path=..., "
        "offset=..., limit=...) for bounded windows and grep_search(pattern=..., path=...) "
        "for targeted search; if a tool reports binary content, stop and ask the user to use /file."
    )


def test_path_strategy_pdf_rejects_with_file_guidance(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    with pytest.raises(
        ValueError,
        match=r"PDF path analysis is not supported by /path\. Use /file <path> instead\.",
    ):
        attachment_paths.path_strategy_hint(pdf)


@pytest.mark.parametrize("suffix", [".zip", ".exe", ".png"])
def test_path_strategy_obvious_binary_rejects_with_file_guidance(
    tmp_path: Path,
    suffix: str,
) -> None:
    payload = tmp_path / f"payload{suffix}"
    payload.write_bytes(b"binary")

    with pytest.raises(ValueError) as exc_info:
        attachment_paths.path_strategy_hint(payload)

    assert str(exc_info.value) == (
        f"{payload.name} looks like a binary/container file and is not suitable for /path. "
        "Use /file if upload is intended."
    )


def test_path_strategy_binary_nul_sample_rejects_with_file_guidance(
    tmp_path: Path,
) -> None:
    payload = tmp_path / "payload.custom"
    payload.write_bytes(b"abc\x00def")

    with pytest.raises(ValueError) as exc_info:
        attachment_paths.path_strategy_hint(payload)

    assert str(exc_info.value) == (
        f"{payload.name} appears to contain binary NUL bytes and is not suitable for /path. "
        "Use /file if upload is intended."
    )


def test_path_prompt_and_attachments_returns_empty_dict_attachment_list_type(
    tmp_path: Path,
) -> None:
    notes = tmp_path / "notes.md"
    notes.write_text("# Notes\n", encoding="utf-8")

    _: tuple[str, list[dict[str, Any]]] = (
        attachment_paths.path_prompt_and_attachments(f"/path {notes}")
    )
