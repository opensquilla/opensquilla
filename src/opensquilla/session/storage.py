"""Async database operations for sessions using aiosqlite + SQLModel."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
import sqlite3
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import wraps
from typing import TYPE_CHECKING, Any, Concatenate

from opensquilla.compat import aiosqlite
from opensquilla.session.keys import canonicalize_session_key, normalize_agent_id
from opensquilla.session.models import (
    AgentTaskRecord,
    AgentTaskStatus,
    MemoryDurableReceipt,
    SessionContextState,
    SessionNode,
    SessionSummary,
    TranscriptEntry,
    TurnIngressReceipt,
)

if TYPE_CHECKING:
    from opensquilla.persistence.meta_run_writer import MetaRunWriter

log = logging.getLogger(__name__)


class StaleEpochError(Exception):
    """Raised when a write is rejected because the session epoch has advanced."""


@dataclass(frozen=True, slots=True)
class CanonicalTranscriptCoverage:
    """Canonical archive coverage and its session metadata snapshot."""

    canonical_complete: bool
    compaction_count: int
    inherited_compactions: bool


class StorageBusyError(RuntimeError):
    """Raised when a SQLite write lock outlives the bounded retry budget."""

    def __init__(
        self,
        operation: str,
        *,
        waited_ms: int,
        retry_after_ms: int,
    ) -> None:
        super().__init__("Session storage is temporarily busy")
        self.operation = operation
        self.waited_ms = waited_ms
        self.retry_after_ms = retry_after_ms


class StorageConnectionPoisonedError(RuntimeError):
    """Raised after transaction cleanup failed and the connection was retired."""


class TurnIngressConflictError(ValueError):
    """Raised when a client request id is reused for a different turn payload."""


class TaskCollectionUnavailableError(RuntimeError):
    """Raised when a queued task stopped being collectable before acceptance."""


@dataclass(frozen=True)
class ResetArchiveSnapshot:
    """Pre-reset session state captured under the acceptance write transaction."""

    node: SessionNode
    entries: tuple[TranscriptEntry, ...]
    summaries: tuple[SessionSummary, ...]


@dataclass(frozen=True)
class TurnAcceptanceResult:
    """Outcome of the durable turn-acceptance transaction."""

    receipt: TurnIngressReceipt
    replayed: bool
    fresh_user_session: bool
    task_status: AgentTaskStatus | None = None
    reset_archive_snapshot: ResetArchiveSnapshot | None = None


_SQLITE_BUSY_TIMEOUT_MS = 100
_INTERACTIVE_BUSY_BUDGET_SECONDS = 2.0
_BUSY_RETRY_INITIAL_SECONDS = 0.025
_BUSY_RETRY_MAX_SECONDS = 0.250


def _is_sqlite_busy(exc: BaseException) -> bool:
    code = getattr(exc, "sqlite_errorcode", None)
    if isinstance(code, int):
        return code & 0xFF in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
    message = str(exc).lower()
    return "database is locked" in message or "database table is locked" in message


def _serialized_read[**P, R](
    method: Callable[Concatenate[SessionStorage, P], Awaitable[R]],
) -> Callable[Concatenate[SessionStorage, P], Awaitable[R]]:
    """Serialize a public read against multi-statement writes on the shared connection."""

    @wraps(method)
    async def _wrapped(self: SessionStorage, *args: P.args, **kwargs: P.kwargs) -> R:
        async with self._operation_lock:
            self._raise_if_poisoned()
            return await method(self, *args, **kwargs)

    return _wrapped


# Bumped whenever the schema is widened or narrowed via migration.
# Version 2 added the epoch column. Version 3 added transcript reasoning replay.
# Version 4 added transcript turn usage metadata.
# Version 5 added structured compaction summary metadata.
# Version 6 added portable/provider context state records.
# Version 7 added archived transcript rows for canonical recovery after compaction.
# Version 8 added the derived_title column for LLM-generated session titles.
# Version 9 added durable turn-ingress receipts.
SCHEMA_VERSION = 9

# Session rows at or above this semantic version were created by fork logic
# that records enough existing metadata for canonical coverage to be checked
# without guessing about legacy prefix forks. This reuses the persisted row
# version and does not widen or rewrite the database schema.
CANONICAL_FORK_PROOF_SCHEMA_VERSION = 2

# SQLite CREATE statements derived from SQLModel metadata
_CREATE_SESSIONS = """
CREATE TABLE IF NOT EXISTS sessions (
    session_key TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    started_at INTEGER,
    ended_at INTEGER,
    runtime_ms INTEGER,
    last_channel TEXT,
    last_to TEXT,
    last_account_id TEXT,
    last_thread_id TEXT,
    delivery_context TEXT,
    model TEXT,
    model_provider TEXT,
    provider_override TEXT,
    model_override TEXT,
    auth_profile_override TEXT,
    auth_profile_override_source TEXT,
    context_tokens INTEGER,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens_fresh INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd REAL NOT NULL DEFAULT 0.0,
    total_cost_usd REAL NOT NULL DEFAULT 0.0,
    billed_cost_usd REAL NOT NULL DEFAULT 0.0,
    estimated_cost_component_usd REAL NOT NULL DEFAULT 0.0,
    cost_source TEXT NOT NULL DEFAULT 'none',
    missing_cost_entries INTEGER NOT NULL DEFAULT 0,
    cache_read INTEGER NOT NULL DEFAULT 0,
    cache_write INTEGER NOT NULL DEFAULT 0,
    compaction_count INTEGER NOT NULL DEFAULT 0,
    session_file TEXT,
    spawned_by TEXT,
    parent_session_key TEXT,
    forked_from_parent INTEGER NOT NULL DEFAULT 0,
    spawn_depth INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running',
    chat_type TEXT NOT NULL DEFAULT 'unknown',
    thinking_level TEXT,
    fast_mode INTEGER NOT NULL DEFAULT 0,
    verbose_level TEXT,
    reasoning_level TEXT,
    send_policy TEXT NOT NULL DEFAULT 'allow',
    queue_mode TEXT NOT NULL DEFAULT 'steer',
    label TEXT,
    display_name TEXT,
    derived_title TEXT,
    channel TEXT,
    group_id TEXT,
    subject TEXT,
    origin TEXT,
    agent_id TEXT NOT NULL DEFAULT 'main',
    schema_version INTEGER NOT NULL DEFAULT 1,
    epoch INTEGER NOT NULL DEFAULT 0
)
"""

# Recency ordering for list_sessions and the title search (ORDER BY updated_at
# DESC LIMIT). Without it both do a full table sort on every call.
_CREATE_IDX_SESSIONS_UPDATED = (
    "CREATE INDEX IF NOT EXISTS idx_sessions_updated_at ON sessions(updated_at)"
)

_CREATE_TRANSCRIPT = """
CREATE TABLE IF NOT EXISTS transcript_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    session_key TEXT NOT NULL,
    message_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT,
    tool_calls TEXT,
    tool_call_id TEXT,
    reasoning_content TEXT,
    turn_usage TEXT,
    created_at INTEGER NOT NULL,
    token_count INTEGER,
    provenance_kind TEXT,
    provenance_origin_session_id TEXT,
    provenance_source_session_key TEXT,
    provenance_source_channel TEXT,
    provenance_source_tool TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
)
"""

_CREATE_IDX_TRANSCRIPT_SESSION = (
    "CREATE INDEX IF NOT EXISTS idx_transcript_session_id ON transcript_entries(session_id)"
)
_CREATE_IDX_TRANSCRIPT_KEY = (
    "CREATE INDEX IF NOT EXISTS idx_transcript_session_key ON transcript_entries(session_key)"
)
_CREATE_IDX_TRANSCRIPT_CURSOR = """
CREATE INDEX IF NOT EXISTS idx_transcript_session_cursor
ON transcript_entries(session_id, created_at, id)
"""

_CREATE_COMPACTED_TRANSCRIPT = """
CREATE TABLE IF NOT EXISTS compacted_transcript_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    session_key TEXT NOT NULL,
    compaction_id TEXT,
    compaction_index INTEGER,
    original_entry_id INTEGER,
    message_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT,
    tool_calls TEXT,
    tool_call_id TEXT,
    reasoning_content TEXT,
    turn_usage TEXT,
    created_at INTEGER NOT NULL,
    token_count INTEGER,
    provenance_kind TEXT,
    provenance_origin_session_id TEXT,
    provenance_source_session_key TEXT,
    provenance_source_channel TEXT,
    provenance_source_tool TEXT,
    archived_at INTEGER NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1
)
"""

_CREATE_IDX_COMPACTED_TRANSCRIPT_SESSION = """
CREATE INDEX IF NOT EXISTS idx_compacted_transcript_session_id
ON compacted_transcript_entries(session_id)
"""

_CREATE_IDX_COMPACTED_TRANSCRIPT_KEY = """
CREATE INDEX IF NOT EXISTS idx_compacted_transcript_session_key
ON compacted_transcript_entries(session_key)
"""
_CREATE_IDX_COMPACTED_TRANSCRIPT_CURSOR = """
CREATE INDEX IF NOT EXISTS idx_compacted_transcript_session_cursor
ON compacted_transcript_entries(session_id, created_at, original_entry_id, id)
"""

_CREATE_IDX_COMPACTED_TRANSCRIPT_COMPACTION = """
CREATE INDEX IF NOT EXISTS idx_compacted_transcript_session_compaction
ON compacted_transcript_entries(session_id, compaction_id)
"""

# FTS5 full-text search on transcript content
_CREATE_TRANSCRIPT_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS transcript_fts
USING fts5(content, content=transcript_entries, content_rowid=id)
"""

_CREATE_FTS_TRIGGER_INSERT = """
CREATE TRIGGER IF NOT EXISTS transcript_fts_ai AFTER INSERT ON transcript_entries BEGIN
    INSERT INTO transcript_fts(rowid, content) VALUES (new.id, new.content);
END
"""

_CREATE_FTS_TRIGGER_DELETE = """
CREATE TRIGGER IF NOT EXISTS transcript_fts_ad AFTER DELETE ON transcript_entries BEGIN
    INSERT INTO transcript_fts(transcript_fts, rowid, content)
    VALUES ('delete', old.id, old.content);
END
"""

_CREATE_FTS_TRIGGER_UPDATE = """
CREATE TRIGGER IF NOT EXISTS transcript_fts_au AFTER UPDATE ON transcript_entries BEGIN
    INSERT INTO transcript_fts(transcript_fts, rowid, content)
    VALUES ('delete', old.id, old.content);
    INSERT INTO transcript_fts(rowid, content) VALUES (new.id, new.content);
END
"""

_CREATE_SUMMARIES = """
CREATE TABLE IF NOT EXISTS session_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    session_key TEXT NOT NULL,
    compaction_index INTEGER NOT NULL DEFAULT 0,
    compaction_id TEXT,
    trigger_reason TEXT,
    summary_text TEXT NOT NULL,
    summary_payload TEXT,
    summary_format TEXT NOT NULL DEFAULT 'text',
    summary_source TEXT NOT NULL DEFAULT 'unknown',
    coverage_status TEXT NOT NULL DEFAULT 'unknown',
    missing_obligations TEXT,
    critical_carry_forward TEXT,
    tokens_before INTEGER,
    tokens_after INTEGER,
    removed_count INTEGER NOT NULL DEFAULT 0,
    kept_count INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    flush_receipt_status TEXT NOT NULL DEFAULT 'unknown',
    covered_through_id INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1
)
"""

_CREATE_IDX_SUMMARIES = (
    "CREATE INDEX IF NOT EXISTS idx_summaries_session_id ON session_summaries(session_id)"
)

_CREATE_CONTEXT_STATES = """
CREATE TABLE IF NOT EXISTS session_context_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    session_key TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'portable',
    model TEXT,
    state_kind TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    covered_through_id INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    expires_at INTEGER,
    portable INTEGER NOT NULL DEFAULT 0,
    cacheable INTEGER NOT NULL DEFAULT 0,
    valid INTEGER NOT NULL DEFAULT 1,
    invalid_reason TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
)
"""

_CREATE_IDX_CONTEXT_STATES_SESSION = """
CREATE INDEX IF NOT EXISTS idx_context_states_session_id
ON session_context_states(session_id)
"""

_CREATE_IDX_CONTEXT_STATES_KEY_VALID = """
CREATE INDEX IF NOT EXISTS idx_context_states_key_valid
ON session_context_states(session_key, valid, state_kind, provider)
"""

_CREATE_AGENT_TASKS = """
CREATE TABLE IF NOT EXISTS agent_tasks (
    task_id TEXT PRIMARY KEY,
    session_key TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT 'main',
    source_kind TEXT NOT NULL,
    queue_mode TEXT NOT NULL,
    run_kind TEXT NOT NULL DEFAULT 'default',
    status TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    started_at INTEGER,
    finished_at INTEGER,
    terminal_reason TEXT,
    error_class TEXT,
    error_message TEXT,
    details TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
)
"""

_CREATE_IDX_AGENT_TASKS_SESSION_STATUS = """
CREATE INDEX IF NOT EXISTS idx_agent_tasks_session_status
ON agent_tasks(session_key, status)
"""

_CREATE_IDX_AGENT_TASKS_STATUS_UPDATED = """
CREATE INDEX IF NOT EXISTS idx_agent_tasks_status_updated
ON agent_tasks(status, updated_at)
"""

_CREATE_TURN_INGRESS_RECEIPTS = """
CREATE TABLE IF NOT EXISTS turn_ingress_receipts (
    receipt_id TEXT PRIMARY KEY,
    source_scope TEXT NOT NULL,
    request_session_key TEXT NOT NULL,
    client_request_id TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    accepted_session_key TEXT NOT NULL,
    session_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    task_id TEXT,
    accepted_at INTEGER NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1
)
"""

_CREATE_IDX_TURN_INGRESS_REQUEST = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_turn_ingress_receipts_request
ON turn_ingress_receipts(source_scope, request_session_key, client_request_id)
"""

_CREATE_IDX_TURN_INGRESS_ACCEPTED_SESSION = """
CREATE INDEX IF NOT EXISTS idx_turn_ingress_receipts_accepted_session
ON turn_ingress_receipts(accepted_session_key, accepted_at)
"""

_CREATE_MEMORY_DURABLE_RECEIPTS = """
CREATE TABLE IF NOT EXISTS memory_durable_receipts (
    receipt_id TEXT PRIMARY KEY,
    session_key TEXT NOT NULL,
    session_id TEXT NOT NULL,
    turn_id TEXT,
    scope TEXT NOT NULL,
    source_path TEXT,
    target_path TEXT,
    content_hash TEXT,
    coverage_turn_id TEXT,
    coverage_hash TEXT,
    coverage_entry_count INTEGER,
    idempotency_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    reason TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at_ms INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1
)
"""

_CREATE_IDX_MEMORY_DURABLE_RECEIPTS_SESSION = (
    "CREATE INDEX IF NOT EXISTS idx_memory_durable_receipts_session "
    "ON memory_durable_receipts(session_key, status, created_at)"
)

_CREATE_IDX_MEMORY_DURABLE_RECEIPTS_COVERAGE = (
    "CREATE INDEX IF NOT EXISTS idx_memory_durable_receipts_coverage "
    "ON memory_durable_receipts("
    "session_key, session_id, scope, status, coverage_turn_id, coverage_hash, "
    "coverage_entry_count"
    ")"
)

_CREATE_EPOCH_ROLLBACK_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS prevent_epoch_rollback
BEFORE UPDATE OF epoch ON sessions
WHEN NEW.epoch < OLD.epoch
BEGIN
    SELECT RAISE(ABORT, 'epoch can only increase');
END
"""

_SQLITE_VARIABLE_CHUNK_SIZE = 900


def _now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def _serialize(value: Any) -> Any:
    """Serialize dict/list fields to JSON string for SQLite TEXT columns."""
    if isinstance(value, dict | list):
        return json.dumps(value)
    if isinstance(value, bool):
        return int(value)
    return value


def _ordered_detail_message_ids(*values: Any) -> list[str]:
    """Normalize persisted-message detail fields without changing order."""

    ordered: list[str] = []
    for value in values:
        candidates = value if isinstance(value, list | tuple) else (value,)
        for candidate in candidates:
            if (
                isinstance(candidate, str)
                and candidate
                and candidate not in ordered
            ):
                ordered.append(candidate)
    return ordered


def _deserialize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Deserialize JSON text fields back to Python objects."""
    json_fields = {
        "delivery_context",
        "tool_calls",
        "turn_usage",
        "origin",
        "details",
        "summary_payload",
        "missing_obligations",
        "critical_carry_forward",
        "payload",
    }
    bool_fields = {
        "total_tokens_fresh",
        "forked_from_parent",
        "fast_mode",
        "portable",
        "cacheable",
        "valid",
    }
    result = {}
    for k, v in row.items():
        if k in json_fields and isinstance(v, str):
            try:
                result[k] = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                result[k] = None
        elif k in bool_fields:
            result[k] = bool(v)
        else:
            result[k] = v
    return result


def _py_lower(value: Any) -> Any:
    """Unicode-aware lowercase for the ``py_lower`` SQL function.

    SQLite's built-in LIKE / lower() only case-fold ASCII, so non-ASCII title /
    content search (Cyrillic, Greek, accented Latin, …) would otherwise be
    case-sensitive. Registered per connection in ``connect``.
    """
    return value.lower() if isinstance(value, str) else value


class SessionStorage:
    """Low-level async SQLite operations for session persistence."""

    def __init__(
        self,
        db_path: str = ":memory:",
        *,
        meta_run_writer: MetaRunWriter | None = None,
    ) -> None:
        self._db_path = db_path
        self._conn: Any | None = None
        self._meta_run_writer = meta_run_writer
        self._operation_lock = asyncio.Lock()
        self._poisoned = False
        self._busy_budget_seconds = _INTERACTIVE_BUSY_BUDGET_SECONDS
        self._sleep = asyncio.sleep
        self._monotonic = time.monotonic
        self._random = random.random

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self._db_path, isolation_level=None)
        self._conn.row_factory = aiosqlite.Row
        # Unicode-aware case folding for non-ASCII LIKE search (see _py_lower).
        # aiosqlite proxies create_function to sqlite3 at runtime; its stub omits it.
        await self._conn.create_function(  # type: ignore[attr-defined]
            "py_lower", 1, _py_lower, deterministic=True
        )
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
        await self._initialize_schema()

    @classmethod
    async def open(cls, db_path: str) -> SessionStorage:
        storage = cls(str(db_path))
        await storage.connect()
        return storage

    async def close(self) -> None:
        async with self._operation_lock:
            if self._conn:
                await self._conn.close()
                self._conn = None

    def _raise_if_poisoned(self) -> None:
        if self._poisoned:
            raise StorageConnectionPoisonedError(
                "Session storage connection is unavailable after rollback failure"
            )

    async def _retire_poisoned_connection(self) -> None:
        self._poisoned = True
        conn, self._conn = self._conn, None
        if conn is not None:
            with contextlib.suppress(BaseException):
                await conn.close()

    async def _finish_sqlite_call(self, awaitable: Awaitable[Any]) -> Any:
        """Do not release the operation gate while a cancelled DB call is still queued."""

        task = asyncio.ensure_future(awaitable)
        cancellation: asyncio.CancelledError | None = None
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError as exc:
                # aiosqlite cancellation does not cancel work already queued on
                # its worker. Keep shielding through repeated cancellation until
                # the call settles, then propagate cancellation to the caller.
                cancellation = cancellation or exc
        if cancellation is not None:
            # Retrieve a settled child result so an operation error is not left
            # unobserved. Cancellation still wins for the interrupted caller;
            # rollback verifies the connection state before deciding it failed.
            with contextlib.suppress(BaseException):
                task.result()
            raise cancellation
        return task.result()

    async def _rollback_transaction(self, conn: Any, operation: str) -> None:
        if not bool(getattr(conn, "in_transaction", False)):
            return
        try:
            await self._finish_sqlite_call(conn.rollback())
        except asyncio.CancelledError as exc:
            # _finish_sqlite_call waits for rollback to settle even through
            # repeated cancellation. A cleared transaction is therefore a
            # successful cleanup, not a poisoned connection.
            if not bool(getattr(conn, "in_transaction", False)):
                raise
            log.error(
                "session_storage.rollback_failed operation=%s error=%s",
                operation,
                type(exc).__name__,
            )
            await self._retire_poisoned_connection()
            raise StorageConnectionPoisonedError(
                f"Session storage rollback failed during {operation}"
            ) from exc
        except BaseException as exc:
            log.error(
                "session_storage.rollback_failed operation=%s error=%s",
                operation,
                type(exc).__name__,
            )
            await self._retire_poisoned_connection()
            raise StorageConnectionPoisonedError(
                f"Session storage rollback failed during {operation}"
            ) from exc

    async def _retry_delay(self, attempt: int, deadline: float) -> None:
        remaining = deadline - self._monotonic()
        if remaining <= 0:
            return
        cap = min(
            _BUSY_RETRY_MAX_SECONDS,
            _BUSY_RETRY_INITIAL_SECONDS * (2 ** min(attempt, 8)),
            remaining,
        )
        await self._sleep(self._random() * cap)

    async def _begin_immediate(
        self,
        conn: Any,
        operation: str,
        deadline: float,
        started: float,
    ) -> None:
        attempt = 0
        while True:
            try:
                await self._finish_sqlite_call(conn.execute("BEGIN IMMEDIATE"))
                return
            except asyncio.CancelledError:
                await self._rollback_transaction(conn, operation)
                raise
            except BaseException as exc:
                if not _is_sqlite_busy(exc):
                    raise
                if self._monotonic() >= deadline:
                    waited_ms = max(0, int((self._monotonic() - started) * 1000))
                    raise StorageBusyError(
                        operation,
                        waited_ms=waited_ms,
                        retry_after_ms=_SQLITE_BUSY_TIMEOUT_MS,
                    ) from exc
                await self._retry_delay(attempt, deadline)
                attempt += 1

    async def _commit_transaction(
        self,
        conn: Any,
        operation: str,
        deadline: float,
        started: float,
    ) -> None:
        attempt = 0
        while True:
            try:
                await self._finish_sqlite_call(conn.commit())
                return
            except asyncio.CancelledError:
                # The shielded commit has settled. If it did not commit, clean up;
                # if it did, the request-id layer above provides replay safety.
                await self._rollback_transaction(conn, operation)
                raise
            except BaseException as exc:
                if not _is_sqlite_busy(exc):
                    raise
                if self._monotonic() >= deadline:
                    waited_ms = max(0, int((self._monotonic() - started) * 1000))
                    raise StorageBusyError(
                        operation,
                        waited_ms=waited_ms,
                        retry_after_ms=_SQLITE_BUSY_TIMEOUT_MS,
                    ) from exc
                await self._retry_delay(attempt, deadline)
                attempt += 1

    @asynccontextmanager
    async def _write_transaction(
        self,
        operation: str,
        *,
        budget_seconds: float | None = None,
    ) -> AsyncIterator[Any]:
        started = self._monotonic()
        budget = self._busy_budget_seconds if budget_seconds is None else budget_seconds
        deadline = started + max(0.0, budget)
        acquired = False
        try:
            remaining = max(0.0, deadline - self._monotonic())
            try:
                # asyncio.timeout(0) still permits an uncontended Lock.acquire
                # to complete synchronously, while refusing to queue behind an
                # existing holder or waiter once the budget is exhausted.
                async with asyncio.timeout(remaining):
                    await self._operation_lock.acquire()
            except TimeoutError as exc:
                raise StorageBusyError(
                    operation,
                    waited_ms=max(0, int((self._monotonic() - started) * 1000)),
                    retry_after_ms=_SQLITE_BUSY_TIMEOUT_MS,
                ) from exc
            acquired = True
            self._raise_if_poisoned()
            conn = self.conn
            await self._begin_immediate(conn, operation, deadline, started)
            try:
                yield conn
                await self._commit_transaction(conn, operation, deadline, started)
            except BaseException:
                await self._rollback_transaction(conn, operation)
                raise
        finally:
            if acquired:
                self._operation_lock.release()

    async def _initialize_schema(self) -> None:
        assert self._conn is not None
        await self._conn.execute(_CREATE_SESSIONS)
        await self._conn.execute(_CREATE_TRANSCRIPT)
        await self._conn.execute(_CREATE_IDX_TRANSCRIPT_SESSION)
        await self._conn.execute(_CREATE_IDX_TRANSCRIPT_KEY)
        await self._conn.execute(_CREATE_IDX_TRANSCRIPT_CURSOR)
        await self._conn.execute(_CREATE_COMPACTED_TRANSCRIPT)
        await self._conn.execute(_CREATE_IDX_COMPACTED_TRANSCRIPT_SESSION)
        await self._conn.execute(_CREATE_IDX_COMPACTED_TRANSCRIPT_KEY)
        await self._conn.execute(_CREATE_IDX_COMPACTED_TRANSCRIPT_CURSOR)
        await self._conn.execute(_CREATE_IDX_COMPACTED_TRANSCRIPT_COMPACTION)
        await self._conn.execute(_CREATE_SUMMARIES)
        await self._conn.execute(_CREATE_IDX_SUMMARIES)
        await self._conn.execute(_CREATE_CONTEXT_STATES)
        await self._conn.execute(_CREATE_IDX_CONTEXT_STATES_SESSION)
        await self._conn.execute(_CREATE_IDX_CONTEXT_STATES_KEY_VALID)
        await self._conn.execute(_CREATE_AGENT_TASKS)
        await self._conn.execute(_CREATE_IDX_AGENT_TASKS_SESSION_STATUS)
        await self._conn.execute(_CREATE_IDX_AGENT_TASKS_STATUS_UPDATED)
        await self._conn.execute(_CREATE_TURN_INGRESS_RECEIPTS)
        await self._conn.execute(_CREATE_IDX_TURN_INGRESS_REQUEST)
        await self._conn.execute(_CREATE_IDX_TURN_INGRESS_ACCEPTED_SESSION)
        await self._conn.execute(_CREATE_MEMORY_DURABLE_RECEIPTS)
        await self._conn.execute(_CREATE_IDX_MEMORY_DURABLE_RECEIPTS_SESSION)
        # FTS5 full-text search index + auto-sync triggers
        await self._conn.execute(_CREATE_TRANSCRIPT_FTS)
        await self._conn.execute(_CREATE_FTS_TRIGGER_INSERT)
        await self._conn.execute(_CREATE_FTS_TRIGGER_DELETE)
        await self._conn.execute(_CREATE_FTS_TRIGGER_UPDATE)
        # Hard DB-level guarantee: epoch can never decrease via UPDATE.
        await self._conn.execute(_CREATE_EPOCH_ROLLBACK_TRIGGER)
        await self._conn.commit()
        # Migrate older databases — add the epoch column if missing.
        await self._migrate_epoch_column()
        await self._migrate_derived_title_column()
        await self._migrate_transcript_reasoning_content_column()
        await self._migrate_transcript_turn_usage_column()
        await self._migrate_summary_metadata_columns()
        await self._migrate_memory_durable_receipt_coverage_columns()
        await self._conn.execute(_CREATE_IDX_MEMORY_DURABLE_RECEIPTS_COVERAGE)
        # Recency index for list_sessions / title search. Guarded on the column
        # because a very old (pre-updated_at) sessions table can survive here
        # without it — connect must not fail on those legacy databases.
        async with self._conn.execute("PRAGMA table_info(sessions)") as cur:
            session_columns = {row[1] for row in await cur.fetchall()}
        if "updated_at" in session_columns:
            await self._conn.execute(_CREATE_IDX_SESSIONS_UPDATED)
        await self._conn.commit()
        await self.mark_abandoned_agent_tasks()

    async def _migrate_epoch_column(self) -> None:
        """Idempotently add the epoch column to an existing sessions table.

        Uses PRAGMA table_info to detect whether the column is already present.
        If absent, ALTER TABLE adds it with DEFAULT 0, then any NULL rows
        (should not exist but guarded anyway) are set to 0.
        """
        assert self._conn is not None
        async with self._conn.execute("PRAGMA table_info(sessions)") as cur:
            columns = [row[1] for row in await cur.fetchall()]
        if "epoch" not in columns:
            await self._conn.execute(
                "ALTER TABLE sessions ADD COLUMN epoch INTEGER NOT NULL DEFAULT 0"
            )
            await self._conn.commit()
        # Defensive: zero-out any NULL epoch rows left by a partial migration.
        async with self._conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE epoch IS NULL"
        ) as cur:
            row = await cur.fetchone()
        null_count = row[0] if row else 0
        if null_count > 0:
            await self._conn.execute(
                "UPDATE sessions SET epoch = 0 WHERE epoch IS NULL"
            )
            await self._conn.commit()

    async def _migrate_derived_title_column(self) -> None:
        """Idempotently add the derived_title column to an existing sessions table.

        Holds the LLM-generated session title. Sits between display_name (manual
        rename) and subject in the title precedence, so it never overrides a name
        the user set by hand. NULL is the natural default (no title generated yet).
        """
        assert self._conn is not None
        async with self._conn.execute("PRAGMA table_info(sessions)") as cur:
            columns = [row[1] for row in await cur.fetchall()]
        if "derived_title" not in columns:
            await self._conn.execute(
                "ALTER TABLE sessions ADD COLUMN derived_title TEXT"
            )
            await self._conn.commit()

    async def _migrate_transcript_reasoning_content_column(self) -> None:
        """Idempotently add assistant reasoning replay storage to transcripts."""
        assert self._conn is not None
        async with self._conn.execute("PRAGMA table_info(transcript_entries)") as cur:
            columns = [row[1] for row in await cur.fetchall()]
        if "reasoning_content" not in columns:
            await self._conn.execute(
                "ALTER TABLE transcript_entries ADD COLUMN reasoning_content TEXT"
            )
            await self._conn.commit()

    async def _migrate_transcript_turn_usage_column(self) -> None:
        """Idempotently add per-turn usage metadata storage to transcripts."""
        assert self._conn is not None
        async with self._conn.execute("PRAGMA table_info(transcript_entries)") as cur:
            columns = [row[1] for row in await cur.fetchall()]
        if "turn_usage" not in columns:
            await self._conn.execute(
                "ALTER TABLE transcript_entries ADD COLUMN turn_usage TEXT"
            )
            await self._conn.commit()

    async def _migrate_summary_metadata_columns(self) -> None:
        """Idempotently add structured compaction summary metadata columns."""
        assert self._conn is not None
        async with self._conn.execute("PRAGMA table_info(session_summaries)") as cur:
            columns = {row[1] for row in await cur.fetchall()}
        additions = {
            "compaction_id": "ALTER TABLE session_summaries ADD COLUMN compaction_id TEXT",
            "trigger_reason": "ALTER TABLE session_summaries ADD COLUMN trigger_reason TEXT",
            "summary_payload": "ALTER TABLE session_summaries ADD COLUMN summary_payload TEXT",
            "summary_format": (
                "ALTER TABLE session_summaries ADD COLUMN "
                "summary_format TEXT NOT NULL DEFAULT 'text'"
            ),
            "summary_source": (
                "ALTER TABLE session_summaries ADD COLUMN "
                "summary_source TEXT NOT NULL DEFAULT 'unknown'"
            ),
            "coverage_status": (
                "ALTER TABLE session_summaries ADD COLUMN "
                "coverage_status TEXT NOT NULL DEFAULT 'unknown'"
            ),
            "missing_obligations": (
                "ALTER TABLE session_summaries ADD COLUMN missing_obligations TEXT"
            ),
            "critical_carry_forward": (
                "ALTER TABLE session_summaries ADD COLUMN critical_carry_forward TEXT"
            ),
            "tokens_before": "ALTER TABLE session_summaries ADD COLUMN tokens_before INTEGER",
            "tokens_after": "ALTER TABLE session_summaries ADD COLUMN tokens_after INTEGER",
            "removed_count": (
                "ALTER TABLE session_summaries ADD COLUMN "
                "removed_count INTEGER NOT NULL DEFAULT 0"
            ),
            "kept_count": (
                "ALTER TABLE session_summaries ADD COLUMN kept_count INTEGER NOT NULL DEFAULT 0"
            ),
            "chunk_count": (
                "ALTER TABLE session_summaries ADD COLUMN chunk_count INTEGER NOT NULL DEFAULT 0"
            ),
            "flush_receipt_status": (
                "ALTER TABLE session_summaries ADD COLUMN "
                "flush_receipt_status TEXT NOT NULL DEFAULT 'unknown'"
            ),
        }
        changed = False
        for column, sql in additions.items():
            if column not in columns:
                await self._conn.execute(sql)
                changed = True
        if changed:
            await self._conn.commit()

    async def _migrate_memory_durable_receipt_coverage_columns(self) -> None:
        """Idempotently add deterministic checkpoint coverage metadata columns."""
        assert self._conn is not None
        async with self._conn.execute("PRAGMA table_info(memory_durable_receipts)") as cur:
            columns = {row[1] for row in await cur.fetchall()}
        additions = {
            "coverage_turn_id": (
                "ALTER TABLE memory_durable_receipts ADD COLUMN coverage_turn_id TEXT"
            ),
            "coverage_hash": (
                "ALTER TABLE memory_durable_receipts ADD COLUMN coverage_hash TEXT"
            ),
            "coverage_entry_count": (
                "ALTER TABLE memory_durable_receipts ADD COLUMN coverage_entry_count INTEGER"
            ),
        }
        changed = False
        for column, sql in additions.items():
            if column not in columns:
                await self._conn.execute(sql)
                changed = True
        if changed:
            await self._conn.commit()

    @property
    def conn(self) -> Any:
        if self._conn is None:
            raise RuntimeError("Storage not connected. Call connect() first.")
        return self._conn

    # ── Session CRUD ────────────────────────────────────────────────────────

    async def upsert_session(self, node: SessionNode) -> None:
        node.session_key = canonicalize_session_key(node.session_key)
        node.agent_id = normalize_agent_id(node.agent_id)
        data = node.model_dump()
        cols = list(data.keys())
        placeholders = ", ".join("?" for _ in cols)
        update_columns = []
        for c in cols:
            if c == "session_key":
                continue
            if c == "epoch":
                # Hard guarantee: epoch can only increase, never roll back.
                update_columns.append("epoch = MAX(sessions.epoch, excluded.epoch)")
            else:
                update_columns.append(f"{c}=excluded.{c}")
        updates = ", ".join(update_columns)
        values = [_serialize(data[c]) for c in cols]
        sql = (
            f"INSERT INTO sessions ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(session_key) DO UPDATE SET {updates}"
        )
        async with self._write_transaction("upsert_session") as conn:
            await conn.execute(sql, values)

    @_serialized_read
    async def get_session(self, session_key: str) -> SessionNode | None:
        session_key = canonicalize_session_key(session_key)
        async with self.conn.execute(
            "SELECT * FROM sessions WHERE session_key = ?", (session_key,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return SessionNode(**_deserialize_row(dict(row)))

    @_serialized_read
    async def list_sessions(
        self,
        agent_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
        spawned_by: str | None = None,
    ) -> list[SessionNode]:
        clauses: list[str] = []
        params: list[Any] = []
        if agent_id is not None:
            clauses.append("sessions.agent_id = ?")
            params.append(normalize_agent_id(agent_id))
        if status is not None:
            clauses.append("sessions.status = ?")
            params.append(status)
        if spawned_by is not None:
            clauses.append("sessions.spawned_by = ?")
            params.append(canonicalize_session_key(spawned_by))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT sessions.*
            FROM sessions
            LEFT JOIN (
                SELECT
                    session_key,
                    MAX(
                        max(
                            max(COALESCE(updated_at, 0), COALESCE(started_at, 0)),
                            COALESCE(created_at, 0)
                        )
                    ) AS active_at
                FROM agent_tasks
                WHERE status IN (?, ?)
                GROUP BY session_key
            ) active_tasks ON active_tasks.session_key = sessions.session_key
            {where}
            ORDER BY
                max(sessions.updated_at, COALESCE(active_tasks.active_at, 0)) DESC,
                sessions.updated_at DESC
            LIMIT ? OFFSET ?
        """
        query_params = [
            AgentTaskStatus.QUEUED.value,
            AgentTaskStatus.RUNNING.value,
            *params,
            limit,
            offset,
        ]
        async with self.conn.execute(sql, query_params) as cur:
            rows = await cur.fetchall()
        return [SessionNode(**_deserialize_row(dict(r))) for r in rows]

    async def delete_session(self, session_key: str) -> None:
        session_key = canonicalize_session_key(session_key)
        session: SessionNode | None = None
        async with self._write_transaction("delete_session") as conn:
            async with conn.execute(
                "SELECT * FROM sessions WHERE session_key = ?", (session_key,)
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                return
            session = SessionNode(**_deserialize_row(dict(row)))
            for table in (
                "transcript_entries",
                "compacted_transcript_entries",
                "session_summaries",
            ):
                await conn.execute(
                    f"DELETE FROM {table} WHERE session_id = ?",  # noqa: S608 - fixed literals
                    (session.session_id,),
                )
            await conn.execute(
                "DELETE FROM session_context_states WHERE session_id = ?",
                (session.session_id,),
            )
            for table in ("router_decisions", "turn_errors"):
                async with conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
                    (table,),
                ) as cur:
                    exists = await cur.fetchone() is not None
                if exists:
                    await conn.execute(
                        f"DELETE FROM {table} WHERE session_key = ?",  # noqa: S608 - fixed literals
                        (session_key,),
                    )
            for table in ("agent_tasks", "memory_durable_receipts"):
                await conn.execute(
                    f"DELETE FROM {table} WHERE session_key = ?",  # noqa: S608 - fixed literals
                    (session_key,),
                )
            await conn.execute(
                "DELETE FROM turn_ingress_receipts WHERE accepted_session_key = ?",
                (session_key,),
            )
            await conn.execute("DELETE FROM sessions WHERE session_key = ?", (session_key,))

        assert session is not None

        # Cascade the on-disk session material (transcript media + workspace
        # attachment copies). DB-only deletion otherwise leaks both stores until
        # the transcript disk budget hard-fails. Best-effort via the registered
        # process-global hook; never fails the delete.
        from opensquilla.session.material_cleanup import run_session_material_cleanup

        await run_session_material_cleanup(session.session_id, session_key)

        # G4 cleanup: cascade meta-skill audit rows for this session. The
        # sessions table is created lazily at runtime (not via yoyo), so
        # there is no SQL FK to rely on — explicit purge is required.
        if self._meta_run_writer is not None:
            try:
                # The writer commits synchronously (busy_timeout=5000); keep the
                # delete off the event loop like every other writer call site.
                await asyncio.to_thread(self._meta_run_writer.purge_for_session, session_key)
            except Exception as exc:  # noqa: BLE001
                log.warning("session_delete.purge_meta_runs_failed: %s", exc)

    async def prune_stale_sessions(self, before_ms: int) -> int:
        """Delete sessions not updated since before_ms epoch ms. Returns count deleted."""
        async with self._operation_lock:
            self._raise_if_poisoned()
            async with self.conn.execute(
                "SELECT session_key FROM sessions WHERE updated_at < ?",
                (before_ms,),
            ) as cur:
                rows = await cur.fetchall()
        session_keys = [row[0] for row in rows]
        for session_key in session_keys:
            await self.delete_session(session_key)
        return len(session_keys)

    @_serialized_read
    async def count_sessions(self) -> int:
        async with self.conn.execute("SELECT COUNT(*) FROM sessions") as cur:
            row = await cur.fetchone()
        return row[0] if row else 0

    async def increment_epoch(self, session_key: str) -> int:
        """Atomically increment the epoch counter for a session.

        Returns the new epoch value. Raises KeyError if the session is not found.
        """
        session_key = canonicalize_session_key(session_key)
        async with self._write_transaction("increment_epoch") as conn:
            await conn.execute(
                "UPDATE sessions SET epoch = epoch + 1 WHERE session_key = ?",
                (session_key,),
            )
            async with conn.execute(
                "SELECT epoch FROM sessions WHERE session_key = ?", (session_key,)
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                raise KeyError(f"Session not found: {session_key}")
            return int(row[0])

    @_serialized_read
    async def get_epoch(self, session_key: str) -> int:
        """Return current epoch for a session (0 if not found)."""
        session_key = canonicalize_session_key(session_key)
        async with self.conn.execute(
            "SELECT epoch FROM sessions WHERE session_key = ?", (session_key,)
        ) as cur:
            row = await cur.fetchone()
        return int(row[0]) if row is not None else 0

    # ── AgentTask ledger CRUD ───────────────────────────────────────────────

    @staticmethod
    async def _insert_agent_task(conn: Any, task: AgentTaskRecord) -> None:
        data = task.model_dump()
        cols = list(data.keys())
        placeholders = ", ".join("?" for _ in cols)
        values = [_serialize(data[col]) for col in cols]
        await conn.execute(
            f"INSERT INTO agent_tasks ({', '.join(cols)}) VALUES ({placeholders})",
            values,
        )

    async def create_agent_task(self, task: AgentTaskRecord) -> AgentTaskRecord:
        task.session_key = canonicalize_session_key(task.session_key)
        task.agent_id = normalize_agent_id(task.agent_id)
        async with self._write_transaction("create_agent_task") as conn:
            await self._insert_agent_task(conn, task)
        return task

    @_serialized_read
    async def get_agent_task(self, task_id: str) -> AgentTaskRecord | None:
        async with self.conn.execute(
            "SELECT * FROM agent_tasks WHERE task_id = ?",
            (task_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return AgentTaskRecord(**_deserialize_row(dict(row)))

    async def update_agent_task(self, task_id: str, **fields: Any) -> AgentTaskRecord:
        if not fields:
            existing = await self.get_agent_task(task_id)
            if existing is None:
                raise KeyError(f"Agent task not found: {task_id}")
            return existing

        allowed = set(AgentTaskRecord.model_fields) - {"task_id", "created_at"}
        unknown = sorted(set(fields) - allowed)
        if unknown:
            raise ValueError(f"Unknown agent task fields: {', '.join(unknown)}")
        fields.setdefault("updated_at", _now_ms())
        assignments = ", ".join(f"{name} = ?" for name in fields)
        values = [_serialize(value) for value in fields.values()]
        values.append(task_id)
        async with self._write_transaction("update_agent_task") as conn:
            await conn.execute(
                f"UPDATE agent_tasks SET {assignments} WHERE task_id = ?",
                values,
            )
            async with conn.execute(
                "SELECT * FROM agent_tasks WHERE task_id = ?", (task_id,)
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                raise KeyError(f"Agent task not found: {task_id}")
            updated = AgentTaskRecord(**_deserialize_row(dict(row)))
        return updated

    @_serialized_read
    async def list_agent_tasks(
        self,
        session_key: str | None = None,
        status: str | AgentTaskStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AgentTaskRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        if session_key is not None:
            clauses.append("session_key = ?")
            params.append(canonicalize_session_key(session_key))
        if status is not None:
            clauses.append("status = ?")
            params.append(str(status))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params += [limit, offset]
        sql = (
            f"SELECT * FROM agent_tasks {where} "
            "ORDER BY created_at ASC, rowid ASC LIMIT ? OFFSET ?"
        )
        async with self.conn.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [AgentTaskRecord(**_deserialize_row(dict(row))) for row in rows]

    async def upsert_memory_durable_receipt(
        self,
        receipt: MemoryDurableReceipt,
    ) -> MemoryDurableReceipt:
        receipt.session_key = canonicalize_session_key(receipt.session_key)
        receipt.updated_at = _now_ms()
        data = receipt.model_dump()
        cols = list(data.keys())
        placeholders = ", ".join("?" for _ in cols)
        updates = ", ".join(
            f"{col}=excluded.{col}"
            for col in cols
            if col not in {"receipt_id", "idempotency_key", "created_at"}
        )
        values = [_serialize(data[col]) for col in cols]
        async with self._write_transaction("upsert_memory_durable_receipt") as conn:
            await conn.execute(
                f"""
                INSERT INTO memory_durable_receipts ({", ".join(cols)})
                VALUES ({placeholders})
                ON CONFLICT(idempotency_key) DO UPDATE SET {updates}
                """,
                values,
            )
            async with conn.execute(
                """
                SELECT * FROM memory_durable_receipts
                WHERE session_key = ? AND idempotency_key = ?
                ORDER BY created_at ASC, rowid ASC
                LIMIT 1
                """,
                (receipt.session_key, receipt.idempotency_key),
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                raise RuntimeError("Upserted memory durable receipt was not readable")
            stored = MemoryDurableReceipt(**_deserialize_row(dict(row)))
        return stored

    @_serialized_read
    async def list_memory_durable_receipts(
        self,
        session_key: str | None = None,
        session_id: str | None = None,
        scope: str | None = None,
        status: str | None = None,
        coverage_turn_id: str | None = None,
        coverage_hash: str | None = None,
        coverage_entry_count: int | None = None,
        idempotency_key: str | None = None,
        limit: int = 100,
    ) -> list[MemoryDurableReceipt]:
        clauses: list[str] = []
        params: list[Any] = []
        if session_key is not None:
            clauses.append("session_key = ?")
            params.append(canonicalize_session_key(session_key))
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        if scope is not None:
            clauses.append("scope = ?")
            params.append(scope)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if coverage_turn_id is not None:
            clauses.append("coverage_turn_id = ?")
            params.append(coverage_turn_id)
        if coverage_hash is not None:
            clauses.append("coverage_hash = ?")
            params.append(coverage_hash)
        if coverage_entry_count is not None:
            clauses.append("coverage_entry_count = ?")
            params.append(coverage_entry_count)
        if idempotency_key is not None:
            clauses.append("idempotency_key = ?")
            params.append(idempotency_key)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        async with self.conn.execute(
            f"""
            SELECT * FROM memory_durable_receipts
            {where}
            ORDER BY created_at ASC, rowid ASC
            LIMIT ?
            """,
            params,
        ) as cur:
            rows = await cur.fetchall()
        return [MemoryDurableReceipt(**_deserialize_row(dict(row))) for row in rows]

    @_serialized_read
    async def list_memory_repair_receipts(
        self,
        *,
        statuses: tuple[str, ...],
        limit: int,
        due_before_ms: int | None = None,
        path: str | None = None,
        session_key_prefix: str | None = None,
    ) -> list[MemoryDurableReceipt]:
        """List repair candidates without bypassing the shared operation gate."""

        if limit <= 0 or not statuses:
            return []
        placeholders = ", ".join("?" for _ in statuses)
        clauses = [f"status IN ({placeholders})"]
        params: list[Any] = [*statuses]
        if due_before_ms is not None:
            clauses.append("(next_retry_at_ms IS NULL OR next_retry_at_ms <= ?)")
            params.append(due_before_ms)
        if path is not None:
            clauses.append("(source_path = ? OR target_path = ?)")
            params.extend((path, path))
        if session_key_prefix is not None:
            clauses.append("substr(session_key, 1, ?) = ?")
            params.extend((len(session_key_prefix), session_key_prefix))
        params.append(limit)
        async with self.conn.execute(
            f"""
            SELECT * FROM memory_durable_receipts
            WHERE {' AND '.join(clauses)}
            ORDER BY
                next_retry_at_ms IS NOT NULL ASC,
                next_retry_at_ms ASC,
                created_at ASC,
                rowid ASC
            LIMIT ?
            """,
            params,
        ) as cur:
            rows = await cur.fetchall()
        return [MemoryDurableReceipt(**_deserialize_row(dict(row))) for row in rows]

    @_serialized_read
    async def list_recent_memory_durable_receipts(
        self,
        *,
        limit: int,
        session_key_prefix: str | None = None,
    ) -> list[MemoryDurableReceipt]:
        """Return the newest durable receipts under the storage read gate."""

        if limit <= 0:
            return []
        clauses: list[str] = []
        params: list[Any] = []
        if session_key_prefix is not None:
            clauses.append("substr(session_key, 1, ?) = ?")
            params.extend((len(session_key_prefix), session_key_prefix))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        async with self.conn.execute(
            f"""
            SELECT * FROM memory_durable_receipts
            {where}
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
            """,
            params,
        ) as cur:
            rows = await cur.fetchall()
        return [MemoryDurableReceipt(**_deserialize_row(dict(row))) for row in rows]

    @_serialized_read
    async def memory_durable_receipt_exists_for_path(
        self,
        path: str,
        *,
        session_key_prefix: str | None = None,
    ) -> bool:
        """Check source/target path identity without exposing the raw connection."""

        clauses = ["(source_path = ? OR target_path = ?)"]
        params: list[Any] = [path, path]
        if session_key_prefix is not None:
            clauses.append("substr(session_key, 1, ?) = ?")
            params.extend((len(session_key_prefix), session_key_prefix))
        async with self.conn.execute(
            f"""
            SELECT 1 FROM memory_durable_receipts
            WHERE {' AND '.join(clauses)}
            LIMIT 1
            """,
            params,
        ) as cur:
            return await cur.fetchone() is not None

    async def claim_memory_repair_receipt(
        self,
        receipt_id: str,
        *,
        eligible_statuses: tuple[str, ...],
        claimed_status: str,
        now_ms: int,
    ) -> MemoryDurableReceipt | None:
        """Atomically claim one due repair receipt and return the claimed row."""

        if not eligible_statuses:
            return None
        placeholders = ", ".join("?" for _ in eligible_statuses)
        async with self._write_transaction("claim_memory_repair_receipt") as conn:
            async with conn.execute(
                f"""
                UPDATE memory_durable_receipts
                SET status = ?, updated_at = ?
                WHERE receipt_id = ?
                  AND status IN ({placeholders})
                  AND (next_retry_at_ms IS NULL OR next_retry_at_ms <= ?)
                """,
                (
                    claimed_status,
                    now_ms,
                    receipt_id,
                    *eligible_statuses,
                    now_ms,
                ),
            ) as cur:
                claimed = cur.rowcount or 0
            if claimed != 1:
                return None
            async with conn.execute(
                "SELECT * FROM memory_durable_receipts WHERE receipt_id = ?",
                (receipt_id,),
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                raise RuntimeError("Claimed memory repair receipt was not readable")
            return MemoryDurableReceipt(**_deserialize_row(dict(row)))

    async def recover_stale_memory_repair_claims(
        self,
        *,
        running_status: str,
        pending_status: str,
        stale_before_ms: int,
        next_retry_at_ms: int,
        updated_at_ms: int,
        reason: str,
    ) -> int:
        """Move stale repair claims back to pending in one explicit transaction."""

        async with self._write_transaction("recover_stale_memory_repair_claims") as conn:
            async with conn.execute(
                """
                UPDATE memory_durable_receipts
                SET status = ?,
                    reason = ?,
                    next_retry_at_ms = ?,
                    updated_at = ?
                WHERE status = ?
                  AND updated_at <= ?
                """,
                (
                    pending_status,
                    reason,
                    next_retry_at_ms,
                    updated_at_ms,
                    running_status,
                    stale_before_ms,
                ),
            ) as cur:
                return int(cur.rowcount or 0)

    async def update_memory_durable_receipt(
        self,
        receipt_id: str,
        **fields: Any,
    ) -> MemoryDurableReceipt:
        allowed = set(MemoryDurableReceipt.model_fields) - {"receipt_id", "created_at"}
        unknown = sorted(set(fields) - allowed)
        if unknown:
            raise ValueError(
                f"Unknown memory durable receipt fields: {', '.join(unknown)}"
            )
        if "session_key" in fields:
            fields["session_key"] = canonicalize_session_key(fields["session_key"])
        fields.setdefault("updated_at", _now_ms())
        assignments = ", ".join(f"{name} = ?" for name in fields)
        values = [_serialize(value) for value in fields.values()]
        values.append(receipt_id)
        async with self._write_transaction("update_memory_durable_receipt") as conn:
            await conn.execute(
                f"UPDATE memory_durable_receipts SET {assignments} WHERE receipt_id = ?",
                values,
            )
            async with conn.execute(
                "SELECT * FROM memory_durable_receipts WHERE receipt_id = ?",
                (receipt_id,),
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                raise KeyError(f"Memory durable receipt not found: {receipt_id}")
            updated = MemoryDurableReceipt(**_deserialize_row(dict(row)))
        return updated

    @_serialized_read
    async def list_agent_tasks_for_sessions(
        self,
        session_keys: list[str],
        limit_per_session: int = 100,
    ) -> dict[str, list[AgentTaskRecord]]:
        keys = list(dict.fromkeys(canonicalize_session_key(key) for key in session_keys))
        grouped: dict[str, list[AgentTaskRecord]] = {key: [] for key in keys}
        if not keys or limit_per_session <= 0:
            return grouped

        for index in range(0, len(keys), _SQLITE_VARIABLE_CHUNK_SIZE):
            chunk = keys[index : index + _SQLITE_VARIABLE_CHUNK_SIZE]
            placeholders = ", ".join("?" for _ in chunk)
            # Session-list/subagent summaries never inspect task details. Keep
            # durable channel outbox content out of this high-fanout batch read;
            # exact replay still uses get_agent_task(), which selects all fields.
            summary_columns = ", ".join(
                name for name in AgentTaskRecord.model_fields if name != "details"
            )
            sql = (
                f"SELECT {summary_columns} FROM agent_tasks "
                f"WHERE session_key IN ({placeholders}) "
                "ORDER BY session_key ASC, created_at DESC, rowid DESC"
            )
            async with self.conn.execute(sql, chunk) as cur:
                rows = await cur.fetchall()

            for row in rows:
                task = AgentTaskRecord(**_deserialize_row(dict(row)))
                bucket = grouped.setdefault(task.session_key, [])
                if len(bucket) < limit_per_session:
                    bucket.append(task)
        return grouped

    async def mark_abandoned_agent_tasks(self, now_ms: int | None = None) -> int:
        """Mark non-terminal persisted tasks as abandoned after process restart."""
        ts = now_ms or _now_ms()
        async with self._write_transaction("mark_abandoned_agent_tasks") as conn:
            cur = await conn.execute(
                """
                UPDATE agent_tasks
                SET status = ?,
                    updated_at = ?,
                    finished_at = COALESCE(finished_at, ?),
                    terminal_reason = COALESCE(terminal_reason, ?)
                WHERE status IN (?, ?)
                """,
                (
                    AgentTaskStatus.ABANDONED,
                    ts,
                    ts,
                    "process_restart",
                    AgentTaskStatus.QUEUED,
                    AgentTaskStatus.RUNNING,
                ),
            )
            count = int(cur.rowcount if cur.rowcount is not None else 0)
        return count

    # ── Transcript CRUD ──────────────────────────────────────────────────────

    @staticmethod
    async def _raise_stale_epoch(
        conn: Any,
        *,
        session_key: str,
        expected_epoch: int,
    ) -> None:
        async with conn.execute(
            "SELECT epoch FROM sessions WHERE session_key = ?",
            (session_key,),
        ) as cur:
            row = await cur.fetchone()
        actual = int(row[0]) if row is not None else None
        raise StaleEpochError(
            f"Epoch mismatch for {session_key}: expected {expected_epoch}, got {actual}"
        )

    @classmethod
    async def _insert_transcript_entry(
        cls,
        conn: Any,
        entry: TranscriptEntry,
        *,
        expected_epoch: int | None,
    ) -> None:
        data = entry.model_dump(exclude={"id"})
        cols = list(data.keys())
        placeholders = ", ".join("?" for _ in cols)
        values = [_serialize(data[c]) for c in cols]

        if expected_epoch is None:
            await conn.execute(
                f"INSERT INTO transcript_entries ({', '.join(cols)}) "
                f"VALUES ({placeholders})",
                values,
            )
            return

        insert_sql = (
            f"INSERT INTO transcript_entries ({', '.join(cols)}) "
            f"SELECT {placeholders} "
            "WHERE EXISTS ("
            "  SELECT 1 FROM sessions "
            "  WHERE session_key = ? AND epoch = ?"
            ")"
        )
        async with conn.execute(
            insert_sql,
            values + [entry.session_key, expected_epoch],
        ) as cur:
            inserted = cur.rowcount or 0
        if inserted == 0:
            await cls._raise_stale_epoch(
                conn,
                session_key=entry.session_key,
                expected_epoch=expected_epoch,
            )

    async def append_transcript_entry(
        self, entry: TranscriptEntry, *, expected_epoch: int | None = None
    ) -> None:
        entry.session_key = canonicalize_session_key(entry.session_key)
        async with self._write_transaction("append_transcript_entry") as conn:
            await self._insert_transcript_entry(
                conn,
                entry,
                expected_epoch=expected_epoch,
            )

    async def append_transcript_entry_and_touch(
        self,
        entry: TranscriptEntry,
        *,
        expected_epoch: int,
        updated_at: int,
        token_delta: int = 0,
        mark_total_tokens_stale: bool = False,
    ) -> None:
        """Append one entry and narrowly touch its session in one transaction."""

        entry.session_key = canonicalize_session_key(entry.session_key)
        async with self._write_transaction("append_transcript_entry_and_touch") as conn:
            await self._insert_transcript_entry(
                conn,
                entry,
                expected_epoch=expected_epoch,
            )
            async with conn.execute(
                """
                UPDATE sessions
                SET updated_at = ?,
                    total_tokens = total_tokens + ?,
                    total_tokens_fresh = CASE WHEN ? THEN 0 ELSE total_tokens_fresh END
                WHERE session_key = ? AND epoch = ?
                """,
                (
                    updated_at,
                    token_delta,
                    int(mark_total_tokens_stale),
                    entry.session_key,
                    expected_epoch,
                ),
            ) as cur:
                touched = cur.rowcount or 0
            if touched == 0:
                await self._raise_stale_epoch(
                    conn,
                    session_key=entry.session_key,
                    expected_epoch=expected_epoch,
                )

    @staticmethod
    async def _select_canonical_transcript(
        conn: Any,
        session_id: str,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[TranscriptEntry]:
        """Read compacted archive rows plus the active tail on one connection."""

        limit_val = limit if limit is not None else -1
        sql = """
            SELECT
                original_entry_id AS id,
                session_id,
                session_key,
                message_id,
                role,
                content,
                tool_calls,
                tool_call_id,
                reasoning_content,
                turn_usage,
                created_at,
                token_count,
                provenance_kind,
                provenance_origin_session_id,
                provenance_source_session_key,
                provenance_source_channel,
                provenance_source_tool,
                schema_version
            FROM compacted_transcript_entries
            WHERE session_id = ?
            UNION ALL
            SELECT
                id,
                session_id,
                session_key,
                message_id,
                role,
                content,
                tool_calls,
                tool_call_id,
                reasoning_content,
                turn_usage,
                created_at,
                token_count,
                provenance_kind,
                provenance_origin_session_id,
                provenance_source_session_key,
                provenance_source_channel,
                provenance_source_tool,
                schema_version
            FROM transcript_entries
            WHERE session_id = ?
            ORDER BY created_at ASC, id ASC
            LIMIT ? OFFSET ?
        """
        async with conn.execute(
            sql,
            (session_id, session_id, limit_val, offset),
        ) as cur:
            rows = await cur.fetchall()
        return [TranscriptEntry(**_deserialize_row(dict(row))) for row in rows]

    @staticmethod
    async def _select_all_summaries(
        conn: Any,
        session_id: str,
    ) -> list[SessionSummary]:
        """Read all summaries on an existing operation/transaction connection."""

        async with conn.execute(
            "SELECT * FROM session_summaries WHERE session_id = ? "
            "ORDER BY compaction_index ASC",
            (session_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [SessionSummary(**_deserialize_row(dict(row))) for row in rows]

    @staticmethod
    async def _select_turn_ingress_receipt(
        conn: Any,
        *,
        source_scope: str,
        request_session_key: str,
        client_request_id: str,
    ) -> tuple[TurnIngressReceipt, AgentTaskStatus | None, bool] | None:
        async with conn.execute(
            """
            SELECT receipt.*, task.status AS accepted_task_status,
                   task.details AS accepted_task_details
            FROM turn_ingress_receipts AS receipt
            LEFT JOIN agent_tasks AS task ON task.task_id = receipt.task_id
            WHERE receipt.source_scope = ?
              AND receipt.request_session_key = ?
              AND receipt.client_request_id = ?
            """,
            (source_scope, request_session_key, client_request_id),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        raw = dict(row)
        task_status_raw = raw.pop("accepted_task_status", None)
        task_details_raw = raw.pop("accepted_task_details", None)
        task_status = (
            AgentTaskStatus(task_status_raw) if task_status_raw is not None else None
        )
        task_details: dict[str, Any] = {}
        if isinstance(task_details_raw, str):
            with contextlib.suppress(json.JSONDecodeError, TypeError):
                parsed = json.loads(task_details_raw)
                if isinstance(parsed, dict):
                    task_details = parsed
        receipt = TurnIngressReceipt(**_deserialize_row(raw))
        return receipt, task_status, bool(task_details.get("fresh_user_session", False))

    @_serialized_read
    async def get_turn_ingress_receipt(
        self,
        *,
        source_scope: str,
        request_session_key: str,
        client_request_id: str,
    ) -> TurnAcceptanceResult | None:
        """Look up an accepted request before re-running destructive ingest work."""

        selected = await self._select_turn_ingress_receipt(
            self.conn,
            source_scope=source_scope,
            request_session_key=canonicalize_session_key(request_session_key),
            client_request_id=client_request_id,
        )
        if selected is None:
            return None
        receipt, task_status, fresh_user_session = selected
        return TurnAcceptanceResult(
            receipt=receipt,
            replayed=True,
            fresh_user_session=fresh_user_session,
            task_status=task_status,
        )

    async def accept_turn(
        self,
        entry: TranscriptEntry,
        *,
        expected_epoch: int,
        updated_at: int,
        task_record: AgentTaskRecord,
        source_scope: str,
        request_session_key: str,
        client_request_id: str,
        request_fingerprint: str,
        session_node: SessionNode | None = None,
        reset_from_session_id: str | None = None,
        initial_transcript_entries: tuple[TranscriptEntry, ...] = (),
        session_updates: dict[str, Any] | None = None,
        merge_into_task: bool = False,
    ) -> TurnAcceptanceResult:
        """Commit one user message, task, and request receipt atomically.

        Repeating the same scoped client request returns the original receipt.
        Reusing its id for a different payload is rejected before any write.
        """

        source_scope = source_scope.strip()
        client_request_id = client_request_id.strip()
        if not source_scope:
            raise ValueError("source_scope is required")
        if not client_request_id:
            raise ValueError("client_request_id is required")
        if not request_fingerprint:
            raise ValueError("request_fingerprint is required")

        request_session_key = canonicalize_session_key(request_session_key)
        entry.session_key = canonicalize_session_key(entry.session_key)
        task_record.session_key = canonicalize_session_key(task_record.session_key)
        task_record.agent_id = normalize_agent_id(task_record.agent_id)
        if task_record.session_key != entry.session_key:
            raise ValueError("task and transcript session keys must match")
        if session_node is not None:
            session_node.session_key = canonicalize_session_key(session_node.session_key)
            session_node.agent_id = normalize_agent_id(session_node.agent_id)
            if session_node.session_key != entry.session_key:
                raise ValueError("prepared session and transcript session keys must match")
            if session_node.session_id != entry.session_id:
                raise ValueError("prepared session and transcript session ids must match")
        elif reset_from_session_id is not None:
            raise ValueError("reset_from_session_id requires session_node")
        if initial_transcript_entries and session_node is None:
            raise ValueError("initial transcript entries require session_node")
        if merge_into_task and session_node is not None:
            raise ValueError("task collection cannot create, reset, or fork a session")
        allowed_session_updates = {
            "last_channel",
            "last_to",
            "last_account_id",
            "last_thread_id",
            "delivery_context",
        }
        session_updates = dict(session_updates or {})
        unknown_session_updates = sorted(set(session_updates) - allowed_session_updates)
        if unknown_session_updates:
            raise ValueError(
                "Unsupported atomic session updates: "
                + ", ".join(unknown_session_updates)
            )

        async with self._write_transaction("accept_turn") as conn:
            selected = await self._select_turn_ingress_receipt(
                conn,
                source_scope=source_scope,
                request_session_key=request_session_key,
                client_request_id=client_request_id,
            )
            if selected is not None:
                receipt, task_status, fresh_user_session = selected
                if receipt.request_fingerprint != request_fingerprint:
                    raise TurnIngressConflictError(
                        "client_request_id was already used for a different turn"
                    )
                return TurnAcceptanceResult(
                    receipt=receipt,
                    replayed=True,
                    fresh_user_session=fresh_user_session,
                    task_status=task_status,
                )

            reset_archive_snapshot: ResetArchiveSnapshot | None = None
            if session_node is not None:
                session_data = session_node.model_dump()
                if reset_from_session_id is None:
                    session_cols = list(session_data.keys())
                    session_placeholders = ", ".join("?" for _ in session_cols)
                    await conn.execute(
                        f"INSERT INTO sessions ({', '.join(session_cols)}) "
                        f"VALUES ({session_placeholders})",
                        [_serialize(session_data[col]) for col in session_cols],
                    )
                else:
                    previous_epoch = max(0, expected_epoch - 1)
                    async with conn.execute(
                        """
                        SELECT *
                        FROM sessions
                        WHERE session_key = ? AND session_id = ? AND epoch = ?
                        """,
                        (
                            session_node.session_key,
                            reset_from_session_id,
                            previous_epoch,
                        ),
                    ) as cur:
                        previous_row = await cur.fetchone()
                    if previous_row is None:
                        await self._raise_stale_epoch(
                            conn,
                            session_key=session_node.session_key,
                            expected_epoch=previous_epoch,
                        )
                    assert previous_row is not None
                    previous_node = SessionNode(
                        **_deserialize_row(dict(previous_row))
                    )
                    reset_archive_snapshot = ResetArchiveSnapshot(
                        node=previous_node,
                        entries=tuple(
                            await self._select_canonical_transcript(
                                conn,
                                reset_from_session_id,
                            )
                        ),
                        summaries=tuple(
                            await self._select_all_summaries(
                                conn,
                                reset_from_session_id,
                            )
                        ),
                    )
                    assignments = [
                        f"{column} = ?"
                        for column in session_data
                        if column != "session_key"
                    ]
                    values = [
                        _serialize(value)
                        for column, value in session_data.items()
                        if column != "session_key"
                    ]
                    async with conn.execute(
                        f"UPDATE sessions SET {', '.join(assignments)} "
                        "WHERE session_key = ? AND session_id = ? AND epoch = ?",
                        [
                            *values,
                            session_node.session_key,
                            reset_from_session_id,
                            previous_epoch,
                        ],
                    ) as cur:
                        rotated = cur.rowcount or 0
                    if rotated == 0:
                        await self._raise_stale_epoch(
                            conn,
                            session_key=session_node.session_key,
                            expected_epoch=previous_epoch,
                        )
                    for table in (
                        "transcript_entries",
                        "compacted_transcript_entries",
                        "session_summaries",
                    ):
                        await conn.execute(
                            f"DELETE FROM {table} WHERE session_id = ?",  # noqa: S608
                            (reset_from_session_id,),
                        )
                    await conn.execute(
                        """
                        UPDATE session_context_states
                        SET valid = 0, invalid_reason = 'session_reset'
                        WHERE session_key = ? AND valid = 1
                        """,
                        (session_node.session_key,),
                    )

            for initial_entry in initial_transcript_entries:
                initial_entry.session_key = canonicalize_session_key(
                    initial_entry.session_key
                )
                if (
                    initial_entry.session_key != entry.session_key
                    or initial_entry.session_id != entry.session_id
                ):
                    raise ValueError(
                        "initial transcript entries must target the accepted session"
                    )
                await self._insert_transcript_entry(
                    conn,
                    initial_entry,
                    expected_epoch=expected_epoch,
                )

            async with conn.execute(
                "SELECT 1 FROM transcript_entries WHERE session_id = ? LIMIT 1",
                (entry.session_id,),
            ) as cur:
                fresh_user_session = await cur.fetchone() is None

            await self._insert_transcript_entry(
                conn,
                entry,
                expected_epoch=expected_epoch,
            )
            touch_fields = {"updated_at": updated_at, **session_updates}
            touch_assignments = ", ".join(f"{name} = ?" for name in touch_fields)
            touch_values = [_serialize(value) for value in touch_fields.values()]
            async with conn.execute(
                f"UPDATE sessions SET {touch_assignments} "  # noqa: S608 - fixed allowlist
                "WHERE session_key = ? AND session_id = ? AND epoch = ?",
                [
                    *touch_values,
                    entry.session_key,
                    entry.session_id,
                    expected_epoch,
                ],
            ) as cur:
                touched = cur.rowcount or 0
            if touched == 0:
                await self._raise_stale_epoch(
                    conn,
                    session_key=entry.session_key,
                    expected_epoch=expected_epoch,
                )

            incoming_details = dict(task_record.details or {})
            if merge_into_task:
                async with conn.execute(
                    """
                    SELECT details
                    FROM agent_tasks
                    WHERE task_id = ? AND session_key = ? AND status = ?
                    """,
                    (
                        task_record.task_id,
                        task_record.session_key,
                        AgentTaskStatus.QUEUED.value,
                    ),
                ) as cur:
                    existing_row = await cur.fetchone()
                if existing_row is None:
                    raise TaskCollectionUnavailableError(
                        "The target task is no longer queued for collection"
                    )
                deserialized = _deserialize_row({"details": existing_row["details"]})
                existing_details_raw = deserialized.get("details")
                existing_details = (
                    dict(existing_details_raw)
                    if isinstance(existing_details_raw, dict)
                    else {}
                )
                details = {**existing_details, **incoming_details}
                message_ids = _ordered_detail_message_ids(
                    existing_details.get("persisted_user_message_id"),
                    existing_details.get("persisted_user_message_ids"),
                    incoming_details.get("persisted_user_message_id"),
                    incoming_details.get("persisted_user_message_ids"),
                    entry.message_id,
                )
                existing_count = existing_details.get("message_count")
                incoming_count = incoming_details.get("message_count")
                existing_count = (
                    existing_count
                    if isinstance(existing_count, int) and existing_count > 0
                    else 0
                )
                incoming_count = (
                    incoming_count
                    if isinstance(incoming_count, int) and incoming_count > 0
                    else 0
                )
                details["persisted_user_message_id"] = (
                    message_ids[0] if message_ids else entry.message_id
                )
                details["persisted_user_message_ids"] = message_ids
                details["message_count"] = max(
                    1,
                    incoming_count,
                    existing_count + 1,
                )
                details["fresh_user_session"] = existing_details.get(
                    "fresh_user_session",
                    fresh_user_session,
                )
                task_record.details = details
                async with conn.execute(
                    """
                    UPDATE agent_tasks
                    SET details = ?, updated_at = ?
                    WHERE task_id = ? AND session_key = ? AND status = ?
                    """,
                    (
                        _serialize(details),
                        task_record.updated_at,
                        task_record.task_id,
                        task_record.session_key,
                        AgentTaskStatus.QUEUED.value,
                    ),
                ) as cur:
                    merged = cur.rowcount or 0
                if merged == 0:
                    raise TaskCollectionUnavailableError(
                        "The target task is no longer queued for collection"
                    )
            else:
                message_ids = _ordered_detail_message_ids(
                    entry.message_id,
                    incoming_details.get("persisted_user_message_id"),
                    incoming_details.get("persisted_user_message_ids"),
                )
                incoming_count = incoming_details.get("message_count")
                details = dict(incoming_details)
                details["persisted_user_message_id"] = entry.message_id
                details["persisted_user_message_ids"] = message_ids
                details["message_count"] = (
                    incoming_count
                    if isinstance(incoming_count, int) and incoming_count > 0
                    else 1
                )
                details["fresh_user_session"] = fresh_user_session
                task_record.details = details
                await self._insert_agent_task(conn, task_record)

            receipt = TurnIngressReceipt(
                source_scope=source_scope,
                request_session_key=request_session_key,
                client_request_id=client_request_id,
                request_fingerprint=request_fingerprint,
                accepted_session_key=entry.session_key,
                session_id=entry.session_id,
                message_id=entry.message_id,
                task_id=task_record.task_id,
            )
            data = receipt.model_dump()
            cols = list(data.keys())
            placeholders = ", ".join("?" for _ in cols)
            await conn.execute(
                f"INSERT INTO turn_ingress_receipts ({', '.join(cols)}) "
                f"VALUES ({placeholders})",
                [_serialize(data[col]) for col in cols],
            )
            return TurnAcceptanceResult(
                receipt=receipt,
                replayed=False,
                fresh_user_session=fresh_user_session,
                task_status=task_record.status,
                reset_archive_snapshot=reset_archive_snapshot,
            )

    @_serialized_read
    async def get_transcript(
        self, session_id: str, limit: int | None = None, offset: int = 0
    ) -> list[TranscriptEntry]:
        # SQLite requires LIMIT before OFFSET; use -1 for unlimited
        limit_val = limit if limit is not None else -1
        sql = (
            "SELECT * FROM transcript_entries WHERE session_id = ? "
            "ORDER BY created_at ASC, id ASC LIMIT ? OFFSET ?"
        )
        async with self.conn.execute(sql, (session_id, limit_val, offset)) as cur:
            rows = await cur.fetchall()
        return [TranscriptEntry(**_deserialize_row(dict(r))) for r in rows]

    @_serialized_read
    async def get_canonical_transcript(
        self, session_id: str, limit: int | None = None, offset: int = 0
    ) -> list[TranscriptEntry]:
        """Return archived compacted rows plus the active transcript tail.

        Provider replay intentionally keeps using get_transcript(). This API is
        for recovery, diagnostics, and future provider-view construction where
        the raw transcript needs to survive destructive compaction rewrites.
        """
        return await self._select_canonical_transcript(
            self.conn,
            session_id,
            limit=limit,
            offset=offset,
        )

    async def _canonical_transcript_cursor_exists(
        self,
        session_id: str,
        cursor: tuple[int, int],
    ) -> bool:
        created_at, entry_id = cursor
        sql = """
            SELECT 1
            FROM transcript_entries
            WHERE session_id = ? AND created_at = ? AND id = ?
            UNION ALL
            SELECT 1
            FROM compacted_transcript_entries
            WHERE session_id = ? AND created_at = ? AND original_entry_id = ?
            LIMIT 1
        """
        async with self.conn.execute(
            sql,
            (session_id, created_at, entry_id, session_id, created_at, entry_id),
        ) as cur:
            return await cur.fetchone() is not None

    @_serialized_read
    async def get_canonical_transcript_page(
        self,
        session_id: str,
        *,
        limit: int,
        before: tuple[int, int] | None = None,
        after: tuple[int, int] | None = None,
    ) -> tuple[list[TranscriptEntry], bool]:
        """Return one keyset page across archived and active transcript rows.

        Each source CTE is bounded to ``limit + 1`` rows and both are merged in
        one SQLite read snapshot. ``before`` keeps its historical precedence
        over ``after`` when both cursors exist; an unknown cursor is ignored,
        matching the legacy list-pagination path.
        """
        page_size = max(1, int(limit))
        fetch_size = page_size + 1

        resolved_before = before
        if resolved_before is not None and not await self._canonical_transcript_cursor_exists(
            session_id,
            resolved_before,
        ):
            resolved_before = None

        resolved_after = None
        if resolved_before is None and after is not None:
            if await self._canonical_transcript_cursor_exists(session_id, after):
                resolved_after = after

        cursor = resolved_before or resolved_after
        ascending = resolved_after is not None
        comparator = ">" if ascending else "<"
        direction = "ASC" if ascending else "DESC"

        active_params: list[Any] = [session_id]
        active_cursor_clause = ""
        if cursor is not None:
            created_at, entry_id = cursor
            active_cursor_clause = (
                f"AND (created_at {comparator} ? "
                f"OR (created_at = ? AND id {comparator} ?))"
            )
            active_params.extend((created_at, created_at, entry_id))
        active_params.append(fetch_size)
        archived_params: list[Any] = [session_id]
        archived_cursor_clause = ""
        if cursor is not None:
            created_at, entry_id = cursor
            archived_cursor_clause = (
                f"AND (created_at {comparator} ? "
                f"OR (created_at = ? AND original_entry_id {comparator} ?))"
            )
            archived_params.extend((created_at, created_at, entry_id))
        archived_params.append(fetch_size)
        sql = f"""
            WITH active_page AS (
                SELECT
                    id,
                    session_id,
                    session_key,
                    message_id,
                    role,
                    content,
                    tool_calls,
                    tool_call_id,
                    reasoning_content,
                    turn_usage,
                    created_at,
                    token_count,
                    provenance_kind,
                    provenance_origin_session_id,
                    provenance_source_session_key,
                    provenance_source_channel,
                    provenance_source_tool,
                    schema_version
                FROM transcript_entries
                WHERE session_id = ?
                  {active_cursor_clause}
                ORDER BY created_at {direction}, id {direction}
                LIMIT ?
            ),
            archived_page AS (
                SELECT
                    original_entry_id AS id,
                    session_id,
                    session_key,
                    message_id,
                    role,
                    content,
                    tool_calls,
                    tool_call_id,
                    reasoning_content,
                    turn_usage,
                    created_at,
                    token_count,
                    provenance_kind,
                    provenance_origin_session_id,
                    provenance_source_session_key,
                    provenance_source_channel,
                    provenance_source_tool,
                    schema_version
                FROM compacted_transcript_entries
                WHERE session_id = ?
                  {archived_cursor_clause}
                ORDER BY
                    created_at {direction},
                    original_entry_id {direction},
                    id {direction}
                LIMIT ?
            ),
            merged AS (
                SELECT * FROM active_page
                UNION ALL
                SELECT * FROM archived_page
            )
            SELECT *
            FROM merged
            ORDER BY created_at {direction}, id {direction}
            LIMIT ?
        """

        # Both sources must be read by one SQLite statement. A compaction moves
        # rows from transcript_entries into compacted_transcript_entries inside
        # one transaction; separate SELECT statements could otherwise observe
        # opposite sides of that move and duplicate or omit canonical rows.
        params = [*active_params, *archived_params, fetch_size]
        async with self.conn.execute(sql, params) as cur:
            rows = await cur.fetchall()

        entries = [TranscriptEntry(**_deserialize_row(dict(row))) for row in rows]
        has_more = len(entries) > page_size
        entries = entries[:page_size]
        if not ascending:
            entries.reverse()
        return entries, has_more

    @_serialized_read
    async def get_canonical_transcript_coverage(
        self,
        session_id: str,
    ) -> CanonicalTranscriptCoverage:
        """Read canonical coverage and current session metadata in one snapshot."""
        sql = """
            SELECT
                session.compaction_count,
                session.forked_from_parent,
                session.schema_version,
                (SELECT COUNT(*)
                 FROM session_summaries
                 WHERE session_id = session.session_id) AS summary_count,
                (SELECT COALESCE(SUM(removed_count), 0)
                 FROM session_summaries
                 WHERE session_id = session.session_id) AS removed_count,
                (SELECT COUNT(*)
                 FROM compacted_transcript_entries
                 WHERE session_id = session.session_id) AS archived_count,
                (SELECT COUNT(*)
                 FROM compacted_transcript_entries
                 WHERE session_id = session.session_id
                   AND original_entry_id IS NULL) AS missing_ids,
                (SELECT COUNT(*)
                 FROM session_summaries AS summary
                 WHERE summary.session_id = session.session_id
                   AND (
                     summary.compaction_id IS NULL
                     OR (summary.removed_count = 0 AND summary.covered_through_id > 0)
                     OR COALESCE((
                       SELECT COUNT(*)
                       FROM compacted_transcript_entries AS archived
                       WHERE archived.session_id = summary.session_id
                         AND archived.compaction_id = summary.compaction_id
                     ), 0) != summary.removed_count
                   )) AS mismatched_summaries
            FROM sessions AS session
            WHERE session.session_id = ?
            LIMIT 1
        """
        async with self.conn.execute(sql, (session_id,)) as cur:
            row = await cur.fetchone()
        if row is None:
            return CanonicalTranscriptCoverage(
                canonical_complete=False,
                compaction_count=0,
                inherited_compactions=False,
            )
        summary_count = int(row["summary_count"] or 0)
        expected_compactions = max(0, int(row["compaction_count"] or 0))
        inherited_compactions = bool(row["forked_from_parent"])
        archived_count = int(row["archived_count"] or 0)
        fork_coverage_proven = not inherited_compactions
        if inherited_compactions:
            # A legacy fork stored only a reusable parent session key, not the
            # fork-time parent identity or coverage. Never let the parent's
            # current row—or the child's later compactions—retroactively prove
            # that an ambiguous inherited prefix retained every original row.
            fork_coverage_proven = (
                int(row["schema_version"] or 0)
                >= CANONICAL_FORK_PROOF_SCHEMA_VERSION
            )
        compaction_count_matches = (
            summary_count >= expected_compactions
            if inherited_compactions
            else summary_count == expected_compactions
        )
        canonical_complete = (
            fork_coverage_proven
            and compaction_count_matches
            and int(row["removed_count"] or 0) == archived_count
            and int(row["missing_ids"] or 0) == 0
            and int(row["mismatched_summaries"] or 0) == 0
        )
        return CanonicalTranscriptCoverage(
            canonical_complete=canonical_complete,
            compaction_count=expected_compactions,
            inherited_compactions=inherited_compactions,
        )

    async def is_canonical_transcript_complete(self, session_id: str) -> bool:
        """Return whether every current compaction has a complete raw archive."""
        coverage = await self.get_canonical_transcript_coverage(session_id)
        return coverage.canonical_complete

    async def copy_compacted_transcript_entries(
        self,
        *,
        source_session_id: str,
        target_session_id: str,
        target_session_key: str,
    ) -> None:
        """Copy archived compacted transcript rows into a forked session."""
        async with self._write_transaction("copy_compacted_transcript_entries") as conn:
            await conn.execute(
                """
                INSERT INTO compacted_transcript_entries (
                session_id,
                session_key,
                compaction_id,
                compaction_index,
                original_entry_id,
                message_id,
                role,
                content,
                tool_calls,
                tool_call_id,
                reasoning_content,
                turn_usage,
                created_at,
                token_count,
                provenance_kind,
                provenance_origin_session_id,
                provenance_source_session_key,
                provenance_source_channel,
                provenance_source_tool,
                archived_at,
                schema_version
            )
            SELECT
                ?,
                ?,
                compaction_id,
                compaction_index,
                original_entry_id,
                message_id,
                role,
                content,
                tool_calls,
                tool_call_id,
                reasoning_content,
                turn_usage,
                created_at,
                token_count,
                provenance_kind,
                provenance_origin_session_id,
                provenance_source_session_key,
                provenance_source_channel,
                provenance_source_tool,
                archived_at,
                schema_version
            FROM compacted_transcript_entries
            WHERE session_id = ?
            ORDER BY created_at ASC, original_entry_id ASC, id ASC
                """,
                (target_session_id, target_session_key, source_session_id),
            )

    @_serialized_read
    async def count_transcript_entries(self, session_id: str) -> int:
        async with self.conn.execute(
            "SELECT COUNT(*) FROM transcript_entries WHERE session_id = ?", (session_id,)
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else 0

    @_serialized_read
    async def count_transcript_entries_batch(
        self, session_ids: list[str]
    ) -> dict[str, int]:
        """Count transcript entries for many sessions in one round trip.

        Used by ``sessions.list`` (rpc_sessions.py) to avoid the N+1 pattern
        where the previous implementation awaited ``count_transcript_entries``
        once per row. Returns ``{session_id: count}`` with missing ids
        explicitly defaulted to 0. The single-id ``count_transcript_entries``
        is kept for backward compatibility with other callers.

        Chunk size 500 stays well below SQLite's default
        ``SQLITE_MAX_VARIABLE_NUMBER`` (999 since 3.32) with headroom.
        """
        if not session_ids:
            return {}
        chunk = 500
        result: dict[str, int] = {}
        for i in range(0, len(session_ids), chunk):
            batch = session_ids[i : i + chunk]
            placeholders = ",".join(["?"] * len(batch))
            sql = (
                f"SELECT session_id, COUNT(*) FROM transcript_entries "
                f"WHERE session_id IN ({placeholders}) GROUP BY session_id"
            )
            async with self.conn.execute(sql, batch) as cur:
                rows = await cur.fetchall()
            for sid, cnt in rows:
                result[sid] = cnt
        for sid in session_ids:
            result.setdefault(sid, 0)
        return result

    @_serialized_read
    async def list_user_transcript_content_batch(
        self,
        session_ids: list[str],
        *,
        limit_per_session: int = 3,
    ) -> dict[str, list[str]]:
        """Return early user transcript content for many sessions.

        ``sessions.list`` uses this to render semantic conversation titles
        without issuing one transcript query per session row.
        """
        if not session_ids:
            return {}
        chunk = 300
        result: dict[str, list[str]] = {sid: [] for sid in session_ids}
        for i in range(0, len(session_ids), chunk):
            batch = session_ids[i : i + chunk]
            placeholders = ",".join(["?"] * len(batch))
            sql = f"""
                SELECT session_id, content
                FROM (
                    SELECT
                        session_id,
                        content,
                        ROW_NUMBER() OVER (
                            PARTITION BY session_id
                            ORDER BY created_at ASC, id ASC
                        ) AS rn
                    FROM transcript_entries
                    WHERE session_id IN ({placeholders})
                        AND role = 'user'
                        AND COALESCE(content, '') != ''
                )
                WHERE rn <= ?
                ORDER BY session_id ASC, rn ASC
            """
            async with self.conn.execute(sql, [*batch, limit_per_session]) as cur:
                rows = await cur.fetchall()
            for sid, content in rows:
                if isinstance(content, str):
                    result.setdefault(sid, []).append(content)
        return result

    async def delete_transcript(self, session_id: str) -> None:
        async with self._write_transaction("delete_transcript") as conn:
            await conn.execute(
                "DELETE FROM transcript_entries WHERE session_id = ?", (session_id,)
            )
            await conn.execute(
                "DELETE FROM compacted_transcript_entries WHERE session_id = ?",
                (session_id,),
            )

    async def delete_transcript_entry(self, session_id: str, message_id: str) -> bool:
        """Delete a single transcript entry by ``message_id``.

        Returns True iff a row was actually removed. Used to roll back an
        ``append_message`` whose follow-up enqueue failed (e.g. the agent task
        queue is full), so the client can safely retry without leaving a
        ghost user turn behind.
        """
        async with self._write_transaction("delete_transcript_entry") as conn:
            async with conn.execute(
                "DELETE FROM transcript_entries WHERE session_id = ? AND message_id = ?",
                (session_id, message_id),
            ) as cur:
                removed = cur.rowcount or 0
        return removed > 0

    async def delete_summaries(self, session_id: str) -> None:
        async with self._write_transaction("delete_summaries") as conn:
            await conn.execute(
                "DELETE FROM session_summaries WHERE session_id = ?", (session_id,)
            )

    @_serialized_read
    async def get_recent_transcript(self, session_id: str, n: int) -> list[TranscriptEntry]:
        """Return the most recent n entries, ordered oldest-first."""
        sql = (
            "SELECT * FROM (SELECT * FROM transcript_entries WHERE session_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?) ORDER BY created_at ASC, id ASC"
        )
        async with self.conn.execute(sql, (session_id, n)) as cur:
            rows = await cur.fetchall()
        return [TranscriptEntry(**_deserialize_row(dict(r))) for r in rows]

    # ── SessionSummary CRUD ──────────────────────────────────────────────────

    async def save_summary(self, summary: SessionSummary) -> SessionSummary:
        """Persist a compaction summary. Sets compaction_index automatically."""
        _next_idx_sql = (
            "SELECT COALESCE(MAX(compaction_index), -1) + 1 "
            "FROM session_summaries WHERE session_id = ?"
        )
        async with self._write_transaction("save_summary") as conn:
            async with conn.execute(_next_idx_sql, (summary.session_id,)) as cur:
                row = await cur.fetchone()
            summary.compaction_index = row[0] if row else 0

            data = summary.model_dump(exclude={"id"})
            cols = list(data.keys())
            placeholders = ", ".join("?" for _ in cols)
            values = [_serialize(data[c]) for c in cols]
            async with conn.execute(
                f"INSERT INTO session_summaries ({', '.join(cols)}) VALUES ({placeholders})",
                values,
            ) as cur:
                summary.id = cur.lastrowid
        return summary

    async def _archive_transcript_entries(
        self,
        *,
        node: SessionNode,
        entries: list[TranscriptEntry],
        compaction_id: str | None,
        compaction_index: int | None,
    ) -> None:
        if not entries:
            return
        archived_at = _now_ms()
        for entry in entries:
            entry_data = entry.model_dump(exclude={"id"})
            entry_data["session_id"] = node.session_id
            entry_data["session_key"] = node.session_key
            archive_data: dict[str, Any] = {
                "session_id": entry_data.pop("session_id"),
                "session_key": entry_data.pop("session_key"),
                "compaction_id": compaction_id,
                "compaction_index": compaction_index,
                "original_entry_id": entry.id,
                **entry_data,
                "archived_at": archived_at,
            }
            cols = list(archive_data.keys())
            placeholders = ", ".join("?" for _ in cols)
            values = [_serialize(archive_data[c]) for c in cols]
            await self.conn.execute(
                "INSERT INTO compacted_transcript_entries "
                f"({', '.join(cols)}) VALUES ({placeholders})",
                values,
            )

    async def rewrite_compacted_session(
        self,
        *,
        node: SessionNode,
        summary: SessionSummary | None,
        entries: list[TranscriptEntry],
        context_states: list[SessionContextState] | None = None,
        archived_entries: list[TranscriptEntry] | None = None,
    ) -> None:
        """Atomically persist a compaction rewrite for one session."""
        node.session_key = canonicalize_session_key(node.session_key)
        node.agent_id = normalize_agent_id(node.agent_id)

        async with self._write_transaction("rewrite_compacted_session") as conn:
            if summary is not None:
                summary.session_id = node.session_id
                summary.session_key = node.session_key
                async with conn.execute(
                    "SELECT COALESCE(MAX(compaction_index), -1) + 1 "
                    "FROM session_summaries WHERE session_id = ?",
                    (summary.session_id,),
                ) as cur:
                    row = await cur.fetchone()
                summary.compaction_index = row[0] if row else 0

            await self._archive_transcript_entries(
                node=node,
                entries=archived_entries or [],
                compaction_id=summary.compaction_id if summary is not None else None,
                compaction_index=summary.compaction_index
                if summary is not None
                else None,
            )

            await conn.execute(
                "DELETE FROM transcript_entries WHERE session_id = ?",
                (node.session_id,),
            )

            if summary is not None:
                summary_data = summary.model_dump(exclude={"id"})
                summary_cols = list(summary_data.keys())
                summary_placeholders = ", ".join("?" for _ in summary_cols)
                summary_values = [_serialize(summary_data[c]) for c in summary_cols]
                async with conn.execute(
                    "INSERT INTO session_summaries "
                    f"({', '.join(summary_cols)}) VALUES ({summary_placeholders})",
                    summary_values,
                ) as cur:
                    summary.id = cur.lastrowid

            for state in context_states or []:
                state.session_id = node.session_id
                state.session_key = node.session_key
                state_data = state.model_dump(exclude={"id"})
                state_cols = list(state_data.keys())
                state_placeholders = ", ".join("?" for _ in state_cols)
                state_values = [_serialize(state_data[c]) for c in state_cols]
                async with conn.execute(
                    "INSERT INTO session_context_states "
                    f"({', '.join(state_cols)}) VALUES ({state_placeholders})",
                    state_values,
                ) as cur:
                    state.id = cur.lastrowid

            for entry in entries:
                entry.session_id = node.session_id
                entry.session_key = node.session_key
                entry_data = entry.model_dump(exclude={"id"})
                entry_cols = list(entry_data.keys())
                entry_placeholders = ", ".join("?" for _ in entry_cols)
                entry_values = [_serialize(entry_data[c]) for c in entry_cols]
                await conn.execute(
                    "INSERT INTO transcript_entries "
                    f"({', '.join(entry_cols)}) VALUES ({entry_placeholders})",
                    entry_values,
                )

            node_data = node.model_dump()
            node_cols = list(node_data.keys())
            node_placeholders = ", ".join("?" for _ in node_cols)
            node_updates: list[str] = []
            for col in node_cols:
                if col == "session_key":
                    continue
                if col == "epoch":
                    node_updates.append("epoch = MAX(sessions.epoch, excluded.epoch)")
                else:
                    node_updates.append(f"{col}=excluded.{col}")
            node_values = [_serialize(node_data[c]) for c in node_cols]
            await conn.execute(
                f"INSERT INTO sessions ({', '.join(node_cols)}) VALUES ({node_placeholders}) "
                f"ON CONFLICT(session_key) DO UPDATE SET {', '.join(node_updates)}",
                node_values,
            )

    @_serialized_read
    async def get_latest_summary(self, session_id: str) -> SessionSummary | None:
        async with self.conn.execute(
            "SELECT * FROM session_summaries WHERE session_id = ? "
            "ORDER BY compaction_index DESC LIMIT 1",
            (session_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return SessionSummary(**_deserialize_row(dict(row)))

    @_serialized_read
    async def get_all_summaries(self, session_id: str) -> list[SessionSummary]:
        return await self._select_all_summaries(self.conn, session_id)

    @_serialized_read
    async def list_degraded_summaries(
        self,
        *,
        session_key_prefix: str | None = None,
        limit: int = 50,
    ) -> list[SessionSummary]:
        clauses = ["flush_receipt_status IN ('degraded_forensic', 'failed_retryable')"]
        params: list[Any] = []
        if session_key_prefix:
            clauses.append("session_key LIKE ?")
            params.append(f"{session_key_prefix}%")
        params.append(limit)
        sql = (
            "SELECT * FROM session_summaries "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY created_at ASC LIMIT ?"
        )
        async with self.conn.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [SessionSummary(**_deserialize_row(dict(r))) for r in rows]

    @_serialized_read
    async def get_compacted_transcript_entries(
        self,
        *,
        session_id: str,
        compaction_id: str,
    ) -> list[TranscriptEntry]:
        sql = """
            SELECT
                original_entry_id AS id,
                session_id,
                session_key,
                message_id,
                role,
                content,
                tool_calls,
                tool_call_id,
                reasoning_content,
                turn_usage,
                created_at,
                token_count,
                provenance_kind,
                provenance_origin_session_id,
                provenance_source_session_key,
                provenance_source_channel,
                provenance_source_tool,
                schema_version
            FROM compacted_transcript_entries
            WHERE session_id = ? AND compaction_id = ?
            ORDER BY created_at ASC, original_entry_id ASC, id ASC
        """
        async with self.conn.execute(sql, (session_id, compaction_id)) as cur:
            rows = await cur.fetchall()
        return [TranscriptEntry(**_deserialize_row(dict(r))) for r in rows]

    async def update_summary_flush_receipt_status(
        self,
        summary_id: int,
        status: str,
    ) -> None:
        async with self._write_transaction("update_summary_flush_receipt_status") as conn:
            await conn.execute(
                "UPDATE session_summaries SET flush_receipt_status = ? WHERE id = ?",
                (status, summary_id),
            )

    async def update_summary_flush_receipt_status_by_compaction(
        self,
        *,
        session_key: str,
        compaction_id: str,
        status: str,
    ) -> int:
        async with self._write_transaction(
            "update_summary_flush_receipt_status_by_compaction"
        ) as conn:
            cur = await conn.execute(
                """
                UPDATE session_summaries
                SET flush_receipt_status = ?
                WHERE session_key = ? AND compaction_id = ?
                """,
                (status, canonicalize_session_key(session_key), compaction_id),
            )
            count = int(cur.rowcount or 0)
        return count

    # ── SessionContextState CRUD ─────────────────────────────────────────────

    async def save_context_state(
        self, state: SessionContextState
    ) -> SessionContextState:
        """Persist portable or provider-native context state for later replay."""
        state.session_key = canonicalize_session_key(state.session_key)
        data = state.model_dump(exclude={"id"})
        cols = list(data.keys())
        placeholders = ", ".join("?" for _ in cols)
        values = [_serialize(data[c]) for c in cols]
        async with self._write_transaction("save_context_state") as conn:
            async with conn.execute(
                "INSERT INTO session_context_states "
                f"({', '.join(cols)}) VALUES ({placeholders})",
                values,
            ) as cur:
                state.id = cur.lastrowid
        return state

    @_serialized_read
    async def get_context_states(
        self,
        session_key: str,
        *,
        provider: str | None = None,
        state_kind: str | None = None,
        valid_only: bool = True,
    ) -> list[SessionContextState]:
        session_key = canonicalize_session_key(session_key)
        clauses = ["session_key = ?"]
        params: list[Any] = [session_key]
        if provider is not None:
            clauses.append("provider = ?")
            params.append(provider)
        if state_kind is not None:
            clauses.append("state_kind = ?")
            params.append(state_kind)
        if valid_only:
            clauses.append("valid = 1")
        where = " AND ".join(clauses)
        async with self.conn.execute(
            "SELECT * FROM session_context_states "
            f"WHERE {where} ORDER BY created_at ASC, id ASC",
            params,
        ) as cur:
            rows = await cur.fetchall()
        return [SessionContextState(**_deserialize_row(dict(row))) for row in rows]

    async def invalidate_context_states(
        self,
        session_key: str,
        *,
        provider: str | None = None,
        state_kind: str | None = None,
        reason: str = "invalidated",
    ) -> int:
        session_key = canonicalize_session_key(session_key)
        clauses = ["session_key = ?", "valid = 1"]
        params: list[Any] = [session_key]
        if provider is not None:
            clauses.append("provider = ?")
            params.append(provider)
        if state_kind is not None:
            clauses.append("state_kind = ?")
            params.append(state_kind)
        async with self._write_transaction("invalidate_context_states") as conn:
            async with conn.execute(
                "UPDATE session_context_states "
                "SET valid = 0, invalid_reason = ? "
                f"WHERE {' AND '.join(clauses)}",
                [reason, *params],
            ) as cur:
                changed = cur.rowcount or 0
        return int(changed)

    # ── FTS5 Search ──────────────────────────────────────────────────────

    @staticmethod
    def sanitize_fts_query(raw: str) -> str:
        """Sanitize a user query for safe FTS5 MATCH.

        Strips FTS5 operators and special chars, wraps each token in quotes.
        """
        import re as _re

        # Whitelist: only allow alphanumeric and whitespace through
        cleaned = _re.sub(r"[^a-zA-Z0-9\s]", " ", raw)
        # Collapse whitespace and split into tokens
        tokens = cleaned.split()
        if not tokens:
            return '""'
        # Wrap each token in double-quotes for literal matching
        return " ".join(f'"{t}"' for t in tokens[:20])  # cap at 20 terms

    @_serialized_read
    async def search_transcript(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Full-text search across transcript entries.

        Returns dicts with: id, session_key, role, snippet, created_at.
        """
        safe_q = self.sanitize_fts_query(query)
        if safe_q == '""':
            return []

        if session_id:
            sql = (
                "SELECT t.id, t.session_key, t.role, t.created_at, "
                "snippet(transcript_fts, 0, '>>>', '<<<', '...', 48) AS snippet "
                "FROM transcript_fts f "
                "JOIN transcript_entries t ON f.rowid = t.id "
                "WHERE f.content MATCH ? AND t.session_id = ? "
                "ORDER BY f.rank LIMIT ?"
            )
            params: list[Any] = [safe_q, session_id, limit]
        else:
            sql = (
                "SELECT t.id, t.session_key, t.role, t.created_at, "
                "snippet(transcript_fts, 0, '>>>', '<<<', '...', 48) AS snippet "
                "FROM transcript_fts f "
                "JOIN transcript_entries t ON f.rowid = t.id "
                "WHERE f.content MATCH ? "
                "ORDER BY f.rank LIMIT ?"
            )
            params = [safe_q, limit]

        async with self.conn.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _like_escape(raw: str) -> str:
        """Escape LIKE wildcards so user input matches literally under ESCAPE '\\'."""
        return raw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    @classmethod
    def _like_tokens(cls, query: str, max_tokens: int = 10) -> list[str]:
        """Whitespace-split a query into lowercased, wildcard-escaped LIKE patterns.

        Each token becomes ``%token%`` and callers AND them, so multi-word and
        mixed ASCII+CJK queries (e.g. ``deploy 部署``) match every term
        independently instead of requiring one contiguous substring. Lowercased
        to pair with the ``py_lower`` column side for Unicode case-insensitivity.
        """
        return [f"%{cls._like_escape(tok.lower())}%" for tok in query.split()[:max_tokens] if tok]

    @staticmethod
    def _needs_unicode_fold(query: str) -> bool:
        """Whether a query needs the per-row ``py_lower`` to match case-insensitively.

        Only non-ASCII *cased* scripts (Cyrillic, Greek, accented Latin, …) need
        it. ASCII is folded by SQLite's own LIKE, and caseless scripts (CJK,
        digits, symbols) don't differ by case — both take the faster plain-LIKE
        path. So the (Chinese-dominant) common case never pays the fold cost.
        """
        return any(ord(ch) > 127 and ch.lower() != ch.upper() for ch in query)

    @staticmethod
    def _make_snippet(content: str, needle: str, window: int = 40) -> str:
        """Build a ``>>>match<<<`` snippet around the first case-insensitive hit.

        Mirrors the delimiter contract of the FTS ``snippet()`` output so the UI
        highlighter treats LIKE and FTS results identically.
        """
        idx = content.lower().find(needle.lower())
        if idx < 0:
            return content[: window * 2]
        end_match = idx + len(needle)
        start = max(0, idx - window)
        end = min(len(content), end_match + window)
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(content) else ""
        return (
            f"{prefix}{content[start:idx]}>>>{content[idx:end_match]}<<<"
            f"{content[end_match:end]}{suffix}"
        )

    @_serialized_read
    async def search_sessions_by_title(
        self,
        query: str,
        limit: int = 20,
    ) -> list[SessionNode]:
        """Substring match over title columns across ALL sessions (not a recent
        page). Every whitespace-separated term must match in one of the title
        columns (display_name / derived_title / subject / label). Matching is
        case-insensitive: ASCII via SQLite's own LIKE, and cased non-ASCII scripts
        via ``py_lower`` (only paid when the query actually contains one)."""
        tokens = self._like_tokens(query)
        if not tokens:
            return []
        col = (lambda c: f"py_lower({c})") if self._needs_unicode_fold(query) else (lambda c: c)
        cols = ("display_name", "derived_title", "subject", "label")
        clauses: list[str] = []
        params: list[Any] = []
        for token in tokens:
            clauses.append("(" + " OR ".join(f"{col(c)} LIKE ? ESCAPE '\\'" for c in cols) + ")")
            params.extend([token] * len(cols))
        params.append(limit)
        sql = (
            f"SELECT * FROM sessions WHERE {' AND '.join(clauses)} "
            "ORDER BY updated_at DESC LIMIT ?"
        )
        async with self.conn.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [SessionNode(**_deserialize_row(dict(r))) for r in rows]

    @_serialized_read
    async def search_transcript_like(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Substring content search for queries the FTS tokenizer can't handle.

        SQLite's default ``unicode61`` FTS tokenizer does not segment CJK and
        other scripts, and ``sanitize_fts_query`` strips non-ASCII entirely, so
        full-text search returns nothing for e.g. Chinese. Each whitespace term
        must appear in the content, so mixed/multi-word queries match all terms;
        cased non-ASCII scripts fold via ``py_lower`` (caseless CJK skips it for
        speed). The handler only reaches this for non-ASCII queries (ASCII stays
        on the indexed FTS path). Returns the same shape as ``search_transcript``.
        """
        tokens = self._like_tokens(query)
        if not tokens:
            return []
        col = "py_lower(content)" if self._needs_unicode_fold(query) else "content"
        clauses = [f"{col} LIKE ? ESCAPE '\\'" for _ in tokens]
        params: list[Any] = list(tokens)
        where = " AND ".join(clauses)
        if session_id:
            where += " AND session_id = ?"
            params.append(session_id)
        params.append(limit)
        sql = (
            "SELECT id, session_key, role, content, created_at "
            f"FROM transcript_entries WHERE {where} "
            "ORDER BY created_at DESC LIMIT ?"
        )
        async with self.conn.execute(sql, params) as cur:
            rows = await cur.fetchall()
        # Snippet highlights the first term; the others are guaranteed present too.
        first_term = query.split()[0]
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            out.append(
                {
                    "id": d.get("id"),
                    "session_key": d.get("session_key"),
                    "role": d.get("role"),
                    "created_at": d.get("created_at"),
                    "snippet": self._make_snippet(str(d.get("content") or ""), first_term),
                }
            )
        return out

    async def __aenter__(self) -> SessionStorage:
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()
