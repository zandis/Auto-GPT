"""Card 10K-15 (D-1364; owner decision 99: no standing access for support; a support-session switch; SO-15).

The hospital's administrator turns the support-session switch on before a supervised screen share (runbook 21).
While it is on, every patient-level page and route is refused to every role, at the one permission function
(``tb_common.authz.permit``), with a page that says so in en, ja and zh-TW; the start and the end are audit events;
it ends by itself 2 hours after its stored start, checked at request time (a frozen clock moved here); when its state
cannot be read, the patient pages stay closed. Synthetic pseudonyms and chart numbers only."""

from __future__ import annotations

import json
import re
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from console.breakglass_store import SupportSessionStore
from tb_common import authz
from tb_common.authz import BEST_STANDING, MATRIX, MATRIX_ROLES, NO_STANDING, SUPPORT_SESSION_OPEN, permit

from tests.console.test_console_app import _done_screen, _ulid, box, login, login_crc  # noqa: F401 - the fixture
from tests.console.test_role_pages import _csrf, _user
from tests.console.test_role_route_matrix import PW, TABLE, parse, walk

A = "a" * 32
PAGE = "/ops/support-session"
ON_EN = "A support session is running"
ON_JA = "サポートセッション実行中"
ON_ZH = "支援作業時段進行中"


def _events(b: dict[str, Any], name: str) -> list[dict[str, Any]]:
    out = []
    for f in sorted((b["dir"] / "audit").glob("*")):
        for line in f.read_text().splitlines():
            if line and json.loads(line).get("event") == name:
                out.append(json.loads(line))
    return out


def _start(b: dict[str, Any], ticket: str = "SUP-0042") -> Any:
    admin, _ = login(b["app"])
    r = admin.post(
        PAGE, data={"csrf": _csrf(admin.get(PAGE).text), "ticket": ticket, "confirm": "yes"}, follow_redirects=False
    )
    assert r.status_code == 303 and r.headers["location"] == f"{PAGE}?done=start", r.headers.get("location")
    return admin


def _end(admin: Any) -> Any:
    page = admin.get(PAGE).text
    sid = re.search(r'name="session" value="(\d+)"', page)
    assert sid, "the page offers the end of the running session"
    return admin.post(f"{PAGE}/end", data={"csrf": _csrf(page), "session": sid.group(1)}, follow_redirects=False)


def _shift(b: dict[str, Any], minutes: int) -> None:
    """Move the console's clock (the session's clock) forward from now: a frozen clock, not a sleep."""
    h = b["app"].state.helpers
    base = h.clock()
    h.clock = lambda: base + timedelta(minutes=minutes)


def _lang(c: Any, lang: str) -> None:
    csrf = _csrf(c.get("/account").text)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})


# ---------------------------------------------------------------------------------------------- the choke point
def test_permit_refuses_every_row_outside_the_open_list_during_a_session() -> None:
    assert not authz.in_support_session()  # a process that never marks a request answers as before
    before = {(r, a): (permit(r, a, BEST_STANDING).allowed, permit(r, a, NO_STANDING).allowed)
              for r in MATRIX_ROLES for a in MATRIX}  # fmt: skip
    token = authz.support_session_begin(True)
    try:
        for (role, action), was in before.items():
            now = (permit(role, action, BEST_STANDING).allowed, permit(role, action, NO_STANDING).allowed)
            if action in SUPPORT_SESSION_OPEN:
                assert now == was, (role, action)  # the open rows keep their answer: nothing is widened
            else:
                assert now == (False, False), (role, action)
                assert permit(role, action, BEST_STANDING).basis == "support session"
    finally:
        authz.support_session_end(token)
    assert {k: (permit(r, a, BEST_STANDING).allowed, permit(r, a, NO_STANDING).allowed)
            for k in before for r, a in [k]} == before  # fmt: skip


def test_the_open_list_holds_no_patient_row_and_the_switch_is_the_administrators() -> None:
    # every open row is the administrator's (who holds no patient-level row, D-280) or one of the two restrictions
    restrictions = {"report.aggregate_only", "report.sponsor_form"}
    for action in SUPPORT_SESSION_OPEN - restrictions:
        assert MATRIX[action]["admin"] is True, action
    patient = ("phi.", "id.", "list.", "task.", "sae.", "optout.", "monitor.", "profile.", "breakglass.", "audit.",
               "notmatched.", "referral.", "delegation.", "irb.", "conflicts.", "items.", "staff.")  # fmt: skip
    assert not [a for a in SUPPORT_SESSION_OPEN if a.startswith(patient)]
    assert {a for a in SUPPORT_SESSION_OPEN if a.startswith("edc.")} == {"edc.switch_off"}  # stopping prefill only
    # the one new row: the administrator starts and ends it; no other role does anything new
    assert {r for r in MATRIX_ROLES if MATRIX["support.session"][r] is not False} == {"admin"}


# ---------------------------------------------------------------------------------------------- proved by
def test_a_patient_page_is_refused_during_a_session(box: dict[str, Any]) -> None:  # noqa: F811
    jid = _ulid(994)
    _done_screen(box["backend"], jid)
    crc, _ = login_crc(box)
    assert crc.get(f"/studies/GZQO/patients/{A}").status_code == 200  # before: the coordinator reads the patient
    assert 'data-testid="screen-rows"' in crc.get(f"/pilot/jobs/{jid}").text
    admin = _start(box)
    for path in (
        f"/studies/GZQO/patients/{A}",
        "/studies/GZQO/candidates",
        f"/studies/GZQO/candidates/{A}",
        "/studies/GZQO/screening-log",
        "/studies/GZQO/screening-log.xlsx",
        "/sae",
        "/studies/GZQO/week",
    ):
        r = crc.get(path)
        assert r.status_code == 403, path
        assert ON_EN in r.text and 'data-testid="problem-page"' in r.text, path  # the clear page, not a bare 403
    page = crc.get(f"/studies/GZQO/patients/{A}").text
    until = re.search(r"at the latest at ([0-9-]+ [0-9:]+)", page)
    assert until, "the page says when the session ends at the latest"
    assert A not in page and A[:8] not in page  # the refused URL's pseudonym is not repeated (no link, no way back)
    # the job page keeps its counts and shows no patient row; the reveal is refused with a body too
    assert 'data-testid="screen-rows"' not in crc.get(f"/pilot/jobs/{jid}").text
    csrf = _csrf(crc.get("/account").text)
    r = crc.post(f"/studies/GZQO/candidates/{A}/reveal", data={"csrf": csrf, "purpose": "contact", "reason": "contact"})
    assert r.status_code == 403 and ON_EN in r.text and box["backend"].revealed == []
    r = crc.post(f"/studies/GZQO/patients/{A}/reveal", data={"csrf": csrf, "reason": "contact"})
    assert r.status_code == 403 and box["backend"].revealed == []
    # the same page in Japanese and Traditional Chinese
    _lang(crc, "ja")
    assert ON_JA in crc.get(f"/studies/GZQO/patients/{A}").text
    _lang(crc, "zh-TW")
    assert ON_ZH in crc.get(f"/studies/GZQO/patients/{A}").text
    # /api/v1 says it in JSON
    token, _ = box["users"].new_session(box["users"].get("crc"), via="api")
    from fastapi.testclient import TestClient

    api = TestClient(box["app"], headers={"Authorization": f"Bearer {token}"})
    r = api.get("/api/v1/studies/GZQO/screening-log")
    assert r.status_code == 403 and r.json()["error"] == "support.session_on" and r.json()["detail"]["until"]
    # every role: the investigator the log names, the administrator under a break-glass grant opened before
    assert admin.get(f"/studies/GZQO/patients/{A}").status_code == 403
    # the administrator's pages carry the banner; the coordinator's refusal page is the explanation
    assert 'data-testid="support-banner"' in admin.get("/home").text
    assert 'data-testid="support-banner"' in admin.get("/jobs").text
    assert 'data-testid="support-banner"' not in crc.get("/home").text
    # after the end the coordinator reads the patient again
    assert _end(admin).status_code == 303
    _lang(crc, "en")
    assert crc.get(f"/studies/GZQO/patients/{A}").status_code == 200
    assert 'data-testid="support-banner"' not in admin.get("/home").text


def test_a_break_glass_grant_opened_before_does_not_open_a_patient_during_a_session(box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(995))
    admin, _ = login(box["app"])
    form = {"csrf": _csrf(admin.get("/breakglass").text), "reason": "support", "note": "support call about one patient",
            "kind": "patient", "ruleset": "GZQO", "pid": A}  # fmt: skip
    assert admin.post("/breakglass", data=form, follow_redirects=False).status_code == 303
    assert admin.get(f"/studies/GZQO/patients/{A}").status_code == 200  # the grant opens it outside a session
    _start(box)
    assert admin.get(f"/studies/GZQO/patients/{A}").status_code == 403
    assert admin.get("/breakglass").status_code == 403  # no grant opened, used or listed while support watches


def test_the_start_and_the_end_are_two_audit_events(box: dict[str, Any]) -> None:  # noqa: F811
    admin, _ = login(box["app"])
    r = admin.post(PAGE, data={"csrf": _csrf(admin.get(PAGE).text), "ticket": "SUP-0041"}, follow_redirects=False)
    assert r.status_code == 400 and 'href="#support-confirm"' in r.text  # not ticked: nothing starts (D-1376 form)
    admin = _start(box, ticket="SUP-0042")
    assert 'data-testid="support-live"' in admin.get(PAGE).text
    r = admin.post(PAGE, data={"csrf": _csrf(admin.get(PAGE).text), "ticket": "SUP-0043", "confirm": "yes"},
                   follow_redirects=False)  # fmt: skip
    assert r.headers["location"] == f"{PAGE}?err=support.err.on"  # one at a time
    assert _end(admin).headers["location"] == f"{PAGE}?done=end"
    start, end = _events(box, "console.support_session_start"), _events(box, "console.support_session_end")
    assert len(start) == 1 and len(end) == 1
    assert start[0]["actor"] == "console:admin" and start[0]["detail"]["ticket"] == "SUP-0042"
    assert start[0]["detail"]["started_by"] == "admin" and start[0]["detail"]["ends_at"]
    assert end[0]["actor"] == "console:admin" and end[0]["detail"]["how"] == "hand"
    assert end[0]["detail"]["session"] == start[0]["detail"]["session"] and end[0]["detail"]["ended_at"]
    # a ticket field holds a ticket number, never a name or a sentence
    r = admin.post(PAGE, data={"csrf": _csrf(admin.get(PAGE).text), "ticket": "Taro Yamada called", "confirm": "yes"},
                   follow_redirects=False)  # fmt: skip
    assert (
        r.status_code == 400
        and 'href="#support-ticket"' in r.text
        and "Taro Yamada called" not in r.text.split('class="fm-summary"')[1].split("</div>")[0]
    )
    for name in ("TaroYamada", "Yamada-Taro", "T.Yamada"):  # the shape of a number: letters alone are refused
        r = admin.post(PAGE, data={"csrf": _csrf(admin.get(PAGE).text), "ticket": name, "confirm": "yes"},
                       follow_redirects=False)  # fmt: skip
        assert r.status_code == 400 and 'href="#support-ticket"' in r.text, name
    assert len(_events(box, "console.support_session_start")) == 1


# ---------------------------------------------------------------------------------------------- the trail (S1)
def _failing_audit(b: dict[str, Any], monkeypatch: pytest.MonkeyPatch, event: str) -> list[int]:
    """The audit append refuses ``event`` while the returned list is empty (append 1 to let it through)."""
    au = b["app"].state.helpers.au
    real = au.append
    let_through: list[int] = []

    def append(name: str, *a: Any, **kw: Any) -> Any:
        if name == event and not let_through:
            raise OSError("the audit chain refused the write")
        return real(name, *a, **kw)

    monkeypatch.setattr(au, "append", append)
    return let_through


def test_no_session_is_on_without_its_start_event(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(985))
    crc, _ = login_crc(box)
    admin, _ = login(box["app"])
    _failing_audit(box, monkeypatch, "console.support_session_start")
    r = admin.post(PAGE, data={"csrf": _csrf(admin.get(PAGE).text), "ticket": "SUP-1", "confirm": "yes"},
                   follow_redirects=False)  # fmt: skip
    assert r.headers["location"] == f"{PAGE}?err=support.err.audit"
    assert box["app"].state.support_guard.store.recent() == []  # rolled back: no row, so no session
    assert crc.get(f"/studies/GZQO/patients/{A}").status_code == 200


def test_an_end_event_that_fails_is_written_at_a_later_request(
    box: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _done_screen(box["backend"], _ulid(986))
    crc, _ = login_crc(box)
    admin = _start(box)
    # by hand: the event fails, so the session stays on (closed) and the end can be tried again
    let = _failing_audit(box, monkeypatch, "console.support_session_end")
    assert _end(admin).headers["location"] == f"{PAGE}?err=support.err.audit"
    assert crc.get(f"/studies/GZQO/patients/{A}").status_code == 403
    # automatically: the row ends at its 2 hours, the event fails, the next request writes it, once
    _shift(box, 121)
    assert crc.get(f"/studies/GZQO/patients/{A}").status_code == 200  # ended: the row is the switch
    row = box["app"].state.support_guard.store.recent()[0]
    assert row.how == "auto" and not row.end_audited and _events(box, "console.support_session_end") == []
    let.append(1)
    crc.get("/home")
    crc.get("/home")
    end = _events(box, "console.support_session_end")
    assert len(end) == 1 and end[0]["detail"]["how"] == "auto" and end[0]["detail"]["ended_at"] == row.ends_at
    assert box["app"].state.support_guard.store.recent()[0].end_audited


def test_a_damaged_or_future_start_can_always_be_ended_and_never_runs_past_two_hours(box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(987))
    crc, _ = login_crc(box)
    admin = _start(box)
    store = box["app"].state.support_guard.store
    sid = store.recent()[0].id
    # a start the clock has not reached (the clock was moved back a day): bounded to 2 hours from the request
    later = (box["app"].state.helpers.clock() + timedelta(days=1)).isoformat(timespec="seconds")
    store.db.execute("UPDATE support_sessions SET started_at = ? WHERE id = ?", (later, sid))
    assert crc.get(f"/studies/GZQO/patients/{A}").status_code == 403
    assert store.get(sid).started_at < later  # re-anchored to the request's time
    _shift(box, 121)
    assert crc.get(f"/studies/GZQO/patients/{A}").status_code == 200  # 2 hours later it is over, not a day later
    # a start that cannot be read: closed on doubt, and the administrator can still end it from the page
    admin = _start(box)
    sid = store.recent()[0].id
    store.db.execute("UPDATE support_sessions SET started_at = 'not a time' WHERE id = ?", (sid,))
    r = crc.get(f"/studies/GZQO/patients/{A}")
    assert r.status_code == 403
    page = admin.get(PAGE)
    assert page.status_code == 200 and "its start time cannot be read" in page.text
    assert _end(admin).headers["location"] == f"{PAGE}?done=end"
    assert crc.get(f"/studies/GZQO/patients/{A}").status_code == 200


def test_a_case_job_page_is_a_patient_page_during_a_session(box: dict[str, Any]) -> None:  # noqa: F811
    from tests.console.test_console_app import _done_case

    job = _done_case(box["backend"])
    crc, _ = login_crc(box)
    admin, _ = login(box["app"])
    assert crc.get(f"/pilot/jobs/{job.job_id}").status_code == 200
    assert admin.get(f"/pilot/jobs/{job.job_id}").status_code == 200  # counts, chart number masked
    _start(box)
    for c in (crc, admin):
        r = c.get(f"/pilot/jobs/{job.job_id}")
        assert r.status_code == 403 and ON_EN in r.text and job.job_id not in r.text


def test_only_the_administrator_starts_or_ends_it(box: dict[str, Any]) -> None:  # noqa: F811
    for name, role in (("crc1", "coordinator"), ("stw1", "steward"), ("pi1", "investigator"), ("dpo1", "privacy")):
        c = _user(box, name, role)
        assert c.get(PAGE).status_code == 403, role
        csrf = _csrf(c.get("/account").text)
        assert c.post(PAGE, data={"csrf": csrf, "ticket": "", "confirm": "yes"}).status_code == 403, role
        assert c.post(f"{PAGE}/end", data={"csrf": csrf, "session": "1"}).status_code == 403, role
    assert _events(box, "console.support_session_start") == []


def test_the_admin_page_links_the_switch(box: dict[str, Any]) -> None:  # noqa: F811
    """One click from the Admin page (its accounts tile), so the plain menu (J-7, D-1251) reaches it too."""
    admin, _ = login(box["app"])
    r = admin.get("/admin?tab=health")
    assert r.status_code == 200 and f'href="{PAGE}"' in r.text


def test_it_ends_by_itself_after_two_hours_on_a_frozen_clock(box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(996))
    crc, _ = login_crc(box)
    admin = _start(box)
    # a restart: a new store reads the stored start, and the session is still on (no timer holds it)
    fresh = SupportSessionStore()
    try:
        live, lapsed = fresh.current(box["app"].state.helpers.clock())
        assert live is not None and lapsed == []
    finally:
        fresh.close()
    _shift(box, 119)
    assert crc.get(f"/studies/GZQO/patients/{A}").status_code == 403  # 1 minute before the end: still closed
    assert _events(box, "console.support_session_end") == []
    _shift(box, 121)  # past the 2 hours; no request in between, no scheduler
    assert crc.get(f"/studies/GZQO/patients/{A}").status_code == 200
    crc.get("/home")  # a second request does not end it twice
    end = _events(box, "console.support_session_end")
    assert len(end) == 1 and end[0]["detail"]["how"] == "auto" and end[0]["actor"] == "console:support-session"
    assert end[0]["detail"]["ended_at"] == end[0]["detail"]["ends_at"]  # ended at its latest end, not when seen
    row = box["app"].state.support_guard.store.recent()[0]
    assert row.how == "auto" and row.ended_at == row.ends_at
    assert 'data-testid="support-banner"' not in admin.get("/home").text
    assert "by itself after 2 hours" in admin.get(PAGE).text


def test_on_doubt_the_patient_pages_stay_closed(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(997))
    crc, _ = login_crc(box)
    store = box["app"].state.support_guard.store

    def broken(now: Any) -> Any:
        raise OSError("the trial database does not answer")

    monkeypatch.setattr(store, "current", broken)
    r = crc.get(f"/studies/GZQO/patients/{A}")
    assert r.status_code == 403 and "cannot read whether a support session is running" in r.text
    monkeypatch.undo()
    assert crc.get(f"/studies/GZQO/patients/{A}").status_code == 200


# ---------------------------------------------------------------------------------------------- the matrix walk
# A route whose path names patient-level data. During a session none may be open (Y) to any role; the exceptions
# answer the walk's empty body (400) before they ask the row, and are refused with a body above.
PATIENT_PATH = re.compile(r"\{pid\}|/patients|/candidates|/participants|/subjects|/sae|/breakglass|/audit|/excluded|"
                          r"/screening-log|/not-matched|/registry/|/profile|/twin|/entry|/history|/visits|/cohort|"
                          r"/studies/\{rs\}/(week|edc|copy|life|report)")  # fmt: skip
EMPTY_BODY = {("POST", "/studies/{rs}/candidates/{pid}/reveal"),
              # turning prefill off stays open (``edc.switch_off``: a stop narrows); turning it on is refused
              ("POST", "/api/v1/studies/{rs}/edc/switch")}  # fmt: skip
# the registry's rows are read signed for the account (console.actor.assert_for asks permit, closed during a session),
# so on a box with a study store the page is refused; the walk's box has none and shows the empty page (no row)
SHOWN_EMPTY = {("GET", "/pilot/registry/{ruleset}")}

# The routes open during a session, and to whom (the walk's columns: ``crc`` coordinator, ``pi`` an investigator the
# log names, ``lpi`` the study's PI, ``smo``, ``cra``, ``viewer``, ``steward``, ``privacy``), pinned on purpose (the
# review of D-1364): a route that opens during a session, or opens to one more column, fails the walk below until it
# is added here after a review that it shows no patient row. Several are open to the administrator only because they
# ask ``is_admin`` and no matrix row (``/metrics``, ``/data/instruments``, ``/ops/notices``, ``/admin``, ``/admin/redcap``,
# ``/admin/accounts``); D-1364 names them. Regenerated from this walk, 2026-11-19: 113 routes
# (86 answer Y, 27 answer 404 or 503 in the walk's box); 2026-11-20 (the review of aeb978e6): 109, since a job's
# files and views outside DOWNLOADS_OPEN_DURING_A_SESSION, a cascade run's files and the cancel (command.CANCEL,
# item 11) are closed (85 Y, 24 n or U). test_no_open_route_shows_a_seeded_patient_token_during_a_session walks
# them all again with patient data present.
OPEN_DURING_A_SESSION: dict[tuple[str, str], str] = {
    ("GET", "/"): "admin crc pi lpi smo cra viewer steward privacy",
    ("GET", "/about"): "admin crc pi lpi smo cra viewer steward privacy",
    ("GET", "/about/NOTICE.txt"): "admin crc pi lpi smo cra viewer steward privacy",
    ("GET", "/account"): "admin crc pi lpi smo cra viewer steward privacy",
    ("GET", "/admin"): "admin",
    ("GET", "/admin/accounts"): "admin",
    ("GET", "/admin/edc"): "admin",
    ("GET", "/admin/notice"): "admin",
    ("GET", "/admin/ops"): "admin",
    ("GET", "/admin/redcap"): "admin",
    ("GET", "/api/edc/health"): "admin crc pi lpi smo cra viewer steward privacy",
    ("GET", "/api/edc/map"): "admin",
    ("GET", "/api/v1/admin/ops"): "admin",
    ("GET", "/api/v1/ask"): "admin crc pi lpi smo viewer steward privacy",
    ("GET", "/api/v1/data/batches"): "admin steward",
    ("GET", "/api/v1/data/sources"): "admin steward",
    ("GET", "/api/v1/site/readiness"): "admin",
    ("GET", "/api/v1/studies"): "admin crc pi lpi smo cra viewer steward privacy",
    ("GET", "/api/v1/studies/{rs}/delegation"): "admin crc pi lpi smo steward privacy",
    ("GET", "/api/v1/studies/{rs}/icf"): "admin crc pi lpi smo steward privacy",
    ("GET", "/api/v1/studies/{rs}/irb"): "admin crc pi lpi smo steward privacy",
    ("GET", "/ask"): "admin crc pi lpi smo cra viewer steward privacy",
    ("GET", "/cmd"): "admin crc pi lpi smo cra viewer steward privacy",
    ("GET", "/data-ops"): "admin steward",
    ("GET", "/data/instruments"): "admin",
    ("GET", "/enrol"): "admin crc pi lpi smo cra viewer steward privacy",
    ("GET", "/help"): "admin crc pi lpi smo cra viewer steward privacy",
    ("GET", "/help/guide"): "admin crc pi lpi smo cra viewer steward privacy",
    ("GET", "/home"): "admin crc pi lpi smo cra viewer steward privacy",
    ("GET", "/jobs"): "admin crc pi lpi steward privacy",
    ("GET", "/metrics"): "admin",
    ("GET", "/notices/received"): "admin crc pi lpi smo viewer steward privacy",
    ("GET", "/ops/accounts/requests"): "admin steward",
    ("GET", "/ops/flags"): "admin steward",
    ("GET", "/ops/identity"): "admin",
    ("GET", "/ops/support-session"): "admin",
    ("GET", "/ops/users"): "admin",
    ("GET", "/pilot/cascade"): "admin crc pi lpi steward privacy",
    ("GET", "/pilot/case"): "admin crc pi lpi smo viewer steward privacy",
    ("GET", "/pilot/consent"): "admin crc pi lpi smo viewer steward privacy",
    ("GET", "/pilot/jobs/{job_id}"): "admin crc pi lpi smo steward privacy",
    ("GET", "/pilot/jobs/{job_id}/approval"): "admin crc pi lpi smo steward privacy",
    ("GET", "/pilot/mailbox"): "admin crc pi lpi steward privacy",
    ("GET", "/pilot/protocol"): "admin crc pi lpi smo viewer steward privacy",
    ("GET", "/pilot/registry"): "admin crc pi lpi smo steward privacy",
    ("GET", "/pilot/registry/{ruleset}"): "crc smo steward privacy",
    ("GET", "/pilot/request"): "admin crc pi lpi smo viewer steward privacy",
    ("GET", "/reports"): "admin crc pi lpi smo cra viewer steward privacy",
    ("GET", "/settings/notices"): "admin crc pi lpi smo viewer steward privacy",
    ("GET", "/site"): "admin",
    ("GET", "/site/checks"): "admin",
    ("GET", "/site/codes"): "admin",
    ("GET", "/site/help"): "admin",
    ("GET", "/site/sheets"): "admin",
    ("GET", "/site/start"): "admin",
    ("GET", "/studies/{rs}/feasibility"): "admin crc pi lpi smo cra viewer steward privacy",
    ("GET", "/studies/{rs}/forms"): "admin crc pi lpi smo steward privacy",
    ("GET", "/studies/{rs}/irb"): "admin crc pi lpi smo steward privacy",
    ("GET", "/studies/{rs}/sources"): "admin crc pi lpi smo steward privacy",
    ("GET", "/studies/{rs}/team"): "admin crc pi lpi smo steward privacy",
    ("GET", "/week"): "admin crc pi lpi smo steward privacy",
    ("POST", "/account/password"): "admin crc pi lpi smo cra viewer steward privacy",
    ("POST", "/admin/jobs/{job_id}/retry"): "admin",
    ("POST", "/admin/models/canary"): "admin",
    ("POST", "/admin/redcap"): "admin",
    ("POST", "/admin/redcap/{ref}/test"): "admin",
    ("POST", "/api/v1/site/checks/{cid}"): "admin",
    ("POST", "/api/v1/site/codes"): "admin",
    ("POST", "/api/v1/studies/{rs}/edc/switch"): "admin lpi",
    ("POST", "/data/instruments/{iid}"): "admin",
    ("POST", "/enrol"): "admin crc pi lpi smo cra viewer steward privacy",
    ("POST", "/feedback"): "admin crc pi lpi smo cra viewer steward privacy",
    ("POST", "/ops/accounts/requests"): "admin steward",
    ("POST", "/ops/flags"): "admin",
    ("POST", "/ops/identity"): "admin",
    ("POST", "/ops/ingest"): "admin",
    ("POST", "/ops/notices"): "admin",
    ("POST", "/ops/support-session"): "admin",
    ("POST", "/ops/support-session/end"): "admin",
    ("POST", "/ops/users"): "admin",
    ("POST", "/settings/notices"): "admin crc pi lpi smo viewer steward privacy",
    ("POST", "/site/practice"): "admin",
    ("POST", "/site/sheets"): "admin",
    ("POST", "/studies/{rs}/candidates/{pid}/reveal"): "admin crc pi lpi smo steward privacy",
    ("PUT", "/api/edc/map"): "admin",
    # Not refused by the switch, and not Y in the walk's box: they answer 404 (n) or 503 (U) there, before or without
    # a closed row (the review of D-1364). Each with why it shows no patient row.
    ("GET", "/admin/ops/network/{name}"): "admin",  # 404 for an unknown file; the remote-help network sheets (ops.*), no patient row
    ("GET", "/api/edc/oidc/.well-known/openid-configuration"): "admin crc pi lpi smo cra viewer steward privacy",  # 404, the EDC sign-in off in the walk's box; on: the issuer's public metadata
    ("GET", "/api/edc/oidc/authorize"): "admin crc pi lpi smo cra viewer steward privacy",  # 404, the EDC sign-in off; on: refused during a session (test_no_edc_sign_in_starts_during_a_session)
    ("GET", "/api/edc/oidc/userinfo"): "admin crc pi lpi smo cra viewer steward privacy",  # 404, the EDC sign-in off; on: a token's subject only, and no token is issued during a session
    ("GET", "/api/v1/data/batches/{bid}"): "admin steward",  # 404 for an unknown batch; a batch's steps (dataops.view, open), as /data-ops
    ("GET", "/api/v1/site/checks"): "admin",  # 503, no setup service in the walk's box; the site's checks (site.setup, open)
    ("GET", "/api/v1/site/codes"): "admin",  # 503, no setup service; the site's code lists (site.setup, open), no patient row
    ("GET", "/api/v1/studies/{rs}/forms"): "admin crc pi lpi smo steward privacy",  # 503, no study store; the study's forms, as /studies/{rs}/forms
    ("GET", "/api/v1/studies/{rs}/sources"): "admin crc pi lpi smo steward privacy",  # 503, no study store; the study's sources, as /studies/{rs}/sources
    ("GET", "/auth/oidc/callback"): "admin crc pi lpi smo cra viewer steward privacy",  # 404, the console's own OIDC sign-in off; signing in stays open, as /login
    ("GET", "/auth/oidc/start"): "admin crc pi lpi smo cra viewer steward privacy",  # 404, the console's own OIDC sign-in off; signing in stays open, as /login
    ("GET", "/data-ops/batches/{bid}"): "admin steward",  # 404 for an unknown batch; a batch's steps (dataops.view, open; D-1364's known limits)
    ("GET", "/demo/ack"): "admin crc pi lpi smo cra viewer steward privacy",  # 404 off the demo box; the demo notice's acknowledgement
    ("GET", "/pilot/cascade/{run_id}"): "admin crc pi lpi steward privacy",  # 404 for an unknown run; a cascade run's released counts (aggregate), as /pilot/cascade
    ("GET", "/site/templates/{name}.xlsx"): "admin",  # 404 for an unknown template; a blank setup sheet (site.setup, open)
    ("POST", "/admin/ops/{action}"): "admin crc pi lpi smo cra viewer steward privacy",  # 404 for an unknown action, before the role; a known action asks its ops.* row (the administrator's)
    ("POST", "/api/edc/events/v1"): "admin crc pi lpi smo cra viewer steward privacy",  # 404, no event secret in the walk's box; the EDC's signed event feed, no console session (D-1364)
    ("POST", "/api/edc/oidc/token"): "admin crc pi lpi smo cra viewer steward privacy",  # 404, the EDC sign-in off; on: refused during a session (test_a_sign_in_code_issued_before_...)
    ("POST", "/demo/ack"): "admin crc pi lpi smo cra viewer steward privacy",  # 404 off the demo box; the demo notice's acknowledgement
    ("POST", "/site/checks/{cid}"): "admin",  # 503 after the CSRF check, no setup service; a site check (site.setup, open)
    ("POST", "/site/codes"): "admin",  # 503 after the CSRF check, no setup service; the site's code lists (site.setup, open)
    ("POST", "/site/remote"): "admin",  # 503 after the CSRF check, no setup service; remote help on or off (is_admin, then ops.network)
    ("POST", "/studies/{rs}/edc/switch"): "admin lpi",  # 503, no study store; turning prefill off (edc.switch_off, a stop narrows), on refused
    ("POST", "/studies/{rs}/sae/{record}/{event}/{what}"): "admin crc pi lpi smo steward privacy",  # 404 for an unknown step, before the scope; a known step asks the record's scope (closed)
}  # fmt: skip


def test_the_matrix_walk_finds_no_patient_route_open_during_a_session(box: dict[str, Any]) -> None:  # noqa: F811
    _start(box)
    during = {(m, p): c for m, p, c in walk(box)}
    design = parse(TABLE.read_text(encoding="utf-8"))
    assert len(during) > 150 and set(during) == set(design)  # the walk reached the whole router table
    opened = {k for k, c in during.items() if "Y" in c.values()}
    # 1. no route that names patient data is open to any role
    assert sorted(k for k in opened if PATIENT_PATH.search(k[1]) and k not in EMPTY_BODY | SHOWN_EMPTY) == []
    # 2. whatever stays open to any role is open to the administrator outside a session (no patient row, D-280)
    assert sorted(k for k in opened if design[k]["admin"] != "Y" and k not in SHOWN_EMPTY) == []
    # 2b. exactly the reviewed list is not refused by the switch, to exactly its columns: a new route open during a
    # session fails here. "Not refused" is any answer but the switch's refusal (every 403 during a session is that
    # refusal, ``SupportGuard.dispatch``) or a sign-in answer (L): a route that answers 404 or 503 in the walk's box
    # (``_cell``'s n and U) is open too, and pinned with the Y routes (the review of D-1364)
    reached = {k for k, c in during.items() if set(c.values()) - {"-", "L"}}
    got = {k: {col for col, v in during[k].items() if v not in ("-", "L")} for k in reached}
    want = {k: set(cols.split()) for k, cols in OPEN_DURING_A_SESSION.items()}
    assert sorted(set(got) - set(want)) == [], "open during a session and not in OPEN_DURING_A_SESSION"
    assert sorted(set(want) - set(got)) == [], "in OPEN_DURING_A_SESSION and no longer open: take it off the list"
    assert {k: sorted(v) for k, v in got.items() if v != want[k]} == {}, "open to other columns than the list says"
    # 3. nothing opens that was closed: the session only narrows
    widened = [(k, col) for k, c in during.items() for col, v in c.items() if v == "Y" and design[k][col] != "Y"]
    assert widened == []
    # 4. and it did close the patient routes the coordinator and the PI read outside a session
    for key in (("GET", "/studies/{rs}/patients/{pid}"), ("GET", "/studies/{rs}/candidates"),
                ("GET", "/api/v1/studies/{rs}/screening-log"), ("GET", "/sae")):  # fmt: skip
        assert design[key]["crc"] == "Y" and during[key]["crc"] == "-", key
        assert design[key]["lpi"] == "Y" and during[key]["lpi"] == "-", key
    assert A[:8] not in login(box["app"], "crc", PW)[0].get("/pilot/registry/GZQO").text


# ---------------------------------------------------------------------------------------------- runbook 21's drill
def test_runbook_21_support_session(box: dict[str, Any]) -> None:  # noqa: F811
    """The drill of runbook 21 (T-213b): a ticket is opened, the hospital's administrator starts the support session
    with its number, the session runs to the rules (what may be on screen opens, a patient page, a patient list and an
    export do not), the hospital's person ends it, and the record is two audit events. The Docker part (the support
    bundle holds no patient data) is held by tests/unit/test_support_bundle_no_secret.py and tools.data_scan."""
    jid = _ulid(998)
    _done_screen(box["backend"], jid)
    ticket = "TB-2026-0117"  # step 0: the ticket (the site, the priority, what was seen): kept in the ticket system
    # rule 1: the hospital starts it, the administrator (tier 1), for one ticket
    admin = _start(box, ticket=ticket)
    # rule 3: what may be on screen: the Operations page, the Jobs page, the health page, the job's own page
    assert admin.get("/metrics").status_code == 200  # the health figures (text, no page)
    for path in ("/admin", "/admin/ops", "/jobs", f"/pilot/jobs/{jid}", PAGE):
        r = admin.get(path)
        assert r.status_code == 200 and 'data-testid="support-banner"' in r.text, path
    assert 'data-testid="screen-rows"' not in admin.get(f"/pilot/jobs/{jid}").text
    # rule 3: never a patient page, a patient list or an export, whoever is signed in on the hospital PC
    crc, _ = login_crc(box)
    for c in (admin, crc):
        for path in (f"/studies/GZQO/patients/{A}", "/studies/GZQO/candidates", "/pilot/registry/GZQO/export.xlsx",
                     "/studies/GZQO/screening-log.xlsx"):  # fmt: skip
            assert c.get(path).status_code == 403, path
    # rule 6: the hospital's person ends it
    assert _end(admin).headers["location"] == f"{PAGE}?done=end"
    # rule 5: the record: the start and the end, who and when, with the ticket number
    start, end = _events(box, "console.support_session_start"), _events(box, "console.support_session_end")
    assert [e["detail"]["ticket"] for e in start] == [ticket] and [e["detail"]["how"] for e in end] == ["hand"]
    assert crc.get(f"/studies/GZQO/patients/{A}").status_code == 200


# ---------------------------------------------------------------------------------------------- the review's round
def _on(admin: Any) -> None:
    """Start a session from this administrator's own client (its one-time secrets are kept for its session)."""
    r = admin.post(PAGE, data={"csrf": _csrf(admin.get(PAGE).text), "ticket": "SUP-7", "confirm": "yes"},
                   follow_redirects=False)  # fmt: skip
    assert r.headers["location"] == f"{PAGE}?done=start"


def _denied(b: dict[str, Any], action: str) -> list[dict[str, Any]]:
    return [e for e in _events(b, "console.denied") if e["detail"].get("action") == action]


def test_the_feedback_file_is_closed_during_a_session(box: dict[str, Any]) -> None:  # noqa: F811
    crc, _ = login_crc(box)
    csrf = _csrf(crc.get("/account").text)
    crc.post("/feedback", data={"csrf": csrf, "path": f"/studies/GZQO/patients/{A}", "comment": "slow page"},
             follow_redirects=False)  # fmt: skip
    admin, _ = login(box["app"])
    r = admin.get("/feedback/export.csv")
    assert r.status_code == 200 and A in r.text  # off: the administrator's file, a patient page's path in it
    _on(admin)
    r = admin.get("/feedback/export.csv")
    assert r.status_code == 403 and ON_EN in r.text and A not in r.text and "slow page" not in r.text
    assert len(_denied(box, "/feedback/export.csv")) == 1  # audited as every closed page
    assert len(_events(box, "feedback.export")) == 1  # the one export before the session
    assert _end(admin).status_code == 303
    assert admin.get("/feedback/export.csv").status_code == 200


def test_a_new_account_or_a_reset_password_is_not_shown_during_a_session(box: dict[str, Any]) -> None:  # noqa: F811
    admin, csrf = login(box["app"])
    add = {"csrf": csrf, "action": "add", "role": "viewer", "affiliation": "hospital", "studies": ""}
    r = admin.post("/ops/users", data={**add, "username": "vw1"})
    assert r.status_code == 200 and 'data-testid="users-pw-field"' in r.text  # off: the one-time password, once
    r = admin.post("/ops/users", data={"csrf": csrf, "action": "reset", "username": "vw1", "confirm": "yes"})
    assert 'data-testid="users-pw-field"' in r.text
    # a password made just before the session started, not yet read: kept, not shown while support watches
    assert admin.post("/ops/users", data={**add, "username": "vw2"}, follow_redirects=False).status_code == 303
    _on(admin)
    page = admin.get("/ops/users")
    assert page.status_code == 200 and 'data-testid="users-made"' not in page.text  # the list stays open
    for action, data in (("add", {**add, "username": "vw3"}),
                         ("reset", {"csrf": csrf, "action": "reset", "username": "vw1", "confirm": "yes"})):  # fmt: skip
        r = admin.post("/ops/users", data=data)
        assert r.status_code == 403 and ON_EN in r.text and 'data-testid="users-pw-field"' not in r.text, action
        assert len(_denied(box, f"/ops/users {action}")) == 1, action
    assert box["users"].get("vw3") is None
    assert _end(admin).status_code == 303
    assert 'data-testid="users-pw-field"' in admin.get("/ops/users").text  # after the end it is shown, once


def test_an_enrolment_code_is_not_shown_during_a_session(box: dict[str, Any]) -> None:  # noqa: F811
    box["users"].create("vw1", "viewer", PW, "vw1@hospa.test")
    admin, _ = login(box["app"])
    form = {"csrf": _csrf(admin.get("/ops/identity").text), "action": "enrol_code", "username": "vw1"}
    r = admin.post("/ops/identity", data=form)
    assert r.status_code == 200 and 'data-testid="identity-code-value"' in r.text  # off: the code, once
    _on(admin)
    for action in ("enrol_code", "reset_totp"):
        r = admin.post("/ops/identity", data={**form, "action": action, "confirm": "yes"})
        assert r.status_code == 403 and ON_EN in r.text and 'data-testid="identity-code"' not in r.text, action
        assert len(_denied(box, f"/ops/identity {action}")) == 1, action
    assert admin.get("/ops/identity").status_code == 200  # the list, and unlocking, stay open
    r = admin.post("/ops/identity", data={**form, "action": "unlock"}, follow_redirects=False)
    assert r.status_code == 303  # nobody is locked out by the switch


def test_a_confirmation_that_shows_a_secret_waits_for_the_end_of_the_session(box: dict[str, Any]) -> None:  # noqa: F811
    stw = _user(box, "stw1", "steward")
    admin, csrf = login(box["app"])
    for name in ("cr1", "cr2"):  # a protected account: a request the second person confirms
        r = admin.post("/ops/users", data={"csrf": csrf, "action": "add", "username": name, "role": "coordinator",
                                           "affiliation": "hospital", "studies": ""})  # fmt: skip
        assert 'data-testid="account-requested"' in r.text
    ids = re.findall(r'name="request" value="([^"]+)"', stw.get("/ops/accounts/requests").text)
    assert len(ids) == 2
    scsrf = _csrf(stw.get("/ops/accounts/requests").text)
    r = stw.post("/ops/accounts/requests", data={"csrf": scsrf, "request": ids[0], "decision": "confirm"})
    assert r.status_code == 200 and 'data-testid="request-secret"' in r.text  # off: the code, once
    _on(admin)
    assert stw.get("/ops/accounts/requests").status_code == 200  # the list stays open
    r = stw.post("/ops/accounts/requests", data={"csrf": scsrf, "request": ids[1], "decision": "confirm"})
    assert r.status_code == 403 and ON_EN in r.text and 'data-testid="request-secret"' not in r.text
    assert [e["detail"]["reason"] for e in _denied(box, "/ops/accounts/requests")] == ["support_session"]
    assert box["users"].get_request(ids[1])["state"] == "pending"  # nothing decided: confirmed after the session
    # the administrator still signs out and ends the session; a person still signs in
    assert _end(admin).headers["location"] == f"{PAGE}?done=end"
    _on(admin)
    assert login_crc(box)[0].get("/home").status_code == 200
    assert _end(admin).headers["location"] == f"{PAGE}?done=end"
    _on(admin)
    out = admin.post("/logout", data={"csrf": _csrf(admin.get("/account").text)}, follow_redirects=False)
    assert out.status_code == 303 and _events(box, "console.logout")


def test_a_pi_lists_no_grant_of_their_study_during_a_session(box: dict[str, Any]) -> None:  # noqa: F811
    from tests.console.test_console_app import name_pi

    _done_screen(box["backend"], _ulid(984))
    pi = _user(box, "drsato", "investigator")
    name_pi(box, "drsato")
    admin, _ = login(box["app"])
    form = {"csrf": _csrf(admin.get("/breakglass").text), "reason": "support", "note": "support call about one patient",
            "kind": "patient", "ruleset": "GZQO", "pid": A}  # fmt: skip
    assert admin.post("/breakglass", data=form, follow_redirects=False).status_code == 303
    gid = _events(box, "console.breakglass_open")[-1]["detail"]["grant"]
    r = pi.get("/breakglass")
    assert r.status_code == 200 and f'data-grant="{gid}"' in r.text  # off: the PI reads the grants of its study
    _on(admin)
    r = pi.get("/breakglass")
    assert r.status_code == 403 and f'data-grant="{gid}"' not in r.text and A[:8] not in r.text


def test_a_start_moved_to_the_clock_is_an_audit_event(box: dict[str, Any]) -> None:  # noqa: F811
    crc, _ = login_crc(box)
    _start(box)
    store = box["app"].state.support_guard.store
    sid = store.recent()[0].id
    later = (box["app"].state.helpers.clock() + timedelta(days=1)).isoformat(timespec="seconds")
    store.db.execute("UPDATE support_sessions SET started_at = ? WHERE id = ?", (later, sid))
    crc.get("/home")
    crc.get("/home")  # moved once
    moved = _events(box, "console.support_session_moved")
    assert len(moved) == 1 and moved[0]["actor"] == "console:support-session"
    assert moved[0]["detail"]["started_at_was"] == later and moved[0]["detail"]["session"] == sid
    assert moved[0]["detail"]["started_at"] == store.get(sid).started_at < later


def test_a_file_of_counts_only_stays_open_and_a_patient_level_file_does_not(box: dict[str, Any]) -> None:  # noqa: F811
    """Runbook 21 rule 3 as written: a FEAS job's aggregate files (counts only) stay downloadable; the sponsor pack
    (it asks the request right, closed) and the patient-level file do not."""
    from tests.console.test_console_app import _done_feas

    job = _done_feas(box["backend"])
    # the review of aeb978e6 item 12: the patient-level file names the coordinator as its recipient, so that it is
    # downloadable outside a session (D-369's guarded download) and the refusal below is the session's, not D-369's
    raw = next(o for o in job.outputs or [] if o.filename.endswith(".raw.json"))
    raw.recipients = ["crc@hospa.test"]
    crc, _ = login_crc(box)
    stem = f"/pilot/jobs/{job.job_id}/files/feasibility_GZQO_v1.0.0_2026-10-04"
    assert crc.get(f"{stem}.pdf").status_code == 200
    assert crc.get(f"{stem}.raw.json").status_code == 200  # the named recipient, outside a session
    _start(box)
    assert crc.get(f"{stem}.pdf").status_code == 200  # counts only
    assert crc.get(f"{stem}.json").status_code == 200  # counts only
    assert crc.get(f"/pilot/jobs/{job.job_id}/sponsor-pack.zip").status_code == 403  # closed by default
    r = crc.get(f"{stem}.raw.json")
    assert r.status_code == 403 and ON_EN in r.text  # the patient-level file: refused by the session


# ---------------------------------------------------------------------------------------------- the EDC door
def _tool_client(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str]]:
    """A tool client that records each call (the EDC's answer about one record), configured for the test."""
    from edc_backend import tools

    calls: list[tuple[str, str, str]] = []

    class Http:
        def close(self) -> None:
            pass

    class Client:
        def __init__(self, base: str, token: str, http: Any) -> None:
            self.http = http

        def capabilities(self) -> dict[str, Any]:  # the connection line of /admin/edc
            raise tools.ToolError("not asked in this test")

        def call(self, tool: str, project_id: str, *, record_id: str = "", confirm: bool = False) -> dict[str, Any]:
            calls.append((tool, project_id, record_id))
            return {"allow": True, "deidentified": True, "record": record_id}

    monkeypatch.setattr(tools, "tool_base", lambda: "https://edc.test")
    monkeypatch.setattr(tools, "tool_token", lambda: "tool-token-for-tests")
    monkeypatch.setattr(tools, "http_client", Http)
    monkeypatch.setattr(tools, "ToolClient", Client)
    return calls


def test_an_edc_tool_call_and_its_confirmation_are_refused_during_a_session(
    box: dict[str, Any],  # noqa: F811
    db_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _tool_client(monkeypatch)
    admin, csrf = login(box["app"])
    hdr = {"x-csrf": csrf}
    read = {"tool": "find_patient", "project_id": "proj-1", "record_id": "1001"}
    r = admin.post("/api/edc/tools", json=read, headers=hdr)
    assert r.status_code == 200 and r.json()["record"] == "1001" and len(calls) == 1  # off: the record's answer
    pid = admin.post("/api/edc/tools", json={"tool": "open_query", "project_id": "proj-1", "record_id": "1001"},
                     headers=hdr).json()["proposal_id"]  # fmt: skip
    _on(admin)
    for tool in ("find_patient", "draft_form", "quality_check", "open_query"):
        r = admin.post("/api/edc/tools", json={**read, "tool": tool}, headers=hdr)
        assert r.status_code == 403 and r.json()["error"] == "support.session_on", tool
        assert "1001" not in r.text, tool
    assert len(calls) == 1 and len(_denied(box, "/api/edc/tools")) == 4
    # the confirmation posted from /admin/edc's form: the page, in the person's language; the JSON call: JSON
    r = admin.post(f"/api/edc/tools/{pid}/confirm", data={"csrf": csrf})
    assert r.status_code == 403 and ON_EN in r.text and 'data-testid="problem-page"' in r.text and pid not in r.text
    _lang(admin, "ja")
    assert ON_JA in admin.post(f"/api/edc/tools/{pid}/confirm", data={"csrf": csrf}).text
    _lang(admin, "zh-TW")
    assert ON_ZH in admin.post(f"/api/edc/tools/{pid}/confirm", data={"csrf": csrf}).text
    r = admin.post(f"/api/edc/tools/{pid}/confirm", headers=hdr)
    assert r.status_code == 403 and r.json()["error"] == "support.session_on"
    assert len(calls) == 1 and _events(box, "edc.tool_confirm") == []
    assert len(_denied(box, f"/api/edc/tools/{pid}/confirm")) == 4
    # the map and the connection page stay open (``redcap.connection``): they show no record
    assert admin.get("/api/edc/map").status_code == 200 and admin.get("/admin/edc").status_code == 200
    # after the end the held write is still there to confirm, and a tool call answers again
    _lang(admin, "en")
    assert _end(admin).status_code == 303
    r = admin.post(f"/api/edc/tools/{pid}/confirm", headers=hdr)
    assert r.status_code == 200 and calls[-1] == ("open_query", "proj-1", "1001")
    assert admin.post("/api/edc/tools", json=read, headers=hdr).status_code == 200 and len(calls) == 3


def test_no_edc_sign_in_starts_during_a_session(
    box: dict[str, Any],  # noqa: F811
    db_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cb = "https://edc.example/callback"
    for name, value in (("TB_EDC_OIDC", "1"), ("TB_EDC_OIDC_ISSUER", "https://box.example"),
                        ("TB_EDC_OIDC_CLIENT_ID", "edc"), ("TB_EDC_OIDC_CLIENT_SECRET", "oidc-client-secret-for-tests"),
                        ("TB_EDC_OIDC_REDIRECT", cb)):  # fmt: skip
        monkeypatch.setenv(name, value)
    q = {"client_id": "edc", "redirect_uri": cb, "state": "s1"}
    crc, _ = login_crc(box)
    r = crc.get("/api/edc/oidc/authorize", params=q, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith(cb)  # off: any signed-in role gets a code
    admin = _start(box)
    for who, c in (("crc", crc), ("admin", admin)):
        r = c.get("/api/edc/oidc/authorize", params=q, follow_redirects=False)
        assert r.status_code == 403 and "location" not in r.headers, who
        assert ON_EN in r.text and 'data-testid="problem-page"' in r.text and cb not in r.text, who
    _lang(crc, "ja")
    assert ON_JA in crc.get("/api/edc/oidc/authorize", params=q, follow_redirects=False).text
    _lang(crc, "zh-TW")
    assert ON_ZH in crc.get("/api/edc/oidc/authorize", params=q, follow_redirects=False).text
    assert len(_denied(box, "/api/edc/oidc/authorize")) == 4
    assert _end(admin).status_code == 303
    assert crc.get("/api/edc/oidc/authorize", params=q, follow_redirects=False).status_code == 302


def test_a_sign_in_code_issued_before_the_start_is_not_redeemed_during_a_session(
    box: dict[str, Any],  # noqa: F811
    db_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    cb = "https://edc.example/callback"
    for name, value in (("TB_EDC_OIDC", "1"), ("TB_EDC_OIDC_ISSUER", "https://box.example"),
                        ("TB_EDC_OIDC_CLIENT_ID", "edc"), ("TB_EDC_OIDC_CLIENT_SECRET", "oidc-client-secret-for-tests"),
                        ("TB_EDC_OIDC_REDIRECT", cb)):  # fmt: skip
        monkeypatch.setenv(name, value)
    crc, _ = login_crc(box)
    r = crc.get("/api/edc/oidc/authorize", params={"client_id": "edc", "redirect_uri": cb, "state": "s1"},
                follow_redirects=False)  # fmt: skip
    m = re.search(r"[?&]code=([^&]+)", r.headers["location"])
    assert r.status_code == 302 and m  # issued with the session off
    form = {"grant_type": "authorization_code", "code": m.group(1), "client_id": "edc", "redirect_uri": cb,
            "client_secret": "oidc-client-secret-for-tests"}  # fmt: skip
    edc = TestClient(box["app"])  # the EDC's own server: no console session
    admin = _start(box)
    r = edc.post("/api/edc/oidc/token", data=form)
    assert r.status_code == 403 and r.json()["error"] == "support.session_on"
    assert "id_token" not in r.text and "access_token" not in r.text
    assert len(_denied(box, "/api/edc/oidc/token")) == 1
    # a wrong client is still told so (refused before the session is asked); nothing is audited for it
    assert edc.post("/api/edc/oidc/token", data={**form, "client_secret": "wrong"}).status_code == 401
    assert len(_denied(box, "/api/edc/oidc/token")) == 1
    # after the end the code, not redeemed during the session, completes the sign-in
    assert _end(admin).status_code == 303
    r = edc.post("/api/edc/oidc/token", data=form)
    assert r.status_code == 200 and r.json()["id_token"]


# ------------------------------------------------------------------------------- the walk with patient data present
# The review of aeb978e6 (H1 to H3): closing by ``permit`` rows is not enough, since pages that mix staff content with
# patient-linked content (the study home, a job's pages, a download tagged aggregate) are open rows. This walk seeds
# synthetic patients of every kind the box shows (a SCREEN list with a quote, a PI's note, a CASE sheet, a SUBMIT
# job's pid, a NAV job's draft named by a pseudonym, an ingest report whose validation message names a patient, a
# feedback entry given on a patient page), starts a session, asks every route of the router table as every column of
# the role-route walk (and every page and file of every seeded job), and asserts that no answer of any route holds a
# seeded patient-linked token. A new open route that leaks fails here. Synthetic pseudonyms only.
P_SCREEN_1, P_SCREEN_2 = "d1e2f3a4" * 4, "e5f6a7b8" * 4
P_CASE, P_SUBMIT, P_NAV, P_INGEST, P_FEEDBACK = (
    "c3c4c5c6" * 4,
    "f0f1f2f3" * 4,
    "a9b8c7d6" * 4,
    "b1b2b3b4" * 4,
    "9d8e7f6a" * 4,
)
QUOTE, NOTE, SHEET = "SYNTHQUOTE tophus left toe", "SYNTHNOTE ask uric acid", "SYNTHCASE flare of March"
CHART = "70000054"
WALK_PID = "0" * 32  # what the walk puts in a route's {pid}: no seeded token, so an echoed URL is not a leak


def _tokens() -> list[str]:
    pids = (P_SCREEN_1, P_SCREEN_2, P_CASE, P_SUBMIT, P_NAV, P_INGEST, P_FEEDBACK)
    return [*pids, *(p[:8] for p in pids), *(p[:12] for p in pids), QUOTE, NOTE, SHEET, CHART]


def _job(
    b: dict[str, Any],
    n: int,
    kind: Any,
    options: dict[str, str],
    files: list[tuple[str, bytes, str]],
    state: Any = "done",
) -> Any:
    from datetime import UTC, datetime

    from tb_common.crypto import sha256_bytes
    from tb_contracts import Job, JobOutput

    jid = _ulid(n)
    now = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
    outs = []
    for name, data, tag in files:
        key = f"outputs/{jid}/{name}"
        b["backend"].objects[key] = data
        outs.append(JobOutput(filename=name, sha256=sha256_bytes(data), minio_key=key,
                              recipients=["crc@hospa.test", "lpi@hospa.test"], tag=tag))  # type: ignore[arg-type]  # fmt: skip
    return b["backend"].add_job(Job(job_id=jid, type=kind, ruleset="GZQO", ruleset_version="1.0.0",
                                    requested_by="crc@hospa.test", received_at=now, updated_at=now, state=state,
                                    options=options, inputs=[], outputs=outs))  # fmt: skip


def _rewrite(b: dict[str, Any], job: Any, pairs: dict[str, str]) -> None:
    for o in job.outputs or []:
        data = b["backend"].objects[o.minio_key].decode("utf-8")
        for old, new in pairs.items():
            data = data.replace(old, new)
        b["backend"].objects[o.minio_key] = data.encode("utf-8")


def _seed(b: dict[str, Any]) -> list[Any]:
    """The synthetic patient-linked data of the walk; returns the seeded jobs."""
    from tests.console.test_console_app import _done_case

    screen = _done_screen(b["backend"], _ulid(991))
    _rewrite(b, screen, {"a" * 32: P_SCREEN_1, "b" * 32: P_SCREEN_2, "two flares this spring": QUOTE})
    case = _done_case(b["backend"], {"lang": "en", "pid": P_CASE})
    _rewrite(b, case, {"ab" * 16: P_CASE, "2026-03-12 acute gout flare": SHEET})
    submit = _job(
        b,
        992,
        "SUBMIT",
        {"pid": P_SUBMIT, "lang": "en"},
        [(f"submit_GZQO_{P_SUBMIT[:12]}.json", json.dumps({"pid": P_SUBMIT}).encode(), "phi")],
    )
    nav = _job(
        b,
        993,
        "NAV",
        {"pid": P_NAV, "lang": "en"},
        [(f"draft_ONC-OSI_{P_NAV[:12]}.docx", f"PK draft for {P_NAV}".encode(), "phi")],
    )
    report = {"passed": False, "errors": [f"Patient/{P_INGEST}: birthDate missing"], "snapshot": "2026-10-04"}
    ingest = _job(b, 994, "INGEST", {}, [("ingest_report_2026-10-04.json", json.dumps(report).encode(), "aggregate")])
    return [screen, case, submit, nav, ingest]


def _seed_marks(b: dict[str, Any], clients: dict[str, Any]) -> None:
    """The PI's "need info" mark with a note, made 4 days ago (its task is overdue: on "Needs you today" too)."""
    h = b["app"].state.helpers
    clock = h.clock
    h.clock = lambda: clock() - timedelta(days=4)
    try:
        _seed_marks_now(b, clients)
    finally:
        h.clock = clock


def _seed_marks_now(b: dict[str, Any], clients: dict[str, Any]) -> None:
    pi, pi_csrf, _ = clients["lpi"]
    r = pi.post(f"/studies/GZQO/patients/{P_SCREEN_1}/mark",
                data={"csrf": pi_csrf, "mark": "need_info", "note": NOTE}, follow_redirects=False)  # fmt: skip
    assert r.status_code in (200, 303), r.status_code
    crc, crc_csrf, _ = clients["crc"]
    r = crc.post("/feedback", data={"csrf": crc_csrf, "path": f"/studies/GZQO/patients/{P_FEEDBACK}",
                                    "comment": f"chart {CHART} looks wrong"}, follow_redirects=False)  # fmt: skip
    assert r.status_code in (200, 303), r.status_code


def _job_urls(jobs: list[Any]) -> list[str]:
    out = []
    for j in jobs:
        base = f"/pilot/jobs/{j.job_id}"
        out += [base, base + "/", base + "/approval", base + "/sponsor-pack.zip"]
        for o in j.outputs or []:
            out += [f"{base}/files/{o.filename}", f"{base}/view/{o.filename}"]
    return out


def _leaks(b: dict[str, Any], jobs: list[Any], clients: dict[str, Any]) -> tuple[int, list[str]]:
    """Every route of the router table as every column (GET, then the changing methods with a valid CSRF token),
    plus every page and file of every seeded job: (answers read, the seeded tokens found in an answer)."""
    from tests.console.test_role_route_matrix import CHANGING, _for, _routes

    tokens = _tokens()
    routes = _routes(b["app"])
    found: list[str] = []
    n = 0

    def fill(path: str) -> str:
        names = {"rs": "GZQO", "ruleset": "GZQO", "pid": WALK_PID, "job_id": jobs[0].job_id, "fmt": "xlsx"}
        return re.sub(r"\{(\w+)(?::\w+)?\}", lambda m: names.get(m.group(1), "1"), path)

    def check(col: str, label: str, r: Any) -> None:
        nonlocal n
        n += 1
        body = r.content.decode("utf-8", "replace") + " " + " ".join(f"{k}: {v}" for k, v in r.headers.items())
        found.extend(f"{label} [{col}] holds {t}" for t in tokens if t in body)

    for changing in (False, True):
        for col, (page, csrf, api) in clients.items():
            for method, path in routes:
                if (method in CHANGING) != changing:
                    continue
                _for(b, path)
                url = fill(path)
                if path.startswith("/api/v1/"):
                    r = api.request(method, url, json={} if changing else None, follow_redirects=False)
                else:
                    r = page.request(method, url, data={"csrf": csrf} if changing else None, follow_redirects=False)
                check(col, f"{method} {path}", r)
    _for(b, "")
    for col, (page, *_rest) in clients.items():
        for url in _job_urls(jobs):
            check(col, f"GET {url}", page.get(url, follow_redirects=False))
        for path in PLAIN_ROUTES:  # the review of 7ce188c6 L-2: routes added with add_route, outside the APIRoutes
            check(col, f"GET {path}", page.get(path, follow_redirects=False))
        check(col, "GET /link", page.get(f"/link?to=/studies/GZQO/patients/{P_SCREEN_1}", follow_redirects=False))
    return n, sorted(set(found))


# The routes the app adds with ``add_route`` (Starlette Routes, not APIRoutes, so outside the role-route walk), each
# with why it shows no patient row during a session (the review of 7ce188c6 L-2). A new one fails
# ``test_l2_every_plain_route_is_pinned`` until it is added here after a review; the seeded walk asks each.
PLAIN_ROUTES: dict[str, str] = {
    "/manifest.webmanifest": "the web app manifest: names and icons",
    "/favicon.ico": "the icon",
    "/link": "a redirect to a console path (a refused page is then refused); no read",
    "/people/candidates": "the study picker (layout.people_lists); a study's list asks a closed row",
    "/people/participants": "the study picker (layout.people_lists); a study's list asks a closed row",
}


def _plain_routes(app: Any) -> set[str]:
    from fastapi.routing import APIRoute
    from starlette.routing import Route

    return {r.path for r in app.routes if isinstance(r, Route) and not isinstance(r, APIRoute)}


def _home_today(b: dict[str, Any], value: str) -> None:
    """The flag ``layout.home_today`` (J-6, D-1225) as the administrator sets it on /ops/flags; a page reads it now."""
    from console import home_today as ht
    from console import phone
    from tb_common import flags as fl

    if fl.Flags().row(ht.FLAG) != value:
        fl.Flags(audit=b["audit"]).set(ht.FLAG, value, actor="console:admin", reason="10K-15 walk (D-1364)")
    fl.clear_cache()
    phone.clear_cache()
    phone.read_now()


@pytest.mark.parametrize("home_today", ["off", "on"])
def test_no_open_route_shows_a_seeded_patient_token_during_a_session(box: dict[str, Any], home_today: str) -> None:  # noqa: F811
    """With the flag ``layout.home_today`` off and on (on is what ships: "Needs you today" on the home)."""
    from console import phone
    from tb_common import flags as fl

    from tests.console.test_role_route_matrix import _clients, _orchestrator_routes

    _orchestrator_routes(box)
    jobs = _seed(box)
    clients = _clients(box)
    _seed_marks(box, clients)
    _home_today(box, home_today)
    try:
        # the data is there: outside a session the coordinator's pages show it (else the walk proves nothing)
        crc = clients["crc"][0]
        assert P_SCREEN_1[:8] in crc.get("/studies/GZQO/week?list=all").text
        homes = " ".join(
            c.get(u).text
            for c in (crc, clients["lpi"][0])
            for u in (("/home", "/home?today=all") if home_today == "on" else ("/home?view=studies",))
        )
        assert NOTE in homes or P_SCREEN_1[:8] in homes, "the homes show the seeded patient outside a session"
        _start(box)
        n, found = _leaks(box, jobs, clients)
    finally:
        _home_today(box, "off")  # the flag lives in the trial database: the next test of this worker finds it off
        fl.clear_cache()
        phone.clear_cache()
    assert n > 2000
    assert found == [], "\n".join(found)


# ------------------------------------------------------------------------------ the review of aeb978e6, one by one
def test_h1_the_study_home_shows_no_patient_task_or_note_during_a_session(box: dict[str, Any]) -> None:  # noqa: F811
    """H1: the study home (``/home?view=studies``, ``layout.home_today`` off) rendered the PI's ``need_info`` note
    and the candidate's pseudonym in a task link during a session. Now its patient parts are read from nothing
    (``home.load`` answers None for a patient-linked file) and the page says they are closed, in three languages."""
    from tests.console.test_role_route_matrix import _clients

    _seed(box)
    clients = _clients(box)
    _seed_marks(box, clients)
    crc = clients["crc"][0]
    before = crc.get("/home?view=studies").text
    assert NOTE in before and P_SCREEN_1[:8] in before  # the coordinator's task: the PI's note and the pseudonym
    _start(box)
    for lang, line in (("en", "Closed during the support session"), ("ja", "サポートセッション中は閉じています"),
                       ("zh-TW", "支援作業時段中關閉")):  # fmt: skip
        _lang(crc, lang)
        r = crc.get("/home?view=studies")
        assert r.status_code == 200 and line in r.text and 'data-testid="support-closed"' in r.text
        assert NOTE not in r.text and P_SCREEN_1[:8] not in r.text and P_SCREEN_2[:8] not in r.text
    r = clients["admin"][0].get("/home?view=studies")
    assert r.status_code == 200 and NOTE not in r.text and P_SCREEN_1[:8] not in r.text


def test_h2_a_submit_or_nav_job_page_is_closed_during_a_session(box: dict[str, Any]) -> None:  # noqa: F811
    """H2: only CASE job pages were closed; a SUBMIT job's page showed its pid, a NAV job's its draft named by a
    pseudonym. Now every job type outside ``JOBS_OPEN_DURING_A_SESSION`` is closed, page and files, audited."""
    _seed(box)
    admin, _ = login(box["app"])
    submit, nav = _ulid(992), _ulid(993)
    assert P_SUBMIT[:12] in admin.get(f"/pilot/jobs/{submit}").text
    assert P_NAV[:12] in admin.get(f"/pilot/jobs/{nav}").text
    _start(box)
    for jid in (submit, nav):
        for url in (f"/pilot/jobs/{jid}", f"/pilot/jobs/{jid}/approval"):
            r = admin.get(url)
            assert r.status_code == 403 and ON_EN in r.text, url
            assert P_SUBMIT[:8] not in r.text and P_NAV[:8] not in r.text and jid not in r.text
    assert [e for e in _denied(box, f"/pilot/jobs/{submit}") if e["detail"].get("why") == "support session"]
    assert admin.get(f"/pilot/jobs/{_ulid(991)}").status_code == 200  # a SCREEN job's page of counts stays open


def test_h3_a_file_tagged_aggregate_is_not_trusted_during_a_session(box: dict[str, Any]) -> None:  # noqa: F811
    """H3: the download route served an ingest report tagged ``aggregate`` whose validation message names a
    patient. During a session only the files of ``DOWNLOADS_OPEN_DURING_A_SESSION`` are served, whatever the tag."""
    from console.support_session import DOWNLOADS_OPEN_DURING_A_SESSION, download_open

    from tests.console.test_console_app import _done_feas

    _seed(box)
    feas = _done_feas(box["backend"])
    admin, _ = login(box["app"])
    url = f"/pilot/jobs/{_ulid(994)}/files/ingest_report_2026-10-04.json"
    r = admin.get(url)
    assert r.status_code == 200 and P_INGEST in r.text  # tagged aggregate, and it names a patient
    _start(box)
    for u in (url, url.replace("/files/", "/view/")):
        r = admin.get(u)
        assert r.status_code == 403 and ON_EN in r.text and P_INGEST not in r.text, u
    assert admin.get(f"/pilot/jobs/{feas.job_id}/files/feasibility_GZQO_v1.0.0_2026-10-04.json").status_code == 200
    assert all(reason for _k, _rx, reason in DOWNLOADS_OPEN_DURING_A_SESSION)  # each open kind says why
    assert not download_open("FEAS", "feasibility_GZQO_v1.0.0_2026-10-04.raw.json")
    assert not download_open("INGEST", "ingest_report_2026-10-04.json")


def test_h4_an_answer_begun_before_the_start_is_refused_when_it_ends_after_it(
    box: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H4: the switch was read only at a request's entry, so a coordinator's patient page waiting on the backend when
    the session started was still sent after the administrator saw "on". Now the start's confirmation waits until
    the answers begun before it (in this process) were sent or refused, and an answer begun before the start that
    ends after it is refused (read again at its end) before a byte of it leaves."""
    import threading

    _seed(box)
    crc, _ = login_crc(box)
    assert P_SCREEN_1[:8] in crc.get("/studies/GZQO/week?list=all").text
    admin, _ = login(box["app"])
    csrf = _csrf(admin.get(PAGE).text)
    bk = box["backend"]
    inner = bk.list_jobs
    entered, release = threading.Event(), threading.Event()
    armed = {"on": True}

    def slow(*a: Any, **k: Any) -> Any:
        if armed.pop("on", False):  # the coordinator's page, once: it waits on "the backend"
            entered.set()
            release.wait(10)
        return inner(*a, **k)

    monkeypatch.setattr(bk, "list_jobs", slow)
    got: dict[str, Any] = {}
    page = threading.Thread(target=lambda: got.update(page=crc.get("/studies/GZQO/week?list=all")))
    page.start()
    assert entered.wait(10)
    start = threading.Thread(target=lambda: got.update(start=admin.post(
        PAGE, data={"csrf": csrf, "ticket": "", "confirm": "yes"}, follow_redirects=False)))  # fmt: skip
    start.start()
    start.join(0.5)
    assert start.is_alive(), "the confirmation waits for the answer begun before the start"
    release.set()
    page.join(10)
    start.join(20)
    r = got["page"]
    assert r.status_code == 403 and ON_EN in r.text and P_SCREEN_1[:8] not in r.text
    assert got["start"].headers["location"] == f"{PAGE}?done=start"
    shown = admin.get(f"{PAGE}?done=start").text
    assert 'data-testid="support-done"' in shown and 'data-testid="support-done-fine"' in shown


def test_h4_a_start_that_cannot_wait_says_so(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from console import support_session

    monkeypatch.setattr(support_session, "DRAIN_S", 0.0)
    guard = box["app"].state.support_guard
    n = guard._enter()  # an answer begun before the start, still being sent
    try:
        admin, _ = login(box["app"])
        r = admin.post(PAGE, data={"csrf": _csrf(admin.get(PAGE).text), "confirm": "yes"}, follow_redirects=False)
        assert r.headers["location"] == f"{PAGE}?done=start&wait=1"
        shown = admin.get(r.headers["location"]).text
        assert 'data-testid="support-done-wait"' in shown
        # L-3 of the review of 7ce188c6: not also "every page asked before the start was finished or refused"
        assert "finished or refused before this line" not in shown and "refused at its end" in shown
    finally:
        guard._leave(n)


def test_item6_a_steward_s_batch_reason_is_withheld_during_a_session(
    box: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Item 6: ``dataops.view`` stays open, and a batch step's reason is a steward's free text ("Duplicate chart
    70000054"). During a session every reason is withheld on the page and in the API; states, who and when stay."""
    from console import dataops_page

    step = {"seq": 1, "old": "landed", "new": "rejected", "who": "stw", "at": "2026-10-04T09:00:00+00:00",
            "reason": f"Duplicate chart {CHART}", "audit_event": "dataops.rejected"}  # fmt: skip
    assert dataops_page.steps_shown([step])[0]["reason"] == f"Duplicate chart {CHART}"
    token = authz.support_session_begin(True)
    try:
        shown = dataops_page.steps_shown([step])
    finally:
        authz.support_session_end(token)
    assert shown[0]["reason"] is None and shown[0]["reason_closed"] and shown[0]["new"] == "rejected"
    assert CHART not in json.dumps(shown)


def test_item7_a_start_whose_end_underflows_is_closed_and_can_be_ended(box: dict[str, Any]) -> None:  # noqa: F811
    """Item 7: ``0001-01-01T00:00:00+14:00`` parses, but its UTC time underflows: the automatic check failed and the
    end by hand rolled back. Now such a start is a damaged one: closed until ended by hand, and the end works."""
    st = SupportSessionStore()
    st.db.execute("INSERT INTO support_sessions (started_by, started_at, ticket) VALUES (?, ?, ?)",
                  ("admin", "0001-01-01T00:00:00+14:00", ""))  # fmt: skip
    st.close()
    crc, _ = login_crc(box)
    r = crc.get("/studies/GZQO/candidates")
    assert r.status_code == 403
    admin, _ = login(box["app"])
    assert _end(admin).headers["location"] == f"{PAGE}?done=end"
    assert ON_EN not in crc.get("/studies/GZQO/candidates").text


def test_item8_a_signed_out_request_for_a_closed_job_is_sent_to_sign_in(box: dict[str, Any]) -> None:  # noqa: F811
    """Item 8: the job guard ran before sign-in, so a signed-out request learnt a job's type. Now a signed-out
    request gets the route's own sign-in answer for every job, and a refusal is audited."""
    from fastapi.testclient import TestClient

    from tests.console.test_console_app import _done_case

    case = _done_case(box["backend"])
    _start(box)
    anon = TestClient(box["app"])
    for jid in (case.job_id, _done_screen(box["backend"], _ulid(991)).job_id):
        r = anon.get(f"/pilot/jobs/{jid}", follow_redirects=False)
        assert r.status_code in (303, 401) and r.status_code != 403, (jid, r.status_code)
    assert not _denied(box, f"/pilot/jobs/{case.job_id}")
    crc, _ = login_crc(box)
    assert crc.get(f"/pilot/jobs/{case.job_id}").status_code == 403
    assert _denied(box, f"/pilot/jobs/{case.job_id}")


def test_item9_the_confirmation_follows_the_state_not_the_url(box: dict[str, Any]) -> None:  # noqa: F811
    admin = _start(box)
    assert 'data-testid="support-done"' in admin.get(f"{PAGE}?done=start").text
    _shift(box, authz.SUPPORT_SESSION_MINUTES + 1)
    page = admin.get(f"{PAGE}?done=start").text  # the old success URL, after the 2 hours
    assert 'data-testid="support-done"' not in page and 'data-testid="support-live"' not in page
    assert 'data-testid="support-done"' in admin.get(f"{PAGE}?done=end").text  # none is open: "ended" is true


def test_item10_a_one_time_password_unread_for_ten_minutes_is_gone(
    box: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time as _time

    """Item 10: a one-time password held back by a session was shown after its 10 minutes, since its age was
    checked only when another secret was kept. Now its age is checked when it is read too."""
    admin, csrf = login(box["app"])
    add = {"csrf": csrf, "action": "add", "role": "viewer", "affiliation": "hospital", "studies": ""}
    assert admin.post("/ops/users", data={**add, "username": "vw9"}, follow_redirects=False).status_code == 303
    _on(admin)
    assert 'data-testid="users-pw-field"' not in admin.get("/ops/users").text  # held back while support watches
    assert _end(admin).status_code == 303
    later = _time.monotonic() + 1200  # 20 minutes later, nothing else kept since
    monkeypatch.setattr(_time, "monotonic", lambda: later)
    page = admin.get("/ops/users").text
    assert 'data-testid="users-pw-field"' not in page and "vw9" in page


def test_item11_cancel_is_closed_during_a_session_like_the_prepare_it_signs(box: dict[str, Any]) -> None:  # noqa: F811
    """Item 11: the cancellation's confirmation opened during a session, and its submit was refused (it signs
    ``request.prepare``, closed), leaving the job running. Now the cancel is refused before its confirmation, audited,
    and the mail command's row ``command.CANCEL`` is closed too."""
    assert "command.CANCEL" not in SUPPORT_SESSION_OPEN and "request.prepare" not in SUPPORT_SESSION_OPEN
    job = _job(box, 995, "FEAS", {}, [], state="running")
    admin, csrf = login(box["app"])
    url = f"/admin/jobs/{job.job_id}/cancel"
    assert admin.post(url, data={"csrf": csrf}).status_code == 200  # outside a session: the confirmation
    _on(admin)
    for data in ({"csrf": csrf}, {"csrf": csrf, "confirm": "yes"}):
        r = admin.post(url, data=data)
        assert r.status_code == 403 and ON_EN in r.text and job.job_id not in r.text
    assert len([e for e in _denied(box, url) if e["detail"].get("why") == "support session"]) == 2


# ------------------------------------------------------------------------------ the review of 7ce188c6
@pytest.mark.parametrize("session", [False, True])
def test_m1_the_steward_is_told_of_an_opened_account_during_a_session(tmp_path: Any, session: bool) -> None:
    """M-1: ``/enrol`` stays open during a session, and its account notice is one of the mails that still go; but its
    recipients were picked with ``permit(.., "breakglass.review")``, which the session refuses, so the steward was
    not told (``sent: 0``). The recipients are now named by the matrix whatever the mark (``authz.role_holds``)."""
    from tests.console.test_console_app import ADMIN_PW
    from tests.console.test_no_one_holds_both_factors import (
        CRC_PW,
        STEWARD_PW,
        _add,
        _box,
        _redeem,
        _request_ids,
        _requests,
        _signin,
    )

    app, _users, audit_dir, clock = _box(tmp_path, steward=True)
    stew, scsrf = _signin(app, "stew", STEWARD_PW)
    admin, csrf = _signin(app, "admin", ADMIN_PW)
    assert _add(admin, csrf, "shadow", "coordinator").status_code == 200
    (rid,) = _request_ids(_requests(stew))
    r = stew.post("/ops/accounts/requests", data={"csrf": scsrf, "request": rid, "decision": "confirm"})
    m = (re.search(r'data-testid="request-secret"[^>]*value="([^"]+)"', r.text)
         or re.search(r'data-testid="enrol-code-value"[^>]*value="([a-z0-9-]+)"', r.text)
         or re.search(r'value="([a-z0-9-]+)" data-testid="[a-z-]*code[a-z-]*"', r.text))  # fmt: skip
    assert m
    if session:
        r = admin.post(PAGE, data={"csrf": _csrf(admin.get(PAGE).text), "ticket": "SUP-1", "confirm": "yes"},
                       follow_redirects=False)  # fmt: skip
        assert "done=start" in r.headers["location"]
    before = len(app.state.test_backend.notices)
    clock.tick(minutes=5)
    assert _redeem(app, "shadow", m.group(1), CRC_PW).status_code == 303
    told = sorted({a for _k, to, _s, _b in app.state.test_backend.notices[before:] for a in to})
    assert told == ["stew@hospa.test"]
    events = [json.loads(line) for f in sorted(Path(audit_dir).glob("*")) for line in f.read_text().splitlines()
              if line and json.loads(line).get("event") == "console.account_notice"]  # fmt: skip
    assert events[-1]["detail"]["sent"] == 1


def test_l2_every_plain_route_is_pinned(box: dict[str, Any]) -> None:  # noqa: F811
    """L-2: routes added with ``add_route`` were outside the pin test and the walk; now they are pinned and walked."""
    assert _plain_routes(box["app"]) == set(PLAIN_ROUTES)
    assert all(PLAIN_ROUTES.values())


def _refusal_events(b: dict[str, Any]) -> int:
    n = 0
    for f in sorted((b["dir"] / "audit").glob("*")):
        for line in f.read_text().splitlines():
            ev = json.loads(line).get("event", "") if line else ""
            n += ev == "console.denied" or ev.endswith("_refused")
    return n


def test_m2_every_refusal_during_a_session_is_audited_once(box: dict[str, Any]) -> None:  # noqa: F811
    """M-2: 5 of 86 refusals during a session wrote no ``console.denied`` (the patient page and the study week among
    them). Now the middleware writes it when the handler wrote none: over the whole route table (GET, pages and
    API), as the coordinator, the PI and the administrator, every refusal is exactly one refusal event."""
    from tests.console.test_role_route_matrix import _clients, _routes

    _seed(box)
    clients = _clients(box)
    _start(box)
    refused = 0
    wrong: list[str] = []
    for col in ("crc", "lpi", "admin"):
        page, _c, api = clients[col]
        for method, path in _routes(box["app"]):
            if method != "GET":
                continue
            url = re.sub(r"\{(\w+)(?::\w+)?\}", lambda m: {"rs": "GZQO", "ruleset": "GZQO", "pid": P_SCREEN_1,
                         "job_id": _ulid(992), "fmt": "xlsx"}.get(m.group(1), "1"), path)  # fmt: skip
            before = _refusal_events(box)
            r = (api if path.startswith("/api/v1/") else page).get(url, follow_redirects=False)
            if r.status_code == 403:
                refused += 1
                if _refusal_events(box) - before != 1:
                    wrong.append(f"{col} {path}: {_refusal_events(box) - before}")
    assert refused > 150 and wrong == []


def test_l1_an_open_job_page_shows_counts_only_during_a_session(box: dict[str, Any]) -> None:  # noqa: F811
    """L-1: an open SCREEN job's page showed its error text and request line (free text that can name a patient),
    its mail thread and audit rows during a session. Now it shows state, type and counts only, and says so."""
    from tb_contracts import JobError

    screen = _done_screen(box["backend"], _ulid(996))
    failed = screen.model_copy(update={"job_id": _ulid(997), "state": "failed", "options": {"note": "ZZOPTMARK"},
                                       "error": JobError(step="match", message=f"Patient/{P_INGEST} birthDate")})  # fmt: skip
    box["backend"].add_job(failed)
    crc, _ = login_crc(box)
    url = f"/pilot/jobs/{failed.job_id}"
    before = crc.get(url).text
    assert P_INGEST in before and "ZZOPTMARK" in before
    _start(box)
    for lang, line in (("en", "Closed during the support session"), ("ja", "サポートセッション中は閉じています"),
                       ("zh-TW", "支援作業時段中關閉")):  # fmt: skip
        _lang(crc, lang)
        r = crc.get(url)
        assert r.status_code == 200 and line in r.text, lang
        assert P_INGEST not in r.text and "ZZOPTMARK" not in r.text and 'data-testid="thread"' not in r.text
