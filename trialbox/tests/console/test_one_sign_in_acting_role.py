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
