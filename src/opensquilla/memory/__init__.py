"""Memory system: long-term persistent memory for opensquilla agents."""

from .backend import MemoryBackend
from .embedding import (
    EmbeddingProvider,
    LocalEmbeddingProvider,
    NullEmbeddingProvider,
    OllamaEmbeddingProvider,
    OpenAIEmbeddingProvider,
    chunk_text,
)
from .flush import SILENT_REPLY_TOKEN, MemoryFlushPlan, resolve_flush_plan, should_flush
from .manager import MemoryManager, build_memory_managers
from .meta import MemoryIndexMeta
from .retrieval import MemoryRetriever
from .runtime import (
    MemoryToolRuntime,
    MemoryToolRuntimeError,
    ResolvedMemoryAgent,
    configure_memory_tools_runtime,
    current_memory_tools_runtime,
    memory_tools_available,
    reset_memory_tools_runtime,
    resolve_memory_agent,
)
from .source_inspection import (
    MEMORY_SOURCE_MAX_SHOW_CHARS,
    MEMORY_SOURCE_MAX_SHOW_FILE_BYTES,
    MEMORY_SOURCE_MAX_SHOW_LINES,
    MemorySourceContent,
    MemorySourceInspectionError,
    MemorySourceNotFoundError,
    MemorySourceRow,
    list_memory_source_rows,
    read_memory_source_content,
)
from .source_paths import (
    is_memory_archive_path,
    is_memory_save_path,
    is_memory_source_path,
    is_raw_fallback_save_path,
    private_archive_error,
)
from .source_search import (
    MEMORY_SOURCE_SEARCH_DEFAULT_RESULTS,
    MEMORY_SOURCE_SEARCH_MAX_RESULTS,
    MemorySourceSearchRow,
    memory_source_search_row,
    search_memory_sources,
)
from .store import LongTermMemoryStore
from .sync_manager import MemorySyncManager, SessionDeltaTracker
from .sync_manager import MemorySyncManager as MemoryFileWatcher
from .tool_search import (
    MEMORY_SEARCH_DEFAULT_RESULTS,
    MEMORY_SEARCH_MAX_RESULTS,
    bounded_memory_search_evidence,
    clean_memory_search_evidence,
    format_memory_search_results,
    memory_search_limit,
    search_memory_tool,
)
from .tool_sources import (
    MemorySourceError,
    delete_memory_source,
    read_memory_source,
)
from .tool_writes import (
    MemoryWriteError,
    PlannedMemoryWrite,
    apply_memory_writes,
    scan_memory_content,
    validate_memory_save_target,
)
from .types import (
    MemorySearchOpts,
    MemorySearchResult,
    MemorySource,
    SearchMode,
)

__all__ = [
    # types
    "MemorySearchResult",
    "MemorySearchOpts",
    "MemorySource",
    "SearchMode",
    # long-term store
    "MemoryBackend",
    "LongTermMemoryStore",
    # facade
    "MemoryManager",
    "build_memory_managers",
    # runtime
    "MemoryToolRuntime",
    "MemoryToolRuntimeError",
    "ResolvedMemoryAgent",
    "configure_memory_tools_runtime",
    "current_memory_tools_runtime",
    "memory_tools_available",
    "reset_memory_tools_runtime",
    "resolve_memory_agent",
    # source paths
    "is_memory_archive_path",
    "is_memory_save_path",
    "is_memory_source_path",
    "is_raw_fallback_save_path",
    "private_archive_error",
    # source search
    "MEMORY_SOURCE_SEARCH_DEFAULT_RESULTS",
    "MEMORY_SOURCE_SEARCH_MAX_RESULTS",
    "MemorySourceSearchRow",
    "memory_source_search_row",
    "search_memory_sources",
    # source inspection
    "MEMORY_SOURCE_MAX_SHOW_CHARS",
    "MEMORY_SOURCE_MAX_SHOW_FILE_BYTES",
    "MEMORY_SOURCE_MAX_SHOW_LINES",
    "MemorySourceContent",
    "MemorySourceInspectionError",
    "MemorySourceNotFoundError",
    "MemorySourceRow",
    "list_memory_source_rows",
    "read_memory_source_content",
    # tool sources
    "MemorySourceError",
    "delete_memory_source",
    "read_memory_source",
    # tool search
    "MEMORY_SEARCH_DEFAULT_RESULTS",
    "MEMORY_SEARCH_MAX_RESULTS",
    "bounded_memory_search_evidence",
    "clean_memory_search_evidence",
    "format_memory_search_results",
    "memory_search_limit",
    "search_memory_tool",
    # tool writes
    "MemoryWriteError",
    "PlannedMemoryWrite",
    "apply_memory_writes",
    "scan_memory_content",
    "validate_memory_save_target",
    # retrieval
    "MemoryRetriever",
    # embedding
    "EmbeddingProvider",
    "NullEmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "OllamaEmbeddingProvider",
    "LocalEmbeddingProvider",
    "chunk_text",
    # watcher (backward compat alias)
    "MemoryFileWatcher",
    # sync manager
    "MemorySyncManager",
    "SessionDeltaTracker",
    # flush
    "MemoryFlushPlan",
    "resolve_flush_plan",
    "should_flush",
    "SILENT_REPLY_TOKEN",
    # meta
    "MemoryIndexMeta",
]
