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
    assert r.headers["location"] == f"{PAGE}?err=support.err.confirm"  # not ticked: nothing starts
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
    assert r.headers["location"] == f"{PAGE}?err=support.err.ticket"
    for name in ("TaroYamada", "Yamada-Taro", "T.Yamada"):  # the shape of a number: letters alone are refused
        r = admin.post(PAGE, data={"csrf": _csrf(admin.get(PAGE).text), "ticket": name, "confirm": "yes"},
                       follow_redirects=False)  # fmt: skip
        assert r.headers["location"] == f"{PAGE}?err=support.err.ticket", name
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
# ``/admin/accounts``); D-1364 names them. Regenerated from this walk, 2026-11-19: 86 routes.
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
    ("POST", "/admin/jobs/{job_id}/cancel"): "admin",
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
    # 2b. exactly the reviewed list stays open, to exactly its columns: a new route open during a session fails here
    got = {k: {col for col, v in during[k].items() if v == "Y"} for k in opened}
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
    crc, _ = login_crc(box)
    stem = f"/pilot/jobs/{job.job_id}/files/feasibility_GZQO_v1.0.0_2026-10-04"
    assert crc.get(f"{stem}.pdf").status_code == 200
    _start(box)
    assert crc.get(f"{stem}.pdf").status_code == 200  # counts only
    assert crc.get(f"/pilot/jobs/{job.job_id}/sponsor-pack.zip").status_code == 403  # asks a closed row
    assert crc.get(f"{stem}.raw.json").status_code in (403, 404)  # the patient-level file: not given


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
