from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from opensquilla.scheduler.persistence import JobStore
from opensquilla.scheduler.types import CronJob, JobReservation, ScheduleKind


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
async def test_due_checks_treat_offset_timestamps_as_absolute_time(tmp_path) -> None:
    store = JobStore(str(tmp_path / "scheduler.db"))
    await store.open()
    try:
        job = CronJob(
            id="offset-at",
            name="Offset AT",
            cron_expr="2026-05-25T16:15:00+08:00",
            schedule_kind=ScheduleKind.AT,
            schedule_raw="2026-05-25T16:15:00+08:00",
            handler_key="static_message",
            next_run_at=datetime.fromisoformat("2026-05-25T16:15:00+08:00"),
            delete_after_run=True,
        )
        await store.save(job)

        now = datetime.fromisoformat("2026-05-25T08:19:31+00:00")
        due_jobs = [due_job async for due_job in store.iter_due(now)]
        reservation = await store.reserve_due_job("offset-at", now)
    finally:
        await store.close()

    assert [due_job.id for due_job in due_jobs] == ["offset-at"]
    assert isinstance(reservation, JobReservation)
    assert reservation.job.id == "offset-at"


@pytest.mark.asyncio
async def test_open_normalizes_existing_offset_timestamps_for_due_checks(tmp_path) -> None:
    db_path = tmp_path / "scheduler.db"
    store = JobStore(str(db_path))
    await store.open()
    await store.close()

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO scheduler_jobs
                (id, name, cron_expr, handler_key, created_at, updated_at,
                 next_run_at, schedule_kind, schedule_raw, delete_after_run)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-offset-at",
                "Legacy Offset AT",
                "2026-05-25T16:15:00+08:00",
                "static_message",
                "2026-05-25T08:12:36.504054+00:00",
                "2026-05-25T08:12:36.508732+00:00",
                "2026-05-25T16:15:00+08:00",
                "at",
                "2026-05-25T16:15:00+08:00",
                1,
            ),
        )

    store = JobStore(str(db_path))
    await store.open()
    try:
        now = datetime.fromisoformat("2026-05-25T08:19:31+00:00")
        loaded = await store.get("legacy-offset-at")
        due_jobs = [due_job async for due_job in store.iter_due(now)]
    finally:
        await store.close()

    assert loaded is not None
    assert loaded.next_run_at == datetime.fromisoformat("2026-05-25T08:15:00+00:00")
    assert [due_job.id for due_job in due_jobs] == ["legacy-offset-at"]
