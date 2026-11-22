"""A command puts back the logging level it found (H-87).

The drills and runs switch INFO logging off (``logging.disable(logging.INFO)``): the in-process services log every
request, and the checks are the output. A command run in a test process left it off, and every later test that reads an
INFO record failed (the polluter ``test_backup_drill_says_why``, the victims in ``test_access_log_route``). A command
wrapped in ``restores_logging_level`` puts back the level found on entry on every exit: a return, an exception and
``SystemExit`` alike.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable


def restores_logging_level[**P, R](fn: Callable[P, R]) -> Callable[P, R]:
    """``fn`` may call ``logging.disable``; the level found on entry is back when it ends, however it ends."""

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        before = logging.root.manager.disable
        try:
            return fn(*args, **kwargs)
        finally:
            logging.disable(before)

    return wrapper
