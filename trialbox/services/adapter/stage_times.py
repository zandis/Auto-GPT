"""OPT-1 §6: seconds per stage of the night and the process peak memory at each stage end, for the ingest report and
the run ledger (``night_runs.json``).

The night already names its stage in ``at["step"]`` (start, site profile, read, validate, publish:<step>, report).
:class:`Stages` is that dict: setting ``at["step"]`` closes the stage that was open, so no call site changes and no
stage is timed twice. A stage entered again adds to its seconds. ``peak_rss_mb`` is the process's high-water mark
when the stage last ended, so it never falls from one stage to the next; it is ``None`` where the platform cannot say.
:meth:`Stages.summary` closes the open stage at one timestamp and starts the next interval there, so a second summary
never counts the same seconds twice.
Names, seconds and megabytes only: no patient data.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from typing import Any


def _maxrss_mb(raw: int, platform: str) -> float:
    """``ru_maxrss`` is in kilobytes on Linux and in bytes on macOS."""
    return round(raw / (1024**2 if platform == "darwin" else 1024), 1)


def peak_rss_mb() -> float | None:
    try:
        import resource

        return _maxrss_mb(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, sys.platform)
    except (ImportError, OSError):
        return None


class Stages(dict[str, str | None]):
    def __init__(self, step: str, clock: Callable[[], float] = time.perf_counter,
                 rss: Callable[[], float | None] = peak_rss_mb) -> None:  # fmt: skip
        super().__init__(step=step, table=None)
        self._clock, self._rss = clock, rss
        self._open, self._since = step, clock()
        self._done: dict[str, dict[str, Any]] = {}

    def __setitem__(self, key: str, value: str | None) -> None:
        if key == "step" and value is not None:
            now = self._clock()
            self._close(now)
            self._open = value
        super().__setitem__(key, value)

    def _close(self, now: float) -> None:
        got = self._done.setdefault(self._open, {"seconds": 0.0, "peak_rss_mb": None})
        got["seconds"] += now - self._since
        got["peak_rss_mb"] = self._rss()
        self._since = now

    def summary(self) -> dict[str, dict[str, Any]]:
        """Close the open stage and say every stage's seconds and peak memory (rounded for the record)."""
        self._close(self._clock())
        return {k: {"seconds": round(v["seconds"], 3), "peak_rss_mb": v["peak_rss_mb"]} for k, v in self._done.items()}


__all__ = ["Stages", "peak_rss_mb"]
