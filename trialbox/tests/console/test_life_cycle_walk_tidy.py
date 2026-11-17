# ruff: noqa: F811 - the box and lb fixtures are imported and taken by name
"""J-4 (D-1224): the tidy-up of lane H's life-cycle walk (``docs/handover/life-cycle-walk-findings-2026-11-17.md``).

Each finding this card settles, on the real page, in en, zh-TW and ja where its words changed:

* F-01: Help on the weekly page reads for the role that opens it (the coordinator is not told to mark);
* F-02: the investigator's mark and its confirmation use one word ("Approach");
* F-07: the screening number on the patient sheet leads to the participant's page, and (half of F-18) the
  participant's page leads back to the patient sheet;
* F-08: the participants' pages and the study's state have their own Help text and are in the role guides;
* F-09: one participant's page is headed by the participant;
* F-10: the orchestrator's stamps take the box's own clock when the box has one (``tools.demo --day data``);
* F-12: two English words for two actions (the participant's "Withdraw", taking back a mark);
* F-19: the opt-out register's note has a label of its own;
* F-21: the administrator's Health tab has a line for the opt-out worker's check, red when stale or failed.

Synthetic data only."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from console.i18n import CATALOGUES, translate

from tests.console.test_console_app import ADMIN_PW, _done_screen, _ulid, box, login, name_pi  # noqa: F401
from tests.console.test_lifecycle_pages import PW as LPW
from tests.console.test_lifecycle_pages import lb  # noqa: F401 - the fixture is used by name
from tests.console.test_role_pages import _csrf, _user
from tests.console.test_team_pages import A

LANGS = ("en", "zh-TW", "ja")


def _lang(c: Any, lang: str) -> None:
    c.post("/lang", data={"csrf": _csrf(c.get("/home").text), "lang": lang, "back": "/home"})


def _help_page(c: Any, back: str) -> str:
    m = re.search(r'data-testid="help-page">([^<]*)<', c.get("/help", params={"back": back}).text)
    assert m, back
    return m.group(1)


def _unescape(s: str) -> str:
    return s.replace("&#39;", "'").replace("&amp;", "&").replace("&quot;", '"')


# ---------------------------------------------------------------------------------------------- F-01, F-08
@pytest.mark.parametrize("lang", LANGS)
def test_help_on_the_weekly_page_reads_for_the_role_and_the_participants_and_state_have_their_own(
    box: dict[str, Any],
    lang: str,
) -> None:
    crc = _user(box, "crc4", "coordinator")
    pi = _user(box, "pi4", "investigator")
    for c in (crc, pi):
        _lang(c, lang)
    crc_week = _unescape(_help_page(crc, "/studies/GZQO/week"))
    pi_week = _unescape(_help_page(pi, "/studies/GZQO/week"))
    assert crc_week == translate(lang, "help.page.week.coordinator") and crc_week != pi_week
    assert pi_week == translate(lang, "help.page.week")  # the investigator marks: the page's own text
    # the coordinator is told who decides and what is theirs to record; the mark's word is the button's own
    assert translate(lang, "mark.approach") in crc_week and translate(lang, "mark.approach") in pi_week
    for back, slug in (("/studies/GZQO/subjects", "subjects"), ("/studies/GZQO/subjects/GZQO-0001", "subjects"),
                       ("/studies/GZQO/state", "state")):  # fmt: skip
        page = crc.get("/help", params={"back": back}).text
        assert f'data-page="{slug}"' in page, back
        text = _unescape(_help_page(crc, back))
        assert text == translate(lang, f"help.page.{slug}") != translate(lang, "help.page.other"), back
    if lang != "en":
        for key in ("help.page.week.coordinator", "help.page.subjects", "help.page.state", "guide.page.subjects",
                    "guide.page.state"):  # fmt: skip
            assert CATALOGUES[lang][key] != CATALOGUES["en"][key], (lang, key)


@pytest.mark.parametrize("lang", LANGS)
def test_the_coordinators_guide_lists_the_participants_and_the_state_with_the_help_text(lang: str) -> None:
    from console import guides

    md = guides.markdown("coordinator", lang)
    for slug in ("subjects", "state"):
        assert f"### {translate(lang, f'guide.page.{slug}')}\n\n{translate(lang, f'help.page.{slug}')}" in md, slug
    week = md.split(f"### {translate(lang, 'guide.page.week')}\n\n", 1)[1].split("\n", 1)[0]
    assert week == translate(lang, "help.page.week.coordinator")
    inv = guides.markdown("investigator", lang)
    assert inv.split(f"### {translate(lang, 'guide.page.week')}", 1)[1].split("\n\n")[1] == translate(
        lang, "help.page.week"
    )


# ---------------------------------------------------------------------------------------------- F-02, F-07
@pytest.mark.parametrize("lang", LANGS)
def test_approach_says_approach_and_the_screening_number_leads_to_the_participant(
    box: dict[str, Any],
    lang: str,
) -> None:
    _done_screen(box["backend"], _ulid(1224))
    pi = _user(box, "drsato", "investigator")
    name_pi(box, "drsato")
    crc = _user(box, "crc4", "coordinator")
    for c in (pi, crc):
        _lang(c, lang)
    page = pi.get(f"/studies/GZQO/patients/{A}").text
    assert f">{translate(lang, 'mark.approach')}<" in page
    r = pi.post(f"/studies/GZQO/patients/{A}/mark", data={"csrf": _csrf(page), "mark": "approach"},
                follow_redirects=True)  # fmt: skip
    done = translate(lang, "wb.done.approach")
    assert r.status_code == 200 and _unescape(done) in _unescape(r.text)
    assert translate(lang, "mark.approach") in done  # one word for the mark and its confirmation
    no = box["app"].state.helpers.store.screening_no("GZQO", A)
    assert no
    sheet = crc.get(f"/studies/GZQO/patients/{A}").text
    pill = sheet.split('data-testid="screening-no"', 1)[1][:400]
    assert f'<a href="/studies/GZQO/subjects/{no}" class="mono" data-testid="to-subject">{no}</a>' in pill


# ---------------------------------------------------------------------------------------------- F-07, F-09
@pytest.mark.parametrize("lang", LANGS)
def test_the_participants_page_is_headed_by_the_participant_and_leads_to_the_patient_sheet(
    lb: dict[str, Any],
    lang: str,
) -> None:
    no = lb["nos"][0]
    c, _ = login(lb["app"], "crc", LPW)
    _lang(c, lang)
    page = c.get(f"/studies/GZQO/subjects/{no}").text
    h1 = re.search(r"<h1>(.*?)</h1>", page, re.S)
    assert h1 and h1.group(1).strip() == translate(lang, "life.subject.title", r=no), h1
    assert "·" not in h1.group(1)  # not "<number> · Participants", the list's title
    pid = f"{1:032x}"  # the pseudonym the fixture gave this screening number
    link = re.search(r'<a href="([^"]+)" data-testid="to-patient">([^<]+)</a>', page)
    assert link and link.group(1) == f"/studies/GZQO/patients/{pid}"
    assert link.group(2) == translate(lang, "life.to.patient")


# ---------------------------------------------------------------------------------------------- F-12
def test_two_english_words_for_the_participants_withdrawal_and_taking_back_a_mark() -> None:
    for lang in LANGS:
        cat = CATALOGUES[lang]
        assert cat["life.go.withdrawn"] not in cat["mark.withdraw"], lang
    assert CATALOGUES["en"]["mark.withdraw"] == "Take back my mark"
    assert "ithdraw" not in CATALOGUES["en"]["mark.withdrawn"] + CATALOGUES["en"]["wb.done.withdrawn"]


# ---------------------------------------------------------------------------------------------- F-19
@pytest.mark.parametrize("lang", LANGS)
def test_the_opt_out_registers_note_has_its_own_label(box: dict[str, Any], lang: str) -> None:
    stw = _user(box, "stw", "steward")
    _lang(stw, lang)
    page = stw.get("/site/opt-outs").text
    label = re.search(r'<label for="oo-note">([^<]+)</label>', page)
    assert label and label.group(1) == translate(lang, "team.optout.note") != translate(lang, "mark.note")


# ---------------------------------------------------------------------------------------------- F-21
@pytest.mark.parametrize("lang", LANGS)
def test_the_health_tab_shows_the_opt_out_worker_red_when_stale_or_failed(box: dict[str, Any], lang: str) -> None:
    h = box["app"].state.helpers
    now = datetime(2026, 11, 2, 7, 0, tzinfo=UTC)
    h.clock = lambda: now
    c, _ = login(box["app"], "admin", ADMIN_PW)
    _lang(c, lang)

    def line(worker: dict[str, Any] | None) -> tuple[str, str]:
        box["backend"].models_info = {"optout_worker": worker} if worker is not None else {}
        page = c.get("/admin?tab=health").text
        m = re.search(r'<li data-testid="health-optout" data-level="([a-z]+)">(.*?)</li>', page, re.S)
        assert m, worker
        return m.group(1), m.group(2)

    ok_at = (now - timedelta(minutes=4)).isoformat()
    level, text = line({"every": 5, "started": ok_at, "ok_at": ok_at, "failed": []})
    assert level == "ok" and translate(lang, "adm.optout.ok", m=4) in text and translate(lang, "adm.optout") in text
    level, text = line({"every": 5, "started": ok_at, "ok_at": ok_at, "failed": ["omop"]})
    assert (
        level == "red"
        and 'class="pill bad"' in text
        and _unescape(translate(lang, "adm.optout.red")) in _unescape(text)
    )
    stale = (now - timedelta(minutes=60)).isoformat()
    assert line({"every": 5, "started": stale, "ok_at": stale, "failed": []})[0] == "red"
    assert line({"every": 0})[0] == "red"  # the worker is off (the box of the walk, F-20)
    assert line({"every": 5, "started": (now - timedelta(minutes=2)).isoformat(), "failed": []})[0] == "warn"
    # the line is the same check /metrics carries
    from tb_common import metrics

    assert metrics.check_optout({"every": 0}, now).level == "red"


# ---------------------------------------------------------------------------------------------- F-10
def test_the_orchestrators_stamps_take_the_boxs_own_clock() -> None:
    """``tools.demo --day data``: the console's clock stands on the box's day; the orchestrator's stamps (the steps
    TrialBox derives itself: candidate, approached) take that clock too, not the wall clock."""
    from orchestrator.app import _now

    from tools.list_demo import Clock

    o = SimpleNamespace(cfg=SimpleNamespace(settings=SimpleNamespace(site=SimpleNamespace(tz="Asia/Tokyo"))),
                        clock=Clock(date(2026, 11, 2), "Asia/Tokyo"))  # fmt: skip
    got = _now(o)  # type: ignore[arg-type]
    assert got.isoformat() == "2026-11-02T07:00:00+09:00"
    o.clock = None
    real = _now(o)  # type: ignore[arg-type]
    assert abs((real - datetime.now(UTC)).total_seconds()) < 60 and str(real.tzinfo) == "Asia/Tokyo"
