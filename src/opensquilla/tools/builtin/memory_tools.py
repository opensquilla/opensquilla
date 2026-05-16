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
from dataclasses import dataclass
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
from opensquilla.tools.registry import tool
from opensquilla.tools.types import ToolError, current_tool_context

if TYPE_CHECKING:
    from opensquilla.memory.retrieval import MemoryRetriever
    from opensquilla.memory.store import LongTermMemoryStore
    from opensquilla.tools.registry import ToolRegistry

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Injection scanning
# ---------------------------------------------------------------------------

_MEMORY_THREAT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.I),
    re.compile(r"you\s+are\s+now\s+(a|an)\b", re.I),
    re.compile(r"system\s+prompt\s+override", re.I),
    re.compile(r"new\s+instructions?\s*:", re.I),
    re.compile(r"(curl|wget)\s+.*\$\{?\w*(KEY|SECRET|TOKEN|PASSWORD)", re.I),
    re.compile(r"cat\s+.*(\.env|\.netrc|\.pgpass|credentials)", re.I),
    re.compile(r"authorized_keys", re.I),
    re.compile(r"<\s*system\s*>", re.I),
)

_INVISIBLE_CHARS = re.compile(r"[\u200b\u200c\u200d\ufeff\u202a-\u202e]")


def _scan_memory_content(content: str) -> str | None:
    """Lightweight check for injection/exfiltration in memory content.

    Returns an error message if blocked, None if clean.
    """
    if _INVISIBLE_CHARS.search(content):
        return "Blocked: content contains invisible Unicode control characters."
    for pattern in _MEMORY_THREAT_PATTERNS:
        if pattern.search(content):
            return f"Blocked: content matches threat pattern ({pattern.pattern[:40]}...)."
    return None


async def _prune_expired_files(
    memory_dir: str,
    store: LongTermMemoryStore,
    ttl_days: int,
    *,
    workspace_dir: str | None = None,
) -> None:
    """In-line TTL prune used by ``memory_save``.

    Thin back-compat wrapper around ``memory/retention.py``. Callers
    that hold a ``ResolvedMemoryAgent`` should pass ``workspace_dir`` so the
    helper builds store keys identical to the inline indexing path
    (``_apply_memory_writes`` indexes ``plan.path`` which is
    workspace-relative). Defaults to ``memory_dir.parent`` for legacy
    direct calls. The background sweeper in ``MemorySyncManager`` covers
    paths the in-line call cannot reach (notably ``memory/archive/**``
    written by ``TurnCaptureService``).
    """
    from opensquilla.memory.retention import prune_expired_memory_files

    await prune_expired_memory_files(
        memory_dir=Path(memory_dir),
        store=store,
        ttl_days=ttl_days,
        workspace_dir=Path(workspace_dir) if workspace_dir else None,
    )


def _is_memory_archive_path(path: str) -> bool:
    rel = Path(path)
    return (
        not rel.is_absolute()
        and not any(part in {"", ".", ".."} for part in rel.parts)
        and rel.parts[:2] == ("memory", "archive")
    )


def _is_memory_source_path(path: str, *, allow_archive: bool = False) -> bool:
    """Return True for OpenSquilla memory source files."""
    rel = Path(path)
    if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
        return False
    if rel.parts == ("MEMORY.md",):
        return True
    if rel.parts[:2] == ("memory", "archive") and not allow_archive:
        return False
    return (
        len(rel.parts) >= 2
        and rel.parts[0] == "memory"
        and rel.suffix == ".md"
        and not any(part.startswith(".") for part in rel.parts[1:])
    )


def _is_raw_fallback_save_path(path: str) -> bool:
    """Return True for paths under the ``memory/.raw_fallbacks/`` sidecar.

    Raw-dump fallback files (written by ``SessionFlushService._raw_dump_fallback``
    when both LLM flush and the curated path fail) live under a dot-prefix
    sidecar so the memory sync_manager scanner skips them — but the writer
    itself still goes through ``memory_save`` for unified file-write
    semantics. This predicate carves a narrow exception in the source-path
    gate for that single sidecar; nothing else dot-prefixed is writable.
    """
    rel = Path(path)
    return (
        not rel.is_absolute()
        and not any(part in {"", ".", ".."} for part in rel.parts)
        and len(rel.parts) >= 3
        and rel.parts[:2] == ("memory", ".raw_fallbacks")
        and rel.suffix == ".md"
    )


def _is_memory_save_path(path: str) -> bool:
    """Return True for writable memory files.

    Save targets must be readable/searchable memory sources OR the raw-dump
    fallback sidecar (``memory/.raw_fallbacks/``). Bootstrap profile files
    such as USER.md and AGENTS.md are edited through agent-file or
    filesystem surfaces, not memory_save.
    """
    return _is_memory_source_path(path) or _is_raw_fallback_save_path(path)


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


def _enforce_size_limits(memory_dir: Path, memory_config: Any) -> None:
    """FIFO-prune ``memory_dir`` against the effective ``max_files`` cap.

    Skips ``MEMORY.md`` (curated) and anything whose suffix is not
    ``.md``. Oldest files by mtime are deleted first.
    """
    if memory_config is None:
        return
    max_files = getattr(memory_config, "max_files", 0) or 0
    if max_files <= 0:
        return
    effective_cap = max_files
    files = sorted(
        (
            p
            for p in memory_dir.iterdir()
            if p.is_file()
            and p.suffix.lower() == ".md"
            and p.name != "MEMORY.md"
            and not p.name.startswith(".")
        ),
        key=lambda p: (p.stat().st_mtime, p.name),
    )
    if len(files) <= effective_cap:
        return
    for old in files[: len(files) - effective_cap]:
        try:
            old.unlink()
        except OSError:
            pass


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

    @dataclass(frozen=True)
    class PlannedWrite:
        path: str
        content: str
        mode: str

    @dataclass(frozen=True)
    class FileSnapshot:
        path: str
        abs_path: Path
        existed: bool
        content: str | None

    def _workspace_path(r: ResolvedMemoryAgent) -> Path:
        if not r.workspace_dir:
            raise ToolError("workspace directory not configured.")
        return Path(r.workspace_dir)

    def _resolve_memory_path(workspace_dir: Path, path: str) -> Path:
        mem_path = workspace_dir / path
        try:
            mem_path.resolve().relative_to(workspace_dir.resolve())
        except ValueError as exc:
            raise ToolError("path traversal not allowed.") from exc
        return mem_path

    def _validate_memory_save_target(path: str, mode: str) -> None:
        if not _is_memory_save_path(path):
            raise ToolError(
                "invalid memory path. Use a memory source file: MEMORY.md or memory/**/*.md."
            )
        if path == "MEMORY.md" and mode != "replace":
            raise ToolError(
                "MEMORY.md must use mode='replace'. "
                "Read it first, then write the full updated content."
            )

    def _allow_archive_memory_source() -> bool:
        config = _runtime().memory_config
        return bool(config and getattr(config, "index_captured_turns", False))

    def _private_archive_error() -> str:
        return (
            "Error: memory archive is private turn-capture storage. Use durable memory "
            "sources returned by memory_search. Enable index_captured_turns only when "
            "raw captured turns are intentionally part of the product contract."
        )

    def _ensure_clean_memory_content(content: str, path: str) -> None:
        threat = _scan_memory_content(content)
        if threat:
            logger.warning("memory_save.blocked", path=path, reason=threat)
            raise ToolError(threat)

    async def _maybe_prune(r: ResolvedMemoryAgent) -> None:
        config = _runtime().memory_config
        if config and getattr(config, "entry_ttl_days", 0) > 0 and r.memory_dir:
            await _prune_expired_files(
                r.memory_dir,
                r.store,
                config.entry_ttl_days,
                workspace_dir=r.workspace_dir,
            )

    async def _enforce_size_limits(
        r: ResolvedMemoryAgent,
        workspace_dir: Path,
        mem_path: Path,
        content: str,
        mode: str,
    ) -> None:
        config = _runtime().memory_config
        if not config:
            return

        content_size_kb = len(content.encode("utf-8")) / 1024

        max_file = getattr(config, "max_file_size_kb", 0)
        if max_file > 0:
            existing_size = mem_path.stat().st_size / 1024 if mem_path.exists() else 0
            projected = (existing_size + content_size_kb) if mode != "replace" else content_size_kb
            if projected > max_file:
                raise ToolError(
                    f"write would exceed per-file limit ({projected:.0f} KB > {max_file} KB)."
                )

        max_files = getattr(config, "max_files", 0)
        if max_files > 0 and not mem_path.exists():
            file_count = len(list(workspace_dir.rglob("*.md")))
            if file_count >= max_files:
                raise ToolError(f"max file count reached ({max_files}).")

        max_total = getattr(config, "max_total_size_kb", 0)
        if max_total > 0:
            total_kb = (await r.store.total_size()) / 1024
            if total_kb + content_size_kb > max_total:
                raise ToolError(
                    f"write would exceed total memory limit "
                    f"({total_kb:.0f} + {content_size_kb:.0f} KB > {max_total} KB)."
                )

    def _snapshot_paths(workspace_dir: Path, plans: list[PlannedWrite]) -> list[FileSnapshot]:
        seen: set[str] = set()
        snapshots: list[FileSnapshot] = []
        for plan in plans:
            if plan.path in seen:
                continue
            seen.add(plan.path)
            abs_path = _resolve_memory_path(workspace_dir, plan.path)
            existed = abs_path.exists()
            content = abs_path.read_text(encoding="utf-8") if existed else None
            snapshots.append(
                FileSnapshot(path=plan.path, abs_path=abs_path, existed=existed, content=content)
            )
        return snapshots

    def _write_content(mem_path: Path, content: str, mode: str) -> None:
        mem_path.parent.mkdir(parents=True, exist_ok=True)
        if mode == "replace":
            mem_path.write_text(content, encoding="utf-8")
        elif mem_path.exists():
            with open(mem_path, "a", encoding="utf-8") as handle:
                handle.write("\n\n" + content)
        else:
            mem_path.write_text(content, encoding="utf-8")

    async def _rollback_snapshots(
        r: ResolvedMemoryAgent,
        snapshots: list[FileSnapshot],
        touched_paths: set[str],
    ) -> str:
        from opensquilla.memory.types import MemorySource

        if not touched_paths:
            return "no-op"

        statuses: list[str] = []
        for snapshot in snapshots:
            if snapshot.path not in touched_paths:
                continue
            try:
                if snapshot.existed:
                    snapshot.abs_path.parent.mkdir(parents=True, exist_ok=True)
                    snapshot.abs_path.write_text(snapshot.content or "", encoding="utf-8")
                elif snapshot.abs_path.exists():
                    snapshot.abs_path.unlink()
            except Exception:
                statuses.append("disk_failed")
                continue

            try:
                if _is_raw_fallback_save_path(snapshot.path):
                    # Raw-dump sidecar paths are never indexed (F2); rollback
                    # only needs to restore disk content, which already
                    # happened above.
                    statuses.append("restored")
                    continue
                if snapshot.existed:
                    await r.store.index_file(
                        path=snapshot.path,
                        content=snapshot.content or "",
                        source=MemorySource.memory,
                    )
                else:
                    await r.store.remove_file(snapshot.path)
                statuses.append("restored")
            except Exception:
                statuses.append("index_stale")

        if any(status == "disk_failed" for status in statuses):
            return "disk_failed"
        if any(status == "index_stale" for status in statuses):
            return "index_stale"
        return "restored"

    def _raise_with_rollback_context(exc: Exception, rollback_status: str) -> None:
        if rollback_status == "restored":
            suffix = "changes rolled back."
        elif rollback_status == "index_stale":
            suffix = "on-disk state rolled back, but index may be stale."
        elif rollback_status == "disk_failed":
            suffix = "rollback failed; disk and index may be inconsistent."
        else:
            suffix = "operation failed."

        message = f"{exc} ({suffix})"
        if isinstance(exc, ToolError):
            raise ToolError(message) from exc
        raise RuntimeError(message) from exc

    async def _apply_memory_writes(
        r: ResolvedMemoryAgent,
        plans: list[PlannedWrite],
    ) -> dict[str, int]:
        from opensquilla.memory.types import MemorySource

        if not plans:
            return {}

        workspace_dir = _workspace_path(r)
        await _maybe_prune(r)

        snapshots = _snapshot_paths(workspace_dir, plans)
        snapshot_map = {snapshot.path: snapshot for snapshot in snapshots}
        touched_paths: set[str] = set()
        chunks_by_path: dict[str, int] = {}

        try:
            for plan in plans:
                mem_path = snapshot_map[plan.path].abs_path
                _ensure_clean_memory_content(plan.content, plan.path)
                await _enforce_size_limits(r, workspace_dir, mem_path, plan.content, plan.mode)
                _write_content(mem_path, plan.content, plan.mode)
                written_content = mem_path.read_text(encoding="utf-8")
                touched_paths.add(plan.path)
                is_raw_fallback = _is_raw_fallback_save_path(plan.path)
                if is_raw_fallback:
                    # Raw-dump fallback files live under ``memory/.raw_fallbacks/``
                    # explicitly to escape retrieval. Skipping inline indexing
                    # here matches the sync_manager dot-prefix exclusion so the
                    # file never enters the store at write-time either. (F2)
                    chunks_by_path[plan.path] = 0
                else:
                    chunks_by_path[plan.path] = await r.store.index_file(
                        path=plan.path,
                        content=written_content,
                        source=MemorySource.memory,
                    )
            return chunks_by_path
        except Exception as exc:
            rollback_status = await _rollback_snapshots(r, snapshots, touched_paths)
            if rollback_status == "no-op":
                raise
            _raise_with_rollback_context(exc, rollback_status)
            raise RuntimeError("unreachable")

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

        _validate_memory_save_target(path, mode)
        chunks = await _apply_memory_writes(
            r,
            [PlannedWrite(path=path, content=content, mode=mode)],
        )
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
            return _private_archive_error()
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
            return _private_archive_error()
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
