"""Standard 5-field cron expression parser."""

from __future__ import annotations

import re as _re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .types import ScheduleKind


class CronParseError(ValueError):
    pass


_FIELD_RANGES = {
    "minute": (0, 59),
    "hour": (0, 23),
    "day_of_month": (1, 31),
    "month": (1, 12),
    "day_of_week": (0, 6),  # 0=Sunday
}

_MONTH_NAMES = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

_DOW_NAMES = {
    "sun": 0,
    "mon": 1,
    "tue": 2,
    "wed": 3,
    "thu": 4,
    "fri": 5,
    "sat": 6,
}

_PRESETS: dict[str, str] = {
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}


@dataclass(frozen=True)
class CronField:
    values: frozenset[int]

    def matches(self, value: int) -> bool:
        return value in self.values


@dataclass(frozen=True)
class CronExpression:
    minute: CronField
    hour: CronField
    day_of_month: CronField
    month: CronField
    day_of_week: CronField
    raw: str

    def matches(self, dt: datetime) -> bool:
        return (
            self.minute.matches(dt.minute)
            and self.hour.matches(dt.hour)
            and self.day_of_month.matches(dt.day)
            and self.month.matches(dt.month)
            and self.day_of_week.matches((dt.weekday() + 1) % 7)  # Python Mon=0 → cron Sun=0
        )


def _parse_field(token: str, field_name: str, names: dict[str, int] | None = None) -> CronField:
    lo, hi = _FIELD_RANGES[field_name]
    values: set[int] = set()

    for part in token.split(","):
        part = part.strip()
        if names:
            # resolve names in ranges and steps too
            sub_parts = part.replace("/", "§").replace("-", "¶")
            for name, val in names.items():
                sub_parts = sub_parts.replace(name.lower(), str(val))
                sub_parts = sub_parts.replace(name.upper(), str(val))
            part = sub_parts.replace("§", "/").replace("¶", "-")

        if "/" in part:
            range_part, step_str = part.split("/", 1)
            try:
                step = int(step_str)
            except ValueError:
                raise CronParseError(f"Invalid step '{step_str}' in field '{field_name}'")
            if step <= 0:
                raise CronParseError(f"Step must be > 0 in field '{field_name}'")

            if range_part == "*":
                start, end = lo, hi
            elif "-" in range_part:
                start_str, end_str = range_part.split("-", 1)
                start = _to_int(start_str, field_name, lo, hi)
                end = _to_int(end_str, field_name, lo, hi)
            else:
                start = _to_int(range_part, field_name, lo, hi)
                end = hi

            values.update(range(start, end + 1, step))

        elif "-" in part:
            start_str, end_str = part.split("-", 1)
            start = _to_int(start_str, field_name, lo, hi)
            end = _to_int(end_str, field_name, lo, hi)
            if start > end:
                raise CronParseError(f"Range start > end in field '{field_name}'")
            values.update(range(start, end + 1))

        elif part == "*":
            values.update(range(lo, hi + 1))

        else:
            values.add(_to_int(part, field_name, lo, hi))

    return CronField(frozenset(values))


def _to_int(s: str, field_name: str, lo: int, hi: int) -> int:
    try:
        v = int(s)
    except ValueError:
        raise CronParseError(f"Invalid value '{s}' in field '{field_name}'")
    if not (lo <= v <= hi):
        raise CronParseError(f"Value {v} out of range [{lo}, {hi}] for field '{field_name}'")
    return v


_EVERY_RE = _re.compile(r"^every\s+(\d+)\s*(m|min|h|hr|d|day)s?$", _re.IGNORECASE)
_RELATIVE_RE = _re.compile(r"^(\d+)\s*(m|min|h|hr|d|day)s?$", _re.IGNORECASE)
_UNIT_SECONDS = {"m": 60, "min": 60, "h": 3600, "hr": 3600, "d": 86400, "day": 86400}
_ZH_EVERY_MINUTE_RE = _re.compile(r"^每\s*(?:(\d+)\s*)?分钟$")
_ZH_RELATIVE_MINUTE_RE = _re.compile(r"^(\d+)\s*分钟后$")
_ZH_DAILY_HOUR_RE = _re.compile(r"^每天\s*(\d{1,2})\s*点$")
_ZH_DAILY_TIME_RE = _re.compile(r"^每天\s*(\d{1,2})\s*[:：]\s*(\d{1,2})$")


def _reference_now(reference_now: datetime | None) -> datetime:
    if reference_now is None:
        return datetime.now().astimezone()
    if reference_now.tzinfo is None:
        raise CronParseError("reference_now must be timezone-aware")
    return reference_now


def _parse_chinese_schedule(raw: str, reference_now: datetime) -> tuple[ScheduleKind, str] | None:
    m = _ZH_EVERY_MINUTE_RE.match(raw)
    if m:
        amount = int(m.group(1) or "1")
        if amount <= 0:
            raise CronParseError("Minute interval must be > 0")
        if 60 % amount == 0:
            return ScheduleKind.EVERY, f"*/{amount} * * * *"
        return ScheduleKind.EVERY, str(amount * 60)

    m = _ZH_RELATIVE_MINUTE_RE.match(raw)
    if m:
        amount = int(m.group(1))
        if amount <= 0:
            raise CronParseError("Relative minute delay must be > 0")
        target = reference_now.astimezone(UTC) + timedelta(minutes=amount)
        return ScheduleKind.AT, target.isoformat()

    m = _ZH_DAILY_HOUR_RE.match(raw)
    if m:
        hour = int(m.group(1))
        minute = 0
    else:
        m = _ZH_DAILY_TIME_RE.match(raw)
        if not m:
            return None
        hour = int(m.group(1))
        minute = int(m.group(2))

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise CronParseError("Daily time out of range")
    local_wall_time = reference_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    utc_wall_time = local_wall_time.astimezone(UTC)
    return ScheduleKind.CRON, f"{utc_wall_time.minute} {utc_wall_time.hour} * * *"


def parse_schedule(
    raw: str,
    *,
    reference_now: datetime | None = None,
) -> tuple[ScheduleKind, str]:
    """Parse user input into (kind, normalized_expression)."""
    raw = raw.strip()
    now = _reference_now(reference_now)

    chinese = _parse_chinese_schedule(raw, now)
    if chinese is not None:
        return chinese

    # 1. "every Nm/Nh"
    m = _EVERY_RE.match(raw)
    if m:
        amount = int(m.group(1))
        if amount <= 0:
            raise CronParseError("Interval amount must be > 0")
        unit = m.group(2).lower()
        if unit in ("m", "min"):
            if 60 % amount == 0:
                return ScheduleKind.EVERY, f"*/{amount} * * * *"
            else:
                return ScheduleKind.EVERY, str(amount * 60)
        elif unit in ("h", "hr"):
            if 24 % amount == 0:
                return ScheduleKind.EVERY, f"0 */{amount} * * *"
            else:
                return ScheduleKind.EVERY, str(amount * 3600)
        elif unit in ("d", "day"):
            return ScheduleKind.EVERY, str(amount * 86400)

    # 2. Relative delay "30m"
    m = _RELATIVE_RE.match(raw)
    if m:
        amount = int(m.group(1))
        if amount <= 0:
            raise CronParseError("Relative delay must be > 0")
        unit = m.group(2).lower()
        secs = amount * _UNIT_SECONDS.get(unit, 60)
        target = now.astimezone(UTC) + timedelta(seconds=secs)
        return ScheduleKind.AT, target.isoformat()

    # 3. ISO-8601
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return ScheduleKind.AT, dt.isoformat()
    except ValueError:
        pass

    # 4. @preset
    if raw.startswith("@"):
        if raw not in _PRESETS:
            raise ValueError(f"Unknown preset: {raw}")
        return ScheduleKind.CRON, _PRESETS[raw]

    # 5. Standard cron
    fields = raw.split()
    if len(fields) == 5:
        parse_cron(raw)  # validate
        return ScheduleKind.CRON, raw

    raise ValueError(f"Cannot parse schedule: {raw!r}")


def parse_cron(expr: str) -> CronExpression:
    """Parse a standard 5-field cron expression or @preset shorthand."""
    expr = expr.strip()

    # Handle @presets
    if expr.startswith("@"):
        if expr not in _PRESETS:
            raise CronParseError(f"Unknown preset '{expr}'")
        expr = _PRESETS[expr]

    fields = expr.split()
    if len(fields) != 5:
        raise CronParseError(f"Expected 5 fields, got {len(fields)}: '{expr}'")

    minute_tok, hour_tok, dom_tok, month_tok, dow_tok = fields

    return CronExpression(
        minute=_parse_field(minute_tok, "minute"),
        hour=_parse_field(hour_tok, "hour"),
        day_of_month=_parse_field(dom_tok, "day_of_month"),
        month=_parse_field(month_tok, "month", _MONTH_NAMES),
        day_of_week=_parse_field(dow_tok, "day_of_week", _DOW_NAMES),
        raw=expr,
    )
