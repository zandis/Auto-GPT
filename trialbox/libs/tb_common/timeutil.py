"""Time helpers. All timestamps are ISO-8601 with offset in the hospital zone (SPEC §1 conventions)."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


def now(tz: str = "Asia/Taipei") -> datetime:
    return datetime.now(ZoneInfo(tz))


def today(tz: str = "Asia/Taipei") -> date:
    return now(tz).date()


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("naive datetime")
    return dt.isoformat(timespec="seconds")


def month_end(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def month_ends(run_date: date, lookback_months: int) -> list[date]:
    """The last ``lookback_months`` complete month-ends strictly before ``run_date``'s month, ascending."""
    first_of_month = run_date.replace(day=1)
    last = first_of_month - timedelta(days=1)
    out = [month_end(add_months(last, -i)) for i in range(lookback_months)]
    return sorted(out)


def quarter_of(d: date) -> str:
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def quarter_end(d: date) -> date:
    q_last_month = ((d.month - 1) // 3 + 1) * 3
    return month_end(date(d.year, q_last_month, 1))


def previous_quarter_end(d: date) -> date:
    q_first = date(d.year, ((d.month - 1) // 3) * 3 + 1, 1)
    return q_first - timedelta(days=1)


def parse_date(value: str) -> date:
    return date.fromisoformat(value[:10])
