"""Memory tools — closure-injected tools wiring Memory system to Agent.

Usage (single store — backward compatible):
    from opensquilla.agents.scope import default_state_dir, default_workspace_dir
    from opensquilla.memory import LongTermMemoryStore, MemoryRetriever
    from opensquilla.tools.builtin.memory_tools import create_memory_tools

    store = LongTermMemoryStore(db_path=str(default_state_dir() / "agents/main/memory.db"))
    await store.initialize()
    retriever = MemoryRetriever(store)
    create_memory_tools(store, retriever, memory_dir=str(default_workspace_dir() / "memory"))

Usage (multi-agent routing):
    from opensquilla.agents.scope import default_state_dir

    stores = {"main": main_store, "ops": ops_store}
    retrievers = {"main": main_retriever, "ops": ops_retriever}
    create_memory_tools(stores, retrievers, memory_base=str(default_state_dir()))
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from opensquilla.memory.tool_surface import (
    MEMORY_SEARCH_DEFAULT_RESULTS,
    create_memory_tool_surface,
)
from opensquilla.tools.registry import tool

if TYPE_CHECKING:
    from opensquilla.memory.retrieval import MemoryRetriever
    from opensquilla.memory.store import LongTermMemoryStore
    from opensquilla.tools.registry import ToolRegistry

logger = structlog.get_logger(__name__)


def create_memory_tools(
    stores: dict[str, LongTermMemoryStore] | LongTermMemoryStore,
    retrievers: dict[str, MemoryRetriever] | MemoryRetriever,
    *,
    memory_base: str | None = None,
    memory_dir: str | None = None,
    registry: ToolRegistry | None = None,
    memory_config: Any | None = None,
    on_memory_write: Any | None = None,
    memory_source: str = "state",
    workspace_base: str | None = None,
) -> None:
    """Register memory tools. Accepts either a single store or a dict keyed by agent_id.

    Backward-compatible: a single store/retriever is auto-wrapped into ``{"main": ...}``.
    When dicts are provided, the active agent_id (from ToolContext via contextvar) selects
    the correct store, retriever, and memory directory at call time.
    """
    surface = create_memory_tool_surface(
        stores,
        retrievers,
        memory_base=memory_base,
        memory_dir=memory_dir,
        memory_config=memory_config,
        on_memory_write=on_memory_write,
        memory_source=memory_source,
        workspace_base=workspace_base,
    )

    @tool(
        name="memory_search",
        description=(
            "Recall step for prior work, decisions, dated history, todos, and "
            "historical memory not already present in injected context. Searches "
            "memory source files (MEMORY.md + memory/*.md) and returns top snippets "
            "with path + lines. User identity/profile fields such as name, preferred "
            "address, pronouns, and timezone belong in injected USER.md when present. "
            "Do not use memory_search for current user identity/profile questions when "
            "injected USER.md contains the answer."
        ),
        params={
            "query": {"type": "string", "description": "Search query"},
            "max_results": {
                "type": "integer",
                "description": "Maximum results to return (default 10, clamped to 1-20)",
            },
        },
        required=["query"],
        registry=registry,
    )
    async def memory_search(query: str, max_results: int = MEMORY_SEARCH_DEFAULT_RESULTS) -> str:
        return await surface.search(query, max_results)

    @tool(
        name="memory_save",
        description=(
            "Save content to memory source files for future recall. This is not "
            "for ordinary task deliverables such as reports, JSON outputs, or "
            "result files. Use MEMORY.md for long-term facts (mode=replace) and "
            "memory/YYYY-MM-DD.md for daily notes (mode=append). Profile/bootstrap "
            "files such as USER.md are edited with filesystem tools, not memory_save."
        ),
        params={
            "content": {"type": "string", "description": "Content to save"},
            "path": {
                "type": "string",
                "description": (
                    "MEMORY.md (long-term, mode=replace) or "
                    "memory/YYYY-MM-DD.md / memory/<name>.md "
                    "(daily or named memory source, mode=append). "
                    "Defaults to today's daily note."
                ),
            },
            "mode": {
                "type": "string",
                "description": "Write mode: 'append' (default) or 'replace'",
            },
        },
        required=["content"],
        exposed_by_default=False,
        registry=registry,
    )
    async def memory_save(content: str, path: str = "", mode: str = "append") -> str:
        return await surface.save(content, path=path, mode=mode)

    @tool(
        name="memory_get",
        description=(
            "Read from memory source files (MEMORY.md or memory/*.md) with optional from/lines. "
            "Use after memory_search to pull only the needed lines and keep context small."
        ),
        params={
            "path": {
                "type": "string",
                "description": "Workspace-relative memory source path: MEMORY.md or memory/*.md",
            },
            "from": {
                "type": "integer",
                "description": "Start from this line (1-indexed, optional)",
            },
            "from_line": {
                "type": "integer",
                "description": "Compatibility alias for from (1-indexed, optional)",
            },
            "lines": {"type": "integer", "description": "Number of lines to return (optional)"},
        },
        required=["path"],
        registry=registry,
    )
    async def memory_get(
        path: str,
        from_line: int | None = None,
        lines: int | None = None,
        **kwargs: Any,
    ) -> str:
        return surface.get(path, from_line=from_line, lines=lines, from_arg=kwargs.get("from"))

    @tool(
        name="memory_delete",
        description=(
            "Delete a memory source file and remove it from the search index. "
            "Use to correct wrong memories or remove outdated information."
        ),
        params={
            "path": {
                "type": "string",
                "description": "File path relative to memory directory to delete",
            },
        },
        required=["path"],
        exposed_by_default=False,
        registry=registry,
    )
    async def memory_delete(path: str) -> str:
        result = await surface.delete(path)
        if result.startswith("Deleted "):
            logger.info("memory_delete.ok", path=path)
        return result

    logger.info(
        "memory_tools_registered",
        tools=[
            "memory_search",
            "memory_save",
            "memory_get",
            "memory_delete",
        ],
    )
