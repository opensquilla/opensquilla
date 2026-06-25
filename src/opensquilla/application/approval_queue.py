"""Approval queue with single-process persistent state."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from opensquilla.paths import state_dir

VALID_APPROVAL_MODES = frozenset({"auto-approve", "auto-deny", "prompt"})
VALID_ELEVATED_MODES = frozenset({"on", "bypass", "full"})
VALID_RUN_MODES = frozenset({"standard", "trusted", "full"})


@dataclass
class ApprovalSettings:
    mode: str = "prompt"
    allow_patterns: list[str] = field(default_factory=list)
    deny_patterns: list[str] = field(default_factory=list)


@dataclass
class PendingApproval:
    approval_id: str
    namespace: str  # "exec" or "plugin"
    params: dict
    created_at: float = field(default_factory=time.time)
    resolved: bool = False
    approved: bool = False
    consumed: bool = False
    claim_token: str | None = None
    claim_started_at: float | None = None
    _event: asyncio.Event = field(default_factory=asyncio.Event)


_DEFAULT_APPROVAL_QUEUE_PATH = state_dir("approval_queue.sqlite")

# Listener signature: (event, info) where event is "requested" or "resolved"
# and info mirrors ``ApprovalQueue.status()`` for the affected approval.
ApprovalEventListener = Callable[[str, dict], None]


class ApprovalQueue:
    def __init__(
        self,
        default_timeout: float = 300.0,
        *,
        db_path: str | None = None,
        poll_interval: float = 0.25,
        claim_ttl_seconds: float = 60.0,
    ):
        self._pending: dict[str, PendingApproval] = {}
        self._timeout = default_timeout
        self._poll_interval = max(0.01, float(poll_interval))
        self._claim_ttl_seconds = max(0.0, float(claim_ttl_seconds))
        self._global_settings = ApprovalSettings()
        self._node_settings: dict[str, ApprovalSettings] = {}
        self._session_run_modes: dict[str, str] = {}
        self._event_listeners: list[ApprovalEventListener] = []

        self._db_path = Path(db_path or os.fspath(_DEFAULT_APPROVAL_QUEUE_PATH))
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            self._db_path,
            timeout=30.0,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._init_schema()
        self._load_pending()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS approval_queue (
                approval_id   TEXT PRIMARY KEY,
                namespace     TEXT NOT NULL,
                params        TEXT NOT NULL,
                created_at    REAL NOT NULL,
                resolved      INTEGER NOT NULL DEFAULT 0,
                approved      INTEGER NOT NULL DEFAULT 0,
                consumed      INTEGER NOT NULL DEFAULT 0,
                claim_token   TEXT,
                claim_started_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_approval_namespace_status
            ON approval_queue(namespace, resolved);
            """
        )
        try:
            self._conn.execute("ALTER TABLE approval_queue ADD COLUMN claim_token TEXT")
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise
        try:
            self._conn.execute("ALTER TABLE approval_queue ADD COLUMN claim_started_at REAL")
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise
        self._conn.commit()

    def _release_stale_claims(self) -> None:
        threshold = time.time() - self._claim_ttl_seconds
        self._conn.execute("BEGIN IMMEDIATE")
        self._conn.execute(
            "UPDATE approval_queue "
            "SET claim_token = NULL, claim_started_at = NULL "
            "WHERE resolved = 0 "
            "AND claim_token IS NOT NULL "
            "AND (claim_started_at IS NULL OR claim_started_at <= ?)",
            (threshold,),
        )
        self._conn.commit()

    def _serialize_params(self, params: dict | None) -> str:
        return json.dumps(params or {}, ensure_ascii=False, sort_keys=True)

    def _deserialize_params(self, raw: str | bytes | bytearray) -> dict:
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw or "{}")
        except json.JSONDecodeError:
            parsed = {}
        return parsed if isinstance(parsed, dict) else {}

    def _row_to_entry(self, row: sqlite3.Row) -> PendingApproval:
        aid = str(row["approval_id"])
        existing = self._pending.get(aid)
        return PendingApproval(
            approval_id=aid,
            namespace=str(row["namespace"]),
            params=self._deserialize_params(row["params"]),
            created_at=float(row["created_at"]),
            resolved=bool(row["resolved"]),
            approved=bool(row["approved"]),
            consumed=bool(row["consumed"]),
            claim_token=str(row["claim_token"] or "") or None,
            claim_started_at=(
                float(row["claim_started_at"])
                if row["claim_started_at"] is not None
                else None
            ),
            _event=existing._event if existing is not None else asyncio.Event(),
        )

    def _load_pending(self) -> None:
        self._pending = {}
        self._release_stale_claims()
        for row in self._conn.execute(
            "SELECT approval_id, namespace, params, created_at, resolved, approved, "
            "consumed, claim_token, claim_started_at "
            "FROM approval_queue WHERE resolved = 0"
        ):
            entry = self._row_to_entry(row)
            self._pending[entry.approval_id] = entry

    def _get_row(self, approval_id: str) -> sqlite3.Row | None:
        return cast(
            sqlite3.Row | None,
            self._conn.execute(
                "SELECT approval_id, namespace, params, created_at, resolved, approved, consumed "
                ", claim_token, claim_started_at "
                "FROM approval_queue WHERE approval_id = ?",
                (approval_id,),
            ).fetchone(),
        )

    def add_event_listener(self, listener: ApprovalEventListener) -> Callable[[], None]:
        """Register a lifecycle listener; returns a remove callable.

        Listeners fire synchronously on ``requested`` (an approval was
        created — the moment a run blocks) and ``resolved`` (a decision
        landed, including deny-on-timeout). Listener errors are swallowed:
        notification is best-effort and must never break queue state.
        """
        self._event_listeners.append(listener)

        def _remove() -> None:
            try:
                self._event_listeners.remove(listener)
            except ValueError:
                pass

        return _remove

    def _notify_event(self, event: str, entry: PendingApproval) -> None:
        if not self._event_listeners:
            return
        info = {
            "id": entry.approval_id,
            "namespace": entry.namespace,
            "params": dict(entry.params),
            "created_at": entry.created_at,
            "resolved": entry.resolved,
            "approved": entry.approved,
        }
        for listener in list(self._event_listeners):
            try:
                listener(event, info)
            except Exception:  # pragma: no cover — listeners are best-effort
                continue

    def request(self, namespace: str = "exec", params: dict | None = None) -> str:
        payload = self._serialize_params(params or {})
        while True:
            approval_id = uuid.uuid4().hex[:12]
            now = time.time()
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                self._conn.execute(
                    "INSERT INTO approval_queue "
                    "(approval_id, namespace, params, created_at, resolved, approved, "
                    "consumed, claim_token, claim_started_at) "
                    "VALUES (?, ?, ?, ?, 0, 0, 0, NULL, NULL)",
                    (approval_id, namespace, payload, now),
                )
                self._conn.commit()
            except sqlite3.IntegrityError:
                self._conn.rollback()
                continue
            break

        entry = PendingApproval(
            approval_id=approval_id,
            namespace=namespace,
            params=params or {},
            created_at=now,
        )
        self._pending[approval_id] = entry
        self._notify_event("requested", entry)
        return approval_id

    def get(self, approval_id: str) -> PendingApproval:
        self._release_stale_claims()
        row = self._get_row(approval_id)
        if row is None:
            raise KeyError(f"Approval not found: {approval_id}")
        entry = self._row_to_entry(row)
        self._pending[approval_id] = entry
        return entry

    async def wait(self, approval_id: str, timeout: float | None = None) -> bool:
        entry = self.get(approval_id)
        if entry.resolved and entry.claim_token is None:
            return entry.approved
        t = timeout if timeout is not None else self._timeout
        deadline = time.monotonic() + t
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                await asyncio.wait_for(
                    entry._event.wait(),
                    timeout=min(self._poll_interval, remaining),
                )
            except TimeoutError:
                pass
            entry = self.get(approval_id)
            if entry.resolved and entry.claim_token is None:
                return entry.approved
        return self._deny_on_timeout_if_unresolved(approval_id)

    def _deny_on_timeout_if_unresolved(self, approval_id: str) -> bool:
        self._release_stale_claims()
        self._conn.execute("BEGIN IMMEDIATE")
        row = self._get_row(approval_id)
        if row is None:
            self._conn.rollback()
            raise KeyError(f"Approval not found: {approval_id}")
        entry = self._row_to_entry(row)
        if entry.claim_token:
            self._conn.rollback()
            self._pending[approval_id] = entry
            raise ValueError(f"Approval resolution in progress: {approval_id}")
        if entry.resolved:
            self._conn.rollback()
            self._pending[approval_id] = entry
            entry._event.set()
            return entry.approved
        self._conn.execute(
            "UPDATE approval_queue "
            "SET resolved = 1, approved = 0 "
            "WHERE approval_id = ? AND resolved = 0 AND claim_token IS NULL",
            (approval_id,),
        )
        self._conn.commit()
        entry = self.get(approval_id)
        entry._event.set()
        self._pending[approval_id] = entry
        self._notify_event("resolved", entry)
        return entry.approved

    def resolve(
        self,
        approval_id: str,
        approved: bool,
        *,
        allow_always: bool = False,
        remember_intent: bool = False,
        elevated_mode: str | None = None,
        allow_idempotent: bool = True,
    ) -> None:
        self._release_stale_claims()
        self._conn.execute("BEGIN IMMEDIATE")
        row = self._get_row(approval_id)
        if row is None:
            self._conn.rollback()
            raise KeyError(f"Approval not found: {approval_id}")
        entry = self._row_to_entry(row)
        if entry.claim_token:
            self._conn.rollback()
            self._pending[approval_id] = entry
            raise ValueError(f"Approval resolution in progress: {approval_id}")
        if entry.resolved:
            self._conn.rollback()
            self._pending[approval_id] = entry
            entry._event.set()
            if allow_idempotent and entry.approved == approved:
                return
            raise ValueError(f"Approval already resolved: {approval_id}")

        cursor = self._conn.execute(
            "UPDATE approval_queue "
            "SET resolved = 1, approved = ? "
            "WHERE approval_id = ? AND resolved = 0 AND claim_token IS NULL",
            (1 if approved else 0, approval_id),
        )
        if cursor.rowcount != 1:
            self._conn.rollback()
            entry = self.get(approval_id)
            if entry.resolved:
                entry._event.set()
                if allow_idempotent and entry.approved == approved:
                    return
                raise ValueError(f"Approval already resolved: {approval_id}")
            if entry.claim_token:
                raise ValueError(f"Approval resolution in progress: {approval_id}")
            raise ValueError(f"Approval could not be resolved: {approval_id}")
        self._conn.commit()

        entry = self.get(approval_id)
        entry.approved = bool(approved)
        entry.resolved = True
        entry._event.set()
        self._pending[approval_id] = entry
        self._notify_event("resolved", entry)

        del elevated_mode

        if approved and entry.namespace == "exec" and (allow_always or remember_intent):
            self._persist_command_intent(entry.params, allow_always=allow_always)

    def claim_resolution(self, approval_id: str) -> str:
        self._release_stale_claims()
        token = uuid.uuid4().hex
        now = time.time()
        self._conn.execute("BEGIN IMMEDIATE")
        row = self._get_row(approval_id)
        if row is None:
            self._conn.rollback()
            raise KeyError(f"Approval not found: {approval_id}")
        entry = self._row_to_entry(row)
        if entry.claim_token:
            self._conn.rollback()
            self._pending[approval_id] = entry
            raise ValueError(f"Approval resolution in progress: {approval_id}")
        if entry.resolved:
            self._conn.rollback()
            self._pending[approval_id] = entry
            entry._event.set()
            raise ValueError(f"Approval already resolved: {approval_id}")
        cursor = self._conn.execute(
            "UPDATE approval_queue "
            "SET claim_token = ?, claim_started_at = ? "
            "WHERE approval_id = ? AND resolved = 0 AND claim_token IS NULL",
            (token, now, approval_id),
        )
        if cursor.rowcount != 1:
            self._conn.rollback()
            entry = self.get(approval_id)
            if entry.resolved:
                raise ValueError(f"Approval already resolved: {approval_id}")
            if entry.claim_token:
                raise ValueError(f"Approval resolution in progress: {approval_id}")
            raise ValueError(f"Approval could not be claimed: {approval_id}")
        self._conn.commit()
        self._pending[approval_id] = self.get(approval_id)
        return token

    def finalize_claimed_resolution(
        self,
        approval_id: str,
        claim_token: str,
        approved: bool,
        *,
        allow_always: bool = False,
        remember_intent: bool = False,
        elevated_mode: str | None = None,
    ) -> None:
        self._conn.execute("BEGIN IMMEDIATE")
        row = self._get_row(approval_id)
        if row is None:
            self._conn.rollback()
            raise KeyError(f"Approval not found: {approval_id}")
        entry = self._row_to_entry(row)
        if entry.resolved:
            self._conn.rollback()
            self._pending[approval_id] = entry
            entry._event.set()
            raise ValueError(f"Approval already resolved: {approval_id}")
        if entry.claim_token != claim_token:
            self._conn.rollback()
            self._pending[approval_id] = entry
            raise ValueError(f"Approval resolution claim mismatch: {approval_id}")
        cursor = self._conn.execute(
            "UPDATE approval_queue "
            "SET resolved = 1, approved = ? "
            "WHERE approval_id = ? AND resolved = 0 AND claim_token = ?",
            (1 if approved else 0, approval_id, claim_token),
        )
        if cursor.rowcount != 1:
            self._conn.rollback()
            raise ValueError(f"Approval could not be finalized: {approval_id}")
        self._conn.commit()

        row = self._get_row(approval_id)
        if row is None:
            raise KeyError(f"Approval not found: {approval_id}")
        entry = self._row_to_entry(row)
        entry.approved = bool(approved)
        entry.resolved = True
        self._pending[approval_id] = entry

        del elevated_mode

    def complete_claimed_resolution(
        self,
        approval_id: str,
        claim_token: str,
        *,
        allow_always: bool = False,
        remember_intent: bool = False,
        elevated_mode: str | None = None,
    ) -> None:
        self._conn.execute("BEGIN IMMEDIATE")
        row = self._get_row(approval_id)
        if row is None:
            self._conn.rollback()
            raise KeyError(f"Approval not found: {approval_id}")
        entry = self._row_to_entry(row)
        if entry.resolved and entry.approved and entry.claim_token is None:
            self._conn.rollback()
            entry._event.set()
            self._pending[approval_id] = entry
            if entry.namespace == "exec" and (allow_always or remember_intent):
                self._persist_command_intent(entry.params, allow_always=allow_always)
            return
        if not entry.resolved or not entry.approved:
            self._conn.rollback()
            self._pending[approval_id] = entry
            raise ValueError(f"Approval is not approved: {approval_id}")
        if entry.claim_token != claim_token:
            self._conn.rollback()
            self._pending[approval_id] = entry
            raise ValueError(f"Approval resolution claim mismatch: {approval_id}")
        cursor = self._conn.execute(
            "UPDATE approval_queue "
            "SET claim_token = NULL, claim_started_at = NULL "
            "WHERE approval_id = ? AND resolved = 1 AND approved = 1 "
            "AND claim_token = ?",
            (approval_id, claim_token),
        )
        if cursor.rowcount != 1:
            self._conn.rollback()
            raise ValueError(f"Approval could not be completed: {approval_id}")
        self._conn.commit()

        entry = self.get(approval_id)
        entry._event.set()
        self._pending[approval_id] = entry
        self._notify_event("resolved", entry)

        del elevated_mode

        if entry.namespace == "exec" and (allow_always or remember_intent):
            self._persist_command_intent(entry.params, allow_always=allow_always)

    def release_resolution_claim(self, approval_id: str, claim_token: str) -> None:
        self._conn.execute("BEGIN IMMEDIATE")
        row = self._get_row(approval_id)
        if row is None:
            self._conn.rollback()
            raise KeyError(f"Approval not found: {approval_id}")
        entry = self._row_to_entry(row)
        if entry.resolved:
            self._conn.rollback()
            self._pending[approval_id] = entry
            return
        if entry.claim_token != claim_token:
            self._conn.rollback()
            self._pending[approval_id] = entry
            return
        self._conn.execute(
            "UPDATE approval_queue "
            "SET claim_token = NULL, claim_started_at = NULL "
            "WHERE approval_id = ? AND resolved = 0 AND claim_token = ?",
            (approval_id, claim_token),
        )
        self._conn.commit()
        self._pending[approval_id] = self.get(approval_id)

    def reopen_resolved_approval(
        self,
        approval_id: str,
        *,
        expected_approved: bool = True,
    ) -> None:
        self._conn.execute("BEGIN IMMEDIATE")
        row = self._get_row(approval_id)
        if row is None:
            self._conn.rollback()
            raise KeyError(f"Approval not found: {approval_id}")
        entry = self._row_to_entry(row)
        if not entry.resolved:
            self._conn.rollback()
            self._pending[approval_id] = entry
            return
        if entry.approved != expected_approved:
            self._conn.rollback()
            self._pending[approval_id] = entry
            raise ValueError(f"Approval resolved state mismatch: {approval_id}")
        self._conn.execute(
            "UPDATE approval_queue "
            "SET resolved = 0, approved = 0, consumed = 0, "
            "claim_token = NULL, claim_started_at = NULL "
            "WHERE approval_id = ? AND resolved = 1 AND approved = ?",
            (approval_id, 1 if expected_approved else 0),
        )
        self._conn.commit()
        reopened = self.get(approval_id)
        reopened._event.clear()
        self._pending[approval_id] = reopened

    def _persist_command_intent(self, params: dict, allow_always: bool = False) -> None:
        if not isinstance(params, dict):
            return
        command = str(params.get("command") or "")
        if not command:
            return
        try:
            from opensquilla.application.intent_cache import get_intent_cache

            cache = get_intent_cache()
            if allow_always:
                cache.record_always(command)
            else:
                cache.record(command)
        except Exception:  # pragma: no cover — cache path is best-effort
            return

    def consume(self, approval_id: str) -> None:
        self._release_stale_claims()
        self._conn.execute("BEGIN IMMEDIATE")
        row = self._get_row(approval_id)
        if row is None:
            self._conn.rollback()
            raise KeyError(f"Approval not found: {approval_id}")
        entry = self._row_to_entry(row)
        if entry.claim_token:
            self._conn.rollback()
            self._pending[approval_id] = entry
            raise ValueError(f"Approval resolution in progress: {approval_id}")
        if not entry.resolved or not entry.approved:
            self._conn.rollback()
            raise ValueError(f"Approval is not approved: {approval_id}")
        if entry.consumed:
            self._conn.rollback()
            raise ValueError(f"Approval already consumed: {approval_id}")
        cursor = self._conn.execute(
            "UPDATE approval_queue "
            "SET consumed = 1 "
            "WHERE approval_id = ? AND resolved = 1 AND approved = 1 "
            "AND consumed = 0 AND claim_token IS NULL",
            (approval_id,),
        )
        if cursor.rowcount != 1:
            self._conn.rollback()
            entry = self.get(approval_id)
            if entry.consumed:
                raise ValueError(f"Approval already consumed: {approval_id}")
            raise ValueError(f"Approval is not approved: {approval_id}")
        self._conn.commit()
        entry = self.get(approval_id)
        self._pending.pop(approval_id, None)

    def status(self, approval_id: str) -> dict:
        entry = self.get(approval_id)
        ready = entry.resolved and entry.claim_token is None
        return {
            "id": entry.approval_id,
            "namespace": entry.namespace,
            "params": entry.params,
            "created_at": entry.created_at,
            "resolved": ready,
            "approved": entry.approved if ready else False,
            "consumed": entry.consumed if ready else False,
        }

    def list_pending(self, namespace: str | None = None) -> list[dict]:
        self._release_stale_claims()
        if namespace:
            rows = self._conn.execute(
                "SELECT approval_id, namespace, params, created_at "
                "FROM approval_queue "
                "WHERE resolved = 0 AND claim_token IS NULL AND namespace = ?",
                (namespace,),
            )
        else:
            rows = self._conn.execute(
                "SELECT approval_id, namespace, params, created_at "
                "FROM approval_queue "
                "WHERE resolved = 0 AND claim_token IS NULL",
            )
        return [
            {
                "id": str(row["approval_id"]),
                "namespace": str(row["namespace"]),
                "params": self._deserialize_params(row["params"]),
                "created_at": float(row["created_at"]),
            }
            for row in rows
        ]

    def set_elevated_mode(self, session_key: str, mode: str | None) -> None:
        """Legacy compatibility wrapper for session run mode."""
        key = session_key.strip()
        if not key:
            raise ValueError("session_key is required")
        if mode in (None, "", "off"):
            self._session_run_modes.pop(key, None)
            return
        if mode not in VALID_ELEVATED_MODES:
            raise ValueError("mode must be one of: on, bypass, full, off")
        self.set_run_mode(key, "full" if mode == "full" else "trusted")

    def get_elevated_mode(self, session_key: str | None) -> str | None:
        """Legacy compatibility wrapper returning only full host access."""
        mode = self.get_run_mode(session_key)
        return "full" if mode == "full" else None

    def set_run_mode(self, session_key: str, mode: str | None) -> None:
        key = session_key.strip()
        if not key:
            raise ValueError("session_key is required")
        if mode in (None, "", "off"):
            self._session_run_modes.pop(key, None)
            return
        if mode not in VALID_RUN_MODES:
            raise ValueError("mode must be one of: full, standard, trusted, off")
        self._session_run_modes[key] = mode

    def get_run_mode(self, session_key: str | None) -> str | None:
        key = (session_key or "").strip()
        if not key:
            return None
        return self._session_run_modes.get(key)

    def resolve_pending_for_session(
        self,
        session_key: str,
        *,
        approved: bool,
        elevated_mode: str | None = None,
    ) -> int:
        key = session_key.strip()
        if not key:
            return 0
        self._release_stale_claims()
        count = 0
        for row in self._conn.execute(
            "SELECT approval_id, namespace, params, created_at, resolved, approved, "
            "consumed, claim_token, claim_started_at "
            "FROM approval_queue "
            "WHERE resolved = 0 AND claim_token IS NULL AND namespace = 'exec'",
        ).fetchall():
            entry = self._row_to_entry(row)
            if str(entry.params.get("sessionKey") or "").strip() != key:
                continue
            self.resolve(
                entry.approval_id,
                approved,
                elevated_mode=elevated_mode,
            )
            count += 1
        return count

    def get_settings(self, node_id: str | None = None) -> ApprovalSettings:
        settings = self._node_settings.get(node_id) if node_id else self._global_settings
        if settings is None:
            settings = self._global_settings
        return ApprovalSettings(
            mode=settings.mode,
            allow_patterns=list(settings.allow_patterns),
            deny_patterns=list(settings.deny_patterns),
        )

    def has_node_settings(self, node_id: str) -> bool:
        return node_id in self._node_settings

    def set_settings(
        self,
        mode: str,
        allow_patterns: list[str] | None = None,
        deny_patterns: list[str] | None = None,
        node_id: str | None = None,
    ) -> ApprovalSettings:
        if mode not in VALID_APPROVAL_MODES:
            raise ValueError(f"mode must be one of: {', '.join(sorted(VALID_APPROVAL_MODES))}")
        settings = ApprovalSettings(
            mode=mode,
            allow_patterns=list(allow_patterns or []),
            deny_patterns=list(deny_patterns or []),
        )
        if node_id is None:
            self._global_settings = settings
        else:
            self._node_settings[node_id] = settings
        return settings

    def close(self) -> None:
        self._conn.close()


_queue: ApprovalQueue | None = None


def get_approval_queue() -> ApprovalQueue:
    global _queue
    if _queue is None:
        _queue = ApprovalQueue()
    return _queue


def reset_approval_queue() -> None:
    global _queue
    if _queue is not None:
        path = _queue._db_path
        _queue.close()
        _queue = None
    else:
        path = _DEFAULT_APPROVAL_QUEUE_PATH
    try:
        path.unlink()
    except FileNotFoundError:
        pass
