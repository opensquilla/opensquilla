"""Document parsers for Phase 1 local RAG."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(slots=True)
class ParsedDocument:
    text: str
    title: str | None
    parser: str
    metadata: dict[str, object] = field(default_factory=dict)


class DocumentParser(Protocol):
    name: str
    extensions: set[str]

    async def parse(self, path: Path, *, relative_path: str) -> ParsedDocument: ...


def _read_text(path: Path) -> tuple[str, dict[str, object]]:
    raw = path.read_bytes()
    metadata: dict[str, object] = {"encoding": "utf-8"}
    try:
        return raw.decode("utf-8"), metadata
    except UnicodeDecodeError:
        metadata["encodingWarning"] = True
        return raw.decode("utf-8", errors="replace"), metadata


def looks_binary(path: Path, *, sample_size: int = 4096) -> bool:
    sample = path.read_bytes()[:sample_size]
    if b"\x00" in sample:
        return True
    if not sample:
        return False
    control = sum(1 for byte in sample if byte < 9 or (13 < byte < 32))
    return control / max(1, len(sample)) > 0.20


class MarkdownParser:
    name = "markdown"
    extensions = {".md", ".markdown"}

    async def parse(self, path: Path, *, relative_path: str) -> ParsedDocument:
        text, metadata = _read_text(path)
        title: str | None = None
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                title = stripped[2:].strip() or None
                break
        if title is None:
            title = Path(relative_path).stem
        return ParsedDocument(text=text, title=title, parser=self.name, metadata=metadata)


class TextParser:
    name = "text"
    extensions = {".txt"}

    async def parse(self, path: Path, *, relative_path: str) -> ParsedDocument:
        text, metadata = _read_text(path)
        return ParsedDocument(
            text=text,
            title=Path(relative_path).stem,
            parser=self.name,
            metadata=metadata,
        )


class ParserRegistry:
    def __init__(self) -> None:
        self._parsers: list[DocumentParser] = [MarkdownParser(), TextParser()]

    def parser_for(self, extension: str) -> DocumentParser | None:
        lower = extension.lower()
        for parser in self._parsers:
            if lower in parser.extensions:
                return parser
        return None
