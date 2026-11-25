"""A command run in a process group of its own, the whole group killed on its limit (T-695, D-752; review F-09).

``subprocess.run(timeout=...)`` kills only the process it started. The update is ``sh apply_update.sh``, which starts
the updater: on the limit the shell died and the updater went on as an orphan, changing the box while the console
reported a failure. Here the command leads a new session; on its limit the group gets SIGTERM, then SIGKILL after
:data:`TERM_GRACE_S`, and :class:`subprocess.TimeoutExpired` is raised as before."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import time
from collections.abc import Sequence
from typing import Any

TERM_GRACE_S = 10  # the group's time to stop after SIGTERM before SIGKILL (a step closes its files)
READ_STEP_S = 0.2  # in the grace: how often the leader's exit is looked at between reads of its pipes


def _kill(pgid: int, sig: int) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(pgid, sig)


def _stop(p: subprocess.Popen[Any], grace: float | None) -> tuple[Any, Any]:
    """The group's SIGTERM, its grace, its SIGKILL; what the command wrote (``communicate``'s pair, its earlier
    output included). H-114d (review 1472-1): its pipes are read through the grace, so a put-back that writes more
    than a pipe holds is not blocked on its write until the SIGKILL; the grace ends when the leader has exited (as
    ``wait`` did: a child left holding the pipes does not keep the group's SIGKILL waiting) or its time is up."""
    _kill(p.pid, signal.SIGTERM)
    end = None if grace is None else time.monotonic() + grace
    while True:
        step = READ_STEP_S if end is None else max(0.0, min(READ_STEP_S, end - time.monotonic()))
        try:
            pair = p.communicate(timeout=step)
            break  # it ended and its pipes are closed
        except subprocess.TimeoutExpired:
            if p.poll() is not None or (end is not None and time.monotonic() >= end):
                pair = None
                break
    _kill(p.pid, signal.SIGKILL)  # what ignored SIGTERM, and every child left in the group
    return pair if pair is not None else p.communicate()


def run(argv: Sequence[str], timeout: float | None = None, grace: float | None = TERM_GRACE_S,
        **kw: Any) -> subprocess.CompletedProcess[Any]:  # fmt: skip
    """:func:`subprocess.run` (``check=False``) with the command's whole process group killed on ``timeout``. H-114b:
    ``grace`` is the group's time between the SIGTERM and the SIGKILL (default :data:`TERM_GRACE_S`, as before; None:
    no SIGKILL until the command has ended by itself)."""
    stdin = kw.pop("input", None)
    with subprocess.Popen(list(argv), start_new_session=True, **kw) as p:
        try:
            out, err = p.communicate(stdin, timeout=timeout)
        except subprocess.TimeoutExpired:
            out, err = _stop(p, grace)  # H-114e (review 1472-2): what it said, the rollback's outcome too, kept
            raise subprocess.TimeoutExpired(list(argv), timeout or 0, output=out, stderr=err) from None
        except BaseException:
            _kill(p.pid, signal.SIGKILL)
            raise
    return subprocess.CompletedProcess(list(argv), p.returncode, out, err)
