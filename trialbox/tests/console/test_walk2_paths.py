"""WALK-2 (lane H's walk H-20, PR #994): the paths a tester could not find. Synthetic data only.

F-04: on a new study the first Approach is recorded as an override (no IRB approval date, no consent-form version),
and no step of the new-study path led to the IRB record. A study in start-up now lists, on its state page, what is
recorded before it opens and is approached, each with its page and whether it is done: the type for SAE reporting
(D-415) and the IRB record (D-147, D-399). A list, not a gate (D-311): Approach under the warning stays an override."""

from __future__ import annotations

from typing import Any

from tests.console.test_close_only_an_empty_study import clock  # noqa: F401 - the fixture is used by name
from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_sdv import PW as SB_PW
from tests.console.test_sdv import sb  # noqa: F401 - the fixture is used by name


def _section(page: str, testid: str) -> str:
    start = page.index(f'data-testid="{testid}"')
    return page[start : page.index("</section>", start)]


def test_a_study_in_start_up_leads_to_the_irb_record_before_it_opens(sb: dict[str, Any], clock: Any) -> None:  # noqa: F811
    from console.teamstore import Irb

    h = sb["app"].state.helpers
    assert h.store.begin_study("GZQO", "console:crc", "2026-11-05T01:00:00+00:00") is not None
    crc, _ = login(sb["app"], "crc", SB_PW)
    page = crc.get("/studies/GZQO/state").text
    todo = _section(page, "before-open")
    assert 'href="/studies/GZQO/irb"' in todo and 'data-testid="before-open-irb" data-done="no"' in todo
    assert 'href="/studies/GZQO/setup' in todo and 'data-testid="before-open-sae"' in todo
    h.team.save_irb("GZQO", Irb(approved_on="2026-10-01", icf_version="2.0"), "console:pi", "2026-11-05T01:00:00+00:00")
    todo = _section(crc.get("/studies/GZQO/state").text, "before-open")
    assert 'data-testid="before-open-irb" data-done="yes"' in todo


def test_an_open_study_shows_no_list(sb: dict[str, Any], clock: Any) -> None:  # noqa: F811
    crc, _ = login(sb["app"], "crc", SB_PW)
    assert 'data-testid="before-open"' not in crc.get("/studies/GZQO/state").text  # no state: open, as before


def test_the_opt_out_form_says_where_the_chart_number_comes_from(box: dict[str, Any]) -> None:  # noqa: F811
    """F-17: the steward's register asks for a chart number, and no page the steward may open shows one (the matrix
    keeps chart numbers from the steward: D-143, D-380). The number comes with the patient's own request, on paper or
    by phone; the form says so, in each language, instead of leaving the steward to look for it on TrialBox."""
    from console.i18n import CATALOGUES

    for lang in ("en", "ja", "zh-TW"):
        words = CATALOGUES[lang]["team.optout.where"]
        assert words and words != "team.optout.where", lang
    box["users"].create("stw2", "steward", "walk2-steward-password-1", "stw2@hospa.test")
    stw, _ = login(box["app"], "stw2", "walk2-steward-password-1")
    page = stw.get("/site/opt-outs").text
    assert 'data-testid="optout-where"' in page and "own request" in page
