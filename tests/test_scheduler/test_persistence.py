from __future__ import annotations

import pytest

from opensquilla.compat import aiosqlite
from opensquilla.scheduler.persistence import JobStore
from opensquilla.scheduler.types import CronJob


@pytest.mark.asyncio
async def test_scheduler_persistence_round_trips_tool_policy(tmp_path) -> None:
    store = JobStore(str(tmp_path / "scheduler.db"))
    await store.open()
    try:
        job = CronJob(
            id="policy",
            name="Policy",
            cron_expr="*/5 * * * *",
            schedule_raw="*/5 * * * *",
            handler_key="agent_run",
            tool_policy={
                "profile": "minimal",
                "also_allow": ["memory_search"],
                "deny": ["web_fetch"],
            },
        )

        await store.save(job)
        loaded = await store.get("policy")
    finally:
        await store.close()

    assert loaded is not None
    assert loaded.tool_policy == {
        "profile": "minimal",
        "also_allow": ["memory_search"],
        "deny": ["web_fetch"],
    }


@pytest.mark.asyncio
async def test_get_handles_empty_payload_row(tmp_path) -> None:
    """An empty `payload` cell must not crash _row_to_job.

    `_normalize_legacy_jobs` already tolerates `payload=''` /
    `JSONDecodeError`; the `_row_to_job` path used by `get` / `list_active`
    / `iter_due` must do the same so a single legacy or externally-written
    row cannot wedge the whole scheduler.
    """
    db_path = tmp_path / "scheduler.db"
    store = JobStore(str(db_path))
    await store.open()
    try:
        async with aiosqlite.connect(str(db_path)) as raw_db:
            now = "2026-01-01T00:00:00+00:00"
            await raw_db.execute(
                """
                INSERT INTO scheduler_jobs
                    (id, name, cron_expr, handler_key, payload,
                     status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("legacy", "Legacy", "*/5 * * * *", "agent_run", "",
                 "pending", now, now),
            )
            await raw_db.commit()

        loaded = await store.get("legacy")
    finally:
        await store.close()

    assert loaded is not None
    assert loaded.id == "legacy"
    assert loaded.payload == {} or isinstance(loaded.payload, dict)
