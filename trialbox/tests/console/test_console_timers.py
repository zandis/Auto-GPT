"""The box's own timers for N1, N2 and the REDCap read-back (TB-PLAN-03 step 6, D-121)."""

from __future__ import annotations

from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from console import timers


@pytest.mark.parametrize(
    ("env", "on"),
    [
        ({}, True),  # D-127 (F-06): unset means PRODUCTION, so a box that forgot TB_ENV keeps its timers
        ({"TB_ENV": "DEV"}, False),
        ({"TB_ENV": "TEST"}, False),
        ({"TB_ENV": "VALIDATION"}, True),
        ({"TB_ENV": "PRODUCTION"}, True),
        ({"TB_ENV": "DEV", "TB_CONSOLE_TIMERS": "on"}, True),
        ({"TB_ENV": "PRODUCTION", "TB_CONSOLE_TIMERS": "off"}, False),
    ],
)
def test_timers_follow_the_environment(env: dict[str, str], on: bool) -> None:
    assert timers.enabled(env) is on


def test_plan_reads_local_times_and_refuses_bad_ones() -> None:
    p = {t.name: (t.hour, t.minute) for t in timers.plan({"TB_NOTICE_N1_AT": "06:45"})}
    assert p == {"redcap_read": (3, 0), "notice_n1": (6, 45), "notice_n2": (7, 30)}
    for bad in ("7am", "24:00", "07:60", ""):
        if bad:
            with pytest.raises(timers.TimerError):
                timers.plan({"TB_NOTICE_N2_AT": bad})
    with pytest.raises(timers.TimerError):
        timers.enabled({"TB_CONSOLE_TIMERS": "sometimes"})


class _Helpers:
    def __init__(self) -> None:
        self.sent: list[tuple[str, ...]] = []

    def clock(self) -> Any:
        from datetime import datetime

        return datetime(2026, 11, 9, 7, 0)

    def today(self) -> date:
        return date(2026, 11, 9)  # the site's date (Helpers.today, D-270)


def test_jobs_are_the_button_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    from console import notify, rc_read

    calls: list[tuple[Any, ...]] = []

    def send_all(h: Any, day: date, kinds: tuple[str, ...], by: str) -> list[Any]:
        calls.append(("notice", day, kinds, by))
        return []

    def run(h: Any) -> list[Any]:
        calls.append(("redcap",))
        return []

    monkeypatch.setattr(notify, "send_all", send_all)
    monkeypatch.setattr(rc_read, "run", run)
    jobs = timers.jobs(_Helpers())
    for name in ("redcap_read", "notice_n1", "notice_n2"):
        jobs[name]()
    assert calls == [
        ("redcap",),
        ("notice", date(2026, 11, 9), ("N1",), "console:timer"),
        ("notice", date(2026, 11, 9), ("N2",), "console:timer"),
    ]


def test_start_schedules_three_jobs_in_the_site_zone() -> None:
    sched = timers.start(_Helpers(), {"TB_CONSOLE_TIMERS": "on"}, ZoneInfo("Asia/Tokyo"))
    try:
        assert sorted(j.id for j in sched.get_jobs()) == ["notice_n1", "notice_n2", "redcap_read"]
        assert str(sched.timezone) == "Asia/Tokyo"
        # review F-14 (D-130): a run missed by a reboot (up to 6 h) still runs once; missed runs coalesce
        assert all(j.misfire_grace_time == 6 * 3600 and j.coalesce for j in sched.get_jobs())
    finally:
        sched.shutdown(wait=False)
    assert timers.start(_Helpers(), {"TB_ENV": "DEV"}, ZoneInfo("Asia/Tokyo")) is None


def test_a_failing_timer_does_not_raise() -> None:
    def boom() -> object:
        raise RuntimeError("smtp down")

    timers._guarded("notice_n1", boom)()  # logged, not raised
