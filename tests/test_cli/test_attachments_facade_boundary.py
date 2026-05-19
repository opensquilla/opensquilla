from __future__ import annotations

import ast
from pathlib import Path

from opensquilla.cli import attachment_files, attachment_paths, attachments

ROOT = Path(__file__).resolve().parents[2]
ATTACHMENTS = ROOT / "src" / "opensquilla" / "cli" / "attachments.py"

FILE_SYMBOLS = {
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

PATH_SYMBOLS = {
    "PATH_REMOTE_GATEWAY_MESSAGE",
    "PATH_TEXT_EXTENSIONS",
    "PATH_SPREADSHEET_EXTENSIONS",
    "PATH_IMAGE_BINARY_EXTENSIONS",
    "PATH_OBVIOUS_BINARY_EXTENSIONS",
    "parse_path_command",
    "path_strategy_hint",
    "path_prompt_and_attachments",
}


def _module_tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _top_level_symbols(path: Path) -> set[str]:
    tree = _module_tree(path)
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _imports_from_module(path: Path, module_name: str) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(_module_tree(path)):
        if isinstance(node, ast.ImportFrom) and node.module == module_name:
            imported.update(alias.name for alias in node.names)
    return imported


def test_attachments_facade_reexports_file_helper_aliases() -> None:
    assert FILE_SYMBOLS <= _imports_from_module(
        ATTACHMENTS,
        "opensquilla.cli.attachment_files",
    )
    assert FILE_SYMBOLS.isdisjoint(_top_level_symbols(ATTACHMENTS))

    for symbol in FILE_SYMBOLS:
        assert getattr(attachments, symbol) is getattr(attachment_files, symbol)


def test_attachments_facade_reexports_path_helper_aliases() -> None:
    assert PATH_SYMBOLS <= _imports_from_module(
        ATTACHMENTS,
        "opensquilla.cli.attachment_paths",
    )
    assert PATH_SYMBOLS.isdisjoint(_top_level_symbols(ATTACHMENTS))

    for symbol in PATH_SYMBOLS:
        assert getattr(attachments, symbol) is getattr(attachment_paths, symbol)
