"""Source readers: each yields plain dict rows per logical table (see mapping YAML ``tables``)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any, Protocol

Row = dict[str, Any]


class Source(Protocol):
    name: str

    def rows(self, table: str, source_name: str, delta_column: str | None, since: str | None) -> Iterator[Row]:
        """Rows of ``source_name``; when ``since`` is set and ``delta_column`` exists, only rows changed since."""
        ...


def has_table(source: object, source_name: str) -> bool | None:
    """Whether ``source`` holds ``source_name`` at all (T-611), or None when the reader cannot tell (a SQL view or an
    SS-MIX2 tree is never "missing"; its row count decides)."""
    fn = getattr(source, "has_table", None)
    return bool(fn(source_name)) if callable(fn) else None


# T-615b (DATA-008): the canonical columns a ``delta:`` may name on a csv or cgrd_sql source. A clinical date (a lab's
# sample time, a diagnosis' record date) is not one: a corrected or late-entered record keeps its old date, and a
# delta on that date never picks the change up
CHANGE_COLUMNS: tuple[str, ...] = ("updated_at",)


def quarantine_reason(source: object, source_name: str) -> str | None:
    """Why ``source`` quarantined ``source_name`` on this read (T-615b), or None. An SS-MIX2 source's extended storage
    is a csv source too."""
    for s in (source, getattr(source, "extended", None)):
        fn = getattr(s, "quarantine_reason", None)
        if callable(fn) and (why := fn(source_name)):
            return str(why)
    return None


# F14 (D-810): a change time that is a date: a four-digit year, month and day with dashes or slashes (a time and an
# offset may follow), or 8, 12 or 14 digits
_CHANGE_DATED = re.compile(r"(\d{4})[-/](\d{2})[-/](\d{2})(?:[ T](\d{2}):?(\d{2})(?::?(\d{2}))?.*)?")
_CHANGE_COMPACT = re.compile(r"(\d{4})(\d{2})(\d{2})(?:(\d{2})(\d{2})(\d{2})?)?")


def _change_key(value: Any) -> str | None:
    """``YYYY-MM-DD HH:MM:SS`` of a change time that is a date, else None."""
    text = "" if value is None else str(value).strip()
    m = _CHANGE_DATED.fullmatch(text) or _CHANGE_COMPACT.fullmatch(text)
    if m is None:
        return None
    y, mo, d, h, mi, sec = m.groups()
    if not (1 <= int(mo) <= 12 and 1 <= int(d) <= 31):
        return None
    return f"{y}-{mo}-{d} {h or '00'}:{mi or '00'}:{sec or '00'}"


def change_time_is_date(value: Any) -> bool:
    """Whether a change time is a date (F14, D-810); a placeholder, a year alone or another order is not."""
    return _change_key(value) is not None


def after(value: Any, since: str | None) -> bool:
    """Whether a change time is at or after ``since`` (delta extraction). Both are compared as dates when they are
    (F14: a compact ``20260930`` is a day before ``2026-10-01``, not after it as text); otherwise as text, as before."""
    if since is None:
        return True
    if value is None:
        return False
    mine, theirs = _change_key(value), _change_key(since)
    if mine is not None and theirs is not None:
        return mine >= theirs
    return str(value)[:19].replace("T", " ") >= since[:19].replace("T", " ")
