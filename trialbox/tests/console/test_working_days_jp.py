"""10C-14 (JP-15): Japanese holidays and the New Year break in the working days of the mails and the visit windows.

* No coordinator digest on a holiday or in the New Year break: what a weekend gives instead (the overdue SAE reports
  only), and the full digest on the next working day; the investigator's weekly list moves to the week's first
  working day.
* Nothing about a serious adverse event waits for a working day: the SAE mails go every day and the deadlines are
  calendar days.
* A visit window the protocol counts in working days skips the holidays (Golden Week); one in calendar days does not.
* A site of another country gets exactly what it got before.
* The schedule page stores "working days" per visit and lists the site's days off, in en, ja and zh-TW.

Synthetic data only (pseudonyms, invented visits); the holidays are the Cabinet Office's public list."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from console import notify
from console.sitestore import NotifyPerson
from datacore import lifecycle as lc
from datacore.lifecycle import Visit, visit_status
from tb_common import workdays
from tb_common.workdays import for_country, for_zone

from tests.console.test_an_sae_is_told_at_once import CRC, PI
from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_lifecycle_pages import PW, lb  # noqa: F401 - the fixture is used by name
from tests.console.test_step2 import _row

JP = for_country("JP", {})
TW = for_zone("Asia/Taipei", {})
LABOUR_DAY = date(2027, 11, 23)  # 勤労感謝の日, a Tuesday
NEW_YEAR = date(2027, 1, 1)  # 元日, a Friday
BREAK = date(2026, 12, 30)  # the New Year break, a Wednesday
SEIJIN = date(2027, 1, 11)  # 成人の日, a Monday


def _life(day: str) -> dict[str, Any]:
    return {"GZQO": {"reports": [{"short": "aaaaaaaa", "due": day, "party": "sponsor"}],
                     "today": [{"short": "bbbbbbbb", "visit": "V2", "start": day, "end": day, "due": day}]}}  # fmt: skip


def _crc_rows(day: date) -> list[tuple[str, list[dict[str, Any]], dict[str, Any]]]:
    row = _row("1" * 16, f"{day.isoformat()}T09:00:00+09:00")
    return [("GZQO", [row], {"marks": [], "retry": {}, "registry": {}})]


# ---------------------------------------------------------------------------------------------- the digest
@pytest.mark.parametrize("day", [LABOUR_DAY, NEW_YEAR, BREAK])
def test_no_digest_on_a_holiday_it_comes_on_the_next_working_day(day: date) -> None:
    person = NotifyPerson("crc", None, lang="ja")
    assert notify.build_n2(CRC, person, day, _crc_rows(day), None, {"GZQO": {"today": _life("x")["GZQO"]["today"]}},
                           cal=JP) is None  # fmt: skip
    nxt = JP.next_working_day(day)
    n = notify.build_n2(CRC, person, nxt, _crc_rows(nxt), None, cal=JP)
    assert n is not None and n.log_kind == "" and n.counts["visits"] == 1  # the full digest, logged as N2
    # the same day without the Japanese calendar (as before 10C-14): the digest goes
    assert notify.build_n2(CRC, person, day, _crc_rows(day), None) is not None


def test_a_holiday_digest_carries_the_overdue_sae_reports_and_only_them() -> None:
    person = NotifyPerson("crc", None, lang="en")
    n = notify.build_n2(CRC, person, LABOUR_DAY, _crc_rows(LABOUR_DAY), None, _life("2027-11-22"), cal=JP)
    assert n is not None and n.counts.get("sae_reports") == 1 and n.log_kind == notify.WEEKEND_N2
    assert "aaaaaaaa" in n.body and "bbbbbbbb" not in n.body and "11111111" not in n.body


def test_the_weekly_investigator_list_moves_to_the_weeks_first_working_day() -> None:
    rows = [_row("1" * 16, "2027-01-13T09:00:00+09:00")]
    person = NotifyPerson("pi", None, lang="en")
    assert notify.build_n1(PI, person, SEIJIN, [("GZQO", rows)], cal=JP) is None  # 成人の日
    n = notify.build_n1(PI, person, date(2027, 1, 12), [("GZQO", rows)], cal=JP)
    assert n is not None and n.counts == {"today": 0, "week": 1} and "first working day" in n.body
    assert notify.build_n1(PI, person, date(2027, 1, 13), [("GZQO", rows)], cal=JP) is None  # once a week
    ja = notify.build_n1(PI, NotifyPerson("pi", None, lang="ja"), date(2027, 1, 12), [("GZQO", rows)], cal=JP)
    assert ja is not None and "週の最初の平日" in ja.body
    # an ordinary Monday: the Monday mail and its words, as before
    rows = [_row("1" * 16, "2027-01-20T09:00:00+09:00")]
    n = notify.build_n1(PI, person, date(2027, 1, 18), [("GZQO", rows)], cal=JP)
    assert n is not None and "comes on Monday" in n.body


# ---------------------------------------------------------------------------------------------- safety is not delayed
@pytest.mark.parametrize("day", [LABOUR_DAY, NEW_YEAR, BREAK, SEIJIN])
def test_sae_mails_go_on_a_holiday(day: date) -> None:
    n1 = notify.build_n1(PI, NotifyPerson("pi", "P1", lang="en"), day, [("GZQO", [])], {"GZQO": {"sae": 1}}, cal=JP)
    assert n1 is not None and n1.counts["sae"] == 1
    n2 = notify.build_n2(CRC, NotifyPerson("crc", None, lang="en"), day, [("GZQO", [], {})], None,
                         _life(day.isoformat()), cal=JP)  # fmt: skip
    assert n2 is not None and n2.counts["sae_reports"] == 1


def test_sae_deadlines_stay_calendar_days_on_a_holiday() -> None:
    """The reporting clock never reads the calendar: a 7-day report learned on 2027-11-16 is due on 勤労感謝の日
    and overdue the next day, not moved to the next working day."""
    rules = lc.RULE_SETS["jp_crb"].parties  # 疾病等報告: 7 days for a life-threatening reaction
    e = {"ae_serious": "1", "ae_serious_why": "2", "ae_aware": "2027-11-16", "ae_onset": "2027-11-16"}
    rows = lc.report_clock(e, LABOUR_DAY, dict(rules))
    seven = [r for r in rows if r["days"] == 7]
    assert seven and seven[0]["due"] == "2027-11-23" and not seven[0]["overdue"]
    assert next(r for r in lc.report_clock(e, date(2027, 11, 24), dict(rules)) if r["days"] == 7)["overdue"]
    import inspect

    assert "cal" not in inspect.signature(lc.report_clock).parameters  # no calendar to read


# ---------------------------------------------------------------------------------------------- visit windows
def test_a_visit_window_in_working_days_skips_golden_week() -> None:
    anchor = date(2027, 4, 2)  # day 28 is Friday 2027-04-30, the day after 昭和の日
    wd = Visit("v4", 28, 2, 3, working_days=True)
    row = visit_status(wd, anchor, {}, "on_study", date(2027, 5, 6), JP)
    assert (row["due"], row["start"], row["end"]) == ("2027-04-30", "2027-04-27", "2027-05-10")
    assert row["status"] == "open"  # 05-06: inside; in calendar days it would be overdue since 05-04
    cal_days = visit_status(Visit("v4", 28, 2, 3), anchor, {}, "on_study", date(2027, 5, 6), JP)
    assert (cal_days["start"], cal_days["end"], cal_days["status"]) == ("2027-04-28", "2027-05-03", "overdue")
    done = visit_status(wd, anchor, {"vs_status": "1", "vs_date": "2027-05-07"}, "on_study", date(2027, 5, 7), JP)
    assert done["in_window"] is True


def test_another_country_gets_exactly_what_it_got_before() -> None:
    """Byte for byte: the mails and the windows of a Taiwan site (or a site with no country) with the site's
    calendar are what they were with none, on every day of 2026-11 to 2027-01 and of Golden Week 2027."""
    one = timedelta(days=1)
    days = [date(2026, 11, 1) + one * i for i in range(92)] + [date(2027, 4, 26) + one * i for i in range(15)]
    for cal in (TW, for_zone(None, {}), for_zone("America/Chicago", {"TB_DAYS_OFF": "2026-11-26"})):
        for day in days:
            for lang in ("en", "ja", "zh-TW"):
                crc, pi = NotifyPerson("crc", None, lang=lang), NotifyPerson("pi", None, lang=lang)
                n2 = (CRC, crc, day, _crc_rows(day), None, _life("2026-11-01"))
                assert notify.build_n2(*n2, cal=cal) == notify.build_n2(*n2)
                n1 = (PI, pi, day, [("GZQO", [_row("1" * 16, f"{day}T09:00:00+09:00")])])
                assert notify.build_n1(*n1, cal=cal) == notify.build_n1(*n1)
            v = Visit("v1", 28, 3, 3)
            assert visit_status(v, day, {}, "on_study", day, cal) == visit_status(v, day, {}, "on_study", day)
    assert Visit("v1", 7, 1, 1).as_dict() == {"visit": "v1", "day": 7, "before": 1, "after": 1,
                                             "anchor": "enrolment", "labels": {}}  # fmt: skip


# ---------------------------------------------------------------------------------------------- the real pages
def test_the_orchestrator_counts_working_days_in_the_site_zone(lb: dict[str, Any]) -> None:  # noqa: F811
    no, _other = lb["nos"]
    c, csrf = login(lb["app"], "crc", PW)
    c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})
    c.get("/studies/GZQO/subjects")
    lb["oc"].put(f"/studies/GZQO/data/{no}", json={"event": "", "values": {"ic_date": "2027-03-30", "ic_version": "v1",
                                                                         "ic_copy": "1"}, "by": "crc"})  # fmt: skip
    lb["oc"].put(f"/studies/GZQO/data/{no}", json={"event": "", "values": {"en_date": "2027-04-02",
                                                                         "en_eligible": "1"}, "by": "crc"})  # fmt: skip
    lb["oc"].put("/studies/GZQO/schedule", json={"visits": [
        {"visit": "v4", "day": 28, "before": 2, "after": 3, "working_days": True},
        {"visit": "v5", "day": 28, "before": 2, "after": 3}]})  # fmt: skip
    tokyo = ZoneInfo("Asia/Tokyo")
    lb["clock"]["now"] = datetime(2027, 5, 6, 9, 0, tzinfo=tokyo)
    lb["oc"].post("/studies/GZQO/subjects/refresh", json={})
    out = lb["oc"].get(f"/studies/GZQO/subjects/{no}?today=2027-05-06").json()
    by = {v["visit"]: v for v in out["visits"]}
    assert (by["v4"]["end"], by["v4"]["status"]) == ("2027-05-10", "open")
    assert (by["v5"]["end"], by["v5"]["status"]) == ("2027-05-03", "overdue")
    sched = lb["oc"].get("/studies/GZQO/schedule").json()["visits"]
    assert [v.get("working_days", False) for v in sched] == [True, False]
    # the same box in Taipei: Monday to Friday only, no Japanese holiday skipped
    lb["clock"]["now"] = datetime(2027, 5, 6, 9, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    by = {v["visit"]: v for v in lb["oc"].get(f"/studies/GZQO/subjects/{no}?today=2027-05-06").json()["visits"]}
    assert by["v4"]["end"] == "2027-05-05"


def test_the_schedule_page_stores_working_days_and_lists_the_days_off(
    lb: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c, csrf = login(lb["app"], "crc", PW)
    sched = {"csrf": csrf, "action": "save", "visit": ["v1", "v2", ""], "label": ["", "", ""], "day": ["7", "28", ""],
             "before": ["1", "2", ""], "after": ["1", "3", ""], "anchor": ["enrolment"] * 3,
             "unit": ["days", "working", "days"]}  # fmt: skip
    r = c.post("/studies/GZQO/schedule", data=sched, follow_redirects=True)
    assert 'data-testid="schedule-saved"' in r.text
    assert re.search(r'data-testid="sched-unit-1"[^>]*>.*?<option value="working" selected>', r.text)
    assert not re.search(r'data-testid="sched-unit-0"[^>]*>.*?<option value="working" selected>', r.text)
    assert 'data-testid="days-off"' not in r.text  # the test box is in Taipei: no holiday list, no section
    # a site in Japan: the next 90 days off, with the holiday's own name
    monkeypatch.setattr(workdays, "for_zone", lambda _tz, env=None: for_country("JP", {"TB_DAYS_OFF": "x"}))
    lb["clock"]["now"] = datetime(2026, 11, 18, 1, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    for lang, title, why in (("en", "Days off at this site", "public holiday"), ("ja", "この施設の休日", "祝日"),
                             ("zh-TW", "本院休假日", "國定假日")):  # fmt: skip
        c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
        page = c.get("/studies/GZQO/schedule").text
        sec = page[page.index('data-testid="days-off"') :]
        assert title in sec and f"2026-11-23 · {why} · 勤労感謝の日" in sec
        assert "2026-12-29" in sec and "2027-01-01" in sec and "2027-01-11" in sec and "2027-02-23" not in sec
        assert 'data-testid="days-off-problems"' in sec and "TB_DAYS_OFF" in sec
