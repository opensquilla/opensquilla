"""Memory-owned orchestration for the public memory tool surface."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from opensquilla.memory.runtime import (
    MemoryToolRuntime,
    MemoryToolRuntimeError,
    ResolvedMemoryAgent,
    configure_memory_tools_runtime,
    current_memory_tools_runtime,
    resolve_memory_agent,
)
from opensquilla.memory.tool_search import (
    MEMORY_SEARCH_DEFAULT_RESULTS as _MEMORY_SEARCH_DEFAULT_RESULTS,
)
from opensquilla.memory.tool_search import (
    search_memory_tool,
)
from opensquilla.memory.tool_sources import (
    memory_delete_tool_result,
    memory_get_tool_result,
)
from opensquilla.memory.tool_writes import (
    MemoryWriteError,
    PlannedMemoryWrite,
    apply_memory_writes,
    validate_memory_save_target,
)
from opensquilla.tools.types import ToolError, current_tool_context

if TYPE_CHECKING:
    from opensquilla.memory.retrieval import MemoryRetriever
    from opensquilla.memory.store import LongTermMemoryStore

MEMORY_SEARCH_DEFAULT_RESULTS = _MEMORY_SEARCH_DEFAULT_RESULTS


class MemoryToolSurface:
    """Facade used by tool adapters to execute memory tool behavior."""

    async def search(self, query: str, max_results: int) -> str:
        agent = self._resolve()
        return await search_memory_tool(agent.retriever, query, max_results)

    async def save(self, content: str, *, path: str = "", mode: str = "append") -> str:
        agent = self._resolve()
        path, mode = self._resolve_save_target(path, mode)

        try:
            validate_memory_save_target(path, mode)
            chunks = await apply_memory_writes(
                agent,
                [PlannedMemoryWrite(path=path, content=content, mode=mode)],
                memory_config=self._runtime().memory_config,
            )
        except MemoryWriteError as exc:
            raise ToolError(str(exc)) from exc

        self._runtime().notify_memory_write(agent.agent_id)
        integrity = "ok" if chunks[path] > 0 else "missing_chunks"
        return f"Saved to {path} ({chunks[path]} chunks indexed; integrity={integrity})."

    def get(
        self,
        path: str,
        *,
        from_line: int | None = None,
        lines: int | None = None,
        from_arg: Any | None = None,
    ) -> str:
        return memory_get_tool_result(
            self._resolve(),
            path,
            from_line=from_line,
            lines=lines,
            from_arg=from_arg,
            allow_archive=self._allow_archive_memory_source(),
        )

    async def delete(self, path: str) -> str:
        return await memory_delete_tool_result(
            self._resolve(),
            path,
            allow_archive=self._allow_archive_memory_source(),
        )

    def _runtime(self) -> MemoryToolRuntime:
        runtime = current_memory_tools_runtime()
        if runtime is None:
            raise ToolError("memory tools runtime not configured.")
        return runtime

    def _resolve(self) -> ResolvedMemoryAgent:
        ctx = current_tool_context.get()
        try:
            return resolve_memory_agent(
                agent_id=(ctx.agent_id if ctx else None) or "main",
                workspace_dir=ctx.workspace_dir if ctx else None,
            )
        except MemoryToolRuntimeError as exc:
            raise ToolError(str(exc)) from exc

    def _allow_archive_memory_source(self) -> bool:
        config = self._runtime().memory_config
        return bool(config and getattr(config, "index_captured_turns", False))

    def _resolve_save_target(self, path: str, mode: str) -> tuple[str, str]:
        if path:
            return path, mode
        today = datetime.now().strftime("%Y-%m-%d")
        return f"memory/{today}.md", "append"


def create_memory_tool_surface(
    stores: dict[str, LongTermMemoryStore] | LongTermMemoryStore,
    retrievers: dict[str, MemoryRetriever] | MemoryRetriever,
    *,
    memory_base: str | None = None,
    memory_dir: str | None = None,
    memory_config: Any | None = None,
    on_memory_write: Any | None = None,
    memory_source: str = "state",
    workspace_base: str | None = None,
) -> MemoryToolSurface:
    """Configure runtime and return the memory-owned tool facade."""
    configure_memory_tools_runtime(
        stores,
        retrievers,
        memory_base=memory_base,
        memory_dir=memory_dir,
        memory_config=memory_config,
        on_memory_write=on_memory_write,
        memory_source=memory_source,
        workspace_base=workspace_base,
    )
    return MemoryToolSurface()
