"""Fix group D-279, identity follow-ups: a password someone else set is replaced by its owner first (SEC-1 P-1, CR-034,
ROLE-004); sign-in failures count per account and address, so an outsider cannot lock a named tester out, and a busy
address is slowed (SEC-9 P-7, CR-116, ROLE-006, OPS-003); an OIDC session asks the directory again within the hour
(CR-117); with TOTP on, an electronic signature needs a fresh code as its second component (SEC-1 P-2). Synthetic
accounts only."""

from __future__ import annotations

import dataclasses
import json
import re
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from console import cli, totp
from console.auth import NAME_CEILING, AuthError, UserStore, source_of
from console.identity import IdentityConfigError, IdentitySettings
from fastapi.testclient import TestClient

from tests import edc_kit as k
from tests.console.test_console_app import ADMIN_PW, PILOT_ENV, VIEWER_PW, box  # noqa: F401 - the fixture is used by name
from tests.console.test_edc_pages import NO, PW, _ready, eb  # noqa: F401 - the fixture is used by name
from tests.console.test_identity import T0, Clock, _app, _code, _code_page, _events, _password

NEW_PW = "my-own-choice-2026-x"
A = "198.51.100.7"  # documentation addresses (RFC 5737)
B = "203.0.113.9"


def _client(app: Any, host: str = "testclient") -> TestClient:
    return TestClient(app, client=(host, 40000))


def _csrf(page: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', page)
    assert m
    return m.group(1)


def _api_login(c: TestClient, user: str, pw: str) -> httpx.Response:
    r: httpx.Response = c.post("/api/v1/session", json={"username": user, "password": pw})
    return r


# ---------------------------------------------------------------------------------------------- P-1 forced change
@pytest.mark.usefixtures("held_dir")
def test_an_account_the_administrator_made_changes_its_password_before_anything_else(tmp_path: Path) -> None:
    clock = Clock()
    app, users, audit_dir = _app(tmp_path, clock, **PILOT_ENV, TB_CONSOLE_WORKSPACE="on")
    admin = _client(app)
    assert _password(admin, "admin", ADMIN_PW).headers["location"] == "/home"
    page = admin.get("/ops/users").text
    r = admin.post("/ops/users", data={"csrf": _csrf(page), "action": "add", "username": "tester.a",
                                       "role": "viewer"})  # fmt: skip  # D-719: a protected account gets a code
    given = re.search(r'value="([^"]+)" data-testid="users-pw-field"', r.text)
    assert given, r.text[-600:]
    assert users.must_change("tester.a")
    # first sign-in: the password page, nothing else
    c = _client(app)
    r = _password(c, "tester.a", given.group(1))
    assert r.status_code == 303 and r.headers["location"] == "/account?must_change=1"
    acc = c.get("/account?must_change=1")
    assert acc.status_code == 200 and 'data-testid="account-must-change"' in acc.text
    for path in ("/", "/home", "/ops/users", "/help"):
        r = c.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/account"), path
    assert c.post("/lang", data={"csrf": _csrf(acc.text), "lang": "en", "back": "/account"}).status_code == 200
    r = c.post("/ops/users", data={"csrf": _csrf(acc.text), "action": "add", "username": "x"})
    assert r.status_code == 403 and 'data-testid="problem"' in r.text
    # no API session either, and the page's session is no bearer token for it
    r = _api_login(_client(app), "tester.a", given.group(1))
    assert r.status_code == 403 and r.json()["error"] == "account.must_change"
    # the same password again is no change
    csrf = _csrf(c.get("/account").text)
    form = {"csrf": csrf, "current": given.group(1), "new": given.group(1), "again": given.group(1)}
    r = c.post("/account/password", data=form)
    assert r.status_code == 400 and 'data-testid="account-error"' in r.text and users.must_change("tester.a")
    form = {"csrf": csrf, "current": given.group(1), "new": NEW_PW, "again": NEW_PW}
    r = c.post("/account/password", data=form, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert not users.must_change("tester.a")
    c2 = _client(app)
    assert _password(c2, "tester.a", NEW_PW).headers["location"] == "/home"
    r = c2.get("/home", follow_redirects=False)
    assert r.status_code == 200 or not r.headers["location"].startswith("/account")
    assert _api_login(_client(app), "tester.a", NEW_PW).status_code == 200
    changed = [
        e for e in _events(audit_dir) if e["event"] == "console.user" and e["detail"].get("action") == "password"
    ]
    assert changed and changed[0]["actor"] == "console:tester.a"


@pytest.mark.usefixtures("held_dir")
def test_an_administrators_reset_and_the_command_line_mark_the_password(tmp_path: Path) -> None:
    clock = Clock()
    app, users, _ = _app(tmp_path, clock)
    admin = _client(app)
    _password(admin, "admin", ADMIN_PW)
    page = admin.get("/ops/users").text
    r = admin.post("/ops/users", data={"csrf": _csrf(page), "action": "reset", "username": "viewer",
                                       "confirm": "yes"})  # fmt: skip
    assert r.status_code == 200 and users.must_change("viewer")
    assert not users.must_change("admin")
    # the owner's own change clears it; an administrator's set marks it again
    users.set_password("viewer", NEW_PW, must_change=False)
    assert not users.must_change("viewer")
    users.set_password("viewer", NEW_PW + "-2", must_change=True)
    assert users.must_change("viewer")
    # an account of the identity provider has no console password, and none is set for it (REG-025)
    users.upsert_oidc("dir.user", "sub-123", "viewer", None)
    with pytest.raises(AuthError):
        users.set_password("dir.user", NEW_PW, must_change=True)


def test_the_command_line_marks_what_it_hands_over(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TB_AUDIT_DIR", str(tmp_path / "audit"))
    users = UserStore()
    assert cli.main(["add-user", "tester.b", "--role", "viewer"]) == 0
    assert users.must_change("tester.b")
    users.set_password("tester.b", NEW_PW, must_change=False)
    assert cli.main(["reset-password", "tester.b"]) == 0
    assert users.must_change("tester.b")
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(NEW_PW + "\n"))
    assert cli.main(["bootstrap-admin", "--username", "boss", "--password-stdin"]) == 0
    assert users.get("boss") is not None and not users.must_change("boss")  # typed by its owner, seen by nobody


def test_first_sign_in_with_totp_ends_on_the_password_page(tmp_path: Path) -> None:
    clock = Clock()
    app, users, _ = _app(tmp_path, clock, TB_CONSOLE_MFA="totp")
    users.set_password("viewer", VIEWER_PW, must_change=True)
    c = TestClient(app, base_url="https://testserver")
    enrol = users.issue_enrol_code("viewer")
    assert _password(c, "viewer", VIEWER_PW).headers["location"] == "/login/totp"
    key, mfa = _code_page(c)
    assert key
    r = _code(c, totp.totp(key, clock.unix()), mfa, enrol)
    assert r.status_code == 303 and r.headers["location"] == "/account"
    assert c.get("/", follow_redirects=False).headers["location"].startswith("/account")


# ---------------------------------------------------------------------------------------------- P-7 per address
def test_thirty_wrong_tries_from_one_address_are_slowed_and_lock_no_named_tester_out(tmp_path: Path) -> None:
    clock = Clock()
    app, users, audit_dir = _app(tmp_path, clock, **PILOT_ENV, TB_CONSOLE_WORKSPACE="on")
    outsider = _client(app, A)
    statuses = []
    for _ in range(30):
        statuses.append(_api_login(outsider, "viewer", "guess-guess-guess").status_code)
        clock.tick(seconds=0.2)
    assert statuses[:5] == [401] * 5 and 429 in statuses, statuses  # slowed after the free tries
    assert users.locked("viewer", source_of(A)) and not users.locked("viewer", source_of(B))
    assert users.throttled(source_of(A)) > 0 and users.throttled(source_of(B)) == 0
    # the tester at another address signs in at once, on the page and on the API
    tester = _client(app, B)
    assert _password(tester, "viewer", VIEWER_PW).headers["location"] == "/home"
    assert _api_login(_client(app, B), "viewer", VIEWER_PW).status_code == 200
    # the page shows the wait, never a lock of the account
    r = _password(outsider, "viewer", VIEWER_PW)
    assert r.status_code == 429 and 'data-testid="login-slowed"' in r.text and r.headers["Retry-After"]
    # slowed, not locked: the wait is at most a minute
    clock.tick(seconds=61)
    assert users.throttled(source_of(A)) == 0
    lock = [e for e in _events(audit_dir) if e["event"] == "console.lockout"]
    assert len(lock) == 1 and lock[0]["detail"]["source"] == A
    # the rows stay few: a try while locked counts for the address only, a wait records nothing
    rows = users.db.fetchval("SELECT count(*) FROM login_failures")
    assert int(rows) < 30


def test_many_addresses_together_lock_the_account_everywhere(tmp_path: Path) -> None:
    clock = Clock()
    users = UserStore(clock=clock)
    users.create("pi", "investigator", PW)
    for i in range(NAME_CEILING // 5):
        for _ in range(5):
            assert users.authenticate("pi", "guess-guess-guess", source=f"192.0.2.{i}") is None
    assert users.locked("pi", "192.0.2.200")  # the backstop against distributed guessing
    assert users.authenticate("pi", PW, source="192.0.2.200") is None
    assert users.unlock("pi") and not users.locked("pi")
    assert users.authenticate("pi", PW, source="192.0.2.200") is not None


def test_a_right_sign_in_clears_only_its_own_address_and_old_rows_go(tmp_path: Path) -> None:
    clock = Clock()
    users = UserStore(clock=clock)
    users.create("crc9", "coordinator", PW)
    for _ in range(4):
        users.authenticate("crc9", "guess-guess-guess", source="192.0.2.1")
    users.authenticate("crc9", "guess-guess-guess", source="192.0.2.2")
    assert users.authenticate("crc9", PW, source="192.0.2.2") is not None
    assert len(users._failures("crc9")) == 4  # the other address's count stays
    clock.tick(minutes=16)
    users.record_failure("someone", "192.0.2.3")
    assert int(users.db.fetchval("SELECT count(*) FROM login_failures")) == 1  # the window's rows only


def test_an_ipv6_address_counts_by_its_64_and_a_mapped_ipv4_as_ipv4() -> None:
    assert source_of("2001:db8:1:2:aaaa::1") == source_of("2001:db8:1:2:bbbb::9") == "2001:db8:1:2::/64"
    assert source_of("::ffff:192.0.2.5") == "192.0.2.5"
    assert source_of("192.0.2.5") == "192.0.2.5" and source_of(None) == "" and source_of("testclient") == "testclient"


# ---------------------------------------------------------------------------------------------- CR-117 OIDC lifetime
def test_an_oidc_session_asks_the_directory_again_within_the_hour(tmp_path: Path) -> None:
    clock = Clock()
    users = UserStore(clock=clock, idle=timedelta(hours=3))
    oidc_user = users.upsert_oidc("dir.pi", "sub-9", "investigator", None)
    local = users.create("local.pi", "investigator", PW)
    tok_oidc, _ = users.new_session(oidc_user, via="oidc")
    tok_local, _ = users.new_session(local, via="password")
    clock.tick(minutes=59)
    assert users.session(tok_oidc) is not None
    clock.tick(minutes=2)
    assert users.session(tok_oidc) is None  # gone: the next sign-in goes through the directory
    assert users.session(tok_local) is not None  # a local session keeps its 8 hours
    assert clock() - T0 < timedelta(hours=8)


def test_the_oidc_session_lifetime_setting() -> None:
    env = {"TB_ENV": "TEST"}
    assert IdentitySettings.from_env(env, "TEST", Path("/tmp")).oidc_absolute == timedelta(minutes=60)
    got = IdentitySettings.from_env({**env, "TB_OIDC_SESSION_MINUTES": "15"}, "TEST", Path("/tmp"))
    assert got.oidc_absolute == timedelta(minutes=15)
    for bad in ("0", "481", "soon"):
        with pytest.raises(IdentityConfigError):
            IdentitySettings.from_env({**env, "TB_OIDC_SESSION_MINUTES": bad}, "TEST", Path("/tmp"))


# ---------------------------------------------------------------------------------------------- P-2 step-up at signing
def test_with_totp_on_a_signature_needs_a_fresh_code(eb: dict[str, Any]) -> None:  # noqa: F811
    _ready(eb)
    app = eb["app"]
    ident = app.state.identity
    clock = Clock()
    ident.now = clock.unix
    ident.settings = dataclasses.replace(ident.settings, mfa="totp")
    secret = totp.new_secret()
    eb["users"].set_totp("crc", ident.box.seal("crc", secret), totp.step_at(clock.unix()) - 5)
    c = TestClient(app)
    # T-505a (D-320): the API sign-in takes a code too; the previous step's, so the current one is fresh for signing
    first = totp.totp(secret, clock.unix() - totp.STEP_SECONDS)
    tok = c.post("/api/v1/session", json={"username": "crc", "password": PW, "code": first}).json()["token"]
    hd = {"authorization": f"Bearer {tok}"}
    r = c.post("/api/v1/studies/GZQO/edc/drafts", json={"record": NO, "visit_date": k.VISIT_DATE}, headers=hd)
    assert r.status_code == 200, r.text
    drafts = {d["item"]: d for d in r.json()["drafts"]}
    c.post(f"/api/v1/studies/GZQO/edc/drafts/{drafts['tophus']['id']}/decide", json={"action": "confirm"},
           headers=hd)  # fmt: skip
    shown = c.get(f"/api/v1/studies/GZQO/edc/drafts?record={NO}", headers=hd).json()["drafts"]
    seen = {str(d["id"]): d["sha"] for d in shown if d["fate"] == "confirmed" and d["signature_id"] is None}
    body = {"record": NO, "password": PW, "meaning_ack": True, "seen": seen}
    r = c.post("/api/v1/studies/GZQO/edc/sign", json=body, headers=hd)  # the password alone
    assert r.status_code == 401 and r.json()["error"] == "edc.err.edc.otp"
    wrong = str((int(totp.totp(secret, clock.unix())) + 500_000) % 1_000_000).zfill(6)
    r = c.post("/api/v1/studies/GZQO/edc/sign", json={**body, "otp": wrong}, headers=hd)
    assert r.status_code == 401 and not eb["svc"].store.signatures("GZQO")
    code = totp.totp(secret, clock.unix())
    r = c.post("/api/v1/studies/GZQO/edc/sign", json={**body, "otp": code}, headers=hd)
    assert r.status_code == 200, r.text
    assert len(eb["svc"].store.signatures("GZQO")) == 1
    r = c.post("/api/v1/studies/GZQO/edc/sign", json={**body, "otp": code}, headers=hd)  # the same code again
    assert r.status_code in (401, 409) and len(eb["svc"].store.signatures("GZQO")) == 1
    failed = [e for e in _events(eb["backend"].audit_dir) if e["event"] == "console.edc_reauth_failed"]
    assert [e["detail"].get("reason") for e in failed][:2] == ["wrong", "wrong"]


def test_the_command_line_names_the_account_and_fails_when_its_audit_is_not_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Security review 2026-11-13: the account events name the account, and outside DEV and TEST a change whose audit
    event could not be written ends with exit 3 and says so, not with a warning and exit 0."""
    monkeypatch.setenv("TB_AUDIT_DIR", str(tmp_path / "audit"))
    users = UserStore()
    assert cli.main(["add-user", "tester.c", "--role", "viewer"]) == 0
    assert cli.main(["disable", "tester.c"]) == 0
    lines = [json.loads(x) for f in sorted((tmp_path / "audit").glob("*")) if f.is_file()
             for x in f.read_text(encoding="utf-8").splitlines() if x.startswith("{")]  # fmt: skip
    acts = [(e["detail"]["action"], e["detail"].get("user")) for e in lines if e.get("event") == "console.user"]
    assert acts == [("create", "tester.c"), ("disable", "tester.c")]

    def broken(*_a: object, **_k: object) -> object:
        raise OSError("journal unreachable")

    monkeypatch.setattr("tb_common.audit_writer.open_audit", broken)
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    assert cli.main(["add-user", "tester.d", "--role", "viewer"]) == 3
    assert users.get("tester.d") is not None  # made: the exit code tells the operator its event is missing
    monkeypatch.setenv("TB_ENV", "TEST")
    assert cli.main(["add-user", "tester.e", "--role", "viewer"]) == 0  # a developer shell: a warning only
