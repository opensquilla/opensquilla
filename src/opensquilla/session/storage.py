"""Async database operations for sessions using aiosqlite + SQLModel."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
import sqlite3
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from functools import wraps
from typing import TYPE_CHECKING, Any, Concatenate, cast

from opensquilla.compat import aiosqlite
from opensquilla.session.keys import canonicalize_session_key, normalize_agent_id, parse_agent_id
from opensquilla.session.models import (
    AgentTaskRecord,
    AgentTaskStatus,
    MemoryDurableReceipt,
    MetaControlIntent,
    MetaLaunchDraft,
    SessionContextState,
    SessionNode,
    SessionStatus,
    SessionSummary,
    TranscriptEntry,
    TurnIngressReceipt,
)
from opensquilla.session.usage_ledger import (
    UsageBackfillBatch,
    UsageBackfillCursor,
    UsageBackfillEntry,
    UsageBackfillStatus,
    UsageBackfillWrite,
    UsageEventCompletion,
    UsageEventItem,
    UsageEventRecord,
    UsageEventStart,
    UsageEventStatus,
    UsageLedgerConflictError,
    UsageLedgerState,
    UsageLegacyBaseline,
    usd_to_nanos,
    validate_usage_completion,
    validate_usage_event_start,
    validate_usage_item,
)
from opensquilla.usage_reasons import normalize_usage_unknown_reason

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


class MetaControlIntentConflictError(ValueError):
    """Raised when a durable MetaSkill control identity is reused incompatibly."""


class MetaLaunchDraftConflictError(ValueError):
    """Raised when a durable MetaSkill draft identity is reused incompatibly."""


class MetaLaunchDraftCapacityError(RuntimeError):
    """Raised when the bounded durable MetaSkill draft outbox is full."""


class MetaLaunchDraftUnavailableError(RuntimeError):
    """Raised when a draft expired before control promotion."""


class MetaLaunchDraftDiscardedError(RuntimeError):
    """Raised when a cancelled draft identity is reused before its tombstone expires."""


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


@dataclass(frozen=True)
class RecoverableMetaControlTask:
    """A never-started accepted control task claimed for restart recovery."""

    task: AgentTaskRecord
    entry: TranscriptEntry


_SQLITE_BUSY_TIMEOUT_MS = 100
_INTERACTIVE_BUSY_BUDGET_SECONDS = 2.0
_BUSY_RETRY_INITIAL_SECONDS = 0.025
_BUSY_RETRY_MAX_SECONDS = 0.250
_META_CONTROL_STAGED_RETENTION_MS = 30 * 24 * 60 * 60 * 1000
_META_CONTROL_STAGED_GC_BATCH = 128
_META_CONTROL_RECOVERY_INVALID_REASON = "meta_control_recovery_invalid"
_META_LAUNCH_DRAFT_RETENTION_MS = 7 * 24 * 60 * 60 * 1000
_META_LAUNCH_DRAFT_PER_SESSION_LIMIT = 20
_META_LAUNCH_DRAFT_GLOBAL_LIMIT = 512
_META_LAUNCH_DRAFT_GC_BATCH = 512
_META_LAUNCH_DRAFT_GC_INTERVAL_SECONDS = 60.0
_META_LAUNCH_DISCARD_PER_SESSION_LIMIT = 64
_META_LAUNCH_DISCARD_GLOBAL_LIMIT = 2048
_META_LAUNCH_ACCEPTED_PER_SESSION_LIMIT = 20
_META_LAUNCH_SESSION_KEY_MAX_LENGTH = 512
_META_LAUNCH_REQUEST_ID_MAX_LENGTH = 256


def normalize_meta_launch_coordinates(
    session_key: object,
    client_request_id: object,
) -> tuple[str, str]:
    """Validate bounded, content-free coordinates for draft and tombstone rows."""

    if not isinstance(session_key, str) or not isinstance(client_request_id, str):
        raise ValueError("meta launch draft coordinates must be strings")
    if len(session_key.strip()) > _META_LAUNCH_SESSION_KEY_MAX_LENGTH:
        raise ValueError("meta launch draft session is invalid")
    normalized_session = canonicalize_session_key(session_key)
    normalized_request_id = client_request_id.strip()
    if not normalized_session or len(normalized_session) > _META_LAUNCH_SESSION_KEY_MAX_LENGTH:
        raise ValueError("meta launch draft session is invalid")
    if (
        not normalized_request_id
        or len(normalized_request_id) > _META_LAUNCH_REQUEST_ID_MAX_LENGTH
        or any(character.isspace() for character in normalized_request_id)
    ):
        raise ValueError("meta launch draft request identity is invalid")
    return normalized_session, normalized_request_id


def _clear_pending_meta_launch_boundary(
    session_key: str,
    *,
    preserve_client_request_id: str | None = None,
    preserve_message: object = None,
) -> int:
    """Clear the process compatibility cache after a committed session boundary."""

    from opensquilla.engine.steps.meta_command import pending_meta_launch_clear_session

    return pending_meta_launch_clear_session(
        session_key,
        preserve_client_request_id=preserve_client_request_id,
        preserve_message=preserve_message,
    )


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
# Version 10 added the durable provider usage ledger and content-free daily usage
# telemetry aggregates. Version 11 added durable hidden MetaSkill control intents.
# Version 12 added the bounded pre-acceptance MetaSkill launch outbox.
SCHEMA_VERSION = 12

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
    turn_context TEXT,
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
    turn_context TEXT,
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

_CREATE_META_CONTROL_INTENTS = """
CREATE TABLE IF NOT EXISTS meta_control_intents (
    intent_id TEXT PRIMARY KEY,
    session_key TEXT NOT NULL,
    control_kind TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    meta_skill_name TEXT NOT NULL,
    replay_run_id TEXT,
    replay_mode TEXT,
    status TEXT NOT NULL DEFAULT 'staged',
    accepted_source_scope TEXT,
    accepted_request_session_key TEXT,
    accepted_client_request_id TEXT,
    accepted_request_fingerprint TEXT,
    accepted_message_id TEXT,
    accepted_task_id TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    CHECK (control_kind IN ('manual', 'replay')),
    CHECK (status IN ('staged', 'accepted'))
)
"""

_CREATE_IDX_META_CONTROL_CORRELATION = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_meta_control_intents_correlation
ON meta_control_intents(session_key, control_kind, correlation_id)
"""

_CREATE_IDX_META_CONTROL_SESSION_STATUS = """
CREATE INDEX IF NOT EXISTS idx_meta_control_intents_session_status
ON meta_control_intents(session_key, status, created_at)
"""

_CREATE_META_LAUNCH_DRAFTS = """
CREATE TABLE IF NOT EXISTS meta_launch_drafts (
    draft_id TEXT PRIMARY KEY,
    session_key TEXT NOT NULL,
    client_request_id TEXT NOT NULL,
    meta_skill_name TEXT NOT NULL,
    launch_text TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1
)
"""

_CREATE_IDX_META_LAUNCH_DRAFT_REQUEST = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_meta_launch_drafts_request
ON meta_launch_drafts(session_key, client_request_id)
"""

_CREATE_IDX_META_LAUNCH_DRAFT_SESSION_EXPIRY = """
CREATE INDEX IF NOT EXISTS idx_meta_launch_drafts_session_expiry
ON meta_launch_drafts(session_key, expires_at, created_at)
"""

_CREATE_META_LAUNCH_DISCARD_TOMBSTONES = """
CREATE TABLE IF NOT EXISTS meta_launch_discard_tombstones (
    session_key TEXT NOT NULL,
    client_request_id TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (session_key, client_request_id)
)
"""

_CREATE_IDX_META_LAUNCH_DISCARD_TOMBSTONES_EXPIRY = """
CREATE INDEX IF NOT EXISTS idx_meta_launch_discard_tombstones_expiry
ON meta_launch_discard_tombstones(expires_at, created_at)
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

_CREATE_TELEMETRY_DAILY_USAGE = """
CREATE TABLE IF NOT EXISTS telemetry_daily_usage (
    day TEXT PRIMARY KEY,
    conversation_turns INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cached_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL,
    uploaded_at INTEGER
)
"""

_CREATE_USAGE_EVENTS = """
CREATE TABLE IF NOT EXISTS usage_events (
    event_id                    TEXT PRIMARY KEY,
    execution_id                TEXT NOT NULL,
    call_index                  INTEGER NOT NULL CHECK (call_index >= 0),
    turn_id                     TEXT,
    agent_run_id                TEXT,
    parent_turn_id              TEXT,
    session_id                  TEXT NOT NULL,
    session_epoch               INTEGER NOT NULL DEFAULT 0 CHECK (session_epoch >= 0),
    agent_id                    TEXT NOT NULL DEFAULT 'main',
    run_kind                    TEXT NOT NULL DEFAULT 'default',
    provider                    TEXT,
    model                       TEXT,
    started_at_ms               INTEGER NOT NULL CHECK (started_at_ms >= 0),
    completed_at_ms             INTEGER,
    status                      TEXT NOT NULL DEFAULT 'started'
                                CHECK (status IN ('started', 'finalized', 'unknown')),
    input_tokens                INTEGER NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens               INTEGER NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    reasoning_tokens            INTEGER NOT NULL DEFAULT 0 CHECK (reasoning_tokens >= 0),
    cache_read_tokens           INTEGER NOT NULL DEFAULT 0 CHECK (cache_read_tokens >= 0),
    cache_write_tokens          INTEGER NOT NULL DEFAULT 0 CHECK (cache_write_tokens >= 0),
    total_tokens                INTEGER NOT NULL DEFAULT 0 CHECK (total_tokens >= 0),
    cost_nanos                  INTEGER NOT NULL DEFAULT 0 CHECK (cost_nanos >= 0),
    billed_cost_nanos           INTEGER NOT NULL DEFAULT 0 CHECK (billed_cost_nanos >= 0),
    estimated_cost_nanos        INTEGER NOT NULL DEFAULT 0 CHECK (estimated_cost_nanos >= 0),
    cost_source                 TEXT NOT NULL DEFAULT 'none',
    estimate_basis              TEXT,
    price_source                TEXT,
    coverage_status             TEXT NOT NULL DEFAULT 'pending',
    missing_cost_entries        INTEGER NOT NULL DEFAULT 0
                                CHECK (missing_cost_entries >= 0),
    unknown_reason              TEXT,
    origin                      TEXT NOT NULL,
    schema_version              INTEGER NOT NULL DEFAULT 1,
    UNIQUE (execution_id, call_index),
    CHECK (completed_at_ms IS NULL OR completed_at_ms >= started_at_ms),
    CHECK (cost_nanos = billed_cost_nanos + estimated_cost_nanos)
)
"""

_CREATE_USAGE_EVENT_ITEMS = """
CREATE TABLE IF NOT EXISTS usage_event_items (
    event_id                    TEXT NOT NULL,
    ordinal                     INTEGER NOT NULL CHECK (ordinal >= 0),
    provider                    TEXT,
    model                       TEXT,
    input_tokens                INTEGER NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens               INTEGER NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    reasoning_tokens            INTEGER NOT NULL DEFAULT 0 CHECK (reasoning_tokens >= 0),
    cache_read_tokens           INTEGER NOT NULL DEFAULT 0 CHECK (cache_read_tokens >= 0),
    cache_write_tokens          INTEGER NOT NULL DEFAULT 0 CHECK (cache_write_tokens >= 0),
    total_tokens                INTEGER NOT NULL DEFAULT 0 CHECK (total_tokens >= 0),
    cost_nanos                  INTEGER NOT NULL DEFAULT 0 CHECK (cost_nanos >= 0),
    billed_cost_nanos           INTEGER NOT NULL DEFAULT 0 CHECK (billed_cost_nanos >= 0),
    estimated_cost_nanos        INTEGER NOT NULL DEFAULT 0 CHECK (estimated_cost_nanos >= 0),
    cost_source                 TEXT NOT NULL DEFAULT 'none',
    estimate_basis              TEXT,
    price_source                TEXT,
    schema_version              INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (event_id, ordinal),
    FOREIGN KEY (event_id) REFERENCES usage_events(event_id) ON DELETE CASCADE,
    CHECK (cost_nanos = billed_cost_nanos + estimated_cost_nanos)
)
"""

_CREATE_USAGE_LEDGER_STATE = """
CREATE TABLE IF NOT EXISTS usage_ledger_state (
    singleton_id                INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    ledger_started_at_ms        INTEGER NOT NULL CHECK (ledger_started_at_ms >= 0),
    backfill_status             TEXT NOT NULL DEFAULT 'pending'
                                CHECK (backfill_status IN
                                       ('pending', 'running', 'complete',
                                        'partial', 'failed')),
    cursor_created_at_ms        INTEGER,
    cursor_session_id           TEXT,
    cursor_message_id           TEXT,
    backfilled_event_count      INTEGER NOT NULL DEFAULT 0
                                CHECK (backfilled_event_count >= 0),
    backfilled_cost_nanos       INTEGER NOT NULL DEFAULT 0
                                CHECK (backfilled_cost_nanos >= 0),
    anomaly_count               INTEGER NOT NULL DEFAULT 0 CHECK (anomaly_count >= 0),
    last_error_code             TEXT,
    updated_at_ms               INTEGER NOT NULL CHECK (updated_at_ms >= 0),
    schema_version              INTEGER NOT NULL DEFAULT 1,
    CHECK (
        (cursor_created_at_ms IS NULL AND cursor_session_id IS NULL
         AND cursor_message_id IS NULL)
        OR
        (cursor_created_at_ms IS NOT NULL AND cursor_session_id IS NOT NULL
         AND cursor_message_id IS NOT NULL)
    )
)
"""

_CREATE_USAGE_LEGACY_BASELINES = """
CREATE TABLE IF NOT EXISTS usage_legacy_baselines (
    session_id                  TEXT NOT NULL,
    session_epoch               INTEGER NOT NULL DEFAULT 0 CHECK (session_epoch >= 0),
    agent_id                    TEXT NOT NULL DEFAULT 'main',
    captured_at_ms              INTEGER NOT NULL CHECK (captured_at_ms >= 0),
    input_tokens                INTEGER NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens               INTEGER NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    total_tokens                INTEGER NOT NULL DEFAULT 0 CHECK (total_tokens >= 0),
    cache_read_tokens           INTEGER NOT NULL DEFAULT 0 CHECK (cache_read_tokens >= 0),
    cache_write_tokens          INTEGER NOT NULL DEFAULT 0 CHECK (cache_write_tokens >= 0),
    cost_nanos                  INTEGER NOT NULL DEFAULT 0 CHECK (cost_nanos >= 0),
    billed_cost_nanos           INTEGER NOT NULL DEFAULT 0 CHECK (billed_cost_nanos >= 0),
    estimated_cost_nanos        INTEGER NOT NULL DEFAULT 0 CHECK (estimated_cost_nanos >= 0),
    cost_source                 TEXT NOT NULL DEFAULT 'none',
    missing_cost_entries        INTEGER NOT NULL DEFAULT 0
                                CHECK (missing_cost_entries >= 0),
    schema_version              INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (session_id, session_epoch),
    CHECK (cost_nanos = billed_cost_nanos + estimated_cost_nanos)
)
"""

_CREATE_IDX_USAGE_EVENTS_COMPLETED = """
CREATE INDEX IF NOT EXISTS idx_usage_events_completed
ON usage_events(completed_at_ms, event_id)
"""
_CREATE_IDX_USAGE_EVENTS_SESSION_COMPLETED = """
CREATE INDEX IF NOT EXISTS idx_usage_events_session_completed
ON usage_events(session_id, completed_at_ms, event_id)
"""
_CREATE_IDX_USAGE_EVENTS_AGENT_COMPLETED = """
CREATE INDEX IF NOT EXISTS idx_usage_events_agent_completed
ON usage_events(agent_id, completed_at_ms, event_id)
"""
_CREATE_IDX_USAGE_EVENTS_STATUS_COMPLETED = """
CREATE INDEX IF NOT EXISTS idx_usage_events_status_completed
ON usage_events(status, completed_at_ms, event_id)
"""
_CREATE_IDX_USAGE_EVENTS_STATUS_STARTED = """
CREATE INDEX IF NOT EXISTS idx_usage_events_status_started
ON usage_events(status, started_at_ms, event_id)
"""
_CREATE_IDX_USAGE_EVENT_ITEMS_MODEL = """
CREATE INDEX IF NOT EXISTS idx_usage_event_items_model
ON usage_event_items(model, event_id, ordinal)
"""
_CREATE_IDX_USAGE_EVENT_ITEMS_PROVIDER = """
CREATE INDEX IF NOT EXISTS idx_usage_event_items_provider
ON usage_event_items(provider, event_id, ordinal)
"""
_CREATE_IDX_USAGE_LEGACY_BASELINES_CAPTURED = """
CREATE INDEX IF NOT EXISTS idx_usage_legacy_baselines_captured
ON usage_legacy_baselines(captured_at_ms, session_id)
"""
_CREATE_IDX_TRANSCRIPT_USAGE_BACKFILL = """
CREATE INDEX IF NOT EXISTS idx_transcript_usage_backfill
ON transcript_entries(created_at, session_id, message_id)
WHERE role = 'assistant' AND turn_usage IS NOT NULL
"""
_CREATE_IDX_COMPACTED_USAGE_BACKFILL = """
CREATE INDEX IF NOT EXISTS idx_compacted_usage_backfill
ON compacted_transcript_entries(created_at, session_id, message_id)
WHERE role = 'assistant' AND turn_usage IS NOT NULL
"""
_CREATE_IDX_SESSIONS_ID_KEY = """
CREATE INDEX IF NOT EXISTS idx_sessions_id_key
ON sessions(session_id, session_key)
"""

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
        "turn_context",
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


def _legacy_nonnegative_integer(value: Any) -> tuple[int, bool]:
    """Return a SQLite-safe counter and whether the source was invalid."""

    if value is None or isinstance(value, bool):
        return 0, True
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return 0, True
    if not parsed.is_finite() or parsed < 0 or parsed != parsed.to_integral_value():
        return 0, True
    integer = int(parsed)
    if integer > (1 << 63) - 1:
        return 0, True
    return integer, False


def _legacy_cost_triplet(
    total_usd: Any,
    billed_usd: Any,
    estimated_usd: Any,
) -> tuple[int, int, int, bool]:
    """Normalize old float columns while preserving the known total.

    A valid legacy total remains authoritative. The billed component is capped
    at that total and the estimate becomes the residual, so every persisted
    baseline satisfies ``cost = billed + estimated``. Any repair is surfaced as
    an anomaly/missing entry rather than silently claiming exact history.
    """

    def parse(value: Any) -> tuple[int, bool]:
        if value is None or isinstance(value, bool):
            return 0, True
        try:
            return usd_to_nanos(value), False
        except (TypeError, ValueError, OverflowError):
            return 0, True

    raw_total, invalid_total = parse(total_usd)
    raw_billed, invalid_billed = parse(billed_usd)
    raw_estimated, invalid_estimated = parse(estimated_usd)
    total = raw_billed + raw_estimated if invalid_total else raw_total
    billed = min(raw_billed, total)
    estimated = total - billed
    anomaly = (
        invalid_total
        or invalid_billed
        or invalid_estimated
        or raw_total != raw_billed + raw_estimated
    )
    return total, billed, estimated, anomaly


def _sqlite_usage_nonnegative_int(value: Any) -> int:
    return _legacy_nonnegative_integer(value)[0]


def _sqlite_usage_invalid_int(value: Any) -> int:
    return int(_legacy_nonnegative_integer(value)[1])


def _sqlite_usage_cost_total(total: Any, billed: Any, estimated: Any) -> int:
    return _legacy_cost_triplet(total, billed, estimated)[0]


def _sqlite_usage_cost_billed(total: Any, billed: Any, estimated: Any) -> int:
    return _legacy_cost_triplet(total, billed, estimated)[1]


def _sqlite_usage_cost_estimated(total: Any, billed: Any, estimated: Any) -> int:
    return _legacy_cost_triplet(total, billed, estimated)[2]


def _sqlite_usage_cost_anomaly(total: Any, billed: Any, estimated: Any) -> int:
    return int(_legacy_cost_triplet(total, billed, estimated)[3])


def _usage_event_from_row(row: Any) -> UsageEventRecord:
    data = dict(row)
    data["status"] = cast(UsageEventStatus, data["status"])
    return UsageEventRecord(**data)


def _usage_item_from_row(row: Any) -> UsageEventItem:
    return UsageEventItem(**dict(row))


def _usage_state_from_row(row: Any) -> UsageLedgerState:
    data = dict(row)
    data.pop("singleton_id", None)
    data["backfill_status"] = cast(UsageBackfillStatus, data["backfill_status"])
    return UsageLedgerState(**data)


def _usage_baseline_from_row(row: Any) -> UsageLegacyBaseline:
    return UsageLegacyBaseline(**dict(row))


def _json_object_or_none(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


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
        self._usage_backfill_index_lock = asyncio.Lock()
        self._usage_backfill_indexes_ready = False
        self._poisoned = False
        self._busy_budget_seconds = _INTERACTIVE_BUSY_BUDGET_SECONDS
        self._sleep = asyncio.sleep
        self._monotonic = time.monotonic
        self._random = random.random
        self._meta_launch_draft_gc_task: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self._db_path, isolation_level=None)
        self._conn.row_factory = aiosqlite.Row
        # Unicode-aware case folding for non-ASCII LIKE search (see _py_lower).
        # aiosqlite proxies create_function to sqlite3 at runtime; its stub omits it.
        await self._conn.create_function(  # type: ignore[attr-defined]
            "py_lower", 1, _py_lower, deterministic=True
        )
        for name, arity, function in (
            ("usage_nonnegative_int", 1, _sqlite_usage_nonnegative_int),
            ("usage_invalid_int", 1, _sqlite_usage_invalid_int),
            ("usage_cost_total", 3, _sqlite_usage_cost_total),
            ("usage_cost_billed", 3, _sqlite_usage_cost_billed),
            ("usage_cost_estimated", 3, _sqlite_usage_cost_estimated),
            ("usage_cost_anomaly", 3, _sqlite_usage_cost_anomaly),
        ):
            await self._conn.create_function(  # type: ignore[attr-defined]
                name, arity, function, deterministic=True
            )
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
        await self._initialize_schema()
        self._meta_launch_draft_gc_task = asyncio.create_task(
            self._run_meta_launch_draft_gc(),
            name="session-storage-meta-launch-draft-gc",
        )

    @classmethod
    async def open(cls, db_path: str) -> SessionStorage:
        storage = cls(str(db_path))
        await storage.connect()
        return storage

    async def close(self) -> None:
        gc_task, self._meta_launch_draft_gc_task = self._meta_launch_draft_gc_task, None
        if gc_task is not None:
            gc_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await gc_task
        async with self._operation_lock:
            if self._conn:
                await self._conn.close()
                self._conn = None

    async def _run_meta_launch_draft_gc(self) -> None:
        """Physically enforce raw-draft retention while the Gateway stays up."""

        while True:
            await asyncio.sleep(_META_LAUNCH_DRAFT_GC_INTERVAL_SECONDS)
            try:
                async with self._write_transaction("meta_launch_draft_periodic_gc") as conn:
                    await self._purge_expired_meta_launch_drafts(
                        conn,
                        now_ms=_now_ms(),
                        limit=_META_LAUNCH_DRAFT_GC_BATCH,
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning("Periodic MetaSkill draft retention cleanup failed", exc_info=True)

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
        await self._conn.execute(_CREATE_META_CONTROL_INTENTS)
        await self._conn.execute(_CREATE_IDX_META_CONTROL_CORRELATION)
        await self._conn.execute(_CREATE_IDX_META_CONTROL_SESSION_STATUS)
        await self._conn.execute(_CREATE_META_LAUNCH_DRAFTS)
        await self._conn.execute(_CREATE_IDX_META_LAUNCH_DRAFT_REQUEST)
        await self._conn.execute(_CREATE_IDX_META_LAUNCH_DRAFT_SESSION_EXPIRY)
        await self._conn.execute(_CREATE_META_LAUNCH_DISCARD_TOMBSTONES)
        await self._conn.execute(_CREATE_IDX_META_LAUNCH_DISCARD_TOMBSTONES_EXPIRY)
        await self._conn.execute(_CREATE_MEMORY_DURABLE_RECEIPTS)
        await self._conn.execute(_CREATE_IDX_MEMORY_DURABLE_RECEIPTS_SESSION)
        await self._conn.execute(_CREATE_TELEMETRY_DAILY_USAGE)
        await self._conn.execute(_CREATE_USAGE_EVENTS)
        await self._conn.execute(_CREATE_USAGE_EVENT_ITEMS)
        await self._conn.execute(_CREATE_USAGE_LEDGER_STATE)
        await self._conn.execute(_CREATE_USAGE_LEGACY_BASELINES)
        await self._conn.execute(_CREATE_IDX_USAGE_EVENTS_COMPLETED)
        await self._conn.execute(_CREATE_IDX_USAGE_EVENTS_SESSION_COMPLETED)
        await self._conn.execute(_CREATE_IDX_USAGE_EVENTS_AGENT_COMPLETED)
        await self._conn.execute(_CREATE_IDX_USAGE_EVENTS_STATUS_COMPLETED)
        await self._conn.execute(_CREATE_IDX_USAGE_EVENTS_STATUS_STARTED)
        await self._conn.execute(_CREATE_IDX_USAGE_EVENT_ITEMS_MODEL)
        await self._conn.execute(_CREATE_IDX_USAGE_EVENT_ITEMS_PROVIDER)
        await self._conn.execute(_CREATE_IDX_USAGE_LEGACY_BASELINES_CAPTURED)
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
        await self._migrate_transcript_turn_context_column()
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
        # Launch drafts contain raw user prompts. Enforce their seven-day
        # retention at every process start even when nobody stages or lists a
        # new draft after the old rows expire.
        await self._purge_expired_meta_launch_drafts(
            self._conn,
            now_ms=_now_ms(),
            limit=_META_LAUNCH_DRAFT_GC_BATCH,
        )
        await self._conn.commit()
        required_recovery_columns = {
            "status",
            "updated_at",
            "ended_at",
            "runtime_ms",
            "started_at",
        }
        if required_recovery_columns <= session_columns:
            await self.mark_abandoned_agent_tasks()

    async def prepare_usage_backfill_indexes(self) -> None:
        """Build optional historical-scan indexes after Gateway readiness.

        V021 and the fresh-install schema deliberately avoid indexing transcript
        history: creating an index scans the complete source table and must not
        delay an upgrade from becoming ready.  The post-ready backfill worker
        calls this method before paging.  File-backed databases use an
        independent connection so the shared interactive connection and its
        operation lock remain available to RPC reads.
        """

        async with self._usage_backfill_index_lock:
            if self._usage_backfill_indexes_ready:
                return
            statements = (
                _CREATE_IDX_TRANSCRIPT_USAGE_BACKFILL,
                _CREATE_IDX_COMPACTED_USAGE_BACKFILL,
                _CREATE_IDX_SESSIONS_ID_KEY,
            )
            if self._db_path == ":memory:":
                async with self._operation_lock:
                    self._raise_if_poisoned()
                    for statement in statements:
                        await self.conn.execute(statement)
                    await self.conn.commit()
            else:
                connection = await aiosqlite.connect(
                    self._db_path,
                    isolation_level=None,
                )
                try:
                    await connection.execute(
                        f"PRAGMA busy_timeout={int(_INTERACTIVE_BUSY_BUDGET_SECONDS * 1000)}"
                    )
                    for statement in statements:
                        await connection.execute(statement)
                finally:
                    await connection.close()
            self._usage_backfill_indexes_ready = True

    async def record_daily_usage(
        self,
        *,
        day: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int,
        cache_write_tokens: int,
        updated_at: int,
    ) -> None:
        """Atomically add one completed interactive turn to a UTC-day bucket."""
        async with self._write_transaction("record_daily_usage") as conn:
            await conn.execute(
                """
                INSERT INTO telemetry_daily_usage (
                    day, conversation_turns, input_tokens, output_tokens,
                    cached_tokens, cache_write_tokens, updated_at, uploaded_at
                ) VALUES (?, 1, ?, ?, ?, ?, ?, NULL)
                ON CONFLICT(day) DO UPDATE SET
                    conversation_turns = conversation_turns + 1,
                    input_tokens = input_tokens + excluded.input_tokens,
                    output_tokens = output_tokens + excluded.output_tokens,
                    cached_tokens = cached_tokens + excluded.cached_tokens,
                    cache_write_tokens = cache_write_tokens + excluded.cache_write_tokens,
                    updated_at = excluded.updated_at,
                    uploaded_at = NULL
                """,
                (
                    day,
                    input_tokens,
                    output_tokens,
                    cached_tokens,
                    cache_write_tokens,
                    updated_at,
                ),
            )

    @_serialized_read
    async def list_pending_daily_usage(self, *, before_day: str) -> list[dict[str, Any]]:
        """Return unsent completed UTC-day aggregates in chronological order."""
        async with self.conn.execute(
            """
            SELECT day, conversation_turns, input_tokens, output_tokens,
                   cached_tokens, cache_write_tokens, updated_at, uploaded_at
            FROM telemetry_daily_usage
            WHERE day < ? AND uploaded_at IS NULL
            ORDER BY day ASC
            """,
            (before_day,),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]

    async def mark_daily_usage_uploaded(
        self,
        *,
        day: str,
        uploaded_at: int,
        expected_conversation_turns: int,
    ) -> bool:
        """Mark a sent snapshot unless another turn changed it in flight."""
        async with self._write_transaction("mark_daily_usage_uploaded") as conn:
            cursor = await conn.execute(
                """
                UPDATE telemetry_daily_usage
                SET uploaded_at = ?
                WHERE day = ? AND conversation_turns = ?
                """,
                (uploaded_at, day, expected_conversation_turns),
            )
            updated = int(cursor.rowcount or 0) > 0
        return updated

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

    async def _migrate_transcript_turn_context_column(self) -> None:
        """Idempotently add causal turn identity to active and archived rows."""
        assert self._conn is not None
        for table in ("transcript_entries", "compacted_transcript_entries"):
            async with self._conn.execute(f"PRAGMA table_info({table})") as cur:
                columns = {row[1] for row in await cur.fetchall()}
            if "turn_context" not in columns:
                await self._conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN turn_context TEXT"
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

    # ── Durable usage ledger ────────────────────────────────────────────────

    async def _get_usage_event_on_conn(
        self,
        conn: Any,
        *,
        event_id: str | None = None,
        execution_id: str | None = None,
        call_index: int | None = None,
    ) -> UsageEventRecord | None:
        if event_id is not None:
            sql = "SELECT * FROM usage_events WHERE event_id = ?"
            params: tuple[Any, ...] = (event_id,)
        elif execution_id is not None and call_index is not None:
            sql = "SELECT * FROM usage_events WHERE execution_id = ? AND call_index = ?"
            params = (execution_id, call_index)
        else:
            raise ValueError("an event id or execution identity is required")
        async with conn.execute(sql, params) as cur:
            row = await cur.fetchone()
        return None if row is None else _usage_event_from_row(row)

    async def _get_usage_items_on_conn(
        self,
        conn: Any,
        event_id: str,
    ) -> list[UsageEventItem]:
        async with conn.execute(
            "SELECT * FROM usage_event_items WHERE event_id = ? ORDER BY ordinal",
            (event_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [_usage_item_from_row(row) for row in rows]

    @staticmethod
    def _assert_usage_start_matches(
        persisted: UsageEventRecord,
        event: UsageEventStart,
    ) -> None:
        persisted_identity = (
            persisted.event_id,
            persisted.execution_id,
            persisted.call_index,
            persisted.session_id,
            persisted.agent_id,
            persisted.session_epoch,
            persisted.turn_id,
            persisted.agent_run_id,
            persisted.parent_turn_id,
            persisted.run_kind,
            persisted.started_at_ms,
            persisted.origin,
        )
        requested_identity = (
            event.event_id,
            event.execution_id,
            event.call_index,
            event.session_id,
            event.agent_id,
            event.session_epoch,
            event.turn_id,
            event.agent_run_id,
            event.parent_turn_id,
            event.run_kind,
            event.started_at_ms,
            event.origin,
        )
        if persisted_identity != requested_identity:
            raise UsageLedgerConflictError(
                "usage event identity was reused with different attribution"
            )

    @staticmethod
    def _assert_usage_completion_matches(
        persisted: UsageEventRecord,
        completion: UsageEventCompletion,
    ) -> None:
        expected_provider = completion.provider or persisted.provider
        expected_model = completion.model or persisted.model
        persisted_payload = (
            persisted.completed_at_ms,
            persisted.input_tokens,
            persisted.output_tokens,
            persisted.reasoning_tokens,
            persisted.cache_read_tokens,
            persisted.cache_write_tokens,
            persisted.total_tokens,
            persisted.cost_nanos,
            persisted.billed_cost_nanos,
            persisted.estimated_cost_nanos,
            persisted.cost_source,
            persisted.provider,
            persisted.model,
            persisted.estimate_basis,
            persisted.price_source,
            persisted.coverage_status,
            persisted.missing_cost_entries,
        )
        requested_payload = (
            completion.completed_at_ms,
            completion.input_tokens,
            completion.output_tokens,
            completion.reasoning_tokens,
            completion.cache_read_tokens,
            completion.cache_write_tokens,
            completion.total_tokens,
            completion.cost_nanos,
            completion.billed_cost_nanos,
            completion.estimated_cost_nanos,
            completion.cost_source,
            expected_provider,
            expected_model,
            completion.estimate_basis,
            completion.price_source,
            completion.coverage_status,
            completion.missing_cost_entries,
        )
        if persisted_payload != requested_payload:
            raise UsageLedgerConflictError(
                "usage event was finalized again with different accounting data"
            )

    @staticmethod
    def _usage_items_match_completion(
        items: Sequence[UsageEventItem],
        completion: UsageEventCompletion,
    ) -> bool:
        if not items:
            return True
        components = (
            ("input_tokens", completion.input_tokens),
            ("output_tokens", completion.output_tokens),
            ("reasoning_tokens", completion.reasoning_tokens),
            ("cache_read_tokens", completion.cache_read_tokens),
            ("cache_write_tokens", completion.cache_write_tokens),
            ("total_tokens", completion.total_tokens),
            ("cost_nanos", completion.cost_nanos),
            ("billed_cost_nanos", completion.billed_cost_nanos),
            ("estimated_cost_nanos", completion.estimated_cost_nanos),
        )
        return all(
            sum(getattr(item, field) for item in items) == expected
            for field, expected in components
        )

    async def _start_usage_event_on_conn(
        self,
        conn: Any,
        event: UsageEventStart,
    ) -> tuple[UsageEventRecord, bool]:
        insert_cursor = await conn.execute(
            """
            INSERT INTO usage_events (
                event_id, execution_id, call_index, turn_id, agent_run_id,
                parent_turn_id, session_id, session_epoch, agent_id, run_kind,
                provider, model, started_at_ms, status, coverage_status, origin
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'started', 'pending', ?)
            ON CONFLICT DO NOTHING
            """,
            (
                event.event_id,
                event.execution_id,
                event.call_index,
                event.turn_id,
                event.agent_run_id,
                event.parent_turn_id,
                event.session_id,
                event.session_epoch,
                event.agent_id,
                event.run_kind,
                event.provider,
                event.model,
                event.started_at_ms,
                event.origin,
            ),
        )
        by_event = await self._get_usage_event_on_conn(conn, event_id=event.event_id)
        by_execution = await self._get_usage_event_on_conn(
            conn,
            execution_id=event.execution_id,
            call_index=event.call_index,
        )
        if by_event is None or by_execution is None or by_event.event_id != by_execution.event_id:
            raise UsageLedgerConflictError(
                "usage event id and execution identity refer to different records"
            )
        self._assert_usage_start_matches(by_event, event)
        created = insert_cursor.rowcount == 1
        return by_event, created

    async def _resolve_live_usage_start_on_conn(
        self,
        conn: Any,
        event: UsageEventStart,
    ) -> UsageEventStart:
        """Fill default live attribution from the current session row.

        Exact event replays retain the originally persisted epoch even if the
        session has reset since the first reservation.
        """

        if event.origin != "live_provider":
            return event
        persisted = await self._get_usage_event_on_conn(conn, event_id=event.event_id)
        if persisted is None:
            persisted = await self._get_usage_event_on_conn(
                conn,
                execution_id=event.execution_id,
                call_index=event.call_index,
            )
        if persisted is not None:
            return replace(
                event,
                agent_id=persisted.agent_id,
                session_epoch=persisted.session_epoch,
            )
        async with conn.execute(
            """
            SELECT agent_id, epoch
            FROM sessions
            WHERE session_id = ?
            ORDER BY session_key
            LIMIT 1
            """,
            (event.session_id,),
        ) as cur:
            session_row = await cur.fetchone()
        if session_row is None:
            return event
        return replace(
            event,
            agent_id=str(session_row["agent_id"] or event.agent_id),
            session_epoch=max(0, int(session_row["epoch"] or 0)),
        )

    async def start_usage_event(self, event: UsageEventStart) -> UsageEventRecord:
        """Durably reserve a provider-call identity before the request is sent.

        Repeating the exact call is idempotent. Reusing either unique identity
        with different attribution raises ``UsageLedgerConflictError``.
        """

        validate_usage_event_start(event)
        async with self._write_transaction("start_usage_event") as conn:
            resolved_event = await self._resolve_live_usage_start_on_conn(conn, event)
            validate_usage_event_start(resolved_event)
            record, _created = await self._start_usage_event_on_conn(conn, resolved_event)
            return record

    async def _finalize_usage_event_on_conn(
        self,
        conn: Any,
        event_id: str,
        completion: UsageEventCompletion,
        items: Sequence[UsageEventItem],
    ) -> tuple[UsageEventRecord, bool]:
        persisted = await self._get_usage_event_on_conn(conn, event_id=event_id)
        if persisted is None:
            raise KeyError(f"usage event not found: {event_id}")
        if completion.completed_at_ms < persisted.started_at_ms:
            raise ValueError("completed_at_ms must not precede started_at_ms")

        seen_ordinals: set[int] = set()
        for item in items:
            validate_usage_item(item, event_id=event_id)
            if item.ordinal in seen_ordinals:
                raise ValueError("usage item ordinals must be unique per event")
            seen_ordinals.add(item.ordinal)
        if items and not self._usage_items_match_completion(items, completion):
            raise ValueError(
                "usage items must reconcile exactly with their event envelope"
            )

        if persisted.status == "finalized":
            self._assert_usage_completion_matches(persisted, completion)
            persisted_items = await self._get_usage_items_on_conn(conn, event_id)
            if persisted_items != sorted(items, key=lambda item: item.ordinal):
                raise UsageLedgerConflictError(
                    "usage event was finalized again with different model items"
                )
            return persisted, False

        provider = completion.provider or persisted.provider
        model = completion.model or persisted.model
        await conn.execute(
            """
            UPDATE usage_events
            SET completed_at_ms = ?, status = 'finalized', input_tokens = ?,
                output_tokens = ?, reasoning_tokens = ?, cache_read_tokens = ?,
                cache_write_tokens = ?, total_tokens = ?, cost_nanos = ?,
                billed_cost_nanos = ?, estimated_cost_nanos = ?, cost_source = ?,
                provider = ?, model = ?, estimate_basis = ?, price_source = ?,
                coverage_status = ?, missing_cost_entries = ?, unknown_reason = NULL
            WHERE event_id = ?
            """,
            (
                completion.completed_at_ms,
                completion.input_tokens,
                completion.output_tokens,
                completion.reasoning_tokens,
                completion.cache_read_tokens,
                completion.cache_write_tokens,
                completion.total_tokens,
                completion.cost_nanos,
                completion.billed_cost_nanos,
                completion.estimated_cost_nanos,
                completion.cost_source,
                provider,
                model,
                completion.estimate_basis,
                completion.price_source,
                completion.coverage_status,
                completion.missing_cost_entries,
                event_id,
            ),
        )
        await conn.execute("DELETE FROM usage_event_items WHERE event_id = ?", (event_id,))
        for item in sorted(items, key=lambda item: item.ordinal):
            await conn.execute(
                """
                INSERT INTO usage_event_items (
                    event_id, ordinal, provider, model, input_tokens, output_tokens,
                    reasoning_tokens, cache_read_tokens, cache_write_tokens,
                    total_tokens, cost_nanos, billed_cost_nanos,
                    estimated_cost_nanos, cost_source, estimate_basis, price_source,
                    schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.event_id,
                    item.ordinal,
                    item.provider,
                    item.model,
                    item.input_tokens,
                    item.output_tokens,
                    item.reasoning_tokens,
                    item.cache_read_tokens,
                    item.cache_write_tokens,
                    item.total_tokens,
                    item.cost_nanos,
                    item.billed_cost_nanos,
                    item.estimated_cost_nanos,
                    item.cost_source,
                    item.estimate_basis,
                    item.price_source,
                    item.schema_version,
                ),
            )
        finalized = await self._get_usage_event_on_conn(conn, event_id=event_id)
        assert finalized is not None
        return finalized, True

    async def finalize_usage_event(
        self,
        event_id: str,
        completion: UsageEventCompletion,
        *,
        items: Sequence[UsageEventItem] = (),
    ) -> UsageEventRecord:
        """Atomically finalize one event and all of its per-model items."""

        if not event_id:
            raise ValueError("event_id must not be empty")
        validate_usage_completion(completion)
        async with self._write_transaction("finalize_usage_event") as conn:
            record, _changed = await self._finalize_usage_event_on_conn(
                conn, event_id, completion, items
            )
            return record

    async def mark_usage_event_unknown(
        self,
        event_id: str,
        *,
        completed_at_ms: int,
        reason: str | None = None,
    ) -> UsageEventRecord:
        """Mark a started provider request as having no trustworthy usage receipt.

        A concurrent successful finalization wins and is never downgraded.
        ``reason`` must be a stable code, not a raw provider error message.
        """

        if not event_id:
            raise ValueError("event_id must not be empty")
        if completed_at_ms < 0:
            raise ValueError("completed_at_ms must be non-negative")
        stable_reason = normalize_usage_unknown_reason(reason)
        async with self._write_transaction("mark_usage_event_unknown") as conn:
            persisted = await self._get_usage_event_on_conn(conn, event_id=event_id)
            if persisted is None:
                raise KeyError(f"usage event not found: {event_id}")
            if persisted.status == "finalized":
                return persisted
            if persisted.status == "unknown":
                return persisted
            if completed_at_ms < persisted.started_at_ms:
                raise ValueError("completed_at_ms must not precede started_at_ms")
            await conn.execute(
                """
                UPDATE usage_events
                SET completed_at_ms = ?, status = 'unknown',
                    coverage_status = 'usage_unknown', missing_cost_entries = 1,
                    unknown_reason = ?
                WHERE event_id = ? AND status = 'started'
                """,
                (completed_at_ms, stable_reason, event_id),
            )
            record = await self._get_usage_event_on_conn(conn, event_id=event_id)
            assert record is not None
            return record

    async def recover_started_usage_events(
        self,
        *,
        completed_at_ms: int | None = None,
        reason: str = "process_restarted",
        started_before_ms: int | None = None,
    ) -> int:
        """Terminalize provider reservations left open by an earlier process.

        Boot should call this before accepting new turns. The optional strict
        ``started_before_ms`` cutoff lets tests or embedding hosts avoid touching
        requests reserved by another known-live writer.
        """

        recovered_at_ms = _now_ms() if completed_at_ms is None else completed_at_ms
        if recovered_at_ms < 0:
            raise ValueError("completed_at_ms must be non-negative")
        if started_before_ms is not None and started_before_ms < 0:
            raise ValueError("started_before_ms must be non-negative")
        stable_reason = normalize_usage_unknown_reason(reason)
        clauses = ["status = 'started'"]
        params: list[Any] = [recovered_at_ms, recovered_at_ms, stable_reason]
        if started_before_ms is not None:
            clauses.append("started_at_ms < ?")
            params.append(started_before_ms)
        async with self._write_transaction("recover_started_usage_events") as conn:
            cursor = await conn.execute(
                """
                UPDATE usage_events
                SET completed_at_ms = CASE
                        WHEN started_at_ms > ? THEN started_at_ms ELSE ?
                    END,
                    status = 'unknown', coverage_status = 'usage_unknown',
                    missing_cost_entries = 1, unknown_reason = ?
                WHERE """
                + " AND ".join(clauses),
                params,
            )
            return max(0, int(cursor.rowcount or 0))

    async def initialize_usage_ledger(
        self,
        now_ms: int | None = None,
    ) -> UsageLedgerState:
        """Atomically establish cutover and snapshot legacy totals with set SQL."""

        captured_at_ms = _now_ms() if now_ms is None else now_ms
        if captured_at_ms < 0:
            raise ValueError("now_ms must be non-negative")

        async with self._write_transaction("initialize_usage_ledger") as conn:
            existing = await self._get_usage_state_on_conn(conn)
            if existing is not None:
                return existing

            await conn.execute(
                """
                INSERT INTO usage_ledger_state (
                    singleton_id, ledger_started_at_ms, backfill_status, updated_at_ms
                ) VALUES (1, ?, 'pending', ?)
                """,
                (captured_at_ms, captured_at_ms),
            )
            # One bounded INSERT...SELECT replaces a Python row loop and keeps
            # the pre-live cutover transaction short even for large histories.
            # The registered deterministic functions sanitize corrupt legacy
            # values without aborting gateway startup.
            await conn.execute(
                """
                WITH normalized AS (
                    SELECT
                        session_key,
                        session_id,
                        usage_nonnegative_int(epoch) AS session_epoch,
                        COALESCE(NULLIF(agent_id, ''), 'main') AS agent_id,
                        usage_nonnegative_int(input_tokens) AS input_tokens,
                        usage_nonnegative_int(output_tokens) AS output_tokens,
                        usage_nonnegative_int(cache_read) AS cache_read_tokens,
                        usage_nonnegative_int(cache_write) AS cache_write_tokens,
                        usage_cost_total(
                            total_cost_usd,
                            billed_cost_usd,
                            estimated_cost_component_usd
                        ) AS cost_nanos,
                        usage_cost_billed(
                            total_cost_usd,
                            billed_cost_usd,
                            estimated_cost_component_usd
                        ) AS billed_cost_nanos,
                        usage_cost_estimated(
                            total_cost_usd,
                            billed_cost_usd,
                            estimated_cost_component_usd
                        ) AS estimated_cost_nanos,
                        COALESCE(NULLIF(cost_source, ''), 'none') AS cost_source,
                        usage_nonnegative_int(missing_cost_entries) AS missing_entries,
                        usage_invalid_int(epoch)
                            + usage_invalid_int(input_tokens)
                            + usage_invalid_int(output_tokens)
                            + usage_invalid_int(total_tokens)
                            + usage_invalid_int(cache_read)
                            + usage_invalid_int(cache_write)
                            + usage_invalid_int(missing_cost_entries)
                            + CASE WHEN usage_nonnegative_int(total_tokens)
                                != usage_nonnegative_int(input_tokens)
                                   + usage_nonnegative_int(output_tokens)
                              THEN 1 ELSE 0 END
                            + usage_cost_anomaly(
                                total_cost_usd,
                                billed_cost_usd,
                                estimated_cost_component_usd
                              ) AS row_anomalies
                    FROM sessions
                ), ranked AS (
                    SELECT
                        normalized.*,
                        ROW_NUMBER() OVER (
                            PARTITION BY session_id, session_epoch
                            ORDER BY session_key
                        ) AS baseline_rank
                    FROM normalized
                )
                INSERT INTO usage_legacy_baselines (
                    session_id, session_epoch, agent_id, captured_at_ms,
                    input_tokens, output_tokens, total_tokens, cache_read_tokens,
                    cache_write_tokens, cost_nanos, billed_cost_nanos,
                    estimated_cost_nanos, cost_source, missing_cost_entries
                )
                SELECT
                    session_id,
                    session_epoch,
                    agent_id,
                    ?,
                    input_tokens,
                    output_tokens,
                    input_tokens + output_tokens,
                    cache_read_tokens,
                    cache_write_tokens,
                    cost_nanos,
                    billed_cost_nanos,
                    estimated_cost_nanos,
                    cost_source,
                    missing_entries + row_anomalies
                FROM ranked
                WHERE baseline_rank = 1
                """,
                (captured_at_ms,),
            )
            await conn.execute(
                """
                UPDATE usage_ledger_state
                SET anomaly_count =
                    COALESCE((
                        SELECT SUM(
                            usage_invalid_int(epoch)
                            + usage_invalid_int(input_tokens)
                            + usage_invalid_int(output_tokens)
                            + usage_invalid_int(total_tokens)
                            + usage_invalid_int(cache_read)
                            + usage_invalid_int(cache_write)
                            + usage_invalid_int(missing_cost_entries)
                            + CASE WHEN usage_nonnegative_int(total_tokens)
                                != usage_nonnegative_int(input_tokens)
                                   + usage_nonnegative_int(output_tokens)
                              THEN 1 ELSE 0 END
                            + usage_cost_anomaly(
                                total_cost_usd,
                                billed_cost_usd,
                                estimated_cost_component_usd
                              )
                        )
                        FROM sessions
                    ), 0)
                    + COALESCE((
                        SELECT SUM(duplicate_count - 1)
                        FROM (
                            SELECT COUNT(*) AS duplicate_count
                            FROM sessions
                            GROUP BY session_id, usage_nonnegative_int(epoch)
                            HAVING COUNT(*) > 1
                        )
                    ), 0)
                WHERE singleton_id = 1
                """
            )
            state = await self._get_usage_state_on_conn(conn)
            assert state is not None
            return state

    @_serialized_read
    async def get_usage_ledger_state(self) -> UsageLedgerState | None:
        async with self.conn.execute(
            "SELECT * FROM usage_ledger_state WHERE singleton_id = 1"
        ) as cur:
            row = await cur.fetchone()
        return None if row is None else _usage_state_from_row(row)

    @_serialized_read
    async def list_usage_legacy_baselines(self) -> list[UsageLegacyBaseline]:
        async with self.conn.execute(
            """
            SELECT * FROM usage_legacy_baselines
            ORDER BY captured_at_ms, session_id, session_epoch
            """
        ) as cur:
            rows = await cur.fetchall()
        return [_usage_baseline_from_row(row) for row in rows]

    @_serialized_read
    async def resolve_usage_session_keys(
        self,
        session_ids: Sequence[str],
    ) -> dict[str, str]:
        """Resolve only currently live session ids to navigable session keys."""

        unique_ids = list(dict.fromkeys(value for value in session_ids if value))
        resolved: dict[str, str] = {}
        for start in range(0, len(unique_ids), _SQLITE_VARIABLE_CHUNK_SIZE):
            chunk = unique_ids[start : start + _SQLITE_VARIABLE_CHUNK_SIZE]
            placeholders = ", ".join("?" for _ in chunk)
            async with self.conn.execute(
                "SELECT session_id, session_key FROM sessions "
                f"WHERE session_id IN ({placeholders}) "  # noqa: S608
                "ORDER BY session_id, session_key",
                chunk,
            ) as cur:
                rows = await cur.fetchall()
            for row in rows:
                resolved.setdefault(str(row["session_id"]), str(row["session_key"]))
        return resolved

    @_serialized_read
    async def query_usage_events(
        self,
        from_ms: int | None,
        to_ms: int | None,
        statuses: Sequence[UsageEventStatus] = ("finalized",),
        session_id: str | None = None,
    ) -> list[UsageEventRecord]:
        """Read terminal events whose completion time is in ``[from_ms, to_ms)``."""

        if from_ms is not None and from_ms < 0:
            raise ValueError("from_ms must be non-negative")
        if to_ms is not None and to_ms < 0:
            raise ValueError("to_ms must be non-negative")
        if from_ms is not None and to_ms is not None and from_ms > to_ms:
            raise ValueError("from_ms must not exceed to_ms")
        allowed_statuses = {"started", "finalized", "unknown"}
        if any(status not in allowed_statuses for status in statuses):
            raise ValueError("unsupported usage event status")
        if not statuses:
            return []
        clauses = [f"status IN ({', '.join('?' for _ in statuses)})"]
        params: list[Any] = list(statuses)
        if from_ms is not None:
            clauses.append("completed_at_ms >= ?")
            params.append(from_ms)
        if to_ms is not None:
            clauses.append("completed_at_ms < ?")
            params.append(to_ms)
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        # Keep the range/order traversal anchored on completion time.  Without
        # the hint SQLite can prefer the recovery-oriented status/started index
        # and materialize a temporary sort, which degrades as the ledger grows.
        range_index = (
            "idx_usage_events_session_completed"
            if session_id is not None
            else "idx_usage_events_completed"
        )
        sql = (
            f"SELECT * FROM usage_events INDEXED BY {range_index} WHERE "  # noqa: S608
            + " AND ".join(clauses)
            + " ORDER BY completed_at_ms, event_id"
        )
        async with self.conn.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [_usage_event_from_row(row) for row in rows]

    @_serialized_read
    async def query_usage_event_items(
        self,
        event_ids: Sequence[str],
    ) -> list[UsageEventItem]:
        if not event_ids:
            return []
        unique_ids = list(dict.fromkeys(event_ids))
        items: list[UsageEventItem] = []
        for start in range(0, len(unique_ids), _SQLITE_VARIABLE_CHUNK_SIZE):
            chunk = unique_ids[start : start + _SQLITE_VARIABLE_CHUNK_SIZE]
            placeholders = ", ".join("?" for _ in chunk)
            async with self.conn.execute(
                "SELECT * FROM usage_event_items "
                f"WHERE event_id IN ({placeholders}) ORDER BY event_id, ordinal",  # noqa: S608
                chunk,
            ) as cur:
                rows = await cur.fetchall()
            items.extend(_usage_item_from_row(row) for row in rows)
        return items

    @_serialized_read
    async def get_usage_backfill_batch(
        self,
        *,
        before_ms: int,
        after: UsageBackfillCursor | None = None,
        limit: int = 500,
    ) -> UsageBackfillBatch:
        """Return canonical pre-cutover assistant rows in stable cursor order.

        Active and compacted copies are deduplicated by ``session_id`` and
        ``message_id``. Current session metadata is joined by ``session_id`` so
        the worker can reject inherited fork rows without a stable ``turn_id``.
        """

        if before_ms < 0:
            raise ValueError("before_ms must be non-negative")
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        cursor_clause = ""
        cursor_params: list[Any] = []
        if after is not None:
            if after.created_at_ms < 0 or not after.session_id or not after.message_id:
                raise ValueError("backfill cursor fields must be valid")
            cursor_clause = (
                "AND (created_at, session_id, message_id) > (?, ?, ?)"
            )
            cursor_params.extend(
                (after.created_at_ms, after.session_id, after.message_id)
            )

        # Read at most one page from each indexed canonical source, then merge
        # and deduplicate in memory. This keeps every page O(log N + limit)
        # instead of rerunning ROW_NUMBER over the complete history.
        source_rows: list[tuple[int, dict[str, Any]]] = []
        source_full = False
        for priority, table in enumerate(
            ("transcript_entries", "compacted_transcript_entries")
        ):
            params = [before_ms, *cursor_params, limit + 1]
            sql = f"""
                SELECT session_id, message_id, created_at, turn_usage, turn_context
                FROM {table}
                WHERE role = 'assistant' AND turn_usage IS NOT NULL
                  AND created_at < ? {cursor_clause}
                ORDER BY created_at, session_id, message_id
                LIMIT ?
            """  # noqa: S608 - table is selected from fixed internal literals.
            async with self.conn.execute(sql, params) as cur:
                rows = await cur.fetchall()
            source_full = source_full or len(rows) > limit
            source_rows.extend((priority, dict(row)) for row in rows)

        canonical: dict[tuple[str, str], tuple[int, dict[str, Any]]] = {}
        for priority, row in source_rows:
            identity = (str(row["session_id"]), str(row["message_id"]))
            current = canonical.get(identity)
            if current is None or priority < current[0]:
                canonical[identity] = (priority, row)
        merged = sorted(
            canonical.values(),
            key=lambda value: (
                int(value[1]["created_at"]),
                str(value[1]["session_id"]),
                str(value[1]["message_id"]),
                value[0],
            ),
        )
        selected = [row for _priority, row in merged[:limit]]
        exhausted = not source_full and len(merged) <= limit

        metadata: dict[str, tuple[str, int, bool]] = {}
        session_ids = list(dict.fromkeys(str(row["session_id"]) for row in selected))
        for start in range(0, len(session_ids), _SQLITE_VARIABLE_CHUNK_SIZE):
            chunk = session_ids[start : start + _SQLITE_VARIABLE_CHUNK_SIZE]
            placeholders = ", ".join("?" for _ in chunk)
            async with self.conn.execute(
                "SELECT session_id, agent_id, epoch, forked_from_parent "
                "FROM sessions "
                f"WHERE session_id IN ({placeholders}) "  # noqa: S608
                "ORDER BY session_id, session_key",
                chunk,
            ) as cur:
                session_rows = await cur.fetchall()
            for row in session_rows:
                metadata.setdefault(
                    str(row["session_id"]),
                    (
                        str(row["agent_id"] or "main"),
                        max(0, int(row["epoch"] or 0)),
                        bool(row["forked_from_parent"]),
                    ),
                )

        entries = tuple(
            UsageBackfillEntry(
                cursor=UsageBackfillCursor(
                    created_at_ms=int(row["created_at"]),
                    session_id=str(row["session_id"]),
                    message_id=str(row["message_id"]),
                ),
                agent_id=metadata.get(str(row["session_id"]), ("main", 0, False))[0],
                session_epoch=metadata.get(
                    str(row["session_id"]), ("main", 0, False)
                )[1],
                forked_from_parent=metadata.get(
                    str(row["session_id"]), ("main", 0, False)
                )[2],
                turn_usage=_json_object_or_none(row["turn_usage"]),
                turn_context=_json_object_or_none(row["turn_context"]),
                session_metadata_missing=str(row["session_id"]) not in metadata,
            )
            for row in selected
        )
        return UsageBackfillBatch(
            entries=entries,
            next_cursor=entries[-1].cursor if entries else after,
            exhausted=exhausted,
        )

    async def update_usage_backfill_progress(
        self,
        *,
        status: UsageBackfillStatus,
        cursor: UsageBackfillCursor | None = None,
        backfilled_event_count_delta: int = 0,
        backfilled_cost_nanos_delta: int = 0,
        anomaly_count_delta: int = 0,
        last_error_code: str | None = None,
        now_ms: int | None = None,
    ) -> UsageLedgerState:
        """Update resumable worker state when no event batch is being committed."""

        allowed_statuses = {"pending", "running", "complete", "partial", "failed"}
        if status not in allowed_statuses:
            raise ValueError("unsupported usage backfill status")
        for label, value in (
            ("backfilled_event_count_delta", backfilled_event_count_delta),
            ("backfilled_cost_nanos_delta", backfilled_cost_nanos_delta),
            ("anomaly_count_delta", anomaly_count_delta),
        ):
            if value < 0:
                raise ValueError(f"{label} must be non-negative")
        updated_at_ms = _now_ms() if now_ms is None else now_ms
        if updated_at_ms < 0:
            raise ValueError("now_ms must be non-negative")
        if last_error_code is not None and (
            not last_error_code or len(last_error_code) > 128
        ):
            raise ValueError("last_error_code must be a stable code up to 128 characters")
        async with self._write_transaction("update_usage_backfill_progress") as conn:
            state = await self._get_usage_state_on_conn(conn)
            if state is None:
                raise RuntimeError("usage ledger must be initialized before backfill")
            self._validate_usage_backfill_cursor_advance(state, cursor)
            effective_cursor = cursor or self._cursor_from_usage_state(state)
            await conn.execute(
                """
                UPDATE usage_ledger_state
                SET backfill_status = ?, cursor_created_at_ms = ?,
                    cursor_session_id = ?, cursor_message_id = ?,
                    backfilled_event_count = backfilled_event_count + ?,
                    backfilled_cost_nanos = backfilled_cost_nanos + ?,
                    anomaly_count = anomaly_count + ?, last_error_code = ?,
                    updated_at_ms = ?
                WHERE singleton_id = 1
                """,
                (
                    status,
                    effective_cursor.created_at_ms if effective_cursor else None,
                    effective_cursor.session_id if effective_cursor else None,
                    effective_cursor.message_id if effective_cursor else None,
                    backfilled_event_count_delta,
                    backfilled_cost_nanos_delta,
                    anomaly_count_delta,
                    last_error_code,
                    updated_at_ms,
                ),
            )
            updated = await self._get_usage_state_on_conn(conn)
            assert updated is not None
            return updated

    async def _get_usage_state_on_conn(self, conn: Any) -> UsageLedgerState | None:
        async with conn.execute(
            "SELECT * FROM usage_ledger_state WHERE singleton_id = 1"
        ) as cur:
            row = await cur.fetchone()
        return None if row is None else _usage_state_from_row(row)

    @staticmethod
    def _cursor_from_usage_state(state: UsageLedgerState) -> UsageBackfillCursor | None:
        if (
            state.cursor_created_at_ms is None
            or state.cursor_session_id is None
            or state.cursor_message_id is None
        ):
            return None
        return UsageBackfillCursor(
            state.cursor_created_at_ms,
            state.cursor_session_id,
            state.cursor_message_id,
        )

    @classmethod
    def _validate_usage_backfill_cursor_advance(
        cls,
        state: UsageLedgerState,
        cursor: UsageBackfillCursor | None,
    ) -> None:
        if cursor is not None and (
            cursor.created_at_ms < 0 or not cursor.session_id or not cursor.message_id
        ):
            raise ValueError("backfill cursor fields must be valid")
        previous = cls._cursor_from_usage_state(state)
        if cursor is not None and previous is not None and cursor < previous:
            raise ValueError("backfill cursor must not move backwards")

    async def apply_usage_backfill_batch(
        self,
        writes: Sequence[UsageBackfillWrite],
        *,
        cursor: UsageBackfillCursor | None,
        exhausted: bool,
        anomaly_delta: int = 0,
        now_ms: int | None = None,
    ) -> UsageLedgerState:
        """Atomically persist historical events, their items, and worker cursor.

        Retrying an ambiguously committed batch does not increment state totals
        twice because exact finalized events are treated as idempotent replays.
        """

        if anomaly_delta < 0:
            raise ValueError("anomaly_delta must be non-negative")
        updated_at_ms = _now_ms() if now_ms is None else now_ms
        if updated_at_ms < 0:
            raise ValueError("now_ms must be non-negative")
        for write in writes:
            validate_usage_event_start(write.start)
            validate_usage_completion(write.completion)
            if write.start.origin != "backfilled_turn":
                raise ValueError("backfill events must use origin='backfilled_turn'")
            for item in write.items:
                validate_usage_item(item, event_id=write.start.event_id)

        async with self._write_transaction("apply_usage_backfill_batch") as conn:
            state = await self._get_usage_state_on_conn(conn)
            if state is None:
                raise RuntimeError("usage ledger must be initialized before backfill")
            self._validate_usage_backfill_cursor_advance(state, cursor)
            effective_cursor = cursor or self._cursor_from_usage_state(state)
            added_count = 0
            added_cost_nanos = 0
            implicit_anomalies = 0
            for write in writes:
                if write.completion.completed_at_ms >= state.ledger_started_at_ms:
                    raise ValueError("backfill events must complete before ledger cutover")
                if not self._usage_items_match_completion(
                    write.items,
                    write.completion,
                ):
                    implicit_anomalies += 1
                    continue
                existing = await self._get_usage_event_on_conn(
                    conn, event_id=write.start.event_id
                )
                if (
                    existing is not None
                    and existing.origin == "backfilled_turn"
                    and write.start.turn_id
                    and existing.turn_id == write.start.turn_id
                    and existing.execution_id == write.start.execution_id
                    and existing.call_index == write.start.call_index
                ):
                    if existing.status == "finalized":
                        try:
                            self._assert_usage_completion_matches(
                                existing, write.completion
                            )
                            existing_items = await self._get_usage_items_on_conn(
                                conn, existing.event_id
                            )
                            if existing_items != sorted(
                                write.items, key=lambda item: item.ordinal
                            ):
                                raise UsageLedgerConflictError(
                                    "fork copy has different model usage items"
                                )
                        except UsageLedgerConflictError:
                            implicit_anomalies += 1
                        # A proven inherited fork copy is attribution of the
                        # same physical spend, never another billable event.
                        continue
                await self._start_usage_event_on_conn(conn, write.start)
                _record, changed = await self._finalize_usage_event_on_conn(
                    conn,
                    write.start.event_id,
                    write.completion,
                    write.items,
                )
                if changed:
                    added_count += 1
                    added_cost_nanos += write.completion.cost_nanos

            total_anomaly_delta = anomaly_delta + implicit_anomalies
            cumulative_anomalies = state.anomaly_count + total_anomaly_delta
            if exhausted:
                next_status = "partial" if cumulative_anomalies else "complete"
            else:
                next_status = "running"
            await conn.execute(
                """
                UPDATE usage_ledger_state
                SET backfill_status = ?, cursor_created_at_ms = ?,
                    cursor_session_id = ?, cursor_message_id = ?,
                    backfilled_event_count = backfilled_event_count + ?,
                    backfilled_cost_nanos = backfilled_cost_nanos + ?,
                    anomaly_count = anomaly_count + ?, last_error_code = NULL,
                    updated_at_ms = ?
                WHERE singleton_id = 1
                """,
                (
                    next_status,
                    effective_cursor.created_at_ms if effective_cursor else None,
                    effective_cursor.session_id if effective_cursor else None,
                    effective_cursor.message_id if effective_cursor else None,
                    added_count,
                    added_cost_nanos,
                    total_anomaly_delta,
                    updated_at_ms,
                ),
            )
            updated = await self._get_usage_state_on_conn(conn)
            assert updated is not None
            return updated

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
            # Drafts and controls may predate the first accepted turn and
            # therefore be attached to a provisional key with no sessions row.
            # Convert their content-free coordinates into finite tombstones
            # before the early return below, so a stale browser outbox cannot
            # recreate a deleted chat with the same ingress identity.
            await self._tombstone_meta_launches_for_boundary(
                conn,
                session_key=session_key,
                now_ms=_now_ms(),
                intent_statuses=("staged", "accepted"),
            )
            await conn.execute(
                "DELETE FROM meta_launch_drafts WHERE session_key = ?",
                (session_key,),
            )
            await conn.execute(
                "DELETE FROM meta_control_intents WHERE session_key = ?",
                (session_key,),
            )
            async with conn.execute(
                "SELECT * FROM sessions WHERE session_key = ?", (session_key,)
            ) as cur:
                row = await cur.fetchone()
            if row is not None:
                session = SessionNode(**_deserialize_row(dict(row)))
            if session is not None:
                for table in (
                    "transcript_entries",
                    "compacted_transcript_entries",
                    "session_summaries",
                ):
                    await conn.execute(
                        f"DELETE FROM {table} WHERE session_id = ?",  # noqa: S608
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
                            f"DELETE FROM {table} WHERE session_key = ?",  # noqa: S608
                            (session_key,),
                        )
                for table in ("agent_tasks", "memory_durable_receipts"):
                    await conn.execute(
                        f"DELETE FROM {table} WHERE session_key = ?",  # noqa: S608
                        (session_key,),
                    )
                await conn.execute(
                    "DELETE FROM turn_ingress_receipts WHERE accepted_session_key = ?",
                    (session_key,),
                )
                await conn.execute("DELETE FROM sessions WHERE session_key = ?", (session_key,))

        _clear_pending_meta_launch_boundary(session_key)
        if session is None:
            return

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

    async def advance_reset_epoch(self, session_key: str) -> int:
        """Fence a same-key reset and invalidate its unaccepted MetaSkill controls.

        The epoch transition and staged-control deletion share one transaction,
        so another client retaining an old hidden control can never observe the
        new epoch while its pre-reset authorization is still consumable. Recent
        accepted browser coordinates are also fenced against stale outbox
        retries; their intent rows remain immutable history.
        """

        session_key = canonicalize_session_key(session_key)
        async with self._write_transaction("advance_reset_epoch") as conn:
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
            await self._tombstone_meta_launches_for_boundary(
                conn,
                session_key=session_key,
                now_ms=_now_ms(),
                intent_statuses=("staged", "accepted"),
            )
            await conn.execute(
                "DELETE FROM meta_control_intents WHERE session_key = ? AND status = 'staged'",
                (session_key,),
            )
            await conn.execute(
                "DELETE FROM meta_launch_drafts WHERE session_key = ?",
                (session_key,),
            )
            new_epoch = int(row[0])
        _clear_pending_meta_launch_boundary(session_key)
        return new_epoch

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
        terminal_session_statuses = (
            SessionStatus.DONE,
            SessionStatus.FAILED,
            SessionStatus.KILLED,
            SessionStatus.TIMEOUT,
        )
        async with self._write_transaction("mark_abandoned_agent_tasks") as conn:
            async with conn.execute(
                """
                SELECT DISTINCT agent_tasks.session_key
                FROM agent_tasks
                JOIN sessions ON sessions.session_key = agent_tasks.session_key
                WHERE sessions.status NOT IN (?, ?, ?, ?)
                  AND (
                    agent_tasks.status IN (?, ?)
                    OR (
                        agent_tasks.status = ?
                        AND agent_tasks.terminal_reason = ?
                    )
                  )
                """,
                (
                    *terminal_session_statuses,
                    AgentTaskStatus.QUEUED,
                    AgentTaskStatus.RUNNING,
                    AgentTaskStatus.ABANDONED,
                    "process_restart",
                ),
            ) as session_cur:
                session_keys = [str(row[0]) for row in await session_cur.fetchall()]

            cur = await conn.execute(
                """
                UPDATE agent_tasks
                SET status = ?,
                    updated_at = ?,
                    finished_at = COALESCE(finished_at, ?),
                    terminal_reason = CASE
                        WHEN status = ? AND EXISTS (
                            SELECT 1 FROM meta_control_intents AS intent
                            WHERE intent.accepted_task_id = agent_tasks.task_id
                              AND intent.status = 'accepted'
                        ) AND EXISTS (
                            SELECT 1 FROM sessions AS owner
                            WHERE owner.session_key = agent_tasks.session_key
                              AND owner.status NOT IN (?, ?, ?, ?)
                        ) THEN 'meta_control_restart_before_start'
                        ELSE COALESCE(terminal_reason, ?)
                    END
                WHERE status IN (?, ?)
                """,
                (
                    AgentTaskStatus.ABANDONED,
                    ts,
                    ts,
                    AgentTaskStatus.QUEUED,
                    *terminal_session_statuses,
                    "process_restart",
                    AgentTaskStatus.QUEUED,
                    AgentTaskStatus.RUNNING,
                ),
            )
            count = int(cur.rowcount if cur.rowcount is not None else 0)
            for index in range(0, len(session_keys), _SQLITE_VARIABLE_CHUNK_SIZE):
                chunk = session_keys[index : index + _SQLITE_VARIABLE_CHUNK_SIZE]
                placeholders = ", ".join("?" for _ in chunk)
                await conn.execute(
                f"""
                UPDATE sessions
                SET status = ?,
                    updated_at = ?,
                    ended_at = COALESCE(ended_at, ?),
                    runtime_ms = CASE
                        WHEN runtime_ms IS NOT NULL THEN runtime_ms
                        WHEN started_at IS NULL THEN NULL
                        WHEN ? >= started_at THEN ? - started_at
                        ELSE 0
                    END
                WHERE session_key IN ({placeholders})
                  AND status NOT IN (?, ?, ?, ?)
                  AND NOT EXISTS (
                      SELECT 1 FROM agent_tasks AS recoverable
                      WHERE recoverable.session_key = sessions.session_key
                        AND recoverable.status = ?
                        AND recoverable.terminal_reason = 'meta_control_restart_before_start'
                  )
                """,
                (
                    SessionStatus.FAILED,
                    ts,
                    ts,
                    ts,
                    ts,
                    *chunk,
                    *terminal_session_statuses,
                    AgentTaskStatus.ABANDONED,
                ),
            )
        return count

    async def claim_recoverable_meta_control_tasks(
        self,
        *,
        limit: int = 64,
    ) -> list[RecoverableMetaControlTask]:
        """Claim accepted control tasks proven not to have started before restart.

        Running tasks are deliberately excluded: provider side effects may have
        occurred before the crash, so replaying them automatically would be
        unsafe. A claimed queued task is returned with its original transcript
        row and task identity; another crash marks it recoverable again.
        """

        bounded_limit = max(1, min(int(limit), 256))
        recovered: list[RecoverableMetaControlTask] = []
        now_ms = _now_ms()
        terminal_session_statuses = (
            SessionStatus.DONE,
            SessionStatus.FAILED,
            SessionStatus.KILLED,
            SessionStatus.TIMEOUT,
        )
        async with self._write_transaction("claim_meta_control_recovery") as conn:
            async def quarantine_invalid(task_id: str) -> None:
                await conn.execute(
                    """
                    UPDATE agent_tasks
                    SET terminal_reason = ?, updated_at = ?,
                        error_class = 'MetaControlRecoveryInvalid',
                        error_message = 'Durable MetaSkill control recovery data is invalid.'
                    WHERE task_id = ? AND status = ?
                      AND terminal_reason = 'meta_control_restart_before_start'
                    """,
                    (
                        _META_CONTROL_RECOVERY_INVALID_REASON,
                        now_ms,
                        task_id,
                        AgentTaskStatus.ABANDONED,
                    ),
                )

            # Invalid rows must not permanently head-of-line block later valid
            # controls when callers use a small limit. Every selected row is
            # either claimed or quarantined before the next bounded read.
            while len(recovered) < bounded_limit:
                remaining = bounded_limit - len(recovered)
                async with conn.execute(
                    """
                    SELECT task.*
                    FROM agent_tasks AS task
                    JOIN meta_control_intents AS intent
                      ON intent.accepted_task_id = task.task_id
                    JOIN sessions AS owner
                      ON owner.session_key = task.session_key
                    WHERE task.status = ?
                      AND task.terminal_reason = 'meta_control_restart_before_start'
                      AND intent.status = 'accepted'
                      AND owner.status NOT IN (?, ?, ?, ?)
                    ORDER BY task.created_at ASC, task.task_id ASC
                    LIMIT ?
                    """,
                    (
                        AgentTaskStatus.ABANDONED,
                        *terminal_session_statuses,
                        remaining,
                    ),
                ) as cur:
                    task_rows = await cur.fetchall()
                if not task_rows:
                    break

                for raw_task in task_rows:
                    task = AgentTaskRecord(**_deserialize_row(dict(raw_task)))
                    details = task.details if isinstance(task.details, dict) else {}
                    metadata = details.get("metadata")
                    message_id = details.get("persisted_user_message_id")
                    if not isinstance(metadata, dict) or not isinstance(message_id, str):
                        await quarantine_invalid(task.task_id)
                        continue
                    control = metadata.get("meta_control")
                    if not isinstance(control, dict):
                        await quarantine_invalid(task.task_id)
                        continue
                    async with conn.execute(
                        """
                        SELECT * FROM transcript_entries
                        WHERE session_key = ? AND message_id = ? AND role = 'user'
                        """,
                        (task.session_key, message_id),
                    ) as entry_cur:
                        entry_row = await entry_cur.fetchone()
                    if entry_row is None:
                        await quarantine_invalid(task.task_id)
                        continue
                    entry = TranscriptEntry(**_deserialize_row(dict(entry_row)))
                    if (
                        not isinstance(entry.turn_context, dict)
                        or entry.turn_context.get("meta_control") != control
                    ):
                        await quarantine_invalid(task.task_id)
                        continue
                    async with conn.execute(
                        """
                        UPDATE agent_tasks
                        SET status = ?, updated_at = ?, finished_at = NULL,
                            terminal_reason = NULL, error_class = NULL, error_message = NULL
                        WHERE task_id = ? AND status = ?
                          AND terminal_reason = 'meta_control_restart_before_start'
                        """,
                        (
                            AgentTaskStatus.QUEUED,
                            now_ms,
                            task.task_id,
                            AgentTaskStatus.ABANDONED,
                        ),
                    ) as update_cur:
                        if int(update_cur.rowcount or 0) != 1:
                            continue
                    task.status = AgentTaskStatus.QUEUED
                    task.updated_at = now_ms
                    task.finished_at = None
                    task.terminal_reason = None
                    task.error_class = None
                    task.error_message = None
                    recovered.append(RecoverableMetaControlTask(task=task, entry=entry))

            recovered_keys = sorted({item.task.session_key for item in recovered})
            for session_key in recovered_keys:
                await conn.execute(
                    """
                    UPDATE sessions
                    SET status = ?, updated_at = ?, ended_at = NULL, runtime_ms = NULL
                    WHERE session_key = ?
                      AND status NOT IN (?, ?, ?, ?)
                    """,
                    (
                        SessionStatus.RUNNING,
                        now_ms,
                        session_key,
                        *terminal_session_statuses,
                    ),
                )
        return recovered

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
                turn_context,
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
                turn_context,
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

    @staticmethod
    async def _select_meta_control_intent(
        conn: Any,
        *,
        session_key: str,
        control_kind: str,
        correlation_id: str,
    ) -> MetaControlIntent | None:
        async with conn.execute(
            """
            SELECT * FROM meta_control_intents
            WHERE session_key = ? AND control_kind = ? AND correlation_id = ?
            """,
            (session_key, control_kind, correlation_id),
        ) as cur:
            row = await cur.fetchone()
        return MetaControlIntent(**_deserialize_row(dict(row))) if row is not None else None

    async def stage_meta_control_intent(
        self,
        *,
        session_key: str,
        control_kind: str,
        correlation_id: str,
        meta_skill_name: str,
        replay_run_id: str | None = None,
        replay_mode: str | None = None,
    ) -> tuple[MetaControlIntent, str]:
        """Durably stage one manual launch or committed replay authorization.

        Repeating the same coordinates is idempotent even after acceptance.
        Reusing their correlation identity for a different skill/run/mode is a
        hard conflict. Staged rows have a 30-day recovery window, far longer
        than the browser outbox, so long turns and restarts remain safe without
        allowing abandoned pre-send authorizations to grow forever.
        """

        session_key = canonicalize_session_key(session_key)
        control_kind = control_kind.strip()
        correlation_id = correlation_id.strip()
        meta_skill_name = meta_skill_name.strip()
        replay_run_id = replay_run_id.strip() if isinstance(replay_run_id, str) else None
        replay_mode = replay_mode.strip() if isinstance(replay_mode, str) else None
        if not session_key or not correlation_id or not meta_skill_name:
            raise ValueError("meta control session, correlation, and skill are required")
        if control_kind not in {"manual", "replay"}:
            raise ValueError("meta control kind must be manual or replay")
        if len(correlation_id) > 272:
            raise ValueError("meta control correlation exceeds 272 characters")
        if control_kind == "manual":
            if not correlation_id.startswith("request:"):
                raise ValueError("manual meta control requires a request correlation")
            if replay_run_id is not None or replay_mode is not None:
                raise ValueError("manual meta control cannot carry replay coordinates")
            session_key, request_id = normalize_meta_launch_coordinates(
                session_key,
                correlation_id.removeprefix("request:"),
            )
            correlation_id = f"request:{request_id}"
        elif (
            not correlation_id.startswith("nonce:")
            or replay_run_id is None
            or replay_mode not in {"failed-step", "partial-context"}
        ):
            raise ValueError("replay meta control requires nonce, run, and live mode")

        async with self._write_transaction("stage_meta_control_intent") as conn:
            return await self._stage_meta_control_intent_in_transaction(
                conn,
                session_key=session_key,
                control_kind=control_kind,
                correlation_id=correlation_id,
                meta_skill_name=meta_skill_name,
                replay_run_id=replay_run_id,
                replay_mode=replay_mode,
            )

    async def _stage_meta_control_intent_in_transaction(
        self,
        conn: Any,
        *,
        session_key: str,
        control_kind: str,
        correlation_id: str,
        meta_skill_name: str,
        replay_run_id: str | None,
        replay_mode: str | None,
    ) -> tuple[MetaControlIntent, str]:
        """Insert or replay a validated control on an existing write transaction."""

        now_ms = _now_ms()
        cutoff_ms = now_ms - _META_CONTROL_STAGED_RETENTION_MS
        await conn.execute(
            """
            DELETE FROM meta_control_intents
            WHERE intent_id IN (
                SELECT intent_id FROM meta_control_intents
                WHERE status = 'staged' AND created_at < ?
                ORDER BY created_at ASC, intent_id ASC
                LIMIT ?
            )
            """,
            (cutoff_ms, _META_CONTROL_STAGED_GC_BATCH),
        )
        if control_kind == "manual":
            request_id = correlation_id.removeprefix("request:")
            await conn.execute(
                """
                DELETE FROM meta_launch_discard_tombstones
                WHERE session_key = ? AND client_request_id = ? AND expires_at <= ?
                """,
                (session_key, request_id, now_ms),
            )
            async with conn.execute(
                """
                SELECT 1 FROM meta_launch_discard_tombstones
                WHERE session_key = ? AND client_request_id = ? AND expires_at > ?
                """,
                (session_key, request_id, now_ms),
            ) as cur:
                discarded = await cur.fetchone()
            if discarded is not None:
                raise MetaLaunchDraftDiscardedError(
                    "meta launch draft identity was explicitly discarded"
                )
        existing = await self._select_meta_control_intent(
            conn,
            session_key=session_key,
            control_kind=control_kind,
            correlation_id=correlation_id,
        )
        if existing is not None:
            if (
                existing.meta_skill_name != meta_skill_name
                or existing.replay_run_id != replay_run_id
                or existing.replay_mode != replay_mode
            ):
                raise MetaControlIntentConflictError(
                    "meta control identity was already used for another launch"
                )
            return existing, "replayed"

        if control_kind == "manual":
            await self._ensure_meta_launch_coordinate_capacity(
                conn,
                now_ms=now_ms,
                session_key=session_key,
                client_request_id=correlation_id.removeprefix("request:"),
            )

        intent = MetaControlIntent(
            session_key=session_key,
            control_kind=control_kind,
            correlation_id=correlation_id,
            meta_skill_name=meta_skill_name,
            replay_run_id=replay_run_id,
            replay_mode=replay_mode,
        )
        data = intent.model_dump()
        columns = list(data)
        await conn.execute(
            f"INSERT INTO meta_control_intents ({', '.join(columns)}) "
            f"VALUES ({', '.join('?' for _ in columns)})",
            [_serialize(data[column]) for column in columns],
        )
        return intent, "stamped"

    @_serialized_read
    async def get_meta_control_intent(
        self,
        *,
        session_key: str,
        control_kind: str,
        correlation_id: str,
    ) -> MetaControlIntent | None:
        """Return the exact durable control authorization, if one exists."""

        return await self._select_meta_control_intent(
            self.conn,
            session_key=canonicalize_session_key(session_key),
            control_kind=control_kind,
            correlation_id=correlation_id,
        )

    @staticmethod
    async def _select_meta_launch_draft(
        conn: Any,
        *,
        session_key: str,
        client_request_id: str,
    ) -> MetaLaunchDraft | None:
        async with conn.execute(
            """
            SELECT * FROM meta_launch_drafts
            WHERE session_key = ? AND client_request_id = ?
            """,
            (session_key, client_request_id),
        ) as cur:
            row = await cur.fetchone()
        return MetaLaunchDraft(**_deserialize_row(dict(row))) if row is not None else None

    async def _select_live_meta_launch_coordinates(
        self,
        conn: Any,
        *,
        now_ms: int,
        session_key: str | None = None,
        include_drafts: bool = True,
        include_tombstones: bool = True,
        include_staged: bool = True,
        include_accepted: bool = True,
        exclude_intent_id: str | None = None,
    ) -> set[tuple[str, str]]:
        """Return the bounded live launch identities represented across ledgers.

        One browser request may briefly exist as both a raw draft and a staged
        control. Capacity is therefore defined over exact coordinates, not row
        counts. Accepted controls contribute only the newest browser-outbox
        window per session; older accepted history is not a live resend source.
        """

        canonical_session = canonicalize_session_key(session_key) if session_key else ""
        coordinates: set[tuple[str, str]] = set()

        def append_coordinate(raw_session: object, raw_request: object) -> None:
            try:
                coordinate = normalize_meta_launch_coordinates(
                    raw_session,
                    raw_request,
                )
            except ValueError:
                # Older ledgers may contain identifiers that current ingress no
                # longer accepts. They cannot be replayed through the bounded RPC.
                return
            if canonical_session and coordinate[0] != canonical_session:
                return
            coordinates.add(coordinate)

        async def append_rows(sql: str, params: tuple[Any, ...]) -> None:
            async with conn.execute(sql, params) as cur:
                for row in await cur.fetchall():
                    append_coordinate(row[0], row[1])

        session_clause = " AND session_key = ?" if canonical_session else ""
        session_params: tuple[Any, ...] = (canonical_session,) if canonical_session else ()
        if include_drafts:
            await append_rows(
                "SELECT session_key, client_request_id FROM meta_launch_drafts "
                f"WHERE expires_at > ?{session_clause}",
                (now_ms, *session_params),
            )
        if include_tombstones:
            await append_rows(
                "SELECT session_key, client_request_id "
                "FROM meta_launch_discard_tombstones "
                f"WHERE expires_at > ?{session_clause}",
                (now_ms, *session_params),
            )
        if include_staged:
            exclude_clause = " AND intent_id <> ?" if exclude_intent_id else ""
            exclude_params: tuple[Any, ...] = (
                (exclude_intent_id,) if exclude_intent_id else ()
            )
            await append_rows(
                "SELECT session_key, substr(correlation_id, 9) "
                "FROM meta_control_intents "
                "WHERE control_kind = 'manual' AND status = 'staged' "
                "AND correlation_id LIKE 'request:%' AND created_at > ?"
                f"{session_clause}{exclude_clause}",
                (
                    now_ms - _META_CONTROL_STAGED_RETENTION_MS,
                    *session_params,
                    *exclude_params,
                ),
            )
        if include_accepted:
            exclude_clause = " AND intent_id <> ?" if exclude_intent_id else ""
            exclude_params = (exclude_intent_id,) if exclude_intent_id else ()
            accepted_sql = (
                "SELECT session_key, substr(correlation_id, 9) "
                "FROM meta_control_intents "
                "WHERE control_kind = 'manual' AND status = 'accepted' "
                "AND correlation_id LIKE 'request:%' AND updated_at > ?"
                f"{session_clause}{exclude_clause} "
                "ORDER BY session_key ASC, updated_at DESC, intent_id DESC"
            )
            accepted_params = (
                now_ms - _META_LAUNCH_DRAFT_RETENTION_MS,
                *session_params,
                *exclude_params,
            )
            if canonical_session:
                accepted_sql += " LIMIT ?"
                accepted_params = (
                    *accepted_params,
                    _META_LAUNCH_ACCEPTED_PER_SESSION_LIMIT,
                )
            async with conn.execute(accepted_sql, accepted_params) as cur:
                accepted_counts: dict[str, int] = {}
                for row in await cur.fetchall():
                    row_session = canonicalize_session_key(str(row[0]))
                    seen = accepted_counts.get(row_session, 0)
                    if seen >= _META_LAUNCH_ACCEPTED_PER_SESSION_LIMIT:
                        continue
                    accepted_counts[row_session] = seen + 1
                    append_coordinate(row[0], row[1])

        return coordinates

    async def _ensure_meta_launch_coordinate_capacity(
        self,
        conn: Any,
        *,
        now_ms: int,
        session_key: str,
        client_request_id: str,
    ) -> None:
        """Reserve one exact live coordinate without exceeding either bound."""

        coordinate = normalize_meta_launch_coordinates(session_key, client_request_id)
        live = await self._select_live_meta_launch_coordinates(conn, now_ms=now_ms)
        if coordinate in live:
            return
        if sum(1 for item in live if item[0] == coordinate[0]) >= (
            _META_LAUNCH_DISCARD_PER_SESSION_LIMIT
        ):
            raise MetaLaunchDraftCapacityError(
                "MetaSkill cancellation retention is full for this session"
            )
        if len(live) >= _META_LAUNCH_DISCARD_GLOBAL_LIMIT:
            raise MetaLaunchDraftCapacityError("MetaSkill cancellation retention is full")

    @_serialized_read
    async def is_meta_launch_discarded(
        self,
        *,
        session_key: str,
        client_request_id: str,
    ) -> bool:
        """Return whether a live terminal marker fences this request identity."""

        session_key, client_request_id = normalize_meta_launch_coordinates(
            session_key,
            client_request_id,
        )
        async with self.conn.execute(
            """
            SELECT 1 FROM meta_launch_discard_tombstones
            WHERE session_key = ? AND client_request_id = ? AND expires_at > ?
            """,
            (session_key, client_request_id, _now_ms()),
        ) as cur:
            return await cur.fetchone() is not None

    @staticmethod
    async def _purge_expired_meta_launch_drafts(
        conn: Any,
        *,
        now_ms: int,
        limit: int,
    ) -> int:
        """Delete bounded pages of expired raw prompts and cancellation markers."""

        bounded_limit = max(1, min(int(limit), _META_LAUNCH_DRAFT_GLOBAL_LIMIT))
        await conn.execute(
            """
            DELETE FROM meta_launch_discard_tombstones
            WHERE rowid IN (
                SELECT rowid
                FROM meta_launch_discard_tombstones
                WHERE expires_at <= ?
                ORDER BY expires_at ASC, created_at ASC
                LIMIT ?
            )
            """,
            (now_ms, bounded_limit),
        )
        async with conn.execute(
            """
            SELECT draft_id, session_key, client_request_id
            FROM meta_launch_drafts
            WHERE expires_at <= ?
            ORDER BY expires_at ASC, draft_id ASC
            LIMIT ?
            """,
            (now_ms, bounded_limit),
        ) as cur:
            expired = await cur.fetchall()
        if not expired:
            return 0

        # Revoke the one-shot authorization before deleting the only row that
        # correlates it to the expiring raw request.
        for row in expired:
            await conn.execute(
                """
                DELETE FROM meta_control_intents
                WHERE session_key = ? AND control_kind = 'manual'
                  AND correlation_id = ? AND status = 'staged'
                """,
                (str(row["session_key"]), f"request:{row['client_request_id']}"),
            )
        placeholders = ", ".join("?" for _ in expired)
        await conn.execute(
            f"DELETE FROM meta_launch_drafts WHERE draft_id IN ({placeholders})",
            [str(row["draft_id"]) for row in expired],
        )
        return len(expired)

    async def _tombstone_meta_launches_for_boundary(
        self,
        conn: Any,
        *,
        session_key: str,
        now_ms: int,
        intent_statuses: tuple[str, ...],
        exclude_intent_id: str | None = None,
        exclude_client_request_id: str | None = None,
    ) -> int:
        """Fence stale MetaSkill identities while erasing their raw content."""

        statuses = tuple(
            status for status in intent_statuses if status in {"staged", "accepted"}
        )
        if not statuses:
            return 0
        await self._purge_expired_meta_launch_drafts(
            conn,
            now_ms=now_ms,
            limit=_META_LAUNCH_DRAFT_GC_BATCH,
        )
        coordinates = await self._select_live_meta_launch_coordinates(
            conn,
            now_ms=now_ms,
            session_key=session_key,
            include_tombstones=False,
            include_staged="staged" in statuses,
            include_accepted="accepted" in statuses,
            exclude_intent_id=exclude_intent_id,
        )
        request_ids = {
            request_id
            for _coordinate_session, request_id in coordinates
            if request_id != exclude_client_request_id
        }

        for request_id in sorted(request_ids):
            await conn.execute(
                """
                INSERT INTO meta_launch_discard_tombstones (
                    session_key, client_request_id, created_at, expires_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(session_key, client_request_id) DO UPDATE SET
                    created_at = excluded.created_at,
                    expires_at = excluded.expires_at
                WHERE meta_launch_discard_tombstones.expires_at <= excluded.created_at
                """,
                (
                    session_key,
                    request_id,
                    now_ms,
                    now_ms + _META_LAUNCH_DRAFT_RETENTION_MS,
                ),
            )
        return len(request_ids)

    async def stage_meta_launch_draft(
        self,
        *,
        session_key: str,
        client_request_id: str,
        meta_skill_name: str,
        launch_text: str,
    ) -> tuple[MetaLaunchDraft, str]:
        """Retain one exact manual request until its hidden turn is accepted.

        The outbox is deliberately small and short-lived because ``launch_text``
        is user content.  Stable request identities are immutable, making
        retries safe after an RPC response loss or application restart.
        """

        session_key, client_request_id = normalize_meta_launch_coordinates(
            session_key,
            client_request_id,
        )
        meta_skill_name = meta_skill_name.strip()
        if (
            not meta_skill_name
            or len(meta_skill_name) > 256
            or any(character.isspace() for character in meta_skill_name)
        ):
            raise ValueError("meta launch draft skill is invalid")
        if not isinstance(launch_text, str) or not launch_text or len(launch_text) > 128_000:
            raise ValueError("meta launch draft content is invalid")
        prefix = f"/meta {meta_skill_name}"
        suffix = launch_text[len(prefix) :] if launch_text.startswith(prefix) else ""
        if launch_text != prefix:
            if not suffix.startswith(" --") or (len(suffix) > 3 and not suffix[3].isspace()):
                raise ValueError("meta launch draft does not match its skill")

        now_ms = _now_ms()
        async with self._write_transaction("stage_meta_launch_draft") as conn:
            await self._purge_expired_meta_launch_drafts(
                conn,
                now_ms=now_ms,
                limit=_META_LAUNCH_DRAFT_GC_BATCH,
            )
            # The bounded global GC page may not include this coordinate when
            # many markers expire together. Remove its own expired marker so a
            # legitimate reuse after the retention window is deterministic.
            await conn.execute(
                """
                DELETE FROM meta_launch_discard_tombstones
                WHERE session_key = ? AND client_request_id = ? AND expires_at <= ?
                """,
                (session_key, client_request_id, now_ms),
            )
            async with conn.execute(
                """
                SELECT 1
                FROM meta_launch_discard_tombstones
                WHERE session_key = ? AND client_request_id = ? AND expires_at > ?
                """,
                (session_key, client_request_id, now_ms),
            ) as cur:
                discarded = await cur.fetchone()
            if discarded is not None:
                raise MetaLaunchDraftDiscardedError(
                    "meta launch draft identity was explicitly discarded"
                )
            existing = await self._select_meta_launch_draft(
                conn,
                session_key=session_key,
                client_request_id=client_request_id,
            )
            if existing is not None:
                if (
                    existing.meta_skill_name != meta_skill_name
                    or existing.launch_text != launch_text
                ):
                    raise MetaLaunchDraftConflictError(
                        "meta launch draft identity was already used for another request"
                    )
                return existing, "replayed"

            async with conn.execute(
                "SELECT COUNT(*) FROM meta_launch_drafts WHERE session_key = ?",
                (session_key,),
            ) as cur:
                per_session_row = await cur.fetchone()
            per_session_count = int(per_session_row[0] if per_session_row else 0)
            if per_session_count >= _META_LAUNCH_DRAFT_PER_SESSION_LIMIT:
                raise MetaLaunchDraftCapacityError("MetaSkill draft outbox is full")
            async with conn.execute("SELECT COUNT(*) FROM meta_launch_drafts") as cur:
                global_row = await cur.fetchone()
            global_drafts = int(global_row[0] if global_row else 0)
            if global_drafts >= _META_LAUNCH_DRAFT_GLOBAL_LIMIT:
                raise MetaLaunchDraftCapacityError("MetaSkill draft outbox is full")
            await self._ensure_meta_launch_coordinate_capacity(
                conn,
                now_ms=now_ms,
                session_key=session_key,
                client_request_id=client_request_id,
            )

            draft = MetaLaunchDraft(
                session_key=session_key,
                client_request_id=client_request_id,
                meta_skill_name=meta_skill_name,
                launch_text=launch_text,
                created_at=now_ms,
                updated_at=now_ms,
                expires_at=now_ms + _META_LAUNCH_DRAFT_RETENTION_MS,
            )
            data = draft.model_dump()
            columns = list(data)
            await conn.execute(
                f"INSERT INTO meta_launch_drafts ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                [_serialize(data[column]) for column in columns],
            )
            return draft, "stamped"

    async def promote_meta_launch_draft(
        self,
        *,
        session_key: str,
        client_request_id: str,
        meta_skill_name: str,
        launch_text: str,
    ) -> tuple[MetaControlIntent, str]:
        """Atomically verify a live draft and stage its manual authorization.

        Readiness checks intentionally run outside SQLite. This compare-and-set
        closes the later boundary: if another tab discarded or expiry removed
        the raw request while readiness was running, no consumable control is
        created and the caller receives a retry-safe failure.
        """

        session_key, client_request_id = normalize_meta_launch_coordinates(
            session_key,
            client_request_id,
        )
        meta_skill_name = meta_skill_name.strip()
        if not meta_skill_name or not launch_text:
            raise ValueError("meta launch draft promotion coordinates are required")

        now_ms = _now_ms()
        async with self._write_transaction("promote_meta_launch_draft") as conn:
            await self._purge_expired_meta_launch_drafts(
                conn,
                now_ms=now_ms,
                limit=_META_LAUNCH_DRAFT_GC_BATCH,
            )
            async with conn.execute(
                """
                SELECT 1 FROM meta_launch_discard_tombstones
                WHERE session_key = ? AND client_request_id = ? AND expires_at > ?
                """,
                (session_key, client_request_id, now_ms),
            ) as cur:
                discarded = await cur.fetchone()
            if discarded is not None:
                raise MetaLaunchDraftDiscardedError(
                    "meta launch draft identity was explicitly discarded"
                )
            draft = await self._select_meta_launch_draft(
                conn,
                session_key=session_key,
                client_request_id=client_request_id,
            )
            if draft is None:
                raise MetaLaunchDraftUnavailableError(
                    "meta launch draft was discarded or expired"
                )
            if (
                draft.meta_skill_name != meta_skill_name
                or draft.launch_text != launch_text
            ):
                raise MetaLaunchDraftConflictError(
                    "meta launch draft identity was already used for another request"
                )
            return await self._stage_meta_control_intent_in_transaction(
                conn,
                session_key=session_key,
                control_kind="manual",
                correlation_id=f"request:{client_request_id}",
                meta_skill_name=meta_skill_name,
                replay_run_id=None,
                replay_mode=None,
            )

    async def list_meta_launch_drafts(
        self,
        *,
        session_key: str | None = None,
        agent_id: str | None = None,
        provisional_only: bool = False,
        limit: int = _META_LAUNCH_DRAFT_PER_SESSION_LIMIT,
    ) -> list[MetaLaunchDraft]:
        """List live drafts for one session or one agent without consuming them."""

        canonical_session = canonicalize_session_key(session_key) if session_key else ""
        normalized_agent = normalize_agent_id(agent_id) if agent_id else ""
        if not canonical_session and not normalized_agent:
            raise ValueError("meta launch draft session or agent is required")
        bounded_limit = max(1, min(int(limit), _META_LAUNCH_DRAFT_PER_SESSION_LIMIT))
        now_ms = _now_ms()
        async with self._write_transaction("list_meta_launch_drafts") as conn:
            await self._purge_expired_meta_launch_drafts(
                conn,
                now_ms=now_ms,
                limit=_META_LAUNCH_DRAFT_GC_BATCH,
            )
            if canonical_session:
                sql = (
                    "SELECT * FROM meta_launch_drafts "
                    "WHERE session_key = ? AND expires_at > ? "
                    "ORDER BY created_at ASC, draft_id ASC LIMIT ?"
                )
                params: tuple[Any, ...] = (canonical_session, now_ms, bounded_limit)
            else:
                session_prefix = f"agent:{normalized_agent}:"
                provisional_clause = (
                    "AND NOT EXISTS ("
                    "SELECT 1 FROM sessions "
                    "WHERE sessions.session_key = meta_launch_drafts.session_key"
                    ") "
                    if provisional_only
                    else ""
                )
                sql = (
                    "SELECT * FROM meta_launch_drafts "
                    "WHERE substr(session_key, 1, length(?)) = ? AND expires_at > ? "
                    f"{provisional_clause}"
                    "ORDER BY created_at ASC, draft_id ASC LIMIT ?"
                )
                params = (session_prefix, session_prefix, now_ms, bounded_limit)
            async with conn.execute(sql, params) as cur:
                rows = await cur.fetchall()
        drafts = [MetaLaunchDraft(**_deserialize_row(dict(row))) for row in rows]
        if normalized_agent:
            # Keep the parser authoritative if session-key formats expand; the
            # SQL prefix is only the bounded query accelerator.
            drafts = [
                draft
                for draft in drafts
                if parse_agent_id(draft.session_key) == normalized_agent
            ]
        return drafts

    async def discard_meta_launch_draft(
        self,
        *,
        session_key: str,
        client_request_id: str,
    ) -> bool:
        """Make an explicit user discard terminal for a bounded retention window."""

        try:
            session_key, client_request_id = normalize_meta_launch_coordinates(
                session_key,
                client_request_id,
            )
        except ValueError:
            return False
        now_ms = _now_ms()
        async with self._write_transaction("discard_meta_launch_draft") as conn:
            intent = await self._select_meta_control_intent(
                conn,
                session_key=session_key,
                control_kind="manual",
                correlation_id=f"request:{client_request_id}",
            )
            # Acceptance is the irreversible boundary: the task may already be
            # invoking a paid provider even if the browser lost the send
            # response. Never report that request as cancelled or let the UI
            # restore it as a newly sendable composer draft.
            if intent is not None and intent.status == "accepted":
                return False
            await self._purge_expired_meta_launch_drafts(
                conn,
                now_ms=now_ms,
                limit=_META_LAUNCH_DRAFT_GC_BATCH,
            )
            async with conn.execute(
                """
                SELECT 1 FROM meta_launch_discard_tombstones
                WHERE session_key = ? AND client_request_id = ? AND expires_at > ?
                """,
                (session_key, client_request_id, now_ms),
            ) as cur:
                existing_tombstone = await cur.fetchone()
            if existing_tombstone is None:
                await self._ensure_meta_launch_coordinate_capacity(
                    conn,
                    now_ms=now_ms,
                    session_key=session_key,
                    client_request_id=client_request_id,
                )
            # Keep only the request coordinates, never the raw launch text or
            # skill name. Repeated response-loss retries do not extend the
            # finite retention window established by the first discard.
            await conn.execute(
                """
                INSERT INTO meta_launch_discard_tombstones (
                    session_key, client_request_id, created_at, expires_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(session_key, client_request_id) DO UPDATE SET
                    created_at = excluded.created_at,
                    expires_at = excluded.expires_at
                WHERE meta_launch_discard_tombstones.expires_at <= excluded.created_at
                """,
                (
                    session_key,
                    client_request_id,
                    now_ms,
                    now_ms + _META_LAUNCH_DRAFT_RETENTION_MS,
                ),
            )
            await conn.execute(
                "DELETE FROM meta_launch_drafts WHERE session_key = ? AND client_request_id = ?",
                (session_key, client_request_id),
            )
            await conn.execute(
                """
                DELETE FROM meta_control_intents
                WHERE session_key = ? AND control_kind = 'manual'
                  AND correlation_id = ? AND status = 'staged'
                """,
                (session_key, f"request:{client_request_id}"),
            )
            # Idempotent cancellation: a retry after a committed discard
            # response loss must confirm the same terminal intent instead of
            # resurrecting a launch in the browser.
            return True

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
        meta_control_intent_id: str | None = None,
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
        if merge_into_task and meta_control_intent_id is not None:
            raise ValueError("a MetaSkill control turn cannot merge into another task")
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
                # Repair an outbox left by an older build that committed the
                # receipt before learning to consume drafts atomically.
                await conn.execute(
                    """
                    DELETE FROM meta_launch_drafts
                    WHERE session_key = ? AND client_request_id = ?
                    """,
                    (request_session_key, client_request_id),
                )
                return TurnAcceptanceResult(
                    receipt=receipt,
                    replayed=True,
                    fresh_user_session=fresh_user_session,
                    task_status=task_status,
                )

            if meta_control_intent_id is not None:
                async with conn.execute(
                    "SELECT * FROM meta_control_intents WHERE intent_id = ?",
                    (meta_control_intent_id,),
                ) as cur:
                    control_row = await cur.fetchone()
                if control_row is None:
                    raise MetaControlIntentConflictError(
                        "MetaSkill control authorization is missing"
                    )
                control = MetaControlIntent(**_deserialize_row(dict(control_row)))
                if control.session_key != request_session_key:
                    raise MetaControlIntentConflictError(
                        "MetaSkill control authorization belongs to another session"
                    )
                if control.status != "staged":
                    raise MetaControlIntentConflictError(
                        "MetaSkill control authorization was already accepted"
                    )
                embedded = (
                    entry.turn_context.get("meta_control")
                    if isinstance(entry.turn_context, dict)
                    else None
                )
                expected_embedded: dict[str, Any] = {
                    "version": 1,
                    "intent_id": control.intent_id,
                    "kind": control.control_kind,
                    "name": control.meta_skill_name,
                    "correlation_id": control.correlation_id,
                }
                if control.control_kind == "replay":
                    expected_embedded.update({
                        "run_id": control.replay_run_id,
                        "mode": control.replay_mode,
                    })
                if embedded != expected_embedded:
                    raise MetaControlIntentConflictError(
                        "MetaSkill control payload does not match its authorization"
                    )
                task_metadata = (task_record.details or {}).get("metadata")
                if (
                    not isinstance(task_metadata, dict)
                    or task_metadata.get("meta_control") != expected_embedded
                ):
                    raise MetaControlIntentConflictError(
                        "MetaSkill control task lost its authorized payload"
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
                    await self._tombstone_meta_launches_for_boundary(
                        conn,
                        session_key=session_node.session_key,
                        now_ms=_now_ms(),
                        intent_statuses=("staged", "accepted"),
                        exclude_intent_id=meta_control_intent_id,
                        exclude_client_request_id=(
                            client_request_id
                            if meta_control_intent_id is not None
                            and request_session_key == session_node.session_key
                            else None
                        ),
                    )
                    if meta_control_intent_id is None:
                        await conn.execute(
                            """
                            DELETE FROM meta_control_intents
                            WHERE session_key = ? AND status = 'staged'
                            """,
                            (session_node.session_key,),
                        )
                    else:
                        # The currently accepted hidden control belongs to this
                        # atomic reset turn. Preserve only that validated row;
                        # every other staged authorization belongs to the old
                        # session identity and must be invalidated.
                        await conn.execute(
                            """
                            DELETE FROM meta_control_intents
                            WHERE session_key = ? AND status = 'staged'
                              AND intent_id <> ?
                            """,
                            (session_node.session_key, meta_control_intent_id),
                        )
                    # A reset discards every unaccepted request owned by the old
                    # session identity. If this transaction is itself accepting
                    # one of them, rollback restores it on any later failure.
                    await conn.execute(
                        "DELETE FROM meta_launch_drafts WHERE session_key = ?",
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
            await conn.execute(
                """
                DELETE FROM meta_launch_drafts
                WHERE session_key = ? AND client_request_id = ?
                """,
                (request_session_key, client_request_id),
            )
            if meta_control_intent_id is not None:
                async with conn.execute(
                    """
                    UPDATE meta_control_intents
                    SET status = 'accepted', accepted_source_scope = ?,
                        accepted_request_session_key = ?, accepted_client_request_id = ?,
                        accepted_request_fingerprint = ?, accepted_message_id = ?,
                        accepted_task_id = ?, updated_at = ?
                    WHERE intent_id = ? AND status = 'staged'
                    """,
                    (
                        source_scope,
                        request_session_key,
                        client_request_id,
                        request_fingerprint,
                        entry.message_id,
                        task_record.task_id,
                        updated_at,
                        meta_control_intent_id,
                    ),
                ) as cur:
                    if int(cur.rowcount or 0) != 1:
                        raise MetaControlIntentConflictError(
                            "MetaSkill control authorization changed during acceptance"
                        )
            acceptance_result = TurnAcceptanceResult(
                receipt=receipt,
                replayed=False,
                fresh_user_session=fresh_user_session,
                task_status=task_record.status,
                reset_archive_snapshot=reset_archive_snapshot,
            )
        if reset_from_session_id is not None:
            _clear_pending_meta_launch_boundary(
                entry.session_key,
                preserve_client_request_id=client_request_id,
                preserve_message=entry.content,
            )
        return acceptance_result

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
                turn_context,
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
                turn_context,
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

    async def update_transcript_turn_context(
        self,
        session_key: str,
        message_id: str,
        turn_context: dict[str, Any],
    ) -> bool:
        """Replace one message's additive causal identity snapshot.

        The row can cross into the compacted archive while a queued turn waits,
        so update both canonical transcript tables in one transaction.
        """

        encoded = _serialize(turn_context)
        changed = 0
        async with self._write_transaction("update_transcript_turn_context") as conn:
            for table in ("transcript_entries", "compacted_transcript_entries"):
                async with conn.execute(
                    f"UPDATE {table} SET turn_context = ? "
                    "WHERE session_key = ? AND message_id = ?",
                    (encoded, session_key, message_id),
                ) as cur:
                    changed += cur.rowcount or 0
        return changed > 0

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
                turn_context,
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
