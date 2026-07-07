from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from opensquilla.knowledge.chunking import extract_title


@dataclass(frozen=True)
class ParsedDocument:
    text: str
    title: str
    page_count: int | None
    parser: str
    status: str = "ready"
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def content_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_document(path: Path, *, strategy: str | None = None) -> ParsedDocument:
    suffix = path.suffix.lower()
    if strategy is None:
        strategy = _default_parser_strategy(suffix)
    if strategy in {"markdown_text_v1", "plain_text_v1"}:
        raw_text = path.read_text(encoding="utf-8", errors="replace")
        text, frontmatter_title, frontmatter = _strip_frontmatter(raw_text)
        return ParsedDocument(
            text=_normalize_text(text),
            title=frontmatter_title or extract_title(text, path.stem),
            page_count=None,
            parser=strategy,
            metadata={"frontmatter": frontmatter, "encoding": "utf-8"},
        )
    if strategy == "html_readability_v1":
        return _parse_html(path)
    if strategy == "pdf_text_v1":
        return _parse_pdf(path)
    raise ValueError(f"Unsupported knowledge parser strategy: {strategy}")


def parser_candidates_for_suffix(suffix: str) -> list[str]:
    suffix = suffix.lower()
    if suffix in {".md", ".markdown"}:
        return ["markdown_text_v1", "plain_text_v1"]
    if suffix == ".txt":
        return ["plain_text_v1"]
    if suffix in {".html", ".htm"}:
        return ["html_readability_v1", "plain_text_v1"]
    if suffix == ".pdf":
        return ["pdf_text_v1"]
    return []


def _default_parser_strategy(suffix: str) -> str:
    candidates = parser_candidates_for_suffix(suffix)
    if candidates:
        return candidates[0]
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
            text=_normalize_text(text),
            title=extract_title(text, path.stem),
            page_count=page_count,
            parser="pdf_text_v1",
            status="ready" if text else "low_text",
            metadata={"engine": "pdfplumber"},
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
                text=_normalize_text(text),
                title=extract_title(text, path.stem),
                page_count=len(reader.pages),
                parser="pdf_text_v1",
                status="ready" if text else "low_text",
                error=str(exc),
                metadata={"engine": "pypdf", "primary_error": str(exc)},
            )
        except Exception as fallback_exc:  # noqa: BLE001
            return ParsedDocument(
                text="",
                title=path.stem,
                page_count=None,
                parser="pdf_text_v1",
                status="error",
                error=f"{exc}; fallback: {fallback_exc}",
                metadata={"engine": "pdf", "primary_error": str(exc)},
            )


def _parse_html(path: Path) -> ParsedDocument:
    raw = path.read_text(encoding="utf-8", errors="replace")
    title = path.stem
    text = ""
    engine = "regex"
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(raw, "html.parser")
        if soup.title and soup.title.get_text(strip=True):
            title = soup.title.get_text(" ", strip=True)
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        main = soup.find("article") or soup.find("main") or soup.body or soup
        text = main.get_text("\n", strip=True)
        engine = "beautifulsoup"
    except Exception:
        text = _strip_html_tags(raw)
    text = _normalize_text(html.unescape(text))
    return ParsedDocument(
        text=text,
        title=extract_title(text, title),
        page_count=None,
        parser="html_readability_v1",
        status="ready" if text else "low_text",
        metadata={"engine": engine, "encoding": "utf-8"},
    )


def _strip_frontmatter(text: str) -> tuple[str, str | None, dict[str, str]]:
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return text, None, {}
    match = re.match(r"\A---\s*\n(?P<meta>.*?)\n---\s*(?:\n|$)(?P<body>.*)\Z", stripped, re.S)
    if not match:
        return text, None, {}
    meta = match.group("meta")
    parsed: dict[str, str] = {}
    for line in meta.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            parsed[key.strip()] = value.strip().strip("'\"")
    title = parsed.get("title") or None
    return match.group("body").lstrip(), title, parsed


def _strip_html_tags(text: str) -> str:
    without_scripts = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    return re.sub(r"(?s)<[^>]+>", " ", without_scripts)


def _normalize_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+\n", "\n", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()
