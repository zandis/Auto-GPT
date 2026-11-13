"""Deep review 2026-11-13 (operations). Two gaps in the timer's ingest, the step every night starts from:

1. F-14 (D-130) says a run missed while the box was down "still runs once when the box is back" (six hours' grace).
   The scheduler's job store is in memory, so a restarted process had no record of the missed fire time: a box that
   rebooted across 02:00 (a Windows update, a power cut) ran no ingest, so no chain, that night.
2. In a zone with daylight saving time the 02:30 of the fall-back night happens twice and the timer fired twice:
   two timed ingests on one site day, so two lake generations and the chain run twice.

The rule for both: the scheduler's ingest runs once per fire time (the site's wall clock), and at start a PRODUCTION
or VALIDATION box runs one that was missed within the grace. An administrator's retry (which copies the options) is
not the timer's run, and a late ingest time caught up after midnight is not the next day's run (adversarial review)."""

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


def at(text: str, tz: str = TZ) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=ZoneInfo(tz))


class Box:
    """An orchestrator stand-in: its jobs, its schedule; ``_submit`` adds the job as the scheduler would."""

    def __init__(self, ingest: str = "02:00", tz: str = TZ, env: str = "PRODUCTION") -> None:
        self.jobs: list[Any] = []
        self.db = SimpleNamespace(
            with_option=lambda t, k, v: [j for j in self.jobs if t == "INGEST" and j.options.get(k) == v]
        )
        self.cfg = SimpleNamespace(
            env=SimpleNamespace(tz=tz, extra={"TB_ENV": env}),
            settings=SimpleNamespace(schedule=SimpleNamespace(ingest=ingest)),
        )

    def ran(self, received: datetime, by: str = "scheduler", **options: str) -> None:
        self.jobs.append(SimpleNamespace(received_at=received, requested_by=by, options={**TIMER, **options}))


@pytest.fixture
def submitted(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    out: list[tuple[Any, ...]] = []
    monkeypatch.setattr(scheduler, "_submit", lambda orch, jtype, rid=None, opts=None: out.append((jtype, rid, opts)))
    return out


def test_an_ingest_missed_while_the_box_was_down_runs_when_it_is_back(submitted: list[Any]) -> None:
    box = Box()
    box.ran(at("2026-11-12T02:00:05"), fire="2026-11-12T02:00")  # last night's ran; tonight's passed while off
    assert scheduler.catch_up_ingest(box, now=at("2026-11-13T03:10")) is True  # type: ignore[arg-type]
    assert submitted == [("INGEST", None, {**TIMER, "fire": "2026-11-13T02:00"})]


def test_no_catch_up_when_tonights_ingest_ran_or_the_grace_has_passed(submitted: list[Any]) -> None:
    ran = Box()
    ran.ran(at("2026-11-13T02:00:03"), fire="2026-11-13T02:00")
    assert scheduler.catch_up_ingest(ran, now=at("2026-11-13T03:10")) is False  # type: ignore[arg-type]
    legacy = Box()  # a job written before the fire time was recorded: received after the fire time
    legacy.ran(at("2026-11-13T02:00:03"))
    assert scheduler.catch_up_ingest(legacy, now=at("2026-11-13T03:10")) is False  # type: ignore[arg-type]
    grace_h = SCHEDULER_JOB_DEFAULTS["misfire_grace_time"] / 3600
    late = at("2026-11-13T02:00").replace(hour=2 + int(grace_h), minute=1)
    assert scheduler.catch_up_ingest(Box(), now=late) is False  # type: ignore[arg-type]
    assert submitted == []


def test_a_test_stack_started_at_night_does_not_ingest(submitted: list[Any]) -> None:
    for env in ("TEST", "DEV"):
        assert scheduler.catch_up_ingest(Box(env=env), now=at("2026-11-13T03:10")) is False  # type: ignore[arg-type]
    assert submitted == []


def test_the_timer_ingest_runs_once_on_the_fall_back_night(submitted: list[Any]) -> None:
    tz = "Europe/Berlin"
    box = Box(ingest="02:30", tz=tz)
    first = datetime(2026, 10, 25, 2, 30, tzinfo=ZoneInfo(tz), fold=0)
    assert scheduler.timed_ingest(box, now=first) is True  # type: ignore[arg-type]
    box.ran(first, **submitted[-1][2])
    second = datetime(2026, 10, 25, 2, 30, tzinfo=ZoneInfo(tz), fold=1)  # the clock went back: 02:30 again
    assert scheduler.timed_ingest(box, now=second) is False  # type: ignore[arg-type]
    assert len(submitted) == 1


def test_a_late_ingest_caught_up_after_midnight_does_not_take_the_next_nights(submitted: list[Any]) -> None:
    box = Box(ingest="23:30")
    assert scheduler.catch_up_ingest(box, now=at("2026-11-14T00:10")) is True  # type: ignore[arg-type]
    assert submitted[-1][2]["fire"] == "2026-11-13T23:30"
    box.ran(at("2026-11-14T00:10"), **submitted[-1][2])
    assert scheduler.timed_ingest(box, now=at("2026-11-14T23:30")) is True  # type: ignore[arg-type]
    assert submitted[-1][2]["fire"] == "2026-11-14T23:30"


def test_an_administrators_retry_does_not_stand_for_the_timers_run(submitted: list[Any]) -> None:
    box = Box()
    box.ran(at("2026-11-13T01:00"), by="admin")  # last night's failed ingest, retried at 01:00 (options copied)
    assert scheduler.timed_ingest(box, now=at("2026-11-13T02:00")) is True  # type: ignore[arg-type]
