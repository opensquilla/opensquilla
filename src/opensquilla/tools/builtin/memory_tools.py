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

import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import structlog

from opensquilla.memory.runtime import (
    MemoryToolRuntime,
    MemoryToolRuntimeError,
    ResolvedMemoryAgent,
    configure_memory_tools_runtime,
    current_memory_tools_runtime,
    resolve_memory_agent,
)
from opensquilla.memory.source_paths import (
    is_memory_archive_path as _is_memory_archive_path,
)
from opensquilla.memory.source_paths import (
    is_memory_source_path as _is_memory_source_path,
)
from opensquilla.memory.source_paths import (
    private_archive_error,
)
from opensquilla.memory.tool_writes import (
    MemoryWriteError,
    PlannedMemoryWrite,
    apply_memory_writes,
    validate_memory_save_target,
)
from opensquilla.tools.registry import tool
from opensquilla.tools.types import ToolError, current_tool_context

if TYPE_CHECKING:
    from opensquilla.memory.retrieval import MemoryRetriever
    from opensquilla.memory.store import LongTermMemoryStore
    from opensquilla.tools.registry import ToolRegistry

logger = structlog.get_logger(__name__)

_MEMORY_SEARCH_DEFAULT_RESULTS: Final[int] = 10
_MEMORY_SEARCH_MAX_RESULTS: Final[int] = 20
_MEMORY_SEARCH_EVIDENCE_CHARS: Final[int] = 900
_MEMORY_SEARCH_STOP_WORDS: Final[frozenset[str]] = frozenset(
    {
        "about",
        "after",
        "and",
        "are",
        "did",
        "for",
        "from",
        "has",
        "have",
        "her",
        "him",
        "his",
        "how",
        "the",
        "their",
        "them",
        "was",
        "were",
        "what",
        "when",
        "where",
        "who",
        "why",
        "with",
    }
)
_YAML_FRONTMATTER_RE = re.compile(r"\A---\s*\n.*?\n---\s*(?:\n|$)", re.S)


def _memory_search_limit(value: object) -> int:
    parsed = _MEMORY_SEARCH_DEFAULT_RESULTS
    if isinstance(value, (int, float, str)):
        try:
            parsed = int(value)
        except (OverflowError, ValueError):
            parsed = _MEMORY_SEARCH_DEFAULT_RESULTS
    return max(1, min(_MEMORY_SEARCH_MAX_RESULTS, parsed))


def _clean_memory_search_evidence(text: str) -> str:
    raw = text.strip()
    if not raw:
        return ""

    cleaned = _YAML_FRONTMATTER_RE.sub("", raw, count=1).lstrip()
    lines = cleaned.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while (
        lines
        and lines[0].lstrip().startswith("#")
        and any(line.strip() and not line.lstrip().startswith("#") for line in lines[1:])
    ):
        lines.pop(0)
        while lines and not lines[0].strip():
            lines.pop(0)

    cleaned = "\n".join(lines).strip()
    return cleaned or raw


def _memory_search_query_terms(query: str) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    for term in re.findall(r"[A-Za-z0-9]+", query.lower()):
        if len(term) < 3 or term in _MEMORY_SEARCH_STOP_WORDS or term in seen:
            continue
        terms.append(term)
        seen.add(term)
    return tuple(terms)


def _query_line_score(line: str, terms: tuple[str, ...]) -> int:
    lowered = line.lower()
    return sum(1 for term in terms if term in lowered)


def _truncate_line_around_query(line: str, terms: tuple[str, ...], budget: int) -> str:
    if len(line) <= budget:
        return line
    lowered = line.lower()
    positions = [lowered.find(term) for term in terms if term in lowered]
    center = min(positions) if positions else 0
    start = max(0, center - budget // 3)
    end = min(len(line), start + budget)
    start = max(0, end - budget)
    excerpt = line[start:end].strip()
    if start > 0:
        excerpt = "... " + excerpt
    if end < len(line):
        excerpt = excerpt.rstrip() + " ..."
    return excerpt


def _query_centered_evidence(cleaned: str, query: str, budget: int) -> str | None:
    terms = _memory_search_query_terms(query)
    if not terms:
        return None
    lines = cleaned.splitlines()
    scored = [(_query_line_score(line, terms), index) for index, line in enumerate(lines)]
    best_score, best_index = max(scored, default=(0, 0))
    if best_score <= 0:
        return None
    if len(lines[best_index]) >= budget:
        return _truncate_line_around_query(lines[best_index], terms, budget)

    start = best_index
    end = best_index + 1
    while True:
        current = "\n".join(lines[start:end])
        added = False
        if start > 0:
            candidate = "\n".join(lines[start - 1 : end])
            if len(candidate) <= budget:
                start -= 1
                added = True
        if end < len(lines):
            candidate = "\n".join(lines[start : end + 1])
            if len(candidate) <= budget:
                end += 1
                added = True
        if not added or "\n".join(lines[start:end]) == current:
            break

    block = "\n".join(lines[start:end]).strip()
    if start > 0:
        block = "... (earlier lines omitted)\n" + block
    if end < len(lines):
        block = block + "\n... (later lines omitted)"
    if len(block) <= budget:
        return block
    return "\n".join(lines[start:end]).strip()


def _bounded_memory_search_evidence(text: str, *, query: str = "") -> str:
    cleaned = _clean_memory_search_evidence(text)
    if len(cleaned) <= _MEMORY_SEARCH_EVIDENCE_CHARS:
        return cleaned
    centered = _query_centered_evidence(cleaned, query, _MEMORY_SEARCH_EVIDENCE_CHARS)
    if centered:
        return centered
    return cleaned[:_MEMORY_SEARCH_EVIDENCE_CHARS].rstrip() + "\n... (truncated)"


def _score_parts(result: Any) -> list[str]:
    parts = [f"score: {result.score:.3f}"]
    if result.text_score is not None:
        parts.append(f"text_score: {result.text_score:.3f}")
    return parts


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

    def _runtime() -> MemoryToolRuntime:
        runtime = current_memory_tools_runtime()
        if runtime is None:
            raise ToolError("memory tools runtime not configured.")
        return runtime

    def _resolve() -> ResolvedMemoryAgent:
        """Pick the store/retriever/memory_dir/workspace_dir for the current agent_id."""
        ctx = current_tool_context.get()
        try:
            return resolve_memory_agent(
                agent_id=(ctx.agent_id if ctx else None) or "main",
                workspace_dir=ctx.workspace_dir if ctx else None,
            )
        except MemoryToolRuntimeError as exc:
            raise ToolError(str(exc)) from exc

    def _allow_archive_memory_source() -> bool:
        config = _runtime().memory_config
        return bool(config and getattr(config, "index_captured_turns", False))

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
    async def memory_search(query: str, max_results: int = _MEMORY_SEARCH_DEFAULT_RESULTS) -> str:
        from opensquilla.memory.types import MemorySearchOpts, SearchIntent

        r = _resolve()
        opts = MemorySearchOpts(max_results=_memory_search_limit(max_results))
        results = await r.retriever.search(query, opts, intent=SearchIntent.TOOL)
        if not results:
            return "No results found."

        lines = []
        for i, result in enumerate(results, 1):
            citation = result.citation or f"{result.path}#L{result.start_line}-L{result.end_line}"
            evidence = _bounded_memory_search_evidence(result.text or result.snippet, query=query)
            lines.append(
                f"[{i}] {result.path} "
                f"(lines {result.start_line}-{result.end_line}; "
                f"citation: {citation}; {', '.join(_score_parts(result))})\n"
                f"{evidence}"
            )
        return "\n\n".join(lines)

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
        r = _resolve()
        # Default path: today's daily note
        today = datetime.now().strftime("%Y-%m-%d")
        if not path:
            path = f"memory/{today}.md"
            mode = "append"

        try:
            validate_memory_save_target(path, mode)
            chunks = await apply_memory_writes(
                r,
                [PlannedMemoryWrite(path=path, content=content, mode=mode)],
                memory_config=_runtime().memory_config,
            )
        except MemoryWriteError as exc:
            raise ToolError(str(exc)) from exc
        # Notify snapshot refresh on successful write
        ctx = current_tool_context.get()
        _aid = (ctx.agent_id if ctx else None) or "main"
        _runtime().notify_memory_write(_aid)
        integrity = "ok" if chunks[path] > 0 else "missing_chunks"
        return f"Saved to {path} ({chunks[path]} chunks indexed; integrity={integrity})."

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
        from_arg = kwargs.get("from")
        if from_line is None and from_arg is not None:
            if isinstance(from_arg, bool) or not isinstance(from_arg, int):
                return "Error: from must be an integer."
            from_line = from_arg

        r = _resolve()
        if not r.workspace_dir:
            return "Error: workspace directory not configured."

        workspace_dir = Path(r.workspace_dir)
        file_path = workspace_dir / path
        try:
            file_path.resolve().relative_to(workspace_dir.resolve())
        except ValueError:
            return "Error: path traversal not allowed."

        allow_archive = _allow_archive_memory_source()
        if _is_memory_archive_path(path) and not allow_archive:
            return private_archive_error()
        if not _is_memory_source_path(path, allow_archive=allow_archive):
            return "Error: path is not a memory source file. Use MEMORY.md or memory/*.md."

        if not file_path.exists():
            return f"Error: {path} not found."

        content = file_path.read_text(encoding="utf-8", errors="replace")
        if from_line is not None or lines is not None:
            all_lines = content.splitlines()
            start = max(0, (from_line - 1)) if from_line else 0
            end = (start + lines) if lines else len(all_lines)
            content = "\n".join(all_lines[start:end])
        full_len = len(content)
        if full_len > 8000:
            return content[:8000] + f"\n\n... (truncated: showing 8000/{full_len} chars)"
        return content

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
        r = _resolve()
        if not r.workspace_dir:
            return "Error: workspace directory not configured."

        workspace_dir = Path(r.workspace_dir)
        file_path = workspace_dir / path
        try:
            file_path.resolve().relative_to(workspace_dir.resolve())
        except ValueError:
            return "Error: path traversal not allowed."

        allow_archive = _allow_archive_memory_source()
        if _is_memory_archive_path(path) and not allow_archive:
            return private_archive_error()
        if not _is_memory_source_path(path, allow_archive=allow_archive):
            return "Error: path is not a memory source file. Use MEMORY.md or memory/*.md."

        if not file_path.exists():
            return f"Error: {path} not found."

        # Remove from disk
        file_path.unlink()

        # Remove from index (workspace-relative path)
        index_path = file_path.resolve().relative_to(workspace_dir.resolve()).as_posix()
        await r.store.remove_file(index_path)

        logger.info("memory_delete.ok", path=path)
        return f"Deleted {path} and removed from index."

    logger.info(
        "memory_tools_registered",
        tools=[
            "memory_search",
            "memory_save",
            "memory_get",
            "memory_delete",
        ],
    )
