# ruff: noqa: F811 - the box fixture is imported from test_console_app and taken by name
"""J-5 (D-1223; the journey review's R16 and D-2): two lists of people, Candidates and Participants, behind the flag
``layout.people_lists``.

* the flag is declared, off by default and described in three languages; the strings of the lists are in three
  languages;
* with it off the old lists, their addresses and the menu are as before, and a new address sends to the old page;
* with it on every old address sends (303) to its view with its query kept, and the view is the old page: for every
  role of the role matrix and every old list, the same answer, the same page body (every form, link and filter: the
  old list's actions) and no extra refusal in the audit trail; the strip offers a view exactly where the role's
  answer is the page; and from the list's first page each view is one step, so each old action is at most two;
* the menu shows Candidates and Participants where it showed the week list and the candidate registry; the picker;
* the view Participants filters by the one state (the withdrawals);
* the strip's words in en, ja and zh-TW.

Synthetic data only (the test box's study GZQO)."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from console import i18n_flags, i18n_lists, people_lists, phone
from console.i18n import CATALOGUES
from fastapi.testclient import TestClient
from tb_common import flags as fl

from tests.console.test_console_app import _done_feas, _done_screen, _ulid, box, login  # noqa: F401
from tests.console.test_role_route_matrix import _clients

LANGS = ("en", "ja", "zh-TW")
RS = "GZQO"
#: the old lists of one study (address with its query) and the view each becomes
OLD: dict[str, str] = {
    f"/studies/{RS}/week": f"/studies/{RS}/people/candidates",
    f"/studies/{RS}/cohort": f"/studies/{RS}/people/candidates/cohort",
    f"/studies/{RS}/candidates": f"/studies/{RS}/people/candidates/referrals",
    f"/pilot/registry/{RS}": f"/studies/{RS}/people/candidates/registry",
    f"/studies/{RS}/screening-log": f"/studies/{RS}/people/candidates/log",
    f"/studies/{RS}/subjects": f"/studies/{RS}/people/participants",
    f"/studies/{RS}/enrolment": f"/studies/{RS}/people/participants/enrolment",
}
KEY_OF = {v.old_path(RS): v.key for v in people_lists.VIEWS}


@pytest.fixture(autouse=True)
def _fresh_cache() -> Any:
    fl.clear_cache()
    people_lists.clear_cache()
    phone.clear_cache()
    yield
    fl.clear_cache()
    people_lists.clear_cache()
    phone.clear_cache()


def _flag(b: dict[str, Any], value: str) -> None:
    """The administrator's change on /ops/flags: audited, with a reason."""
    fl.Flags(audit=b["audit"]).set(people_lists.FLAG, value, actor="console:admin", reason="J-5 test (D-1223)")
    fl.clear_cache()
    people_lists.clear_cache()
    people_lists.flag_on()  # read now: a page gets the value last read


def _events(b: dict[str, Any], name: str) -> list[dict[str, Any]]:
    out = []
    for f in sorted(b["backend"].audit_dir.glob("*.jsonl")):
        out += [json.loads(x) for x in f.read_text().splitlines() if x and json.loads(x).get("event") == name]
    return out


def _main(page: str) -> str:
    """The page's body without the strip: what the old page showed, its forms, links and filters."""
    body = page.split('<main id="main">', 1)[1].split("</main>", 1)[0]
    return re.sub(r"\n\s*\n", "\n", re.sub(r'<nav class="ptabs".*?</nav>', "", body, flags=re.S))


def _box(b: dict[str, Any]) -> dict[str, tuple[TestClient, str, TestClient]]:
    _done_feas(b["backend"])
    _done_screen(b["backend"], _ulid(990))
    return _clients(b)


def _lang(c: TestClient, csrf: str, lang: str) -> None:
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})


# ------------------------------------------------------------------------------------------- the flag and the words
def test_the_flag_is_declared_off_and_described_in_three_languages(box: dict[str, Any]) -> None:
    d = fl.DECLARED[people_lists.FLAG]
    assert d.default == "off" and d.values == ("off", "on") and d.seed_env is None
    assert fl.Flags().row(people_lists.FLAG) == "off" and not people_lists.flag_on()  # seeded off at create_app
    for cat in (i18n_flags.EN, i18n_flags.JA, i18n_flags.ZH):
        assert cat[f"flags.desc.{people_lists.FLAG}"]
    assert set(i18n_lists.EN) == set(i18n_lists.JA) == set(i18n_lists.ZH)
    for lang in LANGS:
        assert all(CATALOGUES[lang][k] for k in i18n_lists.EN)
    for v in people_lists.VIEWS:  # every view has its tab's words
        assert f"people.view.{v.key}" in i18n_lists.EN


def test_the_flag_is_switched_on_the_flags_page_with_a_reason_and_audited(box: dict[str, Any]) -> None:
    admin, _ = login(box["app"])
    csrf = re.search(r'name="csrf" value="([^"]+)"', admin.get("/ops/flags").text)
    assert csrf
    form = {"csrf": csrf.group(1), "name": people_lists.FLAG, "value": "on", "reason": "J-5 test: the walk held",
            "confirm": "yes", "old": "off"}  # fmt: skip
    r = admin.post("/ops/flags", data=form, follow_redirects=False)
    assert r.status_code == 303
    (ev,) = [e for e in _events(box, "flag.set") if e["detail"]["flag"] == people_lists.FLAG]
    assert ev["actor"] == "console:admin" and ev["detail"]["reason"] == "J-5 test: the walk held"
    assert people_lists.flag_on()


# ------------------------------------------------------------------------------------------- flag off: as before
def test_with_the_flag_off_the_old_lists_and_the_menu_are_as_before(box: dict[str, Any]) -> None:
    clients = _box(box)
    crc, _, _ = clients["crc"]
    for old in OLD:
        r = crc.get(old, follow_redirects=False)
        assert r.status_code in (200, 303), old
        if r.status_code == 200:
            assert 'data-testid="people-tabs"' not in r.text, old
    page = crc.get(f"/studies/{RS}/week").text
    assert 'href="/week"' in page and 'href="/pilot/registry"' in page and "/people/" not in page
    assert 'data-testid="more-candidates"' in page
    # a new address kept from elsewhere opens the old page, query kept
    for old, new in OLD.items():
        r = crc.get(new + "?list=all", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == old + "?list=all", new
    assert crc.get("/people/candidates", follow_redirects=False).headers["location"] == "/week"
    # the participants' filter is the view's: the old page ignores it
    assert 'data-testid="state-filter"' not in crc.get(f"/studies/{RS}/subjects?state=withdrawn").text


# ------------------------------------------------------------------------------------------- flag on: redirects
def test_with_the_flag_on_every_old_address_sends_to_its_view_with_its_query(box: dict[str, Any]) -> None:
    clients = _box(box)
    crc, _, _ = clients["crc"]
    _flag(box, "on")
    for old, new in OLD.items():
        r = crc.get(old + "?list=approached&page=2", follow_redirects=False)
        assert r.status_code == 303, old
        assert r.headers["location"] == new + "?list=approached&page=2", old
    # files, actions and other pages keep their addresses
    for path in (f"/studies/{RS}/screening-log.xlsx", f"/pilot/registry/{RS}/export.xlsx", "/pilot/registry",
                 f"/studies/{RS}/subjects/R1", f"/studies/{RS}/enrolment.csv", "/site/patients"):  # fmt: skip
        r = crc.get(path, follow_redirects=False)
        assert not (r.status_code == 303 and "/people/" in r.headers.get("location", "")), path
    # a form posts where it posted before: no redirect of a POST
    assert crc.post(f"/pilot/registry/{RS}", data={}, follow_redirects=False).status_code != 303
    # an unknown view is not a page
    assert crc.get(f"/studies/{RS}/people/candidates/nothing", follow_redirects=False).status_code == 404


def test_a_relative_filter_link_stays_in_its_view(box: dict[str, Any]) -> None:
    """The weekly page's and the referrals' filters are relative links (``?list=``, ``?show=``): the view is in the
    path, so a filter keeps the view."""
    clients = _box(box)
    crc, _, _ = clients["crc"]
    _flag(box, "on")
    week = crc.get(f"/studies/{RS}/people/candidates?list=all")
    assert week.status_code == 200 and 'href="?list=approached"' in week.text
    ref = crc.get(f"/studies/{RS}/people/candidates/referrals?show=unknown")
    assert ref.status_code == 200 and 'data-testid="people-view-referrals"' in ref.text
    assert 'aria-current="true" class="on">' in ref.text.split('data-testid="people-view-referrals"', 1)[1][:40]


# ------------------------------------------------------------------------------------------- the role walk
def test_every_role_gets_the_same_answer_and_the_same_actions_and_two_steps_at_most(box: dict[str, Any]) -> None:
    """For every role of the role matrix and every old list: the flag off answer of the old address, then with the flag
    on the answer of its view. The same status; for a page the same body (the old list's forms, links and filters:
    every action it offered); the strip offers the view exactly when the role gets the page; and the list's first
    page, reached from the menu, links every view the role gets: one step to the view, the action the second."""
    clients = _box(box)
    denied_before = len(_events(box, "console.denied"))
    off: dict[tuple[str, str], tuple[int, str]] = {}
    for col, (page, _, _) in clients.items():
        for old in OLD:
            r = page.get(old, follow_redirects=False)
            off[(col, old)] = (r.status_code, _main(r.text) if r.status_code == 200 else "")
    denied_off = len(_events(box, "console.denied")) - denied_before
    _flag(box, "on")
    reached: dict[str, set[str]] = {}
    for col, (page, _, _) in clients.items():
        for old, new in OLD.items():
            status, body = off[(col, old)]
            r = page.get(new, follow_redirects=False)
            if status == 303:  # the weekly page of a registry study sends to its cohort (not GZQO), and so on
                assert r.status_code == 303, (col, old)
                continue
            assert r.status_code == status, (col, old, status, r.status_code)
            if status == 200:
                assert _main(r.text) == body, (col, old)  # every form, link and filter of the old list, unchanged
                assert 'data-testid="people-tabs"' in r.text, (col, old)
                reached.setdefault(col, set()).add(KEY_OF[old])
    # the same refusals: the strip and the redirects ask no question that is refused and audited
    assert len(_events(box, "console.denied")) - denied_before == 2 * denied_off
    for col, (page, _, _) in clients.items():
        got = reached.get(col, set())
        for lst in people_lists.LISTS:
            # the cohort list of a trial study (GZQO) was linked from nowhere: its address opens it, no tab offers it
            want = {v.key for v in people_lists.VIEWS if v.list == lst} & got - {"cohort"}
            first = page.get(f"/people/{lst}", follow_redirects=True)
            if f'data-testid="people-pick-{RS}"' in first.text:  # several studies: the picker, then the study
                first = page.get(re.findall(rf'<a href="([^"]+)" data-testid="people-pick-{RS}"', first.text)[0])
            if not want:  # the role opens no view of this list: no study listed (a CRO account: its page rule's 403)
                assert first.status_code == 403 or 'data-testid="people-pick-none"' in first.text, (col, lst)
                continue
            assert first.status_code == 200 and 'data-testid="people-tabs"' in first.text, (col, lst)
            offered = set(re.findall(r'data-testid="people-view-([a-z]+)"', first.text))
            assert offered == want, (col, lst, offered, want)  # one step to each view the role gets, no other


def test_the_strip_names_the_other_list_only_where_the_role_opens_it(box: dict[str, Any]) -> None:
    clients = _box(box)
    _flag(box, "on")
    crc, _, _ = clients["crc"]
    page = crc.get(f"/studies/{RS}/people/candidates/log").text
    assert 'data-testid="people-list-candidates"' in page and 'data-testid="people-list-participants"' in page
    stw, _, _ = clients["steward"]  # the steward opens the registry's page (aggregate counts), no patient list
    page = stw.get(f"/studies/{RS}/people/candidates/registry").text
    assert 'data-testid="people-list-participants"' not in page
    assert re.findall(r'data-testid="people-view-([a-z]+)"', page) == ["registry"]


# ------------------------------------------------------------------------------------------- the menu and the picker
def test_the_menu_shows_the_two_lists_where_it_showed_the_old_ones(box: dict[str, Any]) -> None:
    clients = _box(box)
    _flag(box, "on")
    for col in ("crc", "lpi"):
        page, _, _ = clients[col]
        html = page.get("/reports").text
        nav = html.split('data-testid="nav"', 1)[1].split('data-testid="nav-more"', 1)[0]
        assert 'href="/people/candidates"' in nav and 'href="/people/participants"' in nav, col
        assert 'href="/week"' not in nav and 'href="/pilot/registry"' not in nav, col
    crc, _, _ = clients["crc"]
    html = crc.get(f"/studies/{RS}/people/candidates").text
    assert 'data-testid="more-people-candidates"' in html and 'data-testid="more-candidates"' not in html
    nav = html.split('data-testid="nav"', 1)[1].split('data-testid="nav-more"', 1)[0]
    assert re.search(r'<a href="/people/candidates" class="active">', nav)
    # the menu's link opens the study's list, or a choice of the studies that have it
    r = crc.get("/people/participants", follow_redirects=False)
    if r.status_code == 303:
        assert r.headers["location"] == f"/studies/{RS}/people/participants"
    else:
        assert f'data-testid="people-pick-{RS}" href' not in r.text  # the link carries the address first
        assert f'<a href="/studies/{RS}/people/participants" data-testid="people-pick-{RS}">' in r.text
    smo, _, _ = clients["smo"]  # an account scoped to one study: its list at once
    r = smo.get("/people/candidates", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/studies/{RS}/people/candidates"
    assert crc.get("/people/nobody", follow_redirects=False).status_code == 404
    viewer, _, _ = clients["viewer"]  # no list of people: the menu is as before, the picker names no study
    assert "/people/" not in viewer.get("/reports").text
    assert 'data-testid="people-pick-none"' in viewer.get("/people/candidates").text


# ------------------------------------------------------------------------------------------- Participants' filter
def test_the_participants_view_filters_by_the_one_state(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    clients = _box(box)
    _flag(box, "on")
    subjects = [
        {"record": "R1", "pid": "a" * 32, "since": "2026-10-01", "state": "withdrawn", "visits": {}},
        {"record": "R2", "pid": "b" * 32, "since": "2026-10-02", "state": "enrolled", "visits": {}},
    ]
    from console import s28

    real = s28.call

    def call(bk: Any, method: str, path: str, *a: Any, **k: Any) -> Any:
        if method == "GET" and path.startswith(f"/studies/{RS}/subjects?"):
            return {"subjects": [dict(s) for s in subjects]}
        return real(bk, method, path, *a, **k)

    monkeypatch.setattr(s28, "call", call)
    crc, _, _ = clients["crc"]
    page = crc.get(f"/studies/{RS}/people/participants").text
    assert 'data-testid="subject-R1"' in page and 'data-testid="subject-R2"' in page
    assert 'href="?state=withdrawn#subjects"' in page
    only = crc.get(f"/studies/{RS}/people/participants?state=withdrawn").text
    assert 'data-testid="subject-R1"' in only and 'data-testid="subject-R2"' not in only
    assert 'data-testid="state-filter"' in only and 'data-testid="count-enrolled"' in only  # counts stay whole
    assert 'data-testid="subject-R2"' in crc.get(f"/studies/{RS}/people/participants?state=nonsense").text


# ------------------------------------------------------------------------------------------- three languages
@pytest.mark.parametrize("lang", LANGS)
def test_the_strip_and_the_menu_in_each_language(box: dict[str, Any], lang: str) -> None:
    clients = _box(box)
    _flag(box, "on")
    crc, csrf, _ = clients["crc"]
    _lang(crc, csrf, lang)
    page = crc.get(f"/studies/{RS}/people/candidates/log").text
    cat = CATALOGUES[lang]
    for key in ("people.candidates", "people.participants", "people.view.log", "people.view.week",
                "people.view.registry", "people.view.referrals"):  # fmt: skip
        assert cat[key] in page, (lang, key)
    if lang != "en":
        assert ">Screening log<" not in page.split('data-testid="people-tabs"', 1)[1].split("</nav>", 1)[0]
