"""CLI helpers for local /path analysis commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

PATH_REMOTE_GATEWAY_MESSAGE = "Use /file to upload from this CLI machine"
PATH_TEXT_EXTENSIONS = {
    ".txt",
    ".log",
    ".md",
    ".markdown",
    ".json",
    ".html",
    ".htm",
}
PATH_SPREADSHEET_EXTENSIONS = {".csv", ".tsv", ".xlsx"}
PATH_IMAGE_BINARY_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".ico",
    ".tiff",
    ".tif",
}
PATH_OBVIOUS_BINARY_EXTENSIONS = {
    ".7z",
    ".bin",
    ".bz2",
    ".dll",
    ".dmg",
    ".doc",
    ".docx",
    ".dylib",
    ".exe",
    ".gz",
    ".msi",
    ".ppt",
    ".pptx",
    ".rar",
    ".so",
    ".tar",
    ".xls",
    ".zip",
    *PATH_IMAGE_BINARY_EXTENSIONS,
}


def parse_path_command(command: str) -> tuple[Path, str]:
    rest = command[len("/path") :].strip()
    if not rest:
        raise ValueError("Usage: /path <path> [prompt]")
    if "\r" in rest or "\n" in rest:
        raise ValueError("Invalid /path path token: '<', '>', CR, and LF are not allowed.")

    if rest[0] in {'"', "'"}:
        quote = rest[0]
        end = rest.find(quote, 1)
        if end == -1:
            raise ValueError("Usage: /path <path> [prompt] (unclosed quote)")
        token = rest[1:end]
        prompt = rest[end + 1 :].strip()
    else:
        words = rest.split()
        token = ""
        prompt = ""
        for count in range(len(words), 0, -1):
            candidate = " ".join(words[:count])
            if Path(candidate).expanduser().exists():
                token = candidate
                prompt = " ".join(words[count:]).strip()
                break
        if not token:
            token = words[0]
            prompt = rest[len(token) :].strip()

    if not token:
        raise ValueError("Usage: /path <path> [prompt]")
    if any(ch in token for ch in ("<", ">", "\r", "\n")):
        raise ValueError("Invalid /path path token: '<', '>', CR, and LF are not allowed.")
    return Path(token).expanduser(), prompt


def path_strategy_hint(path: Path) -> str:
    if not path.exists():
        raise ValueError(f"File not found: {path}")
    if path.is_dir():
        return (
            "This is a directory. Start with list_dir(path=...), then use "
            "glob_search(pattern=..., path=...) and grep_search(pattern=..., path=...) "
            "to inspect relevant files without uploading bytes."
        )

    ext = path.suffix.lower()
    if ext == ".pdf":
        raise ValueError("PDF path analysis is not supported by /path. Use /file <path> instead.")
    if ext in PATH_SPREADSHEET_EXTENSIONS:
        return (
            "This looks like a spreadsheet. Use read_spreadsheet(path=..., offset=..., "
            "limit=...) to inspect bounded rows."
        )
    if ext in PATH_OBVIOUS_BINARY_EXTENSIONS:
        raise ValueError(
            f"{path.name} looks like a binary/container file and is not suitable for /path. "
            "Use /file if upload is intended."
        )

    try:
        with path.open("rb") as fh:
            sample = fh.read(8192)
    except OSError as exc:
        raise ValueError(f"Cannot inspect path: {path} ({exc})") from exc
    if b"\x00" in sample:
        raise ValueError(
            f"{path.name} appears to contain binary NUL bytes and is not suitable for /path. "
            "Use /file if upload is intended."
        )

    if ext in PATH_TEXT_EXTENSIONS:
        return (
            "This looks like a text/log/markdown/json/html file. Use read_file(path=..., "
            "offset=..., limit=...) for bounded windows and grep_search(pattern=..., path=...) "
            "to find relevant lines."
        )
    return (
        "This appears to be a local UTF-8-compatible file. Use read_file(path=..., "
        "offset=..., limit=...) for bounded windows and grep_search(pattern=..., path=...) "
        "for targeted search; if a tool reports binary content, stop and ask the user to use /file."
    )


def path_prompt_and_attachments(command: str) -> tuple[str, list[dict[str, Any]]]:
    path, user_prompt = parse_path_command(command)
    absolute = path.resolve(strict=False)
    strategy = path_strategy_hint(absolute)
    prompt = user_prompt or "Analyze this local path."
    full_prompt = (
        f"{prompt}\n\n"
        "Local path analysis request (no upload):\n"
        f"- Path: {absolute}\n"
        "- The CLI did not upload or attach file bytes; attachments=[] for this turn.\n"
        "- The path string above is sent in this chat prompt and may be stored in the "
        "conversation transcript.\n"
        "- Use local filesystem tools on this same machine only; prefer bounded reads "
        "for large files.\n"
        f"- Suggested strategy: {strategy}"
    )
    return full_prompt, []
