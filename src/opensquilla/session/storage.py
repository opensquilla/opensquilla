"""Async database operations for sessions using aiosqlite + SQLModel."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

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
)

if TYPE_CHECKING:
    from opensquilla.persistence.meta_run_writer import MetaRunWriter

log = logging.getLogger(__name__)


class StaleEpochError(Exception):
    """Raised when a write is rejected because the session epoch has advanced."""


# Bumped whenever the schema is widened or narrowed via migration.
# Version 2 added the epoch column. Version 3 added transcript reasoning replay.
# Version 4 added transcript turn usage metadata.
# Version 5 added structured compaction summary metadata.
# Version 6 added portable/provider context state records.
# Version 7 added archived transcript rows for canonical recovery after compaction.
SCHEMA_VERSION = 7

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
    channel TEXT,
    group_id TEXT,
    subject TEXT,
    origin TEXT,
    agent_id TEXT NOT NULL DEFAULT 'main',
    schema_version INTEGER NOT NULL DEFAULT 1,
    epoch INTEGER NOT NULL DEFAULT 0
)
"""

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

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._initialize_schema()

    @classmethod
    async def open(cls, db_path: str) -> SessionStorage:
        storage = cls(str(db_path))
        await storage.connect()
        return storage

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def _initialize_schema(self) -> None:
        assert self._conn is not None
        await self._conn.execute(_CREATE_SESSIONS)
        await self._conn.execute(_CREATE_TRANSCRIPT)
        await self._conn.execute(_CREATE_IDX_TRANSCRIPT_SESSION)
        await self._conn.execute(_CREATE_IDX_TRANSCRIPT_KEY)
        await self._conn.execute(_CREATE_COMPACTED_TRANSCRIPT)
        await self._conn.execute(_CREATE_IDX_COMPACTED_TRANSCRIPT_SESSION)
        await self._conn.execute(_CREATE_IDX_COMPACTED_TRANSCRIPT_KEY)
        await self._conn.execute(_CREATE_SUMMARIES)
        await self._conn.execute(_CREATE_IDX_SUMMARIES)
        await self._conn.execute(_CREATE_CONTEXT_STATES)
        await self._conn.execute(_CREATE_IDX_CONTEXT_STATES_SESSION)
        await self._conn.execute(_CREATE_IDX_CONTEXT_STATES_KEY_VALID)
        await self._conn.execute(_CREATE_AGENT_TASKS)
        await self._conn.execute(_CREATE_IDX_AGENT_TASKS_SESSION_STATUS)
        await self._conn.execute(_CREATE_IDX_AGENT_TASKS_STATUS_UPDATED)
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
        await self._migrate_transcript_reasoning_content_column()
        await self._migrate_transcript_turn_usage_column()
        await self._migrate_summary_metadata_columns()
        await self._migrate_memory_durable_receipt_coverage_columns()
        await self._conn.execute(_CREATE_IDX_MEMORY_DURABLE_RECEIPTS_COVERAGE)
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
        await self.conn.execute(sql, values)
        await self.conn.commit()

    async def get_session(self, session_key: str) -> SessionNode | None:
        session_key = canonicalize_session_key(session_key)
        async with self.conn.execute(
            "SELECT * FROM sessions WHERE session_key = ?", (session_key,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return SessionNode(**_deserialize_row(dict(row)))

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
            clauses.append("agent_id = ?")
            params.append(normalize_agent_id(agent_id))
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if spawned_by is not None:
            clauses.append("spawned_by = ?")
            params.append(canonicalize_session_key(spawned_by))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params += [limit, offset]
        sql = f"SELECT * FROM sessions {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        async with self.conn.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [SessionNode(**_deserialize_row(dict(r))) for r in rows]

    async def delete_session(self, session_key: str) -> None:
        session_key = canonicalize_session_key(session_key)
        session = await self.get_session(session_key)
        if session is None:
            return
        await self.conn.execute(
            "DELETE FROM transcript_entries WHERE session_id = ?",
            (session.session_id,),
        )
        await self.conn.execute(
            "DELETE FROM compacted_transcript_entries WHERE session_id = ?",
            (session.session_id,),
        )
        await self.conn.execute(
            "DELETE FROM session_summaries WHERE session_id = ?",
            (session.session_id,),
        )
        await self.conn.execute(
            "DELETE FROM session_context_states WHERE session_id = ?",
            (session.session_id,),
        )
        await self.conn.execute("DELETE FROM sessions WHERE session_key = ?", (session_key,))
        await self.conn.commit()

        # G4 cleanup: cascade meta-skill audit rows for this session. The
        # sessions table is created lazily at runtime (not via yoyo), so
        # there is no SQL FK to rely on — explicit purge is required.
        if self._meta_run_writer is not None:
            try:
                self._meta_run_writer.purge_for_session(session_key)
            except Exception as exc:  # noqa: BLE001
                log.warning("session_delete.purge_meta_runs_failed: %s", exc)

    async def prune_stale_sessions(self, before_ms: int) -> int:
        """Delete sessions not updated since before_ms epoch ms. Returns count deleted."""
        async with self.conn.execute(
            "SELECT session_key FROM sessions WHERE updated_at < ?",
            (before_ms,),
        ) as cur:
            rows = await cur.fetchall()
        session_keys = [row[0] for row in rows]
        for session_key in session_keys:
            await self.delete_session(session_key)
        return len(session_keys)

    async def count_sessions(self) -> int:
        async with self.conn.execute("SELECT COUNT(*) FROM sessions") as cur:
            row = await cur.fetchone()
        return row[0] if row else 0

    async def increment_epoch(self, session_key: str) -> int:
        """Atomically increment the epoch counter for a session.

        Returns the new epoch value. Raises KeyError if the session is not found.
        """
        session_key = canonicalize_session_key(session_key)
        await self.conn.execute(
            "UPDATE sessions SET epoch = epoch + 1 WHERE session_key = ?",
            (session_key,),
        )
        await self.conn.commit()
        async with self.conn.execute(
            "SELECT epoch FROM sessions WHERE session_key = ?", (session_key,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            raise KeyError(f"Session not found: {session_key}")
        return int(row[0])

    async def get_epoch(self, session_key: str) -> int:
        """Return current epoch for a session (0 if not found)."""
        session_key = canonicalize_session_key(session_key)
        async with self.conn.execute(
            "SELECT epoch FROM sessions WHERE session_key = ?", (session_key,)
        ) as cur:
            row = await cur.fetchone()
        return int(row[0]) if row is not None else 0

    # ── AgentTask ledger CRUD ───────────────────────────────────────────────

    async def create_agent_task(self, task: AgentTaskRecord) -> AgentTaskRecord:
        task.session_key = canonicalize_session_key(task.session_key)
        task.agent_id = normalize_agent_id(task.agent_id)
        data = task.model_dump()
        cols = list(data.keys())
        placeholders = ", ".join("?" for _ in cols)
        values = [_serialize(data[c]) for c in cols]
        sql = f"INSERT INTO agent_tasks ({', '.join(cols)}) VALUES ({placeholders})"
        await self.conn.execute(sql, values)
        await self.conn.commit()
        return task

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
        await self.conn.execute(
            f"UPDATE agent_tasks SET {assignments} WHERE task_id = ?",
            values,
        )
        await self.conn.commit()
        updated = await self.get_agent_task(task_id)
        if updated is None:
            raise KeyError(f"Agent task not found: {task_id}")
        return updated

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
        await self.conn.execute(
            f"""
            INSERT INTO memory_durable_receipts ({", ".join(cols)})
            VALUES ({placeholders})
            ON CONFLICT(idempotency_key) DO UPDATE SET {updates}
            """,
            values,
        )
        await self.conn.commit()
        rows = await self.list_memory_durable_receipts(
            session_key=receipt.session_key,
            idempotency_key=receipt.idempotency_key,
            limit=1,
        )
        return rows[0]

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
        await self.conn.execute(
            f"UPDATE memory_durable_receipts SET {assignments} WHERE receipt_id = ?",
            values,
        )
        await self.conn.commit()
        async with self.conn.execute(
            "SELECT * FROM memory_durable_receipts WHERE receipt_id = ?",
            (receipt_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            raise KeyError(f"Memory durable receipt not found: {receipt_id}")
        return MemoryDurableReceipt(**_deserialize_row(dict(row)))

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
            sql = (
                f"SELECT * FROM agent_tasks WHERE session_key IN ({placeholders}) "
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
        cur = await self.conn.execute(
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
        await self.conn.commit()
        return int(cur.rowcount if cur.rowcount is not None else 0)

    # ── Transcript CRUD ──────────────────────────────────────────────────────

    async def append_transcript_entry(
        self, entry: TranscriptEntry, *, expected_epoch: int | None = None
    ) -> None:
        entry.session_key = canonicalize_session_key(entry.session_key)
        data = entry.model_dump(exclude={"id"})
        cols = list(data.keys())
        placeholders = ", ".join("?" for _ in cols)
        values = [_serialize(data[c]) for c in cols]

        if expected_epoch is not None:
            # Atomic guard: INSERT only when the session epoch matches.
            # The INSERT ... SELECT WHERE EXISTS form is a single SQL statement so
            # SQLite evaluates the epoch check and the row insertion atomically
            # (no await between SELECT and INSERT, so no TOCTOU within the
            # single-process asyncio event loop).
            # If 0 rows are affected the epoch has advanced (reset fired) → stale.
            insert_sql = (
                f"INSERT INTO transcript_entries ({', '.join(cols)}) "
                f"SELECT {placeholders} "
                f"WHERE EXISTS ("
                f"  SELECT 1 FROM sessions "
                f"  WHERE session_key = ? AND epoch = ?"
                f")"
            )
            async with self.conn.execute(
                insert_sql, values + [entry.session_key, expected_epoch]
            ) as cur:
                inserted = cur.rowcount or 0
            if inserted == 0:
                # Fetch actual epoch for the error message (best-effort).
                async with self.conn.execute(
                    "SELECT epoch FROM sessions WHERE session_key = ?",
                    (entry.session_key,),
                ) as cur2:
                    row = await cur2.fetchone()
                actual = int(row[0]) if row is not None else None
                raise StaleEpochError(
                    f"Epoch mismatch for {entry.session_key}: "
                    f"expected {expected_epoch}, got {actual}"
            )
            await self.conn.commit()
        else:
            sql = f"INSERT INTO transcript_entries ({', '.join(cols)}) VALUES ({placeholders})"
            await self.conn.execute(sql, values)
            await self.conn.commit()

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

    async def get_canonical_transcript(
        self, session_id: str, limit: int | None = None, offset: int = 0
    ) -> list[TranscriptEntry]:
        """Return archived compacted rows plus the active transcript tail.

        Provider replay intentionally keeps using get_transcript(). This API is
        for recovery, diagnostics, and future provider-view construction where
        the raw transcript needs to survive destructive compaction rewrites.
        """
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
        async with self.conn.execute(
            sql, (session_id, session_id, limit_val, offset)
        ) as cur:
            rows = await cur.fetchall()
        return [TranscriptEntry(**_deserialize_row(dict(r))) for r in rows]

    async def copy_compacted_transcript_entries(
        self,
        *,
        source_session_id: str,
        target_session_id: str,
        target_session_key: str,
    ) -> None:
        """Copy archived compacted transcript rows into a forked session."""
        await self.conn.execute(
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
        await self.conn.commit()

    async def count_transcript_entries(self, session_id: str) -> int:
        async with self.conn.execute(
            "SELECT COUNT(*) FROM transcript_entries WHERE session_id = ?", (session_id,)
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else 0

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

    async def delete_transcript(self, session_id: str) -> None:
        await self.conn.execute(
            "DELETE FROM transcript_entries WHERE session_id = ?", (session_id,)
        )
        await self.conn.execute(
            "DELETE FROM compacted_transcript_entries WHERE session_id = ?",
            (session_id,),
        )
        await self.conn.commit()

    async def delete_transcript_entry(self, session_id: str, message_id: str) -> bool:
        """Delete a single transcript entry by ``message_id``.

        Returns True iff a row was actually removed. Used to roll back an
        ``append_message`` whose follow-up enqueue failed (e.g. the agent task
        queue is full), so the client can safely retry without leaving a
        ghost user turn behind.
        """
        async with self.conn.execute(
            "DELETE FROM transcript_entries WHERE session_id = ? AND message_id = ?",
            (session_id, message_id),
        ) as cur:
            removed = cur.rowcount or 0
        await self.conn.commit()
        return removed > 0

    async def delete_summaries(self, session_id: str) -> None:
        await self.conn.execute("DELETE FROM session_summaries WHERE session_id = ?", (session_id,))
        await self.conn.commit()

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
        async with self.conn.execute(_next_idx_sql, (summary.session_id,)) as cur:
            row = await cur.fetchone()
        summary.compaction_index = row[0] if row else 0

        data = summary.model_dump(exclude={"id"})
        cols = list(data.keys())
        placeholders = ", ".join("?" for _ in cols)
        values = [_serialize(data[c]) for c in cols]
        async with self.conn.execute(
            f"INSERT INTO session_summaries ({', '.join(cols)}) VALUES ({placeholders})",
            values,
        ) as cur:
            summary.id = cur.lastrowid
        await self.conn.commit()
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

        await self.conn.execute("BEGIN IMMEDIATE")
        try:
            if summary is not None:
                summary.session_id = node.session_id
                summary.session_key = node.session_key
                async with self.conn.execute(
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

            await self.conn.execute(
                "DELETE FROM transcript_entries WHERE session_id = ?",
                (node.session_id,),
            )

            if summary is not None:
                summary_data = summary.model_dump(exclude={"id"})
                summary_cols = list(summary_data.keys())
                summary_placeholders = ", ".join("?" for _ in summary_cols)
                summary_values = [_serialize(summary_data[c]) for c in summary_cols]
                async with self.conn.execute(
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
                async with self.conn.execute(
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
                await self.conn.execute(
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
            await self.conn.execute(
                f"INSERT INTO sessions ({', '.join(node_cols)}) VALUES ({node_placeholders}) "
                f"ON CONFLICT(session_key) DO UPDATE SET {', '.join(node_updates)}",
                node_values,
            )
            await self.conn.commit()
        except Exception:
            await self.conn.rollback()
            raise

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

    async def get_all_summaries(self, session_id: str) -> list[SessionSummary]:
        async with self.conn.execute(
            "SELECT * FROM session_summaries WHERE session_id = ? ORDER BY compaction_index ASC",
            (session_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [SessionSummary(**_deserialize_row(dict(r))) for r in rows]

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
        await self.conn.execute(
            "UPDATE session_summaries SET flush_receipt_status = ? WHERE id = ?",
            (status, summary_id),
        )
        await self.conn.commit()

    async def update_summary_flush_receipt_status_by_compaction(
        self,
        *,
        session_key: str,
        compaction_id: str,
        status: str,
    ) -> int:
        cur = await self.conn.execute(
            """
            UPDATE session_summaries
            SET flush_receipt_status = ?
            WHERE session_key = ? AND compaction_id = ?
            """,
            (status, canonicalize_session_key(session_key), compaction_id),
        )
        await self.conn.commit()
        return int(cur.rowcount or 0)

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
        async with self.conn.execute(
            "INSERT INTO session_context_states "
            f"({', '.join(cols)}) VALUES ({placeholders})",
            values,
        ) as cur:
            state.id = cur.lastrowid
        await self.conn.commit()
        return state

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
        async with self.conn.execute(
            "UPDATE session_context_states "
            "SET valid = 0, invalid_reason = ? "
            f"WHERE {' AND '.join(clauses)}",
            [reason, *params],
        ) as cur:
            changed = cur.rowcount or 0
        await self.conn.commit()
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

    async def __aenter__(self) -> SessionStorage:
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()
