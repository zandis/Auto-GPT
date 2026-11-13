"""The night runner (T-726, D-492; scale review F-33): a step starts when the step before it has finished.

Only the ingest and the monthly jobs keep a clock time. When the timer's ingest has passed, the night's other steps
follow it, in this order, each started only when every job of the step before it has ended:

* ``screen``: one MICROBATCH per study with a candidate pool: the weekly one on the weekly day (or the first night
  after a weekly day that was missed), else the one that follows every ingest (D-397). Never both.
* ``nav``: on its weekly day, one NAV per approved NHI ruleset.
* ``retention``: every night.

**One run per study and night.** Every job the chain starts carries its night in its record (``options.night``:
the generation the ingest published, else its date; ``options.step``; ``options.night_day``) and has an id made from
its type, study and night (:func:`chain_job_id`): the job store's key, not a lock of one process, is what makes a
second start the first one's job, whoever asks (a retried ingest, a restart, two processes at once).

**No state of its own.** The chain is read from the jobs: the last timed ingest that passed (the scheduler's, or an
administrator's retry of it), and the chain's jobs of that night. :func:`advance` is called when the ingest ends,
when any job ends and when the orchestrator starts, so a restart resumes the step the night was in:

* a step's jobs carry the step's plan (``options.plan``: the studies it was started for). A step that was started
  in part (the process died between two of its jobs) is completed from that plan before the chain goes on;
* a step with no job is passed over for good once a later step of the night has a job: the model steps are never
  started after retention (a self-test that passes after a restart, a study opened in the morning). What a night
  passed over is made up by the next night that passes, on that night's snapshot;
* while a job of an earlier night's chain has not ended, the newer night waits: two micro-batches of one study never
  run beside each other. The earlier night's steps that had not started are not run; the newer night covers them.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any, cast
from zoneinfo import ZoneInfo

from tb_contracts import Job, JobCreate

if TYPE_CHECKING:
    from orchestrator.core import Orchestrator

log = logging.getLogger("orchestrator.night")
STEPS = ("screen", "nav", "retention")
STEP_TYPE = {"screen": "MICROBATCH", "nav": "NAV", "retention": "RETENTION"}
MODEL_STEPS = ("screen", "nav")  # they ask the models: they wait for the night's self-test
TERMINAL = ("done", "failed")
_DAY = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_lock = threading.Lock()  # one advance at a time in this process (the job's id holds two processes apart)
_said: set[tuple[str, str]] = set()  # (night, what) said once: a pass-over, a night that waits


def chain_job_id(jtype: str, ruleset: str | None, night: str) -> str:
    """The id of the chain's job of ``jtype`` for ``ruleset`` and ``night``: 26 characters of the job id's alphabet
    from a hash of the three. ``Orchestrator.create`` answers an existing job for an id it knows, and the id is the
    job store's primary key, so the chain cannot make two."""
    n = int.from_bytes(hashlib.sha256(f"night-chain|{jtype}|{ruleset or ''}|{night}".encode()).digest()[:17], "big")
    n >>= 6  # 130 bits: 26 characters of 5 bits
    return "".join(_CROCKFORD[(n >> (5 * i)) & 31] for i in reversed(range(26)))


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
    return orch.db.scheduler_jobs(type_=STEP_TYPE[step], night=night, step=step)


def weekly_due(orch: Orchestrator, step: str, ruleset: str | None, day: date, weekday: int | None) -> bool:
    """A weekly step is due for a study when no weekly run of it exists for a night since its last scheduled day:
    on its day, and on the first night that passes after a day that was missed. A weekly job the timers made
    before this card (no ``options.step``) counts by the site's date it was made on."""
    if weekday is None:
        return True
    since = last_scheduled(day, weekday)
    jtype, rid = STEP_TYPE[step], ruleset or ""
    mine = orch.db.scheduler_jobs(type_=jtype, ruleset=rid, step=step, night_day_from=since.isoformat())
    if any((j.options or {}).get("trigger") != "ingest" for j in mine):
        return False
    zone = ZoneInfo(orch.cfg.env.tz)
    # the job store's times are UTC and the day is the site's: read from the day before, compare the site's date
    before = orch.db.scheduler_jobs(
        type_=jtype, ruleset=rid, step="", received_from=(since - timedelta(days=1)).isoformat()
    )
    return not any(
        (j.options or {}).get("trigger") != "ingest" and j.received_at.astimezone(zone).date() >= since for j in before
    )


def current_night(orch: Orchestrator) -> tuple[str, date] | None:
    """The night the chain is on: the newest timed ingest that passed (its generation, else its date; its day). The
    timer's ingest is the scheduler's own job or an administrator's retry of one (D-474): a retry copies the failed
    job's options and names the administrator, and it is the same night."""
    before: str | None = None
    while True:
        j = orch.db.chained_ingest(before)
        if j is None:
            return None
        root = j if j.requested_by == "scheduler" and not j.parent_job_id else orch.scheduled_root(j)
        if root is not None and j.snapshot_date is not None:
            o = j.options or {}
            return str(o.get("lake_generation") or j.snapshot_date.isoformat()), j.snapshot_date
        before = j.job_id  # a person's ingest that carries the option is not the night: the next


def _targets(orch: Orchestrator, step: str) -> list[str | None]:
    from orchestrator import scheduler

    if step == "screen":
        return list(orch.db.pool_rulesets())
    if step == "nav":
        return list(scheduler.nav_rulesets(orch))
    return [None]


def _exists(orch: Orchestrator, jtype: str, rid: str | None, night: str) -> bool:
    return orch.db.get(chain_job_id(jtype, rid, night)) is not None


def _create(orch: Orchestrator, step: str, night: str, day: date, rid: str | None, plan: str) -> None:
    jtype = STEP_TYPE[step]
    options = {"night": night, "step": step, "night_day": day.isoformat(), "plan": plan}
    if step == "screen":
        options["trigger"] = "weekly" if weekly_due(orch, step, rid, day, days(orch)[step]) else "ingest"
    orch.create(
        JobCreate(
            type=cast(Any, jtype),
            ruleset=rid,
            requested_by="scheduler",
            options=options,
            job_id=chain_job_id(jtype, rid, night),
        )
    )


def _say(orch: Orchestrator, night: str, what: str, message: str, detail: dict[str, Any] | None = None) -> None:
    """Log (and audit, with ``detail``) once per night and thing in this process."""
    if (night, what) in _said:
        return
    _said.add((night, what))
    log.error("night %s: %s", night, message)
    if detail is not None:
        try:
            orch.audit.append("scheduler.held", detail={**detail, "night": night})
        except Exception as exc:  # the audit must not take the chain down
            log.warning("scheduler.held not audited: %s", exc)


def _start_step(orch: Orchestrator, step: str, night: str, day: date) -> list[str | None]:
    """Start the jobs of ``step`` that are due for this night; returns the studies started (none: the step is
    passed over). A job of this type, study and night that exists already is never started again."""
    from orchestrator import scheduler

    jtype = STEP_TYPE[step]
    if jtype not in orch.scenarios:
        return []
    weekday = days(orch)[step]
    if step in MODEL_STEPS and not scheduler.night_gate(orch):
        _say(orch, night, step, f"{step} passed over: the night model self-test did not pass",
             {"job": jtype, "state": "self-test failed"})  # fmt: skip
        return []
    due: list[str | None] = []
    for rid in _targets(orch, step):
        if step == "nav" and not weekly_due(orch, step, rid, day, weekday):
            continue
        if scheduler._held(orch, jtype, rid):
            continue
        if _exists(orch, jtype, rid, night):
            continue  # one run per study and night
        due.append(rid)
    plan = ",".join(rid or "" for rid in due)  # written into every job of the step: what a restart completes
    for rid in due:
        _create(orch, step, night, day, rid, plan)
    return due


def _complete(orch: Orchestrator, step: str, night: str, day: date, jobs: list[Job]) -> list[str | None]:
    """The step was started: make the jobs of its plan that do not exist (the process died between two of them)."""
    planned = {r or None for j in jobs for r in str((j.options or {}).get("plan") or "").split(",")}
    if not any("plan" in (j.options or {}) for j in jobs):
        return []  # a step started before the plan was written: as it stands
    missing = sorted((r for r in planned - {j.ruleset for j in jobs}), key=lambda r: r or "")
    plan = next(str((j.options or {})["plan"]) for j in jobs if "plan" in (j.options or {}))
    for rid in missing:
        _create(orch, step, night, day, rid, plan)
    return missing


def advance(orch: Orchestrator) -> list[str | None]:
    """Go on with the night: complete a step that was started in part, else start the first step that has no job
    and is not passed, once every job of the steps before it has ended. Returns the studies of the jobs it started
    (none: nothing to start now). Never raises."""
    try:
        with _lock:
            cur = current_night(orch)
            if cur is None:
                return []
            night, day = cur
            older = [  # an earlier night's chain that has not ended
                j
                for j in orch.db.scheduler_jobs(unfinished=True)
                if (j.options or {}).get("step") and (j.options or {}).get("night") not in (None, night)
            ]
            if older:
                _say(orch, night, "waits", f"waits for {len(older)} job(s) of an earlier night's chain; the steps "
                     "that night had not started are not run, this night covers them")  # fmt: skip
                return []
            by_step = {step: chain_jobs(orch, night, step) for step in STEPS}
            reached = max((i for i, step in enumerate(STEPS) if by_step[step]), default=-1)
            for i, step in enumerate(STEPS):
                jobs = by_step[step]
                if jobs:
                    made = _complete(orch, step, night, day, jobs)
                    if made:
                        return made
                    if any(j.state not in TERMINAL for j in jobs):
                        return []  # this step is still running
                    continue
                if i < reached:
                    continue  # passed over, and a later step has started: not started any more this night
                started = _start_step(orch, step, night, day)
                if started:
                    return started
            return []
    except Exception as exc:  # the chain must not take a job's end or the start-up down
        log.exception("the night chain did not advance: %s", exc)
        return []


__all__ = [
    "STEPS",
    "advance",
    "chain_job_id",
    "chain_jobs",
    "current_night",
    "days",
    "last_scheduled",
    "weekday_of",
    "weekly_due",
]
