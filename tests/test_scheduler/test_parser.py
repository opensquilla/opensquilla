from __future__ import annotations

from datetime import UTC, datetime

import pytest

from opensquilla.scheduler.parser import CronParseError, parse_schedule
from opensquilla.scheduler.types import ScheduleKind


@pytest.mark.parametrize("raw", ["every 0m", "every 0h", "every 0d"])
def test_parse_schedule_rejects_zero_every_interval(raw: str) -> None:
    with pytest.raises(CronParseError, match=r"> 0"):
        parse_schedule(raw)


@pytest.mark.parametrize("raw", ["0m", "0h", "0d"])
def test_parse_schedule_rejects_zero_relative_delay(raw: str) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)

    with pytest.raises(CronParseError, match=r"> 0"):
        parse_schedule(raw, reference_now=now)


def test_parse_schedule_accepts_positive_every_interval() -> None:
    assert parse_schedule("every 5m") == (ScheduleKind.EVERY, "*/5 * * * *")
