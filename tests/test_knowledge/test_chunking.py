from __future__ import annotations

from opensquilla.knowledge.chunking import chunk_text, detect_language_bucket


def test_detect_language_bucket_handles_zh_en_and_mixed() -> None:
    assert detect_language_bucket("这是一个中文研报，讨论算力和光模块。") == "zh"
    assert detect_language_bucket("This report discusses AI infrastructure demand.") == "en"
    assert detect_language_bucket("AI 算力 demand continues to rise.") == "mixed"


def test_chunk_text_preserves_metadata_and_boundaries() -> None:
    text = "\n\n".join(
        [
            "# Section A",
            "康宁公司的 AI 基建玻璃材料需求正在提升。" * 12,
            "## Section B",
            "光通信产业链的资本开支和库存周期需要分开判断。" * 12,
        ]
    )

    chunks = chunk_text(
        text,
        doc_id="doc-1",
        title="康宁公司深度报告",
        source_path="ace-camp/report.md",
        source="ace-camp",
        page_start=1,
        target_chars=220,
        overlap_chars=30,
    )

    assert len(chunks) >= 2
    assert chunks[0].doc_id == "doc-1"
    assert chunks[0].chunk_id == "doc-1:0000"
    assert chunks[0].title == "康宁公司深度报告"
    assert chunks[0].source == "ace-camp"
    assert chunks[0].source_path == "ace-camp/report.md"
    assert chunks[0].text
    assert chunks[0].language_bucket in {"zh", "mixed"}
    assert chunks[-1].ordinal == len(chunks) - 1
