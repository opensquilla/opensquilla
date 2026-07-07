"""Local document knowledge base support.

This package is intentionally separate from ``opensquilla.memory``. Memory is
agent state; knowledge is an operator-managed retrieval source exposed to the
agent through tools.
"""

from opensquilla.knowledge.manager import KnowledgeManager

__all__ = ["KnowledgeManager"]
