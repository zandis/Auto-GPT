"""Card V-3 (plan 8, V9): evidence tests for the ASVS 4.0.3 Level 2 checklist.

The page is ``docs/plan/measurements/asvs-l2-checklist-2026-11-17.md``. Each test names the ASVS requirement it
judges. A plain test is evidence for "meets". A test marked ``xfail(strict=True)`` shows a finding of the page: it
turns the build red the day the product is fixed, until the mark is removed. These tests change no product code and
use only the in-process console with synthetic accounts.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from console.app import COOKIE, create_app
from console.auth import UserStore
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from tb_common.audit import AuditLog, mask_detail

from tests.console.test_console_app import (  # noqa: F401 - the fixture is used by name
    ADMIN_PW,
    VIEWER_PW,
    FakeBackend,
    _done_screen,
    _ulid,
    box,
    login,
)
from tests.console.test_d280_breakglass import A, _open

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"


def _app(tmp_path: Path, **env: str) -> Any:
    backend = FakeBackend()
    backend.audit_dir = tmp_path / "audit"
    users = UserStore()
    users.create("admin", "admin", ADMIN_PW, "admin@hospa.test")
    users.create("viewer", "viewer", VIEWER_PW)
    base = {"TB_ENV": "TEST", "TB_CONSOLE_WORKSPACE": "off", "TB_CONSOLE_DIR": str(tmp_path / "console")}
    return create_app({**base, **env}, backend=backend, audit=AuditLog(backend.audit_dir), users=users)


def _sign_in(c: TestClient, user: str, pw: str) -> Any:
    token = re.search(r'name="login_csrf" value="([^"]+)"', c.get("/login").text)
    assert token
    return c.post("/login", data={"username": user, "password": pw, "login_csrf": token.group(1)},
                  follow_redirects=False)  # fmt: skip


def _set_cookies(r: Any, name: str) -> list[str]:
    return [v for k, v in r.headers.multi_items() if k == "set-cookie" and v.split("=", 1)[0] == name]


# ---------------------------------------------------------------------------------------------- V3 sessions
def test_v3_2_1_sign_in_makes_a_new_token_and_ignores_a_planted_one(tmp_path: Path) -> None:
    """ASVS 3.2.1: a new session token at sign-in; a token the browser already holds is never adopted."""
    app = _app(tmp_path)
    c = TestClient(app)
    planted = "planted-by-another-person-0123456789abcdef"
    c.cookies.set(COOKIE, planted)
    r = _sign_in(c, "viewer", VIEWER_PW)
    assert r.status_code == 303
    cookies = _set_cookies(r, COOKIE)
    assert cookies, r.headers
    token = cookies[0].split(";", 1)[0].split("=", 1)[1]
    assert token != planted and len(token) >= 43  # 32 random bytes, URL-safe base64
    assert app.state.identity.users.session(planted) is None


def test_v3_3_1_sign_out_ends_the_session_on_the_server(tmp_path: Path) -> None:
    """ASVS 3.3.1: after sign-out the old token opens nothing, even when a client sends it again."""
    app = _app(tmp_path)
    c = TestClient(app)
    r = _sign_in(c, "viewer", VIEWER_PW)
    token = _set_cookies(r, COOKIE)[0].split(";", 1)[0].split("=", 1)[1]
    csrf = re.search(r'name="csrf" value="([^"]+)"', c.get("/").text)
    assert csrf
    assert c.post("/logout", data={"csrf": csrf.group(1)}, follow_redirects=False).status_code == 303
    again = TestClient(app)
    again.cookies.set(COOKIE, token)
    r = again.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")


@pytest.mark.xfail(strict=True, reason="V3-02: the session cookie has no __Host- prefix (ASVS 3.4.4)")
def test_v3_4_4_the_session_cookie_has_the_host_prefix(tmp_path: Path) -> None:
    app = _app(tmp_path, TB_CONSOLE_SECURE_COOKIE="1")
    c = TestClient(app, base_url="https://testserver")
    r = _sign_in(c, "viewer", VIEWER_PW)
    assert r.status_code == 303
    session = [v for k, v in r.headers.multi_items() if k == "set-cookie" and v.startswith((f"{COOKIE}=", "__Host-"))]
    assert session and all(v.startswith("__Host-") for v in session), session


@pytest.mark.xfail(strict=True, reason="V3-12: sign-out removes the session cookie without its Secure, HttpOnly and "
                   "SameSite flags (ASVS 3.4.1-3.4.3; full review J-L2)")  # fmt: skip
def test_v3_4_sign_out_removes_the_cookie_with_the_flags_it_was_set_with(tmp_path: Path) -> None:
    app = _app(tmp_path, TB_CONSOLE_SECURE_COOKIE="1")
    c = TestClient(app, base_url="https://testserver")
    assert _sign_in(c, "viewer", VIEWER_PW).status_code == 303
    csrf = re.search(r'name="csrf" value="([^"]+)"', c.get("/").text)
    assert csrf
    r = c.post("/logout", data={"csrf": csrf.group(1)}, follow_redirects=False)
    removal = _set_cookies(r, COOKIE)
    assert removal, r.headers
    flags = removal[0].lower()
    assert "secure" in flags and "httponly" in flags and "samesite=strict" in flags, removal[0]


def test_v3_7_1_a_password_change_asks_for_the_current_password(box: dict[str, Any]) -> None:  # noqa: F811
    """ASVS 2.1.6 and 3.7.1: the owner's own change needs the current password; without it nothing changes."""
    app = box["app"]
    c, _ = login(app, "viewer", VIEWER_PW)
    csrf = re.search(r'name="csrf" value="([^"]+)"', c.get("/account").text)
    assert csrf
    new = "a-new-synthetic-password-77"
    r = c.post("/account/password", data={"csrf": csrf.group(1), "current": "not-the-password-0",
                                          "new": new, "again": new}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 400
    assert box["users"].authenticate("viewer", VIEWER_PW) is not None


@pytest.mark.xfail(strict=True, reason="V3-04: break-glass opens with no fresh password or code (ASVS 3.7.1; full "
                   "review J-M3)")  # fmt: skip
def test_v3_7_1_break_glass_asks_for_a_fresh_credential(box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(993))
    admin, _ = login(box["app"])
    r = _open(admin, kind="patient", ruleset="GZQO", pid=A)  # csrf, reason and note only: no password, no code
    assert r.headers.get("location") != "/breakglass?done=open", "a grant opened on the session alone"


# ---------------------------------------------------------------------------------------------- V2 authentication
def test_v2_1_2_a_password_of_200_characters_signs_in(tmp_path: Path) -> None:
    """ASVS 2.1.2: at least 64 characters are allowed (the control for the V3-05 test below)."""
    app = _app(tmp_path)
    pw = "synthetic-long-passphrase-" * 7 + "x" * 18  # 200 characters
    app.state.identity.users.set_password("viewer", pw, owner=True)
    assert _sign_in(TestClient(app), "viewer", pw).status_code == 303


@pytest.mark.xfail(strict=True, reason="V3-05: a password longer than 256 characters is accepted at change, but the "
                   "sign-in reads only 256, so it never signs in (ASVS 2.1.2, 2.1.3)")  # fmt: skip
def test_v2_1_2_a_long_password_that_is_accepted_also_signs_in(tmp_path: Path) -> None:
    app = _app(tmp_path)
    long_pw = "synthetic-long-passphrase-" * 12  # 312 characters
    app.state.identity.users.set_password("viewer", long_pw, owner=True)
    c = TestClient(app)
    assert _sign_in(c, "viewer", long_pw).status_code == 303


@pytest.mark.nodb
@pytest.mark.xfail(strict=True, reason="V3-01: neither the identity overlay nor the installer tells the console "
                   "which proxy to trust, so every browser behind Caddy shares one address in the sign-in lock "
                   "(ASVS 2.2.1; full review J-4)")  # fmt: skip
def test_v2_2_1_the_console_behind_caddy_trusts_the_proxy_address() -> None:
    overlay = (DEPLOY / "docker-compose.identity.yml").read_text(encoding="utf-8")
    console = overlay[overlay.index("\n  console:\n") :]  # the overlay's console block, to its end
    install = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    assert "TB_CONSOLE_FORWARDED_ALLOW_IPS" in console or "TB_CONSOLE_FORWARDED_ALLOW_IPS" in install


def test_v2_2_1_five_wrong_passwords_lock_the_name_from_that_address(tmp_path: Path) -> None:
    """ASVS 2.2.1, the mechanism (D-279): the lock is per account and address. Every browser behind one proxy is one
    address, which is why V3-01 matters: this test client stands for that one address."""
    app = _app(tmp_path)
    guesser = TestClient(app)
    for _ in range(5):
        assert _sign_in(guesser, "viewer", "wrong-password-000").status_code == 401
    owner = TestClient(app)  # another browser, the same address as the guesser
    assert _sign_in(owner, "viewer", VIEWER_PW).status_code == 401


# ---------------------------------------------------------------------------------------------- V4 access control
_PRE_SIGN_IN = re.compile(r"^/(login|enrol|auth/|api/)")


def test_v4_2_2_every_changing_page_route_refuses_a_post_without_the_csrf_token(
    box: dict[str, Any],  # noqa: F811
) -> None:
    """ASVS 4.2.2 (and 3.5.x for the API): every POST, PUT or DELETE page route, called by a signed-in account with
    no CSRF token, does not do what it was asked: 400, 403, 404, 405, 409, 422 or 503, or a redirect to sign-in. The
    sign-in pages carry their own token in a cookie of their own, and ``/api/v1`` takes a bearer token, never the
    cookie, so they are left out here."""
    _done_screen(box["backend"], _ulid(994))
    clients = {"admin": login(box["app"])[0]}
    for name, role in (("crc", "coordinator"), ("stw", "steward")):
        box["users"].create(name, role, "asvs-evidence-password-01", f"{name}@hospa.test")
        clients[name] = login(box["app"], name, "asvs-evidence-password-01")[0]
    routes = sorted({(m, r.path) for r in box["app"].routes if isinstance(r, APIRoute)
                     for m in (r.methods or ()) if m in ("POST", "PUT", "DELETE")
                     and not _PRE_SIGN_IN.match(r.path)})  # fmt: skip
    assert len(routes) > 50
    done = []
    for who, c in clients.items():
        for method, path in routes:
            url = re.sub(r"\{(\w+)(?::\w+)?\}", lambda m: {"rs": "GZQO", "ruleset": "GZQO", "pid": A,
                                                           "job_id": _ulid(994)}.get(m.group(1), "1"), path)  # fmt: skip
            r = c.request(method, url, data={}, follow_redirects=False)
            loc = r.headers.get("location", "")
            if r.status_code < 300 or (r.status_code < 400 and not loc.split("?")[0].endswith("/login")):
                done.append(f"{who} {method} {path} -> {r.status_code} {loc}")
    assert not done, "\n".join(done)


def test_v4_the_api_refuses_a_page_cookie_as_a_bearer_and_a_bearer_as_a_cookie(tmp_path: Path) -> None:
    """ASVS 3.5.2 and 4.2.2: a page session is no API token, and an API token is no page cookie (T-505a), so a
    cross-site form cannot reach ``/api/v1`` with the browser's cookie."""
    app = _app(tmp_path)
    users = app.state.identity.users
    page_token, _ = users.new_session(users.get("viewer"), via="password")
    api_token, _ = users.new_session(users.get("viewer"), via="api")
    assert users.session(page_token, api=True) is None
    assert users.session(api_token) is None
    assert users.session(page_token) is not None and users.session(api_token, api=True) is not None


# ---------------------------------------------------------------------------------------------- V5, V7, V14
def test_v5_1_5_the_language_switch_stays_on_the_console(tmp_path: Path) -> None:
    """ASVS 5.1.5: ``back`` is checked for "/" and "//" only, but the redirect percent-encodes a backslash, so
    "/\\host" stays a path of this console."""
    app = _app(tmp_path)
    c = TestClient(app)
    assert _sign_in(c, "viewer", VIEWER_PW).status_code == 303
    csrf = re.search(r'name="csrf" value="([^"]+)"', c.get("/").text)
    assert csrf
    r = c.post("/lang", data={"csrf": csrf.group(1), "lang": "en", "back": "/\\elsewhere.invalid"},
               follow_redirects=False)  # fmt: skip
    assert r.status_code == 303
    assert r.headers["location"] == "/%5Celsewhere.invalid", r.headers["location"]


@pytest.mark.nodb
@pytest.mark.xfail(strict=True, reason="V3-14: the audit mask works by key name, so a chart number in free text "
                   "stays in the audit (ASVS 7.1.2; full review J-M1)")  # fmt: skip
def test_v7_1_2_a_chart_number_in_a_free_text_note_is_masked() -> None:
    masked = mask_detail({"note": "support call about chart 70000054"})
    assert "70000054" not in str(masked), masked


def test_v14_4_security_headers_on_the_sign_in_page_and_a_signed_in_page(tmp_path: Path) -> None:
    """ASVS 14.4.1-14.4.7 as far as the console sets them (HSTS is Caddy's: deploy/identity/Caddyfile)."""
    app = _app(tmp_path)
    c = TestClient(app)
    pages = [c.get("/login")]
    assert _sign_in(c, "viewer", VIEWER_PW).status_code == 303
    pages.append(c.get("/"))
    for r in pages:
        h = r.headers
        assert r.status_code == 200
        assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
        assert h["referrer-policy"] == "no-referrer" and h["cache-control"] == "no-store"
        csp = h["content-security-policy"]
        for part in ("default-src 'self'", "object-src 'none'", "frame-ancestors 'none'", "base-uri 'none'"):
            assert part in csp, csp
        assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
        assert h["content-type"].startswith("text/html; charset=utf-8")


def test_v4_3_2_no_folder_listing_and_no_api_description_page(tmp_path: Path) -> None:
    """ASVS 4.3.2 and 14.3.2: the static folder lists nothing and the framework's own API pages are off."""
    c = TestClient(_app(tmp_path))
    for path in ("/static/", "/docs", "/redoc", "/openapi.json", "/.git/config"):
        assert c.get(path, follow_redirects=False).status_code == 404, path
