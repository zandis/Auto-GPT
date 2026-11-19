# ruff: noqa: F811 - the fixtures are imported from other test modules and taken by name
"""J-6 (D-1225; the journey review's R8, R19, R35; root review 09's J3 and DS-13): the opening page's "Next" for the
whole life of a study, and "Needs you today", behind the flag ``layout.home_today``.

* the flag is declared, off by default, described in three languages; with it off ``/home`` is as before;
* the Next step of a study from start-up to archive (:func:`console.home_today.life_step`), table-tested, and on the
  real page for the coordinator, the investigator, the viewer and the CRO, with the link (or none) of each;
* "Needs you today": safety first, then overdue, then due today; never more than five lines, "N more" and the whole
  list beyond; "nothing" said plainly; one line per serious adverse event, nothing twice on the page;
* the lines read only what the role may read: a role with no patient-level row shows no pseudonym and makes no
  patient-level read;
* the role walk with the flag on answers every route as its declared row.

Synthetic data only."""

from __future__ import annotations

import html
import re
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from console import home_today as ht
from console import i18n_flags, i18n_today, phone
from console.i18n import CATALOGUES
from fastapi.testclient import TestClient
from tb_common import flags as fl

from tests.console.test_console_app import VIEWER_PW, box, login  # noqa: F401
from tests.console.test_lifecycle_pages import PW, _save, lb  # noqa: F401

LANGS = ("en", "ja", "zh-TW")


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    fl.clear_cache()
    phone.clear_cache()
    yield
    fl.clear_cache()
    phone.clear_cache()


def _flag(b: dict[str, Any], value: str) -> None:
    """The administrator's change on /ops/flags: audited, with a reason."""
    fl.Flags(audit=b["audit"]).set(ht.FLAG, value, actor="console:admin", reason="J-6 test (D-1225)")
    fl.clear_cache()
    phone.clear_cache()
    phone.read_now()  # read now: a page gets the value last read


def _region(page: str) -> str:
    """The page's content (the menu and the footer left out)."""
    return page.split("<main", 1)[1].split("</main>", 1)[0] if "<main" in page else page


def _today(page: str) -> str:
    return page.split('data-testid="today"', 1)[1].split("</section>", 1)[0]


def _lines(page: str) -> list[tuple[str, str]]:
    """(kind, href) of each line of "Needs you today"."""
    return re.findall(r'data-testid="today-([a-z_]+)" data-what="[^"]*">\s*<a href="([^"]+)"', _today(page))


def _next(page: str, rs: str = "GZQO") -> tuple[str, str]:
    """(step, link or "") of the study's Next line."""
    m = re.search(rf'<p class="next today-next" data-testid="next-{rs}" data-step="([a-z_]+)">(.*?)</p>', page, re.S)
    assert m, page[-3000:]
    link = re.search(r'href="([^"]+)"', m.group(2))
    return m.group(1), (link.group(1).replace("&amp;", "&") if link else "")


# ------------------------------------------------------------------------------------------- the flag, the words
def test_the_flag_is_declared_off_and_described_in_three_languages(box: dict[str, Any]) -> None:
    d = fl.DECLARED[ht.FLAG]
    assert d.default == "off" and d.values == ("off", "on") and d.seed_env is None
    assert fl.Flags().row(ht.FLAG) == "off" and not phone.home_today_on()  # seeded off at create_app
    for cat in (i18n_flags.EN, i18n_flags.JA, i18n_flags.ZH):
        assert cat[f"flags.desc.{ht.FLAG}"]


def test_the_two_layout_flags_are_read_together_in_one_read(box: dict[str, Any], monkeypatch: Any) -> None:
    """One background read answers both layout flags (``Flags.rows``), and ``/home`` takes its value from the request,
    so the opening page adds no read of its own to the store (the review of D-1225)."""
    reads: list[tuple[str, ...]] = []
    real = fl.Flags.rows

    def rows(self: Any, names: Any) -> dict[str, str]:
        reads.append(tuple(names))
        return real(self, names)

    monkeypatch.setattr(fl.Flags, "rows", rows)
    fl.Flags(audit=box["audit"]).set(ht.FLAG, "on", actor="console:admin", reason="J-6 test (D-1225)")
    assert phone.read_now() == {phone.FLAG: False, ht.FLAG: True}
    assert reads == [(phone.FLAG, ht.FLAG)]
    assert fl.Flags().rows([ht.FLAG]) == {ht.FLAG: "on"}


def test_every_line_and_every_next_has_its_words_in_three_languages() -> None:
    assert set(i18n_today.EN) == set(i18n_today.JA) == set(i18n_today.ZH)
    keys = [f"today.next.{k}" for k in ht.NEXT_KEYS] + [f"today.line.{k}" for k in ht.KINDS]
    for lang in LANGS:
        for k in keys:
            assert CATALOGUES[lang].get(k), (lang, k)
    for cat in (i18n_today.JA, i18n_today.ZH):
        for k, v in cat.items():
            assert set(re.findall(r"\{(\w+)\}", i18n_today.EN[k])) == set(re.findall(r"\{(\w+)\}", v)), k


# ------------------------------------------------------------------------------------------- the rule, as a table
@pytest.mark.parametrize(
    ("state", "step", "screened", "counts", "want"),
    [
        ("startup", 1, False, {}, "startup"),
        ("open", 1, False, {}, "approve"),
        ("open", 2, False, {}, "feas"),
        ("open", 3, False, {}, "screen"),
        ("open", 3, True, None, "unknown"),
        ("open", 3, True, {"listed": 4}, "review"),
        ("open", 3, True, {"listed": 4, "to_contact": 1}, "contact"),
        ("open", 4, True, {"contacted": 1}, "consent"),
        ("open", 5, True, {"enrolled": 1}, "conduct"),
        ("open", 5, True, {"on_study": 1, "withdrawn": 1}, "conduct"),
        ("open", 5, True, {"completed": 1, "withdrawn": 1}, "close"),
        ("open", 5, True, {"completed": 1, "declined": 2, "screen_fail": 1}, "close"),
        # the review of D-1225: a withdrawn participant is no reason to close while candidates are in progress
        ("open", 5, True, {"withdrawn": 1, "contacted": 2, "to_contact": 1}, "consent"),
        ("open", 5, True, {"completed": 1, "to_contact": 1}, "contact"),
        ("open", 5, True, {"completed": 1, "listed": 3}, "review"),
        ("open", 5, True, {"completed": 1, "set_aside": 1}, "review"),
        ("open", 4, True, {"consented": 1}, "consent"),
        # the week page's step bar at step 4 is "Contact and screen", even when everyone contacted screen-failed
        ("open", 4, True, {"screen_fail": 1, "listed": 2}, "contact"),
        ("open", 4, True, {"screen_fail": 3}, "contact"),
        ("open", 3, True, {"listed": 3}, "review"),
        ("paused", 5, True, {"on_study": 1}, "paused"),
        ("closed", 5, True, {"completed": 1}, "closed"),
    ],
)
def test_the_next_step_from_start_up_to_archive(state: str, step: int, screened: bool, counts: Any, want: str) -> None:
    assert ht.life_step(state=state, step=step, screen_done=screened, counts=counts) == want


def test_the_order_is_safety_then_overdue_then_today_and_each_thing_once() -> None:
    d = date(2026, 11, 9)
    tasks = [
        {"kind": "call", "rs": "A1", "short": "p1", "href": "/a", "due": date(2026, 11, 9)},
        {"kind": "call", "rs": "A1", "short": "p2", "href": "/b", "due": date(2026, 11, 7)},
        {"kind": "call", "rs": "A1", "short": "p3", "href": "/c", "due": date(2026, 11, 12)},  # not due: not today's
        {"kind": "approve", "rs": "A1", "short": "FEAS", "href": "/d", "due": d},  # the PI's step: the Next line
    ]
    sae = ht.sae_lines("A1", [{"record": "A1-0001", "event": "ae1"}],
                       [{"record": "A1-0001", "event": "ae1", "party": "irb", "due": "2026-11-08"},
                        {"record": "A1-0001", "event": "ae1", "party": "no_clock", "due": ""}],
                       acknowledges=False)  # fmt: skip
    got = ht.ordered(ht.task_lines(tasks, d) + ht.visit_lines("A1", 2, 1, d) + sae + sae)
    assert [(x.kind, x.what) for x in got] == [
        ("sae_overdue", "A1-0001/ae1"),  # one line for the event, its three reasons and its copy
        ("visits_overdue", "overdue"),  # overdue with no day of its own: first among the overdue
        ("call", "p2"),
        ("visits_today", "today"),
        ("call", "p1"),
    ]
    ack = ht.sae_lines("A1", [{"record": "A1-0001", "event": "ae1"}], [], acknowledges=True)
    assert [x.kind for x in ack] == ["sae_ack"]


# ------------------------------------------------------------------------------------------- the pages
def test_with_the_flag_off_the_opening_pages_are_as_before(lb: dict[str, Any]) -> None:
    from tests.console.test_console_app import name_pi

    name_pi(lb, "pi")
    crc, _ = login(lb["app"], "crc", PW)
    page = crc.get("/home").text
    assert 'data-testid="today"' not in page and "today-next" not in page and 'data-testid="next-GZQO"' in page
    pi, _ = login(lb["app"], "pi", PW)
    r = pi.get("/home", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/week"  # the investigator's first page, as before
    v, _ = login(lb["app"], "viewer", VIEWER_PW)
    r = v.get("/home", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/reports"


def _lang(c: TestClient, lang: str) -> None:
    csrf = re.search(r'name="csrf" value="([^"]+)"', c.get("/account").text)
    assert csrf
    c.post("/lang", data={"csrf": csrf.group(1), "lang": lang, "back": "/"})


def test_the_next_line_follows_the_life_of_the_study_for_each_role(lb: dict[str, Any]) -> None:
    from tests.console.test_console_app import _done_feas, _done_screen, _ulid, name_pi

    bk, reg, h = lb["backend"], lb["reg"], lb["app"].state.helpers
    bk.registry_rows = reg.rows  # one screening log: the console's reads and the lifecycle's mirror
    bk.registry_update = lambda rs, upd, sign=None: reg.update(rs, upd, lb["clock"]["now"])
    name_pi(lb, "pi")
    lb["users"].create("mon1", "cro", PW, "mon1@cro.test")
    lb["users"].set_scope("mon1", affiliation="cro", studies="GZQO")
    _flag(lb, "on")
    crc, csrf = login(lb["app"], "crc", PW)
    pi, pcsrf = login(lb["app"], "pi", PW)
    v, _ = login(lb["app"], "viewer", VIEWER_PW)
    mon, _ = login(lb["app"], "mon1", PW)

    def nexts() -> dict[str, tuple[str, str]]:
        return {who: _next(c.get("/home").text) for who, c in (("crc", crc), ("pi", pi), ("viewer", v), ("cro", mon))}

    # no feasibility count yet: the coordinator's step (and the PI's, who may run it, D-349)
    n = nexts()
    assert n["crc"] == n["pi"] == ("feas", "/pilot/request?ruleset=GZQO")
    assert n["viewer"] == n["cro"] == ("report_none", "")
    _done_feas(bk)
    n = nexts()
    assert n["crc"] == ("screen", "/pilot/request?ruleset=GZQO")
    assert n["viewer"] == n["cro"] == ("report", "/studies/GZQO/feasibility")
    _done_screen(bk, _ulid(1225))
    n = nexts()
    assert n["pi"] == ("review", "/studies/GZQO/week?list=review") and n["crc"] == ("review", "")
    assert "the investigator reviews this week's candidates next. Nothing is needed from you." in html.unescape(
        crc.get("/home").text
    )
    a = "a" * 32
    r = pi.post(f"/studies/GZQO/patients/{a}/mark", data={"csrf": pcsrf, "mark": "approach", "back": "patient"},
                follow_redirects=False)  # fmt: skip
    assert r.status_code == 303
    n = nexts()
    assert n["crc"] == ("contact", "/studies/GZQO/week?list=approached") and n["pi"] == ("contact", "")
    lb["clock"]["now"] = datetime(2026, 11, 8, 2, 0, tzinfo=UTC)
    r = crc.post(f"/studies/GZQO/patients/{a}/outcome", data={"csrf": csrf, "outcome": "reached_booked",
                                                              "back": "patient"}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303, r.text[-300:]
    n = nexts()
    assert n["crc"] == n["pi"] == ("consent", "/studies/GZQO/subjects")  # the logged PI enters data too (D-380)
    no_a = h.store.screening_no("GZQO", a)
    crc.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})
    assert crc.get("/studies/GZQO/subjects").status_code == 200
    _save(crc, csrf, no_a, "tb_consent", {"ic_date": "2026-11-05", "ic_version": "v1", "ic_copy": "1"})
    _save(crc, csrf, no_a, "tb_enrolment", {"en_date": "2026-11-06", "en_eligible": "1"})
    n = nexts()
    assert n["crc"] == ("conduct", "/studies/GZQO/visits")
    assert n["viewer"] == ("report", "/studies/GZQO/feasibility")  # an aggregate account reads no participant
    # the CRO under a monitor grant: the monitoring page is its next step
    r = pi.post("/studies/GZQO/team", data={"csrf": pcsrf, "username": "mon1", "role": "monitor", "start": "2026-01-01",
                                           "end": "2099-12-31", "training_ref": "MV-0001"}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303, r.text[-300:]
    assert _next(mon.get("/home").text) == ("monitor", "/studies/GZQO/monitor")
    assert mon.get("/studies/GZQO/monitor").status_code == 200  # the link opens for this account
    for to in ("on_study", "completed"):  # the last participant ends the study
        r = crc.post(f"/studies/GZQO/subjects/{no_a}/step", data={"csrf": csrf, "to": to, "on_day": "2026-11-07",
                                                                  "confirm": "yes"})  # fmt: skip
        assert f'data-state="{to}"' in r.text, r.text[-500:]
    assert nexts()["crc"] == ("review", "")  # two candidates still on the list: not yet "close"; the PI's step
    for other in lb["nos"]:  # the two other candidates end: nobody is in progress any more
        r = crc.post(f"/studies/GZQO/subjects/{other}/step", data={"csrf": csrf, "to": "screen_fail",
                     "reason": "other", "on_day": "2026-11-07", "confirm": "yes"})  # fmt: skip
        assert 'data-state="screen_fail"' in r.text, r.text[-500:]
    assert nexts()["crc"] == ("close", "/studies/GZQO/state")
    h.store.set_study_state("GZQO", "paused", "J-6 test", "crc", "2026-11-08T02:00:00+00:00")
    assert nexts()["crc"] == ("paused", "/studies/GZQO/state")
    h.store.set_study_state("GZQO", "closed", "J-6 test", "crc", "2026-11-08T02:00:00+00:00", keep_years=7)
    n = nexts()
    assert n["crc"] == n["pi"] == ("closed", "")  # archived outside the product: said, not linked
    page = html.unescape(crc.get("/home").text)
    assert "Its files are kept for 7 years in the site's archive, outside TrialBox." in page
    for lang, words in (("ja", "施設の保管庫で 7 年保管されます"), ("zh-TW", "於試驗中心的檔案室保存 7 年")):
        _lang(crc, lang)
        assert words in crc.get("/home").text, lang


def _participant_with_saes(lb: dict[str, Any], n_sae: int) -> tuple[TestClient, TestClient, str]:
    from tests.console.test_console_app import _done_feas, _done_screen, _ulid, name_pi

    _done_feas(lb["backend"])
    _done_screen(lb["backend"], _ulid(1227))
    name_pi(lb, "pi")
    no = lb["nos"][0]
    crc, csrf = login(lb["app"], "crc", PW)
    crc.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})
    crc.get("/studies/GZQO/subjects")
    _save(crc, csrf, no, "tb_consent", {"ic_date": "2026-11-01", "ic_version": "v1", "ic_copy": "1"})
    _save(crc, csrf, no, "tb_enrolment", {"en_date": "2026-11-01", "en_eligible": "1"})
    lb["oc"].put("/studies/GZQO/schedule", json={"visits": [{"visit": "v1", "day": 7, "before": 1, "after": 1},
                                                            {"visit": "v2", "day": 1, "before": 0, "after": 2}],
                                                 "by": "crc"})  # fmt: skip
    lb["clock"]["now"] = datetime(2026, 11, 9, 1, 0, tzinfo=UTC)  # v1 due today, v2 overdue
    for i in range(1, n_sae + 1):
        r = _save(crc, csrf, no, "tb_adverse_event", {"ae_term": f"Pneumonia {i}", "ae_onset": "2026-11-08",
                  "ae_serious": "1", "ae_serious_why": "3", "ae_severity": "3", "ae_related": "9"}, f"ae{i}",
                  "subject")  # fmt: skip
        assert f'data-testid="ae-ae{i}"' in r.text
    pi, _ = login(lb["app"], "pi", PW)
    return crc, pi, no


def test_needs_you_today_safety_first_each_line_to_its_page_and_nothing_twice(lb: dict[str, Any]) -> None:
    crc, pi, no = _participant_with_saes(lb, 1)
    off = crc.get("/home").text
    assert off.count('data-testid="sae-banner"') == 1 and 'data-testid="sae-reports"' in off  # today: two cards
    _flag(lb, "on")
    for lang in LANGS:
        _lang(crc, lang)
        _lang(pi, lang)
        page = crc.get("/home").text
        assert _lines(page) == [
            ("sae_noclock", f"/studies/GZQO/sae/{no}/ae1"),  # no rule set: no deadline, one cause; the SAE case
            ("visits_overdue", "/studies/GZQO/visits"),
            ("visits_today", "/studies/GZQO/visits"),
            ("site", "/studies/GZQO/feasibility#site"),  # a task now, no longer the study's Next (R8)
            ("delegation", "/studies/GZQO/team#check"),  # the monthly comparison, due today
        ], lang
        body = _region(page)
        assert 'data-testid="sae-banner"' not in body and 'data-testid="sae-reports"' not in body
        assert (
            body.count(f'data-what="GZQO/{no}/ae1"') == 1 and body.count(f'href="/studies/GZQO/sae/{no}/ae1"') == 1
        ), lang
        assert 'data-testid="tasks"' not in body and 'data-testid="clinic"' not in body
        assert 'data-testid="home-visits"' not in body
        assert _next(page) == ("conduct", "")  # its page is already a line above: linked once
        assert 'data-testid="today-more"' not in page
        pg = pi.get("/home").text
        kinds = [k for k, _ in _lines(pg)]
        assert kinds[0] == "sae_ack" and kinds.count("sae_ack") == 1 and "sae_noclock" not in kinds, lang
        assert pg.count(f'data-what="GZQO/{no}/ae1"') == 1
        for _k, href in _lines(page) + _lines(pg):
            assert crc.get(href).status_code == 200 or pi.get(href).status_code == 200, href
    for _k, href in _lines(pi.get("/home").text):
        assert pi.get(href).status_code == 200, href  # each of the investigator's lines opens for the investigator


def test_never_more_than_five_lines_and_the_whole_list_beyond(lb: dict[str, Any]) -> None:
    crc, pi, _no = _participant_with_saes(lb, 6)
    _flag(lb, "on")
    page = pi.get("/home").text
    lines = _lines(page)
    assert len(lines) == 5 and all(k == "sae_ack" for k, _ in lines)  # safety first
    whole = pi.get("/home?today=all").text
    every = _lines(whole)
    assert [k for k, _ in every].count("sae_ack") == 6 and len(every) > 6  # the six events, then the visits
    more = re.search(r'href="/home\?today=all" data-testid="today-more">([^<]+)<', page)
    assert more and more.group(1) == f"{len(every) - 5} more: see the whole list"
    assert 'data-testid="today-more"' not in whole and 'data-testid="today-back"' in whole
    whats = re.findall(r'data-what="([^"]+)"', whole)
    assert len(whats) == len(set(whats))  # each thing once
    crc_page = crc.get("/home").text
    assert len(_lines(crc_page)) == 5 and 'data-testid="today-more"' in crc_page


def test_nothing_today_is_said_plainly_and_an_aggregate_account_reads_no_patient_row(lb: dict[str, Any]) -> None:
    from tests.console.test_console_app import _done_feas, _done_screen, _ulid

    _done_feas(lb["backend"])
    _done_screen(lb["backend"], _ulid(1226))
    _flag(lb, "on")
    reads: list[str] = []
    real = lb["backend"].registry_rows

    def counted(rs: str) -> Any:
        reads.append(rs)
        return real(rs)

    lb["backend"].registry_rows = counted
    for lang, words in (("en", "Nothing needs you today."), ("ja", "今日対応が必要なものはありません。"),
                        ("zh-TW", "今天沒有需要你處理的事。")):  # fmt: skip
        v, _ = login(lb["app"], "viewer", VIEWER_PW)
        _lang(v, lang)
        page = v.get("/home").text
        assert words in page and _lines(page) == [] and 'data-testid="today-none"' in page
        assert "a" * 8 not in page and "b" * 8 not in page  # no pseudonym
    assert reads == []  # the viewer's home asked for no screening-log row


# ------------------------------------------------------------------------------------------- the role walk, flag on
def test_the_role_walk_with_the_flag_on_answers_every_route_as_its_row(box: dict[str, Any], tmp_path: Path) -> None:
    """The walk of card V-2 with ``layout.home_today`` on: every route still answers every column as its declared
    row, and no role without patient rows sees a seeded pseudonym (the opening page included)."""
    from tests.console import test_matrix_role_walk as mw
    from tools import role_walk as rw

    _flag(box, "on")
    rows = rw.judge_declared(mw.run_walk(box, tmp_path), rw.load_declared())
    assert phone.home_today_now()  # still on at the end of the walk
    mw.test_every_console_route_answers_every_column_as_its_declared_row(rows)


# ------------------------------------------------------------------------------------------- what the home reads
def _count_reads(b: dict[str, Any]) -> list[str]:
    """Every call the console makes to the data core (participants, visits, serious AEs) and every screening-log read,
    by path: the reads a page makes for patient-level rows."""
    calls: list[str] = []
    api, rows = b["backend"].study_api, b["backend"].registry_rows

    def study_api(method: str, path: str, *a: Any, **kw: Any) -> Any:
        calls.append(f"{method} {path}")
        return api(method, path, *a, **kw)

    def registry_rows(rs: str, *a: Any, **kw: Any) -> Any:
        calls.append(f"registry {rs}")
        return rows(rs, *a, **kw)

    b["backend"].study_api, b["backend"].registry_rows = study_api, registry_rows
    return calls


def test_a_refused_investigator_s_home_reads_no_patient_level_row(lb: dict[str, Any]) -> None:
    """The review of D-1225 (blocker): an investigator the study's log does not name, and a sub-investigator ticked
    for nothing that opens the participant pages, make no read of the study's participants, visits, serious AEs or
    screening log on the opening page, with the flag on as with it off; the participant page refuses them (403)."""
    from tests.console.test_console_app import name_pi, sub_investigator

    _participant_with_saes(lb, 1)  # a study with participants, visits and a serious AE; its PI is "pi"
    lb["users"].create("other", "investigator", PW, "other@hospa.test")  # on no log
    lb["users"].create("refer", "investigator", PW, "refer@hospa.test")
    sub_investigator(lb, "refer", tasks=("refer",))  # ticked, but for nothing that reads participants
    name_pi(lb, "pi")
    for flag in ("off", "on"):
        if flag == "on":
            _flag(lb, "on")
        for who in ("other", "refer"):
            c, _ = login(lb["app"], who, PW)
            assert c.get("/studies/GZQO/subjects").status_code == 403  # the participant pages refuse them
            calls = _count_reads(lb)
            page = c.get("/home", follow_redirects=False)  # off: sent on to /week, as on master
            assert page.status_code == (200 if flag == "on" else 303), (flag, who)
            assert calls == [], (flag, who, calls)
            if flag == "on":
                assert _next(page.text) in (("report", "/studies/GZQO/feasibility"), ("report_none", ""))
                assert _lines(page.text) == []
    # the PI of GZQO reads GZQO (so the counter does see reads), and nothing of a second study whose log names no one
    from console.backend import RulesetInfo

    real = lb["backend"].rulesets
    lb["backend"].rulesets = lambda: [*real(), RulesetInfo("OTHER1", "1.0.0", "approved", "trial")]
    pi, _ = login(lb["app"], "pi", PW)
    assert pi.get("/studies/OTHER1/subjects").status_code in (403, 404)
    calls = _count_reads(lb)
    page = pi.get("/home").text
    assert any(c.startswith("GET /studies/GZQO/") for c in calls), calls
    assert not [c for c in calls if "OTHER1" in c], calls
    assert _next(page, "OTHER1")[0] in ("report", "report_none")


def test_a_sub_investigator_ticked_for_data_entry_gets_the_participant_pages_lines(lb: dict[str, Any]) -> None:
    """The review of D-1225: the home uses the participant pages' own rule (screen or enter_data) for the participants
    and the visits, and the SAE pages' own rule (screen) for the serious AEs: a sub-investigator ticked for data entry
    gets the visit lines and the study's Next, and no serious AE, which the SAE pages do not show them."""
    from tests.console.test_console_app import sub_investigator

    _crc, _pi, _no = _participant_with_saes(lb, 1)
    lb["users"].create("entry", "investigator", PW, "entry@hospa.test")
    sub_investigator(lb, "entry", tasks=("enter_data",))
    _flag(lb, "on")
    c, _ = login(lb["app"], "entry", PW)
    assert c.get("/studies/GZQO/subjects").status_code == 200 and c.get("/studies/GZQO/visits").status_code == 200
    page = c.get("/home").text
    kinds = [k for k, _ in _lines(page)]
    assert "visits_overdue" in kinds and "visits_today" in kinds, kinds
    assert not any(k.startswith("sae_") for k in kinds), kinds
    assert c.get(f"/studies/GZQO/sae/{_no}/ae1").status_code == 403  # the SAE pages refuse this account
    assert _next(page)[0] == "conduct"
    for _k, href in _lines(page):
        assert c.get(href).status_code == 200, href


def test_without_sae_view_no_serious_adverse_event_is_read_into_a_line(lb: dict[str, Any], monkeypatch: Any) -> None:
    """The ``sae.view`` row decides the safety lines, through the SAE pages' own rule: refused (a matrix change), the
    block keeps the visits, shows no serious AE and reads none."""
    _participant_with_saes(lb, 1)
    _flag(lb, "on")
    crc, _ = login(lb["app"], "crc", PW)
    assert any(k.startswith("sae_") for k, _ in _lines(crc.get("/home").text))
    from console import sae_pages
    from tb_common.authz import sae_allowed as real

    monkeypatch.setattr(sae_pages, "sae_allowed", lambda role, action: action != "view" and real(role, action))
    assert crc.get("/sae").status_code == 403  # the SAE pages refuse it too: one rule
    calls = _count_reads(lb)
    kinds = [k for k, _ in _lines(crc.get("/home").text)]
    assert not any(k.startswith("sae_") for k in kinds) and "visits_today" in kinds, kinds
    assert not any("/aes" in x for x in calls), calls  # not read either


def test_today_is_the_site_s_day_not_utc_s(lb: dict[str, Any]) -> None:
    """The site is ahead of UTC (tests run in Asia/Taipei, UTC+8): at 20:00 UTC it is already tomorrow there, and
    what is due on the site's day is today's line; with the UTC date it would wait a day."""
    _participant_with_saes(lb, 1)
    lb["clock"]["now"] = datetime(2026, 11, 9, 20, 0, tzinfo=UTC)  # 2026-11-10 04:00 at the site
    _flag(lb, "on")
    crc, _ = login(lb["app"], "crc", PW)
    page = crc.get("/home?today=all").text
    dated = re.findall(r'data-testid="today-(site|delegation)"[^>]*>.*?<span class="due">([^<]+)<', page, re.S)
    assert dated and all(d == "due 2026-11-10" for _k, d in dated), dated


# ------------------------------------------------------------------------------------------- flag off: as master
def test_with_the_flag_off_the_home_is_byte_for_byte_the_page_without_this_card(lb: dict[str, Any],
                                                                               monkeypatch: Any) -> None:  # fmt: skip
    """Every J-6 part of ``home_crc.html`` sits between ``{#J6#}`` and ``{#/J6#}``. With the flag off the page is the
    same, byte for byte, as the page from the template with those parts taken out (the template as it was before),
    for each role whose home it is, in three languages."""
    import jinja2

    form = ["with"]
    real = jinja2.FileSystemLoader.get_source

    def source(self: Any, env: Any, name: str) -> Any:
        text, path, _uptodate = real(self, env, name)
        if name == "home_crc.html" and form[0] == "without":
            text = re.sub(r"\{#J6#\}.*?\{#/J6#\}", "", text, flags=re.S)
        return text, path, lambda: False  # never kept: each render reads the form asked for

    monkeypatch.setattr(jinja2.FileSystemLoader, "get_source", source)  # before any page is rendered
    _participant_with_saes(lb, 1)
    pages: dict[str, list[str]] = {"with": [], "without": []}
    for f in ("with", "without"):
        form[0] = f
        for lang in LANGS:
            crc, _ = login(lb["app"], "crc", PW)
            _lang(crc, lang)
            pages[f].append(re.sub(r'name="csrf" value="[^"]+"', "", crc.get("/home").text))
    assert all('data-testid="study-GZQO"' in p for p in pages["with"])  # the cards are rendered
    assert pages["with"] == pages["without"]
    assert "{#J6#}" in (Path(__file__).parents[2] / "services/console/templates/home_crc.html").read_text("utf-8")


# ------------------------------------------------------------------------------------------- a statement budget
def _statements(monkeypatch: Any) -> list[str]:
    import psycopg

    seen: list[str] = []
    real = psycopg.Cursor.execute

    def execute(self: Any, query: Any, *a: Any, **kw: Any) -> Any:
        seen.append(str(query)[:60])
        return real(self, query, *a, **kw)

    monkeypatch.setattr(psycopg.Cursor, "execute", execute)
    return seen


def test_the_flag_adds_a_bounded_number_of_statements_per_study(lb: dict[str, Any], monkeypatch: Any) -> None:
    """The review of D-1225 (12 extra statements a study): the account's standing is read once per page view and
    study, and only the shown step's row is asked. With the flag on, each more study costs at most 3 statements more
    than it costs with the flag off (its state; its log, once)."""
    from console.backend import RulesetInfo

    _participant_with_saes(lb, 1)
    crc, _ = login(lb["app"], "crc", PW)
    real = lb["backend"].rulesets

    def count(n: int) -> int:
        extra = [RulesetInfo(f"S{i:02d}", "1.0.0", "approved", "trial") for i in range(n)]
        monkeypatch.setattr(lb["backend"], "rulesets", lambda: [*real(), *extra])
        seen = _statements(monkeypatch)
        assert crc.get("/home").status_code == 200
        return len(seen)

    off = {n: count(n) for n in (0, 8)}
    _flag(lb, "on")
    on = {n: count(n) for n in (0, 8)}
    per_study_off, per_study_on = (off[8] - off[0]) / 8, (on[8] - on[0]) / 8
    assert per_study_on <= per_study_off + 3, (off, on)


def test_what_is_read_is_shown_a_screening_sub_investigator_reads_no_visit(lb: dict[str, Any]) -> None:
    """Nothing is read that the page does not show: a sub-investigator ticked for screening only reads the study's
    participants and serious AEs (both on the page) but not its visits, whose lines are the data-entry task's."""
    from tests.console.test_console_app import sub_investigator

    _participant_with_saes(lb, 1)
    lb["users"].create("screener", "investigator", PW, "screener@hospa.test")
    sub_investigator(lb, "screener", tasks=("screen",))
    _flag(lb, "on")
    c, _ = login(lb["app"], "screener", PW)
    calls = _count_reads(lb)
    page = c.get("/home").text
    assert [k for k, _ in _lines(page)] == ["sae_ack"]
    assert any("/aes" in x for x in calls) and not any("/visits" in x for x in calls), calls


# ------------------------------------------------------------------------------------------- every read, its page
def test_every_read_of_the_home_is_one_the_account_s_own_page_allows(lb: dict[str, Any]) -> None:
    """The review of D-1225 (second round): for each account, every patient-level read the opening page makes is one
    that account's own page of that source allows. A study's serious AEs (``/aes``) are checked against the SAE case
    page, separately from its participants, visits and screening log (``/subjects``, ``/visits``, the registry),
    checked against the participant page. And a study's ``/aes`` and ``/subjects`` are each read once."""
    from tests.console.test_console_app import sub_investigator

    _crc, _pi, no = _participant_with_saes(lb, 1)
    for name, tasks in (("entry", ("enter_data",)), ("screener", ("screen",)), ("refer", ("refer",))):
        lb["users"].create(name, "investigator", PW, f"{name}@hospa.test")
        sub_investigator(lb, name, tasks=tasks)
    lb["users"].create("other", "investigator", PW, "other@hospa.test")
    _flag(lb, "on")
    accounts = [("crc", PW), ("pi", PW), ("entry", PW), ("screener", PW), ("refer", PW), ("other", PW),
                ("viewer", VIEWER_PW)]  # fmt: skip
    seen_sae, seen_people = set(), set()
    for who, pw in accounts:
        c, _ = login(lb["app"], who, pw)
        calls = _count_reads(lb)
        assert c.get("/home").status_code == 200, who
        made = list(calls)
        for call in made:
            rs = call.split("/studies/", 1)[1].split("/", 1)[0] if "/studies/" in call else call.split()[-1]
            if "/aes" in call:
                seen_sae.add(who)
                assert c.get(f"/studies/{rs}/sae/{no}/ae1").status_code == 200, (who, call)
            else:
                seen_people.add(who)
                assert c.get(f"/studies/{rs}/subjects").status_code == 200, (who, call)
        for kind in ("/aes", "/subjects"):
            assert sum(1 for x in made if kind in x and "GZQO" in x) <= 1, (who, kind, made)
    assert seen_sae == {"crc", "pi", "screener"} and seen_people == {"crc", "pi", "entry", "screener"}


def test_a_closed_study_has_no_visit_task_or_site_line_and_keeps_its_safety_lines(lb: dict[str, Any]) -> None:
    """A closed study has no visits, tasks or site fields to do: none on the home, and its visits are not read; its
    serious AEs keep their reporting clocks, so their lines stay."""
    _participant_with_saes(lb, 1)
    h = lb["app"].state.helpers
    _flag(lb, "on")
    crc, _ = login(lb["app"], "crc", PW)
    before = {k for k, _ in _lines(crc.get("/home?today=all").text)}
    assert {"visits_overdue", "site", "delegation"} <= before, before
    h.store.set_study_state("GZQO", "closed", "J-6 test", "crc", "2026-11-09T02:00:00+00:00")
    calls = _count_reads(lb)
    page = crc.get("/home?today=all").text
    kinds = {k for k, _ in _lines(page)}
    assert kinds == {"sae_noclock"}, kinds
    assert not any("/visits" in x for x in calls), calls
    assert _next(page)[0] == "closed"


def test_no_link_of_the_home_opens_a_refusal_for_any_kind_of_account(lb: dict[str, Any]) -> None:
    """Every link in the opening page's content, for every kind of account the page serves (the coordinator, the PI,
    sub-investigators ticked for screening, for data entry or for referral only, an investigator on no log, the
    viewer, a CRO with and without a monitor grant), opens: no 403 and no 404 (the lead's check of D-1225)."""
    from tests.console.test_console_app import sub_investigator

    _participant_with_saes(lb, 1)
    for name, tasks in (("entry", ("enter_data",)), ("screener", ("screen",)), ("refer", ("refer",))):
        lb["users"].create(name, "investigator", PW, f"{name}@hospa.test")
        sub_investigator(lb, name, tasks=tasks)
    lb["users"].create("other", "investigator", PW, "other@hospa.test")
    for mon in ("mon1", "mon2"):
        lb["users"].create(mon, "cro", PW, f"{mon}@cro.test")
        lb["users"].set_scope(mon, affiliation="cro", studies="GZQO")
    pi, pcsrf = login(lb["app"], "pi", PW)
    r = pi.post("/studies/GZQO/team", data={"csrf": pcsrf, "username": "mon1", "role": "monitor", "start": "2026-01-01",
                                           "end": "2099-12-31", "training_ref": "MV-0001"}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303
    _flag(lb, "on")
    accounts = [("crc", PW), ("pi", PW), ("entry", PW), ("screener", PW), ("refer", PW), ("other", PW),
                ("viewer", VIEWER_PW), ("mon1", PW), ("mon2", PW)]  # fmt: skip
    for who, pw in accounts:
        c, _ = login(lb["app"], who, pw)
        page = c.get("/home")
        assert page.status_code == 200, who
        hrefs = sorted(set(re.findall(r'<a [^>]*href="(/[^"#]*)', _region(page.text))))
        assert hrefs, who
        for href in hrefs:
            got = c.get(html.unescape(href))
            assert got.status_code < 400, (who, href, got.status_code)


def test_an_aggregate_account_s_home_reads_only_what_its_reports_page_reads(lb: dict[str, Any],
                                                                           monkeypatch: Any) -> None:  # fmt: skip
    """The viewer's and the CRO's opening page (flag on) make no read their own pages refuse: not the models' state
    (shown on no page of theirs), no patient-level read; the one job-list read is the one their reports page makes,
    for the same fact (whether the study's feasibility report is there)."""
    from tests.console.test_console_app import _done_feas

    _done_feas(lb["backend"])
    lb["users"].create("mon2", "cro", PW, "mon2@cro.test")
    lb["users"].set_scope("mon2", affiliation="cro", studies="GZQO")
    _flag(lb, "on")
    for who, pw in (("viewer", VIEWER_PW), ("mon2", PW)):
        c, _ = login(lb["app"], who, pw)
        made: list[str] = []

        def spy(name: str, real: Any, made: list[str] = made) -> Any:
            def call(*a: Any, **kw: Any) -> Any:
                made.append(name)
                return real(*a, **kw)

            return call

        for name in ("models", "list_jobs", "registry_rows", "study_api"):
            monkeypatch.setattr(lb["backend"], name, spy(name, getattr(lb["backend"], name)))
        assert c.get("/home").status_code == 200
        home = list(made)
        made.clear()
        assert c.get("/reports").status_code == 200
        assert home == ["list_jobs"], (who, home)
        assert "list_jobs" in made, (who, made)  # the reports page makes the same read
        assert c.get("/jobs").status_code == 403  # the job list itself is not theirs
        monkeypatch.undo()
