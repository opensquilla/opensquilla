from __future__ import annotations

from pathlib import Path

from opensquilla.knowledge.index import KnowledgeIndex
from opensquilla.knowledge.models import KnowledgeChunk, KnowledgeDocument


def _doc(doc_id: str, title: str, source: str = "sample") -> KnowledgeDocument:
    return KnowledgeDocument(
        doc_id=doc_id,
        title=title,
        source=source,
        source_path=f"{source}/{title}.md",
        file_type=".md",
        content_kind="report",
        date="2026-06-20",
        language_bucket="zh",
    )


def _chunk(doc_id: str, ordinal: int, text: str) -> KnowledgeChunk:
    return KnowledgeChunk(
        chunk_id=f"{doc_id}:{ordinal:04d}",
        doc_id=doc_id,
        ordinal=ordinal,
        text=text,
        title=f"title-{doc_id}",
        source="sample",
        source_path=f"sample/{doc_id}.md",
        page_start=1,
        page_end=1,
        language_bucket="zh",
    )


def test_knowledge_index_searches_chinese_terms_and_metadata(tmp_path: Path) -> None:
    index = KnowledgeIndex(tmp_path / "knowledge.db")
    index.initialize()
    index.reset()
    index.add_documents(
        [_doc("doc-ai-glass", "康宁公司 AI 玻璃材料"), _doc("doc-battery", "电池产业链")],
        [
            _chunk("doc-ai-glass", 0, "康宁公司的 AI 基建玻璃材料需求正在提升，光通信链条受益。"),
            _chunk("doc-battery", 0, "动力电池产业链库存仍处于去化阶段。"),
        ],
    )

    results = index.search("康宁 AI 玻璃材料", top_k=3)

    assert results
    assert results[0].document_id == "doc-ai-glass"
    assert results[0].chunk_id == "doc-ai-glass:0000"
    assert "康宁" in results[0].snippet
    assert results[0].citation.endswith("#page=1")
    assert results[0].rank_position == 1
    assert results[0].bm25_rank is not None
    assert results[0].score == round(max(-results[0].bm25_rank, 0.0), 4)


def test_knowledge_index_dedupes_repeated_chunk_text(tmp_path: Path) -> None:
    index = KnowledgeIndex(tmp_path / "knowledge.db")
    index.initialize()
    index.reset()
    docs = [
        _doc("doc-pricing-a", "月专业版三档定价"),
        _doc("doc-pricing-b", "月专业版三档定价 副本"),
        _doc("doc-pricing-c", "续费策略"),
    ]
    duplicate_body = "月专业版三档定价的核心观点是先用基础版承接低频用户，再用专业版提升转化。"
    chunks = [
        KnowledgeChunk(
            chunk_id="doc-pricing-a:0001",
            doc_id="doc-pricing-a",
            ordinal=1,
            text=f"<!-- Split index: 7/25 -->\n\n{duplicate_body}",
            title="月专业版三档定价",
            source="sample",
            source_path="sample/1、背景.md",
            page_start=1,
            page_end=1,
            language_bucket="zh",
        ),
        KnowledgeChunk(
            chunk_id="doc-pricing-b:0001",
            doc_id="doc-pricing-b",
            ordinal=1,
            text=f"<!-- Split index: 8/25 -->\n\n{duplicate_body}",
            title="月专业版三档定价 副本",
            source="sample",
            source_path="sample/1、背景 (1).md",
            page_start=1,
            page_end=1,
            language_bucket="zh",
        ),
        _chunk("doc-pricing-c", 0, "续费策略强调年付折扣和套餐升级。"),
    ]
    index.add_documents(docs, chunks)

    results = index.search("根据资料库，月专业版三档定价相关的核心观点是什么？", top_k=5)

    assert [result.rank_position for result in results] == list(range(1, len(results) + 1))
    assert sum(duplicate_body in result.snippet for result in results) == 1
    assert len({result.snippet for result in results}) == len(results)


def test_knowledge_index_get_chunk_returns_full_payload(tmp_path: Path) -> None:
    index = KnowledgeIndex(tmp_path / "knowledge.db")
    index.initialize()
    index.reset()
    index.add_documents(
        [_doc("doc-1", "专家访谈")],
        [_chunk("doc-1", 0, "专家认为库存拐点可能出现。")],
    )

    payload = index.get(chunk_id="doc-1:0000")

    assert payload is not None
    assert payload["chunkId"] == "doc-1:0000"
    assert payload["documentId"] == "doc-1"
    assert payload["text"] == "专家认为库存拐点可能出现。"
