"""The night runner (T-726, D-492; scale review F-33): a step starts when the step before it has finished.

Only the ingest and the monthly jobs keep a clock time. When the timer's ingest has passed, the night's other steps
follow it, in this order, each started only when every job of the step before it has ended:

* ``screen``: one MICROBATCH per study with a candidate pool: the weekly one on the weekly day (or the first night
  after a weekly day that was missed), else the one that follows every ingest (D-397). Never both.
* ``nav``: on its weekly day, one NAV per approved NHI ruleset.
* ``retention``: every night.

**One run per study and generation.** Every job the chain starts carries its night in its record (``options.night``:
the generation the ingest published, else its date; ``options.step``; ``options.night_day``). A job of that type,
study and night is never started twice, whoever asks (a retried ingest, a restart, two calls at once).

**No state of its own.** The chain is read from the jobs: the last timed ingest that passed, and the chain's jobs of
that night. :func:`advance` is called when the ingest ends, when any job ends and when the orchestrator starts, so a
restart resumes the step the night was in.
"""

from __future__ import annotations

import logging
import threading
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any, cast

from tb_contracts import Job, JobCreate

if TYPE_CHECKING:
    from orchestrator.core import Orchestrator

log = logging.getLogger("orchestrator.night")
STEPS = ("screen", "nav", "retention")
STEP_TYPE = {"screen": "MICROBATCH", "nav": "NAV", "retention": "RETENTION"}
MODEL_STEPS = ("screen", "nav")  # they ask the models: they wait for the night's self-test
TERMINAL = ("done", "failed")
LOOK_BACK = 200  # jobs of one type and study read to find the chain's own (newest first; a night makes one)
_DAY = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}
_lock = threading.Lock()  # one advance at a time in this process: "is there a job already" and "start it" together
_said: set[tuple[str, str]] = set()  # (night, step) whose pass-over was audited: said once


def weekday_of(spec: str | None, default: str) -> int | None:
    """The weekly day of a schedule entry (``"MON 03:00"`` -> 0), or None for a daily one. The hour is not read:
    the step follows the ingest (D-492)."""
    parts = (spec or default).strip().split()
    return _DAY.get(parts[0].upper()) if len(parts) == 2 else None


def days(orch: Orchestrator) -> dict[str, int | None]:
    """Step -> its weekly day (None: every night), from ``settings.schedule``."""
    sch = getattr(orch.cfg.settings, "schedule", None)
    return {
        "screen": weekday_of(getattr(sch, "microbatch", None), "MON 03:00"),
        "nav": weekday_of(getattr(sch, "nav", None), "MON 03:30"),
        "retention": weekday_of(getattr(sch, "retention", None), "05:00"),
    }


def last_scheduled(day: date, weekday: int | None) -> date:
    """The latest scheduled day of a step on or before ``day`` (a daily step: ``day`` itself)."""
    return day if weekday is None else day - timedelta(days=(day.weekday() - weekday) % 7)


def _mine(job: Job, step: str) -> bool:
    return job.requested_by == "scheduler" and (job.options or {}).get("step") == step


def chain_jobs(orch: Orchestrator, night: str, step: str) -> list[Job]:
    """The chain's jobs of ``step`` for ``night``, of every study."""
    found = orch.db.find(type_=STEP_TYPE[step], limit=LOOK_BACK)
    return [j for j in found if _mine(j, step) and (j.options or {}).get("night") == night]


def weekly_due(orch: Orchestrator, step: str, ruleset: str | None, day: date, weekday: int | None) -> bool:
    """A weekly step is due for a study when no weekly run of it exists for a night since its last scheduled day:
    on its day, and on the first night that passes after a day that was missed."""
    if weekday is None:
        return True
    since = last_scheduled(day, weekday).isoformat()
    for j in orch.db.find(type_=STEP_TYPE[step], ruleset=ruleset, limit=LOOK_BACK):
        o = j.options or {}
        if _mine(j, step) and o.get("trigger") != "ingest" and str(o.get("night_day") or "") >= since:
            return False
    return True


def current_night(orch: Orchestrator) -> tuple[str, date] | None:
    """The night the chain is on: the newest timed ingest that passed (its generation, else its date; its day)."""
    for j in orch.db.find(type_="INGEST", state="done", limit=20):
        o = j.options or {}
        if j.requested_by == "scheduler" and o.get("chain") == "1" and j.snapshot_date is not None:
            return str(o.get("lake_generation") or j.snapshot_date.isoformat()), j.snapshot_date
    return None


def _targets(orch: Orchestrator, step: str) -> list[str | None]:
    from orchestrator import scheduler

    if step == "screen":
        return list(orch.db.pool_rulesets())
    if step == "nav":
        return list(scheduler.nav_rulesets(orch))
    return [None]


def _start_step(orch: Orchestrator, step: str, night: str, day: date) -> list[str | None]:
    """Start the jobs of ``step`` that are due for this night; returns the studies started (none: the step is
    passed over). A job of this type, study and night that exists already is never started again."""
    from orchestrator import scheduler

    jtype = STEP_TYPE[step]
    if jtype not in orch.scenarios:
        return []
    weekday = days(orch)[step]
    if step in MODEL_STEPS and not scheduler.night_gate(orch):
        if (night, step) not in _said:
            _said.add((night, step))
            log.error("night %s: %s passed over: the night model self-test did not pass", night, step)
            try:
                orch.audit.append("scheduler.held", detail={"job": jtype, "state": "self-test failed", "night": night})
            except Exception as exc:  # the audit must not take the chain down
                log.warning("scheduler.held not audited: %s", exc)
        return []
    started: list[str | None] = []
    for rid in _targets(orch, step):
        weekly = weekly_due(orch, step, rid, day, weekday)
        if step == "nav" and not weekly:
            continue
        if scheduler._held(orch, jtype, rid):
            continue
        have = (
            orch.db.find(type_=jtype, ruleset=rid, limit=LOOK_BACK)
            if rid
            else orch.db.find(type_=jtype, limit=LOOK_BACK)
        )
        if any(_mine(j, step) and (j.options or {}).get("night") == night and j.ruleset == rid for j in have):
            continue  # one run per study and generation
        options = {"night": night, "step": step, "night_day": day.isoformat()}
        if step == "screen":
            options["trigger"] = "weekly" if weekly else "ingest"
        orch.create(JobCreate(type=cast(Any, jtype), ruleset=rid, requested_by="scheduler", options=options))
        started.append(rid)
    return started


def advance(orch: Orchestrator) -> list[str | None]:
    """Go on with the night: start the first step whose jobs do not exist yet, once every job of the steps before
    it has ended. Returns the studies of the step it started (none: nothing to start now). Never raises."""
    try:
        with _lock:
            cur = current_night(orch)
            if cur is None:
                return []
            night, day = cur
            for step in STEPS:
                jobs = chain_jobs(orch, night, step)
                if jobs:
                    if any(j.state not in TERMINAL for j in jobs):
                        return []  # this step is still running
                    continue
                started = _start_step(orch, step, night, day)
                if started:
                    return started
            return []
    except Exception as exc:  # the chain must not take a job's end or the start-up down
        log.exception("the night chain did not advance: %s", exc)
        return []


__all__ = ["STEPS", "advance", "chain_jobs", "current_night", "days", "last_scheduled", "weekday_of", "weekly_due"]
