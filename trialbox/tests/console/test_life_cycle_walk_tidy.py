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


# ---------------------------------------------------------------------------------------------- the review's fixes
def test_an_erased_participant_shows_no_token_and_no_way_to_the_patient_sheet(lb: dict[str, Any]) -> None:
    """D-875: a participant whose pseudonym was erased (ERASE-A2: ``erased:<day>:<hex>``) shows no token and no
    link to a patient sheet that no longer exists."""
    from datacore.lifecycle import Lifecycle

    no = lb["nos"][0]
    c, _ = login(lb["app"], "crc", LPW)
    c.get(f"/studies/GZQO/subjects/{no}")  # the participant is made from its screening number
    token = "erased:2026-11-01:" + "ab" * 8
    Lifecycle(lb["dc"]).db.execute("UPDATE subject SET pid = ? WHERE study = ? AND record = ?", (token, "GZQO", no))
    page = c.get(f"/studies/GZQO/subjects/{no}").text
    assert 'data-testid="to-patient"' not in page and "erased:" not in page


def test_the_way_to_the_patient_sheet_only_for_a_reader_the_sheet_admits(lb: dict[str, Any]) -> None:
    """A sub-investigator ticked only for data entry reads the participant's page, but the patient sheet refuses
    them (it needs "screen"): no link and no part of the pseudonym. The PI reads the sheet: the link is there."""
    from tests.console.test_role_pages import PW as RPW
    from tests.console.test_team_pages import _log_pi_and_sub

    no = lb["nos"][0]
    pid = f"{1:032x}"
    crc, _ = login(lb["app"], "crc", LPW)
    crc.get(f"/studies/GZQO/subjects/{no}")
    pi = _user(lb, "drsato", "investigator")
    _user(lb, "drkato", "investigator")
    _log_pi_and_sub(lb, pi, ("enter_data",))
    kato, _ = login(lb["app"], "drkato", RPW)
    page = kato.get(f"/studies/GZQO/subjects/{no}")
    assert page.status_code == 200 and 'data-testid="to-patient"' not in page.text and pid[:8] not in page.text
    assert kato.get(f"/studies/GZQO/patients/{pid}").status_code == 403  # the sheet's own answer
    sheet = pi.get(f"/studies/GZQO/subjects/{no}").text
    assert f'href="/studies/GZQO/patients/{pid}" data-testid="to-patient"' in sheet


@pytest.mark.parametrize("lang", LANGS)
def test_a_step_trialbox_recorded_itself_reads_trialbox_not_a_service_name(lb: dict[str, Any], lang: str) -> None:
    from datacore.lifecycle import Lifecycle

    no = lb["nos"][0]
    Lifecycle(lb["dc"]).ensure("GZQO", no, f"{1:032x}", "service:console-notify", "2026-11-02T07:00:00+09:00")
    c, _ = login(lb["app"], "crc", LPW)
    _lang(c, lang)
    page = c.get(f"/studies/GZQO/subjects/{no}").text
    trail = page.split('data-testid="life-trail"', 1)[1]
    assert "service:" not in trail and f"<td>{translate(lang, 'life.who.service')}</td>" in trail


@pytest.mark.parametrize("lang", LANGS)
def test_the_system_count_takes_the_opt_out_line_and_an_absent_check_reads_unknown(
    box: dict[str, Any], lang: str
) -> None:
    h = box["app"].state.helpers
    now = datetime(2026, 11, 2, 7, 0, tzinfo=UTC)
    h.clock = lambda: now
    c, _ = login(box["app"], "admin", ADMIN_PW)
    _lang(c, lang)

    def tile(models: dict[str, Any]) -> tuple[str, str]:
        box["backend"].models_info = models
        page = c.get("/admin?tab=health").text
        count = re.search(r'data-testid="system-count" data-level="([a-z]+)">(\d+)/(\d+)', page)
        line = re.search(r'<li data-testid="health-optout" data-level="([a-z]+)">(.*?)</li>', page, re.S)
        assert count and line, models
        assert int(count.group(3)) == len(box["backend"].health()) + 1  # the services and the opt-out worker
        return count.group(1), line.group(1) + ":" + line.group(2)

    ok_at = (now - timedelta(minutes=4)).isoformat()
    assert tile({"optout_worker": {"every": 5, "started": ok_at, "ok_at": ok_at, "failed": []}})[0] == "ok"
    assert tile({"optout_worker": {"every": 0}})[0] == "bad"  # a red line makes a red count
    young = (now - timedelta(minutes=2)).isoformat()
    assert tile({"optout_worker": {"every": 5, "started": young, "failed": []}})[0] == "warn"
    level, line = tile({})  # the orchestrator gave no worker status: said, not left out
    assert level == "warn" and line.startswith("unknown:")
    assert _unescape(translate(lang, "adm.optout.unknown")) in _unescape(line)


@pytest.mark.parametrize("lang", LANGS)
def test_the_coordinators_hint_on_the_weekly_page_says_approach(box: dict[str, Any], lang: str) -> None:
    _done_screen(box["backend"], _ulid(1225))
    crc = _user(box, "crc4", "coordinator")
    _lang(crc, lang)
    page = _unescape(crc.get(f"/studies/GZQO/week?pid={A}").text)
    hint = translate(lang, "wb.crc_hint")
    assert _unescape(hint) in page and translate(lang, "mark.approach") in hint
    assert not any(w in hint for w in ("approve", "承認", "核准"))


def test_the_screening_number_link_is_a_44px_target_on_a_phone_only() -> None:
    from pathlib import Path

    css = (Path(__file__).resolve().parents[2] / "services/console/static/console.css").read_text(encoding="utf-8")
    rule = re.search(r"@media \(max-width: 760px\) \{ \.pill\[data-testid=screening-no\] > a \{([^}]*)\} \}", css)
    assert rule and "min-height: 44px" in rule.group(1) and "min-width: 44px" in rule.group(1)
    assert css.count("[data-testid=screening-no]") == 1  # nothing outside the phone rule: the desktop look is kept


def _box_on_a_clock(tmp_path: Any, clock: Any) -> Any:
    from tests.inproc_box import make_box

    sec = tmp_path / "sec"
    sec.mkdir()
    box = make_box(tmp_path / "box", tmp_path / "lake", sec, date(2026, 11, 2))
    box.orch.clock = clock
    return box


def test_a_job_and_a_derived_step_carry_the_boxs_day_on_its_own_clock(tmp_path: Any) -> None:
    """``--day data``: the box's clock stands on 2026-11-02; a job the orchestrator makes and a participant's step
    it derives itself both carry that day (``Orchestrator._now`` and ``orchestrator.app._now``)."""
    from datacore.lifecycle import Lifecycle
    from orchestrator import app as orch_app
    from orchestrator.lifecycle_api import refresh
    from tb_contracts import JobCreate

    from tools.list_demo import Clock

    box = _box_on_a_clock(tmp_path, Clock(date(2026, 11, 2), "Asia/Tokyo"))
    job = box.orch.create(JobCreate(type="RETENTION", requested_by="scheduler"))
    got = box.orch.db.get(job.job_id)
    assert got is not None and got.received_at.date() == date(2026, 11, 2)
    svc = orch_app.data_service_of(box.orch)
    refresh(svc, "GZQO", {"GZQO-0901": "c" * 32}, "service:test")
    steps = Lifecycle(svc.dc).steps("GZQO", "GZQO-0901")
    assert steps and {s["on_day"] for s in steps} == {"2026-11-02"}


def test_a_box_without_a_clock_keeps_the_wall_clock(tmp_path: Any) -> None:
    """The product (and the test stack's TB_TODAY) has no box clock: the stamps are the real time, as before."""
    from orchestrator import app as orch_app
    from tb_contracts import JobCreate

    box = _box_on_a_clock(tmp_path, None)
    for got in (box.orch._now(), orch_app._now(box.orch)):
        assert abs((got - datetime.now(UTC)).total_seconds()) < 120
    job = box.orch.create(JobCreate(type="RETENTION", requested_by="scheduler"))
    stored = box.orch.db.get(job.job_id)
    assert stored is not None and abs((stored.received_at - datetime.now(UTC)).total_seconds()) < 120
