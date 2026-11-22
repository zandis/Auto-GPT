"""NEW-SEC-3 (D-719): nobody holds both factors of a patient-data, steward, privacy or administrator account.

The owner's decision of 2026-11-14 (the deep review's SEC-02): (b) everywhere, the administrator may set a first
password OR give an enrolment code / reset the authenticator, never both within 30 days unless the holder signed in
in between, and a new such account's first sign-in is the holder's, with the enrolment code; (c) where the box has a
second person (a steward or another administrator), creating such an account, changing its studies, or resetting a
factor takes effect only when that person confirms, and nobody confirms their own request; (a) the holder is told at
sign-in, and the steward and the study's PI by mail.

The review's "shadow" sequence (the administrator adds ``shadow``, a coordinator of every study, is shown its
password, and reads a candidate page as ``shadow``) fails here at the step the rule names: no password is shown.
"""

from __future__ import annotations

import json
import re
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from console import totp
from console.account_rules import CLASS_OF, account_class, protected
from console.auth import UserStore
from fastapi.testclient import TestClient
from tb_common.authz import MATRIX, permit

from tests.console.test_console_app import ADMIN_PW, VIEWER_PW
from tests.console.test_identity import Clock, _app, _code_page, _events, _password

CRC_PW = "crc-own-password-0001"
STEWARD_PW = "steward-password-0001"


def _box(tmp_path: Path, *, steward: bool, **env: str) -> tuple[Any, UserStore, Path, Clock]:
    """The console with its workspace (``/account``: a password someone else set is replaced there first)."""
    clock = Clock()
    app, users, audit_dir = _app(tmp_path, clock, **{"TB_CONSOLE_WORKSPACE": "on", **env})
    if steward:
        users.create("stew", "steward", STEWARD_PW, "stew@hospa.test")
    return app, users, audit_dir, clock


def _signin(app: Any, user: str, pw: str) -> tuple[TestClient, str]:
    c = TestClient(app, base_url="https://testserver")
    r = _password(c, user, pw)
    assert r.status_code == 303, r.text
    page = c.get("/").text  # a password someone else set leads to /account first (D-279)
    m = re.search(r'name="csrf" value="([^"]+)"', page)
    assert m, page
    setattr(c, "first_page", page)  # noqa: B010 - a notice is read once, on this page
    return c, m.group(1)


def _add(c: TestClient, csrf: str, name: str, role: str, studies: str = "") -> httpx.Response:
    data = {
        "csrf": csrf,
        "action": "add",
        "username": name,
        "role": role,
        "affiliation": "hospital",
        "studies": studies,
    }
    r: httpx.Response = c.post("/ops/users", data=data, follow_redirects=True)
    return r


def _code_in(text: str) -> str:
    m = re.search(r'data-testid="enrol-code-value"[^>]*value="([a-z0-9-]+)"', text)
    m = m or re.search(r'value="([a-z0-9-]+)" data-testid="identity-code-value"', text)  # /ops/identity's
    return m.group(1) if m else ""


def _redeem(app: Any, user: str, code: str, pw: str) -> httpx.Response:
    c = TestClient(app, base_url="https://testserver")
    tok = re.search(r'name="login_csrf" value="([^"]+)"', c.get("/enrol").text)
    assert tok
    form = {"username": user, "enrol_code": code, "password": pw, "password2": pw, "login_csrf": tok.group(1)}
    r: httpx.Response = c.post("/enrol", data=form, follow_redirects=False)
    setattr(r, "client", c)  # noqa: B010
    return r


def _requests(c: TestClient) -> str:
    r = c.get("/ops/accounts/requests")
    assert r.status_code == 200, r.text
    text: str = r.text
    return text


def _request_ids(text: str) -> list[str]:
    return re.findall(r'data-request="([a-f0-9]+)"', text)


# ---------------------------------------------------------------------------------------------- the matrix
def test_the_matrix_has_a_row_for_each_class_of_account_and_for_confirming() -> None:
    for cls in ("patient-data", "steward", "privacy", "admin", "aggregate"):
        row = f"account.create.{cls}"
        assert row in MATRIX
        assert permit("admin", row).allowed and not permit("coordinator", row).allowed
    assert permit("admin", "account.confirm").allowed and permit("steward", "account.confirm").allowed
    assert not any(permit(r, "account.confirm").allowed for r in ("coordinator", "investigator", "viewer", "cro"))
    assert set(CLASS_OF) == set(MATRIX_ROLES_FROM_FILE())
    assert {account_class(r) for r in ("coordinator", "investigator")} == {"patient-data"}
    assert protected("steward") and protected("privacy") and protected("admin") and protected("coordinator")
    assert not protected("viewer") and not protected("cro")


def MATRIX_ROLES_FROM_FILE() -> list[str]:
    from tb_common.authz import MATRIX_ROLES

    return list(MATRIX_ROLES)


# ---------------------------------------------------------------------------------------------- one person: (b)
def test_the_shadow_sequence_fails_on_a_one_person_box_no_password_is_shown(tmp_path: Path) -> None:
    app, users, audit_dir, clock = _box(tmp_path, steward=False)
    admin, csrf = _signin(app, "admin", ADMIN_PW)
    r = _add(admin, csrf, "shadow", "coordinator")
    assert r.status_code == 200
    assert 'data-testid="users-pw-field"' not in r.text  # the step the rule names: no password for the creator
    code = _code_in(r.text)
    assert code  # only the enrolment code, once
    assert users.get("shadow") is not None and users.must_change("shadow") is False
    # nobody knows a password of the account: the code is the only way in, and it sets the holder's own
    for guess in (code, "", ADMIN_PW):
        assert _password(TestClient(app), "shadow", guess).status_code == 401
    ev = [e for e in _events(audit_dir) if e["event"] == "console.user"]
    assert ev[-1]["detail"]["action"] == "create" and ev[-1]["detail"]["class"] == "patient-data"
    assert ev[-1]["detail"]["confirmed_by"] == ""
    assert code not in json.dumps(_events(audit_dir))
    # the holder signs in with the code and chooses a password: the steward is told (none here: the audit says so)
    clock.tick(minutes=5)
    r = _redeem(app, "shadow", code, CRC_PW)
    assert r.status_code == 303, r.text
    c = r.client  # type: ignore[attr-defined]
    first = c.get("/")
    assert first.status_code == 200  # signed in
    page = first.text
    assert 'data-testid="account-notice"' in page and "opened" in page  # "your account was opened at <time> ..."
    assert _password(TestClient(app), "shadow", CRC_PW).status_code == 303
    opened = [e for e in _events(audit_dir) if e["event"] == "console.account_opened"]
    assert opened and opened[-1]["actor"] == "console:shadow" and opened[-1]["detail"]["opened_by"] == "admin"
    # the code is spent: a second try shows when it was used, and is audited
    r = _redeem(app, "shadow", code, "another-password-0002")
    assert r.status_code == 401 and 'data-testid="enrol-code-used"' in r.text
    assert any(e["event"] == "console.enrol_code_reused" for e in _events(audit_dir))
    assert _password(TestClient(app), "shadow", CRC_PW).status_code == 303  # the holder's password stands


def test_an_aggregate_account_is_made_as_before(tmp_path: Path) -> None:
    app, users, _, _ = _box(tmp_path, steward=True)
    admin, csrf = _signin(app, "admin", ADMIN_PW)
    r = _add(admin, csrf, "reader", "viewer")
    assert 'data-testid="users-pw-field"' in r.text and users.get("reader") is not None
    assert _request_ids(_requests(admin)) == []


# ---------------------------------------------------------------------------------------------- 30 days: (b)
def test_the_administrator_never_holds_both_factors_within_30_days(tmp_path: Path) -> None:
    app, users, audit_dir, clock = _box(tmp_path, steward=False)
    users.create("crc", "coordinator", CRC_PW, "crc@hospa.test")  # made before the rule: it keeps its factors
    admin, csrf = _signin(app, "admin", ADMIN_PW)
    r = admin.post("/ops/users", data={"csrf": csrf, "action": "reset", "username": "crc", "confirm": "yes"})
    assert r.status_code == 200 and 'data-testid="users-pw-field"' in r.text  # the first reset: the rule starts now
    pw = re.search(r'data-testid="users-pw-field"[^>]*value="([^"]+)"', r.text) or re.search(
        r'value="([^"]+)" data-testid="users-pw-field"', r.text
    )
    assert pw
    r = admin.post("/ops/identity", data={"csrf": csrf, "action": "enrol_code", "username": "crc"})
    assert r.status_code == 409 and 'data-testid="factor-held"' in r.text  # the other factor: refused
    r = admin.post("/ops/identity", data={"csrf": csrf, "action": "reset_totp", "username": "crc", "confirm": "yes"})
    assert r.status_code == 409
    refused = [e for e in _events(audit_dir) if e["event"] == "console.factor_refused"]
    assert refused and refused[-1]["detail"]["factor"] == "totp" and refused[-1]["detail"]["held"] == "password"
    clock.tick(days=29)
    admin, csrf = _signin(app, "admin", ADMIN_PW)
    assert (
        admin.post("/ops/identity", data={"csrf": csrf, "action": "enrol_code", "username": "crc"}).status_code == 409
    )
    # the holder signs in with the other factor: the administrator may then reset the authenticator
    clock.tick(hours=1)
    _signin(app, "crc", pw.group(1))
    admin, csrf = _signin(app, "admin", ADMIN_PW)
    r = admin.post("/ops/identity", data={"csrf": csrf, "action": "enrol_code", "username": "crc"})
    assert r.status_code == 200
    # and now a password reset is refused for 30 days, unless the holder signs in
    r = admin.post("/ops/users", data={"csrf": csrf, "action": "reset", "username": "crc", "confirm": "yes"})
    assert r.status_code == 409
    clock.tick(days=31)
    admin, csrf = _signin(app, "admin", ADMIN_PW)
    r = admin.post("/ops/users", data={"csrf": csrf, "action": "reset", "username": "crc", "confirm": "yes"})
    assert r.status_code == 200


def test_a_new_account_cannot_be_given_a_password_before_its_holder_signs_in(tmp_path: Path) -> None:
    app, _, _, clock = _box(tmp_path, steward=False)
    admin, csrf = _signin(app, "admin", ADMIN_PW)
    code = _code_in(_add(admin, csrf, "shadow", "coordinator").text)
    assert code
    r = admin.post("/ops/users", data={"csrf": csrf, "action": "reset", "username": "shadow", "confirm": "yes"})
    assert r.status_code == 409 and 'data-testid="users-pw-field"' not in r.text
    clock.tick(days=31)  # a code is good for a day; a password with a code nobody used is still refused
    admin, csrf = _signin(app, "admin", ADMIN_PW)
    r = admin.post("/ops/users", data={"csrf": csrf, "action": "reset", "username": "shadow", "confirm": "yes"})
    assert r.status_code == 409
    # a new code is the same factor: allowed, and the holder still chooses the password
    r = admin.post("/ops/identity", data={"csrf": csrf, "action": "enrol_code", "username": "shadow"})
    assert r.status_code == 200
    assert _redeem(app, "shadow", _code_in(r.text), CRC_PW).status_code == 303


def test_the_code_expires_after_the_declared_hours(tmp_path: Path) -> None:
    app, _, _, clock = _box(tmp_path, steward=False, TB_CONSOLE_ENROL_CODE_HOURS="2")
    admin, csrf = _signin(app, "admin", ADMIN_PW)
    code = _code_in(_add(admin, csrf, "shadow", "coordinator").text)
    clock.tick(hours=2, minutes=1)
    r = _redeem(app, "shadow", code, CRC_PW)
    assert r.status_code == 401 and 'data-testid="enrol-code-used"' not in r.text


# ---------------------------------------------------------------------------------------------- notices: (a)
def test_the_holder_is_told_at_sign_in_and_the_steward_by_mail(tmp_path: Path) -> None:
    app, users, audit_dir, clock = _box(tmp_path, steward=True)
    users.create("crc", "coordinator", CRC_PW, "crc@hospa.test")
    stew, scsrf = _signin(app, "stew", STEWARD_PW)
    admin, csrf = _signin(app, "admin", ADMIN_PW)
    r = admin.post("/ops/users", data={"csrf": csrf, "action": "reset", "username": "crc", "confirm": "yes"})
    assert r.status_code == 200 and 'data-testid="account-requested"' in r.text  # a second person: it waits
    assert 'data-testid="users-pw-field"' not in r.text
    assert _password(TestClient(app), "crc", CRC_PW).status_code == 303  # nothing changed yet
    (rid,) = _request_ids(_requests(stew))
    r = stew.post("/ops/accounts/requests", data={"csrf": scsrf, "request": rid, "decision": "confirm"})
    assert r.status_code == 200
    pw = re.search(r'data-testid="request-secret"[^>]*value="([^"]+)"', r.text)
    assert pw  # shown to the confirming person, not to the one who asked
    clock.tick(minutes=1)
    holder, _ = _signin(app, "crc", pw.group(1))
    page = getattr(holder, "first_page")  # noqa: B009
    assert 'data-testid="account-notice"' in page and "admin" in page  # reset by <admin> at <time>
    assert 'data-testid="account-notice"' not in holder.get("/").text  # told once
    notices = app.state.test_backend.notices
    assert any("stew@hospa.test" in to and "crc" in body for _kind, to, _subj, body in notices)
    ev = [e for e in _events(audit_dir) if e["event"] == "console.account_confirmed"]
    assert ev and ev[-1]["actor"] == "console:stew" and ev[-1]["detail"]["requested_by"] == "admin"


# ---------------------------------------------------------------------------------------------- a second person: (c)
def test_the_shadow_sequence_fails_where_a_second_person_exists(tmp_path: Path) -> None:
    app, users, audit_dir, _ = _box(tmp_path, steward=True)
    admin, csrf = _signin(app, "admin", ADMIN_PW)
    r = _add(admin, csrf, "shadow", "coordinator")
    assert 'data-testid="account-requested"' in r.text
    assert not _code_in(r.text) and 'data-testid="users-pw-field"' not in r.text
    assert users.get("shadow") is None  # nothing exists until the second person confirms
    (rid,) = _request_ids(_requests(admin))
    r = admin.post("/ops/accounts/requests", data={"csrf": csrf, "request": rid, "decision": "confirm"})
    assert r.status_code == 403 and users.get("shadow") is None  # nobody confirms their own request
    stew, scsrf = _signin(app, "stew", STEWARD_PW)
    r = stew.post("/ops/accounts/requests", data={"csrf": scsrf, "request": rid, "decision": "confirm"})
    assert r.status_code == 200 and users.get("shadow") is not None
    code = re.search(r'data-testid="request-secret"[^>]*value="([a-z0-9-]+)"', r.text)
    assert code  # the enrolment code goes to the confirming person
    assert 'data-testid="request-secret"' not in admin.get("/ops/users").text
    r = stew.post("/ops/accounts/requests", data={"csrf": scsrf, "request": rid, "decision": "confirm"})
    assert r.status_code == 409  # once
    ev = [e for e in _events(audit_dir) if e["event"] == "console.user" and e["detail"].get("user") == "shadow"]
    assert ev and ev[-1]["detail"]["confirmed_by"] == "stew" and ev[-1]["actor"] == "console:admin"
    assert code.group(1) not in json.dumps(_events(audit_dir))


def test_a_refused_request_changes_nothing_and_scope_waits_too(tmp_path: Path) -> None:
    app, users, audit_dir, _ = _box(tmp_path, steward=True)
    users.create("crc", "coordinator", CRC_PW)
    admin, csrf = _signin(app, "admin", ADMIN_PW)
    data = {"csrf": csrf, "action": "scope", "username": "crc", "affiliation": "hospital", "studies": "GZQO"}
    r = admin.post("/ops/users", data=data)
    assert r.status_code == 200 and 'data-testid="account-requested"' in r.text
    crc = users.get("crc")
    assert crc is not None and crc.studies == ()
    stew, scsrf = _signin(app, "stew", STEWARD_PW)
    (rid,) = _request_ids(_requests(stew))
    r = stew.post("/ops/accounts/requests", data={"csrf": scsrf, "request": rid, "decision": "refuse"})
    assert r.status_code == 200 and _request_ids(_requests(stew)) == []
    crc = users.get("crc")
    assert crc is not None and crc.studies == ()
    assert [e["detail"]["kind"] for e in _events(audit_dir) if e["event"] == "console.account_refused"] == ["scope"]
    # a viewer's scope is not held: aggregate accounts are as before
    users.create("reader", "viewer", VIEWER_PW)
    r = admin.post("/ops/users", data={**data, "username": "reader"}, follow_redirects=False)
    assert r.status_code == 303


def test_the_steward_the_administrator_opened_counts_once_its_holder_used_the_code(tmp_path: Path) -> None:
    """The review of D-719 (critical 2): a box's first steward is opened by the administrator; once its holder used
    the code, it is the administrator's second person, and every confirmation says who opened the confirming
    account (an account one person opened alone shows as such: misuse is seen, not impossible)."""
    app, users, audit_dir, clock = _box(tmp_path, steward=False)
    admin, csrf = _signin(app, "admin", ADMIN_PW)
    code = _code_in(_add(admin, csrf, "stew2", "steward").text)
    assert code and users.get("stew2") is not None  # one person: (b) alone, a code and no password
    r = _add(admin, csrf, "shadow", "coordinator")  # before its holder used it, the code is no second person
    assert 'data-testid="account-requested"' not in r.text and _code_in(r.text)
    clock.tick(minutes=1)
    assert _redeem(app, "stew2", code, "stew2-own-password-01").status_code == 303
    r = _add(admin, csrf, "shadow2", "coordinator")
    assert 'data-testid="account-requested"' in r.text and users.get("shadow2") is None  # now it waits
    stew, scsrf = _signin(app, "stew2", "stew2-own-password-01")
    (rid,) = _request_ids(_requests(stew))
    assert (
        stew.post("/ops/accounts/requests", data={"csrf": scsrf, "request": rid, "decision": "confirm"}).status_code
        == 200
    )
    ev = [e for e in _events(audit_dir) if e["event"] == "console.account_confirmed"]
    assert ev[-1]["detail"]["confirmer_opened_by"] == "admin"


def test_a_disabled_or_expired_account_is_held_as_any_other(tmp_path: Path) -> None:
    """The review of D-719 (critical 1): a reset of a disabled account went the old way (password shown, no record),
    and enabling it then let the administrator give the other factor."""
    app, users, audit_dir, _ = _box(tmp_path, steward=False)
    users.create("crc", "coordinator", CRC_PW, "crc@hospa.test")
    admin, csrf = _signin(app, "admin", ADMIN_PW)
    users.disable("crc")
    r = admin.post("/ops/users", data={"csrf": csrf, "action": "reset", "username": "crc", "confirm": "yes"})
    assert r.status_code == 200 and 'data-testid="users-pw-field"' in r.text
    assert users.factor_held("crc", "totp") is not None  # on record, whatever the account's state
    users.enable("crc")
    r = admin.post("/ops/identity", data={"csrf": csrf, "action": "enrol_code", "username": "crc"})
    assert r.status_code == 409
    users.create("old", "coordinator", CRC_PW)
    users.set_scope("old", "hospital", "", "2020-01-01")  # past its end date
    r = admin.post("/ops/users", data={"csrf": csrf, "action": "reset", "username": "old", "confirm": "yes"})
    assert r.status_code == 200 and users.factor_held("old", "totp") is not None
    assert any(e["event"] == "console.factor_refused" for e in _events(audit_dir))


def test_disabling_the_steward_does_not_void_the_second_person(tmp_path: Path) -> None:
    """The review of D-719 (critical 3): the request waits for the disabled steward, who is still told by mail."""
    app, users, _, _ = _box(tmp_path, steward=True)
    admin, csrf = _signin(app, "admin", ADMIN_PW)
    users.disable("stew")
    r = _add(admin, csrf, "shadow", "coordinator")
    assert 'data-testid="account-requested"' in r.text and not _code_in(r.text) and users.get("shadow") is None
    users.create("crc", "coordinator", CRC_PW, "crc@hospa.test")
    users.enable("stew")
    stew, _ = _signin(app, "stew", STEWARD_PW)
    rids = _request_ids(_requests(stew))
    assert len(rids) == 1
    users.disable("stew")
    users.create("stew9", "steward", STEWARD_PW, "stew9@hospa.test")  # another steward confirms meanwhile
    s9, csrf9 = _signin(app, "stew9", STEWARD_PW)
    r = s9.post("/ops/accounts/requests", data={"csrf": csrf9, "request": rids[0], "decision": "confirm"})
    assert r.status_code == 200
    code = re.search(r'data-testid="request-secret"[^>]*value="([a-z0-9-]+)"', r.text)
    assert code and _redeem(app, "shadow", code.group(1), CRC_PW).status_code == 303  # the holder opens it
    notices = app.state.test_backend.notices
    assert any("stew@hospa.test" in to for _k, to, _s, _b in notices)  # the disabled steward was told too


def test_a_confirmation_that_cannot_be_applied_is_failed_not_confirmed(tmp_path: Path) -> None:
    app, users, audit_dir, _ = _box(tmp_path, steward=True)
    admin, csrf = _signin(app, "admin", ADMIN_PW)
    users.create("crc", "coordinator", CRC_PW)
    users.create("reader", "viewer", VIEWER_PW)
    r = admin.post(
        "/ops/users", data={"csrf": csrf, "action": "scope", "username": "crc", "affiliation": "smo", "studies": "GZQO"}
    )
    assert 'data-testid="account-requested"' in r.text
    stew, scsrf = _signin(app, "stew", STEWARD_PW)
    (rid,) = _request_ids(_requests(stew))
    users.db.execute("DELETE FROM users WHERE username = ?", ("crc",))  # the account is gone in between
    r = stew.post("/ops/accounts/requests", data={"csrf": scsrf, "request": rid, "decision": "confirm"})
    assert r.status_code == 409
    req = users.get_request(rid)
    assert req is not None and req["state"] == "failed"
    assert not any(e["event"] == "console.account_confirmed" for e in _events(audit_dir))
    assert any(e["event"] == "console.account_refused" and e["detail"].get("reason") == "not_applied"
               for e in _events(audit_dir))  # fmt: skip


def test_only_the_spent_code_learns_that_it_was_used(tmp_path: Path) -> None:
    """The review of D-719 (minor): "used" told anyone which accounts were opened by code, and when."""
    app, _, audit_dir, clock = _box(tmp_path, steward=False)
    admin, csrf = _signin(app, "admin", ADMIN_PW)
    code = _code_in(_add(admin, csrf, "shadow", "coordinator").text)
    clock.tick(minutes=1)
    assert _redeem(app, "shadow", code, CRC_PW).status_code == 303
    r = _redeem(app, "shadow", "aaaa-bbbb-cccc-dddd", "another-password-0002")
    assert r.status_code == 401 and 'data-testid="enrol-code-used"' not in r.text  # a guess learns nothing
    assert not any(e["event"] == "console.enrol_code_reused" for e in _events(audit_dir))
    r = _redeem(app, "shadow", code, "another-password-0002")
    assert r.status_code == 401 and 'data-testid="enrol-code-used"' in r.text


def test_a_role_without_the_row_may_not_confirm(tmp_path: Path) -> None:
    app, users, _, _ = _box(tmp_path, steward=True)
    users.create("crc", "coordinator", CRC_PW)
    admin, csrf = _signin(app, "admin", ADMIN_PW)
    _add(admin, csrf, "shadow", "coordinator")
    (rid,) = _request_ids(_requests(admin))
    crc, ccsrf = _signin(app, "crc", CRC_PW)
    assert crc.get("/ops/accounts/requests").status_code == 403
    r = crc.post("/ops/accounts/requests", data={"csrf": ccsrf, "request": rid, "decision": "confirm"})
    assert r.status_code == 403 and users.get("shadow") is None


# ---------------------------------------------------------------------------------------------- with TOTP on
def test_with_totp_on_the_holder_enrols_on_their_own_device_after_the_code(tmp_path: Path) -> None:
    app, users, audit_dir, clock = _box(tmp_path, steward=False, TB_CONSOLE_MFA="totp")
    from tests.console.test_identity import _enrol

    admin, _ = _enrol(app, clock, "admin", ADMIN_PW)
    csrf = re.search(r'name="csrf" value="([^"]+)"', admin.get("/ops/users").text)
    assert csrf
    code = _code_in(_add(admin, csrf.group(1), "shadow", "coordinator").text)
    assert code
    clock.tick(seconds=30)
    r = _redeem(app, "shadow", code, CRC_PW)
    assert r.status_code == 303 and r.headers["location"] == "/login/totp"
    c = r.client  # type: ignore[attr-defined]
    key, mfa = _code_page(c)
    assert key  # a new authenticator, set up by the holder; the code is not asked again
    r = c.post("/login/totp", data={"code": totp.totp(key, clock.unix()), "mfa_csrf": mfa}, follow_redirects=False)
    assert r.status_code == 303 and c.get(r.headers["location"]).status_code == 200  # signed in
    assert users.totp_state("shadow")[0] is not None
    kinds = [e["detail"]["kind"] for e in _events(audit_dir) if e["event"] == "console.totp_enrolled"]
    assert kinds[-1] == "first"


@pytest.mark.parametrize("days", [0, 29])
def test_a_reset_of_the_authenticator_waits_for_the_holder_after_a_password_reset(tmp_path: Path, days: int) -> None:
    """The store says the same as the pages, for the command-line's sake (the record says what the command line
    does)."""
    clock = Clock()
    users = UserStore(clock=clock)
    users.create("crc", "coordinator", CRC_PW)
    users.note_factor_reset("crc", "password", "admin")
    clock.tick(days=days)
    assert users.factor_held("crc", "totp") is not None
    clock.t += timedelta(days=31 - days)
    assert users.factor_held("crc", "totp") is None


def test_the_command_line_records_its_resets_and_holds_the_same_rule(tmp_path: Path, monkeypatch: Any) -> None:
    from console import cli

    users = UserStore(clock=Clock())
    users.create("crc", "coordinator", CRC_PW)
    users.create("reader", "viewer", VIEWER_PW)
    monkeypatch.setattr(cli, "UserStore", lambda: users)
    monkeypatch.setenv("TB_AUDIT_DIR", str(tmp_path / "audit"))
    assert cli.main(["reset-password", "crc"]) == 0
    assert cli.main(["reset-totp", "crc"]) == 2 and cli.main(["enrol-code", "crc"]) == 2  # the other factor: no
    assert users.factor_held("crc", "totp") is not None  # and the pages see the command line's reset
    assert cli.main(["reset-password", "reader"]) == 0 and cli.main(["reset-totp", "reader"]) == 0  # aggregate


@pytest.mark.parametrize("password_set", [True, False])
def test_cli_enrol_code_reaches_the_once_only_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], password_set: bool
) -> None:
    from console import cli
    from console.auth import random_password

    from tests.console.test_identity import _code, _enrol

    app, users, audit_dir, clock = _box(tmp_path, steward=False, TB_CONSOLE_MFA="totp")
    monkeypatch.setenv("TB_AUDIT_DIR", str(audit_dir))
    monkeypatch.setattr(cli, "UserStore", lambda: users)
    name = next(u.username for u in users.users() if u.role == "admin")
    if not password_set:
        name = random_password(2)
        users.open_by_code(name, "admin", None, "cli")
    assert cli.main(["enrol-code", name]) == 0
    printed = capsys.readouterr().out
    code = re.search(r"valid 24 hours\): ([a-z0-9-]+)", printed)
    assert code
    if password_set:
        assert _redeem(app, name, code[1], CRC_PW).status_code == 401
        assert "/login" in printed.split() and "/login/totp" in printed
        client, key = _enrol(app, clock, name, ADMIN_PW, code[1])
        assert not users.check_enrol_code(name, code[1])
        assert _password(client, name, ADMIN_PW).headers["location"] == "/login/totp"
        _, csrf = _code_page(client)
        assert _code(client, totp.totp(key, clock.unix()), csrf, code[1]).status_code == 401
    else:
        assert "/enrol" in printed
        assert _redeem(app, name, code[1], CRC_PW).headers["location"] == "/login/totp"
        assert _redeem(app, name, code[1], CRC_PW).status_code == 401
