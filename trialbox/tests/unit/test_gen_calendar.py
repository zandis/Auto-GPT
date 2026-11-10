"""tools/gen_calendar.py (TB-PLAN-06 T-662): the plan calendar is data, checked by weekday and by site days off."""

from __future__ import annotations

import copy
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools import gen_calendar as gc

BASE: dict[str, Any] = {
    "window": {"start": "2027-04-01", "end": "2027-05-31"},
    "sites": {"TW": "Taiwan", "JP": "Japan"},
    "milestones": [{"id": "G9", "date": "2027-04-28", "day": "Wed", "what": "x", "sites": ["TW", "JP"]}],
    "sources": {
        "TW": {2027: {"status": "verified", "checked": "2026-11-10", "url": "https://example.org/tw", "file": "tw"}},
        "JP": {2027: {"status": "verified", "checked": "2026-11-10", "url": "https://example.org/jp", "file": "jp"}},
    },
    "holidays": {
        "TW": [{"date": "2027-04-30", "day": "Fri", "kind": "holiday", "name": "補假"}],
        "JP": [{"date": "2027-04-29", "day": "Thu", "kind": "holiday", "name": "昭和の日"}],
    },
}


def cal() -> gc.Calendar:
    return gc.parse(copy.deepcopy(BASE))


def test_committed_calendar_is_clean_and_every_year_is_sourced() -> None:
    c = gc.load()
    errors, notes = gc.check(c)
    assert errors == []
    for site in c.sites:
        for year in gc.years(c):
            assert c.sources[site][year]["url"].startswith("https://")
    print("\n".join(notes))


def test_committed_milestones_are_the_build_milestones_only() -> None:
    c = gc.load()
    assert [(m.id, str(m.date)) for m in c.milestones] == [
        ("GP-0", "2026-11-27"),
        ("G1", "2026-12-04"),
        ("G1b", "2026-12-11"),
        ("G2", "2027-01-08"),
        ("G3", "2027-02-26"),
    ]


@pytest.mark.parametrize(
    ("site", "day", "why"),
    [
        ("TW", date(2026, 12, 25), "PLAN-013 (c) 行憲紀念日"),
        ("TW", date(2027, 2, 4), "PLAN-013 (a) 小年夜"),
        ("TW", date(2027, 4, 6), "PLAN-013 (b) 清明 substitute"),
        ("TW", date(2027, 4, 30), "PLAN-012 Labour Day substitute"),
        ("JP", date(2026, 12, 29), "PLAN-013 (d) 年末年始"),
    ],
)
def test_committed_calendar_answers_the_confirm_items(site: str, day: date, why: str) -> None:
    assert not gc.is_working_day(gc.load(), site, day), why


def test_wrong_weekday_on_a_milestone_fails() -> None:
    data = copy.deepcopy(BASE)
    data["milestones"][0]["day"] = "Thu"
    errors, _ = gc.check(gc.parse(data))
    assert errors == ["G9 2027-04-28: printed Thu, is Wed"]


def test_wrong_weekday_on_a_holiday_fails() -> None:
    data = copy.deepcopy(BASE)
    data["holidays"]["TW"][0]["day"] = "Thu"
    errors, _ = gc.check(gc.parse(data))
    assert errors == ["TW 2027-04-30 補假: printed Thu, is Fri"]


def test_milestone_on_a_holiday_of_its_site_fails() -> None:
    data = copy.deepcopy(BASE)
    data["milestones"][0].update(date="2027-04-30", day="Fri")
    errors, _ = gc.check(gc.parse(data))
    assert errors == ["G9 2027-04-30: on a day off at TW (補假)"]


def test_milestone_on_a_holiday_of_another_site_passes() -> None:
    data = copy.deepcopy(BASE)
    data["milestones"][0].update(date="2027-04-30", day="Fri", sites=["JP"])
    assert gc.check(gc.parse(data)) == ([], [])


def test_milestone_on_a_weekend_fails() -> None:
    data = copy.deepcopy(BASE)
    data["milestones"][0].update(date="2027-05-01", day="Sat", sites=["JP"])
    assert gc.check(gc.parse(data))[0] == ["G9 2027-05-01: on a weekend"]


def test_a_year_without_source_fails_and_unverified_is_a_note() -> None:
    data = copy.deepcopy(BASE)
    del data["sources"]["JP"]
    data["sources"]["TW"][2027] = {"status": "unverified"}
    errors, notes = gc.check(gc.parse(data))
    assert errors == ["JP 2027: no source"]
    assert notes == ["TW 2027: holidays unverified, source could not be fetched"]


def test_a_holiday_outside_the_window_or_twice_fails() -> None:
    data = copy.deepcopy(BASE)
    data["holidays"]["JP"].append({"date": "2027-04-29", "day": "Thu", "kind": "holiday", "name": "昭和の日"})
    data["holidays"]["JP"].append({"date": "2027-06-01", "day": "Tue", "kind": "rest", "name": "x"})
    errors, _ = gc.check(gc.parse(data))
    assert "JP 2027-04-29 昭和の日: listed twice" in errors
    assert "JP 2027-06-01 x: outside the window 2027-04-01 to 2027-05-31" in errors
    assert any("kind 'rest'" in e for e in errors)


def test_check_exits_1_on_an_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data = copy.deepcopy(BASE)
    data["milestones"][0]["day"] = "Mon"
    path = tmp_path / "calendar.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    assert gc.main(["--file", str(path), "--check"]) == 1
    assert "printed Mon, is Wed" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("site", "start", "end", "wd"),
    [
        ("TW", "2027-03-29", "2027-04-23", 18),  # PLAN-011: CGMH PQ window of TB-PLAN-06 §2.1
        ("JP", "2027-04-12", "2027-05-12", 19),  # PLAN-011: Japan PQ window of TB-PLAN-06 §2.1
        ("JP", "2027-05-06", "2027-05-12", 5),  # PLAN-011: Japan PQ after Golden Week
        ("TW", "2027-04-26", "2027-04-30", 4),  # PLAN-012: CGMH go-live week
    ],
)
def test_span_prints_working_days(site: str, start: str, end: str, wd: int, capsys: pytest.CaptureFixture[str]) -> None:
    assert gc.main(["--span", site, start, end]) == 0
    line = capsys.readouterr().out.strip().splitlines()[-1]
    assert line == f"{site} {start}..{end} wd {wd}"
    print(line)


def test_render_is_one_table_by_date() -> None:
    out = gc.render(cal()).splitlines()
    assert out[0] == "| Date | Day | Site or milestone | What |"
    assert [r.split(" | ")[0] for r in out[2:]] == ["| 2027-04-28", "| 2027-04-29", "| 2027-04-30"]


JP_CSV = "国民の祝日・休日月日,国民の祝日・休日名称\n2027/4/29,昭和の日\n2027/5/3,憲法記念日\n"
TW_CSV = "﻿西元日期,星期,是否放假,備註\n20270429,四,0,\n20270430,五,2,補假\n20270501,六,2,勞動節\n20270502,日,2,\n20270508,六,0,補行上班\n"


def test_parse_official_files() -> None:
    assert gc.parse_jp_csv(JP_CSV) == {date(2027, 4, 29): "昭和の日", date(2027, 5, 3): "憲法記念日"}
    named, makeup = gc.parse_tw_csv(TW_CSV)
    assert named == {date(2027, 4, 30): "補假", date(2027, 5, 1): "勞動節"}
    assert makeup == [date(2027, 5, 8)]
    assert gc.jp_closures(date(2026, 12, 1), date(2027, 1, 31)) == {
        date(2026, 12, 29): "年末年始",
        date(2026, 12, 30): "年末年始",
        date(2026, 12, 31): "年末年始",
        date(2027, 1, 2): "年末年始",
        date(2027, 1, 3): "年末年始",
    }


def test_verify_sources_reports_each_difference() -> None:
    files = {"jp": JP_CSV.encode("shift_jis"), "tw": TW_CSV.encode("utf-8")}
    errors = gc.verify_sources(cal(), fetch=files.__getitem__)
    assert errors == [
        "JP 2027-05-03: official 憲法記念日 missing from the file",
        "TW 2027-05-08: make-up working day, not modelled",
        "TW 2027-05-01: official 勞動節 missing from the file",
    ]
