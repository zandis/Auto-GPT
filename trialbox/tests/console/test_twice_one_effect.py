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
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests import edc_kit as k
from tests.console.test_amendment_rescreen import _screen
from tests.console.test_console_app import ADMIN_PW, _consent_done, _done_screen, _ulid, box, login, login_crc, name_pi
from tests.console.test_dataops_page import _night
from tests.console.test_edc_pages import NO as ENO
from tests.console.test_edc_pages import PW as EPW
from tests.console.test_edc_pages import _ready, _seen, eb
from tests.console.test_lifecycle_mediums_pages import A, B, _row
from tests.console.test_lifecycle_pages import PW, _save, lb
from tests.console.test_no_one_holds_both_factors import STEWARD_PW, _add, _box, _request_ids, _requests, _signin
from tests.console.test_role_pages import PW as ROLE_PW
from tests.console.test_role_pages import _csrf as _rcsrf
from tests.console.test_role_pages import _user
from tests.console.test_team_pages import _events

__all__ = ["box", "eb", "lb"]
STUDY = "GZQO"


def record(case: str, row: dict[str, Any]) -> None:
    """Add one case's counts to ``$TB_TWICE_OUT/twice.json`` (only when the variable is set)."""
    out = os.environ.get("TB_TWICE_OUT")
    if not out:
        return
    path = Path(out) / "twice.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    text = re.sub(r"\b[0-9A-HJKMNP-TV-Z]{26}\b", "<job>", json.dumps(row))  # stable labels for random ids
    data[case] = json.loads(re.sub(r"\b[0-9a-f]{32}\b", "<pid>", text))
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
           r2.status_code], "steps_added": after - before, "audit_life_step": ev,
           "one_effect": after - before == 1 and ev == 1 and r2.status_code == 409})  # fmt: skip
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
           "audit_data_entry": len(entries), "second_changed": entries[-1].get("changed"),
           "one_effect": len(consents) == 1 and len(lb["dc"].history(STUDY, no)) == n1
           and entries[-1].get("changed") == 0})  # fmt: skip
    assert len(consents) == 1 and len(lb["dc"].history(STUDY, no)) == n1
    assert len(entries) == 2 and entries[-1].get("changed") == 0  # the second save changed no value (sync.py:311)
    assert [s for s in _steps(lb, no) if s[1] == "consented"] == [("approached", "consented")]


def test_the_enrolment_form_saved_twice_is_one_enrolment(lb: dict[str, Any]) -> None:
    c, csrf, no = _enrolled(lb)
    n = len(lb["dc"].history(STUDY, no))
    r2 = _save(c, csrf, no, "tb_enrolment", {"en_date": "2026-11-04", "en_eligible": "1"}, back="subject")
    entries = [e["detail"] for e in _events(lb, "console.data_entry")]
    record("enrolment_twice", {"route": "POST /studies/{rs}/entry (tb_enrolment)", "status_second": r2.status_code,
           "enrolled_steps": sum(1 for s in _steps(lb, no) if s[1] == "enrolled"),
           "values_added_by_second": len(lb["dc"].history(STUDY, no)) - n, "second_changed": entries[-1]["changed"],
           "second_says_saved": 'data-testid="life-entry-saved"' in r2.text,
           "one_effect": len(lb["dc"].history(STUDY, no)) == n and entries[-1]["changed"] == 0})  # fmt: skip
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
    entries = [e["detail"] for e in _events(lb, "console.data_entry") if e["detail"].get("form") == "tb_withdrawal"]
    steps = _all_events(lb).count("console.life_step")
    record("withdrawal_twice", {"route": "POST /studies/{rs}/entry (tb_withdrawal)", "status_second": r2.status_code,
           "withdrawn_steps": sum(1 for s in _steps(lb, no) if s[1] == "withdrawn"),
           "values_added_by_second": len(lb["dc"].history(STUDY, no)) - n, "audit_data_entry": len(entries),
           "second_changed": entries[-1]["changed"], "audit_life_step": steps,
           "second_says_saved": 'data-testid="life-entry-saved"' in r2.text,
           "one_effect": len(lb["dc"].history(STUDY, no)) == n and entries[-1]["changed"] == 0})  # fmt: skip
    assert sum(1 for s in _steps(lb, no) if s[1] == "withdrawn") == 1 and len(lb["dc"].history(STUDY, no)) == n
    assert len(entries) == 2 and entries[-1]["changed"] == 0  # the second save changed no value (sync.py:311)


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
           "override_records": len(team.overrides(STUDY)), "notices": len(lb["backend"].notices),
           "one_effect": len(team.overrides(STUDY)) == 1 and ev.count("console.approach_override") == 1})  # fmt: skip
    assert r2.status_code == 303


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="V11-01: a second identical Approach (no new decision) writes a second IRB-override record and event",
)
def test_approach_marked_twice_is_one_override(lb: dict[str, Any]) -> None:
    """The mark rows are append-only by design (D-104: a mark is an event); only the override trail is asserted."""
    pi, csrf = _marked(lb)
    team = lb["app"].state.helpers.team
    if not team.overrides(STUDY):
        raise RuntimeError("the first Approach made no override: no measure")
    pi.post(f"/studies/{STUDY}/patients/{A}/mark", data={"csrf": csrf, "mark": "approach"}, follow_redirects=False)
    ev = _all_events(lb)
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
           ev.count("console.contact_outcome"), "audit_refused": ev.count("console.refused"),
           "one_effect": len(store.outcomes(STUDY, A)) == 1 and ev.count("console.contact_outcome") == 1})  # fmt: skip
    assert r1.status_code == 303 and r2.status_code == 409 and r2.status_code < 500
    assert len(store.outcomes(STUDY, A)) == 1 and ev.count("console.contact_outcome") == 1


@pytest.mark.usefixtures("held_dir")
def test_an_account_added_twice_is_one_account(box: dict[str, Any]) -> None:
    c, csrf = login(box["app"])
    form = {"csrf": csrf, "action": "add", "username": "Nurse.Twice", "role": "viewer", "mailbox": "tw@hospa.test"}
    r1 = c.post("/ops/users", data=form, follow_redirects=False)
    r2 = c.post("/ops/users", data=form, follow_redirects=False)
    ev = [e for e in _events(box, "console.user")]
    record("account_add_twice", {"route": "POST /ops/users (add)", "status": [r1.status_code, r2.status_code],
           "accounts": int(box["users"].get("nurse.twice") is not None), "audit_console_user": len(ev),
           "one_effect": len(ev) == 1 and r2.status_code == 400})  # fmt: skip
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
           "kinds": [n[0] for n in notices], "mails_after_first": n1, "mails_after_second": n2,
           "audit_console_notice": _all_events(lb).count("console.notice"), "one_effect": n1 >= 1 and n2 == n1})  # fmt: skip
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
           "mails": len(notices), "audit_console_notice": _all_events(lb).count("console.notice"),
           "one_effect": len(notices) == len({(n[0], tuple(n[1])) for n in notices})})  # fmt: skip


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
@pytest.mark.usefixtures("held_dir")
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
           "audit_confirmed": len(confirmed), "own_two_tabs": own,
           "one_effect": len(confirmed) == 10 and all(r == [200, 409] for r in rows) and own == [403, 403]})  # fmt: skip
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
           "form_message": m.group(1).strip() if m else "",
           "one_effect": _steps(lb, no) == steps and len(lb["dc"].history(STUDY, no)) == values})  # fmt: skip
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
           "outcomes_added": len(store.outcomes(STUDY, A)) - n, "one_effect": len(store.outcomes(STUDY, A)) == n})  # fmt: skip
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
           "audit_console_user": len(_events(box, "console.user")),
           "one_effect": len(_events(box, "console.user")) == 1})  # fmt: skip
    assert r1.status_code == 303 and r2.status_code < 500


# ---------------------------------------------------------------------------------------------- regulated routes
#: events a second request may rightly leave: a refusal, a denial or a sign-in; anything else is a second effect
SECOND_OK = re.compile(r"refused|denied|duplicate|login|session|noop|reconciled")


def _snap(b: dict[str, Any], records: Any) -> tuple[Counter[str], int, int, Any]:
    ev: Counter[str] = Counter()
    for f in sorted(Path(b["dir"]).rglob("*.jsonl")):
        for line in f.read_text().splitlines():
            if line.startswith("{"):
                e = json.loads(line)
                if e.get("event"):  # a refusal written under the action's own name is counted as a refusal
                    d = e.get("detail") or {}
                    tag = ":refused" if "refused" in d else ":noop" if d.get("sent") == 0 else ""  # edc: sent 0
                    ev[str(e["event"]) + tag] += 1
    bk = b["backend"]
    return ev, len(bk.notices) + len(bk.mails), len(bk.created), records()


def _delta(a: Counter[str], b: Counter[str]) -> dict[str, int]:
    return {k: b[k] - a[k] for k in sorted(b) if b[k] - a[k] > 0 and not k.startswith("flag.")}


def twice(b: dict[str, Any], case: str, client: Any, path: str, data: dict[str, Any] | None = None, *,
          json_body: Any = None, headers: dict[str, str] | None = None, records: Any = lambda: 0,
          access: bool = False, files: Any = None, template: str = "") -> dict[str, Any]:  # fmt: skip
    """Send the same request twice (same session, same token) and count before, between and after: audit events,
    mails and jobs asked of the stand-in orchestrator (the console box has no mail gateway outbox: mails are counted
    at the stand-in's ``send_notice`` and ``send_test_mail``), and the route's own records (``records``).
    ``access``: a read of a chart number, where each read is its own audited access (D-280)."""
    s0 = _snap(b, records)
    kw: dict[str, Any] = {"follow_redirects": False}
    if headers:
        kw["headers"] = headers
    if json_body is not None:
        kw["json"] = json_body
    else:
        kw["data"] = data
    if files:
        kw["files"] = files
    r1 = client.post(path, **kw)
    s1 = _snap(b, records)
    r2 = client.post(path, **kw)
    s2 = _snap(b, records)
    second = _delta(s1[0], s2[0])
    effects = {k: v for k, v in second.items() if not SECOND_OK.search(k)}
    row: dict[str, Any] = {
        "route": f"POST {template or path}",
        "status": [r1.status_code, r2.status_code],
        "events_first": _delta(s0[0], s1[0]),
        "events_second": second,
        "mails": [s1[1] - s0[1], s2[1] - s1[1]],
        "jobs": [s1[2] - s0[2], s2[2] - s1[2]],
        "records": [s0[3], s1[3], s2[3]],
    }
    worked = r1.status_code < 400 and bool(row["events_first"] or s1[1:] != s0[1:])
    row["first_worked"] = worked
    same = s2[1:3] == s1[1:3] and (access or s2[3] == s1[3])  # mails, jobs; records unless each read is one
    row["one_effect"] = bool(worked and r2.status_code < 500 and same and (access or not effects))
    record(case, row)
    return row


def _bg_open(b: dict[str, Any]) -> tuple[Any, str]:
    _done_screen(b["backend"], _ulid(992))
    _user(b, "stw1", "steward")
    admin, _ = login(b["app"])
    return admin, _rcsrf(admin.get("/breakglass").text)


BG_FORM = {"reason": "support", "note": "support call about one patient", "kind": "patient", "ruleset": STUDY, "pid": A}


def test_break_glass_open_twice(box: dict[str, Any]) -> None:
    """Measures only (the outcome is held by the xfail below)."""
    admin, csrf = _bg_open(box)
    row = twice(box, "breakglass_open", admin, "/breakglass", {"csrf": csrf, **BG_FORM})
    assert row["first_worked"] and row["status"][1] < 500


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="V11-08: a double click on break-glass open makes two grants, two events, two mails",
)
def test_break_glass_open_twice_is_one_grant(box: dict[str, Any]) -> None:
    admin, csrf = _bg_open(box)
    row = twice(box, "breakglass_open", admin, "/breakglass", {"csrf": csrf, **BG_FORM})
    if not row["first_worked"]:
        raise RuntimeError("the first open did not work: no measure")
    assert row["events_second"].get("console.breakglass_open", 0) == 0 and row["mails"][1] == 0


def test_break_glass_end_and_review_twice(box: dict[str, Any]) -> None:
    admin, csrf = _bg_open(box)
    admin.post("/breakglass", data={"csrf": csrf, **BG_FORM})
    gid = _events(box, "console.breakglass_open")[0]["detail"]["grant"]
    end = twice(box, "breakglass_end", admin, f"/breakglass/{gid}/end", {"csrf": csrf},
                template="/breakglass/{gid}/end")  # fmt: skip
    stw, _ = login(box["app"], "stw1", ROLE_PW)
    rev = twice(box, "breakglass_review", stw, f"/breakglass/{gid}/review",
                {"csrf": _rcsrf(stw.get("/breakglass").text), "note": "checked"},
                template="/breakglass/{gid}/review")  # fmt: skip
    assert rev["one_effect"], rev
    assert end["status"][1] < 500


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="V11-11: ending a grant already ended writes a second console.breakglass_end event",
)
def test_break_glass_end_twice_is_one_end(box: dict[str, Any]) -> None:
    admin, csrf = _bg_open(box)
    admin.post("/breakglass", data={"csrf": csrf, **BG_FORM})
    gid = _events(box, "console.breakglass_open")[0]["detail"]["grant"]
    end = twice(box, "breakglass_end", admin, f"/breakglass/{gid}/end", {"csrf": csrf},
                template="/breakglass/{gid}/end")  # fmt: skip
    if not end["first_worked"]:
        raise RuntimeError("the first end did not work: no measure")
    assert end["events_second"].get("console.breakglass_end", 0) == 0


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="V11-11: switching EDC prefill on when it is on writes a second switch record and event",
)
def test_edc_switch_on_twice_is_one_switch(eb: dict[str, Any]) -> None:
    _ready(eb, on=False)
    pi, _ = login(eb["app"], "drsato", EPW)
    page = pi.get("/studies/GZQO/edc").text
    row = twice(eb, "edc_switch", pi, "/studies/GZQO/edc/switch", {"csrf": _rcsrf(page), "on": "1",
                "kind": "sponsor_letter", "reference": "SPN-1", "ack_date": "2026-11-01", "dataflow_ref": "DMP 5",
                "reentry_pages": "30", "reentry_accuracy": "98.5"}, template="/studies/{rs}/edc/switch")  # fmt: skip
    if not row["first_worked"]:
        raise RuntimeError("the first switch did not work: no measure")
    assert row["events_second"].get("edc.switch", 0) == 0


def test_an_opt_out_twice(box: dict[str, Any]) -> None:
    """Measures only (the outcome is held by the xfail below)."""
    stw = _user(box, "stw1", "steward")
    row = twice(box, "opt_out", stw, "/site/opt-outs", {"csrf": _rcsrf(stw.get("/site/opt-outs").text), "pid": A})
    assert row["first_worked"] and row["status"][1] < 500


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="V11-09: a second identical opt-out writes a second console.opt_out event (done=same)",
)
def test_an_opt_out_twice_is_one_event(box: dict[str, Any]) -> None:
    stw = _user(box, "stw1", "steward")
    row = twice(box, "opt_out", stw, "/site/opt-outs", {"csrf": _rcsrf(stw.get("/site/opt-outs").text), "pid": A})
    if not row["first_worked"]:
        raise RuntimeError("the first opt-out did not work: no measure")
    assert row["events_second"].get("console.opt_out", 0) == 0


def _open_study(b: dict[str, Any]) -> None:
    store = b["app"].state.helpers.store
    if store.study_state(STUDY).state != "open":  # seeded, as a steward would
        store.set_study_state(STUDY, "open", "V-11 seed", "stw-setup", "2026-11-08T01:00:00+00:00")


def test_close_a_study_twice(lb: dict[str, Any]) -> None:
    _open_study(lb)
    c, csrf = login(lb["app"], "crc", PW)
    store = lb["app"].state.helpers.store
    row = twice(lb, "close_study", c, f"/studies/{STUDY}/state", {"csrf": csrf, "state": "closed", "reason": "end", "confirm": "yes"},
                records=lambda: len(store.state_history(STUDY)), template="/studies/{rs}/state")  # fmt: skip
    assert row["one_effect"], row


def test_a_chart_number_revealed_twice(box: dict[str, Any]) -> None:
    jid = _ulid(970)
    _done_screen(box["backend"], jid)
    c, csrf = login_crc(box)
    row = twice(box, "reveal_job", c, f"/pilot/jobs/{jid}/reveal", {"csrf": csrf, "pid": "a" * 32,
                "reason": "contact"}, records=lambda: len(box["backend"].revealed), access=True,
                template="/pilot/jobs/{job_id}/reveal")  # fmt: skip
    assert row["one_effect"], row


def test_a_data_ops_decision_twice_page_and_api(box: dict[str, Any]) -> None:
    bid = _night(box, "2026-11-10")
    stw = _user(box, "stw", "steward")
    tok = _rcsrf(stw.get("/data-ops").text)
    page = twice(box, "dataops_decide", stw, f"/data-ops/batches/{bid}/decide",
                 {"csrf": tok, "decision": "reject", "reason": "lab file truncated"},
                 template="/data-ops/batches/{bid}/decide")  # fmt: skip
    bid2 = _night(box, "2026-11-11")
    api = TestClient(box["app"])
    tokn = api.post("/api/v1/session", json={"username": "stw", "password": ROLE_PW}).json()["token"]
    apr = twice(box, "dataops_decide_api", api, f"/api/v1/data/batches/{bid2}/decide",
                json_body={"decision": "reject", "reason": "bad"}, headers={"Authorization": f"Bearer {tokn}"},
                template="/api/v1/data/batches/{bid}/decide")  # fmt: skip
    assert page["one_effect"] and apr["one_effect"], (page, apr)


def test_a_consent_job_released_twice(box: dict[str, Any]) -> None:
    jid = _ulid(950)
    _consent_done(box["backend"], jid)
    c, csrf = login(box["app"])
    row = twice(box, "release", c, f"/pilot/jobs/{jid}/release", {"csrf": csrf, "drop": "i03, q2", "keep": ""},
                template="/pilot/jobs/{job_id}/release")  # fmt: skip
    assert row["status"][1] < 500


def test_the_pilot_forms_twice(box: dict[str, Any]) -> None:
    """A request, a case and a consent form sent twice. Jobs are counted at the stand-in orchestrator; whether the
    real orchestrator merges a second identical request is not modelled there."""
    c, csrf = login(box["app"])
    req = twice(box, "pilot_request", c, "/pilot/request", {"csrf": csrf, "kind": "FEAS", "ruleset": STUDY})
    case = twice(box, "pilot_case", c, "/pilot/case", {"csrf": csrf, "ruleset": STUDY, "mrn": "A1001", "lang": "en"},
                 files=[("charts", ("chart.md", b"# summary\n2026-03-12 flare", "text/markdown"))])  # fmt: skip
    cons = twice(box, "pilot_consent", c, "/pilot/consent", {"csrf": csrf, "study": "S1", "use_sample": "1",
                 "langs": ["en"]})  # fmt: skip
    assert all(r["status"][1] < 500 and r["first_worked"] for r in (req, case, cons))


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="V11-12: a double submit of a request form asks the orchestrator for a second job",
)
def test_a_request_sent_twice_asks_for_one_job(box: dict[str, Any]) -> None:
    c, csrf = login(box["app"])
    row = twice(box, "pilot_request", c, "/pilot/request", {"csrf": csrf, "kind": "FEAS", "ruleset": STUDY})
    if not row["first_worked"]:
        raise RuntimeError("the first request did not work: no measure")
    assert row["jobs"][1] == 0


@pytest.mark.usefixtures("held_dir")
def test_account_reset_twice(box: dict[str, Any]) -> None:
    c, csrf = login(box["app"])
    row = twice(box, "account_reset", c, "/ops/users", {"csrf": csrf, "action": "reset", "username": "viewer",
                "confirm": "yes"}, template="/ops/users (reset)")  # fmt: skip
    assert row["status"][1] < 500


def _edc_review(eb: dict[str, Any]) -> tuple[Any, str]:
    _ready(eb)
    crc, _ = login(eb["app"], "crc", EPW)
    page = crc.get("/studies/GZQO/edc").text
    crc.post("/studies/GZQO/edc/drafts", data={"csrf": _rcsrf(page), "record": ENO, "visit": "",
                                               "visit_date": k.VISIT_DATE})  # fmt: skip
    return crc, _rcsrf(crc.get(f"/studies/GZQO/edc/review/{ENO}").text)


def test_edc_decide_sign_send_twice(eb: dict[str, Any]) -> None:
    crc, csrf = _edc_review(eb)
    store = eb["svc"].store
    drafts = {d["item"]: d for d in store.drafts("GZQO", ENO)}
    dec = twice(eb, "edc_decide", crc, f"/studies/GZQO/edc/decide/{drafts['weight']['id']}",
                {"csrf": csrf, "action": "confirm", "record": ENO},
                template="/studies/{rs}/edc/decide/{draft_id}")  # fmt: skip
    for item in ("urate", "sex"):
        crc.post(f"/studies/GZQO/edc/decide/{drafts[item]['id']}", data={"csrf": csrf, "action": "confirm",
                 "record": ENO})  # fmt: skip
    seen = _seen(crc.get(f"/studies/GZQO/edc/review/{ENO}").text)
    sign = twice(eb, "edc_sign", crc, "/studies/GZQO/edc/sign", {"csrf": csrf, "record": ENO, "password": EPW,
                 "meaning_ack": "1", "seen": seen}, records=lambda: len(store.signatures("GZQO")),
                 template="/studies/{rs}/edc/sign")  # fmt: skip
    send = twice(eb, "edc_send", crc, "/studies/GZQO/edc/send", {"csrf": csrf, "record": ENO},
                 template="/studies/{rs}/edc/send")  # fmt: skip
    assert all(r["status"][1] < 500 for r in (dec, sign, send))


def test_edc_switch_twice(eb: dict[str, Any]) -> None:
    _ready(eb, on=False)
    pi, _ = login(eb["app"], "drsato", EPW)
    page = pi.get("/studies/GZQO/edc").text
    row = twice(eb, "edc_switch", pi, "/studies/GZQO/edc/switch", {"csrf": _rcsrf(page), "on": "1",
                "kind": "sponsor_letter", "reference": "SPN-1", "ack_date": "2026-11-01", "dataflow_ref": "DMP 5",
                "reentry_pages": "30", "reentry_accuracy": "98.5"}, template="/studies/{rs}/edc/switch")  # fmt: skip
    assert row["status"][1] < 500


# ---------------------------------------------------------------------------------------------- back button (more)
def _approach_after_close(lb: dict[str, Any]) -> dict[str, Any]:
    pi, pcsrf = _marked(lb)
    _open_study(lb)
    crc, csrf = login(lb["app"], "crc", PW)
    store = lb["app"].state.helpers.store
    r = crc.post(f"/studies/{STUDY}/state", data={"csrf": csrf, "state": "closed", "reason": "end", "confirm": "yes"},
                 follow_redirects=False)  # fmt: skip
    closed = store.study_state(STUDY).state
    n, nos = len(store.mark_history(STUDY, B)), len(store.screening_nos(STUDY))
    r2 = pi.post(f"/studies/{STUDY}/patients/{B}/mark", data={"csrf": pcsrf, "mark": "approach"},
                 follow_redirects=False)  # fmt: skip
    added = len(store.mark_history(STUDY, B)) - n
    return {"route": "POST /studies/{rs}/patients/{pid}/mark", "close_status": r.status_code, "state": closed,
            "status": r2.status_code, "marks_added": added, "screening_nos_added": len(store.screening_nos(STUDY)) - nos,
            "one_effect": closed == "closed" and added == 0}  # fmt: skip


def test_approach_after_the_study_is_closed_counts(lb: dict[str, Any]) -> None:
    """Measures only (the outcome is held by the xfail below)."""
    record("back_mark_after_close", _approach_after_close(lb))


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="V11-10: an Approach replayed after the study is closed is kept, with a screening number",
)
def test_approach_after_the_study_is_closed_is_refused(lb: dict[str, Any]) -> None:
    row = _approach_after_close(lb)
    if row["state"] != "closed":
        raise RuntimeError(f"the study did not close: {row}")
    assert row["marks_added"] == 0 and row["screening_nos_added"] == 0


def test_contact_outcome_after_a_withdrawal(lb: dict[str, Any]) -> None:
    """The participant is withdrawn on the lifecycle; the coordinator's earlier outcome form is posted again."""
    c, csrf, no = _enrolled(lb)
    _withdraw(c, csrf, no)
    pid = _subject(lb, no)["subject"]["pid"]
    store = lb["app"].state.helpers.store
    n = len(store.outcomes(STUDY, pid))
    r = c.post(f"/studies/{STUDY}/patients/{pid}/outcome", data={"csrf": csrf, "outcome": "reached_booked"},
               follow_redirects=False)  # fmt: skip
    added = len(store.outcomes(STUDY, pid)) - n
    record("back_outcome_after_withdrawal", {"route": "POST /studies/{rs}/patients/{pid}/outcome",
           "status": r.status_code, "outcomes_added": added, "one_effect": added == 0 and r.status_code < 500})  # fmt: skip
    assert r.status_code < 500


def _after_opt_out(lb: dict[str, Any]) -> dict[str, Any]:
    """The person opts out (the steward's register); the coordinator's earlier consent and enrolment forms are posted
    again for that participant."""
    no = lb["nos"][0]
    c, csrf = _crc(lb)
    c.post(f"/studies/{STUDY}/subjects/{no}/step", data={"csrf": csrf, "to": "approached", "on_day": "2026-11-02"})
    pid = _subject(lb, no)["subject"]["pid"]
    stw = _user(lb, "stw1", "steward")
    o = stw.post("/site/opt-outs", data={"csrf": _rcsrf(stw.get("/site/opt-outs").text), "pid": pid},
                 follow_redirects=False)  # fmt: skip
    steps, values = len(_steps(lb, no)), len(lb["dc"].history(STUDY, no))
    r1 = _save(c, csrf, no, "tb_consent", {"ic_date": "2026-11-03", "ic_version": "v1", "ic_copy": "1"})
    r2 = _save(c, csrf, no, "tb_enrolment", {"en_date": "2026-11-04", "en_eligible": "1"}, back="subject")
    row = {
        "route": "POST /studies/{rs}/entry",
        "opt_out_status": o.status_code,
        "status": [r1.status_code, r2.status_code],
        "steps_added": len(_steps(lb, no)) - steps,
        "values_added": len(lb["dc"].history(STUDY, no)) - values,
        "state": _subject(lb, no)["subject"]["state"],
    }
    row["one_effect"] = row["steps_added"] == 0 and row["values_added"] == 0
    record("back_consent_after_opt_out", row)
    return row


def test_consent_and_enrolment_after_an_opt_out_counts(lb: dict[str, Any]) -> None:
    """Measures only (the outcome is held by the xfail below)."""
    row = _after_opt_out(lb)
    assert all(code < 500 for code in row["status"])


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="V11-13: consent and enrolment are recorded for a person after their opt-out",
)
def test_consent_and_enrolment_after_an_opt_out_are_refused(lb: dict[str, Any]) -> None:
    row = _after_opt_out(lb)
    if row["opt_out_status"] != 303:
        raise RuntimeError(f"the opt-out did not take: {row}")
    assert row["steps_added"] == 0 and row["values_added"] == 0


def test_a_patient_page_reveal_twice(box: dict[str, Any]) -> None:
    _done_screen(box["backend"], _ulid(985))
    crc = _user(box, "crc1", "coordinator")
    page = crc.get(f"/studies/GZQO/patients/{A}").text
    row = twice(box, "reveal_patient", crc, f"/studies/GZQO/patients/{A}/reveal",
                {"csrf": _rcsrf(page), "reason": "other", "note": "monitor asked to check the source chart"},
                records=lambda: len(box["backend"].revealed), access=True,
                template="/studies/{rs}/patients/{pid}/reveal")  # fmt: skip
    assert row["one_effect"], row


def _sae_twice(lb: dict[str, Any]) -> dict[str, Any]:
    name_pi(lb, "pi")
    no = lb["nos"][0]
    c, csrf = _crc(lb)
    c.post("/studies/GZQO/setup/sae", data={"csrf": csrf, "rule_set": "tw_trial"})
    lb["clock"]["now"] = datetime(2026, 11, 11, 1, 0, tzinfo=UTC)
    fatal = {"ae_term": "Myocardial infarction", "ae_onset": "2026-11-08", "ae_aware": "2026-11-09",
             "ae_serious": "1", "ae_serious_why": "1", "ae_severity": "3", "ae_outcome": "5", "ae_related": "9"}  # fmt: skip
    data: dict[str, Any] = {"csrf": csrf, "record": no, "event": "ae1", "form": "tb_adverse_event", "back": "subject",
                            "reason": "", **{f"f_{k}": v for k, v in fatal.items()}}  # fmt: skip
    rec = twice(lb, "sae_record", c, "/studies/GZQO/entry", data,
                records=lambda: len(_subject(lb, no)["aes"]), template="/studies/{rs}/entry (tb_adverse_event)")  # fmt: skip
    pi, pcsrf = login(lb["app"], "pi", PW)
    ack = twice(lb, "sae_ack", pi, f"/studies/GZQO/subjects/{no}/aes/ae1/ack", {"csrf": pcsrf},
                template="/studies/{rs}/subjects/{record}/aes/{event}/ack")  # fmt: skip
    assert rec["mails"][1] == 0 and rec["records"][2] == rec["records"][1] and ack["status"][1] < 500
    return ack


def test_an_sae_recorded_and_acknowledged_twice(lb: dict[str, Any]) -> None:
    """Measures only (the acknowledgement is held by the xfail below)."""
    _sae_twice(lb)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="V11-14: a second acknowledgement of one SAE writes a second sae_ack in both audit trails",
)
def test_an_sae_acknowledged_twice_is_one_acknowledgement(lb: dict[str, Any]) -> None:
    ack = _sae_twice(lb)
    if not ack["first_worked"]:
        raise RuntimeError("the first acknowledgement did not work: no measure")
    assert not {k for k in ack["events_second"] if "sae_ack" in k and ":refused" not in k}
