"""Nightly / weekly / monthly batch jobs (SPEC §4.8) from ``settings.schedule``: every scheduled run is a job."""

from __future__ import annotations

import logging
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


def _submit(orch: Orchestrator, jtype: str, ruleset: str | None = None) -> None:
    if jtype not in orch.scenarios:
        return
    try:
        orch.create(JobCreate(type=cast(Any, jtype), ruleset=ruleset, requested_by="scheduler"))
    except Rejected as exc:  # never raised for the scheduler, kept for safety
        log.warning("scheduled %s not created: %s", jtype, exc)


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


def start(orch: Orchestrator) -> Any:
    from apscheduler.schedulers.background import BackgroundScheduler

    sched = BackgroundScheduler(timezone=orch.cfg.env.tz)
    for jtype, kw in plan(orch.cfg.settings):
        if jtype in ("MICROBATCH", "CALIBRATION"):

            def per_ruleset(jt: str = jtype) -> None:
                db = orch.db
                for rid in db.pool_rulesets() if jt == "MICROBATCH" else db.feedback_rulesets():
                    _submit(orch, jt, rid)

            sched.add_job(per_ruleset, "cron", id=jtype.lower(), **kw)
        elif jtype == "NAV":

            def nav() -> None:
                for rid in list_rulesets(orch.rulesets_dir):
                    body = yaml.safe_load((orch.rulesets_dir / rid / "manifest.yaml").read_text(encoding="utf-8"))
                    if (body or {}).get("kind") == "nhi" and body.get("status") == "approved":
                        _submit(orch, "NAV", rid)

            sched.add_job(nav, "cron", id="nav", **kw)
        else:
            sched.add_job(_submit, "cron", id=jtype.lower(), args=[orch, jtype], **kw)
    sched.start()
    return sched
