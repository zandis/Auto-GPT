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

import json
import re
import shutil
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
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
from tests.console.test_cjk_layout import PHONE, SCRIPT, _node_playwright
from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_lifecycle_pages import PW, lb  # noqa: F401 - the fixture is used by name
from tests.console.test_step2 import _row

JP = for_country("JP", {})
TW = for_zone("Asia/Taipei", {})
ROOT = Path(__file__).resolve().parents[2]
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
    # the test box is in Taipei: no holiday list, so no unit column and no days-off section (as on master)
    page = c.get("/studies/GZQO/schedule").text
    assert 'name="unit"' not in page and 'data-testid="days-off"' not in page and "Window counted in" not in page
    assert page.count("<th>") == 6
    # a site in Japan: the column, the next 90 days off with the holiday's own name
    monkeypatch.setattr(workdays, "for_zone", lambda _tz, env=None: for_country("JP", {"TB_DAYS_OFF": "x"}))
    r = c.post("/studies/GZQO/schedule", data=sched, follow_redirects=True)
    assert 'data-testid="schedule-saved"' in r.text
    assert re.search(r'data-testid="sched-unit-1"[^>]*>.*?<option value="working" selected>', r.text)
    assert not re.search(r'data-testid="sched-unit-0"[^>]*>.*?<option value="working" selected>', r.text)
    lb["clock"]["now"] = datetime(2026, 11, 18, 1, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    for lang, title, why in (("en", "Days off at this site", "public holiday"), ("ja", "この施設の休日", "祝日"),
                             ("zh-TW", "本院休假日", "國定假日")):  # fmt: skip
        c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
        page = c.get("/studies/GZQO/schedule").text
        sec = page[page.index('data-testid="days-off"') :]
        assert title in sec and f"2026-11-23 · {why} · 勤労感謝の日" in sec
        assert "2026-12-29" in sec and "2027-01-01" in sec and "2027-01-11" in sec and "2027-02-23" not in sec
        assert 'data-testid="days-off-problems"' in sec and "TB_DAYS_OFF" in sec


@pytest.mark.skipif(not _node_playwright(), reason="Node Playwright is not available")
def test_the_schedule_page_with_its_days_off_fits_a_phone_in_three_languages(
    lb: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """At 390 x 844 px the page does not scroll sideways (the schedule table scrolls in its own box, as before)."""
    monkeypatch.setattr(workdays, "for_zone", lambda _tz, env=None: for_country("JP", {}))
    lb["clock"]["now"] = datetime(2026, 12, 20, 1, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    c, csrf = login(lb["app"], "crc", PW)
    out = tmp_path / "pages"
    out.mkdir()
    pages: list[dict[str, Any]] = []
    for lang in ("en", "ja", "zh-TW"):
        c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
        page = c.get("/studies/GZQO/schedule").text
        assert 'data-testid="days-off"' in page and "2026-12-29" in page
        f = f"schedule-{lang}.html"
        (out / f).write_text(page.replace('href="/static/console.css"', 'href="console.css"'), encoding="utf-8")
        pages.append({"file": f, "lang": lang, "width": PHONE[0], "height": PHONE[1], "checks": []})
    (out / "console.css").write_text(c.get("/static/console.css").text, encoding="utf-8")
    r = subprocess.run(
        [shutil.which("node") or "node", str(SCRIPT), json.dumps({"dir": str(out), "pages": pages, "shots": ""})],
        cwd=ROOT, capture_output=True, text=True, timeout=600, check=False,
    )  # fmt: skip
    res = json.loads(r.stdout.strip().splitlines()[-1])
    assert r.returncode == 0 and res["failed"] == 0, (res.get("results"), r.stderr[-2000:])


def test_the_schedule_page_says_when_the_holiday_list_runs_out(
    lb: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workdays, "for_zone", lambda _tz, env=None: for_country("JP", {}))
    c, _csrf = login(lb["app"], "crc", PW)
    for now, words in ((datetime(2027, 6, 1, 1, 0, tzinfo=ZoneInfo("Asia/Tokyo")), None),
                       (datetime(2027, 11, 1, 1, 0, tzinfo=ZoneInfo("Asia/Tokyo")), "must bring the next year"),
                       (datetime(2028, 2, 1, 1, 0, tzinfo=ZoneInfo("Asia/Tokyo")), "now count as working days")):  # fmt: skip
        lb["clock"]["now"] = now
        page = c.get("/studies/GZQO/schedule").text
        assert ('data-testid="days-off-runs-out"' in page) == (words is not None)
        assert words is None or (words in page and "2027-12-31" in page)


# ---------------------------------------------------------------------------------------------- the review of #1126
TOKYO_BK = {"cfg": SimpleNamespace(settings=SimpleNamespace(site=SimpleNamespace(tz="Asia/Tokyo")))}


def _tokyo(life: dict[str, Any] | None = None) -> Any:
    from console.sitestore import SiteStore

    from tests.console.test_study_state_d386 import _helpers

    store = SiteStore()
    store.save_notify_person(NotifyPerson("pi", None, lang="en"))
    store.save_notify_person(NotifyPerson("crc", None, lang="en"))
    h = _helpers(store, life=life)
    h.bk = SimpleNamespace(registry_rows=lambda _rs: [], **TOKYO_BK)
    rows = [_row("1" * 16, "2026-11-24T09:00:00+09:00"), _row("2" * 16, "2026-11-26T10:00:00+09:00")]
    h.week_bundle = lambda _sess, _rs: {"rows": [dict(r) for r in rows], "cl": None}
    return h


def test_collect_reads_the_sites_calendar_for_a_tokyo_site() -> None:
    """The review's mutation: ``site_calendar`` returning Monday to Friday always went unseen. The real round, a
    Tokyo site: 勤労感謝の日 2026-11-23 (a Monday) gives no list and no digest; Tuesday gives both."""
    h = _tokyo()
    assert notify.site_calendar(h).country == "JP"
    assert notify.collect(h, date(2026, 11, 23)) == []
    got = {n.kind: n for n in notify.collect(h, date(2026, 11, 24))}
    assert set(got) == {"N1", "N2"} and "first working day" in got["N1"].body
    h.bk = SimpleNamespace(registry_rows=lambda _rs: [])  # no site zone: Monday to Friday, as before
    assert {n.kind for n in notify.collect(h, date(2026, 11, 23))} == {"N1"}  # the Monday list (no visit that day)


def test_an_investigator_without_clinic_days_gets_the_sae_mail_on_a_holiday() -> None:
    life = {"today": [], "week": [], "overdue": [], "reports": [], "sae": 1}
    for day in (LABOUR_DAY, NEW_YEAR, BREAK, SEIJIN, date(2027, 1, 13)):
        n1 = notify.build_n1(PI, NotifyPerson("pi", None, lang="en"), day, [("GZQO", [])], {"GZQO": life}, cal=JP)
        assert n1 is not None and n1.counts["sae"] == 1, day
    got = notify.collect(_tokyo(life), SEIJIN, ("N1",))
    assert len(got) == 1 and got[0].counts["sae"] == 1


class _Broken(workdays.Calendar):
    """A calendar that cannot answer (a fault in the site's days off): the safety mails must not depend on it."""

    def next_working_day(self, d: date) -> date:
        raise ValueError("no working day")

    def is_working_day(self, d: date) -> bool:
        raise ValueError("no working day")


def test_a_calendar_fault_never_stops_a_safety_mail() -> None:
    life = {"today": [], "week": [], "overdue": [], "sae": 1,
            "reports": [{"short": "aaaaaaaa", "due": "2027-01-10", "party": "sponsor"}]}  # fmt: skip
    broken = _Broken("JP", workdays.holidays("JP"))
    n1 = notify.build_n1(PI, NotifyPerson("pi", None, lang="en"), SEIJIN, [("GZQO", [])], {"GZQO": life}, cal=broken)
    assert n1 is not None and n1.counts["sae"] == 1
    h = _tokyo(life)
    original = notify.site_calendar
    try:
        notify.site_calendar = lambda _h: broken  # type: ignore[assignment]
        got = {n.kind: n for n in notify.collect(h, SEIJIN)}
    finally:
        notify.site_calendar = original
    assert got["N1"].counts["sae"] == 1 and got["N2"].counts["sae_reports"] == 1  # built again, Monday to Friday


def test_one_mail_that_cannot_be_built_does_not_stop_the_others(monkeypatch: pytest.MonkeyPatch) -> None:
    h = _tokyo()

    def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("one builder fails")

    monkeypatch.setattr(notify, "build_n1", boom)
    got = notify.collect(h, date(2026, 11, 24))
    assert [n.kind for n in got] == ["N2"]


def test_the_health_line_carries_the_calendar(lb: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    h = lb["app"].state.helpers
    assert all(c.name != "calendar" for c in h.health().checks)  # Taipei: no line, as before
    monkeypatch.setattr(workdays, "for_zone", lambda _tz, env=None: for_country("JP", {}))
    lb["clock"]["now"] = datetime(2028, 1, 4, 1, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    line = next(c for c in h.health().checks if c.name == "calendar")
    assert line.level == "red" and "2027-12-31" in line.text and h.health().level == "red"


def test_the_data_core_upgrade_adds_the_working_days_column(db_url: str) -> None:
    """A data core at version 9 (master before 10C-14), with a saved schedule, is migrated by the next start: the
    column is added, the old schedule reads as calendar days, and a working-days visit can be saved."""
    from datacore import lifecycle as life_mod
    from datacore import sponsor
    from datacore import store as dstore
    from tb_common.db import Database

    with Database.connect(db_url, "datacore") as db:
        db.migrate([dstore.SCHEMA, life_mod.SCHEMA, *life_mod.SAE_MIGRATIONS, sponsor.SCHEMA, dstore.HISTORY_REASON])
        db.execute("INSERT INTO schedule (study, visit, seq, labels, anchor, day, win_before, win_after, origin, at) "
                   "VALUES ('UPG', 'v1', 0, '{}', 'enrolment', 7, 1, 1, 'trialbox', '2026-11-01')")  # fmt: skip
    dc = dstore.DataCore(db_url)
    try:
        life = life_mod.Lifecycle(dc)
        assert life.schedule("UPG") == [Visit("v1", 7, 1, 1)]
        life.set_schedule("UPG", [Visit("v1", 7, 1, 1, working_days=True)], "trialbox", "2026-11-19")
        assert life.schedule("UPG")[0].working_days and life.schedule_on("UPG", date(2027, 1, 1))[0].working_days
    finally:
        dc.close()


# ---------------------------------------------------------------------------------------------- the second review
def _wd_subject(lb: dict[str, Any]) -> str:  # noqa: F811
    """A participant enrolled 2027-04-02 with v4 (day 28 = Friday 2027-04-30, 2 working days before, 3 after)."""
    no, _other = lb["nos"]
    c, csrf = login(lb["app"], "crc", PW)
    c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})
    c.get("/studies/GZQO/subjects")
    for values in ({"ic_date": "2027-03-30", "ic_version": "v1", "ic_copy": "1"},
                   {"en_date": "2027-04-02", "en_eligible": "1"}):  # fmt: skip
        lb["oc"].put(f"/studies/GZQO/data/{no}", json={"event": "", "values": values, "by": "crc"})
    lb["oc"].put("/studies/GZQO/schedule", json={"visits": [{"visit": "v4", "day": 28, "before": 2, "after": 3,
                                                            "working_days": True}]})  # fmt: skip
    lb["clock"]["now"] = datetime(2027, 5, 6, 9, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    lb["oc"].post("/studies/GZQO/subjects/refresh", json={})
    return str(no)


def test_every_route_passes_the_sites_calendar(lb: dict[str, Any]) -> None:  # noqa: F811
    """The second review (H): a hand mutation that dropped the calendar from /visits, /subjects, the possible
    deviations, their decision or the old-schedule judgement of a done visit went unseen. Each is held here, on a
    Tokyo site in Golden Week: in working days v4's window ends 2027-05-10; in Monday-to-Friday days 05-05."""
    no = _wd_subject(lb)
    rows = lb["oc"].get("/studies/GZQO/visits?today=2027-05-06").json()["rows"]
    assert [(r["visit"], r["end"], r["status"]) for r in rows] == [("v4", "2027-05-10", "open")]
    sub = next(s for s in lb["oc"].get("/studies/GZQO/subjects?today=2027-05-06").json()["subjects"]
               if s["record"] == no)  # fmt: skip
    assert sub["visits"]["open"] == 1 and sub["visits"]["overdue"] == 0
    # done on 05-07: inside the working-days window, outside a Monday-to-Friday one
    lb["oc"].put(f"/studies/GZQO/data/{no}", json={"event": "v4", "values": {"vs_status": "1",
                                                                           "vs_date": "2027-05-07"}, "by": "crc"})  # fmt: skip
    lb["clock"]["now"] = datetime(2027, 5, 11, 9, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    props = lb["oc"].get("/studies/GZQO/deviations/possible?today=2027-05-11").json()["rows"]
    assert not [p for p in props if p["kind"] == "visit_window"]
    r = lb["oc"].post("/studies/GZQO/deviations/possible", json={"record": no, "key": "visit_window:v4",
                                                                 "decision": "dismiss", "reason": "x",
                                                                 "today": "2027-05-11"})  # fmt: skip
    assert r.status_code == 409 and "proposal" in r.text  # no such proposal with the site's calendar
    # a later schedule (from 05-08, no days after): the done visit is judged by the one in force on 05-07
    lb["oc"].put("/studies/GZQO/schedule", json={"effective_from": "2027-05-08", "visits": [
        {"visit": "v4", "day": 28, "before": 2, "after": 0, "working_days": True}]})  # fmt: skip
    v = next(x for x in lb["oc"].get(f"/studies/GZQO/subjects/{no}?today=2027-05-11").json()["visits"]
             if x["visit"] == "v4")  # fmt: skip
    assert v["status"] == "done" and v["in_window"] is True and v["end"] == "2027-05-10"


def test_a_get_then_put_keeps_working_days_and_redcap_keeps_them(lb: dict[str, Any]) -> None:  # noqa: F811
    """The second review (C): the JSON route and the REDCap import dropped the field."""
    from fastapi.testclient import TestClient

    c = TestClient(lb["app"])
    c.headers["Authorization"] = (
        "Bearer " + c.post("/api/v1/session", json={"username": "crc", "password": PW}).json()["token"]
    )
    lb["oc"].put("/studies/GZQO/schedule", json={"visits": [{"visit": "v4", "day": 28, "before": 2, "after": 3,
                                                            "working_days": True}, {"visit": "v5", "day": 56}]})  # fmt: skip
    got = c.get("/api/v1/studies/GZQO/schedule").json()["visits"]
    assert c.put("/api/v1/studies/GZQO/schedule", json={"visits": got}).status_code == 200
    again = lb["oc"].get("/studies/GZQO/schedule").json()["visits"]
    assert [(v["visit"], v.get("working_days", False)) for v in again] == [("v4", True), ("v5", False)]
    # REDCap's events read again: the visit counted in working days keeps it; a new event counts calendar days
    from fastapi import FastAPI
    from orchestrator.datacore_api import DataService
    from orchestrator.lifecycle_api import router as life_router

    from tests.actor3 import SignedClient

    class Rc:
        def __enter__(self) -> Any:
            return self

        def __exit__(self, *_a: Any) -> None:
            return None

        def events(self) -> list[dict[str, Any]]:
            return [
                {"unique_event_name": "v4", "day_offset": 28, "offset_min": 2, "offset_max": 3, "arm_num": 1},
                {"unique_event_name": "v6", "day_offset": 84, "offset_min": 7, "offset_max": 7, "arm_num": 1},
            ]

    svc = DataService(lb["dc"], lb["audit"], lambda: lb["clock"]["now"], lambda _ref: Rc(), None, lb["reg"])  # type: ignore[arg-type,return-value]
    api = FastAPI()
    api.include_router(life_router(lambda: svc))
    r = SignedClient(api).post("/studies/GZQO/schedule/redcap", json={"token_ref": "main"})
    assert r.status_code == 200, r.text
    assert [(v["visit"], v.get("working_days", False)) for v in r.json()["visits"]] == [("v4", True), ("v6", False)]


def test_a_window_whose_calendar_fails_counts_calendar_days_and_a_safety_mail_survives_overflow() -> None:
    class NoDays(workdays.Calendar):
        def add_working_days(self, d: date, n: int) -> date:
            raise ValueError("no working day")

    class Overflow(workdays.Calendar):
        def next_working_day(self, d: date) -> date:
            raise OverflowError("date value out of range")

    row = visit_status(Visit("v4", 28, 2, 3, working_days=True), date(2027, 4, 2), {}, "on_study", date(2027, 5, 6),
                       NoDays("JP", workdays.holidays("JP")))  # fmt: skip
    assert (row["start"], row["end"], row["status"]) == ("2027-04-28", "2027-05-03", "overdue")
    life = {"GZQO": {"today": [], "week": [], "overdue": [], "reports": [], "sae": 1}}
    n1 = notify.build_n1(PI, NotifyPerson("pi", None, lang="en"), date(9999, 12, 27), [("GZQO", [])], life,
                         cal=Overflow("JP", workdays.holidays("JP")))  # fmt: skip
    assert n1 is not None and n1.counts["sae"] == 1


def test_a_damaged_holiday_file_never_stops_the_round(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The second review (A): a bad kind in the file raised inside ``site_calendar`` before any mail was built."""
    (tmp_path / "holidays_jp.csv").write_text("date,name,kind\n2026-11-23,勤労感謝の日,festival\n", encoding="utf-8")
    monkeypatch.setattr(workdays, "SRC", tmp_path)
    workdays.holidays.cache_clear()
    try:
        life = {"today": [], "week": [], "overdue": [], "sae": 1,
                "reports": [{"short": "aaaaaaaa", "due": "2026-11-22", "party": "sponsor"}]}  # fmt: skip
        h = _tokyo(life)
        cal = notify.site_calendar(h)
        assert cal.broken and workdays.health(cal, date(2026, 11, 23))[0] == "red"  # type: ignore[index]
        got = {n.kind: n for n in notify.collect(h, date(2026, 11, 23))}  # Monday to Friday: a working day
        assert got["N1"].counts["sae"] == 1 and got["N2"].counts["sae_reports"] == 1
    finally:
        monkeypatch.undo()
        workdays.holidays.cache_clear()


def test_a_window_past_the_list_says_its_holidays_are_not_known() -> None:
    """The second review (D): a working-days window reaching 2028 (after the list) or 2024 (before it)."""
    late = visit_status(Visit("v9", 28, 2, 5, working_days=True), date(2027, 12, 1), {}, "on_study",
                        date(2027, 12, 1), JP)  # fmt: skip
    assert late["end"] > "2027-12-31" and late["days_off_unknown"] is True
    early = visit_status(Visit("v1", 7, 2, 2, working_days=True), date(2024, 12, 20), {}, "on_study",
                         date(2024, 12, 20), JP)  # fmt: skip
    assert early["days_off_unknown"] is True
    inside = visit_status(Visit("v4", 28, 2, 3, working_days=True), date(2027, 4, 2), {}, "on_study",
                          date(2027, 5, 6), JP)  # fmt: skip
    assert "days_off_unknown" not in inside
    plain = visit_status(Visit("v9", 28, 2, 5), date(2027, 12, 1), {}, "on_study", date(2027, 12, 1), JP)
    assert "days_off_unknown" not in plain  # a calendar-day window reads as before
