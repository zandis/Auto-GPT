"""Identity and TLS for the console (D-192, D-193): TOTP (RFC 6238) for local accounts, lock-out and its audited
unlock, the administrator's authenticator reset, idle and absolute session expiry, cookie flags, the OIDC sign-in
(off by default; roles only from the configured group map) and the hospital-certificate check."""

from __future__ import annotations

import base64
import json
import re
import stat
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from console import totp
from console.app import ConsoleSettings, PilotRefused, create_app
from console.auth import AuthError, UserStore
from console.identity import IdentityConfigError, IdentitySettings, check_tls, secure_cookie_default
from console.oidc import OidcClient, OidcConfigError, OidcError, OidcSettings
from cryptography import x509
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient
from tb_common.audit import AuditLog

from tests.console.test_console_app import ADMIN_PW, VIEWER_PW, FakeBackend, _done_feas

T0 = datetime(2026, 11, 9, 9, 0, tzinfo=UTC)
ISSUER = "https://auth.hosp.test"
REDIRECT = "https://trialbox.hosp.test/auth/oidc/callback"


def _events(audit_dir: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(audit_dir.glob("*.jsonl")):
        out += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return out


class Clock:
    def __init__(self) -> None:
        self.t = T0

    def __call__(self) -> datetime:
        return self.t

    def unix(self) -> float:
        return self.t.timestamp()

    def tick(self, **kw: float) -> None:
        self.t += timedelta(**kw)


def _app(tmp_path: Path, clock: Clock, **env: str) -> tuple[Any, UserStore, Path]:
    backend = FakeBackend()
    backend.audit_dir = tmp_path / "audit"
    users = UserStore(clock=clock)
    users.create("admin", "admin", ADMIN_PW, "admin@hospa.test")
    users.create("viewer", "viewer", VIEWER_PW)
    base = {"TB_ENV": "TEST", "TB_CONSOLE_WORKSPACE": "off", "TB_CONSOLE_DIR": str(tmp_path / "console")}
    app = create_app({**base, **env}, backend=backend, audit=AuditLog(backend.audit_dir), users=users)
    app.state.identity.now = clock.unix
    app.state.test_backend = backend
    return app, users, backend.audit_dir


def _password(c: TestClient, user: str, pw: str) -> httpx.Response:
    token = re.search(r'name="login_csrf" value="([^"]+)"', c.get("/login").text)
    assert token
    r: httpx.Response = c.post(
        "/login", data={"username": user, "password": pw, "login_csrf": token.group(1)}, follow_redirects=False
    )
    return r


def _code_page(c: TestClient) -> tuple[str | None, str]:
    page = c.get("/login/totp").text
    key = re.search(r'id="totp-key"[^>]*value="([A-Z2-7 ]+)"', page)
    mfa = re.search(r'name="mfa_csrf" value="([^"]+)"', page)
    assert mfa, page
    return (key.group(1).replace(" ", "") if key else None), mfa.group(1)


def _code(c: TestClient, code: str, mfa: str, enrol: str = "") -> httpx.Response:
    data = {"code": code, "mfa_csrf": mfa, **({"enrol_code": enrol} if enrol else {})}
    r: httpx.Response = c.post("/login/totp", data=data, follow_redirects=False)
    return r


def _signed_in(c: TestClient) -> bool:
    status: int = c.get("/", follow_redirects=False).status_code
    return status == 200


def _enrol(app: Any, clock: Clock, user: str, pw: str, code: str | None = None) -> tuple[TestClient, str]:
    """Sign in and set up an authenticator with an administrator's enrolment code (issued here unless given)."""
    enrol = code or app.state.identity.users.issue_enrol_code(user)
    c = TestClient(app, base_url="https://testserver")
    assert _password(c, user, pw).headers["location"] == "/login/totp"
    key, mfa = _code_page(c)
    assert key
    r = _code(c, totp.totp(key, clock.unix()), mfa, enrol)
    assert r.status_code == 303 and _signed_in(c)
    return c, key


# ---------------------------------------------------------------------------------------------- TOTP (RFC 6238)
def test_totp_matches_the_rfc_6238_vectors() -> None:
    secret = base64.b32encode(b"12345678901234567890").decode()  # RFC 6238 appendix B, SHA-1
    assert totp.totp(secret, 59) == "287082"  # 94287082, last six digits
    assert totp.totp(secret, 1111111109) == "081804"
    assert totp.totp(secret, 1234567890) == "005924"
    assert totp.totp(secret, 2000000000) == "279037"


def test_totp_window_replay_and_input_cleaning() -> None:
    s = totp.new_secret()
    now = 1_800_000_000.0
    code = totp.totp(s, now)
    step = totp.step_at(now)
    assert totp.verify(s, code, now, None) == step
    assert totp.verify(s, code, now + 30, None) == step  # one step of drift is accepted
    assert totp.verify(s, code, now + 90, None) is None  # three steps later: too old
    assert totp.verify(s, code, now, step) is None  # a code is good once (replay)
    assert totp.verify(s, code, now, step - 1) == step
    assert totp.verify(s, f"{code[:3]} {code[3:]}", now, None) == step
    full = "".join(chr(0xFF10 + int(d)) for d in code)  # full-width digits from a Japanese IME
    assert totp.verify(s, full, now, None) == step
    assert totp.verify(s, code[:3] + "x" + code[3:], now, None) is None
    assert totp.verify(s, "", now, None) is None and totp.clean_code("1234567") == ""
    uri = totp.otpauth_uri(s, "crc1")
    assert uri.startswith("otpauth://totp/TrialBox%3Acrc1?secret=") and "digits=6" in uri and "period=30" in uri


def test_totp_secret_is_sealed_with_a_key_file_outside_the_database(tmp_path: Path) -> None:
    box = totp.SecretBox(tmp_path / "k" / "totp.key")
    s = totp.new_secret()
    sealed = box.seal("crc1", s)
    assert s not in sealed and box.open("crc1", sealed) == s
    assert stat.S_IMODE((tmp_path / "k" / "totp.key").stat().st_mode) == 0o600
    with pytest.raises(InvalidTag):  # bound to the account: another row's secret does not open as this one's
        box.open("crc2", sealed)
    with pytest.raises(InvalidTag):
        totp.SecretBox(tmp_path / "other.key").open("crc1", sealed)


# ---------------------------------------------------------------------------------------------- settings
def test_totp_is_the_default_outside_dev_and_test_and_cannot_be_turned_off_in_production(tmp_path: Path) -> None:
    assert IdentitySettings.from_env({}, "PRODUCTION", tmp_path).totp_required
    assert IdentitySettings.from_env({}, "STAGING", tmp_path).totp_required
    assert not IdentitySettings.from_env({}, "TEST", tmp_path).totp_required
    assert IdentitySettings.from_env({"TB_CONSOLE_MFA": "totp"}, "DEV", tmp_path).totp_required
    for env in ("PRODUCTION", "VALIDATION", "PILOT"):  # off only in DEV and TEST (review M2)
        with pytest.raises(IdentityConfigError, match=f"refused in {env}"):
            IdentitySettings.from_env({"TB_CONSOLE_MFA": "off"}, env, tmp_path)
    with pytest.raises(IdentityConfigError):
        IdentitySettings.from_env({"TB_CONSOLE_MFA": "sms"}, "TEST", tmp_path)
    st = IdentitySettings.from_env({"TB_CONSOLE_IDLE_MINUTES": "15", "TB_CONSOLE_SESSION_HOURS": "4"}, "TEST", tmp_path)
    assert st.idle == timedelta(minutes=15) and st.absolute == timedelta(hours=4)
    assert IdentitySettings.from_env({}, "TEST", tmp_path).idle == timedelta(minutes=10)
    for bad in ({"TB_CONSOLE_IDLE_MINUTES": "0"}, {"TB_CONSOLE_IDLE_MINUTES": "61"}, {"TB_CONSOLE_SESSION_HOURS": "x"}):
        with pytest.raises(IdentityConfigError):
            IdentitySettings.from_env(bad, "TEST", tmp_path)
    assert secure_cookie_default({}, "PRODUCTION") and not secure_cookie_default({}, "TEST")
    with pytest.raises(IdentityConfigError):  # review M1: an explicit off is refused in PRODUCTION
        secure_cookie_default({"TB_CONSOLE_SECURE_COOKIE": "0"}, "PRODUCTION")
    assert not secure_cookie_default({"TB_CONSOLE_SECURE_COOKIE": "0"}, "TEST")
    assert secure_cookie_default({"TB_CONSOLE_SECURE_COOKIE": "1"}, "TEST")


# ---------------------------------------------------------------------------------------------- the TOTP step
def test_password_alone_gives_no_session_and_first_sign_in_enrols(tmp_path: Path) -> None:
    clock = Clock()
    app, users, audit_dir = _app(tmp_path, clock, TB_CONSOLE_MFA="totp")
    enrol = users.issue_enrol_code("viewer")
    c = TestClient(app)
    r = _password(c, "viewer", VIEWER_PW)
    assert r.status_code == 303 and r.headers["location"] == "/login/totp"
    assert "tb_console=" not in r.headers.get("set-cookie", "")  # no session before the code
    assert not _signed_in(c)
    key, mfa = _code_page(c)
    assert key is not None
    assert users.totp_state("viewer") == (None, None)  # nothing stored until a code confirms the key
    wrong = "000000" if totp.totp(key, clock.unix()) != "000000" else "111111"
    assert _code(c, wrong, mfa, enrol).status_code == 401
    assert _code_page(c)[0] == key  # the same key until it is confirmed
    r = _code(c, totp.totp(key, clock.unix()), mfa, enrol)
    assert r.status_code == 303 and _signed_in(c)
    assert users.enrol_state("viewer") == (False, "first")  # the enrolment code is used up
    sealed, step = users.totp_state("viewer")
    assert sealed and key not in sealed and step == totp.step_at(clock.unix())
    ev = [e for e in _events(audit_dir) if e.get("actor") == "console:viewer"]
    assert [e["event"] for e in ev] == ["console.login_failed", "console.totp_enrolled", "console.login"]
    assert ev[0]["detail"] == {"factor": "totp", "reason": "wrong"}
    assert ev[1]["detail"] == {"kind": "first"}
    assert enrol not in json.dumps(_events(audit_dir))  # the code is never in the audit
    assert ev[-1]["detail"]["via"] == "password+totp"


def test_a_totp_code_is_refused_when_wrong_or_replayed(tmp_path: Path) -> None:
    clock = Clock()
    app, _, audit_dir = _app(tmp_path, clock, TB_CONSOLE_MFA="totp")
    _, key = _enrol(app, clock, "viewer", VIEWER_PW)
    used = totp.totp(key, clock.unix())
    c = TestClient(app)
    assert _password(c, "viewer", VIEWER_PW).headers["location"] == "/login/totp"
    shown, mfa = _code_page(c)
    assert shown is None  # enrolled: the key is never shown again
    r = _code(c, used, mfa)  # the code that signed in a moment ago
    assert r.status_code == 401 and 'data-testid="totp-error"' in r.text and not _signed_in(c)
    wrong = str((int(totp.totp(key, clock.unix() + 300)) + 1) % 1_000_000).zfill(6)
    assert _code(c, wrong, mfa).status_code == 401
    reasons = [e["detail"]["reason"] for e in _events(audit_dir) if e["event"] == "console.login_failed"]
    assert reasons == ["replay", "wrong"]
    clock.tick(seconds=30)
    assert _code(c, totp.totp(key, clock.unix()), mfa).status_code == 303 and _signed_in(c)


def test_wrong_codes_lock_the_account_and_a_right_password_does_not_reset_the_count(tmp_path: Path) -> None:
    clock = Clock()
    app, users, audit_dir = _app(tmp_path, clock, TB_CONSOLE_MFA="totp")
    _, key = _enrol(app, clock, "viewer", VIEWER_PW)
    bad = str((int(totp.totp(key, clock.unix())) + 500_000) % 1_000_000).zfill(6)
    c = TestClient(app)
    tries = 0
    for round_ in (3, 2):  # three wrong codes, the right password again, two more wrong codes
        assert _password(c, "viewer", VIEWER_PW).headers["location"] == "/login/totp"
        _, mfa = _code_page(c)
        for _ in range(round_):
            r = _code(c, bad, mfa)
            tries += 1
            assert r.status_code == 401
            assert users.locked("viewer") == (tries == 5), tries  # the password in between reset nothing
    assert 'data-testid="login-locked"' in r.text
    assert users.locked("viewer")
    clock.tick(seconds=30)
    r = _password(c, "viewer", VIEWER_PW)  # the right password while locked
    assert r.status_code == 401 and 'data-testid="login-locked"' in r.text
    lock_events = [e for e in _events(audit_dir) if e["event"] == "console.lockout"]
    assert len(lock_events) == 1 and lock_events[0]["actor"] == "console:viewer"


def test_password_lockout_and_the_audited_unlock(tmp_path: Path) -> None:
    clock = Clock()
    app, users, audit_dir = _app(tmp_path, clock, TB_CONSOLE_MFA="totp")
    admin, _ = _enrol(app, clock, "admin", ADMIN_PW)
    c = TestClient(app)
    for _ in range(5):
        assert _password(c, "viewer", "wrong-wrong-wrong").status_code == 401
    assert users.locked("viewer")
    assert _password(c, "viewer", VIEWER_PW).status_code == 401  # locked even with the right password
    page = admin.get("/ops/identity").text
    assert 'data-testid="unlock-viewer"' in page
    csrf = re.search(r'name="csrf" value="([^"]+)"', page)
    assert csrf
    r = admin.post("/ops/identity", data={"csrf": csrf.group(1), "action": "unlock", "username": "viewer"},
                   follow_redirects=False)  # fmt: skip
    assert r.status_code == 303 and not users.locked("viewer")
    unlock = [e for e in _events(audit_dir) if e["event"] == "console.unlock"]
    assert unlock[0]["actor"] == "console:admin" and unlock[0]["detail"] == {"user": "viewer", "was_locked": True}
    assert [e["event"] for e in _events(audit_dir)].count("console.lockout") == 1
    assert _password(c, "viewer", VIEWER_PW).headers["location"] == "/login/totp"


def test_admin_resets_an_authenticator_and_only_an_admin_may(tmp_path: Path) -> None:
    clock = Clock()
    app, users, audit_dir = _app(tmp_path, clock, TB_CONSOLE_MFA="totp")
    admin, _ = _enrol(app, clock, "admin", ADMIN_PW)
    clock.tick(seconds=30)
    viewer, old = _enrol(app, clock, "viewer", VIEWER_PW)
    stolen = viewer.cookies.get("tb_console")
    vcsrf = re.search(r'name="csrf" value="([^"]+)"', viewer.get("/").text)
    assert vcsrf
    r = viewer.post("/ops/identity", data={"csrf": vcsrf.group(1), "action": "reset_totp", "username": "admin"})
    assert r.status_code == 403 and users.totp_state("admin")[0] is not None
    assert viewer.get("/ops/identity").status_code == 403
    csrf = re.search(r'name="csrf" value="([^"]+)"', admin.get("/ops/identity").text)
    assert csrf
    form = {"csrf": csrf.group(1), "action": "reset_totp", "username": "admin"}
    assert admin.post("/ops/identity", data=form).status_code == 400  # never one's own, here
    form["username"] = "viewer"
    r = admin.post("/ops/identity", data=form)  # first a confirmation sheet
    assert r.status_code == 200 and 'data-testid="confirm"' in r.text and users.totp_state("viewer")[0] is not None
    r = admin.post("/ops/identity", data={**form, "confirm": "yes"}, follow_redirects=False)
    assert r.status_code == 200 and users.totp_state("viewer") == (None, None)
    shown = re.search(r'data-testid="identity-code-value" [^>]*value="([a-z0-9-]+)"', r.text)
    shown = shown or re.search(r'id="enrol-code-value"[^>]*value="([a-z0-9-]+)"', r.text)
    assert shown  # the enrolment code, shown to the resetting administrator once
    assert not _signed_in(viewer)  # signed out everywhere
    replay = TestClient(app, base_url="https://testserver", cookies={"tb_console": stolen or ""})
    assert stolen and not _signed_in(replay)  # the old session token is dead
    ev = [e for e in _events(audit_dir) if e["event"] == "console.totp_reset"]
    assert ev and ev[0]["actor"] == "console:admin" and ev[0]["detail"] == {"user": "viewer"}
    assert shown.group(1) not in json.dumps(_events(audit_dir))
    assert any(e["event"] == "console.denied" and e["actor"] == "console:viewer" for e in _events(audit_dir))
    clock.tick(seconds=30)
    # the password alone no longer sets up a device: the enrolment code from the administrator is needed
    c = TestClient(app)
    _password(c, "viewer", VIEWER_PW)
    key, mfa = _code_page(c)
    assert key
    r = _code(c, totp.totp(key, clock.unix()), mfa, "aaaa-bbbb-cccc-dddd")
    assert r.status_code == 401 and users.totp_state("viewer") == (None, None)
    clock.tick(seconds=30)
    _, new = _enrol(app, clock, "viewer", VIEWER_PW, code=shown.group(1))
    assert new != old
    enrolled = [e for e in _events(audit_dir) if e["event"] == "console.totp_enrolled"]
    assert [e["detail"]["kind"] for e in enrolled] == ["first", "first", "reset"]
    reasons = [e["detail"].get("reason") for e in _events(audit_dir) if e["event"] == "console.login_failed"]
    assert "enrol_code" in reasons


def test_totp_off_in_test_keeps_the_one_step_sign_in(tmp_path: Path) -> None:
    clock = Clock()
    app, _, _ = _app(tmp_path, clock)
    c = TestClient(app)
    r = _password(c, "viewer", VIEWER_PW)
    assert r.status_code == 303 and r.headers["location"] == "/" and _signed_in(c)
    assert c.get("/login/totp", follow_redirects=False).headers["location"] == "/login"  # no half-done sign-in


# ---------------------------------------------------------------------------------------------- sessions
def test_session_expires_when_idle_and_at_the_absolute_limit(tmp_path: Path) -> None:
    clock = Clock()
    app, users, _ = _app(tmp_path, clock, TB_CONSOLE_IDLE_MINUTES="20", TB_CONSOLE_SESSION_HOURS="2")
    assert users.idle == timedelta(minutes=20) and users.absolute == timedelta(hours=2)
    c = TestClient(app)
    _password(c, "viewer", VIEWER_PW)
    clock.tick(minutes=19)
    assert _signed_in(c)  # activity moves the idle clock
    clock.tick(minutes=19)
    assert _signed_in(c)
    clock.tick(minutes=21)
    r = c.get("/jobs", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"  # idle
    c2 = TestClient(app)
    _password(c2, "viewer", VIEWER_PW)
    for _ in range(12):  # busy for two hours, ten minutes apart
        clock.tick(minutes=10)
        assert _signed_in(c2)
    clock.tick(minutes=1)
    assert not _signed_in(c2)  # past the absolute limit, however busy


def test_default_idle_timeout_is_ten_minutes(tmp_path: Path) -> None:
    clock = Clock()
    store = UserStore(clock=clock)
    token, _ = store.new_session(store.create("a", "admin", ADMIN_PW))
    clock.tick(minutes=9)
    assert store.session(token) is not None
    clock.tick(minutes=10, seconds=1)
    assert store.session(token) is None


def test_production_cookies_are_secure_httponly_and_strict(tmp_path: Path) -> None:
    clock = Clock()
    app, users, _ = _app(tmp_path, clock, TB_ENV="PRODUCTION")
    enrol = users.issue_enrol_code("viewer")
    c = TestClient(app, base_url="https://testserver")
    r = _password(c, "viewer", VIEWER_PW)
    mfa_cookie = r.headers["set-cookie"].lower()
    assert "tb_console_mfa=" in mfa_cookie and "secure" in mfa_cookie and "httponly" in mfa_cookie
    assert "samesite=strict" in mfa_cookie
    key, mfa = _code_page(c)
    assert key
    r = _code(c, totp.totp(key, clock.unix()), mfa, enrol)
    session = [v for k, v in r.headers.multi_items() if k == "set-cookie" and v.startswith("tb_console=")]
    assert session and all(f in session[0].lower() for f in ("secure", "httponly", "samesite=strict"))
    # over plain http the browser keeps no Secure cookie: no sign-in is possible
    plain = TestClient(app)
    assert _password(plain, "viewer", VIEWER_PW).status_code == 400


# ---------------------------------------------------------------------------------------------- OIDC
OIDC_ENV = {
    "TB_OIDC_ENABLED": "1",
    "TB_OIDC_ISSUER": ISSUER,
    "TB_OIDC_CLIENT_ID": "trialbox-console",
    "TB_OIDC_REDIRECT_URL": REDIRECT,
    "TB_OIDC_GROUP_ROLES": "tb-coordinators:coordinator,tb-investigators:investigator,tb-readers:viewer",
    "TB_OIDC_LOGOUT_URL": "https://auth.hosp.test/logout",
}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


class FakeIdp:
    """An OIDC provider behind httpx.MockTransport: discovery, keys, token and userinfo endpoints."""

    def __init__(self, now: Callable[[], float]) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.now = now
        self.claims: dict[str, Any] = {}
        self.header: dict[str, Any] = {"alg": "RS256", "kid": "k1"}
        self.token_requests: list[dict[str, list[str]]] = []
        self.userinfo: dict[str, Any] | None = None

    def jwt(self, claims: dict[str, Any], header: dict[str, Any] | None = None) -> str:
        h = _b64(json.dumps(header or self.header).encode())
        p = _b64(json.dumps(claims).encode())
        sig = self.key.sign(f"{h}.{p}".encode(), padding.PKCS1v15(), hashes.SHA256())
        return f"{h}.{p}.{_b64(sig)}"

    def base_claims(self, nonce: str) -> dict[str, Any]:
        now = int(self.now())
        return {"iss": ISSUER, "aud": "trialbox-console", "sub": "S-1001", "exp": now + 300, "iat": now,
                "nonce": nonce, "preferred_username": "crc.tanaka", "email": "crc.tanaka@hosp.test",
                "groups": ["tb-coordinators", "all-staff"], "amr": ["pwd", "otp", "mfa"]}  # fmt: skip

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == ISSUER + "/.well-known/openid-configuration":
            return httpx.Response(200, json={
                "issuer": ISSUER, "authorization_endpoint": ISSUER + "/api/oidc/authorization",
                "token_endpoint": ISSUER + "/api/oidc/token", "jwks_uri": ISSUER + "/jwks.json",
                "userinfo_endpoint": ISSUER + "/api/oidc/userinfo"})  # fmt: skip
        if url == ISSUER + "/jwks.json":
            n = self.key.public_key().public_numbers()
            jwk = {"kty": "RSA", "kid": "k1", "alg": "RS256", "use": "sig",
                   "n": _b64(n.n.to_bytes(256, "big")), "e": _b64(n.e.to_bytes(3, "big"))}  # fmt: skip
            return httpx.Response(200, json={"keys": [jwk]})
        if url == ISSUER + "/api/oidc/token":
            form = parse_qs(request.content.decode())
            self.token_requests.append(form)
            assert request.headers["authorization"].startswith("Basic ")
            return httpx.Response(200, json={"id_token": self.jwt(self.claims), "access_token": "at-1"})
        if url == ISSUER + "/api/oidc/userinfo":  # by default only the subject, no groups
            return httpx.Response(200, json=self.userinfo or {"sub": self.claims.get("sub")})
        return httpx.Response(404)


def _oidc_app(tmp_path: Path, clock: Clock, **env: str) -> tuple[Any, UserStore, Path, FakeIdp]:
    secret = tmp_path / "oidc_secret"
    secret.write_text("client-secret-value\n")
    app, users, audit_dir = _app(tmp_path, clock, **{**OIDC_ENV, "TB_OIDC_CLIENT_SECRET_FILE": str(secret), **env})
    idp = FakeIdp(clock.unix)
    client = app.state.identity.oidc_client
    client.transport = httpx.MockTransport(idp.handler)
    client.now = clock.unix
    return app, users, audit_dir, idp


def _oidc_round(c: TestClient, idp: FakeIdp, change: Callable[[dict[str, Any]], None] | None = None) -> httpx.Response:
    r = c.get("/auth/oidc/start", follow_redirects=False)
    assert r.status_code == 303, r.text
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["code_challenge_method"] == ["S256"] and q["redirect_uri"] == [REDIRECT]
    cookie = r.headers["set-cookie"].lower()
    assert "samesite=lax" in cookie and "httponly" in cookie and "path=/auth/oidc" in cookie
    idp.claims = idp.base_claims(q["nonce"][0])
    if change:
        change(idp.claims)
    done: httpx.Response = c.get(
        "/auth/oidc/callback", params={"code": "c-1", "state": q["state"][0]}, follow_redirects=False
    )
    return done


def test_oidc_is_off_by_default(tmp_path: Path) -> None:
    assert not OidcSettings.from_env({}).enabled
    assert not IdentitySettings.from_env({}, "PRODUCTION", tmp_path).oidc.enabled
    clock = Clock()
    app, _, _ = _app(tmp_path, clock)
    assert app.state.identity.oidc_client is None
    c = TestClient(app)
    assert 'data-testid="login-oidc"' not in c.get("/login").text
    assert c.get("/auth/oidc/start", follow_redirects=False).status_code == 404
    assert c.get("/auth/oidc/callback?code=x&state=y", follow_redirects=False).status_code == 404


def test_oidc_settings_are_checked_before_start() -> None:
    base = {**OIDC_ENV, "TB_OIDC_CLIENT_SECRET_FILE": "/run/secrets/oidc"}
    assert OidcSettings.from_env(base).group_roles[0] == ("tb-coordinators", "coordinator")
    for key, value in (("TB_OIDC_ISSUER", "http://auth.hosp.test"), ("TB_OIDC_GROUP_ROLES", ""),
                       ("TB_OIDC_LOGOUT_URL", ""), ("TB_OIDC_LOGOUT_URL", "http://auth.hosp.test/logout"),
                       ("TB_OIDC_GROUP_ROLES", "tb-x:superuser"), ("TB_OIDC_REDIRECT_URL", "https://x/other"),
                       ("TB_OIDC_CLIENT_ID", ""), ("TB_OIDC_CLIENT_SECRET_FILE", "")):  # fmt: skip
        with pytest.raises(OidcConfigError):
            OidcSettings.from_env({**base, key: value})


def test_oidc_sign_in_maps_a_configured_group_to_its_role(tmp_path: Path) -> None:
    clock = Clock()
    app, users, audit_dir, idp = _oidc_app(tmp_path, clock)
    c = TestClient(app, base_url="https://trialbox.hosp.test")
    assert 'data-testid="login-oidc"' in c.get("/login").text
    r = _oidc_round(c, idp)
    assert r.status_code == 200 and 'http-equiv="refresh"' in r.text  # a same-site hop carries the Strict cookie
    assert _signed_in(c)
    u = users.get("crc.tanaka")
    assert u is not None and u.role == "coordinator" and u.mailbox == "crc.tanaka@hosp.test"
    assert users.is_oidc("crc.tanaka") and users.totp_state("crc.tanaka") == (None, None)  # factor is the IdP's
    form = idp.token_requests[0]
    assert form["grant_type"] == ["authorization_code"] and len(form["code_verifier"][0]) >= 43
    login = [e for e in _events(audit_dir) if e["event"] == "console.login"][-1]
    assert login["actor"] == "console:crc.tanaka" and login["detail"] == {"role": "coordinator", "via": "oidc"}
    # sign-out goes on to the provider's logout
    csrf = re.search(r'name="csrf" value="([^"]+)"', c.get("/").text)
    assert csrf
    stolen = c.cookies.get("tb_console")
    out = c.post("/logout", data={"csrf": csrf.group(1)}, follow_redirects=False)
    assert out.headers["location"] == "https://auth.hosp.test/logout" and not _signed_in(c)
    replay = TestClient(app, base_url="https://trialbox.hosp.test", cookies={"tb_console": stolen or ""})
    assert stolen and not _signed_in(replay)  # the token is dead after sign-out


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda cl: cl.update(role="admin", groups=["tb-readers"]), None),  # a role claim gives nothing
        (lambda cl: cl.update(groups=["all-staff", "Domain Admins"]), "no mapped group"),
        (lambda cl: cl.update(groups=["tb-coordinators", "tb-investigators"]), "groups map to more than one role"),
        (lambda cl: cl.pop("groups"), "no mapped group"),
        (lambda cl: cl.update(amr=["pwd"]), "the identity provider did not report a second factor"),
        (lambda cl: cl.update(nonce="other"), "id_token nonce"),
        (lambda cl: cl.update(aud="another-client"), "id_token audience"),
        (lambda cl: cl.update(iss="https://evil.test"), "id_token issuer"),
        (lambda cl: cl.update(exp=int(T0.timestamp()) - 600), "id_token expired"),
    ],
)
def test_oidc_never_elevates_from_claims_that_are_not_configured(
    tmp_path: Path, change: Callable[[dict[str, Any]], None], reason: str | None
) -> None:
    clock = Clock()
    app, users, audit_dir, idp = _oidc_app(tmp_path, clock)
    c = TestClient(app, base_url="https://trialbox.hosp.test")
    r = _oidc_round(c, idp, change)
    if reason is None:
        assert r.status_code == 200 and users.get("crc.tanaka").role == "viewer"  # type: ignore[union-attr]
        return
    assert r.status_code == 403 and 'data-testid="login-oidc-error"' in r.text and not _signed_in(c)
    assert users.get("crc.tanaka") is None
    failed = [e for e in _events(audit_dir) if e["event"] == "console.login_failed"]
    assert failed[-1]["detail"] == {"via": "oidc", "reason": reason}


def test_oidc_groups_from_userinfo_must_be_about_the_same_subject(tmp_path: Path) -> None:
    clock = Clock()
    app, users, _, idp = _oidc_app(tmp_path, clock)
    c = TestClient(app, base_url="https://trialbox.hosp.test")
    idp.userinfo = {"sub": "S-1001", "groups": ["tb-investigators"]}
    assert _oidc_round(c, idp, lambda cl: cl.pop("groups")).status_code == 200
    assert users.get("crc.tanaka").role == "investigator"  # type: ignore[union-attr]
    c2 = TestClient(app, base_url="https://trialbox.hosp.test")
    idp.userinfo = {"sub": "S-9999", "groups": ["tb-investigators"]}
    assert _oidc_round(c2, idp, lambda cl: cl.pop("groups")).status_code == 403


def test_oidc_state_is_single_use_and_bound_to_the_browser(tmp_path: Path) -> None:
    clock = Clock()
    app, _, audit_dir, idp = _oidc_app(tmp_path, clock)

    def reasons() -> list[str]:
        return [e["detail"]["reason"] for e in _events(audit_dir) if e["event"] == "console.login_failed"]

    def start(c: TestClient) -> str:
        r = c.get("/auth/oidc/start", follow_redirects=False)
        q: dict[str, list[str]] = parse_qs(urlparse(str(r.headers["location"])).query)
        idp.claims = idp.base_claims(q["nonce"][0])
        return q["state"][0]

    c = TestClient(app, base_url="https://trialbox.hosp.test")
    state = start(c)
    other = TestClient(app, base_url="https://trialbox.hosp.test")  # a callback link opened in another browser
    assert other.get("/auth/oidc/callback", params={"code": "c", "state": state}).status_code == 403
    assert reasons()[-1] == "state does not match this browser"
    # the other browser did not burn the state: the right browser still signs in, once
    assert c.get("/auth/oidc/callback", params={"code": "c", "state": state}).status_code == 200 and _signed_in(c)
    c2 = TestClient(app, base_url="https://trialbox.hosp.test", cookies={"tb_console_oidc": state})
    assert c2.get("/auth/oidc/callback", params={"code": "c", "state": state}).status_code == 403  # used up
    assert reasons()[-1] == "unknown or expired state"
    c3 = TestClient(app, base_url="https://trialbox.hosp.test")
    state = start(c3)
    clock.tick(minutes=11)  # too late; the token itself is fresh, so only the state's age refuses it
    idp.claims.update(iat=int(clock.unix()), exp=int(clock.unix()) + 300)
    assert c3.get("/auth/oidc/callback", params={"code": "c", "state": state}).status_code == 403
    assert reasons()[-1] == "unknown or expired state" and not _signed_in(c3)


def test_oidc_never_takes_over_a_local_account(tmp_path: Path) -> None:
    clock = Clock()
    app, users, _, idp = _oidc_app(tmp_path, clock)
    c = TestClient(app, base_url="https://trialbox.hosp.test")
    r = _oidc_round(c, idp, lambda cl: cl.update(preferred_username="admin"))
    assert r.status_code == 403 and users.get("admin").role == "admin"  # type: ignore[union-attr]
    assert not users.is_oidc("admin")
    _oidc_round(TestClient(app, base_url="https://trialbox.hosp.test"), idp)
    r = _oidc_round(  # the same name from another directory subject
        TestClient(app, base_url="https://trialbox.hosp.test"), idp, lambda cl: cl.update(sub="S-2002")
    )
    assert r.status_code == 403


def _client(idp: FakeIdp, clock: Clock) -> OidcClient:
    st = OidcSettings.from_env({**OIDC_ENV, "TB_OIDC_CLIENT_SECRET_FILE": "/dev/null"})
    return OidcClient(st, transport=httpx.MockTransport(idp.handler), now=clock.unix)


def test_id_token_signature_and_algorithm_are_checked() -> None:
    clock = Clock()
    idp = FakeIdp(clock.unix)
    client = _client(idp, clock)
    claims = idp.base_claims("n1")
    assert client.verify_id_token(idp.jwt(claims), "n1")["sub"] == "S-1001"
    h, p, s = idp.jwt(claims).split(".")
    forged = _b64(json.dumps({**claims, "groups": ["tb-coordinators"], "sub": "S-0"}).encode())
    with pytest.raises(OidcError, match="signature"):
        client.verify_id_token(f"{h}.{forged}.{s}", "n1")
    with pytest.raises(OidcError, match="not allowed"):
        client.verify_id_token(f"{_b64(json.dumps({'alg': 'none'}).encode())}.{p}.", "n1")
    with pytest.raises(OidcError, match="not allowed"):  # a shared-key token signed with the public key
        client.verify_id_token(f"{_b64(json.dumps({'alg': 'HS256', 'kid': 'k1'}).encode())}.{p}.{s}", "n1")
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    sig = other.sign(f"{h}.{p}".encode(), padding.PKCS1v15(), hashes.SHA256())
    with pytest.raises(OidcError, match="signature"):
        client.verify_id_token(f"{h}.{p}.{_b64(sig)}", "n1")
    with pytest.raises(OidcError, match="key is unknown"):
        client.verify_id_token(idp.jwt(claims, {"alg": "RS256", "kid": "k9"}), "n1")


def test_id_token_es256_is_accepted_with_an_ec_key() -> None:
    clock = Clock()
    idp = FakeIdp(clock.unix)
    key = ec.generate_private_key(ec.SECP256R1())
    nums = key.public_key().public_numbers()
    jwk = {"kty": "EC", "crv": "P-256", "kid": "e1", "x": _b64(nums.x.to_bytes(32, "big")),
           "y": _b64(nums.y.to_bytes(32, "big"))}  # fmt: skip
    client = _client(idp, clock)
    client._meta = {"jwks_uri": ISSUER + "/jwks.json"}
    client._jwks = {"e1": jwk}
    h = _b64(json.dumps({"alg": "ES256", "kid": "e1"}).encode())
    p = _b64(json.dumps(idp.base_claims("n2")).encode())
    r, s = decode_dss_signature(key.sign(f"{h}.{p}".encode(), ec.ECDSA(hashes.SHA256())))
    token = f"{h}.{p}.{_b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
    assert client.verify_id_token(token, "n2")["sub"] == "S-1001"
    with pytest.raises(OidcError):
        client.verify_id_token(token, "other-nonce")


# ---------------------------------------------------------------------------------------------- TLS (D-193)
def _cert(tmp_path: Path, names: list[str], days: int = 365, start: int = -1) -> tuple[Path, Path]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0])])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now + timedelta(days=start))
        .not_valid_after(now + timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(n) for n in names]), critical=False)
        .sign(key, hashes.SHA256())
    )
    crt, pem = tmp_path / f"{names[0]}.crt", tmp_path / f"{names[0]}.key"
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    pem.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()))  # fmt: skip
    return crt, pem


def test_tls_internal_ca_needs_only_a_hostname() -> None:
    rep = check_tls({"TB_TLS_HOSTNAME": "trialbox.hosp.test"})
    assert rep.ok and rep.mode == "internal" and "install its root" in rep.notes[0]
    assert not check_tls({}).ok  # no host name
    assert not check_tls({"TB_TLS_HOSTNAME": "127.0.0.1"}).ok
    assert not check_tls({"TB_TLS_MODE": "self", "TB_TLS_HOSTNAME": "trialbox.hosp.test"}).ok


def test_tls_hospital_certificate_is_checked(tmp_path: Path) -> None:
    crt, key = _cert(tmp_path, ["trialbox.hosp.test"])
    env = {"TB_TLS_MODE": "hospital", "TB_TLS_HOSTNAME": "trialbox.hosp.test", "TB_TLS_CERT_FILE": str(crt),
           "TB_TLS_KEY_FILE": str(key)}  # fmt: skip
    assert check_tls(env).ok
    assert check_tls({**env, "TB_TLS_HOSTNAME": "other.hosp.test"}).problems[0].startswith("the certificate does not")
    wild, wkey = _cert(tmp_path, ["*.hosp.test"])
    assert check_tls({**env, "TB_TLS_CERT_FILE": str(wild), "TB_TLS_KEY_FILE": str(wkey)}).ok
    _, other_key = _cert(tmp_path, ["x.hosp.test"])
    assert "does not belong" in check_tls({**env, "TB_TLS_KEY_FILE": str(other_key)}).problems[0]
    old, okey = _cert(tmp_path, ["old.hosp.test", "trialbox.hosp.test"], days=-1, start=-30)
    assert "not valid now" in check_tls({**env, "TB_TLS_CERT_FILE": str(old), "TB_TLS_KEY_FILE": str(okey)}).problems[0]
    soon, skey = _cert(tmp_path, ["soon.hosp.test", "trialbox.hosp.test"], days=10)
    rep = check_tls({**env, "TB_TLS_CERT_FILE": str(soon), "TB_TLS_KEY_FILE": str(skey)})
    assert rep.ok and any("ends on" in n for n in rep.notes)
    assert not check_tls({**env, "TB_TLS_CERT_FILE": str(tmp_path / "missing.crt")}).ok


def test_cli_unlock_reset_totp_and_check_tls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                             capsys: pytest.CaptureFixture[str]) -> None:  # fmt: skip
    from console import cli

    monkeypatch.setenv("TB_AUDIT_DIR", str(tmp_path / "audit"))
    store = UserStore()
    store.create("crc1", "coordinator", VIEWER_PW)
    for _ in range(5):
        store.record_failure("crc1")
    assert store.locked("crc1")
    assert cli.main(["unlock", "crc1"]) == 0 and not store.locked("crc1")
    store.set_totp("crc1", totp.SecretBox(tmp_path / "k").seal("crc1", totp.new_secret()), 1)
    assert cli.main(["reset-totp", "crc1"]) == 0 and store.totp_state("crc1") == (None, None)
    assert store.enrol_state("crc1") == (True, "reset")
    assert cli.main(["enrol-code", "crc1"]) == 0
    printed = capsys.readouterr().out
    codes = re.findall(r"valid 24 hours\): ([a-z0-9-]+)", printed)
    assert len(codes) == 2 and store.check_enrol_code("crc1", codes[1]) and not store.check_enrol_code("crc1", codes[0])
    events = [e["event"] for e in _events(tmp_path / "audit")]
    assert events == ["console.unlock", "console.totp_reset", "console.enrol_code"]
    assert not any(c in json.dumps(_events(tmp_path / "audit")) for c in codes)
    monkeypatch.setenv("TB_TLS_HOSTNAME", "trialbox.hosp.test")
    assert cli.main(["check-tls"]) == 0
    monkeypatch.setenv("TB_TLS_MODE", "hospital")
    assert cli.main(["check-tls"]) == 1
    assert "FAIL" in capsys.readouterr().err


# ---------------------------------------------------------------------------------------------- deploy files
DEPLOY = Path(__file__).resolve().parents[2] / "deploy"


def test_identity_example_files_hold_the_safe_settings() -> None:
    """What needs no Docker: the Authelia example and the settings example. The Caddyfile and the compose overlay are
    checked by the real tools in test_identity_overlay_merged_config (below) and in CI (caddy validate, compose
    config and a smoke run: .github/workflows/trialbox-identity.yml)."""
    authelia = (DEPLOY / "identity" / "authelia" / "configuration.example.yml").read_text(encoding="utf-8")
    for line in ("implementation: activedirectory", "require_pkce: true", "pkce_challenge_method: S256",
                 "authorization_policy: two_factor", "/auth/oidc/callback", "ldaps://", "remember_me: -1",
                 "- domain: auth.trialbox.hospital.example"):  # fmt: skip
        assert line in authelia, line
    example = (DEPLOY / "identity" / "identity.env.example").read_text(encoding="utf-8")
    assert "TB_OIDC_ENABLED=0" in example and "TB_CONSOLE_MFA=totp" in example
    for line in example.splitlines():  # compose .env: a comment on its own line only
        assert line.startswith("#") or " #" not in line, line


def _compose_config(tmp_path: Path, extra_env: dict[str, str]) -> dict[str, Any]:
    """``docker compose config`` of the base file plus the identity overlay, as the box would merge them."""
    import os
    import shutil
    import subprocess

    docker = shutil.which("docker")
    if (
        docker is None
        or subprocess.run([docker, "compose", "version"], check=False, capture_output=True).returncode != 0
    ):
        pytest.skip("docker compose is not installed here (the CI job trialbox-identity runs this test)")
    env_file = tmp_path / "compose.env"
    env_file.write_text("")
    env = {**os.environ, "TB_TLS_HOSTNAME": "trialbox.hosp.test", **extra_env}
    cmd = [docker, "compose", "--project-directory", str(DEPLOY), "--env-file", str(env_file),
           "-f", str(DEPLOY / "docker-compose.yml"), "-f", str(DEPLOY / "docker-compose.identity.yml"),
           "--profile", "oidc", "config", "--format", "json", "--no-path-resolution"]  # fmt: skip
    created = not (DEPLOY / ".env").exists()
    if created:  # env_file: [.env] of the base file must exist for compose to read it
        (DEPLOY / ".env").write_text("")
    try:
        out = subprocess.run(cmd, check=False, capture_output=True, text=True, env=env, cwd=DEPLOY)
    finally:
        if created:
            (DEPLOY / ".env").unlink()
    assert out.returncode == 0, out.stderr
    doc: dict[str, Any] = json.loads(out.stdout)
    return doc


def test_identity_overlay_merged_config(tmp_path: Path) -> None:
    cfg = _compose_config(tmp_path, {})
    svc = cfg["services"]
    published = {name: [p.get("published") for p in s.get("ports", [])] for name, s in svc.items() if s.get("ports")}
    assert published == {"caddy": ["443"]}, published  # only Caddy, only 443; the console's 8090 is gone
    console = svc["console"]["environment"]
    assert console["TB_CONSOLE_SECURE_COOKIE"] == "1" and console["TB_CONSOLE_SSO_HEADER"] == ""
    assert console["TB_OIDC_ENABLED"] == "0"  # off unless the site turns it on
    assert console["TB_OIDC_REDIRECT_URL"] == "https://trialbox.hosp.test/auth/oidc/callback"
    assert "@sha256:" in svc["caddy"]["image"] and "@sha256:" in svc["authelia"]["image"]
    assert all("caddy-data" not in json.dumps(v) for v in svc["console"].get("volumes", []))  # never the CA keys
    assert svc["caddy"]["environment"]["TB_TLS_MODE"] == "internal"


def test_caddy_strips_identity_headers_and_query_strings_from_logs() -> None:
    """Static part of review H1/M4 (the CI smoke run sends the headers through a real Caddy)."""
    caddy = (DEPLOY / "identity" / "Caddyfile").read_text(encoding="utf-8")
    block = caddy[caddy.index("request_header {") : caddy.index("reverse_proxy console:8090")]
    for header in ("-X-Forwarded-User", "-Remote-User", "-{$TB_CONSOLE_SSO_HEADER:", "-X-Forwarded-Groups"):
        assert header in block, header
    assert "request>uri regexp" in caddy and "request>headers>Cookie delete" in caddy


def test_a_half_done_sign_in_expires(tmp_path: Path) -> None:
    clock = Clock()
    app, users, _ = _app(tmp_path, clock, TB_CONSOLE_MFA="totp")
    enrol = users.issue_enrol_code("viewer")
    c = TestClient(app)
    _password(c, "viewer", VIEWER_PW)
    key, mfa = _code_page(c)
    assert key
    clock.tick(minutes=11)  # the password was given more than ten minutes ago
    r = _code(c, totp.totp(key, clock.unix()), mfa, enrol)
    assert r.status_code == 303 and r.headers["location"] == "/login" and not _signed_in(c)
    assert users.totp_state("viewer") == (None, None)


# ---------------------------------------------------------------------------------------------- review 2026-11-10
def test_no_authenticator_and_no_enrolment_code_means_no_way_in(tmp_path: Path) -> None:
    """H2: an existing account after the upgrade (or after a reset) cannot set up a device with its password alone."""
    clock = Clock()
    app, users, _ = _app(tmp_path, clock, TB_CONSOLE_MFA="totp")
    c = TestClient(app)
    assert _password(c, "viewer", VIEWER_PW).headers["location"] == "/login/totp"
    r = c.get("/login/totp")
    assert r.status_code == 403 and 'data-testid="totp-no-code"' in r.text and 'id="totp-key"' not in r.text
    assert (
        c.post("/login/totp", data={"code": "123456", "mfa_csrf": "x"}, follow_redirects=False).headers["location"]
        == "/login"
    )  # the half-done sign-in is gone
    code = users.issue_enrol_code("viewer")
    clock.tick(hours=24, minutes=1)  # the code runs out after a day
    assert users.enrol_state("viewer")[0] is False and not users.check_enrol_code("viewer", code)
    _password(c, "viewer", VIEWER_PW)
    assert c.get("/login/totp").status_code == 403
    code = users.issue_enrol_code("viewer")
    assert users.check_enrol_code("viewer", code.upper().replace("-", " "))  # typed in groups or capitals
    _enrol(app, clock, "viewer", VIEWER_PW, code=code)
    assert not users.check_enrol_code("viewer", code)  # used up
    with pytest.raises(AuthError):  # an enrolled account gets no enrolment code; it is reset instead
        users.issue_enrol_code("viewer")
    assert not _signed_in(TestClient(app))


def test_admin_page_lists_accounts_without_an_authenticator_and_issues_a_code(tmp_path: Path) -> None:
    clock = Clock()
    app, users, audit_dir = _app(tmp_path, clock, TB_CONSOLE_MFA="totp")
    users.create("crc1", "coordinator", VIEWER_PW)
    admin, _ = _enrol(app, clock, "admin", ADMIN_PW)
    page = admin.get("/ops/identity").text
    box = page[page.index('data-testid="identity-unenrolled"') :]
    box = box[: box.index("</section>")]
    assert 'data-user="viewer"' in box and 'data-user="crc1"' in box and 'data-user="admin"' not in box
    csrf = re.search(r'name="csrf" value="([^"]+)"', page)
    assert csrf
    r = admin.post("/ops/identity", data={"csrf": csrf.group(1), "action": "enrol_code", "username": "crc1"})
    shown = re.search(r'id="enrol-code-value"[^>]*value="([a-z0-9-]+)"', r.text)
    assert r.status_code == 200 and shown and users.check_enrol_code("crc1", shown.group(1))
    assert "enrol" not in str(r.url) and shown.group(1) not in admin.get("/ops/identity").text  # shown once
    ev = [e for e in _events(audit_dir) if e["event"] == "console.enrol_code"]
    assert ev[0]["actor"] == "console:admin" and ev[0]["detail"] == {"user": "crc1"}
    form = {"csrf": csrf.group(1), "action": "enrol_code", "username": "admin"}
    assert admin.post("/ops/identity", data=form).status_code == 400  # never for one's own account
    clock.tick(seconds=30)
    _enrol(app, clock, "crc1", VIEWER_PW, code=shown.group(1))


def test_trusted_header_never_skips_the_password_or_the_second_factor(tmp_path: Path) -> None:
    """H1: the header SSO is refused at start with TOTP or OIDC on, and never signs in a local account."""
    sso = {
        "TB_CONSOLE_SSO_HEADER": "X-Forwarded-User",
        "TB_CONSOLE_SSO_TRUSTED_PROXIES": "testclient",
    }
    clock = Clock()
    base = {"TB_ENV": "TEST", "TB_CONSOLE_DIR": str(tmp_path / "c"), **sso}
    with pytest.raises(PilotRefused, match="TB_CONSOLE_MFA=off"):
        ConsoleSettings.from_env({**base, "TB_CONSOLE_MFA": "totp"})
    with pytest.raises(PilotRefused, match="TB_CONSOLE_MFA=off"):
        ConsoleSettings.from_env({**base, "TB_ENV": "PRODUCTION"})
    with pytest.raises(PilotRefused, match="OIDC off"):
        ConsoleSettings.from_env({**base, **OIDC_ENV, "TB_OIDC_CLIENT_SECRET_FILE": str(tmp_path / "s")})
    app, users, audit_dir = _app(tmp_path, clock, **sso)  # TEST, TOTP off: the one allowed combination
    spoof = TestClient(app, headers={"X-Forwarded-User": "admin"})
    assert not _signed_in(spoof) and users.get("admin").role == "admin"  # type: ignore[union-attr]
    rejected = [e for e in _events(audit_dir) if e["event"] == "console.sso_rejected"]
    assert rejected and rejected[-1]["detail"]["reason"] == "a local account has this name"
    assert TestClient(app, headers={"X-Forwarded-User": "newnurse"}).get("/").status_code == 200


def test_auto_refresh_does_not_keep_a_session_awake(tmp_path: Path) -> None:
    """H3: a running job's page refreshes itself every 5 seconds through the URL the page gives (auto=1); those
    requests are not activity, so the session still ends at the idle limit."""
    clock = Clock()
    app, users, _ = _app(tmp_path, clock)
    backend: FakeBackend = app.state.test_backend
    job = _done_feas(backend)
    backend.jobs[job.job_id] = job.model_copy(update={"state": "running"})
    c = TestClient(app)
    _password(c, "admin", ADMIN_PW)
    html = c.get("/jobs").text
    m = re.search(r'<meta http-equiv="refresh" content="5;url=([^"]+)">', html)
    assert m, "a running job's page refreshes itself"
    url = m.group(1).replace("&amp;", "&")
    assert url == "/jobs?auto=1"
    status = 200
    for _ in range(10 * 12 + 1):  # ten minutes and five seconds of refreshes only
        clock.tick(seconds=5)
        status = c.get(url, follow_redirects=False).status_code
        if status != 200:
            break
    assert status == 303 and clock.t - T0 > users.idle  # signed out at the idle limit, not before
    c2 = TestClient(app)
    _password(c2, "admin", ADMIN_PW)
    for _ in range(4):  # clicks keep a session awake
        clock.tick(minutes=9)
        assert c2.get("/jobs", follow_redirects=False).status_code == 200
