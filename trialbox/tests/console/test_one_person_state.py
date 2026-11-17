"""D-1221 (review R10, B-2, D-2): every list that shows a person names the same state, in en, zh-TW and ja, and the
home card, the registry and the research office count alike; the registry has no status form of its own.

On the orchestrator's real data core, lifecycle API and candidate registry (``lb`` of the lifecycle page tests), the
console's registry reads wired to that same registry. Three people of GZQO:

* ``a`` (on the list, high tier): the investigator marks Approach, the coordinator reaches them and books a visit,
  the consent form is saved: **Consented**;
* ``b`` (on the list, review tier): the investigator asks for information: **Waiting for information**;
* the first numbered person of the fixture: contacted, consented, then withdrawn by the form: **Withdrawn**.
"""

from __future__ import annotations

import html
import re
from typing import Any

import pytest
from console import person_state as ps
from console.backend import Refused
from console.i18n import CATALOGUES, translate
from console.screening_log import SMALL_CELL, suppress

from tests.console.test_console_app import _done_screen, _ulid, box, login, name_pi  # noqa: F401 - box: by name
from tests.console.test_lifecycle_pages import PW, _save, lb  # noqa: F401 - the fixture is used by name

A, B = "a" * 32, "b" * 32
LANGS = ("en", "zh-TW", "ja")


def _csrf(page: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', page)
    assert m
    return m.group(1)


def _as(app: Any, user: str, lang: str) -> Any:
    c, csrf = login(app, user, PW)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
    return c


@pytest.fixture
def study(lb: dict[str, Any]) -> dict[str, Any]:  # noqa: F811
    bk, reg = lb["backend"], lb["reg"]
    bk.registry_rows = reg.rows  # one screening log: the console's reads and the lifecycle's mirror
    bk.registry_update = lambda rs, upd, sign=None: reg.update(rs, upd, lb["clock"]["now"])
    _done_screen(bk, _ulid(1221))
    name_pi(lb, "pi")
    pi, pcsrf = login(lb["app"], "pi", PW)
    for pid, mark in ((A, "approach"), (B, "need_info")):
        r = pi.post(f"/studies/GZQO/patients/{pid}/mark", data={"csrf": pcsrf, "mark": mark, "back": "patient"},
                    follow_redirects=False)  # fmt: skip
        assert r.status_code == 303, r.text[-400:]
    crc, csrf = login(lb["app"], "crc", PW)
    # F-05: approved, nobody called yet: "To contact" on the weekly page, not "contacted"
    week = crc.get("/studies/GZQO/week?list=approached").text
    assert _state_in(_cell(week, f'data-testid="row-{A[:8]}"')) == ["to_contact"] and ">To contact<" in week
    r = crc.post(f"/studies/GZQO/patients/{A}/outcome", data={"csrf": csrf, "outcome": "reached_booked",
                                                              "back": "patient"}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303, r.text[-400:]
    no_a = lb["app"].state.helpers.store.screening_no("GZQO", A)
    assert no_a
    crc.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})
    assert crc.get("/studies/GZQO/subjects").status_code == 200  # the participants follow the screening numbers
    _save(crc, csrf, no_a, "tb_consent", {"ic_date": "2026-11-05", "ic_version": "v1", "ic_copy": "1"})
    gone = lb["nos"][0]
    crc.post(f"/studies/GZQO/subjects/{gone}/step", data={"csrf": csrf, "to": "approached", "on_day": "2026-11-02"})
    _save(crc, csrf, gone, "tb_consent", {"ic_date": "2026-11-03", "ic_version": "v1", "ic_copy": "1"})
    r = _save(crc, csrf, gone, "tb_withdrawal", {"wd_date": "2026-11-06", "wd_reason": "3", "wd_data_use": "1"},
              back="subject")  # fmt: skip
    assert 'data-state="withdrawn"' in r.text
    return {**lb, "no_a": no_a, "gone": gone}


def _cell(page: str, start: str, end: str = "</tr>") -> str:
    i = page.index(start)
    return page[i : page.index(end, i)]


def _state_in(fragment: str) -> list[str]:
    return re.findall(r'data-state="([a-z_]+)"', fragment)


def _pill(page: str, tid: str) -> str:
    m = re.search(rf'<span[^>]*data-state="([a-z_]+)"[^>]*data-testid="{tid}"', page)
    assert m, tid
    return m.group(1)


def test_every_list_names_the_same_person_with_the_same_state_in_three_languages(study: dict[str, Any]) -> None:
    app = study["app"]
    want = {A: "consented", B: "need_info"}
    for lang in LANGS:
        word = {pid: translate(lang, ps.key(s)) for pid, s in want.items()}
        crc, pi = _as(app, "crc", lang), _as(app, "pi", lang)
        for who, c in (("crc", crc), ("pi", pi)):
            week = c.get("/studies/GZQO/week?list=all").text
            for pid, s in want.items():
                row = _cell(week, f'data-testid="row-{pid[:8]}"')
                assert _state_in(row) == [s] and word[pid] in html.unescape(row), (who, lang, pid)
        cands = crc.get("/studies/GZQO/candidates").text
        for pid, s in want.items():
            row = _cell(cands, f'data-testid="cand-{pid[:8]}"')
            assert _state_in(row) == [s] and word[pid] in html.unescape(row), (lang, pid)
        sheet = crc.get(f"/studies/GZQO/patients/{A}").text
        assert _pill(sheet, "patient-state") == "consented"
        reg = crc.get("/pilot/registry/GZQO").text
        for pid, s in want.items():
            row = _cell(reg, f'data-pid="{pid}"')
            assert _state_in(row) == [s] and word[pid] in html.unescape(row), (lang, pid)
        subs = crc.get("/studies/GZQO/subjects").text
        for rec, s in ((study["no_a"], "consented"), (study["gone"], "withdrawn")):
            row = _cell(subs, f'data-testid="subject-{rec}"')
            assert _state_in(row) == [s] and translate(lang, ps.key(s)) in html.unescape(row), (lang, rec)
        log = crc.get("/studies/GZQO/screening-log").text
        assert _state_in(_cell(log, f'data-testid="status-{study["no_a"]}"', "</td>")) == ["consented"]
        one = crc.get(f"/studies/GZQO/subjects/{study['gone']}").text
        assert _state_in(_cell(one, 'data-testid="life-now"', "</p>"))[0] == "withdrawn"
        # walk finding F-13: no contact step for a participant
        assert 'data-testid="outcome-done"' in sheet and 'data-testid="outcome-reached_booked"' not in sheet
        assert CATALOGUES[lang][ps.key("consented")] in html.unescape(sheet)


def _strip(page: str, tid: str) -> dict[str, int]:
    frag = _cell(page, f'data-testid="{tid}"', "</div>")
    return {k: int(n) for k, n in re.findall(r'data-state="([a-z_]+)"><b>(\d+)</b>', frag)}


def test_the_home_card_the_registry_and_the_research_office_count_alike(study: dict[str, Any]) -> None:
    crc = _as(study["app"], "crc", "en")
    home = _strip(crc.get("/home").text, "pipeline-GZQO")
    reg = _strip(crc.get("/pilot/registry/GZQO").text, "registry-counts")
    assert home == reg == {"need_info": 1, "consented": 1, "withdrawn": 1}, (home, reg)
    summary = _cell(crc.get("/pilot/registry").text, 'data-testid="summary-GZQO"')
    assert {k: int(v) for k, v in re.findall(r'data-state="([a-z_]+)">(\d+)<', summary)} == home
    office = _cell(crc.get("/reports/research-office?year=2026").text, 'data-testid="office-GZQO"')
    cells = dict(re.findall(r'data-key="([a-z_]+)">([^<]*)<', office))
    for s in ps.COUNTED:
        assert html.unescape(cells[s]) == str(suppress(home.get(s, 0), SMALL_CELL)), (s, cells[s])
    # the B-2 symptom: no list says "consented 2, enrolled 1" while another says 1 and 1
    assert "enrolled" not in home and "contacted" not in home


def test_the_registry_has_no_status_form_and_its_post_is_gone(study: dict[str, Any]) -> None:
    crc, csrf = login(study["app"], "crc", PW)
    page = crc.get("/pilot/registry/GZQO").text
    assert 'name="status"' not in page and 'name="mrn"' not in page and 'data-testid="registry-add"' not in page
    assert 'data-testid="registry-promote"' in page and 'data-testid="registry-export"' in page
    before = {e.pid: e.status for e in study["reg"].rows("GZQO")}
    r = crc.post("/pilot/registry/GZQO", data={"csrf": csrf, "pid": B, "status": "enrolled"})
    assert r.status_code == 405
    assert {e.pid: e.status for e in study["reg"].rows("GZQO")} == before


def test_a_log_that_cannot_be_read_counts_unknown_never_zero(study: dict[str, Any]) -> None:
    """CR-010: the orchestrator refuses the screening log to this reader (as it does an account without the right to
    patient-level rows, D-280): the counts are unknown ("–", a sentence), never a quiet 0."""
    crc, _ = login(study["app"], "crc", PW)

    def refused(rs: str) -> Any:
        raise Refused("the signed-in person is refused")

    study["backend"].registry_rows = refused
    office = crc.get("/reports/research-office?year=2026").text
    cells = dict(re.findall(r'data-key="([a-z_]+)">([^<]*)<', _cell(office, 'data-testid="office-GZQO"')))
    assert all(cells[s] == "–" for s in ps.COUNTED), cells
    assert 'data-testid="pipeline-GZQO-unread"' in crc.get("/home").text
