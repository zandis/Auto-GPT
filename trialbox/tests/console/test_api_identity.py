"""T-505a (D-320, ROLE-001): the API sign-in asks for the second factor, and a session belongs to one channel. With
``TB_CONSOLE_MFA=totp`` a password alone gets no token from ``POST /api/v1/session``; a wrong or replayed code counts
as a failed sign-in from that address; a token from the API is no cookie for the pages, and a page's cookie is no
bearer token. Synthetic accounts and documentation addresses (RFC 5737) only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from console import totp
from console.auth import UserStore, source_of
from fastapi.testclient import TestClient

from tests.console.test_console_app import ADMIN_PW, PILOT_ENV, VIEWER_PW
from tests.console.test_identity import Clock, _app, _events, _password

A = "198.51.100.7"
B = "203.0.113.9"
COOKIE = "tb_console"
ON = {**PILOT_ENV, "TB_CONSOLE_WORKSPACE": "on"}  # the /api/v1 routes are the workspace's


def _client(app: Any, host: str = "testclient", **kw: Any) -> TestClient:
    return TestClient(app, base_url="https://testserver", client=(host, 40000), **kw)


def _api_login(c: TestClient, user: str, pw: str, code: str = "") -> httpx.Response:
    body = {"username": user, "password": pw, **({"code": code} if code else {})}
    r: httpx.Response = c.post("/api/v1/session", json=body)
    return r


def _with_authenticator(app: Any, users: UserStore, clock: Clock, user: str) -> str:
    """Give ``user`` an authenticator, as an enrolment on the page would, and return its secret."""
    ident = app.state.identity
    secret = totp.new_secret()
    users.set_totp(user, ident.box.seal(user, secret), totp.step_at(clock.unix()) - 5)
    return secret


def _wrong(secret: str, clock: Clock) -> str:
    return str((int(totp.totp(secret, clock.unix())) + 500_000) % 1_000_000).zfill(6)


def _sessions(users: UserStore, user: str) -> list[str]:
    return [str(r[0]) for r in users.db.fetchall("SELECT via FROM sessions WHERE username = ?", (user,))]


def test_with_totp_on_a_password_alone_gets_no_api_session(tmp_path: Path) -> None:
    clock = Clock()
    app, users, audit_dir = _app(tmp_path, clock, **ON, TB_CONSOLE_MFA="totp")
    secret = _with_authenticator(app, users, clock, "viewer")
    c = _client(app)
    r = _api_login(c, "viewer", VIEWER_PW)
    assert r.status_code == 401 and r.json()["error"] == "login.code" and "token" not in r.json()
    assert _sessions(users, "viewer") == []
    # a wrong code: refused, and it counts as a failed sign-in from this address
    r = _api_login(c, "viewer", VIEWER_PW, _wrong(secret, clock))
    assert r.status_code == 401 and r.json()["error"] == "login"
    assert len(users._failures("viewer")) == 1
    # the right code: a bearer session, marked as the API's with both factors
    code = totp.totp(secret, clock.unix())
    r = _api_login(c, "viewer", VIEWER_PW, code)
    assert r.status_code == 200, r.text
    tok = r.json()["token"]
    assert _sessions(users, "viewer") == ["api+totp"] and users._failures("viewer") == []
    assert c.get("/api/v1/studies", headers={"Authorization": f"Bearer {tok}"}).status_code == 200
    # the same code again is a replay
    r = _api_login(_client(app), "viewer", VIEWER_PW, code)
    assert r.status_code == 401 and _sessions(users, "viewer") == ["api+totp"]
    failed = [e for e in _events(audit_dir) if e["event"] == "console.login_failed" and e["detail"].get("via") == "api"]
    assert [e["detail"].get("reason") for e in failed] == ["no_code", "wrong", "replay"]
    ok = [e for e in _events(audit_dir) if e["event"] == "console.login"]
    assert ok and ok[-1]["detail"]["via"] == "api+totp"


def test_an_account_without_an_authenticator_enrols_on_the_page_not_on_the_api(tmp_path: Path) -> None:
    clock = Clock()
    app, users, _ = _app(tmp_path, clock, **ON, TB_CONSOLE_MFA="totp")
    users.issue_enrol_code("viewer")
    r = _api_login(_client(app), "viewer", VIEWER_PW, "123456")
    assert r.status_code == 403 and r.json()["error"] == "login.enrol"
    assert _sessions(users, "viewer") == []


def test_wrong_codes_on_the_api_lock_the_address_and_a_right_password_does_not_reset_them(tmp_path: Path) -> None:
    clock = Clock()
    app, users, audit_dir = _app(tmp_path, clock, **ON, TB_CONSOLE_MFA="totp")
    secret = _with_authenticator(app, users, clock, "viewer")
    guesser = _client(app, A)
    for _ in range(5):  # the password is known; the codes are guessed
        assert _api_login(guesser, "viewer", VIEWER_PW, _wrong(secret, clock)).status_code == 401
        assert _api_login(guesser, "viewer", VIEWER_PW).status_code in (401, 429)  # no code: no reset either
        clock.tick(seconds=1)
    assert users.locked("viewer", source_of(A))
    clock.tick(seconds=61)  # past the address's wait: the lock itself still holds
    assert _api_login(guesser, "viewer", VIEWER_PW, totp.totp(secret, clock.unix())).status_code == 401
    # the owner at another address signs in with both factors
    clock.tick(seconds=30)
    r = _api_login(_client(app, B), "viewer", VIEWER_PW, totp.totp(secret, clock.unix()))
    assert r.status_code == 200, r.text
    assert any(e["event"] == "console.lockout" and e["detail"]["source"] == A for e in _events(audit_dir))


def test_thirty_wrong_tries_on_the_api_do_not_lock_a_named_tester_out_with_totp_on(tmp_path: Path) -> None:
    clock = Clock()
    app, users, _ = _app(tmp_path, clock, **ON, TB_CONSOLE_MFA="totp")
    secret = _with_authenticator(app, users, clock, "viewer")
    outsider = _client(app, A)
    statuses = []
    for _ in range(30):
        statuses.append(_api_login(outsider, "viewer", "guess-guess-guess", "000000").status_code)
        clock.tick(seconds=0.2)
    assert 429 in statuses and 200 not in statuses, statuses  # slowed
    assert not users.locked("viewer", source_of(B))
    r = _api_login(_client(app, B), "viewer", VIEWER_PW, totp.totp(secret, clock.unix()))
    assert r.status_code == 200, r.text


@pytest.mark.usefixtures("held_dir")
def test_an_api_token_is_no_cookie_and_a_cookie_is_no_bearer_token(tmp_path: Path) -> None:
    clock = Clock()
    app, users, _ = _app(tmp_path, clock, **ON)  # TOTP off (TEST): the channel rule holds without it too
    r = _api_login(_client(app), "admin", ADMIN_PW)
    assert r.status_code == 200
    tok = r.json()["token"]
    stolen = _client(app, cookies={COOKIE: tok})
    for path in ("/ops/users", "/admin", "/home"):
        r = stolen.get(path, follow_redirects=False)
        assert r.status_code in (302, 303) and r.headers["location"].startswith("/login"), (path, r.status_code)
    # it is still a good bearer token, and reading it as a cookie did not end it
    bearer = {"Authorization": f"Bearer {tok}"}
    assert _client(app).get("/api/v1/studies", headers=bearer).status_code == 200
    # a page's session is no bearer token, and the API's sign-out does not end it
    page = _client(app)
    assert _password(page, "admin", ADMIN_PW).headers["location"] == "/home"
    cookie = page.cookies.get(COOKIE)
    assert cookie
    as_bearer = {"Authorization": f"Bearer {cookie}"}
    r = _client(app).get("/api/v1/studies", headers=as_bearer)
    assert r.status_code == 401 and r.json()["error"] == "login"
    assert _client(app).delete("/api/v1/session", headers=as_bearer).status_code == 200
    assert page.get("/ops/users", follow_redirects=False).status_code == 200
    # the API's own sign-out ends its token
    assert _client(app).delete("/api/v1/session", headers=bearer).status_code == 200
    assert _client(app).get("/api/v1/studies", headers=bearer).status_code == 401
    assert sorted(_sessions(users, "admin")) == ["password"]
