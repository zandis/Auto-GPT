"""``Orchestrator.drain``: a stall window that restarts on progress, and an optional cap on the whole drain."""

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
    o = _orch(jobs=5000, seconds_per_job=0.2, clock=clock)  # 1,000 s in all, far past one 600 s window
    o.drain(timeout=600)
    assert clock.t == pytest.approx(1000)


def test_a_stalled_queue_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock()
    monkeypatch.setattr("orchestrator.core.time.monotonic", clock)
    o = _orch(jobs=3, seconds_per_job=700, clock=clock)  # the first job alone outlasts the window
    with pytest.raises(TimeoutError, match="queue not drained"):
        o.drain(timeout=600)


def test_the_total_cap_still_stops_a_moving_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock()
    monkeypatch.setattr("orchestrator.core.time.monotonic", clock)
    o = _orch(jobs=5000, seconds_per_job=1.0, clock=clock)
    with pytest.raises(TimeoutError, match="queue not drained"):
        o.drain(timeout=600, total=100)
