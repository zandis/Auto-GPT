"""NEW-DEMO-1 (D-797): lane G's browser walk of the demo (2026-11-15), the cosmetic findings of lane C2.

1. The candidates page said "This run screened only these doctors' patients: ." with an empty list when the run's
   scope named neither the whole hospital nor any doctor: now it says nothing about the scope then.
3. The coordinator's home page listed an SAE with no reporting clock as "...no deadline yet: ... due" with no date:
   now that row says only that there is no deadline yet and where to choose the rule set.
6. The footer read "TrialBox · DEV · data class D0" on the demo: in demo mode it reads "DEMO".
7. ``/sae`` showed an investigator the set-up warnings (no trial office mailbox, reporting rules to check) that only
   the coordinator (the study's set-up) or the administrator (the site's set-up) can act on: now only they see them.

Synthetic data only."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

import pytest
from console.i18n import CATALOGUES, translate
from jinja2 import Environment, FileSystemLoader

from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_demo_guard import _demo_on, _signed_in
from tests.console.test_lifecycle_pages import PW, lb  # noqa: F401 - the fixture is used by name

ROOT = Path(__file__).resolve().parents[2]
LANGS = ("en", "ja", "zh-TW")


def _render(src: str, lang: str = "en", **ctx: Any) -> str:
    env = Environment(loader=FileSystemLoader(str(ROOT / "services" / "console" / "templates")), autoescape=True)
    env.globals["t"] = lambda key, **kw: translate(lang, key, **kw)
    return env.from_string(src).render(**ctx)


# ---------------------------------------------------------------------------------------------- 1. the run's scope
@pytest.mark.parametrize("scope", [{}, {"whole_hospital": False, "practitioners": []}, {"practitioners": None}])
def test_a_scope_naming_no_one_says_nothing(scope: dict[str, Any]) -> None:
    out = _render('{% include "_run_scope.html" %}', wk={"summary": {"scope": scope}}, rs="GZQO")
    assert "scope-pract" not in out and "scope-hospital" not in out and ": ." not in out


def test_a_scope_still_names_the_doctors_or_the_hospital() -> None:
    out = _render('{% include "_run_scope.html" %}', wk={"summary": {"scope": {"practitioners": ["D01", "D02"]}}},
                  rs="GZQO")  # fmt: skip
    assert 'data-testid="scope-pract"' in out and "D01, D02" in out
    out = _render('{% include "_run_scope.html" %}', wk={"summary": {"scope": {"whole_hospital": True}}}, rs="GZQO")
    assert 'data-testid="scope-hospital"' in out


# ---------------------------------------------------------------------------------------------- 3. no deadline
@pytest.mark.parametrize("lang", LANGS)
def test_an_sae_with_no_clock_has_no_due_without_a_day(lang: str) -> None:
    rows = [{"record": "GZQO-0001", "event": "ae1", "rs": "GZQO", "party": "no_clock", "due": ""},
            {"record": "GZQO-0002", "event": "ae1", "rs": "GZQO", "party": "irb", "due": "2026-11-10"}]  # fmt: skip
    out = _render('{% from "_life.html" import report_banner %}{{ report_banner(reports) }}', lang, reports=rows)
    noclock = html.unescape(out[out.index('data-testid="sae-report-GZQO-0001-ae1-no_clock"') :].split("</li>")[0])
    why = translate(lang, "life.clock.party.no_clock")
    assert translate(lang, "life.reports.row_noclock", r="GZQO-0001", rs="GZQO", why=why) in noclock
    due = {"en": ", due", "ja": "、期限", "zh-TW": "，期限"}[lang]  # the dated row's "due <day>" part
    assert due not in noclock
    dated = out[out.index('data-testid="sae-report-GZQO-0002-ae1-irb"') :].split("</li>")[0]
    assert f"{due} 2026-11-10" in html.unescape(dated)  # a dated report keeps its due day


# ---------------------------------------------------------------------------------------------- 6. the footer
def test_the_demo_footer_says_demo(box: dict[str, Any]) -> None:  # noqa: F811
    c, _ = _signed_in(box, "crc1", "coordinator")
    foot = c.get("/home").text.split("<footer>")[1]
    assert "DEMO" not in foot.split("·")[1]  # demo mode off: the environment as before
    _demo_on(box)
    foot = c.get("/home").text.split("<footer>")[1]
    assert foot.split("·")[1].strip() == "DEMO"


# ---------------------------------------------------------------------------------------------- 7. /sae warnings
def test_the_sae_set_up_warnings_go_to_who_can_act(lb: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.delenv("TB_SAE_OFFICE_MAILBOX", raising=False)
    crc, _ = login(lb["app"], "crc", PW)
    assert 'data-testid="sae-no-mailbox"' in crc.get("/sae").text  # the coordinator asks the administrator
    pi, _ = login(lb["app"], "pi", PW)
    page = pi.get("/sae")
    assert page.status_code == 200
    assert 'data-testid="sae-no-mailbox"' not in page.text and 'data-testid="sae-alert-rules"' not in page.text


def test_the_new_words_are_in_every_language() -> None:
    for lang in LANGS:
        assert CATALOGUES[lang].get("life.reports.row_noclock"), lang
