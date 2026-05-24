"""V011 - relax meta_skill_runs.triggered_by CHECK to accept auto_* values.

V010 originally restricted ``triggered_by`` to
``('hard_takeover','soft_meta_invoke')``. Auto-trigger paths (cron
+ dream-loop hook) need to record runs as ``'auto_cron'`` or
``'auto_dream'`` so the WebUI proposals panel and ``opensquilla skills
meta runs`` CLI can distinguish unattended synthesis from user-driven
invocations.

SQLite cannot ``ALTER`` a CHECK constraint in place. We follow the
SQLite-recommended recipe
(https://www.sqlite.org/lang_altertable.html section 7) which avoids
breaking the child-table foreign-key references that point at
``meta_skill_runs``:

1. PRAGMA foreign_keys = OFF
2. CREATE TABLE meta_skill_runs__new with the relaxed CHECK
3. INSERT INTO meta_skill_runs__new SELECT * FROM meta_skill_runs
4. DROP TABLE meta_skill_runs
5. ALTER TABLE meta_skill_runs__new RENAME TO meta_skill_runs
6. recreate indexes
7. PRAGMA foreign_key_check (verify no orphans introduced)
8. PRAGMA foreign_keys = ON

Renaming the NEW table (step 5) is safe; renaming the OLD table is
what corrupts child FK refs and was the original bug.

Rollback restores the original (stricter) CHECK; rows whose
``triggered_by`` already contains ``auto_*`` would block the rollback
copy step, which is the correct safety behavior — operators who
roll back must first purge auto-triggered runs they no longer want.
"""

from __future__ import annotations

from yoyo import step

__depends__: set[str] = {"V010__meta_skill_runs"}


_NEW_TRIGGERED_BY_VALUES = (
    "'hard_takeover'",
    "'soft_meta_invoke'",
    "'auto_cron'",
    "'auto_dream'",
)
_OLD_TRIGGERED_BY_VALUES = (
    "'hard_takeover'",
    "'soft_meta_invoke'",
)


def _create_table_sql(
    triggered_by_values: tuple[str, ...],
    table_name: str = "meta_skill_runs",
) -> str:
    return f"""
    CREATE TABLE {table_name} (
        run_id              TEXT PRIMARY KEY,
        meta_skill_name     TEXT NOT NULL,
        meta_skill_digest   TEXT NOT NULL,
        plan_snapshot_json  TEXT NOT NULL,
        triggered_by        TEXT NOT NULL
                              CHECK(triggered_by IN ({", ".join(triggered_by_values)})),
        session_key         TEXT,
        turn_id             TEXT,
        owner_pid           INTEGER,
        status              TEXT NOT NULL
                              CHECK(status IN ('running','ok','failed','cancelled')),
        started_at_ms       INTEGER NOT NULL,
        ended_at_ms         INTEGER,
        inputs_json         TEXT NOT NULL,
        final_text          TEXT,
        failed_step_id      TEXT,
        error               TEXT,
        truncated_fields    TEXT NOT NULL DEFAULT ''
    )
    """


_INDEXES = [
    "CREATE INDEX idx_meta_runs_name_started"
    " ON meta_skill_runs(meta_skill_name, started_at_ms DESC)",
    "CREATE INDEX idx_meta_runs_status_started"
    " ON meta_skill_runs(status, started_at_ms DESC)",
    "CREATE INDEX idx_meta_runs_session"
    " ON meta_skill_runs(session_key, started_at_ms DESC)",
    "CREATE INDEX idx_meta_runs_started"
    " ON meta_skill_runs(started_at_ms DESC)",
]


def _table_exists(conn, table: str) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return cur.fetchone() is not None


def _recreate_runs_table(conn, triggered_by_values: tuple[str, ...]) -> None:
    """Follow SQLite's recommended recreate procedure (section 7 of
    lang_altertable.html). Build the NEW table under a temporary name,
    copy rows, drop the OLD table, then rename NEW to the canonical
    name. This order keeps child-table FK references intact — renaming
    the OLD table first would orphan them."""
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = OFF")
    try:
        cur.execute(_create_table_sql(triggered_by_values, "meta_skill_runs__new"))
        cur.execute(
            "INSERT INTO meta_skill_runs__new SELECT * FROM meta_skill_runs"
        )
        cur.execute("DROP TABLE meta_skill_runs")
        cur.execute("ALTER TABLE meta_skill_runs__new RENAME TO meta_skill_runs")
        for ddl in _INDEXES:
            cur.execute(ddl)
        # Defensive: catch any orphan child rows the recreate would have
        # introduced. If this fails, the surrounding transaction rolls
        # back and the migration aborts cleanly.
        cur.execute("PRAGMA foreign_key_check")
        bad = cur.fetchall()
        if bad:
            raise RuntimeError(
                f"V011 foreign_key_check found orphans after recreate: {bad}"
            )
    finally:
        cur.execute("PRAGMA foreign_keys = ON")


def apply_step(conn) -> None:
    if not _table_exists(conn, "meta_skill_runs"):
        # V010 hasn't been applied — nothing to relax. yoyo's __depends__
        # should prevent this, but be defensive against manual rollbacks.
        return
    _recreate_runs_table(conn, _NEW_TRIGGERED_BY_VALUES)


def rollback_step(conn) -> None:
    if not _table_exists(conn, "meta_skill_runs"):
        return
    _recreate_runs_table(conn, _OLD_TRIGGERED_BY_VALUES)


steps = [step(apply_step, rollback_step)]
