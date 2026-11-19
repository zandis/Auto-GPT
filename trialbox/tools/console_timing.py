"""The console's ten-page timing walk (D-1245, card 10E-13, review 13 item 13-14): p95 server time under 300 ms.

Each page of the walk is asked for ``WARMUP`` times (not counted), then ``REPEAT`` times; each answer's time is the
console's own, read from its ``Server-Timing`` header (``console.timing``), never a client's clock. A page fails when
an answer is not a ``200`` with the header, or when the 95th percentile (nearest rank) of its times exceeds the
budget. A page over the budget is walked once more, whole, and fails only when the second walk is over the budget too.

How the numbers were chosen (a loaded CI runner; the decision has the reasoning):

* **The header, not the client.** On a runner, the time between the test client and the console's outermost
  middleware (the client's own work, the event loop's queue, a neighbour's CPU) is not the page's; the header holds
  only the console's time for the request.
* **Warm-up 10.** The first answers of a page compile its templates and fill the console's per-process caches (the
  rule sets, the catalogue); a box serves pages warm for hours, so the walk measures them warm. Measured on the test
  box (2026-11-19): the first answer of a page took 6 to 91 ms against 3 to 12 ms for the later ones (up to ten
  times); from the second answer on they were as the rest. Ten leaves room for a page whose caches fill later.
* **Repeat 60.** The p95 by nearest rank of 60 times is the 57th: three slow answers per page (a garbage collection,
  a runner's burst) are absorbed; a fourth fails it (the same probe saw one answer of 83 ms among a job page's 4 ms
  ones). Ten pages, 70 answers each: about 12 seconds on the test box.
* **Once more when over.** A runner's burst lasts seconds and passes; a slow page is slow again. Only a page over the
  budget twice fails; a page that is slow every time (the planted page) fails at once on both.

What a pass proves, and what it does not: on a synthetic box (the console with its in-memory stand-in orchestrator,
synthetic studies and patients, no model, no real data volume), each of the ten pages answers in under 300 ms of the
console's own time at the 95th percentile. It says nothing about the orchestrator's or the lake's time on a real
box (the stand-in answers at once), nothing at 50,000 patients (the stand-in holds a handful), nothing about the
network or the browser. It catches a page whose own work (rendering, the console's reads and their loops) got slow.

    TB_CONSOLE_TIMING_OUT=out/ pytest tests/perf/test_console_timing_walk.py -m perf   # the walk itself
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BUDGET_MS = 300.0
WARMUP = 10
REPEAT = 60
HEADER = "server-timing"

#: one answer: (status code, headers)
Answer = tuple[int, Mapping[str, str]]


@dataclass(frozen=True)
class Page:
    """One page of the walk: its name in the report, its path, and how to ask for it (the account that opens it)."""

    name: str
    path: str
    get: Callable[[str], Answer]


@dataclass
class Timing:
    """One page's walk: its times in milliseconds (the measured answers only), or why it could not be timed."""

    name: str
    path: str
    times: list[float] = field(default_factory=list)
    broken: str = ""  # an answer that was not a timed page: "status 403", "no Server-Timing header"
    again: list[float] | None = None  # the second walk, when the first was over the budget

    def p(self, q: float, times: Sequence[float] | None = None) -> float:
        return percentile(self.times if times is None else times, q)

    def over(self, budget_ms: float) -> bool:
        if self.broken:
            return True
        first = self.p(95) > budget_ms
        return first and (self.again is None or self.p(95, self.again) > budget_ms)


def percentile(times: Sequence[float], q: float) -> float:
    """The ``q``-th percentile by nearest rank: the smallest time with at least ``q`` % of the times at or below it."""
    if not times:
        return math.inf
    ordered = sorted(times)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[rank - 1]


def server_ms(headers: Mapping[str, str]) -> float | None:
    """The console's time from its ``Server-Timing`` header (``total;dur=12.3``), or None when it has none."""
    raw = headers.get(HEADER) or headers.get("Server-Timing") or ""
    for part in raw.split(","):
        name, _, rest = part.strip().partition(";")
        if name != "total":
            continue
        for param in rest.split(";"):
            key, _, val = param.strip().partition("=")
            if key == "dur":
                try:
                    ms = float(val)
                except ValueError:
                    return None
                return ms if math.isfinite(ms) and ms >= 0 else None  # nan, inf or a negative time is no time
    return None


def measure(page: Page, warmup: int = WARMUP, repeat: int = REPEAT) -> tuple[list[float], str]:
    """``repeat`` server times of ``page`` after ``warmup`` answers; the first answer that is not a timed ``200``
    ends it with its reason."""
    times: list[float] = []
    for i in range(warmup + repeat):
        status, headers = page.get(page.path)
        if status != 200:
            return times, f"status {status}"
        ms = server_ms(headers)
        if ms is None:
            return times, "no Server-Timing header"
        if i >= warmup:
            times.append(ms)
    return times, ""


def walk(pages: Sequence[Page], *, warmup: int = WARMUP, repeat: int = REPEAT,
         budget_ms: float = BUDGET_MS) -> Report:  # fmt: skip
    """Each page timed; a page over the budget timed once more (see the module's text)."""
    out: list[Timing] = []
    for page in pages:
        times, broken = measure(page, warmup, repeat)
        t = Timing(page.name, page.path, times, broken)
        if not broken and t.p(95) > budget_ms:
            again, broken = measure(page, warmup, repeat)
            t.again, t.broken = again, broken
        out.append(t)
    return Report(out, budget_ms, warmup, repeat)


@dataclass
class Report:
    pages: list[Timing]
    budget_ms: float
    warmup: int
    repeat: int

    def failed(self) -> list[Timing]:
        return [t for t in self.pages if t.over(self.budget_ms)]

    def rows(self) -> list[dict[str, Any]]:
        rows = []
        for t in self.pages:
            row: dict[str, Any] = {"page": t.name, "path": t.path, "n": len(t.times), "p50_ms": _num(t.p(50)),
                                   "p95_ms": _num(t.p(95)), "max_ms": _num(max(t.times or [math.inf])),
                                   "passed": not t.over(self.budget_ms)}  # fmt: skip
            if t.again is not None:
                row["again_p95_ms"] = _num(t.p(95, t.again))
            if t.broken:
                row["broken"] = t.broken
            rows.append(row)
        return rows

    def markdown(self) -> str:
        head = (f"## Console page time (D-1245): p95 of the console's own time, budget {self.budget_ms:g} ms\n\n"
                f"Warm-up {self.warmup}, then {self.repeat} answers per page, read from `Server-Timing`; a synthetic "
                "box (in-memory stand-in orchestrator, no model, no real data volume).\n\n"
                "| Page | Path | p50 ms | p95 ms | max ms | Second walk p95 | Result |\n"
                "| --- | --- | ---: | ---: | ---: | ---: | --- |\n")  # fmt: skip
        lines = []
        for r in self.rows():
            result = "pass" if r["passed"] else f"FAIL{' (' + r['broken'] + ')' if r.get('broken') else ''}"
            lines.append(f"| {r['page']} | `{r['path']}` | {r['p50_ms']} | {r['p95_ms']} | {r['max_ms']} | "
                         f"{r.get('again_p95_ms', '–')} | {result} |")  # fmt: skip
        return head + "\n".join(lines) + "\n"

    def write(self, out: Path) -> None:
        out.mkdir(parents=True, exist_ok=True)
        (out / "console_timing.md").write_text(self.markdown(), encoding="utf-8")
        body = {"budget_ms": self.budget_ms, "warmup": self.warmup, "repeat": self.repeat, "pages": self.rows()}
        (out / "console_timing.json").write_text(json.dumps(body, indent=1) + "\n", encoding="utf-8")


def _num(v: float) -> float | None:
    return None if math.isinf(v) else round(v, 1)
