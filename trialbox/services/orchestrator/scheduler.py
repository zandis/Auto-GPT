"""Nightly / weekly / monthly batch jobs (SPEC §4.8) from ``settings.schedule``: every scheduled run is a job.

D-386 (T-622, LIFE-008): a list job (SCREEN, MICROBATCH, COHORT) runs only for a study whose state is ``open``. The
state is the console's (schema ``site`` of the trial database, table ``study_state``; the console writes it, this
module only reads it). The timer skips a study that is not open and audits the skip; a list job asked for by hand
fails at its first step with the reason (:func:`require_open`, called by the list scenarios). A study with no
recorded state is open, as before D-386.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, cast

import yaml
from tb_common.ruleset import list_rulesets
from tb_contracts import JobCreate, Settings

from orchestrator.core import Orchestrator, Rejected

log = logging.getLogger("orchestrator.scheduler")
_DAYS = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}
QUARTER_MONTHS = "1,4,7,10"


class ScheduleError(ValueError):
    pass


def cron_kwargs(spec: str, quarterly: bool = False) -> dict[str, Any]:
    """``"02:00"`` daily · ``"MON 03:00"`` weekly · ``"1st 04:00"`` monthly (quarterly for COHORT)."""
    parts = spec.strip().split()
    if not parts or not re.fullmatch(r"[0-2]?\d:[0-5]\d", parts[-1]):
        raise ScheduleError(f"bad schedule {spec!r}")
    hh, mm = (int(x) for x in parts[-1].split(":"))
    if hh > 23:
        raise ScheduleError(f"bad hour in {spec!r}")
    kw: dict[str, Any] = {"hour": hh, "minute": mm}
    if len(parts) == 2:
        day = parts[0].upper()
        if day in _DAYS:
            kw["day_of_week"] = day.lower()
        elif m := re.fullmatch(r"(\d{1,2})(ST|ND|RD|TH)", day):
            kw["day"] = int(m.group(1))
            if quarterly:
                kw["month"] = QUARTER_MONTHS
        else:
            raise ScheduleError(f"bad day in {spec!r}")
    elif len(parts) != 1:
        raise ScheduleError(f"bad schedule {spec!r}")
    return kw


LIST_JOBS = ("SCREEN", "MICROBATCH", "COHORT")  # the jobs that make a patient list (D-386)
OPEN = "open"


def study_state(ruleset: str, url: str | None = None) -> str:
    """The study's state from the console's ``site.study_state`` (latest row), or ``open`` when the study has none
    or the console has not made the table yet. ``url``: the trial database (``TB_DB_URL`` when None); without one
    (a bare test stack) every study is open. A database error is raised: the caller decides."""
    from tb_common.db import Database

    url = url or os.environ.get("TB_DB_URL")
    if not url:
        return OPEN
    with Database.connect(url, "site") as site:
        if site.fetchval("SELECT to_regclass(?)", (f'"{site.schema}".study_state',)) is None:
            return OPEN
        state = site.fetchval(
            "SELECT state FROM study_state WHERE ruleset = ? ORDER BY at DESC, id DESC LIMIT 1",
            ((ruleset or "").upper(),),
        )
    return str(state) if state else OPEN


def require_open(ruleset: str | None) -> None:
    """A list scenario's first check (D-386): refuse to make a list for a study that is not open. The job fails
    with the reason; nothing is listed or mailed. An unreachable trial database is logged and left to the run's own
    steps, which need the same database (the timer, :func:`_held`, holds the job instead)."""
    from orchestrator.clients import StepFailed

    from tb_common.db import DatabaseError

    if not ruleset:
        return
    try:
        state = study_state(ruleset)
    except DatabaseError as exc:  # the trial database is unreachable: the run that follows needs it and fails there
        log.warning("study state of %s not read: %s", ruleset, exc)
        return
    if state != OPEN:
        raise StepFailed(
            "ruleset",
            f"Study {ruleset.upper()} is {state}: lists run only for an open study. "
            "The study coordinator changes the state on the study's set-up page.",
        )


def _held(orch: Orchestrator, jtype: str, ruleset: str | None) -> bool:
    """True when the timer must not start ``jtype`` for ``ruleset``: a list job of a study that is not open. The
    skip is audited (``scheduler.held``); a state that cannot be read holds the job too (logged)."""
    if jtype not in LIST_JOBS or not ruleset:
        return False
    try:
        state = study_state(ruleset)
    except Exception as exc:  # the trial database is down: no list rather than a list for a paused study
        log.error("%s for %s held: the study state could not be read: %s", jtype, ruleset, exc)
        return True
    if state == OPEN:
        return False
    log.info("%s for %s held: the study is %s", jtype, ruleset, state)
    try:
        orch.audit.append("scheduler.held", ruleset=ruleset, detail={"job": jtype, "state": state})
    except Exception as exc:  # the audit must not take the scheduler down
        log.warning("scheduler.held not audited: %s", exc)
    return True


def _submit(orch: Orchestrator, jtype: str, ruleset: str | None = None) -> None:
    if jtype not in orch.scenarios:
        return
    if _held(orch, jtype, ruleset):
        return
    try:
        orch.create(JobCreate(type=cast(Any, jtype), ruleset=ruleset, requested_by="scheduler"))
    except Rejected as exc:  # never raised for the scheduler, kept for safety
        log.warning("scheduled %s not created: %s", jtype, exc)


LLM_JOBS = ("MICROBATCH", "NAV", "COHORT", "CALIBRATION")  # night jobs that ask the models
_gate: dict[str, bool] = {}  # date -> canary result, so the self-test runs once a night


def night_gate(orch: Orchestrator, today: str | None = None) -> bool:
    """The night's model self-test (:mod:`orchestrator.selftest`), run before the first LLM job of the day; the LLM
    jobs start only when it passed. Its result is kept for the day, so a failed canary holds every LLM job that
    night and a passed one runs once."""
    from tb_common.timeutil import today as site_today

    from orchestrator.selftest import preflight

    # the site's night, not the container's UTC date (D-270); not orch.today(), which a test stack may pin
    day = today or site_today(orch.cfg.env.tz).isoformat()
    if day not in _gate:
        try:
            _gate[day] = preflight(orch)
        except Exception as exc:  # the gate itself must not take the scheduler down
            log.exception("night self-test errored: %s", exc)
            _gate[day] = False
    return _gate[day]


def plan(settings: Settings) -> list[tuple[str, dict[str, Any]]]:
    sch = settings.schedule

    def get(key: str, default: str) -> str:
        return str(getattr(sch, key, None) or default) if sch else default

    return [
        ("INGEST", cron_kwargs(get("ingest", "02:00"))),
        ("MICROBATCH", cron_kwargs(get("microbatch", "MON 03:00"))),
        ("NAV", cron_kwargs(get("nav", "MON 03:30"))),
        ("COHORT", cron_kwargs(get("cohort", "1st 04:00"), quarterly=True)),
        ("RETENTION", cron_kwargs(get("retention", "05:00"))),
        ("CALIBRATION", cron_kwargs(get("calibration", "1st 05:30"))),
    ]


def run_now(orch: Orchestrator, jtype: str, ruleset: str | None = None) -> None:
    """Run one scheduled job type now (the on-demand path of FR-OPS-12), with the same fan-out as the timer."""
    if jtype == "MICROBATCH":
        targets: list[str | None] = list(orch.db.pool_rulesets())
    elif jtype == "CALIBRATION":
        targets = list(orch.db.feedback_rulesets())
    elif jtype == "COHORT":
        targets = list(cohort_rulesets(orch))
    else:
        targets = [ruleset]
    for rid in [ruleset] if ruleset and jtype != "INGEST" else targets:
        _submit(orch, jtype, rid)


def cohort_rulesets(orch: Orchestrator) -> list[str]:
    """``settings.cohort.rulesets`` when given, else every approved cohort ruleset."""
    cs = orch.cfg.settings.cohort
    if cs and cs.rulesets:
        return list(cs.rulesets)
    out = []
    for rid in list_rulesets(orch.rulesets_dir):
        body = yaml.safe_load((orch.rulesets_dir / rid / "manifest.yaml").read_text(encoding="utf-8"))
        if (body or {}).get("kind") == "cohort" and body.get("status") == "approved":
            out.append(rid)
    return out


def start(orch: Orchestrator) -> Any:
    """Start the timed jobs, or nothing when the schedule is on demand (DEV by default, FR-OPS-12): then INGEST,
    MICROBATCH and the rest run only when requested (mail command, console or ``run_now``)."""
    from apscheduler.schedulers.background import BackgroundScheduler
    from tb_common.config import SCHEDULER_JOB_DEFAULTS, schedule_on_demand, tb_env

    if schedule_on_demand(orch.cfg.settings, tb_env(orch.cfg.env)):
        log.info("schedule is on demand (TB_ENV=%s): no timed jobs", tb_env(orch.cfg.env))
        return None

    sched = BackgroundScheduler(timezone=orch.cfg.env.tz, job_defaults=SCHEDULER_JOB_DEFAULTS)  # F-14
    for jtype, kw in plan(orch.cfg.settings):
        if jtype in ("MICROBATCH", "CALIBRATION"):

            def per_ruleset(jt: str = jtype) -> None:
                if not night_gate(orch):
                    log.error("%s held: the night model self-test did not pass", jt)
                    return
                db = orch.db
                for rid in db.pool_rulesets() if jt == "MICROBATCH" else db.feedback_rulesets():
                    _submit(orch, jt, rid)

            sched.add_job(per_ruleset, "cron", id=jtype.lower(), **kw)
        elif jtype == "NAV":

            def nav() -> None:
                if not night_gate(orch):
                    log.error("NAV held: the night model self-test did not pass")
                    return
                for rid in list_rulesets(orch.rulesets_dir):
                    body = yaml.safe_load((orch.rulesets_dir / rid / "manifest.yaml").read_text(encoding="utf-8"))
                    if (body or {}).get("kind") == "nhi" and body.get("status") == "approved":
                        _submit(orch, "NAV", rid)

            sched.add_job(nav, "cron", id="nav", **kw)
        elif jtype == "COHORT":

            def cohort() -> None:
                if not night_gate(orch):
                    log.error("COHORT held: the night model self-test did not pass")
                    return
                for rid in cohort_rulesets(orch):
                    _submit(orch, "COHORT", rid)

            sched.add_job(cohort, "cron", id="cohort", **kw)
        else:
            sched.add_job(_submit, "cron", id=jtype.lower(), args=[orch, jtype], **kw)
    sched.start()
    return sched
