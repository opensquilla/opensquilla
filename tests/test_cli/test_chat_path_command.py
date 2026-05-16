from __future__ import annotations

from pathlib import Path

import pytest

from opensquilla.cli.chat_cmd import (
    _parse_path_command,
    _path_prompt_and_attachments,
    _path_strategy_hint,
)
from opensquilla.cli.repl.commands import REGISTRY
from opensquilla.commands import DEFAULT_REGISTRY, Surface


def test_path_command_parses_quoted_path_with_prompt(tmp_path: Path) -> None:
    target = tmp_path / "file with spaces.log"
    target.write_text("hello\n", encoding="utf-8")

    prompt, attachments = _path_prompt_and_attachments(
        f'/path "{target}" summarize errors'
    )

    assert str(target.resolve(strict=False)) in prompt
    assert "summarize errors" in prompt
    assert "attachments=[]" in prompt
    assert attachments == []


def test_path_command_parses_unquoted_existing_path_with_spaces(tmp_path: Path) -> None:
    target = tmp_path / "file with spaces.log"
    target.write_text("hello\n", encoding="utf-8")

    path, trailing_prompt = _parse_path_command(f"/path {target} inspect it")

    assert path == target
    assert trailing_prompt == "inspect it"


@pytest.mark.parametrize("unsafe", ["<", ">", "\n", "\r"])
def test_path_command_rejects_unsafe_path_token(unsafe: str) -> None:
    with pytest.raises(ValueError, match="not allowed|Invalid"):
        _path_prompt_and_attachments(f"/path bad{unsafe}name")


@pytest.mark.parametrize("command", ["/path", '/path "unterminated'])
def test_path_command_rejects_missing_or_unclosed_quote(command: str) -> None:
    with pytest.raises(ValueError, match="Usage"):
        _path_prompt_and_attachments(command)


def test_path_command_default_prompt_mentions_no_upload(tmp_path: Path) -> None:
    target = tmp_path / "notes.md"
    target.write_text("# Notes\n", encoding="utf-8")

    prompt, attachments = _path_prompt_and_attachments(f"/path {target}")

    assert "Analyze this local path" in prompt
    assert "did not upload or attach file bytes" in prompt
    assert "path string" in prompt
    assert str(target.resolve(strict=False)) in prompt
    assert attachments == []


def test_path_strategy_directory_uses_list_and_search(tmp_path: Path) -> None:
    hint = _path_strategy_hint(tmp_path)
    assert "list_dir" in hint
    assert "glob_search" in hint
    assert "grep_search" in hint


@pytest.mark.parametrize("suffix", [".csv", ".tsv", ".xlsx"])
def test_path_strategy_spreadsheet_uses_read_spreadsheet(
    tmp_path: Path,
    suffix: str,
) -> None:
    target = tmp_path / f"data{suffix}"
    target.write_bytes(b"a,b\n1,2\n")
    assert "read_spreadsheet" in _path_strategy_hint(target)


@pytest.mark.parametrize("suffix", [".txt", ".log", ".md", ".json", ".html"])
def test_path_strategy_text_uses_read_file_or_grep(tmp_path: Path, suffix: str) -> None:
    target = tmp_path / f"data{suffix}"
    target.write_text("hello\n", encoding="utf-8")
    hint = _path_strategy_hint(target)
    assert "read_file" in hint
    assert "grep_search" in hint


def test_path_strategy_pdf_rejects_with_file_guidance(tmp_path: Path) -> None:
    target = tmp_path / "paper.pdf"
    target.write_bytes(b"%PDF-1.4\n")
    with pytest.raises(ValueError, match="/file"):
        _path_strategy_hint(target)


@pytest.mark.parametrize("suffix", [".zip", ".exe"])
def test_path_strategy_obvious_binary_rejects(tmp_path: Path, suffix: str) -> None:
    target = tmp_path / f"payload{suffix}"
    target.write_bytes(b"binary")
    with pytest.raises(ValueError, match="not suitable"):
        _path_strategy_hint(target)


def test_path_strategy_nul_sample_rejects(tmp_path: Path) -> None:
    target = tmp_path / "payload.txt"
    target.write_bytes(b"abc\x00def")
    with pytest.raises(ValueError, match="NUL|not suitable"):
        _path_strategy_hint(target)


def test_tui_help_includes_path_command() -> None:
    commands = DEFAULT_REGISTRY.for_surface(Surface.TUI)
    path_command = next(cmd for cmd in commands if cmd.name == "/path")

    assert path_command.usage == "/path <path> [prompt]"
    assert "without uploading bytes" in path_command.description
    assert any(command.usage == "/path <path> [prompt]" for command in REGISTRY)
