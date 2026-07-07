from __future__ import annotations

from pathlib import Path

from opensquilla.knowledge.parsers import parse_document


def test_parse_markdown_strips_frontmatter_and_uses_title(tmp_path: Path) -> None:
    path = tmp_path / "report.md"
    path.write_text(
        "---\n"
        "date: 2026-06-21\n"
        "source: ace-camp\n"
        "title: MLCC村田太阳诱电观点更新\n"
        "---\n\n"
        "# 正文标题\n\n"
        "村田太阳诱电的扩产节奏需要结合需求判断。",
        encoding="utf-8",
    )

    parsed = parse_document(path)

    assert parsed.title == "MLCC村田太阳诱电观点更新"
    assert not parsed.text.startswith("---")
    assert "村田太阳诱电" in parsed.text
