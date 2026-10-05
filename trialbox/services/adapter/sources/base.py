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


def after(value: Any, since: str | None) -> bool:
    """Lexicographic ISO comparison (``YYYY-MM-DD[ HH:MM:SS]``) used for delta extraction."""
    if since is None:
        return True
    return value is not None and str(value)[:19].replace("T", " ") >= since[:19].replace("T", " ")
