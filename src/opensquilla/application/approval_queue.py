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
from fnmatch import fnmatchcase
from pathlib import Path
from typing import cast

from opensquilla.paths import state_dir

VALID_APPROVAL_MODES = frozenset({"auto-approve", "auto-deny", "prompt"})
VALID_ELEVATED_MODES = frozenset({"on", "bypass", "full"})


@dataclass
class ApprovalSettings:
    mode: str = "prompt"
    allow_patterns: list[str] = field(default_factory=list)
    deny_patterns: list[str] = field(default_factory=list)


def _command_matches(command: str, pattern: str) -> bool:
    """Match a command string against a single allow/deny pattern.

    A pattern matches when it is a shell-style glob hit
    (``fnmatchcase("uv build", "uv *")``) or a plain substring of the
    command. The substring fallback keeps unsophisticated entries like
    ``rm -rf`` working even when the user omits ``*`` wildcards. Matching is
    case-sensitive to match shell semantics; empty patterns never match.
    """
    pattern = pattern.strip()
    if not pattern:
        return False
    return fnmatchcase(command, pattern) or pattern in command


def classify_command(
    command: str,
    allow_patterns: list[str],
    deny_patterns: list[str],
) -> str | None:
    """Classify a command against allow/deny patterns (deny takes precedence).

    Returns ``"deny"`` when any deny pattern matches, ``"allow"`` when no deny
    pattern matches but an allow pattern does, or ``None`` when neither side
    matches (the caller should fall through to its normal decision path).

    Deny precedence is intentional and conservative: a command that matches
    both an allow and a deny pattern is denied. This helper is pure so the
    matching rules can be unit-tested in isolation; it has no view of the
    hard safety guards, so callers must apply allow-results only as a
    prompt-skip, never as an override of a hard block.
    """
    if not command:
        return None
    for pattern in deny_patterns:
        if _command_matches(command, pattern):
            return "deny"
    for pattern in allow_patterns:
        if _command_matches(command, pattern):
            return "allow"
    return None


# Terminal resolution reasons. ``approved``/``denied`` are explicit human
# decisions; ``expired`` is a deadline lapse with no response. The legacy
# ``approved`` boolean stays the back-compat source of truth (expired and
# denied both read ``approved=False``); ``resolution`` is the additive field
# that lets callers tell an expiry apart from a deliberate refusal.
RESOLUTION_APPROVED = "approved"
RESOLUTION_DENIED = "denied"
RESOLUTION_EXPIRED = "expired"


@dataclass
class PendingApproval:
    approval_id: str
    namespace: str  # "exec" or "plugin"
    params: dict
    created_at: float = field(default_factory=time.time)
    resolved: bool = False
    approved: bool = False
    consumed: bool = False
    # Wall-clock deadline after which an unresolved request expires. ``wait()``
    # re-reads this every poll, so ``extend()`` re-arms a pending request live.
    deadline: float = 0.0
    # One of RESOLUTION_* once resolved, else "".
    resolution: str = ""
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
    ):
        self._pending: dict[str, PendingApproval] = {}
        self._timeout = default_timeout
        self._poll_interval = max(0.01, float(poll_interval))
        self._global_settings = ApprovalSettings()
        self._node_settings: dict[str, ApprovalSettings] = {}
        self._session_elevated_modes: dict[str, str] = {}
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
                consumed      INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_approval_namespace_status
            ON approval_queue(namespace, resolved);
            """
        )
        # Migration-on-open for the columns added after the table shipped.
        # Existing rows backfill to a 0 deadline (treated as "no row-level
        # deadline" by wait()) and an inferred resolution from the legacy
        # ``approved`` flag, so persisted approvals survive an upgrade.
        existing = {
            str(row["name"])
            for row in self._conn.execute("PRAGMA table_info(approval_queue)")
        }
        if "deadline" not in existing:
            self._conn.execute(
                "ALTER TABLE approval_queue ADD COLUMN deadline REAL NOT NULL DEFAULT 0"
            )
        if "resolution" not in existing:
            self._conn.execute(
                "ALTER TABLE approval_queue ADD COLUMN resolution TEXT NOT NULL DEFAULT ''"
            )
            # Backfill resolved-but-unlabelled rows so an upgraded queue still
            # answers "was this approved or denied" for history reads.
            self._conn.execute(
                "UPDATE approval_queue SET resolution = ? "
                "WHERE resolved = 1 AND resolution = '' AND approved = 1",
                (RESOLUTION_APPROVED,),
            )
            self._conn.execute(
                "UPDATE approval_queue SET resolution = ? "
                "WHERE resolved = 1 AND resolution = '' AND approved = 0",
                (RESOLUTION_DENIED,),
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
            deadline=float(row["deadline"] or 0.0),
            resolution=str(row["resolution"] or ""),
            _event=existing._event if existing is not None else asyncio.Event(),
        )

    def _load_pending(self) -> None:
        self._pending = {}
        for row in self._conn.execute(
            "SELECT approval_id, namespace, params, created_at, resolved, approved, "
            "consumed, deadline, resolution "
            "FROM approval_queue WHERE resolved = 0"
        ):
            entry = self._row_to_entry(row)
            self._pending[entry.approval_id] = entry

    def _get_row(self, approval_id: str) -> sqlite3.Row | None:
        return cast(
            sqlite3.Row | None,
            self._conn.execute(
                "SELECT approval_id, namespace, params, created_at, resolved, approved, "
                "consumed, deadline, resolution "
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
            "deadline": entry.deadline,
            "resolved": entry.resolved,
            "approved": entry.approved,
            "resolution": entry.resolution,
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
            deadline = now + self._timeout
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                self._conn.execute(
                    "INSERT INTO approval_queue "
                    "(approval_id, namespace, params, created_at, resolved, approved, "
                    "consumed, deadline, resolution) "
                    "VALUES (?, ?, ?, ?, 0, 0, 0, ?, '')",
                    (approval_id, namespace, payload, now, deadline),
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
            deadline=deadline,
        )
        self._pending[approval_id] = entry
        self._notify_event("requested", entry)
        return approval_id

    def get(self, approval_id: str) -> PendingApproval:
        row = self._get_row(approval_id)
        if row is None:
            raise KeyError(f"Approval not found: {approval_id}")
        entry = self._row_to_entry(row)
        self._pending[approval_id] = entry
        return entry

    async def wait(self, approval_id: str, timeout: float | None = None) -> bool:
        entry = self.get(approval_id)
        if entry.resolved:
            return entry.approved
        # An explicit timeout re-arms the row's wall-clock deadline for this
        # wait; otherwise the request keeps the deadline stamped at request()
        # time. Either way the loop drives off the *row* deadline, re-read every
        # poll, so an extend() that pushes the deadline takes effect live.
        if timeout is not None:
            self._rearm_deadline(approval_id, time.time() + timeout)
        while True:
            entry = self.get(approval_id)
            if entry.resolved:
                return entry.approved
            remaining = entry.deadline - time.time()
            if remaining <= 0:
                # Deadline lapsed: try to expire. The expiry path re-checks the
                # deadline under the write lock and returns None if an extend()
                # pushed it into the future in the gap — then we re-wait on the
                # new deadline instead of expiring a just-extended request.
                outcome = self._expire_if_unresolved(approval_id)
                if outcome is not None:
                    return outcome
                continue
            try:
                await asyncio.wait_for(
                    entry._event.wait(),
                    timeout=min(self._poll_interval, remaining),
                )
            except TimeoutError:
                pass
            entry = self.get(approval_id)
            if entry.resolved:
                return entry.approved

    def _rearm_deadline(self, approval_id: str, deadline: float) -> None:
        """Set a pending request's wall-clock deadline (no-op once resolved)."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            self._conn.execute(
                "UPDATE approval_queue SET deadline = ? "
                "WHERE approval_id = ? AND resolved = 0",
                (deadline, approval_id),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        cached = self._pending.get(approval_id)
        if cached is not None and not cached.resolved:
            cached.deadline = deadline

    def extend(self, approval_id: str, seconds: float) -> float:
        """Push a pending request's deadline out by ``seconds`` and return it.

        Reads the current row deadline and adds ``seconds`` (re-arming relative
        to the live deadline, so repeated extends stack). A resolved request is
        left untouched and its existing deadline is returned. ``wait()`` re-reads
        the row each poll, so an extend lands live on an in-flight wait.
        """
        if seconds <= 0:
            raise ValueError("seconds must be positive")
        self._conn.execute("BEGIN IMMEDIATE")
        row = self._get_row(approval_id)
        if row is None:
            self._conn.rollback()
            raise KeyError(f"Approval not found: {approval_id}")
        entry = self._row_to_entry(row)
        if entry.resolved:
            self._conn.rollback()
            self._pending[approval_id] = entry
            return entry.deadline
        new_deadline = float(entry.deadline or time.time()) + float(seconds)
        self._conn.execute(
            "UPDATE approval_queue SET deadline = ? "
            "WHERE approval_id = ? AND resolved = 0",
            (new_deadline, approval_id),
        )
        self._conn.commit()
        entry = self.get(approval_id)
        return entry.deadline

    def _expire_if_unresolved(self, approval_id: str) -> bool | None:
        """Mark a lapsed-deadline request expired (distinct from an explicit deny).

        Returns the terminal ``approved`` flag once the request is resolved
        (expired → False; or whatever an explicit decision set). Returns
        ``None`` when the deadline was pushed into the future by an extend()
        that landed in the gap between the wait loop observing the lapse and
        this write lock — the request is no longer expired and the caller must
        re-wait on the new deadline. The deadline re-check and the expire write
        share one ``BEGIN IMMEDIATE`` transaction, so they are atomic against
        ``_rearm_deadline``'s own immediate transaction.
        """
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
            return entry.approved
        if entry.deadline > time.time():
            # Extended past now after the wait loop saw it lapse — not expired.
            # Refresh the cache and tell the caller to re-wait (None).
            self._conn.rollback()
            self._pending[approval_id] = entry
            return None
        self._conn.execute(
            "UPDATE approval_queue "
            "SET resolved = 1, approved = 0, resolution = ? "
            "WHERE approval_id = ? AND resolved = 0",
            (RESOLUTION_EXPIRED, approval_id),
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
            if entry.approved == approved:
                return
            raise ValueError(f"Approval already resolved: {approval_id}")

        cursor = self._conn.execute(
            "UPDATE approval_queue "
            "SET resolved = 1, approved = ?, resolution = ? "
            "WHERE approval_id = ? AND resolved = 0",
            (
                1 if approved else 0,
                RESOLUTION_APPROVED if approved else RESOLUTION_DENIED,
                approval_id,
            ),
        )
        if cursor.rowcount != 1:
            self._conn.rollback()
            entry = self.get(approval_id)
            if entry.resolved:
                entry._event.set()
                if entry.approved == approved:
                    return
                raise ValueError(f"Approval already resolved: {approval_id}")
            raise ValueError(f"Approval could not be resolved: {approval_id}")
        self._conn.commit()

        entry = self.get(approval_id)
        entry.approved = bool(approved)
        entry.resolved = True
        entry._event.set()
        self._pending[approval_id] = entry
        self._notify_event("resolved", entry)

        if approved and elevated_mode in VALID_ELEVATED_MODES:
            entry.params["elevatedMode"] = elevated_mode
            session_key = str(entry.params.get("sessionKey") or "").strip()
            if session_key:
                self.set_elevated_mode(session_key, elevated_mode)

        if approved and entry.namespace == "exec" and (allow_always or remember_intent):
            self._persist_command_intent(entry.params, allow_always=allow_always)

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
        self._conn.execute("BEGIN IMMEDIATE")
        row = self._get_row(approval_id)
        if row is None:
            self._conn.rollback()
            raise KeyError(f"Approval not found: {approval_id}")
        entry = self._row_to_entry(row)
        if not entry.resolved or not entry.approved:
            self._conn.rollback()
            raise ValueError(f"Approval is not approved: {approval_id}")
        if entry.consumed:
            self._conn.rollback()
            raise ValueError(f"Approval already consumed: {approval_id}")
        cursor = self._conn.execute(
            "UPDATE approval_queue "
            "SET consumed = 1 "
            "WHERE approval_id = ? AND resolved = 1 AND approved = 1 AND consumed = 0",
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
        return {
            "id": entry.approval_id,
            "namespace": entry.namespace,
            "params": entry.params,
            "created_at": entry.created_at,
            "deadline": entry.deadline,
            "resolved": entry.resolved,
            "approved": entry.approved,
            "resolution": entry.resolution,
            "consumed": entry.consumed,
        }

    def list_pending(self, namespace: str | None = None) -> list[dict]:
        if namespace:
            rows = self._conn.execute(
                "SELECT approval_id, namespace, params, created_at, deadline "
                "FROM approval_queue "
                "WHERE resolved = 0 AND namespace = ?",
                (namespace,),
            )
        else:
            rows = self._conn.execute(
                "SELECT approval_id, namespace, params, created_at, deadline "
                "FROM approval_queue "
                "WHERE resolved = 0",
            )
        return [
            {
                "id": str(row["approval_id"]),
                "namespace": str(row["namespace"]),
                "params": self._deserialize_params(row["params"]),
                "created_at": float(row["created_at"]),
                "deadline": float(row["deadline"] or 0.0),
            }
            for row in rows
        ]

    def set_elevated_mode(self, session_key: str, mode: str | None) -> None:
        key = session_key.strip()
        if not key:
            raise ValueError("session_key is required")
        if mode in (None, "", "off"):
            self._session_elevated_modes.pop(key, None)
            return
        if mode not in VALID_ELEVATED_MODES:
            raise ValueError("mode must be one of: on, bypass, full, off")
        self._session_elevated_modes[key] = mode

    def get_elevated_mode(self, session_key: str | None) -> str | None:
        key = (session_key or "").strip()
        if not key:
            return None
        return self._session_elevated_modes.get(key)

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
        count = 0
        for row in self._conn.execute(
            "SELECT approval_id, namespace, params, created_at, resolved, approved, "
            "consumed, deadline, resolution "
            "FROM approval_queue "
            "WHERE resolved = 0 AND namespace = 'exec'",
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
