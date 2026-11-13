"""Deep review 2026-11-13 (operations). Two gaps in the timer's ingest, the step every night starts from:

1. F-14 (D-130) says a run missed while the box was down "still runs once when the box is back" (six hours' grace).
   The scheduler's job store is in memory, so a restarted process had no record of the missed fire time: a box that
   rebooted across 02:00 (a Windows update, a power cut) ran no ingest, so no chain, that night.
2. In a zone with daylight saving time the 02:30 of the fall-back night happens twice and the timer fired twice:
   two timed ingests on one site day, so two lake generations and the chain run twice.

The rule for both: the timer's ingest runs at most once per site day, and at start the scheduler runs one that was
missed within the grace."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from orchestrator import scheduler
from tb_common.config import SCHEDULER_JOB_DEFAULTS

TZ = "Asia/Taipei"
TIMER = {"timer": "1", "chain": "1"}


def _orch(received: list[datetime], tz: str = TZ) -> Any:
    jobs = [SimpleNamespace(received_at=at, options=dict(TIMER)) for at in received]
    db = SimpleNamespace(with_option=lambda t, k, v: [j for j in jobs if t == "INGEST" and j.options.get(k) == v])
    return SimpleNamespace(db=db, cfg=SimpleNamespace(env=SimpleNamespace(tz=tz), settings=None))


@pytest.fixture
def submitted(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    out: list[tuple[Any, ...]] = []
    monkeypatch.setattr(scheduler, "_submit", lambda orch, jtype, rid=None, opts=None: out.append((jtype, rid, opts)))
    return out


def at(text: str, tz: str = TZ) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=ZoneInfo(tz))


def test_an_ingest_missed_while_the_box_was_down_runs_when_it_is_back(submitted: list[Any]) -> None:
    orch = _orch([at("2026-11-12T02:00:05")])  # last night's ran; tonight's 02:00 passed while the box was off
    assert scheduler.catch_up_ingest(orch, "02:00", now=at("2026-11-13T03:10")) is True
    assert submitted == [("INGEST", None, TIMER)]


def test_no_catch_up_when_tonights_ingest_ran_or_the_grace_has_passed(submitted: list[Any]) -> None:
    ran = _orch([at("2026-11-13T02:00:03")])
    assert scheduler.catch_up_ingest(ran, "02:00", now=at("2026-11-13T03:10")) is False
    grace_h = SCHEDULER_JOB_DEFAULTS["misfire_grace_time"] / 3600
    late = at("2026-11-13T02:00").replace(hour=2 + int(grace_h), minute=1)
    assert scheduler.catch_up_ingest(_orch([]), "02:00", now=late) is False
    assert submitted == []


def test_the_timer_ingest_runs_once_on_the_fall_back_night(submitted: list[Any]) -> None:
    tz = "Europe/Berlin"
    first = datetime(2026, 10, 25, 2, 30, tzinfo=ZoneInfo(tz), fold=0)
    orch = _orch([first], tz=tz)  # the first 02:30 (+02:00) ran; the clock goes back and 02:30 (+01:00) comes again
    second = datetime(2026, 10, 25, 2, 30, tzinfo=ZoneInfo(tz), fold=1)
    scheduler.timed_ingest(orch, now=second)
    assert submitted == []
    scheduler.timed_ingest(_orch([at("2026-10-24T02:30", tz)], tz=tz), now=second)  # yesterday's only: tonight's runs
    assert submitted == [("INGEST", None, TIMER)]
