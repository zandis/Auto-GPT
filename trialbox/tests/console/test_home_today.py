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
from console import i18n_flags, i18n_today
from console.i18n import CATALOGUES
from fastapi.testclient import TestClient
from tb_common import flags as fl

from tests.console.test_console_app import VIEWER_PW, box, login  # noqa: F401
from tests.console.test_lifecycle_pages import PW, _save, lb  # noqa: F401

LANGS = ("en", "ja", "zh-TW")


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    fl.clear_cache()
    ht.clear_cache()
    yield
    fl.clear_cache()
    ht.clear_cache()


def _flag(b: dict[str, Any], value: str) -> None:
    """The administrator's change on /ops/flags: audited, with a reason."""
    fl.Flags(audit=b["audit"]).set(ht.FLAG, value, actor="console:admin", reason="J-6 test (D-1225)")
    fl.clear_cache()
    ht.clear_cache()
    ht.flag_on()  # read now: a page gets the value last read


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
    assert fl.Flags().row(ht.FLAG) == "off" and not ht.flag_on()  # seeded off at create_app
    for cat in (i18n_flags.EN, i18n_flags.JA, i18n_flags.ZH):
        assert cat[f"flags.desc.{ht.FLAG}"]


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
        ("call", "p2"),
        ("visits_overdue", "overdue"),
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
    for to in ("on_study", "completed"):  # the last participant ends the study; nobody else is in the pipeline
        r = crc.post(f"/studies/GZQO/subjects/{no_a}/step", data={"csrf": csrf, "to": to, "on_day": "2026-11-07",
                                                                  "confirm": "yes"})  # fmt: skip
        assert f'data-state="{to}"' in r.text, r.text[-500:]
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
            ("sae_noclock", f"/studies/GZQO/subjects/{no}"),  # no rule set: no deadline, one cause
            ("visits_overdue", "/studies/GZQO/visits"),
            ("visits_today", "/studies/GZQO/visits"),
            ("site", "/studies/GZQO/feasibility#site"),  # a task now, no longer the study's Next (R8)
            ("delegation", "/studies/GZQO/team#check"),  # the monthly comparison, due today
        ], lang
        body = _region(page)
        assert 'data-testid="sae-banner"' not in body and 'data-testid="sae-reports"' not in body
        assert (
            body.count(f'data-what="GZQO/{no}/ae1"') == 1 and body.count(f'href="/studies/GZQO/subjects/{no}"') == 1
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
    assert ht.flag_now()  # still on at the end of the walk
    mw.test_every_console_route_answers_every_column_as_its_declared_row(rows)
