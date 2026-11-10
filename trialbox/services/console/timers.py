"""The box's own timers for the console jobs (TB-PLAN-03 step 6, D-121).

Before D-121 the investigator list (N1), the coordinator digest (N2) and the nightly REDCap read-back ran from the
host's timers (``python -m console.notify`` / ``python -m console.rc_read``). The box now sends its own mail: the
console process schedules them, because both need the console's site store (people, notice settings, project links).

Environment:

* ``TB_CONSOLE_TIMERS``: ``auto`` (default: on when ``TB_ENV`` is VALIDATION or PRODUCTION, off otherwise, like the
  orchestrator's ``schedule.mode``), ``on`` or ``off``.
* ``TB_NOTICE_N1_AT`` (``07:00``), ``TB_NOTICE_N2_AT`` (``07:30``), ``TB_REDCAP_READ_AT`` (``03:00``, after the
  nightly ingest): local times in the site's zone.

Each run is the same call as its button (admin "Send notices now", S21 "Run now"); a notice still goes at most once
per person and day, so a timer and a button on the same morning never send twice.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from tb_common.config import environment_name

log = logging.getLogger("console.timers")
_HHMM = re.compile(r"([01]?\d|2[0-3]):([0-5]\d)")


class TimerError(ValueError):
    pass


@dataclass(frozen=True)
class Timer:
    name: str
    hour: int
    minute: int


def _at(env: Mapping[str, str], key: str, default: str) -> tuple[int, int]:
    raw = (env.get(key) or default).strip()
    m = _HHMM.fullmatch(raw)
    if not m:
        raise TimerError(f"{key} must be HH:MM, got {raw!r}")
    return int(m.group(1)), int(m.group(2))


def enabled(env: Mapping[str, str]) -> bool:
    mode = (env.get("TB_CONSOLE_TIMERS") or "auto").strip().lower()
    if mode not in ("auto", "on", "off"):
        raise TimerError(f"TB_CONSOLE_TIMERS must be auto, on or off, got {mode!r}")
    if mode == "auto":
        return environment_name(env) in ("VALIDATION", "PRODUCTION")
    return mode == "on"


def plan(env: Mapping[str, str]) -> list[Timer]:
    return [
        Timer("redcap_read", *_at(env, "TB_REDCAP_READ_AT", "03:00")),
        Timer("notice_n1", *_at(env, "TB_NOTICE_N1_AT", "07:00")),
        Timer("notice_n2", *_at(env, "TB_NOTICE_N2_AT", "07:30")),
    ]


def jobs(h: Any) -> dict[str, Callable[[], object]]:
    """The callables behind each timer (the same calls as the buttons)."""
    from console import notify, rc_read

    def n1() -> object:
        return notify.send_all(h, h.today(), ("N1",), by="console:timer")

    def n2() -> object:
        return notify.send_all(h, h.today(), ("N2",), by="console:timer")

    def rc() -> object:
        return rc_read.run(h)

    return {"redcap_read": rc, "notice_n1": n1, "notice_n2": n2}


def _guarded(name: str, fn: Callable[[], object]) -> Callable[[], None]:
    def run() -> None:
        try:
            fn()
        except Exception:  # a failed morning must not stop the next one
            log.exception("console timer %s failed", name)

    return run


def start(h: Any, env: Mapping[str, str], tz: Any) -> Any:
    """A started APScheduler, or ``None`` when the timers are off."""
    if not enabled(env):
        log.info("console timers off (TB_CONSOLE_TIMERS / TB_ENV)")
        return None
    from apscheduler.schedulers.background import BackgroundScheduler
    from tb_common.config import SCHEDULER_JOB_DEFAULTS

    sched = BackgroundScheduler(timezone=tz, job_defaults=SCHEDULER_JOB_DEFAULTS)  # review F-14 (D-130)
    calls = jobs(h)
    for t in plan(env):
        sched.add_job(_guarded(t.name, calls[t.name]), "cron", id=t.name, hour=t.hour, minute=t.minute)
    sched.start()
    return sched
