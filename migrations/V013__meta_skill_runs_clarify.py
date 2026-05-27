"""V013 — widen meta_skill_runs.status CHECK and add clarify-state columns.

V010 created meta_skill_runs with a narrow status CHECK constraint
(running / ok / failed / cancelled). PR2 of the user_input design adds
two new statuses (awaiting_user / expired) plus six nullable
clarify-state columns, plus one partial unique index on session_key to
guarantee at most one awaiting row per session.

SQLite cannot widen a CHECK constraint in place, so we follow the
recreate-and-copy pattern from V012.
"""

from __future__ import annotations

from yoyo import step

__depends__: set[str] = {"V012__meta_skill_run_steps_allow_llm_chat"}

_NEW_STATUS_VALUES = (
    "'running'", "'ok'", "'failed'", "'cancelled'",
    "'awaiting_user'", "'expired'",
)
_OLD_STATUS_VALUES = (
    "'running'", "'ok'", "'failed'", "'cancelled'",
)


def _new_table_sql(status_values: tuple[str, ...]) -> str:
    return f"""
    CREATE TABLE meta_skill_runs__new (
        run_id                 TEXT PRIMARY KEY,
        meta_skill_name        TEXT NOT NULL,
        meta_skill_digest      TEXT NOT NULL,
        plan_snapshot_json     TEXT NOT NULL,
        triggered_by           TEXT NOT NULL
                                 CHECK(triggered_by IN (
                                     'hard_takeover','soft_meta_invoke',
                                     'auto_cron','auto_dream'
                                 )),
        session_key            TEXT,
        turn_id                TEXT,
        owner_pid              INTEGER,
        status                 TEXT NOT NULL
                                 CHECK(status IN ({", ".join(status_values)})),
        started_at_ms          INTEGER NOT NULL,
        ended_at_ms            INTEGER,
        inputs_json            TEXT NOT NULL,
        final_text             TEXT,
        failed_step_id         TEXT,
        error                  TEXT,
        truncated_fields       TEXT NOT NULL DEFAULT '',
        awaiting_step_id       TEXT,
        awaiting_schema_json   TEXT,
        awaiting_since         REAL,
        awaiting_filled_json   TEXT,
        step_outputs_json      TEXT,
        parse_failure_count    INTEGER NOT NULL DEFAULT 0
    )
    """


_OLD_TABLE_SQL = f"""
CREATE TABLE meta_skill_runs__old (
    run_id              TEXT PRIMARY KEY,
    meta_skill_name     TEXT NOT NULL,
    meta_skill_digest   TEXT NOT NULL,
    plan_snapshot_json  TEXT NOT NULL,
    triggered_by        TEXT NOT NULL
                          CHECK(triggered_by IN (
                              'hard_takeover','soft_meta_invoke',
                              'auto_cron','auto_dream'
                          )),
    session_key         TEXT,
    turn_id             TEXT,
    owner_pid           INTEGER,
    status              TEXT NOT NULL
                          CHECK(status IN ({", ".join(_OLD_STATUS_VALUES)})),
    started_at_ms       INTEGER NOT NULL,
    ended_at_ms         INTEGER,
    inputs_json         TEXT NOT NULL,
    final_text          TEXT,
    failed_step_id      TEXT,
    error               TEXT,
    truncated_fields    TEXT NOT NULL DEFAULT ''
)
"""


_COPY_FORWARD_SQL = """
INSERT INTO meta_skill_runs__new (
    run_id, meta_skill_name, meta_skill_digest, plan_snapshot_json,
    triggered_by, session_key, turn_id, owner_pid, status,
    started_at_ms, ended_at_ms, inputs_json, final_text,
    failed_step_id, error, truncated_fields
)
SELECT
    run_id, meta_skill_name, meta_skill_digest, plan_snapshot_json,
    triggered_by, session_key, turn_id, owner_pid, status,
    started_at_ms, ended_at_ms, inputs_json, final_text,
    failed_step_id, error, truncated_fields
FROM meta_skill_runs
"""


_COPY_BACK_SQL = """
INSERT INTO meta_skill_runs__old SELECT
    run_id, meta_skill_name, meta_skill_digest, plan_snapshot_json,
    triggered_by, session_key, turn_id, owner_pid, status,
    started_at_ms, ended_at_ms, inputs_json, final_text,
    failed_step_id, error, truncated_fields
FROM meta_skill_runs
"""


def _table_exists(conn, table: str) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return cur.fetchone() is not None


_PRE_EXISTING_INDEXES = [
    "CREATE INDEX idx_meta_runs_name_started "
    "ON meta_skill_runs(meta_skill_name, started_at_ms DESC)",
    "CREATE INDEX idx_meta_runs_status_started "
    "ON meta_skill_runs(status, started_at_ms DESC)",
    "CREATE INDEX idx_meta_runs_session "
    "ON meta_skill_runs(session_key, started_at_ms DESC)",
    "CREATE INDEX idx_meta_runs_started "
    "ON meta_skill_runs(started_at_ms DESC)",
]


def apply_step(conn) -> None:
    if not _table_exists(conn, "meta_skill_runs"):
        return
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = OFF")
    try:
        cur.execute(_new_table_sql(_NEW_STATUS_VALUES))
        cur.execute(_COPY_FORWARD_SQL)
        cur.execute("DROP TABLE meta_skill_runs")
        cur.execute("ALTER TABLE meta_skill_runs__new RENAME TO meta_skill_runs")
        for idx_sql in _PRE_EXISTING_INDEXES:
            cur.execute(idx_sql)
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_one_awaiting_per_session "
            "ON meta_skill_runs(session_key) "
            "WHERE status = 'awaiting_user'"
        )
        cur.execute("PRAGMA foreign_key_check")
        bad = cur.fetchall()
        if bad:
            raise RuntimeError(
                f"V013 foreign_key_check found orphans after recreate: {bad}"
            )
    finally:
        cur.execute("PRAGMA foreign_keys = ON")


def rollback_step(conn) -> None:
    if not _table_exists(conn, "meta_skill_runs"):
        return
    cur = conn.cursor()
    cur.execute("DROP INDEX IF EXISTS uq_one_awaiting_per_session")
    cur.execute(
        "SELECT COUNT(*) FROM meta_skill_runs "
        "WHERE status IN ('awaiting_user','expired')"
    )
    leftover = cur.fetchone()[0]
    if leftover:
        raise RuntimeError(
            f"V013 rollback blocked: {leftover} rows in "
            f"awaiting_user/expired must be transitioned to a legacy status "
            f"(cancelled/ok/failed) first.",
        )
    cur.execute("PRAGMA foreign_keys = OFF")
    try:
        cur.execute(_OLD_TABLE_SQL)
        cur.execute(_COPY_BACK_SQL)
        cur.execute("DROP TABLE meta_skill_runs")
        cur.execute("ALTER TABLE meta_skill_runs__old RENAME TO meta_skill_runs")
        for idx_sql in _PRE_EXISTING_INDEXES:
            cur.execute(idx_sql)
        cur.execute("PRAGMA foreign_key_check")
    finally:
        cur.execute("PRAGMA foreign_keys = ON")


steps = [step(apply_step, rollback_step)]
