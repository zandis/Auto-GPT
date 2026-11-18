"""10C-14 (JP-15): the site's working days as data (``tb_common.workdays``).

Japan's holidays come from the Cabinet Office's list (``refdata_src/holidays_jp.csv``, 2025 to 2027); the New Year
break is the country's default and the site's to change; a site of another country, or with no country, keeps
Monday to Friday exactly. Public data only (the Cabinet Office list); no patient data."""

from __future__ import annotations

import ast
import csv
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml
from tb_common import workdays
from tb_common.workdays import WEEKDAYS_ONLY, for_country, for_zone

ROOT = Path(__file__).resolve().parents[2]
JP = for_country("JP", {})


def _all_days(first: date, last: date) -> list[date]:
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


# ---------------------------------------------------------------------------------------------- the data
def test_three_years_of_national_holidays_from_the_cabinet_office_list() -> None:
    hol = workdays.holidays("JP")
    assert hol is not None and hol.until == date(2027, 12, 31)
    by_year = {y: sorted(d for d in hol.days if d.year == y) for y in (2025, 2026, 2027)}
    assert {y: len(v) for y, v in by_year.items()} == {2025: 19, 2026: 18, 2027: 17}
    assert JP.day_off(date(2026, 1, 1)) == "holiday" and JP.name(date(2026, 1, 1)) == "元日"
    assert JP.day_off(date(2027, 11, 23)) == "holiday" and JP.name(date(2027, 11, 23)) == "勤労感謝の日"
    assert JP.day_off(date(2025, 1, 13)) == "holiday"  # 成人の日, the second Monday


def test_substitute_and_citizens_holidays() -> None:
    # 振替休日: a holiday on a Sunday moves to the next day that is not one (2026-05-03 Sun -> after 4 and 5: the 6th)
    assert JP.day_off(date(2026, 5, 6)) == "substitute"
    assert JP.day_off(date(2027, 3, 22)) == "substitute"  # 春分の日 2027-03-21 is a Sunday
    # 国民の休日: a day between two holidays (敬老の日 2026-09-21 and 秋分の日 2026-09-23)
    assert JP.day_off(date(2026, 9, 22)) == "citizens"
    kinds = {d: k for d, (_n, k) in workdays.holidays("JP").days.items()}  # type: ignore[union-attr]
    assert sorted(d.isoformat() for d, k in kinds.items() if k != "holiday") == [
        "2025-02-24", "2025-05-06", "2025-11-24", "2026-05-06", "2026-09-22", "2027-03-22",
    ]  # fmt: skip


def test_a_holiday_on_a_weekend() -> None:
    """A holiday on a Saturday has no substitute (2025-05-03, 憲法記念日); one on a Sunday has (2025-11-23, the 24th
    is off). Either way the weekend day was off already: it is a weekend, not a holiday, for the rules."""
    assert JP.day_off(date(2025, 5, 3)) == "weekend" and JP.name(date(2025, 5, 3)) == "憲法記念日"
    subs = [d for d, (_n, k) in workdays.holidays("JP").days.items() if k == "substitute" and d.year == 2025]  # type: ignore[union-attr]
    assert sorted(subs) == [date(2025, 2, 24), date(2025, 5, 6), date(2025, 11, 24)]  # none for the Saturday
    assert JP.day_off(date(2025, 11, 23)) == "weekend" and JP.day_off(date(2025, 11, 24)) == "substitute"
    assert JP.next_working_day(date(2025, 11, 22)) == date(2025, 11, 25)


def test_the_file_agrees_with_the_plan_calendar_read_from_the_same_source() -> None:
    """``docs/plan/calendar.yaml`` holds Japan's holidays of 2026-11 to 2027-06, read from the same Cabinet Office
    file on 2026-11-10 (``tools.gen_calendar``): the two never disagree."""
    doc = yaml.safe_load((ROOT / "docs/plan/calendar.yaml").read_text(encoding="utf-8"))
    rows = [r for r in doc["holidays"]["JP"] if r["kind"] == "holiday"]
    start, end = doc["window"]["start"], doc["window"]["end"]
    ours = {d for d in workdays.holidays("JP").days if start <= d <= end}  # type: ignore[union-attr]
    assert {r["date"] for r in rows} == ours
    closure = {r["date"] for r in doc["holidays"]["JP"] if r["kind"] == "closure"}
    assert closure == {d for d in _all_days(start, end) if JP._in_break(d) and d not in ours}


def test_the_holiday_file_keeps_the_source_columns_and_kinds() -> None:
    with (ROOT / "libs/tb_common/refdata_src/holidays_jp.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert list(rows[0]) == ["date", "name", "kind"]
    assert {r["kind"] for r in rows} == set(workdays.KINDS)
    assert all(r["name"] == "休日" for r in rows if r["kind"] != "holiday")  # the source's word, unchanged


# ---------------------------------------------------------------------------------------------- the New Year break
def test_the_new_year_break_across_the_year_end() -> None:
    days = _all_days(date(2026, 12, 26), date(2027, 1, 5))
    off = {d.isoformat(): JP.day_off(d) for d in days if JP.day_off(d)}
    assert off == {
        "2026-12-26": "weekend", "2026-12-27": "weekend", "2026-12-29": "new_year", "2026-12-30": "new_year",
        "2026-12-31": "new_year", "2027-01-01": "holiday", "2027-01-02": "weekend", "2027-01-03": "weekend",
    }  # fmt: skip
    assert JP.is_working_day(date(2026, 12, 28)) and JP.is_working_day(date(2027, 1, 4))
    assert JP.next_working_day(date(2026, 12, 29)) == date(2027, 1, 4)
    assert JP.add_working_days(date(2026, 12, 28), 1) == date(2027, 1, 4)


def test_a_site_changes_its_break_and_its_own_days() -> None:
    cal = for_country("JP", {"TB_NEW_YEAR_BREAK": "12-30/01-02", "TB_DAYS_OFF": "2027-08-13, 2027-08-16",
                             "TB_DAYS_OPEN": "2026-12-31"})  # fmt: skip
    assert cal.problems == ()
    assert cal.is_working_day(date(2026, 12, 29)) and cal.is_working_day(date(2026, 12, 31))  # open on the 31st
    assert cal.day_off(date(2026, 12, 30)) == "new_year" and cal.is_working_day(date(2027, 1, 4))
    assert cal.day_off(date(2027, 8, 13)) == "site" and cal.day_off(date(2027, 8, 16)) == "site"
    assert for_country("JP", {"TB_NEW_YEAR_BREAK": "none"}).is_working_day(date(2026, 12, 30))
    open_holiday = for_country("JP", {"TB_DAYS_OPEN": "2027-11-23"})
    assert open_holiday.is_working_day(date(2027, 11, 23))
    assert not open_holiday.is_working_day(date(2027, 11, 20))  # "open" never makes a weekend a working day


def test_settings_that_cannot_be_read_are_shown_not_guessed() -> None:
    cal = for_country("JP", {"TB_NEW_YEAR_BREAK": "29 Dec", "TB_DAYS_OFF": "2027-02-30,2027-08-13"})
    assert cal.problems == ("TB_NEW_YEAR_BREAK=29 Dec", "TB_DAYS_OFF/TB_DAYS_OPEN: 2027-02-30")
    assert cal.day_off(date(2026, 12, 29)) == "new_year"  # the country's break stands
    assert cal.day_off(date(2027, 8, 13)) == "site"  # the readable part is used
    with pytest.raises(ValueError):
        workdays.parse_break("13-01/01-03")


# ---------------------------------------------------------------------------------------------- unchanged elsewhere
@pytest.mark.parametrize("tz", ["Asia/Taipei", "America/New_York", "Europe/Berlin", "", None])
def test_another_country_or_none_is_monday_to_friday_exactly(tz: str | None) -> None:
    env = {"TB_NEW_YEAR_BREAK": "12-29/01-03", "TB_DAYS_OFF": "2026-11-18", "TB_DAYS_OPEN": "2026-11-21"}
    cal = for_zone(tz, env)
    assert cal is WEEKDAYS_ONLY and not cal.has_days_off  # the site's changes are not read either
    for d in _all_days(date(2025, 1, 1), date(2027, 12, 31)):
        assert cal.is_working_day(d) == (d.weekday() < 5)
    assert workdays.holidays("TW") is None and workdays.holidays("../x") is None


def test_working_day_arithmetic() -> None:
    fri = date(2027, 4, 30)  # Golden Week: 04-29, 05-03, 05-04, 05-05 are holidays
    assert JP.add_working_days(fri, 3) == date(2027, 5, 10)
    assert JP.add_working_days(fri, -2) == date(2027, 4, 27)
    assert JP.add_working_days(fri, 0) == fri
    assert WEEKDAYS_ONLY.add_working_days(fri, 3) == date(2027, 5, 5)
    assert [d for d, _w, _n in JP.days_off(date(2027, 4, 26), date(2027, 5, 10))] == [
        date(2027, 4, 29), date(2027, 5, 3), date(2027, 5, 4), date(2027, 5, 5),
    ]  # fmt: skip


def test_the_site_zone_decides_the_day() -> None:
    """2027-01-03 15:30 UTC is 2027-01-04 00:30 in Tokyo: the site's first working day of the year, though the UTC
    date is still in the New Year break. The callers pass the site's date (``console.timefmt.local_today``)."""
    from console.timefmt import local_today

    now = datetime(2027, 1, 3, 15, 30, tzinfo=UTC)
    site_day = local_today(now, ZoneInfo("Asia/Tokyo"))
    assert site_day == date(2027, 1, 4) and JP.is_working_day(site_day)
    assert not JP.is_working_day(now.date())


def test_the_module_imports_under_python_3_10() -> None:
    """The settings wizard imports it with the host's ``python3`` (Ubuntu 22.04: 3.10)."""
    src = (ROOT / "libs/tb_common/workdays.py").read_text(encoding="utf-8")
    ast.parse(src, feature_version=(3, 10))
    tree = ast.parse(src)
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imported <= {"__future__", "csv", "os", "re", "collections", "dataclasses", "datetime", "functools",
                        "pathlib", "tb_common"}  # fmt: skip


# ---------------------------------------------------------------------------------------------- the settings wizard
def test_the_wizard_asks_the_new_year_break_for_japan_only() -> None:
    from tb_common import site_country

    from tools import settings_wizard as sw

    assert sw._asked("new_year_break", site_country.defaults("jp"), {})
    assert not sw._asked("new_year_break", site_country.defaults("tw"), {})
    assert not sw._asked("new_year_break", site_country.LEGACY, {})
    assert sw.new_year_default("jp") == "12-29/01-03"
    errors: list[str] = []
    assert sw.new_year_env("jp", "12-29/01-03", errors) == {}  # the country's own: nothing written
    assert sw.new_year_env("jp", "", errors) == {}
    assert sw.new_year_env("jp", "12-28/01-04", errors) == {"TB_NEW_YEAR_BREAK": "12-28/01-04"}
    assert sw.new_year_env("jp", "none", errors) == {"TB_NEW_YEAR_BREAK": "none"}
    assert errors == []
    assert sw.new_year_env("jp", "Dec 28", errors) == {} and errors[-1].startswith("new_year_break:")
    assert sw.new_year_env("tw", "12-28/01-04", errors) == {} and "no holiday list" in errors[-1]
