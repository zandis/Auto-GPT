"""10C-13 and 10C-15 on the real pages: the two answers on the first-run form (with the country, 10K-1) reach the
settings file, and the research office counts by 年度 at a Japanese site, saying which year it counts in three
languages. All data is synthetic."""

from __future__ import annotations

import html
import io
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from console.i18n import translate
from console.screening_log import SMALL_CELL
from tb_common import firstrun
from tb_common.box_answers import parse
from tb_common.config import load_settings
from tb_common.dates import site_dates

from tests.console.test_console_app import box  # noqa: F401 - the fixture is used by name
from tests.console.test_firstrun import _box, _with_code
from tests.console.test_firstrun_country import _answered, _keep
from tests.console.test_lifecycle_pages import lb  # noqa: F401 - the fixture is used by name
from tests.console.test_one_person_state import _as, _office, study  # noqa: F401 - study: by name
from tests.unit.test_site_country import _box as _plan_box

LANGS = ("en", "zh-TW", "ja")


# ------------------------------------------------------------------------------------------------ the form
def test_the_first_run_form_asks_both_with_the_country_in_three_languages(tmp_path: Path) -> None:
    b = _box(tmp_path, TB_FIRSTRUN_COUNTRY="1")
    c = _with_code(b)
    first = c.get("/login/first-run/answers").text
    assert 'name="printed_dates"' not in first  # the country step comes first
    for lang in LANGS:
        page = html.unescape(_keep(c, first, lang=lang, pick_country="jp").text)
        for key in ("firstrun.printed_dates", "firstrun.printed_dates.auto", "firstrun.printed_dates.both",
                    "firstrun.year_basis", "firstrun.year_basis.auto", "firstrun.year_basis.fiscal"):  # fmt: skip
            assert translate(lang, key) in page, (lang, key)
        assert '<option value="">' in page  # the first choice: follow the country


def test_the_answers_reach_the_installer_and_an_unknown_one_is_refused(tmp_path: Path) -> None:
    b = _box(tmp_path, TB_FIRSTRUN_COUNTRY="1")
    c = _with_code(b)
    r = _answered(c, "jp", printed_dates="heisei")
    assert r.status_code == 422 and 'data-testid="err-printed_dates"' in r.text
    r = _answered(c, "jp", printed_dates="era", year_basis="fiscal")
    assert r.status_code == 200, r.text[-400:]
    got = json.loads((b["folder"] / firstrun.ANSWERS).read_text(encoding="utf-8"))
    assert (got["printed_dates"], got["year_basis"]) == ("era", "fiscal")


def test_unanswered_writes_nothing(tmp_path: Path) -> None:
    b = _box(tmp_path, TB_FIRSTRUN_COUNTRY="1")
    r = _answered(_with_code(b), "jp")
    assert r.status_code == 200, r.text[-400:]
    got = json.loads((b["folder"] / firstrun.ANSWERS).read_text(encoding="utf-8"))
    assert "printed_dates" not in got and "year_basis" not in got


def test_with_the_flag_off_posted_answers_are_dropped(tmp_path: Path) -> None:
    from tests.console.test_firstrun import _answers

    off = _box(tmp_path)
    r, _ = _answers(_with_code(off), printed_dates="era", year_basis="fiscal")
    assert r.status_code == 200, r.text[-400:]
    got = json.loads((off["folder"] / firstrun.ANSWERS).read_text(encoding="utf-8"))
    assert "printed_dates" not in got and "year_basis" not in got


def test_the_plan_writes_them_into_the_sites_settings(tmp_path: Path) -> None:
    _p, s, _ = _plan_box(tmp_path, country="jp", printed_dates="western", year_basis="calendar")
    assert (s["site"]["printed_dates"], s["site"]["year_basis"]) == ("western", "calendar")
    _p, s, _ = _plan_box(tmp_path / "plain")
    assert "printed_dates" not in s["site"] and "year_basis" not in s["site"]  # follows the country
    assert parse({"printed_dates": "x"})[1] and any(
        q.field == "printed_dates" for q in parse({"printed_dates": "x"})[1]
    )
    out = tmp_path / "settings.yaml"
    import yaml

    out.write_text(yaml.safe_dump(s, allow_unicode=True), encoding="utf-8")
    assert site_dates(load_settings(out).site) == ("both", "fiscal")  # Asia/Tokyo, unanswered: Japan's defaults


# ------------------------------------------------------------------------------------------------ the office
def _site(bk: Any, monkeypatch: pytest.MonkeyPatch, **site: Any) -> None:
    monkeypatch.setattr(bk, "cfg", SimpleNamespace(settings=SimpleNamespace(site=SimpleNamespace(**site))),
                        raising=False)  # fmt: skip


def test_a_japanese_site_counts_by_nendo_and_says_so_in_three_languages(
    study: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bk = study["backend"]
    crc = _as(study["app"], "crc", "en")
    calendar = _office(crc.get("/reports/research-office?year=2026").text)
    _site(bk, monkeypatch, tz="Asia/Tokyo", locale="ja")
    for lang in LANGS:
        c = _as(study["app"], "crc", lang)
        page = c.get("/reports/research-office?year=2026").text
        label = translate(lang, "office.year.fiscal", year=2026, first="2026-04-01", last="2027-03-31")
        assert label in html.unescape(page), lang
        assert translate(lang, "office.help.fiscal", k=SMALL_CELL) in html.unescape(page), lang
        # every fact of the fixture is in November 2026: 年度2026 holds what calendar 2026 held, 年度2025 nothing
        assert _office(page) == calendar, lang
        before = c.get("/reports/research-office?year=2025").text
        assert 'data-testid="office"' not in before
    # no year asked: the 年度 of the site's today (2026-11-08 in the fixture's clock)
    assert "2026-04-01" in crc.get("/reports/research-office").text
    x = crc.get("/reports/research-office.xlsx?year=2026")
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(x.content))
    assert wb.worksheets[0].title == "counts FY2026"
    about = {r[0]: r[1] for r in wb["about"].iter_rows(values_only=True)}
    assert about["year basis"] == "fiscal year (年度): 2026-04-01 to 2027-03-31"


def test_a_site_elsewhere_counts_by_calendar_year_as_before(
    study: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bk = study["backend"]
    _site(bk, monkeypatch, tz="Asia/Taipei", locale="zh-TW")
    for lang in LANGS:
        page = _as(study["app"], "crc", lang).get("/reports/research-office?year=2026").text
        label = translate(lang, "office.year.calendar", year=2026, first="2026-01-01", last="2026-12-31")
        assert label in html.unescape(page) and translate(lang, "office.help", k=SMALL_CELL) in html.unescape(page), (
            lang
        )
    x = _as(study["app"], "crc", "en").get("/reports/research-office.xlsx?year=2026")
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(x.content))
    assert wb.worksheets[0].title == "counts 2026"
    assert "year basis" not in {r[0] for r in wb["about"].iter_rows(values_only=True)}  # the export as before
