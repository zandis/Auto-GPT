# ruff: noqa: F811 - the box fixture is imported from test_console_app and taken by name
"""STEPS-ROLE (D-877, the owner's D-1063): one sign-in per person on a test box, and the role it acts in.

* with the flag off an account with extra roles is its own role only, and no switch is offered or accepted;
* with the flag on the top bar offers the account's roles, a switch is one CSRF post and one audit event
  (role.acting: user, from, to), every page shows the acting role, and the acting role decides every permission;
* the audit trail names the person, never only the acting role;
* on a validation or production box the flag cannot be set, extra roles cannot be granted, the switch is refused, and
  the console refuses to start with the flag on or an extra role on record;
* the boot tool opens one account per person by a one-time code with its roles.

Synthetic accounts only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.console.test_console_app import ADMIN_PW, box, login  # noqa: F401 - the fixture is used by name

PW = "acting-role-password-01"


def _flag(b: dict[str, Any], value: str) -> None:
    from tb_common.flags import Flags

    Flags(audit=b["audit"]).set("steps.acting_role", value, "console:admin", "the test walks a study in steps")


def _events(b: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    out = []
    for f in sorted(Path(b["backend"].audit_dir).rglob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            e = json.loads(line)
            if e.get("event") == kind:
                out.append(e)
    return out


@pytest.fixture
def person(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setenv("TB_ENV", "TEST")
    users = box["users"]
    users.create("mei", "viewer", PW, "mei@hospa.test")
    users.grant_roles("mei", ["admin", "coordinator", "investigator", "steward"], allowed=True)
    return box


def test_with_the_flag_off_an_account_is_its_own_role_only(person: dict[str, Any]) -> None:
    c, csrf = login(person["app"], "mei", PW)
    page = c.get("/account").text
    assert 'data-testid="role-switch"' not in page and 'data-testid="acting-role"' not in page
    r = c.post("/role", data={"csrf": csrf, "role": "admin"}, follow_redirects=False)
    assert r.status_code == 403
    assert c.get("/ops/users", follow_redirects=False).status_code == 403  # a viewer's answer


@pytest.mark.usefixtures("held_dir")
def test_a_switch_is_one_audited_post_and_the_acting_role_decides(person: dict[str, Any]) -> None:
    _flag(person, "on")
    c, csrf = login(person["app"], "mei", PW)
    page = c.get("/account").text
    assert 'data-testid="role-switch"' in page and 'value="admin"' in page
    assert c.get("/ops/users", follow_redirects=False).status_code == 403
    assert c.post("/role", data={"csrf": "wrong", "role": "admin"}, follow_redirects=False).status_code == 400
    r = c.post("/role", data={"csrf": csrf, "role": "admin", "back": "/ops/users"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/ops/users"
    assert c.get("/ops/users", follow_redirects=False).status_code == 200  # the acting role's answer
    page = c.get("/account").text
    assert 'data-testid="acting-role" data-acting="admin"' in page and "mei" in page
    (ev,) = _events(person, "role.acting")
    assert ev["actor"] == "console:mei" and ev["detail"] == {"user": "mei", "from": "viewer", "to": "admin"}
    c.post("/role", data={"csrf": csrf, "role": "viewer"}, follow_redirects=False)
    assert c.get("/ops/users", follow_redirects=False).status_code == 403
    assert [e["detail"]["to"] for e in _events(person, "role.acting")] == ["admin", "viewer"]
    r = c.post("/role", data={"csrf": csrf, "role": "privacy"}, follow_redirects=False)  # a role it does not hold
    assert r.status_code == 403


def test_the_audit_trail_names_the_person_when_acting(person: dict[str, Any]) -> None:
    _flag(person, "on")
    c, csrf = login(person["app"], "mei", PW)
    c.post("/role", data={"csrf": csrf, "role": "coordinator"}, follow_redirects=False)
    assert c.get("/ops/flags", follow_redirects=False).status_code == 403  # the page audits whom it refuses
    denied = _events(person, "console.denied")
    assert denied and all(e["actor"] == "console:mei" for e in denied)
    assert all("coordinator" not in str(e["actor"]) for e in _events(person, "role.acting") + denied)


@pytest.mark.usefixtures("held_dir")
def test_the_flag_switched_off_ends_the_acting_role(person: dict[str, Any]) -> None:
    _flag(person, "on")
    c, csrf = login(person["app"], "mei", PW)
    c.post("/role", data={"csrf": csrf, "role": "admin"}, follow_redirects=False)
    assert c.get("/ops/users", follow_redirects=False).status_code == 200
    _flag(person, "off")
    assert c.get("/ops/users", follow_redirects=False).status_code == 403  # its own role again


@pytest.mark.parametrize("env", ["VALIDATION", "PRODUCTION", ""])
def test_on_a_validation_or_production_box_nothing_opens(box: dict[str, Any], env: str,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    from console.auth import AuthError
    from console.steps_roles import open_people
    from tb_common.flags import Flags

    if env:
        monkeypatch.setenv("TB_ENV", env)
    else:
        monkeypatch.delenv("TB_ENV", raising=False)  # unset is PRODUCTION
    with pytest.raises(ValueError, match="test box only"):
        Flags(audit=box["audit"]).set("steps.acting_role", "on", "console:admin", "a reason")
    box["users"].create("mei", "viewer", PW)
    with pytest.raises(AuthError, match="test box only"):
        import os

        from console.acting import env_allows

        box["users"].grant_roles("mei", ["admin"], allowed=env_allows(os.environ))
    with pytest.raises(SystemExit, match="test box only"):
        open_people(box["users"], None, [("lin", ("viewer", "admin"))], [], 24)


def test_the_route_refuses_on_a_production_box_even_with_rows_written_behind_its_back(
    box: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from console.app import create_app
    from tb_common.audit import AuditLog

    from tests.console.test_console_app import PILOT_ENV as ENV
    from tests.console.test_console_app import FakeBackend

    users = box["users"]
    users.create("mei", "viewer", PW)
    users.db.execute("UPDATE users SET extra_roles = 'admin' WHERE username = 'mei'")  # written behind its back
    backend = FakeBackend()
    backend.audit_dir = tmp_path / "audit2"
    with pytest.raises(Exception, match="extra roles"):  # the console does not start
        create_app({**ENV, "TB_ENV": "PRODUCTION", "TB_CONSOLE_DIR": str(tmp_path)}, backend=backend,
                   audit=AuditLog(backend.audit_dir), users=users)  # fmt: skip


def test_the_console_refuses_to_start_on_production_with_the_flag_on(
    box: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from console.app import create_app
    from tb_common.audit import AuditLog
    from tb_common.flags import Flags

    from tests.console.test_console_app import PILOT_ENV as ENV
    from tests.console.test_console_app import FakeBackend

    monkeypatch.setenv("TB_ENV", "TEST")
    Flags(audit=box["audit"]).set("steps.acting_role", "on", "console:admin", "a reason")
    backend = FakeBackend()
    backend.audit_dir = tmp_path / "audit2"
    with pytest.raises(Exception, match="steps.acting_role"):
        create_app({**ENV, "TB_ENV": "VALIDATION", "TB_CONSOLE_DIR": str(tmp_path)}, backend=backend,
                   audit=AuditLog(backend.audit_dir), users=box["users"])  # fmt: skip


def test_the_switch_is_refused_on_a_production_box(box: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """The route's own check: a box whose environment is not a test box refuses the switch whatever the flag and
    the account hold (the start check stops such a console first; this holds if a row is written after the start)."""
    from console import acting

    users = box["users"]
    users.create("mei", "viewer", PW)
    c, csrf = login(box["app"], "mei", PW)
    users.db.execute("UPDATE users SET extra_roles = 'admin' WHERE username = 'mei'")
    users.acting_on = lambda: True  # as if the flag were read on
    monkeypatch.setattr(acting, "env_allows", lambda env: False)
    assert c.post("/role", data={"csrf": csrf, "role": "admin"}, follow_redirects=False).status_code == 403


def test_the_boot_tool_opens_one_account_per_person_with_its_roles(box: dict[str, Any],
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    from console.steps_roles import _people, open_people

    monkeypatch.setenv("TB_ENV", "TEST")
    people = _people(["Lin", "investigator,coordinator,admin,steward", "kai", "coordinator,viewer"])
    assert people == [("lin", ("investigator", "coordinator", "admin", "steward")), ("kai", ("coordinator", "viewer"))]
    rows = open_people(box["users"], None, people, [], 24)
    assert [(n, r) for n, r, _code, _exp in rows] == people
    users = box["users"]
    assert users.role_of("lin") == "investigator" and users.extra_roles("lin") == ("admin", "coordinator", "steward")
    assert not users.holder_set("lin")  # opened by code: nobody knows a password
    with pytest.raises(SystemExit, match="exists already"):
        open_people(users, None, [("lin", ("viewer",))], [], 24)


def test_an_api_token_reads_the_acting_role_too(person: dict[str, Any]) -> None:
    """The one place: a bearer session resolves its role the same way (and starts in the account's own role)."""
    users = person["users"]
    _flag(person, "on")
    token, sess = users.new_session(users.get("mei"), via="api")
    users.set_acting(sess, "admin")
    api = TestClient(person["app"], headers={"Authorization": f"Bearer {token}"})
    got = users.session(token, api=True)
    assert got is not None and got.user.role == "admin" and got.acting_from == "viewer" and got.user.username == "mei"
    assert api.get("/api/v1/studies").status_code in (200, 403)  # answered as the acting role, never a server error


def test_the_delegation_logs_standing_follows_the_person_not_the_role(person: dict[str, Any]) -> None:
    """A person the log names PI is PI acting as investigator (the standing is by user name); another person acting
    as investigator, on no log, is not."""
    from console.teamstore import TeamStore

    users = person["users"]
    users.create("kai", "viewer", PW, "kai@hospa.test")
    users.grant_roles("kai", ["investigator"], allowed=True)
    team = TeamStore()
    team.add_entry("GZQO", username="mei", name="Dr Mei", role="pi", tasks=(), start="2026-01-01", end=None,
                   training_day="2026-01-01", training_ref=None, by="stw", at="2026-01-01T00:00:00+00:00")  # fmt: skip
    team.close()
    _flag(person, "on")
    url = "/studies/GZQO/not-matched/sample"  # the log's PI alone (the design table: lpi Y, pi -)
    mei, mcsrf = login(person["app"], "mei", PW)
    kai, kcsrf = login(person["app"], "kai", PW)
    assert mei.get(url, follow_redirects=False).status_code == 403  # a viewer
    mei.post("/role", data={"csrf": mcsrf, "role": "investigator"}, follow_redirects=False)
    kai.post("/role", data={"csrf": kcsrf, "role": "investigator"}, follow_redirects=False)
    assert mei.get(url, follow_redirects=False).status_code not in (401, 403)
    assert kai.get(url, follow_redirects=False).status_code == 403


@pytest.mark.usefixtures("held_dir")
def test_an_account_that_may_act_in_a_protected_role_is_held_as_protected(person: dict[str, Any]) -> None:
    """The review of D-877 (D-719): an account whose own role is a viewer's but that may act as an administrator or
    an investigator is a protected account: one administrator alone cannot reset its password and sign in as it."""
    from console.account_rules import protected, protected_account

    users = person["users"]
    assert not protected("viewer") and protected_account(users, "mei")
    users.create("ann", "viewer", PW)
    assert not protected_account(users, "ann")
    c, csrf = login(person["app"], "admin", ADMIN_PW)
    for name in ("mei", "ann"):  # the administrator resets each password alone (no second person on this box)
        r = c.post("/ops/users", data={"csrf": csrf, "action": "reset", "username": name, "confirm": "yes"},
                   follow_redirects=False)  # fmt: skip
        assert r.status_code == 303
    # one factor at a time (D-719): the authenticator of the account that may act as an administrator is now held for
    # anyone but its holder, so the same administrator cannot also set it and sign in as the person
    assert users.factor_held("mei", "totp") is not None
    assert users.factor_held("ann", "totp") is None  # a viewer's account, as before


def test_a_stale_acting_role_never_comes_back_unannounced(person: dict[str, Any]) -> None:
    users = person["users"]
    _flag(person, "on")
    c, csrf = login(person["app"], "mei", PW)
    c.post("/role", data={"csrf": csrf, "role": "admin"}, follow_redirects=False)
    _flag(person, "off")
    assert c.get("/ops/users", follow_redirects=False).status_code == 403  # read off: the acting role is ended
    _flag(person, "on")
    assert c.get("/ops/users", follow_redirects=False).status_code == 403  # not back without a new, audited switch
    assert [e["detail"]["to"] for e in _events(person, "role.acting")] == ["admin"]
    assert users.db.fetchval("SELECT count(*) FROM sessions WHERE acting_role IS NOT NULL") == 0


def test_the_flags_page_says_a_test_box_flag_is_refused(person: dict[str, Any],
                                                        monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    c, csrf = login(person["app"], "admin", ADMIN_PW)
    r = c.post("/ops/flags", data={"csrf": csrf, "name": "steps.acting_role", "value": "on", "reason": "a reason",
                                   "confirm": "yes", "old": ""}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 400 and "test box only" in r.text


# ---------------------------------------------------------------------------------- STEPS-ROLE-2 (D-1151)
def _sign_in(app: Any, user: str, pw: str, role: str = "") -> tuple[TestClient, str, Any]:
    import re

    c = TestClient(app)
    page = c.get("/login").text
    token = re.search(r'name="login_csrf" value="([^"]+)"', page)
    assert token
    data = {"username": user, "password": pw, "login_csrf": token.group(1), **({"role": role} if role else {})}
    r = c.post("/login", data=data, follow_redirects=False)
    assert r.status_code == 303, r.text
    home = c.get("/").text
    csrf = re.search(r'name="csrf" value="([^"]+)"', home)
    assert csrf
    return c, csrf.group(1), page


def test_the_sign_in_page_offers_the_boxs_roles_only_while_acting_is_on(person: dict[str, Any]) -> None:
    import re

    assert 'data-testid="login-role"' not in TestClient(person["app"]).get("/login").text  # the flag off: none
    _flag(person, "on")
    page = TestClient(person["app"]).get("/login").text
    offered = re.findall(r'<option value="([a-z]+)">', page.split('data-testid="login-role"')[1].split("</select>")[0])
    assert offered == ["admin", "coordinator", "investigator", "viewer", "steward"]  # the roles the box gave, in order


@pytest.mark.usefixtures("held_dir")
def test_a_person_signs_in_already_acting_as_the_chosen_role(person: dict[str, Any]) -> None:
    _flag(person, "on")
    c, _csrf, _page = _sign_in(person["app"], "mei", PW, "admin")
    assert c.get("/ops/users", follow_redirects=False).status_code == 200  # acting as the administrator
    (ev,) = [e for e in _events(person, "role.acting") if e["detail"].get("at") == "sign-in"]
    assert ev["actor"] == "console:mei" and ev["detail"]["from"] == "viewer" and ev["detail"]["to"] == "admin"
    c2, _c2, _p = _sign_in(person["app"], "mei", PW)  # the next sign-in, no role chosen: the last one
    assert c2.get("/ops/users", follow_redirects=False).status_code == 200


def test_a_role_not_held_cannot_be_chosen_by_a_forged_form_value(person: dict[str, Any]) -> None:
    _flag(person, "on")
    users = person["users"]
    c, _csrf, _page = _sign_in(person["app"], "mei", PW, "privacy")  # mei does not hold privacy
    assert c.get("/ops/users", follow_redirects=False).status_code == 403  # her own role, a viewer's
    assert users.last_role("mei") == "" and not _events(person, "role.acting")
    c3, _c3, _p = _sign_in(person["app"], "mei", PW, "nonsense")
    assert c3.get("/ops/users", follow_redirects=False).status_code == 403


def test_a_switch_keeps_the_session_and_lands_on_the_roles_home_page(person: dict[str, Any]) -> None:
    _flag(person, "on")
    users = person["users"]
    c, csrf, _page = _sign_in(person["app"], "mei", PW)
    before = dict(c.cookies)
    c.post("/lang", data={"csrf": csrf, "lang": "ja", "back": "/"}, follow_redirects=False)
    r = c.post("/role", data={"csrf": csrf, "role": "coordinator"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"  # the role's home page
    assert dict(c.cookies) == before  # the same session: no new sign-in, no second factor
    home = c.get("/", follow_redirects=True)
    assert home.status_code == 200 and 'lang="ja"' in home.text  # in the same language
    assert users.last_role("mei") == "coordinator"
    assert [e["detail"]["to"] for e in _events(person, "role.acting")] == ["coordinator"]


def test_a_page_the_acting_role_may_not_open_offers_the_switch(person: dict[str, Any]) -> None:
    _flag(person, "on")
    c, _csrf, _page = _sign_in(person["app"], "mei", PW)
    r = c.get("/ops/flags")  # the administrator's page, refused to a viewer
    assert r.status_code == 403 and 'data-testid="problem-role-switch"' in r.text
    assert 'value="admin"' in r.text and 'name="back" value="/ops/flags"' in r.text


@pytest.mark.usefixtures("held_dir")
def test_the_chosen_role_waits_for_the_second_factor(person: dict[str, Any]) -> None:
    """The review of D-1151 (1): with TOTP on, the role chosen on the sign-in page is neither remembered nor audited
    on the password alone; only once the code is right."""
    import dataclasses
    import re
    from datetime import UTC, datetime

    from console import totp

    _flag(person, "on")
    app, users = person["app"], person["users"]
    ident = app.state.identity
    ident.settings = dataclasses.replace(ident.settings, mfa="totp")
    enrol = users.issue_enrol_code("mei")
    c = TestClient(app, base_url="https://testserver")
    token = re.search(r'name="login_csrf" value="([^"]+)"', c.get("/login").text)
    assert token
    form = {"username": "mei", "password": PW, "login_csrf": token.group(1), "role": "admin"}
    r = c.post("/login", data=form, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login/totp", r.text
    assert users.last_role("mei") == "" and not _events(person, "role.acting")  # the password alone: nothing yet
    page = c.get("/login/totp").text
    key = re.search(r'id="totp-key"[^>]*value="([A-Z2-7 ]+)"', page)
    mfa = re.search(r'name="mfa_csrf" value="([^"]+)"', page)
    assert key and mfa
    bad = c.post("/login/totp", data={"code": "000000", "mfa_csrf": mfa.group(1), "enrol_code": enrol},
                 follow_redirects=False)  # fmt: skip
    assert bad.status_code != 303 or bad.headers["location"] != "/"
    assert users.last_role("mei") == "" and not _events(person, "role.acting")  # a wrong code: still nothing
    code = totp.totp(key.group(1).replace(" ", ""), datetime.now(UTC).timestamp())
    r = c.post("/login/totp", data={"code": code, "mfa_csrf": mfa.group(1), "enrol_code": enrol},
               follow_redirects=False)  # fmt: skip
    assert r.status_code == 303, r.text
    assert users.last_role("mei") == "admin"
    (ev,) = [e for e in _events(person, "role.acting") if e["detail"].get("at") == "sign-in"]
    assert ev["detail"]["from"] == "viewer" and ev["detail"]["to"] == "admin"
    assert c.get("/ops/users", follow_redirects=False).status_code == 200  # the session acts as the administrator


def test_a_remembered_role_taken_away_or_switched_off_is_forgotten(person: dict[str, Any]) -> None:
    """The review of D-1151 (2): a remembered role the account no longer holds, or kept while acting was off, never
    comes back at a later sign-in."""
    users = person["users"]
    _flag(person, "on")
    assert users.remember_role("mei", "admin") and users.last_role("mei") == "admin"
    users.grant_roles("mei", ["coordinator"], allowed=True)  # admin taken away
    assert users.last_role("mei") == ""
    assert users.remember_role("mei", "coordinator")
    _flag(person, "off")
    _token, sess = users.new_session(users.get("mei"))
    assert sess.user.role == "viewer" and users.last_role("mei") == ""  # acting off: forgotten, not kept for later
    _flag(person, "on")
    _token, sess = users.new_session(users.get("mei"))
    assert sess.user.role == "viewer"  # the flag back on brings no role back unannounced


def test_an_api_token_never_starts_acting_and_a_page_session_that_does_is_audited(person: dict[str, Any]) -> None:
    """The review of D-1151 (3): the remembered role is a page session's; an API token starts in the account's own
    role. A page session that starts acting writes a ``role.acting`` event (at session-start)."""
    users = person["users"]
    _flag(person, "on")
    assert users.remember_role("mei", "admin")
    _token, api = users.new_session(users.get("mei"), via="api")
    assert api.user.role == "viewer" and not _events(person, "role.acting")
    _c, _csrf, _page = _sign_in(person["app"], "mei", PW)
    (ev,) = _events(person, "role.acting")
    assert ev["actor"] == "console:mei" and ev["detail"] == {"user": "mei", "from": "viewer", "to": "admin",
                                                             "at": "session-start"}  # fmt: skip


def test_a_refused_change_offers_the_switch_without_a_way_back_to_repeat_it(person: dict[str, Any]) -> None:
    """The review of D-1151 (LOW): the switch on a refused page goes back only to a page read (GET), never to repeat
    a change."""
    _flag(person, "on")
    c, csrf, _page = _sign_in(person["app"], "mei", PW)
    r = c.post("/ops/flags", data={"csrf": csrf, "name": "x", "value": "on", "reason": "r"}, follow_redirects=False)
    assert r.status_code == 403 and 'data-testid="problem-role-switch"' in r.text
    assert 'name="back"' not in r.text.split('data-testid="problem-role-switch"')[1].split("</form>")[0]


def test_the_sign_in_page_offers_every_accounts_own_role_too(person: dict[str, Any]) -> None:
    """The review of D-1151 (LOW): the page cannot know who signs in, so it offers each account's own role as well
    (an account holding privacy only may choose it); still none while acting is off."""
    import re

    person["users"].create("lin", "privacy", PW, "lin@hospa.test")
    _flag(person, "on")
    page = TestClient(person["app"]).get("/login").text
    offered = re.findall(r'<option value="([a-z]+)">', page.split('data-testid="login-role"')[1].split("</select>")[0])
    assert "privacy" in offered and "admin" in offered
