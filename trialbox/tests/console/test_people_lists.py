# ruff: noqa: F811 - the box fixture is imported from test_console_app and taken by name
"""J-5 (D-1223; the journey review's R16 and D-2): two lists of people, Candidates and Participants, behind the flag
``layout.people_lists``.

* the flag is declared, off by default, described in three languages and audited when it changes;
* with it off every page is byte for byte what the templates without J-5's additions render, the new addresses and
  the picker are no page (404, even with no session), and the old pages ignore the new filter;
* the two default views divide the study's people at consent by J-2's one state: each person is in exactly one
  (screen failure before consent, withdrawn and re-consented after it), nobody opted out or erased is in either,
  and a default shows nothing its old page did not show; a filter reads the one state, never the record's own step;
* with it on, an old address sends a reader its route lets in to its view (query kept) and gives anyone else the
  route's own answer; for every role of the role matrix and every old list: the same answer and the same refusals
  in the audit trail, the same page body on a working view and the same forms on a default, the strip only on a
  200 and offering exactly the views the role gets, each one step from the list's first page;
* the menu, the picker (which keeps the view asked for), the weekly page across studies one step from Candidates,
  the links from another site, and the words in en, ja and zh-TW.

Synthetic data only (the test box's study GZQO and J-2's three people of it)."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import jinja2
import pytest
from console import i18n_flags, i18n_lists, people_lists, phone
from console import person_state as ps
from console.i18n import CATALOGUES
from fastapi.testclient import TestClient
from tb_common import flags as fl

from tests.console.test_console_app import _done_feas, _done_screen, _ulid, box, login  # noqa: F401
from tests.console.test_lifecycle_pages import PW, lb  # noqa: F401 - the fixture is used by name
from tests.console.test_one_person_state import study  # noqa: F401 - the fixture is used by name
from tests.console.test_role_route_matrix import _clients

LANGS = ("en", "ja", "zh-TW")
RS = "GZQO"
REG, WEEK, SUBJ = f"/pilot/registry/{RS}", f"/studies/{RS}/week", f"/studies/{RS}/subjects"
CAND, PART = f"/studies/{RS}/people/candidates", f"/studies/{RS}/people/participants"
#: each view walked: (the old address whose route serves it, the view's address, its key)
WALK: tuple[tuple[str, str, str], ...] = (
    (REG, CAND, "before"),
    (WEEK, f"{CAND}/week", "week"),
    (f"/studies/{RS}/cohort", f"{CAND}/cohort", "cohort"),
    (f"/studies/{RS}/candidates", f"{CAND}/referrals", "referrals"),
    (f"/studies/{RS}/screening-log", f"{CAND}/log", "log"),
    (REG, f"{CAND}/everyone", "everyone"),
    (SUBJ, PART, "from"),
    (SUBJ, f"{PART}/records", "records"),
    (f"/studies/{RS}/enrolment", f"{PART}/enrolment", "enrolment"),
)
#: where each old address goes: the working view that is the old page as it was (a default is a new page)
OLD_TO = {old: new for old, new, key in WALK if key not in ("before", "from")}
DEFAULTS = ("before", "from")
#: the columns that read the study registry page's counts without patient rows (D-280, D-380)
AGGREGATE_REGISTRY = ("steward", "privacy")
#: the test ids a default view may add to its old page: the state filter only (a participant the log names first is
#: allowed where the log's own page admits the reader, and tested there: never through this list)
NEW_IDS = re.compile(r"^(state-filter|state-filter-all|state-only)$")


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch: pytest.MonkeyPatch) -> Any:
    # these tests set the flag in the store themselves: a run that forces the flag on reads the store here
    monkeypatch.setattr(people_lists, "flag_now", people_lists._flag.now)
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
    return re.sub(r'<nav class="ptabs".*?</nav>\n?', "", body, flags=re.S)


def _forms(body: str) -> list[str]:
    return sorted(re.findall(r"<form[^>]*>", body))


def _ids(body: str) -> set[str]:
    return set(re.findall(r'data-testid="([^"]+)"', body))


def _box(b: dict[str, Any]) -> dict[str, tuple[TestClient, str, TestClient]]:
    _done_feas(b["backend"])
    _done_screen(b["backend"], _ulid(990))
    return _clients(b)


def _lang(c: TestClient, csrf: str, lang: str) -> None:
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})


def _subjects(monkeypatch: pytest.MonkeyPatch, subjects: list[dict[str, Any]]) -> None:
    """The participant records the data core answers for GZQO (the test box has no study store)."""
    from console import s28

    real = s28.call

    def call(bk: Any, method: str, path: str, *a: Any, **k: Any) -> Any:
        if method == "GET" and path.startswith(f"/studies/{RS}/subjects?"):
            return {"subjects": [dict(s) for s in subjects]}
        return real(bk, method, path, *a, **k)

    monkeypatch.setattr(s28, "call", call)


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
    assert next(v.name for v in people_lists.VIEWS if v.list == "candidates") == ""  # each list starts on its default
    assert next(v.name for v in people_lists.VIEWS if v.list == "participants") == ""


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
#: J-5's additions in the templates, each with what the template held before (the flag-off output must not change)
_REDUCE: tuple[tuple[str, str], ...] = (
    (r"\{#\s*J-5 .*?#\}\n?", ""),  # its comments (a comment renders nothing)
    (r"\{% if pl %\}(?:(?!\{% else %\}).)*\{% else %\}(.*?)\{% endif %\}", r"\1"),
    (r"\{% if request is defined and request\.state is defined and request\.state\.people %\}.*?\{% endif -%\}\n", ""),
    (r"\{% set by_state = [^%]*%\}", ""),
    (r"\{% if by_state and only %\}.*?\{% endif %\}", ""),
    (r", 'count', by_state\)", ", 'count')"),
    (r"\{\{ '\?state=' ~ k ~ href if by_state else href \}\}", "{{ href }}"),
    (r", by_state=false\)", ")"),
    (r"\{% if s\.record %\}(.*?)\{% else %\}.*?\{% endif %\}", r"\1"),
    (r"s\.record or 'log-' ~ loop\.index", "s.record"),
    (r"'state-' \+ \(s\.record\)", "'state-' + s.record"),
)


def test_with_the_flag_off_every_page_is_byte_for_byte_as_without_j5(box: dict[str, Any]) -> None:
    """Each page is rendered twice with the flag off: with the console's templates, and with the same templates
    where every J-5 addition is put back to what the line held before. The two are the same, byte for byte."""
    clients = _box(box)
    env = box["app"].state.people_lists_env
    names = ("base.html", "_nav.html", "_person.html", "life_subjects.html")
    reduced = {}
    for name in names:
        src = env.loader.get_source(env, name)[0]
        for pattern, repl in _REDUCE:
            src = re.sub(pattern, repl, src, flags=re.S)
        assert "{% if pl %}" not in src and "by_state" not in src and "request.state.people %" not in src, name
        reduced[name] = src
    pages = ("/home", WEEK, REG, SUBJ, f"/studies/{RS}/screening-log", "/reports", "/pilot/registry", "/account")
    for col in ("crc", "lpi", "smo", "steward", "viewer"):  # (the administrator's home shows live figures)
        page, _, _ = clients[col]
        with_j5 = {p: page.get(p).text for p in pages}
        loader = env.loader
        try:
            env.loader = jinja2.ChoiceLoader([jinja2.DictLoader(reduced), loader])
            env.cache.clear()
            without = {p: page.get(p).text for p in pages}
        finally:
            env.loader = loader
            env.cache.clear()
        for p in pages:
            # the CSRF token, and the idle warning's live seconds (D-1370), differ from one rendering to the next
            a = re.sub(r'name="csrf" value="[^"]+"|data-(?:idle|abs)-left="\d+"', "", with_j5[p])
            b = re.sub(r'name="csrf" value="[^"]+"|data-(?:idle|abs)-left="\d+"', "", without[p])
            assert a == b, (col, p)
            assert 'data-testid="people-tabs"' not in a, (col, p)


def test_with_the_flag_off_the_new_addresses_are_no_page_and_the_old_ones_unchanged(
    box: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    clients = _box(box)
    crc, _, _ = clients["crc"]
    anon = TestClient(box["app"])
    for _, new, _k in WALK:
        for c in (crc, anon):  # no page, and no redirect before the session check
            r = c.get(new + "?list=all", follow_redirects=False)
            assert r.status_code == 404, (new, r.status_code)
    unknown = crc.get("/no-such-page/at-all", follow_redirects=False)  # what master's router answers
    for path in ("/people/candidates", "/people/participants", CAND, f"{PART}/records"):
        for c in (crc, anon):
            r = c.get(path, follow_redirects=False)
            assert r.status_code == 404 and r.content == unknown.content, (path, r.text[:80])
            assert r.headers["content-type"] == unknown.headers["content-type"], path
    # the route table the walks read is master's: the pickers are plain routes, not API routes
    from fastapi.routing import APIRoute

    assert not [
        r.path
        for r in box["app"].routes
        if isinstance(r, APIRoute) and re.match(r"^/(people|studies/[^/]+/people)/", r.path)
    ]
    page = crc.get(WEEK).text
    assert 'href="/week"' in page and 'href="/pilot/registry"' in page and "/people/" not in page
    assert 'data-testid="more-candidates"' in page
    # the participants' filter is a view's: the old page shows every row
    _subjects(monkeypatch, [
        {"record": "R1", "pid": "a" * 32, "since": "2026-10-01", "state": "withdrawn", "visits": {}},
        {"record": "R2", "pid": "b" * 32, "since": "2026-10-02", "state": "enrolled", "visits": {}},
    ])  # fmt: skip
    old = crc.get(f"{SUBJ}?state=withdrawn").text
    assert 'data-testid="subject-R1"' in old and 'data-testid="subject-R2"' in old
    assert 'data-testid="state-filter"' not in old


# ------------------------------------------------------------------------------------------- the division at consent
def _entry(pid: str, status: str) -> Any:
    return SimpleNamespace(pid=pid, status=status, updated_at=datetime(2026, 11, 1, 9, tzinfo=UTC), updated_by="crc")


def _log_row(rs: str, pid: str) -> Any:
    """A consented screening-log row as the orchestrator answers it (the contract the pages render)."""
    from tb_contracts import RegistryEntry

    return RegistryEntry(ruleset=rs, pid=pid, status="consented", reason=None, source="manual",
                         updated_at=datetime(2026, 11, 1, 9, tzinfo=UTC), updated_by="console:crc")  # fmt: skip


def test_the_two_defaults_divide_a_study_at_consent_by_the_one_state() -> None:
    """Every person is in exactly one default: a screen failure before consent and a record at its first step with
    the candidates; a withdrawal after consent and a re-consent with the participants; nobody opted out or erased."""
    a, b, c, d, e, g = ("a" * 32, "b" * 32, "c" * 32, "d" * 32, "e" * 32, "f" * 32)
    erased = "erased:2026-11-01:abcd"
    people = ps.gather(
        registry=[_entry(a, "candidate"), _entry(b, "screen_fail"), _entry(c, "contacted"), _entry(g, "consented"),
                  _entry(erased, "consented")],
        subjects=[
            {"pid": c, "record": "R3", "state": "withdrawn", "since": "2026-11-02", "changed_at": "2026-11-02T10:00"},
            {"pid": d, "record": "R4", "state": "withdrawn", "since": "2026-11-01", "changed_at": "2026-11-01T10:00"},
            {"pid": d, "record": "R5", "state": "consented", "since": "2026-11-03", "changed_at": "2026-11-03T10:00"},
            {"pid": e, "record": "R6", "state": "enrolled", "since": "2026-11-02", "changed_at": "2026-11-02T10:00"},
            {"pid": "", "record": "R9", "state": "candidate", "since": "2026-11-02", "changed_at": "2026-11-02T10:00"},
        ],
        gone={e},  # opted out (a kept trial record of an enrolled person)
        today=date(2026, 11, 5),
    )  # fmt: skip
    before, after = people_lists.side(people, "candidates"), people_lists.side(people, "participants")
    assert set(before) == {a, b, "#R9"} and set(after) == {c, d, g}
    assert not set(before) & set(after) and set(before) | set(after) == set(people.states())
    assert {s.name for s in before.values()} <= set(ps.CANDIDATE) and {s.name for s in after.values()} <= set(
        ps.PARTICIPANT)  # fmt: skip
    assert after[c].name == "withdrawn" and after[d].name == "consented" and before[b].name == "screen_fail"
    assert e not in before | after and erased not in before | after
    unread = ps.gather(registry=[_entry(a, "candidate")], readable=False)
    assert not people_lists.side(unread, "candidates") and not people_lists.side(unread, "participants")


def _registry_rows(page: str) -> dict[str, str]:
    """``pid -> state`` of the registry page's table."""
    return dict(re.findall(r'<tr data-pid="([^"]+)" id="p-[^"]+">\s*<td[^>]*>.*?</td>\s*<td><span class="pill '
                           r'ps-[a-z_]+" data-state="([a-z_]+)"', page, flags=re.S))  # fmt: skip


def _subject_states(page: str) -> list[str]:
    body = page.split('data-testid="subjects"', 1)[1]
    return re.findall(r'data-state="([a-z_]+)" data-testid="state-', body)


def test_on_the_box_each_person_is_on_one_default_and_a_default_shows_nothing_new(
    study: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """J-2's people of GZQO on the orchestrator's real data core: one consented, one waiting for information, one
    withdrawn after consent, the fixture's other numbered people, and an erased token added to the log. Flag off, the
    registry page lists every person once; flag on, Candidates' default lists those before consent and Participants'
    default those from consent on: together everyone once, the erased token nowhere, nothing either default shows that
    its old page did not."""
    real = study["reg"].rows

    def rows(rs: str) -> Any:
        return [*real(rs), _log_row(rs, "erased:2026-11-01:abcd")]

    study["backend"].registry_rows = rows
    crc, _ = login(study["app"], "crc", PW)
    old_registry = crc.get(REG).text
    everyone = _registry_rows(old_registry)
    old_subjects = crc.get(SUBJ).text
    assert everyone and not [p for p in everyone if p.startswith("erased:")]
    _flag(study, "on")
    cand_page = crc.get(CAND)
    part_page = crc.get(PART)
    assert cand_page.status_code == part_page.status_code == 200
    cand = _registry_rows(cand_page.text)
    part = _subject_states(part_page.text)
    assert set(cand.values()) <= set(ps.CANDIDATE) and set(part) <= set(ps.PARTICIPANT)
    assert cand == {p: s for p, s in everyone.items() if s in ps.CANDIDATE}  # nothing new, nobody missing
    assert sorted(part) == sorted(s for s in everyone.values() if s in ps.PARTICIPANT)  # the rest, once each
    assert "withdrawn" in part and "consented" in part and "need_info" in cand.values()
    assert "abcd" not in cand_page.text and "abcd" not in part_page.text
    # nothing a default shows that the old page did not (rows, columns, forms)
    assert _ids(_main(part_page.text)) - _ids(_main(old_subjects)) <= {i for i in _ids(_main(part_page.text))
                                                                       if NEW_IDS.match(i)}  # fmt: skip
    assert _forms(_main(cand_page.text)) == _forms(_main(old_registry))  # the add, the take-over, the export
    for lst, page in (("candidates", cand_page.text), ("participants", part_page.text)):
        assert 'data-testid="people-side"' in page and CATALOGUES["en"][f"people.side.{lst}"] in page


def test_a_participant_known_only_from_the_log_is_shown_only_to_whom_the_logs_page_admits(
    study: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """The screening log says consented and no participant record exists yet: Participants' default shows that
    person (state and day, no pseudonym) to the coordinator, whom the screening log's page admits. A sub-investigator
    ticked only for data entry is refused the log's page; with the flag on they get the participant records only: no
    log-only row, no count of it, and no read of the screening log beyond the one master's participants page makes
    for them (``person_state.read`` names each record's state from it, D-1221)."""
    from tests.console.test_console_app import sub_investigator

    real = study["reg"].rows
    log_only = "d" * 32

    def rows(rs: str) -> Any:
        return [*real(rs), _log_row(rs, log_only)]

    study["backend"].registry_rows = rows
    study["users"].create("subi", "investigator", PW, "subi@hospa.test")
    sub_investigator(study, "subi", tasks=("enter_data",))
    reads: list[str] = []
    real_read = ps.registry_rows

    def spy(h: Any, rs: str) -> Any:
        reads.append(rs)
        return real_read(h, rs)

    monkeypatch.setattr(ps, "registry_rows", spy)
    crc, _ = login(study["app"], "crc", PW)
    subi, _ = login(study["app"], "subi", PW)
    assert subi.get(f"/studies/{RS}/screening-log").status_code == 403  # the log's own page refuses them
    reads.clear()
    old = subi.get(SUBJ)
    assert old.status_code == 200
    master_reads = len(reads)
    _flag(study, "on")
    page = crc.get(PART).text
    assert re.search(r'data-testid="subject-log-\d+"', page) and 'data-testid="log-only"' in page
    assert log_only not in page and log_only[:8] not in page  # its state and day, never its pseudonym
    reads.clear()
    mine = subi.get(PART)
    assert mine.status_code == 200
    assert 'data-testid="subject-log-' not in mine.text and 'data-testid="log-only"' not in mine.text
    assert len(reads) == master_reads  # no read the old page did not make
    old_counts = dict(re.findall(r'data-testid="count-([a-z_]+)" data-state="[a-z_]+"><b>(\d+)</b>', old.text))
    new_counts = dict(re.findall(r'data-testid="count-([a-z_]+)" data-state="[a-z_]+"><b>(\d+)</b>', mine.text))
    assert all(int(n) <= int(old_counts.get(k, 0)) for k, n in new_counts.items()), (old_counts, new_counts)


def test_a_filter_reads_the_one_state_never_the_records_own_step(
    box: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """R3's record says "approached" (the EDC's step); its one state is Contacted, before consent. Participants'
    default leaves R3 out and offers participant states only; "every record" filters by the one state."""
    clients = _box(box)
    _subjects(monkeypatch, [
        {"record": "R1", "pid": "a" * 32, "since": "2026-10-01", "state": "withdrawn", "visits": {}},
        {"record": "R2", "pid": "b" * 32, "since": "2026-10-02", "state": "enrolled", "visits": {}},
        {"record": "R3", "pid": "c" * 32, "since": "2026-10-03", "state": "approached", "visits": {}},
    ])  # fmt: skip
    _flag(box, "on")
    crc, _, _ = clients["crc"]
    page = crc.get(PART).text
    assert 'data-testid="subject-R1"' in page and 'data-testid="subject-R2"' in page
    assert 'data-testid="subject-R3"' not in page and 'data-testid="count-contacted"' not in page
    assert 'href="?state=withdrawn#subjects"' in page
    only = crc.get(f"{PART}?state=withdrawn").text
    assert 'data-testid="subject-R1"' in only and 'data-testid="subject-R2"' not in only
    assert 'data-testid="state-filter"' in only and 'data-testid="count-enrolled"' in only  # counts stay whole
    assert 'data-testid="subject-R3"' not in crc.get(f"{PART}?state=contacted").text  # not a participant state here
    every = crc.get(f"{PART}/records?state=contacted").text
    assert 'data-testid="subject-R3"' in every and 'data-testid="subject-R1"' not in every
    raw = crc.get(f"{PART}/records?state=approached").text  # the record's own word is no filter: every row stays
    assert 'data-testid="subject-R3"' in raw and 'data-testid="subject-R1"' in raw
    assert CATALOGUES["en"]["people.working"] in every


# ------------------------------------------------------------------------------------------- flag on: redirects
def test_with_the_flag_on_every_old_address_sends_to_its_view_with_its_query(box: dict[str, Any]) -> None:
    clients = _box(box)
    crc, _, _ = clients["crc"]
    _flag(box, "on")
    for old, new in OLD_TO.items():
        r = crc.get(old + "?list=approached&page=2", follow_redirects=False)
        assert r.status_code == 303, old
        assert r.headers["location"] == new + "?list=approached&page=2", old
    for path in (f"/studies/{RS}/screening-log.xlsx", f"/pilot/registry/{RS}/export.xlsx", "/pilot/registry",
                 f"{SUBJ}/R1", f"/studies/{RS}/enrolment.csv", "/site/patients"):  # fmt: skip
        r = crc.get(path, follow_redirects=False)
        assert not (r.status_code == 303 and "/people/" in r.headers.get("location", "")), path
    assert crc.post(REG, data={}, follow_redirects=False).status_code != 303  # a form posts where it did
    anon = TestClient(box["app"]).get(f"{WEEK}?list=all", follow_redirects=False)  # the route's own answer
    assert anon.status_code == 303 and anon.headers["location"].startswith("/login"), anon.headers.get("location")
    assert crc.get(f"{CAND}/nothing", follow_redirects=False).status_code == 404


def test_a_relative_filter_link_stays_in_its_view(box: dict[str, Any]) -> None:
    clients = _box(box)
    crc, _, _ = clients["crc"]
    _flag(box, "on")
    week = crc.get(f"{CAND}/week?list=all")
    assert week.status_code == 200 and 'href="?list=approached"' in week.text
    ref = crc.get(f"{CAND}/referrals?show=unknown")
    assert ref.status_code == 200 and 'data-testid="people-view-referrals"' in ref.text
    assert 'aria-current="true" class="on">' in ref.text.split('data-testid="people-view-referrals"', 1)[1][:40]


# ------------------------------------------------------------------------------------------- the role walk
def test_every_role_gets_the_same_answer_and_the_same_actions_and_two_steps_at_most(box: dict[str, Any]) -> None:
    """For every role of the role matrix and every view: the flag off answer of its old address, then with the flag
    on the answers of the view and of the old address. The same status and the same refusals in the audit trail;
    on a working view the same body (every form, link and filter: every action), on a default the same forms and no
    row or column its old page did not show; the strip on a 200 only, offering the view exactly when the role gets
    it; and from the list's first page (the menu's link) one step to each view the role gets."""
    clients = _box(box)
    off: dict[tuple[str, str], tuple[int, str]] = {}
    denied: dict[tuple[str, str], int] = {}  # the refusals each old address writes to the audit trail
    for col, (page, _, _) in clients.items():
        for old in OLD_TO:
            n = len(_events(box, "console.denied"))
            r = page.get(old, follow_redirects=False)
            denied[(col, old)] = len(_events(box, "console.denied")) - n
            off[(col, old)] = (r.status_code, _main(r.text) if r.status_code == 200 else "")
    _flag(box, "on")
    reached: dict[str, set[str]] = {}
    for col, (page, _, _) in clients.items():
        for old, new, key in WALK:
            status, body = off[(col, old)]
            n = len(_events(box, "console.denied"))
            r = page.get(new, follow_redirects=False)
            assert len(_events(box, "console.denied")) - n == denied[(col, old)], (col, new)  # the same refusals
            if status == 303:  # the weekly page of a registry study sends to its cohort (not GZQO), and so on
                assert r.status_code == 303, (col, old)
                continue
            assert r.status_code == status, (col, old, status, r.status_code)
            if status != 200:
                assert 'data-testid="people-tabs"' not in r.text, (col, new)  # no strip on a refusal
                continue
            assert 'data-testid="people-tabs"' in r.text, (col, new)
            if key in DEFAULTS:
                assert _forms(_main(r.text)) == _forms(body), (col, new)
                extra = _ids(_main(r.text)) - _ids(body)
                assert all(NEW_IDS.match(i) or i.startswith("people-") for i in extra), (col, new, extra)
            else:
                assert _main(r.text) == body, (col, new)  # every form, link and filter of the old list, unchanged
            if not (col in AGGREGATE_REGISTRY and key in ("before", "everyone")):
                reached.setdefault(col, set()).add(key)
    for col, (page, _, _) in clients.items():
        for old, new in OLD_TO.items():
            status = off[(col, old)][0]
            n = len(_events(box, "console.denied"))
            o = page.get(old, follow_redirects=False)
            if status == 200 and not (col in AGGREGATE_REGISTRY and old == REG):
                assert o.status_code == 303 and o.headers["location"] == new, (col, old, o.status_code)
            else:  # anyone the route does not let in gets the route's own answer and audit event, as before
                assert o.status_code == status, (col, old, status, o.status_code)
                assert len(_events(box, "console.denied")) - n == denied[(col, old)], (col, old)
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


def test_the_strip_shows_on_a_200_only_and_the_other_list_where_the_role_opens_it(box: dict[str, Any]) -> None:
    clients = _box(box)
    _flag(box, "on")
    crc, _, _ = clients["crc"]
    page = crc.get(f"{CAND}/log").text
    assert 'data-testid="people-list-candidates"' in page and 'data-testid="people-list-participants"' in page
    assert CATALOGUES["en"]["people.working"] in page  # a working view says so
    viewer, _, _ = clients["viewer"]
    r = viewer.get(CAND)
    assert r.status_code == 403 and 'data-testid="people-tabs"' not in r.text
    r = crc.get("/studies/NOSUCH/people/candidates/week")
    assert r.status_code == 404 and 'data-testid="people-tabs"' not in r.text
    stw, _, _ = clients["steward"]  # reads the registry page's counts, no patient list: no view offered
    assert 'data-testid="people-pick-none"' in stw.get("/people/candidates").text
    assert stw.get(REG, follow_redirects=False).status_code == 200  # its address answers as before


# ------------------------------------------------------------------------------------------- the menu and the picker
def test_the_menu_the_picker_and_the_weekly_page_across_studies(box: dict[str, Any]) -> None:
    clients = _box(box)
    _flag(box, "on")
    for col in ("crc", "lpi"):
        page, _, _ = clients[col]
        html = page.get("/reports").text
        nav = html.split('data-testid="nav"', 1)[1].split('data-testid="nav-more"', 1)[0]
        assert 'href="/people/candidates"' in nav and 'href="/people/participants"' in nav, col
        assert 'href="/week"' not in nav and 'href="/pilot/registry"' not in nav, col
        assert len(re.findall(r"<a ", nav)) <= 4, col
    crc, _, _ = clients["crc"]
    html = crc.get(f"{CAND}/week").text  # a study's page: More's study links name the two lists
    assert 'data-testid="more-people-candidates"' in html and 'data-testid="more-candidates"' not in html
    nav = html.split('data-testid="nav"', 1)[1].split('data-testid="nav-more"', 1)[0]
    assert re.search(r'<a href="/people/candidates" class="active">', nav)
    # the weekly page across studies (approvals, safety banners, registry lists): one step from Candidates
    assert '<a href="/week" class="ptabs-all" data-testid="people-week-all">' in html
    # the picker: the study's list, or a choice; the view asked for is kept through the choice
    r = crc.get("/people/candidates?view=log", follow_redirects=False)
    if r.status_code == 303:
        assert r.headers["location"] == f"{CAND}/log"
    else:
        assert f'<a href="{CAND}/log" data-testid="people-pick-{RS}">' in r.text
    smo, _, _ = clients["smo"]  # an account scoped to one study: its list at once
    r = smo.get("/people/candidates", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == CAND
    r = smo.get("/people/candidates?view=nothing", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == CAND
    viewer, _, _ = clients["viewer"]  # no list of people: the menu is as before, the picker names no study
    assert "/people/" not in viewer.get("/reports").text
    assert 'data-testid="people-pick-none"' in viewer.get("/people/candidates").text


# ------------------------------------------------------------------------------------------- links from another site
def test_a_link_from_another_site_to_a_list_continues_to_it_with_its_filters() -> None:
    pid = "c" * 32
    assert phone.continue_to(f"{CAND}/week?list=all&pid={pid}&x=1") == f"{CAND}/week?list=all&pid={pid}"
    assert phone.continue_to(f"{CAND}/referrals?show=open") == f"{CAND}/referrals?show=open"
    assert phone.continue_to(f"{PART}?state=withdrawn") == f"{PART}?state=withdrawn"
    assert phone.continue_to(f"{PART}/records?state=nonsense") == f"{PART}/records"
    assert phone.continue_to("/people/candidates?view=log") == "/people/candidates?view=log"
    assert phone.continue_to(f"{CAND}/nothing") == "/home"  # not a view: the home page
    assert phone.match(f"{PART}/enrolment")[1].name == "link.page.participants"


# ------------------------------------------------------------------------------------------- three languages
@pytest.mark.parametrize("lang", LANGS)
def test_the_strip_and_the_menu_in_each_language(box: dict[str, Any], lang: str) -> None:
    clients = _box(box)
    _flag(box, "on")
    crc, csrf, _ = clients["crc"]
    _lang(crc, csrf, lang)
    cat = CATALOGUES[lang]
    page = crc.get(f"{CAND}/log").text
    for key in ("people.candidates", "people.participants", "people.view.log", "people.view.week",
                "people.view.before", "people.view.referrals", "people.working", "people.week_all"):  # fmt: skip
        assert cat[key] in page, (lang, key)
    page = crc.get(PART).text
    for key in ("people.view.from", "people.view.records", "people.view.enrolment", "people.side.participants"):
        assert cat[key] in page, (lang, key)
    if lang != "en":
        assert ">Screening log<" not in page.split('data-testid="people-tabs"', 1)[1].split("</nav>", 1)[0]


# ------------------------------------------------------------------------------------------- other tests, flag on
@pytest.mark.parametrize("role", ["investigator", "coordinator"])
@pytest.mark.parametrize("lang", LANGS)
def test_the_wording_walk_holds_with_the_flag_on(
    box: dict[str, Any], role: str, lang: str, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """The wording walk's flag-on branch (the weekly page reached at its view's address) runs in the normal suite:
    the walk of the two roles whose lists change, with the flag on, in each language."""
    from tests.console import test_wording_walk as ww

    monkeypatch.setattr(people_lists, "flag_now", lambda: True)
    ww.test_no_forbidden_word_on_any_role_page(box, role, lang)


def test_the_role_pages_hold_with_the_flag_on(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """The role pages' flag-on branch (the investigator lands on the weekly page's view) runs in the normal suite."""
    from tests.console import test_role_pages as rp

    monkeypatch.setattr(people_lists, "flag_now", lambda: True)
    rp.test_each_role_lands_on_its_own_home_with_at_most_four_items(box)
