"""10E-9 (plan 10, Track E; review 13-10): how long each connector takes per message, for the ingest report.

A message is what a connector hands the night one at a time: a CSV or SQL row, an SS-MIX2 message, a FHIR resource.
:meth:`ReadTimes.timed` wraps a connector's iterator and times only the step that produces each message (reading and
parsing), never the mapping that runs after it. Per table it keeps a count, the total seconds and a histogram on
fixed buckets, so the memory is the same for ten messages and ten million; the 95th percentile is read from the
histogram as the upper bound of the bucket the 95th-percentile message falls in (never an under-statement); above the
last bound it is ``None`` and the histogram's last bucket shows it. Counts and times only: no value of a row is kept.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterable, Iterator
from typing import Any, TypeVar

T = TypeVar("T")

#: the buckets' upper bounds, in milliseconds per message; a slower message goes in the last bucket (``>2500``)
BOUNDS_MS: tuple[float, ...] = (0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 25, 50, 100, 250, 500, 1000, 2500)
LABELS: tuple[str, ...] = (*(f"<={b:g}" for b in BOUNDS_MS), f">{BOUNDS_MS[-1]:g}")
PERCENTILE = 0.95


class _Table:
    __slots__ = ("counts", "seconds")

    def __init__(self) -> None:
        self.counts = [0] * len(LABELS)
        self.seconds = 0.0

    def add(self, seconds: float) -> None:
        self.seconds += seconds
        ms = seconds * 1000
        self.counts[next((i for i, b in enumerate(BOUNDS_MS) if ms <= b), len(BOUNDS_MS))] += 1


def _summary(counts: list[int], seconds: float) -> dict[str, Any]:
    n = sum(counts)
    p95: float | None = None
    if n:
        need, seen = math.ceil(PERCENTILE * n), 0
        for i, c in enumerate(counts):
            seen += c
            if seen >= need:
                p95 = BOUNDS_MS[i] if i < len(BOUNDS_MS) else math.inf
                break
    return {"messages": n, "seconds": round(seconds, 6), "p95_ms": None if p95 is None or math.isinf(p95) else p95,
            "histogram": dict(zip(LABELS, counts, strict=True))}  # fmt: skip


class ReadTimes:
    """The night's read times, per table of one connector."""

    def __init__(self, clock: Callable[[], float] = time.perf_counter) -> None:
        self._clock = clock
        self._tables: dict[str, _Table] = {}

    def timed(self, table: str | Callable[[T], str], rows: Iterable[T]) -> Iterator[T]:
        """``rows`` as they come, each timed from the request to the connector's answer. ``table`` names the table,
        or reads it from each message (a FHIR file's resource type)."""
        if isinstance(table, str):
            self._tables.setdefault(table, _Table())
        it = iter(rows)
        while True:
            start = self._clock()
            try:
                row = next(it)
            except StopIteration:
                return
            name = table if isinstance(table, str) else table(row)
            self._tables.setdefault(name, _Table()).add(self._clock() - start)
            yield row

    def summary(self, kind: str) -> dict[str, Any]:
        """The report's ``connector`` section: the source kind, the whole and each table."""
        tables = {name: _summary(t.counts, t.seconds) for name, t in sorted(self._tables.items())}
        whole = [sum(t.counts[i] for t in self._tables.values()) for i in range(len(LABELS))]
        return {"kind": kind, **_summary(whole, sum(t.seconds for t in self._tables.values())), "tables": tables}
