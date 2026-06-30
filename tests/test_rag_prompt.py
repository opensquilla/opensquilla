from __future__ import annotations

from pathlib import Path


def test_system_prompt_documents_rag_memory_boundary():
    root = Path(__file__).resolve().parents[1]
    template = (root / "src/opensquilla/identity/templates/system_prompt.j2").read_text(
        encoding="utf-8"
    )

    assert "## RAG Evidence" in template
    assert "RAG is separate from memory" in template
    assert "Do not pass a `mode` to `rag_search`" in template
    assert "configured RAG retrieval mode" in template
    assert "compact evidence list" in template
    assert "call `rag_get`" in template
    assert "untrusted external evidence" in template
    assert "[来源：relative/path.md]" in template
    assert "引用：" in template
