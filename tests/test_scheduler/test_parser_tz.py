"""IANA timezone support for cron schedules.

Covers the new ``CronJob.tz`` field + ``validate_tz`` + ``_next_run``'s
wall-time-in-tz matching, and round-trip persistence of ``tz``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from opensquilla.scheduler.jobs import _next_run
from opensquilla.scheduler.ops import SchedulerOps
from opensquilla.scheduler.parser import validate_tz
from opensquilla.scheduler.payloads import make_agent_turn_payload
from opensquilla.scheduler.persistence import JobStore
from opensquilla.scheduler.types import CronJob, ScheduleKind, SessionTarget

# --- validate_tz ---------------------------------------------------------


def test_validate_tz_accepts_empty() -> None:
    validate_tz("")


def test_validate_tz_accepts_iana_zone() -> None:
    validate_tz("America/Los_Angeles")
    validate_tz("Asia/Shanghai")
    validate_tz("UTC")


def test_validate_tz_rejects_nonsense() -> None:
    with pytest.raises(ValueError, match="Unknown timezone"):
        validate_tz("Not/A_Real_Zone")


# --- _next_run uses tz ---------------------------------------------------


def _cron_job(expr: str, tz: str = "") -> CronJob:
    return CronJob(
        id="job-1",
        cron_expr=expr,
        handler_key="agent_run",
        payload={"kind": "agent_turn", "task": "x", "agent_id": "main"},
        session_target=SessionTarget.ISOLATED,
        schedule_kind=ScheduleKind.CRON,
        schedule_raw=expr,
        tz=tz,
    )


def test_next_run_la_morning_lands_at_la_local_time() -> None:
    """0 9 * * * with tz=America/Los_Angeles must fire at 09:00 LA local."""
    from zoneinfo import ZoneInfo

    # Pick a date when LA is on PST (UTC-8): January 15, 2026.
    after = datetime(2026, 1, 15, 0, 0, tzinfo=UTC)  # 16:00 PST prev day
    job = _cron_job("0 9 * * *", tz="America/Los_Angeles")
    next_run = _next_run(job, after)
    la_local = next_run.astimezone(ZoneInfo("America/Los_Angeles"))
    assert la_local.hour == 9
    assert la_local.minute == 0
    # In PST (UTC-8) → 17:00 UTC. In PDT (UTC-7) → 16:00 UTC. Jan 15 is PST.
    assert next_run.hour == 17
    assert next_run.minute == 0


def test_next_run_la_morning_after_dst_lands_at_16_utc() -> None:
    """In PDT (April), 09:00 LA → 16:00 UTC. Confirms DST is respected."""
    from zoneinfo import ZoneInfo

    after = datetime(2026, 4, 15, 0, 0, tzinfo=UTC)
    job = _cron_job("0 9 * * *", tz="America/Los_Angeles")
    next_run = _next_run(job, after)
    la_local = next_run.astimezone(ZoneInfo("America/Los_Angeles"))
    assert la_local.hour == 9
    assert next_run.hour == 16


def test_next_run_without_tz_matches_in_utc() -> None:
    """Legacy behaviour: empty tz → UTC matching."""
    after = datetime(2026, 1, 15, 8, 30, tzinfo=UTC)
    job = _cron_job("0 9 * * *")
    next_run = _next_run(job, after)
    assert next_run.hour == 9
    assert next_run.minute == 0
    assert next_run.tzinfo == UTC


def test_next_run_with_empty_tz_matches_in_utc() -> None:
    after = datetime(2026, 1, 15, 8, 30, tzinfo=UTC)
    job = _cron_job("0 9 * * *", tz="")
    next_run = _next_run(job, after)
    assert next_run.hour == 9


# --- SchedulerOps.add accepts tz ----------------------------------------


async def test_ops_add_persists_tz(tmp_path: Path) -> None:
    db = tmp_path / "cron.db"
    store = JobStore(str(db))
    await store.open()
    try:
        ops = SchedulerOps(store)
        job = await ops.add(
            name="LA brief",
            schedule_kind=ScheduleKind.CRON,
            schedule_value="0 9 * * *",
            handler_key="agent_run",
            payload=make_agent_turn_payload("Morning briefing"),
            session_target=SessionTarget.ISOLATED,
            tz="America/Los_Angeles",
        )
        assert job.tz == "America/Los_Angeles"

        # Round-trip through the store.
        reloaded = await store.get(job.id)
        assert reloaded is not None
        assert reloaded.tz == "America/Los_Angeles"
    finally:
        await store.close()


async def test_ops_add_rejects_bad_tz(tmp_path: Path) -> None:
    db = tmp_path / "cron.db"
    store = JobStore(str(db))
    await store.open()
    try:
        ops = SchedulerOps(store)
        with pytest.raises(ValueError, match="Unknown timezone"):
            await ops.add(
                name="bad",
                schedule_kind=ScheduleKind.CRON,
                schedule_value="0 9 * * *",
                handler_key="agent_run",
                payload=make_agent_turn_payload("x"),
                session_target=SessionTarget.ISOLATED,
                tz="Mars/Olympus",
            )
    finally:
        await store.close()


async def test_ops_update_changes_tz_and_recomputes_next_run(tmp_path: Path) -> None:
    db = tmp_path / "cron.db"
    store = JobStore(str(db))
    await store.open()
    try:
        ops = SchedulerOps(store)
        job = await ops.add(
            name="briefing",
            schedule_kind=ScheduleKind.CRON,
            schedule_value="0 9 * * *",
            handler_key="agent_run",
            payload=make_agent_turn_payload("brief"),
            session_target=SessionTarget.ISOLATED,
            tz="UTC",
        )
        utc_next = job.next_run_at
        # Now patch tz to LA and reschedule.
        updated = await ops.update(
            job.id,
            tz="America/Los_Angeles",
            schedule_kind=ScheduleKind.CRON,
            schedule_value="0 9 * * *",
        )
        assert updated is not None
        assert updated.tz == "America/Los_Angeles"
        # LA next_run shifts at least 7h relative to UTC schedule.
        assert utc_next is not None
        assert updated.next_run_at is not None
        assert updated.next_run_at != utc_next
    finally:
        await store.close()


async def test_ops_update_rejects_bad_tz(tmp_path: Path) -> None:
    db = tmp_path / "cron.db"
    store = JobStore(str(db))
    await store.open()
    try:
        ops = SchedulerOps(store)
        job = await ops.add(
            name="x",
            schedule_kind=ScheduleKind.CRON,
            schedule_value="0 9 * * *",
            handler_key="agent_run",
            payload=make_agent_turn_payload("x"),
            session_target=SessionTarget.ISOLATED,
        )
        with pytest.raises(ValueError, match="Unknown timezone"):
            await ops.update(job.id, tz="Mars/Olympus")
    finally:
        await store.close()
