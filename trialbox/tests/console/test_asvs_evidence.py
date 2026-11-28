"""Card V-3 (plan 8, V9): evidence tests for the ASVS 4.0.3 Level 2 checklist.

The page is ``docs/plan/measurements/asvs-l2-checklist-2026-11-17.md``. Each test names the ASVS requirement it
judges. A plain test is evidence for "meets". A test marked ``xfail(strict=True)`` shows a finding of the page: it
turns the build red the day the product is fixed, until the mark is removed. These tests change no product code and
use only the in-process console with synthetic accounts.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
from pathlib import Path
from typing import Any, cast

import pytest
from console.app import COOKIE, create_app
from console.auth import AuthError, UserStore
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from tb_common.audit import AuditFull, AuditLog

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


@pytest.mark.xfail(strict=True, reason="V3-05: a password longer than 256 characters is accepted when chosen, but "
                   "the sign-in reads only 256, so it never signs in (ASVS 2.1.2, 2.1.3)")  # fmt: skip
def test_v2_1_2_a_long_password_is_refused_when_chosen_or_signs_in(tmp_path: Path) -> None:
    """Passes under either correct fix: refused when it is chosen (ASVS 2.1.2 allows refusing more than 128
    characters, as long as 64 are allowed), or accepted and then signs in. Fails only on "accepted, then cannot sign
    in"."""
    app = _app(tmp_path)
    long_pw = "synthetic-long-passphrase-" * 12  # 312 characters
    try:
        app.state.identity.users.set_password("viewer", long_pw, owner=True)
    except AuthError:
        return  # refused when chosen: a correct fix
    assert _sign_in(TestClient(app), "viewer", long_pw).status_code == 303


def _trusted_proxies_as_configured() -> str:
    """What uvicorn in the console container trusts for forwarded headers, as the files a box is installed from set it:
    the base file's ``--forwarded-allow-ips`` (its ``${TB_CONSOLE_FORWARDED_ALLOW_IPS:-...}`` default), a value the
    installer writes for that variable into deploy/.env, or, in the identity overlay's console block, a command with
    the flag or uvicorn's own ``FORWARDED_ALLOW_IPS`` variable. Any of these ways counts. H-137: a
    ``${TB_CONSOLE_FORWARDED_ALLOW_IPS:-...}`` default in the overlay is what a box behind Caddy runs with too."""
    base = (DEPLOY / "docker-compose.yml").read_text(encoding="utf-8")
    m = re.search(r'"--forwarded-allow-ips",\s*"\$\{TB_CONSOLE_FORWARDED_ALLOW_IPS:-([^}]*)\}"', base)
    assert m, "the base file's console command no longer names --forwarded-allow-ips"
    value = m.group(1)
    install = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    m = re.search(r"TB_CONSOLE_FORWARDED_ALLOW_IPS=[\"']?([^\s\"']+)", install)
    value = m.group(1) if m else value
    overlay = (DEPLOY / "docker-compose.identity.yml").read_text(encoding="utf-8")
    block = overlay[overlay.index("\n  console:\n") :]
    for pat in (r"--forwarded-allow-ips[\"',\s=]+([^\"'\]\s,]+)", r"\bFORWARDED_ALLOW_IPS:\s*\"?([^\"\s]+)",
                r"(?<!\{)TB_CONSOLE_FORWARDED_ALLOW_IPS:\s*\"?([^\"\s]+)"):  # fmt: skip
        m = re.search(pat, block)
        if m and not m.group(1).startswith("$"):
            value = m.group(1)
        elif m and (d := re.fullmatch(r"\$\{TB_CONSOLE_FORWARDED_ALLOW_IPS:-([^}]+)\}", m.group(1))):
            value = d.group(1)
    return value


def _caddy_address_as_configured() -> str:
    """H-137: Caddy's fixed address on the box's internal network, as the identity overlay sets it."""
    overlay = (DEPLOY / "docker-compose.identity.yml").read_text(encoding="utf-8")
    m = re.search(r'ipv4_address:\s*"\$\{TB_PROXY_ADDR:-([^}]+)\}"', overlay)
    assert m, "the identity overlay gives Caddy no fixed address"
    return m.group(1)


@pytest.mark.nodb
def test_v2_2_1_behind_caddy_two_browsers_are_two_addresses() -> None:
    """Behaviour, not a variable name: uvicorn's own proxy-header middleware, with the trust the files configure, in
    front of an app that answers the client address it sees; Caddy at its fixed address on the box's internal network
    (H-137, closing V3-01) sends two requests forwarded for two different browsers, and another container's
    forwarded header is not believed."""
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    async def echo(scope: Any, receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": str(scope["client"][0]).encode()})

    app = ProxyHeadersMiddleware(echo, trusted_hosts=_trusted_proxies_as_configured())
    caddy = TestClient(cast(Any, app), client=(_caddy_address_as_configured(), 41000))
    a = caddy.get("/", headers={"X-Forwarded-For": "10.20.0.11", "X-Forwarded-Proto": "https"}).text
    b = caddy.get("/", headers={"X-Forwarded-For": "10.20.0.12", "X-Forwarded-Proto": "https"}).text
    assert a != b, (a, b)
    other = TestClient(cast(Any, app), client=("172.31.252.7", 41000))  # another container on the same network
    assert other.get("/", headers={"X-Forwarded-For": "10.20.0.13"}).text == "172.31.252.7"


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


#: the changing page routes whose CSRF refusal the walk below shows (it fails when fewer are shown, so a walk that
#: stops reaching the check cannot stay green); the page lists the others as "read from code, not shown"
CSRF_SHOWN_AT_LEAST = 84
CSRF_WALK_OUT = os.environ.get("TB_ASVS_CSRF_WALK_OUT", "")
_BARE_ONLY = ("/logout", "/role", "/lang")


def _problem_text(r: Any) -> str:
    m = re.search(r'data-testid="problem">(.*?)</p>', r.text, re.S)
    return m.group(1) if m else ""


@pytest.mark.usefixtures("held_dir")
def test_v4_2_2_every_changing_page_route_refuses_a_post_without_the_csrf_token(
    box: dict[str, Any],  # noqa: F811
) -> None:
    """ASVS 4.2.2. For every POST, PUT or DELETE page route and every role of the role walk: the request without the
    token is sent first, then the same request with the role's token. Where the role is let in with the token (the
    answer is not a sign-in, 403, 404, 405, 422 or 503, and not the CSRF refusal), the answer without the token must be
    the CSRF refusal itself: 400 with the console's CSRF sentence, taken from ``POST /lang`` without a token (a route
    whose check is ``csrf_ok``). A route no role is let into with the token is "not shown". ``/api/v1`` takes a bearer
    token, never the cookie, and the sign-in pages carry their own token: both are left out."""
    from tests.console.test_role_route_matrix import _clients, _for, _orchestrator_routes

    _orchestrator_routes(box)
    job_id = _ulid(994)
    _done_screen(box["backend"], job_id)
    clients = _clients(box)
    page0 = clients["admin"][0]
    ref = page0.post("/lang", data={"lang": "en", "back": "/"}, follow_redirects=False)
    assert ref.status_code == 400 and _problem_text(ref), ref.text[-400:]
    csrf_sentence = _problem_text(ref)
    routes = sorted({(m, r.path) for r in box["app"].routes if isinstance(r, APIRoute)
                     for m in (r.methods or ()) if m in ("POST", "PUT", "DELETE")
                     and not _PRE_SIGN_IN.match(r.path)})  # fmt: skip
    ids = {"rs": "GZQO", "ruleset": "GZQO", "pid": A, "job_id": job_id, "action": "backup_check"}
    shown: set[str] = set()
    wrong: list[str] = []
    for method, path in routes:
        url = re.sub(r"\{(\w+)(?::\w+)?\}", lambda m: ids.get(m.group(1), "1"), path)
        _for(box, path)
        for col, (page, csrf, _api) in clients.items():
            bare = page.request(method, url, data={}, follow_redirects=False)
            if path in _BARE_ONLY:  # every signed-in role is let in; with the token it would end or change the session
                if bare.status_code == 400 and _problem_text(bare) == csrf_sentence:
                    shown.add(f"{method} {path}")
                else:
                    wrong.append(f"{col} {method} {path}: without the token -> {bare.status_code}")
                continue
            withtok = page.request(method, url, data={"csrf": csrf}, follow_redirects=False)
            loc = withtok.headers.get("location", "").split("?")[0]
            refused_csrf = withtok.status_code == 400 and _problem_text(withtok) == csrf_sentence
            if withtok.status_code in (401, 403, 404, 405, 422, 503) or loc.endswith("/login") or refused_csrf:
                continue  # not let in with the token: this role tells nothing about the check
            if bare.status_code == 400 and _problem_text(bare) == csrf_sentence:
                shown.add(f"{method} {path}")
            else:
                wrong.append(f"{col} {method} {path}: without the token -> {bare.status_code}")
    _for(box, "")
    if CSRF_WALK_OUT:
        Path(CSRF_WALK_OUT).write_text(json.dumps({"shown": sorted(shown), "routes": [f"{m} {p}" for m, p in routes]},
                                                  indent=1))  # fmt: skip
    assert not wrong, "\n".join(wrong)
    assert len(shown) >= CSRF_SHOWN_AT_LEAST, sorted(shown)


def test_v4_the_api_refuses_a_page_cookie_and_takes_only_its_own_bearer_token(
    box: dict[str, Any],  # noqa: F811
) -> None:
    """ASVS 3.5.2, 4.2.2 and 13.2.3, through a route of ``/api/v1`` (its ``api_session`` dependency): the browser's
    page cookie opens nothing, a page token sent as a bearer token opens nothing, and only a token of
    ``POST /api/v1/session`` does; so a cross-site form cannot reach the API with the browser's cookie."""
    page, _ = login(box["app"], "viewer", VIEWER_PW)
    page_token = page.cookies.get(COOKIE)
    assert page_token
    assert page.get("/api/v1/studies").status_code == 401  # the cookie alone
    as_bearer = TestClient(box["app"], headers={"Authorization": f"Bearer {page_token}"})
    assert as_bearer.get("/api/v1/studies").status_code == 401
    api_token, _ = box["users"].new_session(box["users"].get("viewer"), via="api")
    api = TestClient(box["app"], headers={"Authorization": f"Bearer {api_token}"})
    assert api.get("/api/v1/studies").status_code == 200
    page.cookies.set(COOKIE, api_token)  # and the API's token is no page cookie
    r = page.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")


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


#: a chart-number-shaped value, invented for this test
CHART_LIKE = "70000054"


def _audit_text(b: dict[str, Any]) -> str:
    return "".join(f.read_text(encoding="utf-8") for f in sorted((b["dir"] / "audit").glob("*")) if f.is_file())


@pytest.mark.xfail(strict=True, reason="V3-14: a chart number typed in a break-glass note is written into the audit "
                   "in clear (ASVS 7.1.2; full review J-M1)")  # fmt: skip
def test_v7_1_2_a_chart_number_in_a_break_glass_note_does_not_reach_the_audit(box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(995))
    admin, _ = login(box["app"])
    r = _open(admin, kind="patient", ruleset="GZQO", pid=A, note=f"support call, chart {CHART_LIKE} checked")
    assert r.headers.get("location") == "/breakglass?done=open"  # the grant opened (the event was written)
    assert "console.breakglass_open" in _audit_text(box)
    assert CHART_LIKE not in _audit_text(box)


@pytest.mark.xfail(strict=True, reason="V3-18: a break-glass grant is stored before its audit event; when the audit "
                   "write fails (AuditFull) the grant stays open with no event (ASVS 7.1.3)")  # fmt: skip
def test_v7_1_3_a_grant_whose_audit_event_fails_is_not_left_open(
    box: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _done_screen(box["backend"], _ulid(996))
    admin, _ = login(box["app"])
    csrf = re.search(r'name="csrf" value="([^"]+)"', admin.get("/breakglass").text)
    assert csrf
    monkeypatch.setenv("TB_AUDIT_MIN_FREE_MB", str(10**12))  # the audit volume reads as full: append raises AuditFull
    # today the request ends in AuditFull; a fix may refuse it with an answer instead: either way no grant may be left
    with contextlib.suppress(AuditFull):
        admin.post("/breakglass", data={"csrf": csrf.group(1), "reason": "support", "kind": "patient",
                                        "note": "support call about one patient", "ruleset": "GZQO", "pid": A})  # fmt: skip
    monkeypatch.delenv("TB_AUDIT_MIN_FREE_MB")
    assert "console.breakglass_open" not in _audit_text(box)
    assert 'data-testid="bg-active"' not in admin.get("/breakglass").text, "a grant is open with no audit event"


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
