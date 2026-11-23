"""One factor for every timing bound that the branch-coverage run would otherwise break (rc1 line 1).

The branch tracer slows Python code several times over, so a bound written for a plain run (a guard that must scan a
long line in 5 s, a whole run within 15 minutes) fails on the coverage nightly while the code is no slower. A bound
read through :func:`bound` is multiplied by :data:`COVERAGE_FACTOR` only in a pytest run that measures coverage
(``TB_COVERAGE_RUN_DIR``, set by that run itself, ``tools/coverage_shards.register``); a plain run, the pull-request
gate and a box keep the bound as written. No test and no assertion changes: only the number a bound is read from."""

from __future__ import annotations

import os

COVERAGE_FACTOR = 3
RUN_DIR_ENV = "TB_COVERAGE_RUN_DIR"  # = tools.coverage_shards.RUN_DIR_ENV


def factor() -> int:
    """3 in a run that measures coverage, else 1."""
    return COVERAGE_FACTOR if (os.environ.get(RUN_DIR_ENV) or "").strip() else 1


def bound(seconds: float) -> float:
    """``seconds`` as written for a plain run, times the coverage factor in a run that measures coverage."""
    return seconds * factor()
