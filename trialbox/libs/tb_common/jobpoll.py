"""Polling a job another service runs (T-690, D-472).

Work that grows with the hospital (the lake rebuild, the night's ingest) is started with one short request, which the
service answers with 202 and a state, and then followed by reading that state. The caller never times the work
itself (OD-10: no fixed limit on work whose length is the size of the data): a job that answers ``running`` is
followed for as long as it runs. Two declared settings bound the polling:

* ``TB_JOB_POLL_SECONDS`` (5): the longest pause between two reads. Reads start at a fraction of a second and double
  up to it, so a short job is seen ending at once. A read is one small file or memory read on the other side.
* ``TB_JOB_LOST_SECONDS`` (900): how long the caller goes on asking a service that does not answer at all (no
  connection, a 5xx). A container restart under compose, a lake worker's start included, takes well under it. Past
  it the job is reported lost (:class:`JobLost`) with a plain message; the job's state can still be read later.

A service that answers that it does not know the job (state ``none``, or 404 for a run) has lost it (it restarted):
that is :class:`JobLost` at once, not a wait.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from tb_common.config import ConfigError

#: the states that end a job; ``running`` is the only one that is followed
TERMINAL = frozenset({"done", "busy", "refused", "failed", "interrupted"})
FIRST_PAUSE = 0.05


class JobLost(RuntimeError):
    """The job can no longer be followed: its service stopped answering for ``TB_JOB_LOST_SECONDS``, or it no longer
    knows the job. Nothing is known about its end."""


def _setting(name: str, default: str) -> float:
    raw = os.environ.get(name, "").strip() or default
    try:
        val = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number of seconds, not {raw!r}") from None
    if val <= 0:
        raise ConfigError(f"{name} must be more than 0 seconds")
    return val


def poll_seconds() -> float:
    """``TB_JOB_POLL_SECONDS``: the longest pause between two reads of a job's state."""
    return _setting("TB_JOB_POLL_SECONDS", "5")


def lost_seconds() -> float:
    """``TB_JOB_LOST_SECONDS``: how long a service may not answer before its job is reported lost (at least one
    poll interval)."""
    val = _setting("TB_JOB_LOST_SECONDS", "900")
    if val < poll_seconds():
        raise ConfigError("TB_JOB_LOST_SECONDS must be at least TB_JOB_POLL_SECONDS")
    return val


def no_answer(exc: Exception) -> bool:
    """Whether ``exc`` means the service did not answer (no connection, a timeout of one read, a 5xx)."""
    from tb_common.http import ServiceError

    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, ServiceError):
        return exc.status == 0 or exc.status >= 500
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


@dataclass
class Poll:
    """Follow a job to its end: ``until_done(read, what)`` calls ``read`` (one state read) until the state is not
    ``running``. The interval and the bound on silence are the declared settings unless given (tests)."""

    interval: float = field(default_factory=poll_seconds)
    lost_after: float = field(default_factory=lost_seconds)
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic

    def until_done(self, read: Callable[[], dict[str, Any]], what: str) -> dict[str, Any]:
        pause = min(FIRST_PAUSE, self.interval)
        answered = self.clock()
        while True:
            try:
                state = read()
            except Exception as exc:
                if not no_answer(exc):
                    raise
                silent = self.clock() - answered
                if silent > self.lost_after:
                    raise JobLost(
                        f"{what}: no answer for {silent:.0f} s (TB_JOB_LOST_SECONDS {self.lost_after:g}); its end is "
                        f"not known ({type(exc).__name__})"
                    ) from None
            else:
                answered = self.clock()
                st = state.get("state")
                if st in TERMINAL:
                    return state
                if st != "running":
                    raise JobLost(f"{what}: the service no longer knows the job (state {st!r}; it restarted)")
            self.sleep(pause)
            pause = min(pause * 2, self.interval)
