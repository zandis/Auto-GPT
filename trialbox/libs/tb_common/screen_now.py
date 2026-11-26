"""M8 (R1-N1): the rule of "screen now", shared by the orchestrator (``orchestrator.scheduler`` re-exports it) and the
console page (``console.screen_now``; the console imports no orchestrator code). Pure functions over job records."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from tb_contracts import Job

#: M8 (R1-N1): the night's job types. A screen-now asked for while one has not ended is queued behind it
NIGHT_TYPES = ("INGEST", "MICROBATCH", "NAV", "RETENTION")
LIST_TYPES = ("SCREEN", "MICROBATCH")  # the jobs whose wall time and scope say how long a screening takes
_RECENT = 5  # the last runs the expected time is taken from
STALE_DAYS = 1  # a snapshot older than this is said to be old on the page


@dataclass(frozen=True)
class ScreenNowPlan:
    """What a "screen now" request does: ``join`` the study's running SCREEN (``job_id``), ``queue`` behind the
    night's jobs that have not ended (``behind``; the orchestrator's queue takes them in order of arrival), or
    ``start`` at once."""

    action: str
    job_id: str | None = None
    behind: int = 0


def screen_now_plan(active: Iterable[Job], ruleset: str) -> ScreenNowPlan:
    """The job rule of "screen now": one per study at a time. ``active`` are the jobs not ended. A second request for
    a study joins the first, never makes a second job; a request during the night is queued, never run beside it
    under another name. Nothing here starts a job, changes a snapshot or starts an ingest."""
    rs = ruleset.upper()
    jobs = list(active)
    for j in sorted(jobs, key=lambda j: (j.received_at, j.job_id)):
        if j.type == "SCREEN" and (j.ruleset or "").upper() == rs and j.state not in ("done", "failed"):
            return ScreenNowPlan("join", j.job_id)
    behind = sum(1 for j in jobs if j.type in NIGHT_TYPES and j.state not in ("done", "failed"))
    return ScreenNowPlan("queue" if behind else "start", None, behind)


def _timed(done: Iterable[Job]) -> list[Job]:
    got = [j for j in done if j.state == "done" and j.metrics and j.metrics.wall_seconds > 0]
    return sorted(got, key=lambda j: (j.updated_at or j.received_at, j.job_id))[-_RECENT:]


def per_1000_seconds(done: Iterable[Job], ruleset: str) -> float | None:
    """The median seconds per 1,000 patients of the study's last screenings (``SCREEN`` and ``MICROBATCH`` that are
    done and counted their patients); None when there is no such run: a time is never made up."""
    rs = ruleset.upper()
    runs = [
        j
        for j in _timed(d for d in done if d.type in LIST_TYPES and (d.ruleset or "").upper() == rs)
        if j.metrics and j.metrics.patients_scoped > 0
    ]
    rates = sorted(j.metrics.wall_seconds * 1000 / j.metrics.patients_scoped for j in runs if j.metrics)
    return rates[len(rates) // 2] if rates else None


def expected_wait(active: Iterable[Job], done: Iterable[Job]) -> float | None:
    """The seconds a request waits behind the night: for each night job not ended, the median wall time of the last
    jobs of its type that are done; None when any of them has no earlier run (the page says "not known")."""
    pool = list(done)
    total = 0.0
    for j in active:
        if j.type not in NIGHT_TYPES or j.state in ("done", "failed"):
            continue
        walls = sorted(x.metrics.wall_seconds for x in _timed(d for d in pool if d.type == j.type) if x.metrics)
        if not walls:
            return None
        total += walls[len(walls) // 2]
    return total
