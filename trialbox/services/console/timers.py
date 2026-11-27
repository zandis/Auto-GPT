"""The box's own timers for the console jobs (TB-PLAN-03 step 6, D-121).

Before D-121 the investigator list (N1), the coordinator digest (N2) and the nightly REDCap read-back ran from the
host's timers (``python -m console.notify`` / ``python -m console.rc_read``). The box now sends its own mail: the
console process schedules them, because both need the console's site store (people, notice settings, project links).

Environment:

* ``TB_CONSOLE_TIMERS``: ``auto`` (default: on when ``TB_ENV`` is VALIDATION or PRODUCTION, off otherwise, like the
  orchestrator's ``schedule.mode``), ``on`` or ``off``.
* ``TB_NOTICE_N1_AT`` (``07:00``), ``TB_NOTICE_N2_AT`` (``07:30``), ``TB_REDCAP_READ_AT`` (``03:00``, after the
  nightly ingest): local times in the site's zone.
* ``TB_HEALTH_MAIL_AT`` (``07:00``): the administrators' daily health mail (T-209a, D-379).

Each run is the same call as its button (admin "Send notices now", S21 "Run now"); a notice still goes at most once
per person and day, so a timer and a button on the same morning never send twice.
"""

from __future__ import annotations

import fcntl
import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

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
        Timer("health_mail", *_at(env, "TB_HEALTH_MAIL_AT", "07:00")),
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

    def health() -> object:
        return notify.send_all(h, h.today(), ("HEALTH",), by="console:timer")

    return {"redcap_read": rc, "notice_n1": n1, "notice_n2": n2, "health_mail": health}


def _guarded(name: str, fn: Callable[[], object]) -> Callable[[], None]:
    def run() -> None:
        try:
            fn()
        except Exception:  # a failed morning must not stop the next one
            log.exception("console timer %s failed", name)

    return run


_held: list[IO[str]] = []  # the lock file of the process that runs the timers, open for as long as it lives


def owns(lock: Path) -> bool:
    """P2-11 (D7): the console runs ``TB_CONSOLE_WORKERS`` processes and a notice must go once, so the timers run in
    one. True for the process that holds ``lock`` (an ``flock`` on a file in the console's data folder). The kernel
    releases it when that process ends; uvicorn starts a new worker, whose start takes it. Any other failure to lock
    (no locks to be had, ENOLCK) is raised: the start fails and says why, never read as another worker's timers."""
    fh = lock.open("a", encoding="utf-8")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        return False
    except OSError:
        fh.close()
        raise
    _held.append(fh)
    return True


def start(h: Any, env: Mapping[str, str], tz: Any, lock: Path | None = None) -> Any:
    """A started APScheduler, or ``None`` when the timers are off or another worker process runs them."""
    if not enabled(env):
        log.info("console timers off (TB_CONSOLE_TIMERS / TB_ENV)")
        return None
    if lock is not None and not owns(lock):
        log.info("console timers run in another worker process (%s)", lock)
        return None
    from apscheduler.schedulers.background import BackgroundScheduler
    from tb_common.config import SCHEDULER_JOB_DEFAULTS

    sched = BackgroundScheduler(timezone=tz, job_defaults=SCHEDULER_JOB_DEFAULTS)  # review F-14 (D-130)
    calls = jobs(h)
    for t in plan(env):
        sched.add_job(_guarded(t.name, calls[t.name]), "cron", id=t.name, hour=t.hour, minute=t.minute)
    sched.start()
    return sched
