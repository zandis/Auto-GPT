"""Source readers: each yields plain dict rows per logical table (see mapping YAML ``tables``)."""

from __future__ import annotations

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


def after(value: Any, since: str | None) -> bool:
    """Lexicographic ISO comparison (``YYYY-MM-DD[ HH:MM:SS]``) used for delta extraction."""
    if since is None:
        return True
    return value is not None and str(value)[:19].replace("T", " ") >= since[:19].replace("T", " ")
