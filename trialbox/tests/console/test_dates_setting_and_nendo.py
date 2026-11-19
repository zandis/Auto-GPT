"""10C-13 and 10C-15 on the real pages: the two answers on the first-run form (with the country, 10K-1) reach the
settings file, and the research office counts by 年度 at a Japanese site, saying which year it counts in three
languages. All data is synthetic."""

from __future__ import annotations

import html
import io
import json
import re
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
def _done(b: dict[str, Any]) -> dict[str, Any]:
    events = [json.loads(x) for f in sorted(b["audit"].glob("*")) if f.is_file()
              for x in f.read_text(encoding="utf-8").splitlines() if x.startswith("{")]  # fmt: skip
    done = [
        e for e in events if e.get("event") == "console.first_run" and (e.get("detail") or {}).get("step") == "done"
    ]
    assert len(done) == 1
    return dict(done[0]["detail"])


def _chosen(page: str, name: str) -> str:
    m = re.search(rf'<select id="{name}" name="{name}">(.*?)</select>', page, re.S)
    assert m, name
    sel = re.findall(r'<option value="([a-z]+)" selected>', m.group(1))
    assert len(sel) == 1, sel
    return str(sel[0])


def test_the_first_run_form_asks_both_with_the_countrys_default_chosen_in_three_languages(tmp_path: Path) -> None:
    b = _box(tmp_path, TB_FIRSTRUN_COUNTRY="1")
    c = _with_code(b)
    first = c.get("/login/first-run/answers").text
    assert 'name="printed_dates"' not in first  # the country step comes first
    for lang in LANGS:
        page = _keep(c, first, lang=lang, pick_country="jp").text
        for key in ("firstrun.printed_dates", "firstrun.printed_dates.western", "firstrun.printed_dates.era",
                    "firstrun.printed_dates.both", "firstrun.year_basis", "firstrun.year_basis.calendar",
                    "firstrun.year_basis.fiscal"):  # fmt: skip
            assert translate(lang, key) in html.unescape(page), (lang, key)
        assert (_chosen(page, "printed_dates"), _chosen(page, "year_basis")) == ("both", "fiscal"), lang
        us = _keep(c, first, lang=lang, pick_country="us").text
        assert (_chosen(us, "printed_dates"), _chosen(us, "year_basis")) == ("western", "calendar"), lang


def test_the_answers_reach_the_installer_and_the_audit_record_and_an_unknown_one_is_refused(tmp_path: Path) -> None:
    b = _box(tmp_path, TB_FIRSTRUN_COUNTRY="1")
    c = _with_code(b)
    r = _answered(c, "jp", printed_dates="heisei")
    assert r.status_code == 422 and 'data-testid="err-printed_dates"' in r.text
    r = _answered(c, "jp", printed_dates="era", year_basis="fiscal")
    assert r.status_code == 200, r.text[-400:]
    got = json.loads((b["folder"] / firstrun.ANSWERS).read_text(encoding="utf-8"))
    assert (got["printed_dates"], got["year_basis"]) == ("era", "fiscal")
    detail = _done(b)
    assert (detail["printed_dates"], detail["year_basis"]) == ("era", "fiscal")


def test_with_the_flag_off_posted_answers_are_dropped_and_not_recorded(tmp_path: Path) -> None:
    from tests.console.test_firstrun import _answers

    off = _box(tmp_path)
    r, _ = _answers(_with_code(off), printed_dates="era", year_basis="fiscal")
    assert r.status_code == 200, r.text[-400:]
    got = json.loads((off["folder"] / firstrun.ANSWERS).read_text(encoding="utf-8"))
    assert "printed_dates" not in got and "year_basis" not in got
    assert "printed_dates" not in _done(off) and "year_basis" not in _done(off)


def test_the_plan_writes_the_countrys_default_or_the_answer_into_the_sites_settings(tmp_path: Path) -> None:
    import yaml

    _p, s, _ = _plan_box(tmp_path, country="jp", printed_dates="western", year_basis="calendar")
    assert (s["site"]["printed_dates"], s["site"]["year_basis"]) == ("western", "calendar")
    _p, s, _ = _plan_box(tmp_path / "jp", country="jp")  # a new Japanese site that kept the defaults shown
    assert (s["site"]["printed_dates"], s["site"]["year_basis"]) == ("both", "fiscal")
    out = tmp_path / "settings.yaml"
    out.write_text(yaml.safe_dump(s, allow_unicode=True), encoding="utf-8")
    assert site_dates(load_settings(out).site) == ("both", "fiscal")
    _p, s, _ = _plan_box(tmp_path / "plain")  # no country (the flag off): no key; prints and years as before
    assert "printed_dates" not in s["site"] and "year_basis" not in s["site"]
    out.write_text(yaml.safe_dump(s, allow_unicode=True), encoding="utf-8")
    assert site_dates(load_settings(out).site) == ("western", "calendar")  # a Tokyo site with Japanese reports
    assert any(q.field == "printed_dates" for q in parse({"printed_dates": "x"})[1])


# ------------------------------------------------------------------------------------------------ the office
def _site(bk: Any, monkeypatch: pytest.MonkeyPatch, **site: Any) -> None:
    monkeypatch.setattr(bk, "cfg", SimpleNamespace(settings=SimpleNamespace(site=SimpleNamespace(**site))),
                        raising=False)  # fmt: skip


def test_a_site_counting_by_nendo_says_so_in_three_languages(
    study: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bk = study["backend"]
    crc = _as(study["app"], "crc", "en")
    calendar = _office(crc.get("/reports/research-office?year=2026").text)
    _site(bk, monkeypatch, tz="Asia/Tokyo", locale="ja", year_basis="fiscal")
    for lang in LANGS:
        c = _as(study["app"], "crc", lang)
        raw = c.get("/reports/research-office?year=2026").text
        page = html.unescape(raw)
        label = translate(lang, "office.year.fiscal", year=2026, first="2026-04-01", last="2027-03-31")
        assert label in page and translate(lang, "office.help.fiscal", k=SMALL_CELL) in page, lang
        for y in (2025, 2027):  # the year links name the 年度, never a bare number
            assert translate(lang, "office.year.fiscal.short", year=y) in page, (lang, y)
        # every fact of the fixture is in November 2026: 年度2026 holds what calendar 2026 held, 年度2025 nothing
        assert _office(raw) == calendar, lang
        assert 'data-testid="office"' not in c.get("/reports/research-office?year=2025").text
        x = c.get("/reports/research-office.xlsx?year=2026")
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(x.content))
        assert wb.worksheets[0].title == "counts FY2026"  # nothing reads the sheet by name (searched)
        about = {r[0]: r[1] for r in wb["about"].iter_rows(values_only=True)}
        assert about["year basis"] == label, lang
    # no year asked: the 年度 of the site's today (2026-11-08 in the fixture's clock)
    assert "2026-04-01" in crc.get("/reports/research-office").text


def test_the_sites_zone_decides_the_nendo_of_a_stamp_on_the_page(
    study: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A listing stamped 2027-03-31T15:30Z is 1 April 00:30 in Tokyo: 年度2027, not 年度2026 (its UTC day)."""
    store = study["app"].state.helpers.store
    real = store.first_seen

    def first_seen(rs: str) -> dict[str, tuple[str, str]]:
        return {**real(rs), "e" * 32: ("J-late", "2027-03-31T15:30:00+00:00")}

    monkeypatch.setattr(store, "first_seen", first_seen)
    crc = _as(study["app"], "crc", "en")
    _site(study["backend"], monkeypatch, tz="Asia/Tokyo", locale="ja", year_basis="fiscal")
    late = crc.get("/reports/research-office?year=2027").text
    assert _office(late)["listed"] == f"<{SMALL_CELL}", late[-600:]  # counted in 年度2027 (one person)
    _site(study["backend"], monkeypatch, tz="America/Los_Angeles", locale="en", year_basis="fiscal")
    assert 'data-testid="office"' not in crc.get("/reports/research-office?year=2027").text  # 31 March there


def test_an_upgraded_japanese_site_and_a_site_elsewhere_count_by_calendar_year_as_before(
    study: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-1229 (b): no key (an installed site, whatever its zone): the page and the export are master's."""
    bk = study["backend"]
    for site in ({"tz": "Asia/Tokyo", "locale": "ja"}, {"tz": "Asia/Taipei", "locale": "zh-TW"}):
        _site(bk, monkeypatch, **site)
        for lang in LANGS:
            page = _as(study["app"], "crc", lang).get("/reports/research-office?year=2026").text
            plain = html.unescape(page)
            assert f"{translate(lang, 'office.title')} · 2026</h1>" in plain, (site, lang)
            assert translate(lang, "office.help", k=SMALL_CELL) in plain and 'data-testid="office-year"' not in page
            assert ">← 2025</a>" in page and ">2027 →</a>" in page
        x = _as(study["app"], "crc", "en").get("/reports/research-office.xlsx?year=2026")
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(x.content))
        assert wb.worksheets[0].title == "counts 2026"
        assert "year basis" not in {r[0] for r in wb["about"].iter_rows(values_only=True)}
