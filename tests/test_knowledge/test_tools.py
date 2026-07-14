from __future__ import annotations

import inspect

from opensquilla.rag_provider import tools as provider_tools


def test_standard_rag_tools_do_not_import_legacy_knowledge_backend() -> None:
    source = inspect.getsource(provider_tools)

    assert "opensquilla.knowledge" not in source
    assert "KnowledgeBackend" not in source
    assert "manager_from_config" not in source
