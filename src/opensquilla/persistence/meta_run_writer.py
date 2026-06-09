"""MetaRunWriter — persistence facade for meta-skill execution traces.

G4 traceable and auditable ledger. Thread-safe sync writer over a long-lived
SQLite connection; the orchestrator wraps calls in ``loop.run_in_executor()``.

Connection contract:
    * ``check_same_thread=False`` — allows cross-thread access.
    * ``threading.Lock`` around every SQL call — serializes at Python level.
    * PRAGMAs set once at construction: ``foreign_keys=ON``,
      ``journal_mode=WAL``, ``synchronous=NORMAL``, ``busy_timeout=5000``.

Fail-open: persistence is observability; all writes are try/except → log.warning
so a writer failure cannot fail a meta-skill turn.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from opensquilla.skills.meta.types import MetaPlan, MetaResult, MetaStep

log = logging.getLogger(__name__)

# 64 KiB matches tool_truncation.py
_DEFAULT_MAX_FIELD_BYTES = 64 * 1024
# 4 KiB per-string clip for redactor; small enough to discourage secrets
_REDACTOR_PER_STRING_BYTES = 4 * 1024

_SECRET_KEY_RE = re.compile(
    r"(?i)(api_?key|access_?key|secret|token|password|passwd|auth(?:_?header)?|bearer)"
)
_SECRET_PREFIX_RE = re.compile(
    r"^(sk-|pk-|ghp_|gho_|ghu_|ghs_|ghr_|xoxb-|xoxp-|Bearer )"
)
# Crockford Base32 — no I, L, O, U
_BASE32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

# Monotonic ULID state — when two _gen_ulid() calls land in the same ms, the
# random component is incremented by 1 instead of re-rolled so the result
# is strictly greater than the previous one (ULID spec §"Monotonicity").
_ULID_LOCK = threading.Lock()
_ULID_LAST_TS_MS: int = -1
_ULID_LAST_RAND: int = 0
_ULID_RAND_MAX = (1 << 80) - 1


# ---------------------------------------------------------------------------
# Dataclasses (public API)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StepRecord:
    run_id: str
    step_id: str
    step_kind: str
    declared_skill: str
    effective_skill: str
    status: str
    started_at_ms: int
    ended_at_ms: int | None
    rendered_inputs_json: str
    output_text: str | None
    error: str | None
    substitute_step_id: str | None
    truncated_fields: tuple[str, ...]


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    meta_skill_name: str
    meta_skill_digest: str
    plan_snapshot_json: str
    triggered_by: str
    session_key: str | None
    turn_id: str | None
    owner_pid: int | None
    status: str
    started_at_ms: int
    ended_at_ms: int | None
    inputs_json: str
    final_text: str | None
    failed_step_id: str | None
    error: str | None
    truncated_fields: tuple[str, ...]
    steps: tuple[StepRecord, ...] = ()


@dataclass
class AwaitingPeek:
    """Read-only view of a single `awaiting_user` row.

    Returned by `MetaRunWriter.peek_awaiting`. The schema field is the
    deserialized `ClarifyStepConfig`; the `_json` strings are exposed
    raw so callers that just want to forward them (e.g. the surface
    renderers) don't pay a JSON parse cost.
    """

    run_id: str
    step_id: str
    awaiting_since: float
    awaiting_session_id: str
    awaiting_schema_json: str
    awaiting_filled_json: str
    step_outputs_json: str
    inputs_json: str
    parse_failure_count: int


@dataclass
class ResumePayload:
    """Full payload required to call MetaOrchestrator.resume.

    Returned by `MetaRunWriter.try_claim_resume` only on rowcount==1
    (the caller has won the CAS for this run).
    """

    run_id: str
    plan_snapshot_json: str
    inputs_json: str
    step_outputs_json: str
    awaiting_step_id: str
    awaiting_schema_json: str
    awaiting_filled_json: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _truncate(
    value: str | None, field_name: str, *, max_bytes: int
) -> tuple[str | None, bool]:
    """UTF-8 byte-bounded truncate. Returns (value, was_truncated)."""
    if value is None:
        return None, False
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value, False
    clipped = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return clipped, True


def _gen_ulid() -> str:
    """26-char monotonic ULID.

    48-bit ms timestamp + 80-bit randomness, Crockford-base32. When two calls
    fall in the same millisecond, the random component is incremented from
    the previous one rather than re-rolled — guarantees lexicographic order
    matches insertion order even at sub-ms cadence (ULID spec §monotonic).
    """
    global _ULID_LAST_TS_MS, _ULID_LAST_RAND
    ts_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    with _ULID_LOCK:
        if ts_ms == _ULID_LAST_TS_MS:
            # Same ms — increment last random. If it overflows the 80-bit
            # space, bump the ms by 1 and re-roll (extremely rare).
            rand_int = _ULID_LAST_RAND + 1
            if rand_int > _ULID_RAND_MAX:
                ts_ms = (ts_ms + 1) & ((1 << 48) - 1)
                rand_int = int.from_bytes(secrets.token_bytes(10), "big")
        else:
            rand_int = int.from_bytes(secrets.token_bytes(10), "big")
        _ULID_LAST_TS_MS = ts_ms
        _ULID_LAST_RAND = rand_int
    full = (ts_ms << 80) | rand_int
    out_chars: list[str] = []
    for shift in range(125, -1, -5):  # 26 * 5 = 130 bits; top two are zero
        out_chars.append(_BASE32[(full >> shift) & 0x1F])
    return "".join(out_chars[:26])


def _redact_inputs_json(raw: Mapping[str, Any], *, max_bytes: int) -> str:
    """Recursive redactor for arbitrary inputs mapping.

    Rules:
    * Key match against secret regex → ``[REDACTED]``
    * Value prefix match against secret prefix regex → ``[REDACTED]``
    * Per-string clip to ``_REDACTOR_PER_STRING_BYTES``
    * Total JSON ≤ ``max_bytes``; drops fields in reverse-key order on overflow
    """

    def _walk(node: Any, key_hint: str | None) -> Any:
        if isinstance(node, Mapping):
            return {k: _walk(v, key_hint=str(k)) for k, v in node.items()}
        if isinstance(node, (list, tuple)):
            return [_walk(item, key_hint=key_hint) for item in node]
        if isinstance(node, str):
            if key_hint and _SECRET_KEY_RE.search(key_hint):
                return "[REDACTED]"
            if _SECRET_PREFIX_RE.match(node):
                return "[REDACTED]"
            encoded = node.encode("utf-8")
            if len(encoded) > _REDACTOR_PER_STRING_BYTES:
                clipped = encoded[:_REDACTOR_PER_STRING_BYTES].decode(
                    "utf-8", errors="ignore"
                )
                # Keep suffix tiny (1 char) so total stays within
                # ``_REDACTOR_PER_STRING_BYTES + 4`` chars; callers asserting
                # the budget would fail with a verbose suffix.
                return f"{clipped}…"
            return node
        return node

    redacted = _walk(dict(raw), key_hint=None)
    text = json.dumps(redacted, sort_keys=True, ensure_ascii=False)
    if len(text.encode("utf-8")) <= max_bytes:
        return text

    # Overflow — drop fields in reverse-key order
    keys = sorted(redacted.keys(), reverse=True)
    while keys:
        dropped = keys.pop(0)
        redacted.pop(dropped, None)
        redacted["_redaction_overflow"] = True
        text = json.dumps(redacted, sort_keys=True, ensure_ascii=False)
        if len(text.encode("utf-8")) <= max_bytes:
            return text
    return json.dumps({"_redaction_overflow": True}, sort_keys=True)


def _serialize_plan(plan: MetaPlan) -> tuple[str, str]:
    """Returns (plan_snapshot_json, meta_skill_digest).

    Thin wrapper over opensquilla.skills.meta.plan_serde; this preserves the
    versioned user-input plan snapshot contract.
    The snapshot JSON is the *envelope* (with ``"v": 1``); the digest is
    over the same canonical JSON. Existing rows' digests will change on
    next write — this is a one-time churn at the V013 cut-over.
    """
    from opensquilla.skills.meta.plan_serde import plan_digest, to_jsonable

    snapshot = to_jsonable(plan)
    snapshot_json = json.dumps(snapshot, sort_keys=True, ensure_ascii=False)
    digest = plan_digest(plan)
    return snapshot_json, digest


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


class MetaRunWriter:
    """Long-lived sync writer over a single sqlite3 connection.

    Caller responsibilities:
    * Construct via :func:`open_meta_run_writer` (sets PRAGMAs).
    * Call ``close()`` at shutdown.
    * Wrap async calls in ``loop.run_in_executor()`` if used from async code.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        max_field_bytes: int = _DEFAULT_MAX_FIELD_BYTES,
        clock: Callable[[], int] = lambda: int(time.time() * 1000),
        id_gen: Callable[[], str] = _gen_ulid,
        pid_fn: Callable[[], int] = os.getpid,
    ) -> None:
        self._conn = connection
        self._lock = threading.Lock()
        self._max_field_bytes = max_field_bytes
        self._clock = clock
        self._id_gen = id_gen
        self._pid_fn = pid_fn

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception as exc:  # noqa: BLE001
                log.warning("meta_run_writer.close_failed: %s", exc)

    # ------------- write path -------------

    def begin_run_sync(
        self,
        *,
        meta_skill_name: str,
        meta_plan: MetaPlan,
        triggered_by: Literal[
            "hard_takeover", "soft_meta_invoke", "auto_cron", "auto_dream",
        ],
        inputs: Mapping[str, Any],
        session_key: str | None,
        turn_id: str | None,
    ) -> str:
        run_id = self._id_gen()
        snapshot_json, digest = _serialize_plan(meta_plan)
        inputs_json = _redact_inputs_json(inputs, max_bytes=self._max_field_bytes)
        try:
            with self._lock:
                self._conn.execute(
                    """
                    INSERT INTO meta_skill_runs (
                        run_id, meta_skill_name, meta_skill_digest, plan_snapshot_json,
                        triggered_by, session_key, turn_id, owner_pid, status,
                        started_at_ms, inputs_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, ?)
                    """,
                    (
                        run_id, meta_skill_name, digest, snapshot_json,
                        triggered_by, session_key, turn_id, self._pid_fn(),
                        self._clock(), inputs_json,
                    ),
                )
                self._conn.commit()
        except Exception as exc:  # noqa: BLE001
            log.warning("meta_run_writer.begin_run_failed: %s", exc)
        return run_id

    def begin_step_sync(
        self,
        *,
        run_id: str,
        step: MetaStep,
        effective_skill: str,
        rendered_inputs: Mapping[str, Any],
    ) -> None:
        rendered_json = _redact_inputs_json(rendered_inputs, max_bytes=self._max_field_bytes)
        try:
            with self._lock:
                self._conn.execute(
                    """
                    INSERT INTO meta_skill_run_steps (
                        run_id, step_id, step_kind, declared_skill, effective_skill,
                        status, started_at_ms, rendered_inputs_json
                    ) VALUES (?, ?, ?, ?, ?, 'running', ?, ?)
                    """,
                    (
                        run_id, step.id, step.kind, step.skill, effective_skill,
                        self._clock(), rendered_json,
                    ),
                )
                self._conn.commit()
        except Exception as exc:  # noqa: BLE001
            log.warning("meta_run_writer.begin_step_failed: %s", exc)

    def finish_step_sync(
        self,
        *,
        run_id: str,
        step_id: str,
        status: Literal["ok", "failed", "substituted"],
        output_text: str | None,
        error: str | None = None,
        substitute_step_id: str | None = None,
    ) -> None:
        truncated: list[str] = []
        out, was_t = _truncate(output_text, "output_text", max_bytes=self._max_field_bytes)
        if was_t:
            truncated.append("output_text")
        try:
            with self._lock:
                self._conn.execute(
                    """
                    UPDATE meta_skill_run_steps
                       SET status=?, ended_at_ms=?, output_text=?, error=?,
                           substitute_step_id=?, truncated_fields=?
                     WHERE run_id=? AND step_id=?
                    """,
                    (
                        status, self._clock(), out, error,
                        substitute_step_id, ",".join(truncated),
                        run_id, step_id,
                    ),
                )
                self._conn.commit()
        except Exception as exc:  # noqa: BLE001
            log.warning("meta_run_writer.finish_step_failed: %s", exc)

    def on_step_failover_sync(
        self,
        *,
        run_id: str,
        failed_step_id: str,
        substitute_step_id: str,
        error: str,
    ) -> None:
        """C3: mark original step as substituted with substitute pointer."""
        self.finish_step_sync(
            run_id=run_id,
            step_id=failed_step_id,
            status="substituted",
            output_text=None,
            error=error,
            substitute_step_id=substitute_step_id,
        )

    def finish_run_sync(
        self,
        *,
        run_id: str,
        status: Literal["ok", "failed", "cancelled"],
        result: MetaResult | None,
    ) -> None:
        truncated: list[str] = []
        final_text: str | None = None
        failed_step_id: str | None = None
        error: str | None = None
        if result is not None:
            final_text_raw = result.final_text or None
            final_text, was_t = _truncate(
                final_text_raw, "final_text", max_bytes=self._max_field_bytes,
            )
            if was_t:
                truncated.append("final_text")
            failed_step_id = result.failed_step_id
            error = result.error
        try:
            with self._lock:
                self._conn.execute(
                    """
                    UPDATE meta_skill_runs
                       SET status=?, ended_at_ms=?, final_text=?,
                           failed_step_id=?, error=?, truncated_fields=?
                     WHERE run_id=?
                    """,
                    (
                        status, self._clock(), final_text,
                        failed_step_id, error, ",".join(truncated),
                        run_id,
                    ),
                )
                self._conn.commit()
        except Exception as exc:  # noqa: BLE001
            log.warning("meta_run_writer.finish_run_failed: %s", exc)

    # ------------- read path -------------

    def get_run(self, run_id: str) -> RunRecord | None:
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT * FROM meta_skill_runs WHERE run_id=?", (run_id,),
                ).fetchone()
        except Exception as exc:  # noqa: BLE001
            log.warning("meta_run_writer.get_run_failed: %s", exc)
            return None
        if row is None:
            return None
        return self._row_to_run(row, steps=tuple(self.get_steps(run_id)))

    def get_steps(self, run_id: str) -> list[StepRecord]:
        try:
            with self._lock:
                rows = self._conn.execute(
                    "SELECT * FROM meta_skill_run_steps WHERE run_id=? "
                    "ORDER BY started_at_ms ASC, step_id ASC",
                    (run_id,),
                ).fetchall()
        except Exception as exc:  # noqa: BLE001
            log.warning("meta_run_writer.get_steps_failed: %s", exc)
            return []
        return [self._row_to_step(r) for r in rows]

    def list_runs(
        self,
        *,
        name: str | None = None,
        status: str | None = None,
        session_key: str | None = None,
        since_ms: int | None = None,
        limit: int = 50,
    ) -> list[RunRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        if name is not None:
            clauses.append("meta_skill_name = ?")
            params.append(name)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if session_key is not None:
            clauses.append("session_key = ?")
            params.append(session_key)
        if since_ms is not None:
            clauses.append("started_at_ms >= ?")
            params.append(since_ms)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            f"SELECT * FROM meta_skill_runs{where} "
            "ORDER BY started_at_ms DESC, run_id DESC LIMIT ?"
        )
        params.append(limit)
        try:
            with self._lock:
                rows = self._conn.execute(sql, params).fetchall()
        except Exception as exc:  # noqa: BLE001
            log.warning("meta_run_writer.list_runs_failed: %s", exc)
            return []
        return [self._row_to_run(r, steps=()) for r in rows]

    def list_failures(
        self,
        *,
        name: str | None = None,
        since_ms: int | None = None,
        limit: int = 50,
    ) -> list[RunRecord]:
        return self.list_runs(
            name=name, status="failed", since_ms=since_ms, limit=limit,
        )

    def peek_awaiting(self, *, session_id: str) -> AwaitingPeek | None:
        """Read the single awaiting_user record for this session, if any.

        Read-only: does NOT transition state. The partial unique index on
        session_key WHERE status='awaiting_user' guarantees at most one row.
        """
        if not session_id:
            return None
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT * FROM meta_skill_runs "
                    "WHERE session_key=? AND status='awaiting_user' LIMIT 1",
                    (session_id,),
                ).fetchone()
        except Exception as exc:  # noqa: BLE001
            log.warning("meta_run_writer.peek_awaiting_failed: %s", exc)
            return None
        if row is None:
            return None
        return AwaitingPeek(
            run_id=row["run_id"],
            step_id=row["awaiting_step_id"] or "",
            awaiting_since=float(row["awaiting_since"] or 0.0),
            awaiting_session_id=row["session_key"] or "",
            awaiting_schema_json=row["awaiting_schema_json"] or "{}",
            awaiting_filled_json=row["awaiting_filled_json"] or "{}",
            step_outputs_json=row["step_outputs_json"] or "{}",
            inputs_json=row["inputs_json"] or "{}",
            parse_failure_count=int(row["parse_failure_count"] or 0),
        )

    def try_claim_awaiting(
        self,
        *,
        run_id: str,
        step_id: str,
        schema_json: str,
        session_id: str,
        inputs_json: str,
        step_outputs_json: str,
        awaiting_since: float,
        awaiting_filled_json: str = "{}",
    ) -> bool:
        """Atomically transition status running → awaiting_user.

        Returns True on success (rowcount == 1).
        Returns False if either:
          (a) the run is no longer 'running' (lost a race to finalize); or
          (b) another run in the same session is already awaiting_user
              (partial unique index rejects the write with IntegrityError).

        Callers MUST NOT raise MetaPaused on False — the user_input
        executor treats False as a normal step failure (design §10).

        ``awaiting_filled_json`` defaults to ``"{}"`` for callers that
        haven't run prefill. The user_input executor's prefill pass
        passes the JSON-encoded ``{field: value, __prefill_audit__:...}``
        here so the surface form renders pre-filled values on first
        paint (rather than always starting blank).
        """
        try:
            with self._lock:
                try:
                    cur = self._conn.execute(
                        """
                        UPDATE meta_skill_runs
                           SET status='awaiting_user',
                               awaiting_step_id=?,
                               awaiting_schema_json=?,
                               awaiting_since=?,
                               session_key=?,
                               inputs_json=?,
                               step_outputs_json=?,
                               awaiting_filled_json=?,
                               parse_failure_count=0
                         WHERE run_id=? AND status='running'
                        """,
                        (
                            step_id, schema_json, awaiting_since,
                            session_id, inputs_json, step_outputs_json,
                            awaiting_filled_json, run_id,
                        ),
                    )
                    if cur.rowcount == 0:
                        self._conn.rollback()
                        return False
                    self._conn.commit()
                    return True
                except sqlite3.IntegrityError as exc:
                    try:
                        self._conn.rollback()
                    except Exception:
                        pass
                    log.info(
                        "meta_run_writer.try_claim_awaiting.race_lost run=%s session=%s err=%s",
                        run_id, session_id, exc,
                    )
                    return False
        except Exception as exc:  # noqa: BLE001
            log.warning("meta_run_writer.try_claim_awaiting_failed: %s", exc)
            return False

    def try_claim_resume(
        self,
        *,
        run_id: str,
        session_id: str,
    ) -> ResumePayload | None:
        """Atomically transition awaiting_user → running, scoped by session.

        On rowcount==1, returns the full payload for MetaOrchestrator.resume.
        On rowcount==0, returns None (race lost, or cancelled/expired).
        """
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT plan_snapshot_json, inputs_json, step_outputs_json, "
                    "       awaiting_step_id, awaiting_schema_json, "
                    "       awaiting_filled_json "
                    "  FROM meta_skill_runs "
                    " WHERE run_id=? AND session_key=? AND status='awaiting_user' "
                    "LIMIT 1",
                    (run_id, session_id),
                ).fetchone()
                if row is None:
                    return None
                cur = self._conn.execute(
                    """
                    UPDATE meta_skill_runs
                       SET status='running',
                           awaiting_step_id=NULL,
                           awaiting_schema_json=NULL,
                           awaiting_since=NULL
                     WHERE run_id=? AND session_key=? AND status='awaiting_user'
                    """,
                    (run_id, session_id),
                )
                if cur.rowcount == 0:
                    self._conn.rollback()
                    return None
                self._conn.commit()
                return ResumePayload(
                    run_id=run_id,
                    plan_snapshot_json=row["plan_snapshot_json"] or "{}",
                    inputs_json=row["inputs_json"] or "{}",
                    step_outputs_json=row["step_outputs_json"] or "{}",
                    awaiting_step_id=row["awaiting_step_id"] or "",
                    awaiting_schema_json=row["awaiting_schema_json"] or "{}",
                    awaiting_filled_json=row["awaiting_filled_json"] or "{}",
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("meta_run_writer.try_claim_resume_failed: %s", exc)
            return None

    def mark_expired(self, *, run_id: str) -> None:
        """Transition an awaiting_user run to 'expired'.

        Idempotent: a row already in 'expired' is left untouched.
        """
        try:
            with self._lock:
                self._conn.execute(
                    """
                    UPDATE meta_skill_runs
                       SET status='expired', ended_at_ms=?
                     WHERE run_id=? AND status='awaiting_user'
                    """,
                    (self._clock(), run_id),
                )
                self._conn.commit()
        except Exception as exc:  # noqa: BLE001
            log.warning("meta_run_writer.mark_expired_failed: %s", exc)

    def mark_cancelled(self, *, run_id: str, reason: str) -> None:
        """Transition an awaiting_user run to 'cancelled' with a recorded reason.

        Reason is stored in the existing `error` column (with `cancelled:`
        prefix); callers must check `status` before interpreting `error`.
        """
        try:
            with self._lock:
                self._conn.execute(
                    """
                    UPDATE meta_skill_runs
                       SET status='cancelled', ended_at_ms=?, error=?
                     WHERE run_id=? AND status='awaiting_user'
                    """,
                    (self._clock(), f"cancelled:{reason}", run_id),
                )
                self._conn.commit()
        except Exception as exc:  # noqa: BLE001
            log.warning("meta_run_writer.mark_cancelled_failed: %s", exc)

    def increment_parse_failures(self, *, run_id: str) -> int:
        """Atomically increment parse_failure_count; return new value.

        Returns 0 if the row is not in 'awaiting_user' (no-op sentinel).
        Uses UPDATE ... RETURNING for atomicity across multiple connections.
        """
        try:
            with self._lock:
                cur = self._conn.execute(
                    """
                    UPDATE meta_skill_runs
                       SET parse_failure_count = parse_failure_count + 1
                     WHERE run_id=? AND status='awaiting_user'
                     RETURNING parse_failure_count
                    """,
                    (run_id,),
                )
                row = cur.fetchone()
                if row is None:
                    self._conn.rollback()
                    return 0
                self._conn.commit()
                if isinstance(row, sqlite3.Row):
                    return int(row["parse_failure_count"])
                return int(row[0])
        except Exception as exc:  # noqa: BLE001
            log.warning("meta_run_writer.increment_parse_failures_failed: %s", exc)
            return 0

    def update_awaiting_partial(
        self, *, run_id: str, filled_json: str, awaiting_since: float,
    ) -> bool:
        """Persist a partial fill for chat-mode awaiting (design §5.4).

        Resets awaiting_since so the user gets a fresh timeout window.
        Returns True only if the row was still in awaiting_user.
        """
        try:
            with self._lock:
                cur = self._conn.execute(
                    """
                    UPDATE meta_skill_runs
                       SET awaiting_filled_json=?, awaiting_since=?
                     WHERE run_id=? AND status='awaiting_user'
                    """,
                    (filled_json, awaiting_since, run_id),
                )
                if cur.rowcount == 0:
                    self._conn.rollback()
                    return False
                self._conn.commit()
                return True
        except Exception as exc:  # noqa: BLE001
            log.warning("meta_run_writer.update_awaiting_partial_failed: %s", exc)
            return False

    # ------------- cleanup -------------

    def purge_for_session(self, session_key: str) -> int:
        try:
            with self._lock:
                cur = self._conn.execute(
                    "DELETE FROM meta_skill_runs WHERE session_key=?", (session_key,),
                )
                self._conn.commit()
                return cur.rowcount or 0
        except Exception as exc:  # noqa: BLE001
            log.warning("meta_run_writer.purge_failed: %s", exc)
            return 0

    def mark_orphans_failed(self, *, age_ms: int = 3_600_000) -> int:
        """W6: boot cleanup. Only marks rows owned by other-or-null pid AND aged."""
        current_pid = self._pid_fn()
        cutoff = self._clock() - age_ms
        try:
            with self._lock:
                cur = self._conn.execute(
                    """
                    UPDATE meta_skill_runs
                       SET status='failed', ended_at_ms=?, error='gateway restart'
                     WHERE status='running'
                       AND (owner_pid IS NULL OR owner_pid != ?)
                       AND started_at_ms < ?
                    """,
                    (self._clock(), current_pid, cutoff),
                )
                self._conn.commit()
                return cur.rowcount or 0
        except Exception as exc:  # noqa: BLE001
            log.warning("meta_run_writer.mark_orphans_failed: %s", exc)
            return 0

    # ------------- row mappers -------------

    @staticmethod
    def _row_to_run(row: sqlite3.Row, *, steps: tuple[StepRecord, ...]) -> RunRecord:
        return RunRecord(
            run_id=row["run_id"],
            meta_skill_name=row["meta_skill_name"],
            meta_skill_digest=row["meta_skill_digest"],
            plan_snapshot_json=row["plan_snapshot_json"],
            triggered_by=row["triggered_by"],
            session_key=row["session_key"],
            turn_id=row["turn_id"],
            owner_pid=row["owner_pid"],
            status=row["status"],
            started_at_ms=row["started_at_ms"],
            ended_at_ms=row["ended_at_ms"],
            inputs_json=row["inputs_json"],
            final_text=row["final_text"],
            failed_step_id=row["failed_step_id"],
            error=row["error"],
            truncated_fields=tuple(
                f for f in (row["truncated_fields"] or "").split(",") if f
            ),
            steps=steps,
        )

    @staticmethod
    def _row_to_step(row: sqlite3.Row) -> StepRecord:
        return StepRecord(
            run_id=row["run_id"],
            step_id=row["step_id"],
            step_kind=row["step_kind"],
            declared_skill=row["declared_skill"],
            effective_skill=row["effective_skill"],
            status=row["status"],
            started_at_ms=row["started_at_ms"],
            ended_at_ms=row["ended_at_ms"],
            rendered_inputs_json=row["rendered_inputs_json"],
            output_text=row["output_text"],
            error=row["error"],
            substitute_step_id=row["substitute_step_id"],
            truncated_fields=tuple(
                f for f in (row["truncated_fields"] or "").split(",") if f
            ),
        )


# ---------------------------------------------------------------------------
# Constructor with full PRAGMA contract
# ---------------------------------------------------------------------------


def open_meta_run_writer(db_path: str) -> MetaRunWriter:
    """Open writer with PRAGMA contract (C2 + W1 v2)."""
    conn = sqlite3.connect(
        db_path,
        check_same_thread=False,  # W1 — orchestrator runs us in executor threads
        isolation_level=None,     # autocommit; we still call .commit() explicitly
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return MetaRunWriter(conn)
