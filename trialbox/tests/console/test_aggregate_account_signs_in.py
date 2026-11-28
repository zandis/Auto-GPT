"""E2E P-17: a viewer or CRO account made on ``/ops/users`` could not sign in with what the page handed over. It got a
one-time password only; with TOTP on, the sign-in then asked for an authenticator and said "This account has no
authenticator and no valid enrolment code" (an account without one enrols only with an administrator's code, D-192).
The page now shows the enrolment code beside the password, once, and the account signs in with the two."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from console import totp
from fastapi.testclient import TestClient

from tests.console.test_console_app import ADMIN_PW
from tests.console.test_identity import _code, _code_page, _enrol, _events, _password
from tests.console.test_no_one_holds_both_factors import _add, _box, _signin


@pytest.mark.parametrize("role", ["viewer", "cro"])
@pytest.mark.usefixtures("held_dir")
def test_an_account_made_on_users_signs_in_with_what_the_page_shows(tmp_path: Path, role: str) -> None:
    app, _users, audit_dir, clock = _box(tmp_path, steward=False, TB_CONSOLE_MFA="totp")  # as on an installed box
    admin, _key = _enrol(app, clock, "admin", ADMIN_PW)  # the administrator signs in with TOTP too
    csrf = re.search(r'name="csrf" value="([^"]+)"', admin.get("/ops/users").text)
    assert csrf
    page = _add(admin, csrf.group(1), "reader", role, "GOUT-301" if role == "cro" else "").text  # D-380
    pw = re.search(r'value="([^"]+)" data-testid="users-pw-field"', page)
    code = re.search(r'data-testid="users-pw-code" value="([a-z0-9-]+)"', page)
    assert pw and code, page
    assert "users-pw-code" not in admin.get("/ops/users").text  # shown once
    c = TestClient(app, base_url="https://testserver")
    assert _password(c, "reader", pw.group(1)).headers["location"] == "/login/totp"
    key, mfa = _code_page(c)
    assert key  # an authenticator is set up now, not "no valid enrolment code"
    r = _code(c, totp.totp(key, clock.unix()), mfa, code.group(1))
    assert r.status_code == 303 and r.headers["location"] == "/account"  # signed in: a set password is replaced
    assert c.get("/account", follow_redirects=False).status_code == 200
    events = _events(audit_dir)
    assert [e["detail"]["user"] for e in events if e["event"] == "console.enrol_code"] == ["reader"]
    assert code.group(1) not in repr(events)  # the code is shown once, never written to the audit


@pytest.mark.usefixtures("held_dir")
def test_without_totp_the_password_alone_is_handed_over(tmp_path: Path) -> None:
    app, _users, audit_dir, _ = _box(tmp_path, steward=False)  # a synthetic box: TOTP off
    admin, csrf = _signin(app, "admin", ADMIN_PW)
    page = _add(admin, csrf, "reader", "viewer").text
    assert 'data-testid="users-pw-field"' in page and "users-pw-code" not in page
    assert not [e for e in _events(audit_dir) if e["event"] == "console.enrol_code"]
