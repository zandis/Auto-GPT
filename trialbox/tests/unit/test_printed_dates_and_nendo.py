"""10C-13 (JP-14) and 10C-15 (JP-16): printed dates in Western, 和暦 or both, and the fiscal year 年度.

The eras come from the one table ``tb_common.dates.ERAS``; a printed page writes a date through
``tb_common.dates.printed``; a yearly count asks ``tb_common.dates.in_year`` with the site's zone."""

from __future__ import annotations

import os
import time
from datetime import UTC, date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from tb_common import dates

pytestmark = pytest.mark.nodb

TOKYO = ZoneInfo("Asia/Tokyo")


@pytest.mark.parametrize(
    ("day", "era", "both"),
    [
        ("1989-01-07", "昭和64年1月7日", "1989年（昭和64年）1月7日"),  # the last day of 昭和
        ("1989-01-08", "平成元年1月8日", "1989年（平成元年）1月8日"),  # the first day of 平成: 元年
        ("2019-04-30", "平成31年4月30日", "2019年（平成31年）4月30日"),
        ("2019-05-01", "令和元年5月1日", "2019年（令和元年）5月1日"),
        ("2026-11-18", "令和8年11月18日", "2026年（令和8年）11月18日"),
        ("1926-12-25", "昭和元年12月25日", "1926年（昭和元年）12月25日"),
        ("1912-07-30", "大正元年7月30日", "1912年（大正元年）7月30日"),
    ],
)
def test_dates_across_the_era_changes_print_right(day: str, era: str, both: str) -> None:
    assert dates.printed(day, "era") == era
    assert dates.printed(date.fromisoformat(day), "era") == era
    assert dates.printed(day, "both") == both
    assert dates.printed(day + "T10:00:00+09:00", "era") == era  # a stamp prints its day


def test_the_first_year_of_an_era_is_gannen_and_the_second_is_two() -> None:
    assert dates.era_year(date(2019, 12, 31)) == "令和元年"
    assert dates.era_year(date(2020, 1, 1)) == "令和2年"
    assert dates.era_of(date(1868, 10, 22)) is None  # before the first era of the table: printed as it is
    assert dates.printed("1868-10-22", "era") == "1868-10-22"


def test_western_and_anything_unreadable_print_exactly_as_before() -> None:
    for value in ("2026-11-18", date(2026, 11, 18), "2026-11-18T09:00:00+09:00", "—", "", "None", "2026-13-40"):
        before = value.isoformat() if isinstance(value, date) else str(value)
        assert dates.printed(value, "western") == before
        assert dates.printed(value, None) == before
        assert dates.printed(value, "nonsense") == before
    for value in ("—", "", "2026-13-40"):  # an era form never invents a date
        assert dates.printed(value, "both") == value


def test_a_future_era_is_a_row_of_the_table(monkeypatch: pytest.MonkeyPatch) -> None:
    eras = dict(dates.ERAS)
    eras["次元"] = (2040, date(2041, 1, 1), None)  # a made-up era, for the test only
    monkeypatch.setattr(dates, "ERAS", eras)
    assert dates.printed("2041-01-01", "era") == "次元元年1月1日"
    assert dates.printed("2040-12-31", "era") == "令和22年12月31日"


def test_defaults_follow_the_country_and_an_answer_wins() -> None:
    jp = SimpleNamespace(tz="Asia/Tokyo", locale="ja")
    tw = SimpleNamespace(tz="Asia/Taipei", locale="zh-TW")
    us = SimpleNamespace(tz="America/New_York", locale="en")
    assert dates.site_dates(jp) == ("both", "fiscal")
    assert dates.site_dates(tw) == ("western", "calendar")
    assert dates.site_dates(us) == ("western", "calendar")
    assert dates.site_dates(None) == ("western", "calendar")
    assert dates.site_dates(SimpleNamespace(tz="Asia/Tokyo", printed_dates="western", year_basis=None)) == (
        "western",
        "fiscal",
    )
    assert dates.site_dates(SimpleNamespace(tz="Asia/Taipei", printed_dates="era", year_basis="fiscal")) == (
        "era",
        "fiscal",
    )


def test_the_settings_file_takes_the_two_answers_and_refuses_others() -> None:
    from pydantic import ValidationError
    from tb_contracts.generated.models import SiteInfo

    site = SiteInfo(id="A", name="A", tz="Asia/Tokyo", printed_dates="era", year_basis="fiscal")
    assert dates.site_dates(site) == ("era", "fiscal")
    assert dates.site_dates(SiteInfo(id="A", name="A", tz="Asia/Tokyo")) == ("both", "fiscal")
    assert dates.site_dates(SiteInfo(id="A", name="A", tz="Asia/Taipei")) == ("western", "calendar")
    with pytest.raises(ValidationError):
        SiteInfo(id="A", name="A", tz="Asia/Tokyo", printed_dates="heisei")


# ------------------------------------------------------------------------------------------------ 年度
def test_nendo_2026_counts_april_2026_to_march_2027() -> None:
    assert dates.year_window(2026, "fiscal") == (date(2026, 4, 1), date(2027, 4, 1))
    assert dates.year_window(2026, "calendar") == (date(2026, 1, 1), date(2027, 1, 1))
    assert dates.year_of(date(2026, 3, 31), "fiscal") == 2025
    assert dates.year_of(date(2026, 4, 1), "fiscal") == 2026
    assert dates.year_of(date(2027, 3, 31), "fiscal") == 2026
    assert dates.year_of(date(2027, 3, 31), "calendar") == 2027
    for day, inside in (("2026-03-31", False), ("2026-04-01", True), ("2027-03-31", True), ("2027-04-01", False)):
        assert dates.in_year(day, 2026, "fiscal", TOKYO) is inside, day


@pytest.fixture
def server_in_los_angeles() -> object:
    """The server's own clock in another zone than the site's: the boundary must not follow it."""
    before = os.environ.get("TZ")
    os.environ["TZ"] = "America/Los_Angeles"
    time.tzset()
    yield
    if before is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = before
    time.tzset()


@pytest.mark.usefixtures("server_in_los_angeles")
def test_the_sites_zone_decides_the_boundary_day_not_the_servers() -> None:
    assert time.strftime("%Z") in ("PST", "PDT")
    # 2027-03-31 15:30 UTC is 2027-04-01 00:30 in Tokyo (and still 31 March in Los Angeles and in UTC): 年度2027
    late = datetime(2027, 3, 31, 15, 30, tzinfo=UTC)
    for stamp in (late.isoformat(), late.isoformat().replace("+00:00", "Z"), late.replace(tzinfo=None).isoformat()):
        assert dates.in_year(stamp, 2027, "fiscal", TOKYO), stamp
        assert not dates.in_year(stamp, 2026, "fiscal", TOKYO), stamp
    # 2026-03-31 14:59 UTC is 23:59 on 31 March in Tokyo: still 年度2025
    edge = "2026-03-31T14:59:59+00:00"
    assert dates.in_year(edge, 2025, "fiscal", TOKYO) and not dates.in_year(edge, 2026, "fiscal", TOKYO)
    # a stamp written in the site's zone keeps its own day
    assert dates.in_year("2026-04-01T00:00:00+09:00", 2026, "fiscal", TOKYO)


def test_a_calendar_count_reads_the_stamp_as_it_always_did() -> None:
    """Calendar year (every non-Japanese site, unchanged): the stamp's first four characters, as before."""
    for stamp in ("2026-12-31T23:59:00+00:00", "2026-01-01", "2026", "2026-12-31T20:00:00Z"):
        assert dates.in_year(stamp, 2026, "calendar", TOKYO) is stamp.startswith("2026")
        assert dates.in_year(stamp, 2026, None, None) is stamp.startswith("2026")


def test_people_count_a_state_in_its_nendo_each_source_in_its_own_zone() -> None:
    from console import person_state as ps

    people = ps.People({}, date(2027, 4, 2), True, frozenset(), TOKYO, True)
    # the screening log writes site-local naive stamps; marks and outcomes write UTC
    registry = ps.PersonState("listed", "registry", "2027-04-01T00:10:00")
    mark = ps.PersonState("approach", "mark", "2027-03-31T15:10:00")  # UTC: 1 April 00:10 in Tokyo
    early = ps.PersonState("approach", "mark", "2027-03-31T14:50:00+00:00")  # 31 March 23:50 in Tokyo
    for st in (registry, mark):
        assert people.began_in(st, 2027, "fiscal") and not people.began_in(st, 2026, "fiscal")
    assert people.began_in(early, 2026, "fiscal")
    assert people.began_in(mark, 2027, "calendar") and not people.began_in(mark, 2026, "calendar")
    assert not people.began_in(ps.PersonState("x", "mark", ""), 2026, "fiscal")


# ------------------------------------------------------------------------------------------------ the prints
def test_the_feasibility_report_prints_its_run_date_in_the_sites_style() -> None:
    import dataclasses
    import io

    from orchestrator.reports import feasibility_pdf
    from pypdf import PdfReader

    from tests.unit.test_feas_unit import GZQO, META, _result

    r = _result()
    western = feasibility_pdf.render(r, GZQO, META, {})
    # a non-Japanese site (the default style): byte for byte what it printed before
    assert western == feasibility_pdf.render(r, GZQO, dataclasses.replace(META, dates="western"), {})
    ja = dataclasses.replace(META, locale="ja", dates="both")
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(feasibility_pdf.render(r, GZQO, ja, {}))).pages)
    assert "2026年（令和8年）10月5日" in text
    assert META.footer in text  # the footer's snapshot is an identifier: kept as stored
    era = dataclasses.replace(META, locale="ja", dates="era")
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(feasibility_pdf.render(r, GZQO, era, {}))).pages)
    assert "令和8年10月5日" in text


def test_the_case_sheet_and_the_consent_page_print_dates_in_the_sites_style() -> None:
    from orchestrator.reports import case_html, consent_html
    from orchestrator.scenarios import consent as c

    from tests.unit.test_wording_outputs import _case_rec, _consent_rec

    rec = _case_rec("ja")
    assert case_html.sheet(rec) == case_html.sheet(rec, "western")  # unchanged for every other site
    page = case_html.sheet(rec, "both").decode()
    assert "2026年（令和8年）10月5日" in page  # checked on
    assert "2026年（令和8年）9月1日 – 2026年（令和8年）9月18日" in page  # the chart's excerpts
    assert "2026-10-05" not in page.split("<footer")[0].split('class="meta"')[1].split("</p>")[0]

    crec = _consent_rec()
    release = {"by": "crc1@hospa.test", "at": "2026-11-18T10:00:00+09:00", "job_id": "01J"}
    view = c.released_view(crec, "ja", [], [])
    before = consent_html.patient(crec, "ja", view, release=release)
    assert before == consent_html.patient(crec, "ja", view, release=release, dates="western")
    assert "2026-11-18" in before.decode()
    assert "令和8年11月18日" in consent_html.patient(crec, "ja", view, release=release, dates="era").decode()
