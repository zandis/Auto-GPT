"""V-11: twice has one effect (console routes and the back button).

The same request is sent twice in a row, with the same session and the same CSRF token, through the real route of
the in-process console. Then the state is read: the route's own rows, the mails the stand-in orchestrator was asked
to send, the audit events, and the second answer. The back button is a replay of an earlier page's form after the
state has moved on. Two people at once are threads against the in-process app (each its own client).

Counts go to ``twice.json`` when ``TB_TWICE_OUT`` names a folder (the findings page's folder); a CI run writes
nothing. All data is synthetic."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tests.console.test_amendment_rescreen import _screen
from tests.console.test_console_app import ADMIN_PW, box, login, name_pi
from tests.console.test_lifecycle_mediums_pages import A, B, _row
from tests.console.test_lifecycle_pages import PW, _save, lb
from tests.console.test_no_one_holds_both_factors import STEWARD_PW, _add, _box, _request_ids, _requests, _signin
from tests.console.test_team_pages import _events

__all__ = ["box", "lb"]
STUDY = "GZQO"


def record(case: str, row: dict[str, Any]) -> None:
    """Add one case's counts to ``$TB_TWICE_OUT/twice.json`` (only when the variable is set)."""
    out = os.environ.get("TB_TWICE_OUT")
    if not out:
        return
    path = Path(out) / "twice.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    data[case] = row
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")


def _subject(b: dict[str, Any], no: str) -> dict[str, Any]:
    out: dict[str, Any] = b["oc"].get(f"/studies/{STUDY}/subjects/{no}").json()
    return out


def _steps(b: dict[str, Any], no: str) -> list[tuple[Any, Any]]:
    return [(s["old"], s["new"]) for s in _subject(b, no)["steps"]]


def _all_events(b: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for f in sorted((b["dir"] / "audit").glob("*.jsonl")):
        out += [json.loads(line)["event"] for line in f.read_text().splitlines() if line]
    return out


def _crc(b: dict[str, Any]) -> tuple[Any, str]:
    c, csrf = login(b["app"], "crc", PW)
    c.post(f"/studies/{STUDY}/forms/builtin", data={"csrf": csrf})
    c.get(f"/studies/{STUDY}/subjects")  # the screening numbers become participants
    return c, csrf


def _enrolled(b: dict[str, Any]) -> tuple[Any, str, str]:
    no = b["nos"][0]
    c, csrf = _crc(b)
    c.post(f"/studies/{STUDY}/subjects/{no}/step", data={"csrf": csrf, "to": "approached", "on_day": "2026-11-02"})
    _save(c, csrf, no, "tb_consent", {"ic_date": "2026-11-03", "ic_version": "v1", "ic_copy": "1"})
    _save(c, csrf, no, "tb_enrolment", {"en_date": "2026-11-04", "en_eligible": "1"}, back="subject")
    assert _subject(b, no)["subject"]["state"] == "enrolled"
    return c, csrf, no


# ---------------------------------------------------------------------------------------------- double submit
def test_a_lifecycle_step_sent_twice_is_one_step_and_a_plain_refusal(lb: dict[str, Any]) -> None:
    no = lb["nos"][0]
    c, csrf = _crc(lb)
    form = {"csrf": csrf, "to": "approached", "on_day": "2026-11-02"}
    before = len(_steps(lb, no))
    r1 = c.post(f"/studies/{STUDY}/subjects/{no}/step", data=form, follow_redirects=False)
    r2 = c.post(f"/studies/{STUDY}/subjects/{no}/step", data=form, follow_redirects=False)
    after = len(_steps(lb, no))
    ev = _all_events(lb).count("console.life_step")
    record("step_twice", {"route": "POST /studies/{rs}/subjects/{record}/step", "status": [r1.status_code,
           r2.status_code], "steps_added": after - before, "audit_life_step": ev})  # fmt: skip
    assert r1.status_code == 303 and r2.status_code == 409
    assert "already at this step" in r2.text
    assert after - before == 1 and ev == 1


@pytest.mark.parametrize("form,values", [
    ("tb_consent", {"ic_date": "2026-11-03", "ic_version": "v1", "ic_copy": "1"}),
])  # fmt: skip
def test_the_consent_form_saved_twice_is_one_consent(lb: dict[str, Any], form: str, values: dict[str, str]) -> None:
    no = lb["nos"][0]
    c, csrf = _crc(lb)
    c.post(f"/studies/{STUDY}/subjects/{no}/step", data={"csrf": csrf, "to": "approached", "on_day": "2026-11-02"})
    r1 = _save(c, csrf, no, form, values)
    n1 = len(lb["dc"].history(STUDY, no))
    r2 = _save(c, csrf, no, form, values)
    subj = _subject(lb, no)
    consents = subj["subject"]["consent"]["consents"]
    entries = [e["detail"] for e in _events(lb, "console.data_entry")]
    record("consent_twice", {"route": "POST /studies/{rs}/entry (tb_consent)", "status": [r1.status_code,
           r2.status_code], "consents": len(consents), "values_added_by_second": len(lb["dc"].history(STUDY, no)) - n1,
           "audit_data_entry": len(entries), "second_changed": entries[-1].get("changed")})  # fmt: skip
    assert len(consents) == 1 and len(lb["dc"].history(STUDY, no)) == n1
    assert [s for s in _steps(lb, no) if s[1] == "consented"] == [("approached", "consented")]


def test_the_enrolment_form_saved_twice_is_one_enrolment(lb: dict[str, Any]) -> None:
    c, csrf, no = _enrolled(lb)
    n = len(lb["dc"].history(STUDY, no))
    r2 = _save(c, csrf, no, "tb_enrolment", {"en_date": "2026-11-04", "en_eligible": "1"}, back="subject")
    entries = [e["detail"] for e in _events(lb, "console.data_entry")]
    record("enrolment_twice", {"route": "POST /studies/{rs}/entry (tb_enrolment)", "status_second": r2.status_code,
           "enrolled_steps": sum(1 for s in _steps(lb, no) if s[1] == "enrolled"),
           "values_added_by_second": len(lb["dc"].history(STUDY, no)) - n, "second_changed": entries[-1]["changed"],
           "second_says_saved": 'data-testid="life-entry-saved"' in r2.text})  # fmt: skip
    assert sum(1 for s in _steps(lb, no) if s[1] == "enrolled") == 1
    assert len(lb["dc"].history(STUDY, no)) == n and entries[-1]["changed"] == 0


def _withdraw(c: Any, csrf: str, no: str) -> Any:
    return _save(c, csrf, no, "tb_withdrawal", {"wd_date": "2026-11-11", "wd_reason": "3", "wd_data_use": "1"},
                 back="subject")  # fmt: skip


def test_the_withdrawal_form_saved_twice_is_one_withdrawal(lb: dict[str, Any]) -> None:
    c, csrf, no = _enrolled(lb)
    _withdraw(c, csrf, no)
    n = len(lb["dc"].history(STUDY, no))
    r2 = _withdraw(c, csrf, no)
    record("withdrawal_twice", {"route": "POST /studies/{rs}/entry (tb_withdrawal)", "status_second": r2.status_code,
           "withdrawn_steps": sum(1 for s in _steps(lb, no) if s[1] == "withdrawn"),
           "values_added_by_second": len(lb["dc"].history(STUDY, no)) - n,
           "second_says_saved": 'data-testid="life-entry-saved"' in r2.text})  # fmt: skip
    assert sum(1 for s in _steps(lb, no) if s[1] == "withdrawn") == 1 and len(lb["dc"].history(STUDY, no)) == n


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="V11-02: a second identical withdrawal save answers 'Saved' though nothing was saved",
)
def test_the_second_withdrawal_save_says_that_nothing_changed(lb: dict[str, Any]) -> None:
    c, csrf, no = _enrolled(lb)
    _withdraw(c, csrf, no)
    r2 = _withdraw(c, csrf, no)
    assert r2.status_code < 500
    told = re.search(r"already|no change|nothing (was )?changed|not changed", r2.text, re.I)
    assert 'data-testid="life-entry-saved"' not in r2.text or told


def _marked(b: dict[str, Any]) -> tuple[Any, str]:
    """A and B on the weekly list, each with a clinic visit this week; A gets the first Approach (the PI's week page,
    the real route), B stays open for the investigator's Monday mail."""
    rows = [{**_row(p), "next_appointment": "2026-11-11T09:00:00+08:00"} for p in (A, B)]
    _screen(b, 9901, "3.0.0", rows, 0)
    name_pi(b, "pi")
    pi, _ = login(b["app"], "pi", PW)
    week = pi.get(f"/studies/{STUDY}/week").text
    m = re.search(r'name="csrf" value="([^"]+)"', week)
    assert m
    r = pi.post(f"/studies/{STUDY}/patients/{A}/mark", data={"csrf": m.group(1), "mark": "approach"},
                follow_redirects=False)  # fmt: skip
    assert r.status_code == 303, r.text[:300]
    week = pi.get(f"/studies/{STUDY}/week").text
    m = re.search(r'name="csrf" value="([^"]+)"', week)
    assert m
    return pi, m.group(1)


def test_approach_marked_twice_counts(lb: dict[str, Any]) -> None:
    """Measures only (the outcome is held by the xfail below): what a double Approach leaves."""
    pi, csrf = _marked(lb)
    store, team = lb["app"].state.helpers.store, lb["app"].state.helpers.team
    r2 = pi.post(f"/studies/{STUDY}/patients/{A}/mark", data={"csrf": csrf, "mark": "approach"},
                 follow_redirects=False)  # fmt: skip
    ev = _all_events(lb)
    record("approach_twice", {"route": "POST /studies/{rs}/patients/{pid}/mark (approach)",
           "status_second": r2.status_code, "mark_rows": len(store.mark_history(STUDY, A)),
           "audit_pi_mark": ev.count("console.pi_mark"), "audit_approach_override": ev.count("console.approach_override"),
           "override_records": len(team.overrides(STUDY)), "notices": len(lb["backend"].notices)})  # fmt: skip
    assert r2.status_code == 303


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="V11-01: a second identical Approach writes a second mark, override record and audit event",
)
def test_approach_marked_twice_is_one_mark(lb: dict[str, Any]) -> None:
    pi, csrf = _marked(lb)
    store, team = lb["app"].state.helpers.store, lb["app"].state.helpers.team
    pi.post(f"/studies/{STUDY}/patients/{A}/mark", data={"csrf": csrf, "mark": "approach"}, follow_redirects=False)
    ev = _all_events(lb)
    assert len(store.mark_history(STUDY, A)) == 1
    assert len(team.overrides(STUDY)) <= 1
    assert ev.count("console.approach_override") <= 1


def test_a_contact_outcome_sent_twice_is_one_outcome(lb: dict[str, Any]) -> None:
    _marked(lb)
    crc, csrf = login(lb["app"], "crc", PW)
    store = lb["app"].state.helpers.store
    form = {"csrf": csrf, "outcome": "reached_booked"}
    r1 = crc.post(f"/studies/{STUDY}/patients/{A}/outcome", data=form, follow_redirects=False)
    r2 = crc.post(f"/studies/{STUDY}/patients/{A}/outcome", data=form, follow_redirects=False)
    ev = _all_events(lb)
    record("outcome_twice", {"route": "POST /studies/{rs}/patients/{pid}/outcome", "status": [r1.status_code,
           r2.status_code], "outcomes": len(store.outcomes(STUDY, A)), "audit_contact_outcome":
           ev.count("console.contact_outcome"), "audit_refused": ev.count("console.refused")})  # fmt: skip
    assert r1.status_code == 303 and r2.status_code == 409 and r2.status_code < 500
    assert len(store.outcomes(STUDY, A)) == 1 and ev.count("console.contact_outcome") == 1


def test_an_account_added_twice_is_one_account(box: dict[str, Any]) -> None:
    c, csrf = login(box["app"])
    form = {"csrf": csrf, "action": "add", "username": "Nurse.Twice", "role": "viewer", "mailbox": "tw@hospa.test"}
    r1 = c.post("/ops/users", data=form, follow_redirects=False)
    r2 = c.post("/ops/users", data=form, follow_redirects=False)
    ev = [e for e in _events(box, "console.user")]
    record("account_add_twice", {"route": "POST /ops/users (add)", "status": [r1.status_code, r2.status_code],
           "accounts": int(box["users"].get("nurse.twice") is not None), "audit_console_user": len(ev)})  # fmt: skip
    assert r1.status_code == 303 and r2.status_code == 400 and "exists" in r2.text
    assert len(ev) == 1


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="V11-04: a second disable of a disabled account writes a second 'disable' audit event",
)
def test_an_account_disabled_twice_is_one_disable(box: dict[str, Any]) -> None:
    c, csrf = login(box["app"])
    form = {"csrf": csrf, "action": "disable", "username": "viewer", "confirm": "yes"}
    c.post("/ops/users", data=form, follow_redirects=False)
    r2 = c.post("/ops/users", data=form, follow_redirects=False)
    assert r2.status_code < 500
    assert len(_events(box, "console.user")) == 1


def _n1_ready(b: dict[str, Any]) -> list[Any]:
    """The investigator with a weekly list (the Approach above) turns the morning mail on: N1 carries patient rows."""
    pi, csrf = _marked(b)
    r = pi.post("/settings/notices", data={"csrf": csrf, "enabled": "1", "digest_time": "07:30", "lang": "en"},
                follow_redirects=False)  # fmt: skip
    assert r.status_code == 303
    store = b["app"].state.helpers.store
    if store.study_state(STUDY).state != "open":  # D-386: only a study in care is mailed (seeded, as a steward would)
        store.set_study_state(STUDY, "open", "V-11 seed", "stw-setup", "2026-11-08T01:00:00+00:00")
    b["clock"]["now"] = datetime(2026, 11, 9, 1, 0, tzinfo=UTC)  # a Monday: the week's N1 goes without a clinic id
    notices: list[Any] = b["backend"].notices
    return notices


def test_the_morning_notices_sent_twice_the_same_day_are_one_mail(lb: dict[str, Any]) -> None:
    notices = _n1_ready(lb)
    c, csrf = login(lb["app"])
    r1 = c.post("/ops/notices", data={"csrf": csrf})
    n1 = len(notices)
    r2 = c.post("/ops/notices", data={"csrf": csrf})
    n2 = len(notices)
    record("notices_twice", {"route": "POST /ops/notices", "status": [r1.status_code, r2.status_code],
           "kinds": [n[0] for n in notices], "mails_after_first": n1, "mails_after_second": n2})  # fmt: skip
    assert n1 >= 1 and "N1" in [n[0] for n in notices] and n2 == n1 and r2.status_code == 200


def _race_notices(b: dict[str, Any]) -> list[Any]:
    notices = _n1_ready(b)
    slow = b["backend"].send_notice

    def send_notice(*a: Any) -> str:  # the stand-in MTA takes a moment, as a real one does
        time.sleep(0.3)
        return str(slow(*a))

    b["backend"].send_notice = send_notice
    clients = [login(b["app"]) for _ in range(2)]
    go = threading.Barrier(2)
    codes: list[int] = []

    def one(c: Any, csrf: str) -> None:
        go.wait()
        codes.append(c.post("/ops/notices", data={"csrf": csrf}).status_code)

    ts = [threading.Thread(target=one, args=cl) for cl in clients]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(codes) == 2 and all(code < 500 for code in codes)
    return notices


def test_two_send_now_at_once_counts(lb: dict[str, Any]) -> None:
    """Measures only (the outcome is held by the xfail below)."""
    notices = _race_notices(lb)
    record("notices_race", {"route": "POST /ops/notices, two threads at once", "kinds": [n[0] for n in notices],
           "mails": len(notices), "audit_console_notice": _all_events(lb).count("console.notice")})  # fmt: skip


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="V11-03: two 'send now' at once send each person's patient digest twice (check, send, log)",
)
def test_two_send_now_at_once_send_one_mail(lb: dict[str, Any]) -> None:
    notices = _race_notices(lb)
    if not notices:  # not an AssertionError: a fixture that sends nothing must not satisfy the xfail
        raise RuntimeError("the fixture sent no mail at all: not a measure of the race")
    assert len(notices) == len({(n[0], tuple(n[1])) for n in notices})  # each person's digest once


# ---------------------------------------------------------------------------------------------- two approvers
def test_two_confirmers_at_once_open_one_account(tmp_path: Path) -> None:
    """D-719 (c): a protected account waits for a second person. Two second persons confirm at once (threads against
    the in-process app), ten times: one account, one confirmation, the other told plainly."""
    app, users, _audit, _clock = _box(tmp_path, steward=True)
    users.create("admin2", "admin", ADMIN_PW + "x", "admin2@hospa.test")
    admin, csrf = _signin(app, "admin", ADMIN_PW)
    confirmers = [_signin(app, "stew", STEWARD_PW), _signin(app, "admin2", ADMIN_PW + "x")]
    rows = []
    for i in range(10):
        name = f"shadow{i}"
        _add(admin, csrf, name, "coordinator")
        rid = [r for r in _request_ids(_requests(admin))][-1]
        go = threading.Barrier(2)
        codes: list[int] = []
        texts: list[str] = []

        def one(
            c: Any,
            t: str,
            rid: str = rid,
            go: threading.Barrier = go,
            codes: list[int] = codes,
            texts: list[str] = texts,
        ) -> None:
            go.wait()
            r = c.post("/ops/accounts/requests", data={"csrf": t, "request": rid, "decision": "confirm"})
            codes.append(r.status_code)
            texts.append(r.text)

        ts = [threading.Thread(target=one, args=cl) for cl in confirmers]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        rows.append(sorted(codes))
        assert sorted(codes) == [200, 409], codes
        assert any("no longer waiting" in t for t in texts)
        assert users.get(name) is not None
    confirmed = [e for e in _audit_events(tmp_path) if e == "console.account_confirmed"]
    # the same person from two tabs is never the second person of their own request
    _add(admin, csrf, "shadow-own", "coordinator")
    rid = _request_ids(_requests(admin))[-1]
    tabs = [_signin(app, "admin", ADMIN_PW) for _ in range(2)]
    own = [c.post("/ops/accounts/requests", data={"csrf": t, "request": rid, "decision": "confirm"}).status_code
           for c, t in tabs]  # fmt: skip
    record("two_confirmers", {"route": "POST /ops/accounts/requests", "repetitions": 10, "codes": rows,
           "audit_confirmed": len(confirmed), "own_two_tabs": own})  # fmt: skip
    assert len(confirmed) == 10 and own == [403, 403] and users.get("shadow-own") is None


def _audit_events(tmp_path: Path) -> list[str]:
    out: list[str] = []
    for f in sorted(tmp_path.rglob("*.jsonl")):
        for line in f.read_text().splitlines():
            if line.startswith("{"):
                out.append(str(json.loads(line).get("event")))
    return out


# ---------------------------------------------------------------------------------------------- the back button
def test_the_back_button_after_a_withdrawal_changes_nothing(lb: dict[str, Any]) -> None:
    """The earlier pages' forms, replayed with their old token after the withdrawal: the enrolment form, a lifecycle
    step and a contact outcome. Each is refused and the state is unchanged."""
    c, csrf, no = _enrolled(lb)
    _withdraw(c, csrf, no)
    steps, values = _steps(lb, no), len(lb["dc"].history(STUDY, no))
    r_form = _save(c, csrf, no, "tb_enrolment", {"en_date": "2026-11-12", "en_eligible": "1"}, back="subject")
    r_step = c.post(f"/studies/{STUDY}/subjects/{no}/step", data={"csrf": csrf, "to": "enrolled",
                    "on_day": "2026-11-12"}, follow_redirects=False)  # fmt: skip
    m = re.search(r'data-testid="[^"]*refused[^"]*"[^>]*>([^<]{0,200})', r_form.text)
    record("back_after_withdrawal", {"routes": ["POST /studies/{rs}/entry (tb_enrolment)",
           "POST /studies/{rs}/subjects/{record}/step"], "status": [r_form.status_code, r_step.status_code],
           "state": _subject(lb, no)["subject"]["state"], "steps_added": len(_steps(lb, no)) - len(steps),
           "values_added": len(lb["dc"].history(STUDY, no)) - values,
           "form_message": m.group(1).strip() if m else ""})  # fmt: skip
    assert _subject(lb, no)["subject"]["state"] == "withdrawn"
    assert _steps(lb, no) == steps and len(lb["dc"].history(STUDY, no)) == values
    assert r_step.status_code == 409 and r_form.status_code < 500 and m


def test_the_changing_routes_of_the_live_app(box: dict[str, Any]) -> None:
    """Every non-GET route of the live console app object: the list the findings page splits into driven twice and
    not driven."""
    routes = sorted({f"{m} {r.path}" for r in box["app"].routes for m in (getattr(r, "methods", None) or ())
                     if m not in ("GET", "HEAD", "OPTIONS")})  # fmt: skip
    record("inventory", {"place": "console.app.create_app().routes", "routes": routes})
    assert "POST /ops/users" in routes and "POST /studies/{rs}/subjects/{record}/step" in routes


def test_the_back_button_after_a_declined_contact_counts(lb: dict[str, Any]) -> None:
    """Measures only: after "reached, declined", the earlier outcome form ("reached, booked") replayed. No written
    rule says a declined contact is final, so this records what happens and asserts no 500."""
    _marked(lb)
    crc, csrf = login(lb["app"], "crc", PW)
    store = lb["app"].state.helpers.store
    crc.post(f"/studies/{STUDY}/patients/{A}/outcome", data={"csrf": csrf, "outcome": "reached_declined"})
    n = len(store.outcomes(STUDY, A))
    r = crc.post(f"/studies/{STUDY}/patients/{A}/outcome", data={"csrf": csrf, "outcome": "reached_booked"},
                 follow_redirects=False)  # fmt: skip
    record("back_after_declined", {"route": "POST /studies/{rs}/patients/{pid}/outcome", "status": r.status_code,
           "outcomes_added": len(store.outcomes(STUDY, A)) - n})  # fmt: skip
    assert r.status_code < 500


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="V11-05: the enrolment form replayed after a withdrawal is refused without saying why",
)
def test_the_enrolment_form_after_a_withdrawal_says_the_participant_is_withdrawn(lb: dict[str, Any]) -> None:
    c, csrf, no = _enrolled(lb)
    _withdraw(c, csrf, no)
    r = _save(c, csrf, no, "tb_enrolment", {"en_date": "2026-11-12", "en_eligible": "1"}, back="subject")
    m = re.search(r'data-testid="entry-refused"[^>]*>([^<]*)', r.text)
    assert r.status_code < 500 and m and "withdrawn" in m.group(1).lower()


def test_a_disable_sent_twice_counts(box: dict[str, Any]) -> None:
    """Measures only (the outcome is held by the xfail below)."""
    c, csrf = login(box["app"])
    form = {"csrf": csrf, "action": "disable", "username": "viewer", "confirm": "yes"}
    r1 = c.post("/ops/users", data=form, follow_redirects=False)
    r2 = c.post("/ops/users", data=form, follow_redirects=False)
    record("account_disable_twice", {"route": "POST /ops/users (disable)", "status": [r1.status_code,
           r2.status_code], "location_second": r2.headers.get("location", ""),
           "audit_console_user": len(_events(box, "console.user"))})  # fmt: skip
    assert r1.status_code == 303 and r2.status_code < 500
