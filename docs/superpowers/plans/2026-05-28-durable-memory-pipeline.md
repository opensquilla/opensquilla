# Durable Memory Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make WebUI chat and destructive compaction safe when memory distillation, provider output, or JSON parsing fails, by adding deterministic checkpoint receipts, a canonical ledger, and a repair loop around the existing memory flush pipeline.

**Architecture:** Reuse the current `opensquilla.memory.flush.MemoryFlushPlan` and `SessionFlushService`; do not create a parallel flush planner. Add a durable checkpoint layer as the safety floor, a SQLite-backed memory receipt ledger as the source of truth, checkpoint-aware compaction gates, and ledger-derived repair work for raw fallback and failed semantic flushes. Normal WebUI chat must remain sendable and must not wait on semantic distillation or repair.

**Tech Stack:** Python, SQLModel/SQLite session storage, existing OpenSquilla memory tools, pytest, gateway RPC tests, WebUI chat smoke tests.

---

## Current Repo Facts To Preserve

- `src/opensquilla/memory/flush.py` already defines `MemoryFlushPlan`, `SILENT_REPLY_TOKEN`, daily archive path selection, prompt construction, thresholds, and transcript excerpt audit fields. This plan hardens and reuses it.
- `MemoryFlushPlan.relative_path` may be `memory/YYYY-MM-DD.md` or a rotated `memory/YYYY-MM-DD-partNNN.md` when `flush_archive_max_bytes` is exceeded. Tool guards must exact-match the active plan path, not hard-code only the base daily filename.
- `src/opensquilla/gateway/rpc_chat.py` intentionally keeps WebChat sendable even with oversized history; context shaping belongs downstream. Do not add a blocking memory-distill gate to `chat.send`.
- `src/opensquilla/session/compaction_lifecycle.py` currently treats only strong LLM flush receipts as destructive-safe. This plan adds checkpoint receipts as an independent durable safety receipt.
- `memory/.raw_fallbacks/*.md` is already writeable through `memory_save`, bypasses `max_files`, and is excluded from inline indexing. Keep that behavior.

## File Structure

- Create `src/opensquilla/memory/checkpoint.py`
  - Owns checkpoint event schema, JSONL serialization, hash/idempotency helpers, atomic append, and path normalization under `memory/.checkpoints/`.
- Create `tests/test_memory_checkpoint.py`
  - Unit tests for checkpoint schema, redaction/truncation markers, stable hashes, path safety, and idempotent append.
- Modify `src/opensquilla/session/models.py`
  - Add `MemoryDurableReceipt` SQLModel and status enums/constants used by storage and health code.
- Modify `src/opensquilla/session/storage.py`
  - Add table DDL, migrations, CRUD, idempotent upsert, and reconciliation queries for memory durable receipts.
- Create `tests/test_session/test_memory_durable_receipts.py`
  - Storage tests for unique idempotency keys, status transitions, queue listing, and orphan detection.
- Modify `src/opensquilla/session/compaction_lifecycle.py`
  - Add checkpoint-aware safety helpers while keeping existing flush receipt behavior.
- Modify `tests/test_session/test_compaction_lifecycle.py`
  - Tests for checkpoint-safe, checkpoint-missing, orphaned, and strict/block behavior.
- Modify `src/opensquilla/engine/runtime.py`, `src/opensquilla/engine/agent.py`, and `src/opensquilla/gateway/context_overflow.py`
  - Wire checkpoint creation before destructive compaction paths without blocking normal WebUI chat on distill/repair.
- Modify `src/opensquilla/gateway/rpc_sessions.py`
  - Apply checkpoint-aware safety to reset/truncate/manual compact paths.
- Modify `src/opensquilla/memory/session_flush.py`
  - Record ledger receipts for flush/raw fallback outcomes, lower success-archive noise, and mark distill/repair state instead of treating JSON parse failure as safety failure.
- Modify `src/opensquilla/tools/builtin/memory_tools.py`
  - Add `.checkpoints` exclusion parallel to `.raw_fallbacks`; keep checkpoints unindexed and not user-searchable.
- Modify `src/opensquilla/gateway/memory_repair_service.py`
  - Rebase repair queue on ledger rows; keep legacy raw fallback listing as an input source.
- Modify `src/opensquilla/gateway/rpc_memory.py` and `src/opensquilla/gateway/rpc_system.py`
  - Expose safety vs semantic-memory health from ledger, without showing checkpoint internals to ordinary chat users.
- Create or update tests under `tests/test_gateway/`, `tests/test_engine/`, and `tests/test_memory_repair_service.py`
  - Cover WebUI chat sendability, automatic compaction, reset/truncate gates, repair backlog, and search-index exclusion.

---

### Task 1: Define Checkpoint Event Schema

**Files:**
- Create: `src/opensquilla/memory/checkpoint.py`
- Test: `tests/test_memory_checkpoint.py`

- [ ] **Step 1: Write failing schema and hash tests**

```python
from pathlib import Path

from opensquilla.memory.checkpoint import (
    CheckpointEvent,
    checkpoint_event_hash,
    checkpoint_relative_path,
)


def test_checkpoint_event_serializes_required_fields() -> None:
    event = CheckpointEvent(
        schema_version=1,
        event_id="evt-1",
        session_key="agent:main:webchat:abc",
        session_id="session-1",
        turn_id="turn-1",
        sequence=1,
        timestamp_ms=123,
        role="tool_result",
        content_type="json",
        content='{"ok": true}',
        summary="tool succeeded",
        tool_name="memory_save",
        tool_call_id="call-1",
        status="ok",
        token_estimate=3,
        source="tool_runtime",
        attachments=[],
        content_hash="",
    )

    payload = event.to_json_dict()

    assert payload["schema_version"] == 1
    assert payload["session_key"] == "agent:main:webchat:abc"
    assert payload["role"] == "tool_result"
    assert payload["tool_name"] == "memory_save"
    assert payload["status"] == "ok"


def test_checkpoint_hash_is_stable_for_normalized_content() -> None:
    first = checkpoint_event_hash(" user message\n")
    second = checkpoint_event_hash("user message")

    assert first == second
    assert len(first) == 64


def test_checkpoint_relative_path_is_sidecar_only() -> None:
    path = checkpoint_relative_path(
        session_key="agent:main:webchat:abc",
        turn_id="turn-1",
    )

    assert path == Path("memory/.checkpoints/agent-main-webchat-abc/turn-1.jsonl")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
TMPDIR=/dev/shm .venv/bin/pytest tests/test_memory_checkpoint.py -q
```

Expected: FAIL because `opensquilla.memory.checkpoint` does not exist.

- [ ] **Step 3: Implement checkpoint schema helpers**

Create `src/opensquilla/memory/checkpoint.py` with:

```python
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

CheckpointRole = Literal[
    "user",
    "assistant",
    "tool_call",
    "tool_result",
    "system_notice",
    "error",
]
CheckpointContentType = Literal["text", "json", "binary_ref", "redacted"]
CheckpointStatus = Literal["ok", "error", "truncated", "redacted"]


@dataclass(frozen=True)
class CheckpointEvent:
    schema_version: int
    event_id: str
    session_key: str
    session_id: str
    turn_id: str
    sequence: int
    timestamp_ms: int
    role: CheckpointRole
    content_type: CheckpointContentType
    content: str
    summary: str | None
    tool_name: str | None
    tool_call_id: str | None
    status: CheckpointStatus
    token_estimate: int
    source: str
    attachments: list[dict]
    content_hash: str

    def to_json_dict(self) -> dict:
        payload = asdict(self)
        if not payload["content_hash"]:
            payload["content_hash"] = checkpoint_event_hash(self.content)
        return payload


def checkpoint_event_hash(content: str) -> str:
    normalized = str(content or "").strip().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def _safe_path_component(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return safe.strip("-") or "unknown"


def checkpoint_relative_path(*, session_key: str, turn_id: str) -> Path:
    return (
        Path("memory")
        / ".checkpoints"
        / _safe_path_component(session_key)
        / f"{_safe_path_component(turn_id)}.jsonl"
    )


def serialize_checkpoint_event(event: CheckpointEvent) -> str:
    return json.dumps(event.to_json_dict(), ensure_ascii=False, sort_keys=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
TMPDIR=/dev/shm .venv/bin/pytest tests/test_memory_checkpoint.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/opensquilla/memory/checkpoint.py tests/test_memory_checkpoint.py
git commit -m "Add deterministic memory checkpoint event schema"
```

---

### Task 2: Add Atomic Checkpoint Writer

**Files:**
- Modify: `src/opensquilla/memory/checkpoint.py`
- Test: `tests/test_memory_checkpoint.py`

- [ ] **Step 1: Write failing writer tests**

Append:

```python
from opensquilla.memory.checkpoint import append_checkpoint_events


async def test_append_checkpoint_events_writes_jsonl_once(tmp_path):
    event = CheckpointEvent(
        schema_version=1,
        event_id="evt-1",
        session_key="agent:main:webchat:abc",
        session_id="session-1",
        turn_id="turn-1",
        sequence=1,
        timestamp_ms=123,
        role="user",
        content_type="text",
        content="hello",
        summary=None,
        tool_name=None,
        tool_call_id=None,
        status="ok",
        token_estimate=1,
        source="turn_runner",
        attachments=[],
        content_hash="",
    )

    result = append_checkpoint_events(tmp_path, [event])
    second = append_checkpoint_events(tmp_path, [event])

    assert result.relative_path == "memory/.checkpoints/agent-main-webchat-abc/turn-1.jsonl"
    assert result.event_count == 1
    assert result.content_hash == second.content_hash
    lines = (tmp_path / result.relative_path).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
TMPDIR=/dev/shm .venv/bin/pytest tests/test_memory_checkpoint.py::test_append_checkpoint_events_writes_jsonl_once -q
```

Expected: FAIL because `append_checkpoint_events` is missing.

- [ ] **Step 3: Implement idempotent append**

Add:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class CheckpointWriteResult:
    relative_path: str
    event_count: int
    content_hash: str


def append_checkpoint_events(workspace: Path, events: list[CheckpointEvent]) -> CheckpointWriteResult:
    if not events:
        raise ValueError("checkpoint events are required")
    first = events[0]
    rel = checkpoint_relative_path(session_key=first.session_key, turn_id=first.turn_id)
    abs_path = workspace / rel
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [serialize_checkpoint_event(event) for event in events]
    body = "\n".join(lines) + "\n"
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    if abs_path.exists():
        existing = abs_path.read_text(encoding="utf-8")
        if hashlib.sha256(existing.encode("utf-8")).hexdigest() == digest:
            return CheckpointWriteResult(rel.as_posix(), len(events), digest)
    tmp_path = abs_path.with_suffix(abs_path.suffix + ".tmp")
    tmp_path.write_text(body, encoding="utf-8")
    tmp_path.replace(abs_path)
    return CheckpointWriteResult(rel.as_posix(), len(events), digest)
```

- [ ] **Step 4: Run checkpoint tests**

Run:

```bash
TMPDIR=/dev/shm .venv/bin/pytest tests/test_memory_checkpoint.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/opensquilla/memory/checkpoint.py tests/test_memory_checkpoint.py
git commit -m "Persist idempotent memory checkpoints"
```

---

### Task 3: Exclude Checkpoints From Memory Search

**Files:**
- Modify: `src/opensquilla/tools/builtin/memory_tools.py`
- Modify: `tests/test_memory_search_defaults.py`

- [ ] **Step 1: Write failing search exclusion test**

Add a checkpoint result beside the existing hidden/raw fallback exclusion coverage:

```python
MemorySearchResult(
    chunk_id="checkpoint",
    path="memory/.checkpoints/agent-main-webchat-abc/turn-1.jsonl",
    source=MemorySource.memory,
    start_line=1,
    end_line=1,
    snippet="checkpoint",
    score=0.97,
    text="checkpoint",
),
```

Then assert:

```python
assert ".checkpoints" not in output
```

- [ ] **Step 2: Run focused test to verify it fails**

Run:

```bash
TMPDIR=/dev/shm .venv/bin/pytest tests/test_memory_search_defaults.py -k "filters_hidden_or_raw" -q
```

Expected: FAIL until checkpoint paths are filtered.

- [ ] **Step 3: Add checkpoint sidecar predicate**

In `memory_tools.py`, add a helper parallel to `_is_raw_fallback_save_path`:

```python
def _is_checkpoint_sidecar_path(path: str) -> bool:
    rel = Path(path)
    return (
        not rel.is_absolute()
        and not any(part in {"", ".", ".."} for part in rel.parts)
        and len(rel.parts) >= 4
        and rel.parts[:2] == ("memory", ".checkpoints")
        and rel.suffix == ".jsonl"
    )
```

Use it in the search-result filtering branch that already hides dot-prefixed memory paths and raw fallback paths.

- [ ] **Step 4: Run memory search tests**

Run:

```bash
TMPDIR=/dev/shm .venv/bin/pytest tests/test_memory_search_defaults.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/opensquilla/tools/builtin/memory_tools.py tests/test_memory_search_defaults.py
git commit -m "Keep memory checkpoints out of recall"
```

---

### Task 4: Add Durable Receipt Model And Storage

**Files:**
- Modify: `src/opensquilla/session/models.py`
- Modify: `src/opensquilla/session/storage.py`
- Test: `tests/test_session/test_memory_durable_receipts.py`

- [ ] **Step 1: Write failing storage tests**

Create `tests/test_session/test_memory_durable_receipts.py`:

```python
from opensquilla.session.models import MemoryDurableReceipt
from opensquilla.session.storage import SessionStorage


async def test_memory_durable_receipt_upsert_is_idempotent(tmp_path):
    storage = await SessionStorage.open(tmp_path / "sessions.db")
    receipt = MemoryDurableReceipt(
        receipt_id="r1",
        session_key="agent:main:webchat:abc",
        session_id="session-1",
        turn_id="turn-1",
        scope="checkpoint",
        source_path="memory/.checkpoints/agent-main-webchat-abc/turn-1.jsonl",
        target_path=None,
        content_hash="h1",
        idempotency_key="checkpoint:agent:main:webchat:abc:turn-1:h1",
        status="checkpoint_saved",
        reason=None,
        attempt_count=0,
        next_retry_at_ms=None,
    )

    await storage.upsert_memory_durable_receipt(receipt)
    await storage.upsert_memory_durable_receipt(receipt)

    rows = await storage.list_memory_durable_receipts(session_key="agent:main:webchat:abc")
    assert len(rows) == 1
    assert rows[0].status == "checkpoint_saved"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
TMPDIR=/dev/shm .venv/bin/pytest tests/test_session/test_memory_durable_receipts.py -q
```

Expected: FAIL because model/storage methods are missing.

- [ ] **Step 3: Add SQLModel**

In `models.py`, add:

```python
class MemoryDurableReceipt(SQLModel, table=True):
    __tablename__ = "memory_durable_receipts"

    receipt_id: str = Field(default_factory=_new_uuid, primary_key=True)
    session_key: str = Field(index=True, max_length=512)
    session_id: str = Field(index=True)
    turn_id: str | None = Field(default=None, index=True)
    scope: str = Field(index=True)
    source_path: str | None = None
    target_path: str | None = None
    content_hash: str | None = None
    idempotency_key: str = Field(index=True, unique=True)
    status: str = Field(index=True)
    reason: str | None = None
    attempt_count: int = 0
    next_retry_at_ms: int | None = None
    created_at: int = Field(default_factory=_now_ms)
    updated_at: int = Field(default_factory=_now_ms)
    schema_version: int = 1
```

- [ ] **Step 4: Add storage DDL and CRUD**

In `storage.py`, add this DDL, create the unique index on `idempotency_key`, and call both statements from the existing storage initialization path:

```python
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
```

Add these storage methods:

```python
async def upsert_memory_durable_receipt(
    self,
    receipt: MemoryDurableReceipt,
) -> MemoryDurableReceipt:
    receipt.session_key = canonicalize_session_key(receipt.session_key)
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
    status: str | None = None,
    idempotency_key: str | None = None,
    limit: int = 100,
) -> list[MemoryDurableReceipt]:
    clauses: list[str] = []
    params: list[Any] = []
    if session_key is not None:
        clauses.append("session_key = ?")
        params.append(canonicalize_session_key(session_key))
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
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
        raise ValueError(f"Unknown memory durable receipt fields: {', '.join(unknown)}")
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
```

The upsert must preserve one row per `idempotency_key` and update `status`, `reason`, `attempt_count`, `next_retry_at_ms`, and `updated_at`.

- [ ] **Step 5: Run storage tests**

Run:

```bash
TMPDIR=/dev/shm .venv/bin/pytest tests/test_session/test_memory_durable_receipts.py tests/test_session/test_agent_task_storage.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/opensquilla/session/models.py src/opensquilla/session/storage.py tests/test_session/test_memory_durable_receipts.py
git commit -m "Add durable memory receipt ledger"
```

---

### Task 5: Record Checkpoint Receipts

**Files:**
- Modify: `src/opensquilla/memory/checkpoint.py`
- Modify: `src/opensquilla/engine/runtime.py`
- Modify: `src/opensquilla/engine/agent.py`
- Modify: `src/opensquilla/gateway/context_overflow.py`
- Test: `tests/test_engine/test_preflight_compaction.py`
- Test: `tests/test_gateway/test_context_overflow.py`

- [ ] **Step 1: Write failing preflight checkpoint test**

Add a preflight test that uses a fake storage with `upsert_memory_durable_receipt` and asserts checkpoint happens before compact:

```python
async def test_preflight_checkpoint_runs_before_compact(tmp_path) -> None:
    context_window = 1000
    entries = [_make_entry("early durable fact " + ("a" * 4000))]
    calls: list[str] = []
    mock_sm = MagicMock()
    mock_sm.get_transcript = AsyncMock(return_value=entries)
    mock_sm.compact = AsyncMock(side_effect=lambda *args, **kwargs: calls.append("compact") or "summary")
    mock_sm.workspace_dir = tmp_path
    mock_sm.record_memory_checkpoint = AsyncMock(side_effect=lambda *args, **kwargs: calls.append("checkpoint"))

    runner = TurnRunner(provider_selector=MagicMock(), session_manager=mock_sm)

    with patch("opensquilla.session.tokenizer.estimate_tokens", return_value=1000):
        await runner._maybe_preflight_compact("agent:ops:long-session", context_window)

    assert calls[0] == "checkpoint"
    assert "compact" in calls
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
TMPDIR=/dev/shm .venv/bin/pytest tests/test_engine/test_preflight_compaction.py::test_preflight_checkpoint_runs_before_compact -q
```

Expected: FAIL because no checkpoint hook is wired.

- [ ] **Step 3: Add session-manager checkpoint method**

Implement a method on the session manager/storage boundary that:

1. Converts transcript entries to `CheckpointEvent` rows.
2. Calls `append_checkpoint_events(workspace, events)`.
3. Upserts a `MemoryDurableReceipt` with `scope="checkpoint"` and `status="checkpoint_saved"`.
4. On write failure, upserts `status="checkpoint_failed"` and re-raises for destructive paths.

- [ ] **Step 4: Wire preflight compaction checkpoint**

In runtime/agent preflight compaction paths, call checkpoint before compacting history. Do not wait on semantic flush or repair. Keep existing `SessionFlushService.execute()` as curated flush/distill work after the checkpoint safety floor is satisfied.

- [ ] **Step 5: Run preflight and context overflow tests**

Run:

```bash
TMPDIR=/dev/shm .venv/bin/pytest tests/test_engine/test_preflight_compaction.py tests/test_gateway/test_context_overflow.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/opensquilla/memory/checkpoint.py src/opensquilla/engine/runtime.py src/opensquilla/engine/agent.py src/opensquilla/gateway/context_overflow.py tests/test_engine/test_preflight_compaction.py tests/test_gateway/test_context_overflow.py
git commit -m "Checkpoint session history before compaction"
```

---

### Task 6: Make Compaction Safety Checkpoint-Aware

**Files:**
- Modify: `src/opensquilla/session/compaction_lifecycle.py`
- Modify: `src/opensquilla/gateway/rpc_sessions.py`
- Test: `tests/test_session/test_compaction_lifecycle.py`
- Test: `tests/test_gateway/test_rpc_sessions.py`

- [ ] **Step 1: Write failing safety tests**

Add:

```python
def test_checkpoint_receipt_allows_destructive_compaction() -> None:
    receipt = {
        "scope": "checkpoint",
        "status": "checkpoint_saved",
        "source_path": "memory/.checkpoints/agent-main-webchat-abc/turn-1.jsonl",
        "content_hash": "h1",
    }

    assert durable_receipt_allows_destructive_compaction(receipt) is True


def test_orphaned_checkpoint_receipt_is_not_destructive_safe() -> None:
    receipt = {"scope": "checkpoint", "status": "receipt_orphaned"}

    assert durable_receipt_allows_destructive_compaction(receipt) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
TMPDIR=/dev/shm .venv/bin/pytest tests/test_session/test_compaction_lifecycle.py -k "checkpoint_receipt" -q
```

Expected: FAIL because helper is missing.

- [ ] **Step 3: Add durable receipt helper**

In `compaction_lifecycle.py`, add:

```python
def durable_receipt_allows_destructive_compaction(receipt: Any) -> bool:
    scope = str(_receipt_value(receipt, "scope", "") or "")
    status = str(_receipt_value(receipt, "status", "") or "")
    source_path = str(_receipt_value(receipt, "source_path", "") or "")
    content_hash = str(_receipt_value(receipt, "content_hash", "") or "")
    if scope == "checkpoint":
        return status == "checkpoint_saved" and bool(source_path) and bool(content_hash)
    if scope == "flush":
        return status == "flush_appended" and bool(_receipt_value(receipt, "target_path", ""))
    return flush_receipt_allows_destructive_compaction(receipt)
```

- [ ] **Step 4: Update reset/truncate/manual compact gates**

In `rpc_sessions.py`, use durable checkpoint receipt when available before rejecting reset/truncate/manual compaction. Preserve existing strict behavior when no checkpoint receipt covers the messages being removed.

- [ ] **Step 5: Run compaction and RPC tests**

Run:

```bash
TMPDIR=/dev/shm .venv/bin/pytest tests/test_session/test_compaction_lifecycle.py tests/test_gateway/test_rpc_sessions.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/opensquilla/session/compaction_lifecycle.py src/opensquilla/gateway/rpc_sessions.py tests/test_session/test_compaction_lifecycle.py tests/test_gateway/test_rpc_sessions.py
git commit -m "Allow durable checkpoints to satisfy compaction safety"
```

---

### Task 7: Record Flush And Raw Fallback Receipts In Ledger

**Files:**
- Modify: `src/opensquilla/memory/session_flush.py`
- Test: `tests/test_memory_flush.py`
- Test: `tests/test_session/test_memory_durable_receipts.py`

- [ ] **Step 1: Write failing ledger tests**

Add a test that invalid JSON returns a raw fallback receipt and also writes a `distill_failed` or `repair_pending` ledger row, while archive success is not treated as a safety failure when checkpoint exists.

```python
async def test_invalid_json_records_repair_pending_receipt(tmp_path):
    ledger = _FakeMemoryLedger()
    service = _make_flush_service(tmp_path, ledger=ledger, llm_output="{not json")

    receipt = await service.execute([_msg("user", "remember x")], "agent:main:webchat:abc")

    assert receipt.result_status == "parse_failed_archived"
    assert any(row.status == "repair_pending" for row in ledger.rows)
```

- [ ] **Step 2: Run focused test to verify it fails**

Run:

```bash
TMPDIR=/dev/shm .venv/bin/pytest tests/test_memory_flush.py -k "repair_pending_receipt" -q
```

Expected: FAIL because flush service does not write durable repair receipts.

- [ ] **Step 3: Inject optional ledger writer**

Extend `SessionFlushService.__init__` with an optional `receipt_writer` callable. Keep default `None` so existing tests and CLI call sites do not break. Use it in `_record_flush_done()` and `_raw_dump_fallback()`.

- [ ] **Step 4: Map statuses**

Use these mappings:

- `mode="llm"` and destructive-safe receipt -> `scope="flush"`, `status="flush_appended"`
- `result_status="parse_failed_archived"` -> `scope="repair"`, `status="repair_pending"`, `reason="parse_failed_archived"`
- `result_status="provider_failed_archived"` -> `scope="repair"`, `status="repair_pending"`, `reason="provider_failed_archived"`
- `result_status="archive_failed"` -> `scope="checkpoint"`, `status="checkpoint_failed"` only if no checkpoint exists; otherwise `scope="repair"`, `status="repair_failed"`

- [ ] **Step 5: Reduce noisy log severity**

Change successful raw fallback archive logging from warning to info. Keep `session_flush.raw_fallback_save_failed` as error only when `memory_save` actually fails.

- [ ] **Step 6: Run memory flush tests**

Run:

```bash
TMPDIR=/dev/shm .venv/bin/pytest tests/test_memory_flush.py tests/test_cli/test_memory_flush_cmd.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/opensquilla/memory/session_flush.py tests/test_memory_flush.py tests/test_cli/test_memory_flush_cmd.py
git commit -m "Record degraded memory flushes as repair work"
```

---

### Task 8: Harden Constrained Flush Guard

**Files:**
- Modify: `src/opensquilla/memory/session_flush.py`
- Modify: `src/opensquilla/memory/flush.py`
- Test: `tests/test_memory_flush.py`

- [ ] **Step 1: Write failing exact-path guard tests**

Add tests:

```python
async def test_flush_runner_rejects_wrong_memory_path(tmp_path):
    plan = resolve_flush_plan(workspace_dir=tmp_path)
    result = await _call_flush_tool(plan, path="memory/other.md", mode="append")
    assert result.is_error
    assert "only append to" in result.content


async def test_flush_runner_allows_plan_part_path(tmp_path):
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "2026-05-28.md").write_text("x" * 900_000, encoding="utf-8")
    plan = resolve_flush_plan(workspace_dir=tmp_path, archive_max_bytes=800_000)
    assert "-part" in plan.relative_path
    result = await _call_flush_tool(plan, path=plan.relative_path, mode="append")
    assert not result.is_error
```

- [ ] **Step 2: Run focused tests**

Run:

```bash
TMPDIR=/dev/shm .venv/bin/pytest tests/test_memory_flush.py -k "flush_runner_rejects_wrong_memory_path or flush_runner_allows_plan_part_path" -q
```

Expected: FAIL until the guard exact-matches `MemoryFlushPlan.relative_path`.

- [ ] **Step 3: Implement exact-path append-only guard**

In the flush tool handler, enforce:

- `arguments["path"] == plan.relative_path`
- `arguments["mode"] == "append"`
- path does not start with `memory/.raw_fallbacks/`
- path does not start with `memory/.checkpoints/`
- path is not `MEMORY.md`, `AGENTS.md`, `USER.md`, `SOUL.md`, or `TOOLS.md`

- [ ] **Step 4: Run flush tests**

Run:

```bash
TMPDIR=/dev/shm .venv/bin/pytest tests/test_memory_flush.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/opensquilla/memory/session_flush.py src/opensquilla/memory/flush.py tests/test_memory_flush.py
git commit -m "Constrain memory flush writes to the active plan path"
```

---

### Task 9: Implement Ledger-Derived Repair Queue

**Files:**
- Modify: `src/opensquilla/gateway/memory_repair_service.py`
- Modify: `src/opensquilla/gateway/rpc_memory.py`
- Test: `tests/test_memory_repair_service.py`
- Test: `tests/test_gateway/test_rpc_product_cli_gaps.py`

- [ ] **Step 1: Write failing repair queue test**

Add:

```python
async def test_repair_service_lists_ledger_pending_items(tmp_path):
    storage = await SessionStorage.open(tmp_path / "sessions.db")
    await storage.upsert_memory_durable_receipt(
        MemoryDurableReceipt(
            receipt_id="r1",
            session_key="agent:main:webchat:abc",
            session_id="session-1",
            turn_id="turn-1",
            scope="repair",
            source_path="memory/.raw_fallbacks/raw.md",
            target_path=None,
            content_hash="h1",
            idempotency_key="repair:r1",
            status="repair_pending",
            reason="parse_failed_archived",
        )
    )

    rows = await list_repair_queue(storage, limit=10)

    assert rows[0].source_path == "memory/.raw_fallbacks/raw.md"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
TMPDIR=/dev/shm .venv/bin/pytest tests/test_memory_repair_service.py -k "ledger_pending" -q
```

Expected: FAIL because repair queue is still raw-fallback-file driven.

- [ ] **Step 3: Add queue listing from ledger**

Implement `list_repair_queue(storage, limit)` that returns rows with statuses:

- `repair_pending`
- `distill_failed`
- `flush_failed`

Sort by `next_retry_at_ms NULLS FIRST`, then `created_at ASC`.

- [ ] **Step 4: Add retry/backoff transitions**

Implement:

- attempt 1 failure -> `next_retry_at_ms = now + 5 minutes`
- attempt 2 failure -> `now + 30 minutes`
- attempt 3 failure -> `now + 6 hours`
- attempt 4 failure -> `repair_abandoned`

- [ ] **Step 5: Keep legacy raw fallback as input**

Legacy `memory/.raw_fallbacks/*.md` files without ledger rows should be imported as `repair_pending` rows before repair runs. Do not delete raw files after repair; mark the ledger row `repair_done`.

- [ ] **Step 6: Run repair and RPC tests**

Run:

```bash
TMPDIR=/dev/shm .venv/bin/pytest tests/test_memory_repair_service.py tests/test_gateway/test_rpc_product_cli_gaps.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/opensquilla/gateway/memory_repair_service.py src/opensquilla/gateway/rpc_memory.py tests/test_memory_repair_service.py tests/test_gateway/test_rpc_product_cli_gaps.py
git commit -m "Drive memory repair from durable receipts"
```

---

### Task 10: Expose Safety And Semantic Health Separately

**Files:**
- Modify: `src/opensquilla/gateway/rpc_system.py`
- Modify: `src/opensquilla/gateway/rpc_memory.py`
- Modify: `src/opensquilla/gateway/static/js/views/chat.js`
- Modify: `tests/test_gateway/test_chat_view_static.py`
- Modify: `tests/test_gateway/test_rpc_product_cli_gaps.py`

- [ ] **Step 1: Write failing health tests**

Add assertions that system/memory health reports separate fields:

```python
assert payload["memorySafety"]["status"] in {"ok", "error"}
assert payload["semanticMemory"]["status"] in {"healthy", "degraded", "warning"}
assert "repairBacklogCount" in payload["semanticMemory"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
TMPDIR=/dev/shm .venv/bin/pytest tests/test_gateway/test_rpc_product_cli_gaps.py -k "memory_health" -q
```

Expected: FAIL because split health fields are missing.

- [ ] **Step 3: Implement health summary**

Use ledger rows to compute:

- `memorySafety.status = "error"` if any recent `checkpoint_failed`, `receipt_orphaned`, or hash mismatch exists.
- `memorySafety.status = "ok"` otherwise.
- `semanticMemory.status = "healthy"` if pending backlog is 0.
- `semanticMemory.status = "degraded"` if backlog is 1-10 and oldest pending <= 24h.
- `semanticMemory.status = "warning"` if backlog > 10 or oldest pending > 24h.

- [ ] **Step 4: Keep normal WebUI chat positive**

In chat UI, show no blocking error for `semanticMemory.degraded`. If a status is displayed, use a non-blocking label such as `Memory saved; organizing`. Do not surface raw checkpoint paths in ordinary chat.

- [ ] **Step 5: Run gateway static and RPC tests**

Run:

```bash
TMPDIR=/dev/shm .venv/bin/pytest tests/test_gateway/test_chat_view_static.py tests/test_gateway/test_rpc_product_cli_gaps.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/opensquilla/gateway/rpc_system.py src/opensquilla/gateway/rpc_memory.py src/opensquilla/gateway/static/js/views/chat.js tests/test_gateway/test_chat_view_static.py tests/test_gateway/test_rpc_product_cli_gaps.py
git commit -m "Separate memory safety from semantic repair health"
```

---

### Task 11: Verify WebUI Chat Sendability Under Memory Failures

**Files:**
- Modify: `tests/test_gateway/test_context_overflow.py`
- Modify: `tests/test_gateway/test_chat_view_static.py`
- Modify: `scripts/live_long_context_chat_smoke.py`

- [ ] **Step 1: Add failing RPC smoke test**

Add a test where the flush/distill service fails but checkpoint succeeds:

```python
async def test_chat_send_stays_sendable_when_distill_fails(tmp_path):
    ctx = _make_chat_context(
        checkpoint_result="checkpoint_saved",
        flush_error=RuntimeError("bad json"),
    )

    result = await _handle_chat_send({"message": "continue", "sessionKey": "webchat:abc"}, ctx)

    assert result["ok"] is True
    assert "flush failed" not in str(result).lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
TMPDIR=/dev/shm .venv/bin/pytest tests/test_gateway/test_context_overflow.py -k "distill_fails" -q
```

Expected: FAIL until chat path ignores semantic distill failure after checkpoint.

- [ ] **Step 3: Update chat/context overflow behavior**

Ensure `chat.send` and automatic context overflow paths:

- do not await repair
- do not return semantic distill failure to normal user
- keep refusal only for budget failure when no safe sendable view can be produced
- keep checkpoint failures visible only when destructive removal would otherwise happen unsafely

- [ ] **Step 4: Extend live smoke script**

Add an option:

```bash
--simulate-memory-distill-failure
```

The smoke should prove the send call is accepted and the UI does not show a blocking memory error.

- [ ] **Step 5: Run gateway tests**

Run:

```bash
TMPDIR=/dev/shm .venv/bin/pytest tests/test_gateway/test_context_overflow.py tests/test_gateway/test_chat_view_static.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/test_gateway/test_context_overflow.py tests/test_gateway/test_chat_view_static.py scripts/live_long_context_chat_smoke.py
git commit -m "Keep WebUI chat sendable during memory distill failures"
```

---

### Task 12: End-To-End Regression And Log Assertions

**Files:**
- Modify: `tests/test_memory_flush.py`
- Modify: `tests/test_engine/test_preflight_compaction.py`
- Modify: `tests/test_gateway/test_context_overflow.py`

- [ ] **Step 1: Add log regression tests**

Add caplog assertions:

```python
assert "session_flush.raw_fallback_save_failed" not in [r.message for r in caplog.records]
assert any("session_flush.raw_fallback" in r.message for r in caplog.records)
assert all(r.levelname != "ERROR" for r in caplog.records if "raw_fallback" in r.message)
```

Only actual `memory_save` failure should emit `session_flush.raw_fallback_save_failed` at ERROR.

- [ ] **Step 2: Add destructive safety matrix tests**

Cover:

- checkpoint saved + distill failed -> compaction allowed
- checkpoint failed + distill failed -> compaction refused in destructive path
- no checkpoint + degraded raw fallback -> existing protect/block semantics preserved
- checkpoint orphaned -> compaction refused

- [ ] **Step 3: Run targeted suite**

Run:

```bash
TMPDIR=/dev/shm .venv/bin/pytest tests/test_memory_checkpoint.py tests/test_memory_flush.py tests/test_session/test_compaction_lifecycle.py tests/test_engine/test_preflight_compaction.py tests/test_gateway/test_context_overflow.py tests/test_memory_repair_service.py -q
```

Expected: PASS.

- [ ] **Step 4: Run broader memory/session/gateway verification**

Run:

```bash
TMPDIR=/dev/shm .venv/bin/pytest tests/test_memory_search_defaults.py tests/test_session tests/test_gateway/test_rpc_sessions.py tests/test_gateway/test_rpc_product_cli_gaps.py -q
```

Expected: PASS.

- [ ] **Step 5: Run compile and diff checks**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m compileall -q src/opensquilla/memory src/opensquilla/session src/opensquilla/gateway
```

Expected: exit 0.

Run:

```bash
git diff --check
```

Expected: exit 0.

- [ ] **Step 6: Commit**

```bash
git add tests/test_memory_flush.py tests/test_engine/test_preflight_compaction.py tests/test_gateway/test_context_overflow.py
git commit -m "Prove durable memory pipeline failure semantics"
```

---

## Acceptance Criteria

- Normal WebUI chat remains sendable when semantic memory distillation fails.
- Destructive compaction never removes transcript entries unless a durable checkpoint, safe flush, or equivalent archive receipt covers the removed window.
- `invalid_proposal_json` and `parse_failed_archived` become semantic repair signals, not safety failures when checkpoint exists.
- `memory/.checkpoints/**` and `memory/.raw_fallbacks/**` never enter search recall.
- `MemoryFlushPlan.relative_path` is the only allowed target for constrained flush writes, including rotated `-partNNN` paths.
- Repair backlog is visible through admin/system health and does not block normal chat.
- Raw fallback archive success is not logged as ERROR; only actual fallback save failure logs `session_flush.raw_fallback_save_failed`.

## Risks And Mitigations

- **Risk:** Checkpoint writes add latency to chat sends.
  **Mitigation:** Write checkpoint only when destructive compaction/reset/truncate is about to remove history; do not require per-turn checkpoint before ordinary send.

- **Risk:** DB ledger and file checkpoint can diverge.
  **Mitigation:** File write happens first, ledger success second; startup/reconcile marks missing files as `receipt_orphaned` and backfills ledger rows for existing checkpoint files.

- **Risk:** Repair queue grows forever.
  **Mitigation:** Retry schedule ends in `repair_abandoned`; health escalates backlog >10 or oldest >24h.

- **Risk:** Existing strict/block behavior regresses.
  **Mitigation:** Preserve current flush receipt semantics when no checkpoint receipt is present; add tests for protect/block modes.

- **Risk:** Checkpoint content leaks into recall.
  **Mitigation:** Dot-sidecar path, memory tool filtering, sync/index exclusion tests, and RPC health redaction.

## Verification Commands

Run after all tasks:

```bash
TMPDIR=/dev/shm .venv/bin/pytest tests/test_memory_checkpoint.py tests/test_memory_flush.py tests/test_memory_search_defaults.py tests/test_memory_repair_service.py tests/test_session/test_compaction_lifecycle.py tests/test_session/test_memory_durable_receipts.py tests/test_engine/test_preflight_compaction.py tests/test_gateway/test_context_overflow.py tests/test_gateway/test_rpc_sessions.py tests/test_gateway/test_rpc_product_cli_gaps.py tests/test_gateway/test_chat_view_static.py -q
```

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m compileall -q src/opensquilla/memory src/opensquilla/session src/opensquilla/gateway src/opensquilla/engine
```

```bash
git diff --check
```

## Execution Notes

- Use the current clean `dev` as the base.
- Do not revert the existing WebUI polish or long WebChat sendability work.
- Do not introduce a second flush planner. Reuse `opensquilla.memory.flush.MemoryFlushPlan`.
- Keep commits small; each task above is independently testable.
