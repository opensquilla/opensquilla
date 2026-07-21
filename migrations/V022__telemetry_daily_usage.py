"""V022 - content-free daily usage aggregates governed by the privacy switch."""

from __future__ import annotations

from yoyo import step

# This special release line starts at v0.5.0rc4, whose migration tip is V019.
# Keep the V022 ID so a later upgrade to main recognizes the same migration.
__depends__: set[str] = {"V019__turn_errors"}

CREATE_TELEMETRY_DAILY_USAGE = """
CREATE TABLE telemetry_daily_usage (
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


def _table_exists(conn, table: str) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return cur.fetchone() is not None


def apply_step(conn) -> None:
    if not _table_exists(conn, "telemetry_daily_usage"):
        conn.cursor().execute(CREATE_TELEMETRY_DAILY_USAGE)


def rollback_step(conn) -> None:
    conn.cursor().execute("DROP TABLE IF EXISTS telemetry_daily_usage")


steps = [step(apply_step, rollback_step)]
