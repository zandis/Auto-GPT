"""``Orchestrator.drain``: a finished job is progress however long it took; only ``total`` caps the drain."""

from __future__ import annotations

from typing import Any

import pytest
from orchestrator import core


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _orch(jobs: int, seconds_per_job: float, clock: _Clock) -> Any:
    o: Any = core.Orchestrator.__new__(core.Orchestrator)
    left = [jobs]

    class _Db:
        def claim(self) -> str | None:
            if left[0] == 0:
                return None
            left[0] -= 1
            return f"j{left[0]}"

    def run(_jid: str) -> None:
        clock.t += seconds_per_job

    o.db = _Db()
    o.run = run
    return o


def test_a_long_queue_that_keeps_moving_drains(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock()
    monkeypatch.setattr("orchestrator.core.time.monotonic", clock)
    o = _orch(jobs=5000, seconds_per_job=0.2, clock=clock)
    o.drain()
    assert clock.t == pytest.approx(1000)


def test_one_job_that_runs_for_hours_and_finishes_drains(monkeypatch: pytest.MonkeyPatch) -> None:
    """G1 of 2026-11-11: one screening job over 50,000 patients took 2.6 h and was failed as a stall."""
    clock = _Clock()
    monkeypatch.setattr("orchestrator.core.time.monotonic", clock)
    o = _orch(jobs=2, seconds_per_job=9500, clock=clock)
    o.drain()
    assert clock.t == pytest.approx(19000)


def test_the_total_cap_still_stops_a_moving_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock()
    monkeypatch.setattr("orchestrator.core.time.monotonic", clock)
    o = _orch(jobs=5000, seconds_per_job=1.0, clock=clock)
    with pytest.raises(TimeoutError, match="queue not drained"):
        o.drain(total=100)
