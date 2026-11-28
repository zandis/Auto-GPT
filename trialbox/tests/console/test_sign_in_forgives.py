"""TOL-AUTH (TOL-1 §2.5; STOPS.csv T-A020, T-A021, T-A030, T-A031, T-A032): sign-in that a clinical person gets through.

* T-A021: a password reset on ``/ops/users`` for a local account with no authenticator hands over an enrolment code
  with the password (as an account made there does, E2E P-17), so "a password and no code" cannot arise; the page an
  account without either sees says where the administrator makes one.
* T-A032: the locked page says the time (as before) and who can unlock it sooner.
* T-A020: a code that is right for a minute a little off (the box's clock or the phone's) says so; a random code
  does not. The accepted window is not widened: the clock code is still a failed try.
* T-A030/T-A031: a form sent after the session ended (idle or the absolute end) comes back, values filled, after the
  SAME account signs in again; never a password or code, never to another account, once.

The kept classes keep their tests: the lockout (test_identity's lockout tests), the idle and absolute ends
(test_idle_warning), the TOTP window (test_identity's RFC vectors and replay tests). Synthetic data only."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from console import totp
from fastapi.testclient import TestClient

from tests.console.test_console_app import ADMIN_PW, VIEWER_PW
from tests.console.test_identity import Clock, _app, _code, _code_page, _enrol, _events, _password
from tests.console.test_no_one_holds_both_factors import _box

ROOT = Path(__file__).resolve().parents[2]


def _csrf(text: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', text)
    assert m, text
    return m.group(1)


# ---------------------------------------------------------------------------------------------- T-A021
def test_a_password_reset_hands_over_the_code_an_account_without_an_authenticator_needs(tmp_path: Path) -> None:
    app, users, audit_dir, clock = _box(tmp_path, steward=False, TB_CONSOLE_MFA="totp")
    admin, _key = _enrol(app, clock, "admin", ADMIN_PW)
    assert users.enrol_state("viewer") == (False, "first")  # made before: no authenticator, no live code
    r = admin.post("/ops/users", data={"csrf": _csrf(admin.get("/ops/users").text), "action": "reset",
                                       "username": "viewer", "confirm": "yes"})  # fmt: skip
    pw = re.search(r'value="([^"]+)" data-testid="users-pw-field"', r.text)
    code = re.search(r'data-testid="users-pw-code" value="([a-z0-9-]+)"', r.text)
    assert pw and code, r.text  # one hand-over: the password and the code, no CLI
    c = TestClient(app, base_url="https://testserver")
    assert _password(c, "viewer", pw.group(1)).headers["location"] == "/login/totp"
    key, mfa = _code_page(c)
    assert key
    r = _code(c, totp.totp(key, clock.unix()), mfa, code.group(1))
    assert r.status_code == 303 and r.headers["location"] == "/account"  # signed in; the set password is replaced
    assert code.group(1) not in repr(_events(audit_dir))


def test_a_password_reset_leaves_a_working_authenticator_alone(tmp_path: Path) -> None:
    app, users, _audit, clock = _box(tmp_path, steward=False, TB_CONSOLE_MFA="totp")
    admin, _key = _enrol(app, clock, "admin", ADMIN_PW)
    _enrolled(app, clock, "viewer", VIEWER_PW)
    r = admin.post("/ops/users", data={"csrf": _csrf(admin.get("/ops/users").text), "action": "reset",
                                       "username": "viewer", "confirm": "yes"})  # fmt: skip
    assert 'data-testid="users-pw-field"' in r.text and "users-pw-code" not in r.text
    assert users.totp_state("viewer")[0] is not None


def test_an_account_with_no_way_in_is_told_where_the_code_comes_from(tmp_path: Path) -> None:
    clock = Clock()
    app, _users, _audit = _app(tmp_path, clock, TB_CONSOLE_WORKSPACE="on", TB_CONSOLE_MFA="totp")
    c = TestClient(app, base_url="https://testserver")
    assert _password(c, "viewer", VIEWER_PW).headers["location"] == "/login/totp"
    page = c.get("/login/totp").text
    assert 'data-testid="totp-no-code-where"' in page and "Reset password" in page and "Users" in page


# ---------------------------------------------------------------------------------------------- T-A032
def test_the_locked_page_says_until_when_and_who_can_unlock(tmp_path: Path) -> None:
    clock = Clock()
    app, users, _audit = _app(tmp_path, clock, TB_CONSOLE_WORKSPACE="on")
    c = TestClient(app)
    for _ in range(5):
        r = _password(c, "viewer", "not-the-password-000")
    assert users.locked("viewer")
    assert r.status_code == 401 and 'data-testid="login-locked"' in r.text
    locked = r.text.split('data-testid="login-locked"')[1][:1500]
    assert re.search(r"\d{1,2}:\d{2}", locked)  # the time it opens again
    assert 'data-testid="login-locked-who"' in locked and "administrator" in locked
    assert "Sign-in and recovery" in locked and "Unlock" in locked  # the page and the button that lift it


# ---------------------------------------------------------------------------------------------- T-A020
def test_a_code_right_for_a_nearby_minute_gets_the_clock_sentence_and_a_random_one_does_not(tmp_path: Path) -> None:
    clock = Clock()
    app, _users, audit_dir = _app(tmp_path, clock, TB_CONSOLE_WORKSPACE="on", TB_CONSOLE_MFA="totp")
    _c, key = _enrolled(app, clock, "viewer", VIEWER_PW)
    clock.tick(minutes=2)
    c = TestClient(app, base_url="https://testserver")
    assert _password(c, "viewer", VIEWER_PW).headers["location"] == "/login/totp"
    _, mfa = _code_page(c)
    ahead = totp.totp(key, clock.unix() + 3 * totp.STEP_SECONDS)  # the phone 90 s fast (E2E OPS-clock: 94 s)
    r = _code(c, ahead, mfa)
    assert r.status_code == 401 and "right for a different minute" in r.text
    near = {totp.totp(key, clock.unix() + s * totp.STEP_SECONDS) for s in range(-totp.NEAR, totp.NEAR + 1)}
    bad = next(x for x in (str(n).zfill(6) for n in range(123_457, 10**6, 7919)) if x not in near)  # random-like
    r = _code(c, bad, mfa)
    assert r.status_code == 401 and "different minute" not in r.text and "That code is not right" in r.text
    reasons = [e["detail"].get("reason") for e in _events(audit_dir) if e["event"] == "console.login_failed"]
    assert reasons[-2:] == ["clock", "wrong"]  # IT reads a clock problem in the audit


def test_the_accepted_window_is_not_widened() -> None:
    key = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # the RFC 6238 key: fixed, so no chance collision of two steps
    assert totp.verify(key, totp.totp(key, 1_000_000 + 2 * totp.STEP_SECONDS), 1_000_000, None) is None
    assert totp.near_step(key, totp.totp(key, 1_000_000 + 2 * totp.STEP_SECONDS), 1_000_000)
    assert not totp.near_step(key, totp.totp(key, 1_000_000), 1_000_000)  # the accepted minute is no clock problem


# ---------------------------------------------------------------------------------------------- T-A030 / T-A031
def _enrolled(app: Any, clock: Clock, user: str, pw: str) -> tuple[TestClient, str]:
    """Sign in with a fresh enrolment code and set up the authenticator; (the signed-in browser, its key)."""
    enrol = app.state.identity.users.issue_enrol_code(user)
    c = TestClient(app, base_url="https://testserver")
    assert _password(c, user, pw).headers["location"] == "/login/totp"
    key, mfa = _code_page(c)
    assert key
    r = _code(c, totp.totp(key, clock.unix()), mfa, enrol)
    assert r.status_code == 303, r.text
    return c, key


def _signed_in_viewer(app: Any) -> TestClient:
    c = TestClient(app)
    assert _password(c, "viewer", VIEWER_PW).status_code == 303
    return c


def _send_after_the_end(c: TestClient, csrf: str) -> None:
    r = c.post("/feedback", data={"csrf": csrf, "path": "/help", "rating": "2", "comment": "half-typed note",
                                  "password": "never-kept-0001"},
               headers={"referer": "http://testserver/help"}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303 and r.headers["location"] == "/login?why=idle"


def _draft(text: str) -> dict[str, Any] | None:
    m = re.search(r'<script type="application/json" id="tb-draft"[^>]*>(.*?)</script>', text, re.S)
    return json.loads(m.group(1)) if m else None


def test_a_form_sent_after_the_idle_end_is_back_after_signing_in_again(tmp_path: Path) -> None:
    clock = Clock()
    app, _users, audit_dir = _app(tmp_path, clock, TB_CONSOLE_WORKSPACE="on")
    c = _signed_in_viewer(app)
    csrf = _csrf(c.get("/help").text)
    clock.tick(minutes=11)  # past the 10-minute idle end
    _send_after_the_end(c, csrf)
    r = _password(c, "viewer", VIEWER_PW)
    assert r.status_code == 303 and r.headers["location"] == "/help"  # D-777: back to the page
    draft = _draft(c.get("/help").text)
    assert draft == {"action": "/feedback", "fields": {"path": ["/help"], "rating": ["2"],
                                                       "comment": ["half-typed note"]}}  # fmt: skip
    assert _draft(c.get("/help").text) is None  # once
    assert "half-typed note" not in repr(_events(audit_dir))  # typed text is never audited


def test_after_the_absolute_end_and_through_the_code_step_too(tmp_path: Path) -> None:
    clock = Clock()
    app, users, _audit = _app(tmp_path, clock, TB_CONSOLE_WORKSPACE="on", TB_CONSOLE_MFA="totp")
    c, key = _enrolled(app, clock, "viewer", VIEWER_PW)
    csrf = _csrf(c.get("/help").text)
    for _ in range(17):  # kept active (last_seen moved) for 8 h 30: the absolute end, not the idle one
        clock.tick(minutes=30)
        users.db.execute("UPDATE sessions SET last_seen = ?", (clock().isoformat(),))
    _send_after_the_end(c, csrf)
    assert _password(c, "viewer", VIEWER_PW).headers["location"] == "/login/totp"
    _, mfa = _code_page(c)
    r = _code(c, totp.totp(key, clock.unix()), mfa)
    assert r.status_code == 303 and r.headers["location"] == "/help"
    assert (_draft(c.get("/help").text) or {}).get("fields", {}).get("comment") == ["half-typed note"]


def test_another_account_signing_in_on_the_same_browser_gets_nothing(tmp_path: Path) -> None:
    clock = Clock()
    app, _users, _audit = _app(tmp_path, clock, TB_CONSOLE_WORKSPACE="on")
    c = _signed_in_viewer(app)
    csrf = _csrf(c.get("/help").text)
    clock.tick(minutes=11)
    _send_after_the_end(c, csrf)
    assert _password(c, "admin", ADMIN_PW).status_code == 303
    assert _draft(c.get("/help").text) is None


def test_a_kept_form_expires_with_the_kept_page(tmp_path: Path) -> None:
    clock = Clock()
    app, _users, _audit = _app(tmp_path, clock, TB_CONSOLE_WORKSPACE="on")
    c = _signed_in_viewer(app)
    csrf = _csrf(c.get("/help").text)
    clock.tick(minutes=11)
    _send_after_the_end(c, csrf)
    clock.tick(minutes=16)  # longer than the kept page's 15 minutes (D-777)
    assert _password(c, "viewer", VIEWER_PW).status_code == 303
    assert _draft(c.get("/help").text) is None


RUN_JS = """
const [src, draft] = process.argv.slice(1);
const mk = (name, type, value) => ({name, type, value, checked: false, disabled: false,
  classList: {add() {}, remove() {}}});
const fields = [mk("csrf", "hidden", "fresh"), mk("comment", "textarea", ""), mk("rating", "radio", "1"),
  mk("rating", "radio", "2"), mk("other", "text", "typed after")];
const notes = [];
const form = {getAttribute: (a) => (a === "action" ? "/feedback" : a === "data-draft-msg" ? null : null),
  elements: fields, parentNode: {insertBefore: (n) => notes.push(n.textContent || n.children.map((c) => c.textContent).join(""))}};
const el = () => ({setAttribute() {}, appendChild(c) { (this.children = this.children || []).push(c); },
  addEventListener() {}, classList: {add() {}}, children: []});
global.sessionStorage = {getItem: () => null, setItem() {}, removeItem() {}, length: 0, key: () => null};
global.navigator = {};
global.window = {location: {hash: "", pathname: "/help", search: ""}, history: {length: 1}, addEventListener: () => {}};
global.document = {
  getElementById: (id) => (id === "tb-draft" ? {textContent: draft, getAttribute: (a) => (a === "data-msg" ?
    "Fields restored: {n}." : a === "data-discard" ? "Discard" : null)} : null),
  querySelector: () => null, createElement: el,
  querySelectorAll: (q) => (q === "form" ? [form] : [])};
eval(src);
console.log(JSON.stringify({values: fields.map((f) => f.type === "radio" ? f.checked : f.value), notes}));
"""


def test_the_page_script_fills_the_kept_form_and_says_so() -> None:
    from console.app import CONSOLE_JS

    node = shutil.which("node")
    assert node, "node runs the console's script in the tests"
    draft = json.dumps({"action": "/feedback", "fields": {"csrf": ["old"], "comment": ["half-typed note"],
                                                          "rating": ["2"], "other": ["kept"]}})  # fmt: skip
    out = subprocess.run([node, "-e", RUN_JS, CONSOLE_JS, draft], capture_output=True, text=True, timeout=30,
                         check=True)  # fmt: skip
    got = json.loads(out.stdout.strip().splitlines()[-1])
    # the fresh CSRF stays, the note and the choice come back, a field typed since is not overwritten
    assert got["values"] == ["fresh", "half-typed note", False, True, "typed after"]
    assert got["notes"] and "2" in got["notes"][0]
