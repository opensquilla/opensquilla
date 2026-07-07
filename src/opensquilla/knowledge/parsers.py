from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from opensquilla.knowledge.chunking import extract_title


@dataclass(frozen=True)
class ParsedDocument:
    text: str
    title: str
    page_count: int | None
    parser: str
    status: str = "ready"
    error: str | None = None


def content_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_document(path: Path) -> ParsedDocument:
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown", ".txt"}:
        raw_text = path.read_text(encoding="utf-8", errors="replace")
        text, frontmatter_title = _strip_frontmatter(raw_text)
        return ParsedDocument(
            text=text,
            title=frontmatter_title or extract_title(text, path.stem),
            page_count=None,
            parser="text",
        )
    if suffix == ".pdf":
        return _parse_pdf(path)
    raise ValueError(f"Unsupported knowledge file type: {suffix or '<none>'}")


def _parse_pdf(path: Path) -> ParsedDocument:
    try:
        import pdfplumber

        pages: list[str] = []
        with pdfplumber.open(path) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                page_text = page.extract_text() or ""
                if page_text.strip():
                    pages.append(f"\n\n[page {page_number}]\n{page_text.strip()}")
            text = "\n".join(pages).strip()
            page_count = len(pdf.pages)
        return ParsedDocument(
            text=text,
            title=extract_title(text, path.stem),
            page_count=page_count,
            parser="pdfplumber",
            status="ready" if text else "low_text",
        )
    except Exception as exc:  # noqa: BLE001 - parser diagnostics should preserve failure
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            pages = []
            for page_number, page in enumerate(reader.pages, start=1):
                page_text = page.extract_text() or ""
                if page_text.strip():
                    pages.append(f"\n\n[page {page_number}]\n{page_text.strip()}")
            text = "\n".join(pages).strip()
            return ParsedDocument(
                text=text,
                title=extract_title(text, path.stem),
                page_count=len(reader.pages),
                parser="pypdf",
                status="ready" if text else "low_text",
                error=str(exc),
            )
        except Exception as fallback_exc:  # noqa: BLE001
            return ParsedDocument(
                text="",
                title=path.stem,
                page_count=None,
                parser="pdf",
                status="error",
                error=f"{exc}; fallback: {fallback_exc}",
            )


def _strip_frontmatter(text: str) -> tuple[str, str | None]:
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return text, None
    match = re.match(r"\A---\s*\n(?P<meta>.*?)\n---\s*(?:\n|$)(?P<body>.*)\Z", stripped, re.S)
    if not match:
        return text, None
    meta = match.group("meta")
    title = None
    for line in meta.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip().lower() == "title":
            title = value.strip().strip("'\"") or None
            break
    return match.group("body").lstrip(), title
