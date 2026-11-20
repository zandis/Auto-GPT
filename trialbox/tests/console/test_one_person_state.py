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
import io
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from console import person_state as ps
from console.backend import Refused, Unavailable
from console.i18n import CATALOGUES, translate
from console.screening_log import SMALL_CELL, suppress

from tests.console.test_console_app import ADMIN_PW, _done_screen, _ulid, box, login, name_pi  # noqa: F401 - box: by name
from tests.console.test_lifecycle_pages import PW, _save, lb  # noqa: F401 - the fixture is used by name

A, B, C = "a" * 32, "b" * 32, "c" * 32
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
        assert re.search(rf'data-state="consented" data-testid="status-{study["no_a"]}">', log)  # the log page
        one = crc.get(f"/studies/GZQO/subjects/{study['gone']}").text
        assert _state_in(_cell(one, 'data-testid="life-now"', "</p>"))[0] == "withdrawn"
        # walk finding F-13: no contact step for a participant
        assert 'data-testid="outcome-done"' in sheet and 'data-testid="outcome-reached_booked"' not in sheet
        assert CATALOGUES[lang][ps.key("consented")] in html.unescape(sheet)


def _strip(page: str, tid: str) -> dict[str, int]:
    frag = _cell(page, f'data-testid="{tid}"', "</div>")
    return {k: int(n) for k, n in re.findall(r'data-state="([a-z_]+)"><b>(\d+)</b>', frag)}


def _funnel(page: str) -> dict[str, str]:
    frag = _cell(page, 'data-testid="pipeline-GZQO"', "</div>")
    return dict(re.findall(r'data-testid="pipeline-GZQO-([a-z]+)"><b>([^<]*)</b>', frag))


def _office(page: str) -> dict[str, str]:
    from console.screening_log import COUNT_KEYS

    row = re.search(r"<tr><td>GZQO</td>(.*?)</tr>", page, re.S)
    assert row, "no GZQO row"
    return dict(zip(COUNT_KEYS, [html.unescape(x) for x in re.findall(r'<td class="num">([^<]*)</td>', row.group(1))],
                    strict=True))  # fmt: skip


def test_the_home_card_the_registry_and_the_research_office_count_alike(study: dict[str, Any]) -> None:
    """The home card keeps master's funnel (cumulative), the registry counts people by state, the office keeps its
    eight cumulative columns; all three read the one state and reconcile by the written definition (D-1221)."""
    crc = _as(study["app"], "crc", "en")
    reg = _strip(crc.get("/pilot/registry/GZQO").text, "registry-counts")
    assert reg == {"need_info": 1, "consented": 1, "withdrawn": 1}, reg
    home = crc.get("/home").text
    assert 'data-testid="pipeline-GZQO-found"' in home and "PI reviewed" in home  # master's funnel, as people see it
    f = _funnel(home)
    # the written definition (D-1221): everyone who ever reached the step; the withdrawn participant had consented
    assert f["consented"] == str(sum(reg.get(s, 0) for s in ps.PARTICIPANT)) == "2"
    assert f["contacted"] == "2" and f["enrolled"] == "0"
    summary = _cell(crc.get("/pilot/registry").text, 'data-testid="summary-GZQO"')
    assert {k: int(v) for k, v in re.findall(r'data-state="([a-z_]+)">(\d+)<', summary)} == reg
    office = _office(crc.get("/reports/research-office?year=2026").text)
    for step in ("contacted", "consented", "enrolled"):
        assert office[step] == str(suppress(int(f[step]), SMALL_CELL)), (step, office)
    x = crc.get("/reports/research-office.xlsx?year=2026")
    from openpyxl import load_workbook

    head = [c.value for c in next(load_workbook(io.BytesIO(x.content)).worksheets[0].iter_rows(max_row=1))]
    assert head == ["study", "kind", "listed", "reviewed", "approached", "contacted", "consented", "enrolled",
                    "screen_fail", "declined"]  # fmt: skip


def test_the_registry_adds_by_chart_number_but_sets_no_status(study: dict[str, Any]) -> None:
    crc, csrf = login(study["app"], "crc", PW)
    page = crc.get("/pilot/registry/GZQO").text
    assert 'name="status"' not in page and 'name="mrn"' in page and 'data-testid="registry-add"' in page
    assert 'data-testid="registry-promote"' in page and 'data-testid="registry-export"' in page
    # a status sent is refused, not dropped (D-1221)
    r = crc.post("/pilot/registry/GZQO", data={"csrf": csrf, "pid": C, "status": "enrolled", "reason": "walk-in"})
    assert r.status_code == 400 and C not in {e.pid for e in study["reg"].rows("GZQO")}
    r = crc.post("/pilot/registry/GZQO", data={"csrf": csrf, "pid": C, "reason": "walk-in"}, follow_redirects=False)
    assert r.status_code == 303
    rows = {e.pid: e for e in study["reg"].rows("GZQO")}
    assert rows[C].status == "candidate" and rows[C].reason == "walk-in"
    # a person already on the log is never changed by an add: refused with their state and a link to their row
    before = {e.pid: (e.status, e.reason) for e in study["reg"].rows("GZQO")}
    for lang in LANGS:
        c = _as(study["app"], "crc", lang)
        page = c.get("/pilot/registry/GZQO").text
        r = c.post("/pilot/registry/GZQO", data={"csrf": _csrf(page), "pid": A, "reason": "again"})
        assert r.status_code == 409 and f'href="#p-{A}"' in r.text
        assert translate(lang, ps.key("consented")) in html.unescape(r.text), lang
    assert {e.pid: (e.status, e.reason) for e in study["reg"].rows("GZQO")} == before
    # the table counts the people the strip counts: one row each, a record without a pseudonym too
    page = crc.get("/pilot/registry/GZQO").text
    n_rows = len(re.findall(r'<tr data-pid="', page))
    listed = len(
        re.findall(r'<tr data-pid="[^"]*"[^>]*>\s*<td[^>]*>[^<]*</td>\s*<td><span class="pill ps-listed"', page)
    )
    assert n_rows == sum(_strip(page, "registry-counts").values()) + listed == 5


def test_the_administrator_adds_without_a_read_of_patient_rows(study: dict[str, Any]) -> None:
    """The matrix lets the administrator add to the screening log (``request.prepare``) and not read patient rows
    (``phi.view``, D-280): the add asks for no read of the log, so it is answered as the matrix says (the role walk
    of train 83 found it refused). An add that names nobody is refused for every role before anything is read."""
    bk = study["backend"]
    reads: list[str] = []
    rows = bk.registry_rows

    def counted(rs: str) -> Any:
        reads.append(rs)
        return rows(rs)

    bk.registry_rows = counted
    admin, csrf = login(study["app"], "admin", ADMIN_PW)
    r = admin.post("/pilot/registry/GZQO", data={"csrf": csrf, "pid": C, "reason": "walk-in"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/pilot/registry/GZQO", r.text[:300]
    assert reads == []  # no patient rows asked for this account
    assert {e.pid: e.status for e in study["reg"].rows("GZQO")}[C] == "candidate"
    n = len(study["reg"].rows("GZQO"))
    for user, pw in (("admin", ADMIN_PW), ("crc", PW)):
        c, token = login(study["app"], user, pw)
        reads.clear()  # the coordinator's home page reads the log; the add that names nobody does not
        r = c.post("/pilot/registry/GZQO", data={"csrf": token}, follow_redirects=False)
        assert r.status_code == 400 and "Give a chart number or a pseudonym".lower() in html.unescape(r.text).lower()
    assert reads == [] and len(study["reg"].rows("GZQO")) == n


def _seq(lb: dict[str, Any]) -> tuple[Any, str, Any, str]:  # noqa: F811
    bk, reg = lb["backend"], lb["reg"]
    bk.registry_rows = reg.rows
    bk.registry_update = lambda rs, upd, sign=None: reg.update(rs, upd, lb["clock"]["now"])
    _done_screen(bk, _ulid(1222))
    name_pi(lb, "pi")
    pi, pcsrf = login(lb["app"], "pi", PW)
    crc, csrf = login(lb["app"], "crc", PW)
    return pi, pcsrf, crc, csrf


def _tick(lb: dict[str, Any]) -> None:  # noqa: F811
    lb["clock"]["now"] += timedelta(minutes=5)  # every fact a later time, as in the clinic


def _mark(lb: dict[str, Any], pi: Any, csrf: str, mark: str, **kw: str) -> None:  # noqa: F811
    _tick(lb)
    r = pi.post(f"/studies/GZQO/patients/{A}/mark", data={"csrf": csrf, "mark": mark, "back": "patient", **kw},
                follow_redirects=False)  # fmt: skip
    assert r.status_code == 303, (mark, r.text[-300:])


def _outcome(lb: dict[str, Any], crc: Any, csrf: str, outcome: str) -> int:  # noqa: F811
    lb["clock"]["now"] += timedelta(days=1)  # the study's contact rule: a day between two attempts
    r = crc.post(f"/studies/GZQO/patients/{A}/outcome",
                 data={"csrf": csrf, "outcome": outcome, "back": "patient", "confirm": "yes"},
                 follow_redirects=False)  # fmt: skip
    return int(r.status_code)


def _sheet(crc: Any) -> tuple[str, bool]:
    page = crc.get(f"/studies/GZQO/patients/{A}").text
    return _pill(page, "patient-state"), 'data-testid="outcomes"' in page


def test_a_newer_fact_is_never_overridden_by_an_older_one(lb: dict[str, Any]) -> None:  # noqa: F811
    """Review of J-2 (A, S1): time decides. Not approached, then Approach again: to contact, the panel back;
    not reached, then Not suitable: set aside; not reached, then the mark taken back: on the list. The week row's quick
    outcomes show only where the outcome route takes one (an Approach mark in force, D-133)."""
    pi, pcsrf, crc, csrf = _seq(lb)
    _mark(lb, pi, pcsrf, "approach")
    assert _outcome(lb, crc, csrf, "not_approached") == 303
    assert _sheet(crc)[0] == "not_approached"
    _mark(lb, pi, pcsrf, "approach")  # A
    assert _sheet(crc) == ("to_contact", True)
    assert _outcome(lb, crc, csrf, "not_reached") == 303
    assert _sheet(crc)[0] == "to_contact"
    _mark(lb, pi, pcsrf, "not_suitable", reason="other")  # S1
    assert _sheet(crc)[0] == "set_aside"
    week = crc.get("/studies/GZQO/week?list=all").text
    assert f'data-testid="quick-{A[:8]}"' not in week
    assert _outcome(lb, crc, csrf, "not_reached") == 409  # the route refuses what the page no longer offers
    _mark(lb, pi, pcsrf, "approach")
    week = crc.get("/studies/GZQO/week?list=all").text
    assert f'data-testid="quick-{A[:8]}"' in week and f'data-testid="mark-{A[:8]}"' in week
    _mark(lb, pi, pcsrf, "withdraw")
    assert _sheet(crc)[0] == "listed"
    week = crc.get("/studies/GZQO/week?list=all").text
    assert f'data-testid="quick-{A[:8]}"' not in week


def test_declined_keeps_the_panel_and_an_undo_on_the_participant_page_is_followed(
        lb: dict[str, Any]) -> None:  # noqa: F811  # fmt: skip
    """Review of J-2 (D, F-13): a declined candidate keeps the contact panel; the record follows the decline (screen
    failure), the coordinator undoes that step on the participant page, and the state follows the undo. A
    participant (after consent) gets no panel, and the outcome route refuses with the page's own words."""
    pi, pcsrf, crc, csrf = _seq(lb)
    _mark(lb, pi, pcsrf, "approach")
    assert _outcome(lb, crc, csrf, "reached_booked") == 303
    no = lb["app"].state.helpers.store.screening_no("GZQO", A)
    crc.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})
    assert _outcome(lb, crc, csrf, "reached_declined") == 303
    _tick(lb)
    crc.get("/studies/GZQO/subjects")  # the record follows the log (screen failure, declined)
    state, panel = _sheet(crc)
    assert state == "declined" and panel  # a finished candidate keeps the panel, as on master
    _tick(lb)
    r = crc.post(f"/studies/GZQO/subjects/{no}/undo", data={"csrf": csrf, "note": "entered by mistake"})
    assert r.status_code in (200, 303), r.text[-300:]
    # D: the state follows the undo (record and log back before the decline): to contact again, the Approach in force
    assert _sheet(crc) == ("to_contact", True)
    _tick(lb)
    _save(crc, csrf, no, "tb_consent", {"ic_date": "2026-11-07", "ic_version": "v1", "ic_copy": "1"})
    state, panel = _sheet(crc)
    assert state == "consented" and not panel
    assert _outcome(lb, crc, csrf, "not_reached") == 409
    r = crc.post(
        f"/studies/GZQO/patients/{A}/outcome", data={"csrf": csrf, "outcome": "not_reached", "back": "patient"}
    )
    assert "Contact outcomes are for candidates" in html.unescape(r.text)


def test_no_new_refused_read_for_a_role_that_may_not_read_rows(study: dict[str, Any]) -> None:
    """The screening log is read through the real signing path (``actor.read_headers``, as the HTTP backend does); an
    administrator's registry index, research office and home page make no refused read (no ``console.denied``), and
    the registry index and the office show the aggregate counts."""
    from console import actor as console_actor

    real = study["reg"].rows

    def signed_rows(rs: str) -> Any:
        console_actor.read_headers("GET", f"/registry/{rs}")  # what HttpBackend._registry_call does first
        return real(rs)

    study["backend"].registry_rows = signed_rows
    study["backend"].registry_summaries = study["reg"].summaries  # the aggregate source (no patient row)
    admin, _ = login(study["app"])

    def denied() -> int:
        return sum(1 for e in study["backend"].audit(None, 5000) if e.event == "console.denied")

    for path in ("/pilot/registry", "/reports/research-office?year=2026", "/home?view=studies"):
        before = denied()
        assert admin.get(path).status_code == 200, path
        assert denied() == before, path
    page = admin.get("/pilot/registry").text
    assert re.search(r'data-testid="summary-GZQO">.*?data-state="consented">1<', page, re.S)


def test_an_unreadable_participant_store_makes_nobody_contactable(study: dict[str, Any]) -> None:
    """Fail safe (CR-010): the participant records cannot be read: the state is unknown, the counts "–", and
    nobody gets the contact panel or the quick outcomes by default."""
    real = study["backend"].study_api

    def broken(method: str, path: str, body: Any = None, headers: Any = None) -> Any:
        if method == "GET" and "/subjects" in path and "slim=1" in path:
            raise Unavailable("the study store is down")
        return real(method, path, body, headers=headers) if headers else real(method, path, body)

    study["backend"].study_api = broken
    crc, _ = login(study["app"], "crc", PW)
    page = crc.get(f"/studies/GZQO/patients/{B}").text
    assert _pill(page, "patient-state") == ps.UNKNOWN and 'data-testid="outcomes"' not in page
    assert "–" in _funnel(crc.get("/home").text).values()
    week = crc.get("/studies/GZQO/week?list=all").text
    assert 'data-testid="quick-' not in week


def test_an_erased_token_is_on_no_page_and_in_no_count(study: dict[str, Any]) -> None:
    """D-875: an erased screening-log row (``erased:<day>:<hex>``) is matched by the opt-out register's own test; it
    is on no list, in no count (home funnel, registry strip and index, office) and its token is printed nowhere."""
    token = "erased:2026-11-01:abcd"
    real = study["reg"].rows

    def rows(rs: str) -> Any:
        from tb_contracts import RegistryEntry

        e = RegistryEntry(
            ruleset=rs,
            pid=token,
            status="consented",
            reason=None,
            updated_at=datetime(2026, 11, 1, tzinfo=UTC),
            updated_by="console:crc",
            source="manual",
        )
        return [*real(rs), e]  # fmt: skip

    crc = _as(study["app"], "crc", "en")
    plain = {p: crc.get(p).text for p in ("/home", "/pilot/registry/GZQO", "/pilot/registry",
                                            "/reports/research-office?year=2026")}  # fmt: skip
    study["backend"].registry_rows = rows
    for path, before in plain.items():
        page = crc.get(path).text
        assert token not in page and "abcd" not in page, path
        if path == "/home":
            assert _funnel(page) == _funnel(before)
        if path == "/pilot/registry/GZQO":
            assert _strip(page, "registry-counts") == _strip(before, "registry-counts")
        if path.startswith("/reports"):
            assert _office(page) == _office(before)


def test_the_office_fails_closed_for_a_reader_whose_read_fails(study: dict[str, Any]) -> None:
    """CR-010: a reader who may read the rows but whose read fails gets "–" and the sentence, never the aggregate."""
    crc, _ = login(study["app"], "crc", PW)

    def refused(rs: str) -> Any:
        raise Refused("the signed-in person is refused")

    study["backend"].registry_rows = refused
    page = crc.get("/reports/research-office?year=2026").text
    cells = _office(page)
    assert all(cells[s] == "–" for s in ("contacted", "consented", "enrolled", "screen_fail", "declined")), cells
    assert 'data-testid="office-unread"' in page and 'data-testid="office-aggregate"' not in page
    assert "–" in _funnel(crc.get("/home").text).values()


def test_a_role_without_rows_sees_masters_figures_and_is_told_what_they_are(study: dict[str, Any]) -> None:
    """The administrator's office: the log's own counts by status for the whole study, by master's formula (the same
    numbers master's office gave on the same data when its read was let through), with one sentence saying so."""
    from console.screening_log import aggregate_counts

    study["backend"].registry_summaries = study["reg"].summaries
    rows = study["reg"].rows("GZQO")
    master = {  # master's office formula (screening_log.office_counts on 15108f46), over every row of the log
        "contacted": sum(1 for e in rows if {"contacted": 1, "consented": 2, "enrolled": 3}.get(e.status, 0) >= 1
                         or e.status == "screen_fail"),
        "consented": sum(1 for e in rows if {"contacted": 1, "consented": 2, "enrolled": 3}.get(e.status, 0) >= 2),
        "enrolled": sum(1 for e in rows if e.status == "enrolled"),
        "screen_fail": sum(1 for e in rows if e.status == "screen_fail"),
        "declined": sum(1 for e in rows if e.status == "declined"),
    }  # fmt: skip
    by: dict[str, int] = {}
    for e in rows:
        by[e.status] = by.get(e.status, 0) + 1
    assert aggregate_counts(by) == master
    for lang in LANGS:
        admin, acsrf = login(study["app"], "admin", ADMIN_PW)
        admin.post("/lang", data={"csrf": acsrf, "lang": lang, "back": "/"})
        page = admin.get("/reports/research-office?year=2026").text
        cells = _office(page)
        assert {k: cells[k] for k in master} == {k: str(suppress(v, SMALL_CELL)) for k, v in master.items()}
        assert translate(lang, "registry.office.aggregate") in html.unescape(page), lang


def _api(app: Any) -> Any:
    from fastapi.testclient import TestClient

    c = TestClient(app)
    r = c.post("/api/v1/session", json={"username": "crc", "password": PW, "lang": "en"})
    c.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return c


def test_an_unreadable_participant_store_falls_back_to_the_log_before_consent(lb: dict[str, Any]) -> None:  # noqa: F811
    """Availability: the participant records cannot be read, but the screening log says the person is before
    consent: the outcome is taken (the log decides before consent, as on master). With the log unread too: 503 and
    a retry message, on the page and on /api/v1 (a JSON problem)."""
    pi, pcsrf, crc, csrf = _seq(lb)
    _mark(lb, pi, pcsrf, "approach")
    real = lb["backend"].study_api

    def broken(method: str, path: str, body: Any = None, headers: Any = None) -> Any:
        if method == "GET" and "/subjects" in path:
            raise Unavailable("the study store is down")
        return real(method, path, body, headers=headers) if headers else real(method, path, body)

    lb["backend"].study_api = broken
    assert _outcome(lb, crc, csrf, "not_reached") == 303
    api = _api(lb["app"])
    lb["clock"]["now"] += timedelta(days=1)
    r = api.post(f"/api/v1/studies/GZQO/patients/{A}/outcome", json={"outcome": "not_reached"})
    assert r.status_code == 200, r.text[:300]

    def refused(rs: str) -> Any:
        raise Unavailable("the log is down")

    lb["backend"].registry_rows = refused
    lb["clock"]["now"] += timedelta(days=1)
    r = crc.post(
        f"/studies/GZQO/patients/{A}/outcome", data={"csrf": csrf, "outcome": "not_reached", "back": "patient"}
    )
    assert r.status_code == 503 and "Try again in a moment" in html.unescape(r.text)
    r = api.post(f"/api/v1/studies/GZQO/patients/{A}/outcome", json={"outcome": "not_reached"})
    assert r.status_code == 503 and r.json()["error"] == "outcome.state_unknown"


def test_a_participant_and_a_closed_study_are_refused_on_the_api_too(lb: dict[str, Any]) -> None:  # noqa: F811
    pi, pcsrf, crc, csrf = _seq(lb)
    _mark(lb, pi, pcsrf, "approach")
    assert _outcome(lb, crc, csrf, "reached_booked") == 303
    no = lb["app"].state.helpers.store.screening_no("GZQO", A)
    crc.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})
    _tick(lb)
    _save(crc, csrf, no, "tb_consent", {"ic_date": "2026-11-07", "ic_version": "v1", "ic_copy": "1"})
    api = _api(lb["app"])
    lb["clock"]["now"] += timedelta(days=1)
    r = api.post(f"/api/v1/studies/GZQO/patients/{A}/outcome", json={"outcome": "not_reached"})
    assert r.status_code == 409 and r.json()["error"] == "outcome.participant"  # the API's problem body names the key
    # a closed study: no quick outcome, and the route refuses (page and API)
    lb["app"].state.helpers.store.set_study_state("GZQO", "closed", "done", "crc", lb["clock"]["now"].isoformat())
    week = crc.get("/studies/GZQO/week?list=all").text
    assert 'data-testid="quick-' not in week
    r = crc.post(
        f"/studies/GZQO/patients/{B}/outcome", data={"csrf": csrf, "outcome": "not_reached", "back": "patient"}
    )
    assert r.status_code == 409 and "the study is closed" in html.unescape(r.text)
    r = api.post(f"/api/v1/studies/GZQO/patients/{B}/outcome", json={"outcome": "not_reached"})
    assert r.status_code == 409 and r.json()["error"] == "outcome.closed"


def test_separate_clocks_a_tokyo_site_re_approach_after_a_decline(lb: dict[str, Any]) -> None:  # noqa: F811
    """The console stamps in UTC, the orchestrator in the site's zone (+09:00): the PI's Approach an hour after a
    decline is the newer fact (a text comparison read the log 9 h newer)."""
    tokyo = ZoneInfo("Asia/Tokyo")
    h = lb["app"].state.helpers
    h.clock = lambda: lb["clock"]["now"].astimezone(UTC)
    pi, pcsrf, crc, csrf = _seq(lb)
    lb["backend"].registry_update = lambda rs, upd, sign=None: lb["reg"].update(
        rs, upd, lb["clock"]["now"].astimezone(tokyo)
    )  # the orchestrator's own clock, in the site's zone
    _mark(lb, pi, pcsrf, "approach")
    assert _outcome(lb, crc, csrf, "reached_declined") == 303
    assert [e.updated_at.utcoffset() for e in lb["reg"].rows("GZQO")] == [timedelta(hours=9)]
    lb["clock"]["now"] += timedelta(hours=1)
    _mark(lb, pi, pcsrf, "approach")
    assert _sheet(crc) == ("to_contact", True)
