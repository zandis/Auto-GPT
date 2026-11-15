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
from collections.abc import Sequence
from typing import Any

TERM_GRACE_S = 10  # the group's time to stop after SIGTERM before SIGKILL (a step closes its files)


def _kill(pgid: int, sig: int) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(pgid, sig)


def run(argv: Sequence[str], timeout: float | None = None, **kw: Any) -> subprocess.CompletedProcess[Any]:
    """:func:`subprocess.run` (``check=False``) with the command's whole process group killed on ``timeout``."""
    stdin = kw.pop("input", None)
    with subprocess.Popen(list(argv), start_new_session=True, **kw) as p:
        try:
            out, err = p.communicate(stdin, timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill(p.pid, signal.SIGTERM)
            with contextlib.suppress(subprocess.TimeoutExpired):
                p.wait(TERM_GRACE_S)
            _kill(p.pid, signal.SIGKILL)  # what ignored SIGTERM, and every child left in the group
            p.communicate()
            raise subprocess.TimeoutExpired(list(argv), timeout or 0) from None
        except BaseException:
            _kill(p.pid, signal.SIGKILL)
            raise
    return subprocess.CompletedProcess(list(argv), p.returncode, out, err)
