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

    def csrf_of(client: TestClient) -> str:
        return _csrf(client.get("/help").text)

    clock.tick(minutes=11)  # past the 10-minute idle end
    _send_after_the_end(c, csrf)
    r = _password(c, "viewer", VIEWER_PW)
    assert r.status_code == 303 and r.headers["location"] == "/help"  # D-777: back to the page
    draft = _draft(c.get("/help").text)
    assert draft == {"action": "/feedback", "fields": {"path": ["/help"], "rating": ["2"],
                                                       "comment": ["half-typed note"]}}  # fmt: skip
    assert _draft(c.get("/help").text) is not None  # kept until a form took it (a page render does not use it up)
    c.post(
        "/feedback",
        data={"csrf": csrf_of(c), "path": "/help", "comment": "x"},
        headers={"referer": "http://testserver/help"},
    )  # its form was sent: used up
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


def test_two_tabs_keep_two_forms_and_a_long_note_comes_back_whole(tmp_path: Path) -> None:
    clock = Clock()
    app, _users, _audit = _app(tmp_path, clock, TB_CONSOLE_WORKSPACE="on")
    c = _signed_in_viewer(app)
    csrf = _csrf(c.get("/help").text)
    clock.tick(minutes=11)
    long_note = "the patient said " + "x" * 3000  # longer than a failed form shows again (form_errors.VALUE_MAX)
    for page, note in (("/help", long_note), ("/account", "second tab")):
        r = c.post("/feedback", data={"csrf": csrf, "path": page, "comment": note},
                   headers={"referer": "http://testserver" + page}, follow_redirects=False)  # fmt: skip
        assert r.headers["location"] == "/login?why=idle"
    assert _password(c, "viewer", VIEWER_PW).status_code == 303
    assert (_draft(c.get("/help").text) or {})["fields"]["comment"] == [long_note]  # whole, never cut
    assert (_draft(c.get("/account").text) or {})["fields"]["comment"] == ["second tab"]  # the other tab's too


RUN_JS = """
const [src, spec] = process.argv.slice(1);
const {forms, draft, edit, discard} = JSON.parse(spec);
const notes = [];
const built = forms.map((f) => {
  const elements = f.fields.map(([name, type, value, more]) => ({name, type, value, checked: false, disabled: false,
    classList: {add() {}, remove() {}}, ...(more || {}),
    ...(more && more.options ? {tagName: "SELECT", options: more.options.map((o) => ({value: o, selected: false}))} : {})}));
  return {getAttribute: (a) => (a === "action" ? f.action : null), elements,
    parentNode: {insertBefore: (n) => notes.push(n), removeChild() {}}};
});
const el = () => ({setAttribute() {}, appendChild(c) { this.children.push(c); }, children: [], listeners: [],
  addEventListener(ev, fn) { this.listeners.push(fn); }, classList: {add() {}}, parentNode: {removeChild() {}}});
global.sessionStorage = {getItem: () => null, setItem() {}, removeItem() {}, length: 0, key: () => null};
global.navigator = {};
global.window = {location: {hash: "", pathname: "/help", search: ""}, history: {length: 1}, addEventListener: () => {}};
global.document = {
  getElementById: (id) => (id === "tb-draft" ? {textContent: JSON.stringify(draft), getAttribute: (a) =>
    (a === "data-msg" ? "Fields restored: {n}." : a === "data-discard" ? "Discard" : null)} : null),
  querySelector: () => null, createElement: el,
  querySelectorAll: (q) => (q === "form" ? built : [])};
eval(src);
(edit || []).forEach(([i, name, value]) => { built[i].elements.find((x) => x.name === name).value = value; });
if (discard) notes.forEach((n) => n.children[1].listeners.forEach((fn) => fn()));
console.log(JSON.stringify({
  values: built.map((f) => f.elements.map((x) => (x.options && x.multiple ? x.options.filter((o) => o.selected).map((o) => o.value)
    : x.type === "radio" ? x.checked : x.value))),
  notes: notes.map((n) => n.children.map((c) => c.textContent).join("")),
}));
"""


def _js(forms: list[dict[str, Any]], draft: dict[str, Any], **more: Any) -> dict[str, Any]:
    from console.app import CONSOLE_JS

    node = shutil.which("node")
    assert node, "node runs the console's script in the tests"
    spec = json.dumps({"forms": forms, "draft": draft, **more})
    out = subprocess.run([node, "-e", RUN_JS, CONSOLE_JS, spec], capture_output=True, text=True, timeout=30,
                         check=True)  # fmt: skip
    got: dict[str, Any] = json.loads(out.stdout.strip().splitlines()[-1])
    return got


FEEDBACK = {"action": "/feedback", "fields": [["csrf", "hidden", "fresh"], ["comment", "textarea", ""],
                                             ["rating", "radio", "1"], ["rating", "radio", "2"],
                                             ["other", "text", "typed after"]]}  # fmt: skip
KEPT = {"action": "/feedback", "fields": {"comment": ["half-typed note"], "rating": ["2"], "other": ["kept"]}}


def test_the_page_script_fills_the_kept_form_and_says_so() -> None:
    got = _js([FEEDBACK], KEPT)
    # the page's fresh CSRF stays, the note and the choice come back, a field typed since is not overwritten
    assert got["values"] == [["fresh", "half-typed note", False, True, "typed after"]]
    assert got["notes"] == ["Fields restored: 2. Discard"]


def _row(pid: str) -> dict[str, Any]:
    return {"action": "/studies/GZQO/marks", "fields": [["csrf", "hidden", "fresh"], ["pid", "hidden", pid],
                                                       ["note", "text", ""]]}  # fmt: skip


def test_only_the_row_of_the_same_patient_is_filled() -> None:
    kept = {"action": "/studies/GZQO/marks", "fields": {"pid": ["p2"], "note": ["check the creatinine"]}}
    got = _js([_row("p1"), _row("p2"), _row("p3")], kept)
    assert got["values"] == [["fresh", "p1", ""], ["fresh", "p2", "check the creatinine"], ["fresh", "p3", ""]]
    assert len(got["notes"]) == 1


def test_two_forms_that_cannot_be_told_apart_get_nothing() -> None:
    kept = {"action": "/studies/GZQO/marks", "fields": {"pid": ["p2"], "note": ["check the creatinine"]}}
    got = _js([_row("p2"), _row("p2")], kept)
    assert got["values"] == [["fresh", "p2", ""], ["fresh", "p2", ""]] and got["notes"] == []
    assert _js([_row("p1")], kept)["values"] == [["fresh", "p1", ""]]  # no form of that patient: nothing
    other = {"action": "/studies/GZQO/marks", "fields": [["csrf", "hidden", "fresh"], ["patient_id", "hidden", "p1"],
                                                        ["note", "text", ""]]}  # fmt: skip
    assert _js([other], kept)["values"] == [["fresh", "p1", ""]]  # the kept patient field is not on it: nothing


def test_discard_undoes_the_refill_but_keeps_what_was_typed_since() -> None:
    got = _js([FEEDBACK], {"action": "/feedback", "fields": {"comment": ["half-typed note"], "other": ["kept"]}},
              discard=True)  # fmt: skip
    assert got["values"] == [["fresh", "", False, False, "typed after"]]
    kept = {"action": "/feedback", "fields": {"comment": ["half-typed note"]}}
    got = _js([FEEDBACK], kept, edit=[[0, "comment", "half-typed note, then more"]], discard=True)
    assert got["values"][0][1] == "half-typed note, then more"  # changed since the refill: Discard leaves it


def test_a_draft_of_patient_a_is_not_put_into_the_form_of_patient_b() -> None:
    kept = {"action": "/studies/GZQO/marks", "fields": {"pid": ["pA"], "note": ["check the creatinine"]}}
    other = {"action": "/studies/GZQO/marks", "fields": [["csrf", "hidden", "fresh"], ["pid", "hidden", "pB"],
                                                        ["note", "text", ""]]}  # fmt: skip
    assert _js([other], kept)["values"] == [["fresh", "pB", ""]]  # nothing put in, no note
    ro = {"action": "/feedback", "fields": [["csrf", "hidden", "fresh"], ["patient", "text", "pB", {"readOnly": True}],
                                            ["comment", "textarea", ""]]}  # fmt: skip
    got = _js([ro], {"action": "/feedback", "fields": {"comment": ["note"]}})  # the kept form has no saved patient
    assert got["values"] == [["fresh", "pB", ""]] and got["notes"] == []
    sel = {"action": "/feedback", "fields": [["csrf", "hidden", "fresh"], ["patient", "text", "pB", {"options": ["pA", "pB"]}],
                                            ["comment", "textarea", ""]]}  # fmt: skip
    got = _js([sel], {"action": "/feedback", "fields": {"patient": ["pA"], "comment": ["note"]}})
    assert got["values"][0][2] == "" and got["notes"] == []


def test_a_draft_stays_when_no_form_matched_and_goes_when_one_took_it(tmp_path: Path) -> None:
    clock = Clock()
    app, users, _audit = _app(tmp_path, clock, TB_CONSOLE_WORKSPACE="on")
    c = _signed_in_viewer(app)
    csrf = _csrf(c.get("/help").text)
    clock.tick(minutes=11)
    _send_after_the_end(c, csrf)
    assert _password(c, "viewer", VIEWER_PW).status_code == 303
    for _ in range(3):  # pages rendered, no form took it: still there
        assert _draft(c.get("/help").text) is not None
    for _ in range(3):  # kept awake (idle limit is 10 minutes) until the 15 minutes end: gone, and the row too
        clock.tick(minutes=4)
        assert _draft(c.get("/help").text) is not None
    clock.tick(minutes=4)
    assert _draft(c.get("/help").text) is None
    assert users.db.fetchone("SELECT COUNT(*) FROM session_drafts WHERE page <> ''")[0] == 0  # type: ignore[index]


def test_a_multiple_choice_list_comes_back_whole() -> None:
    form = {"action": "/feedback", "fields": [["csrf", "hidden", "fresh"],
                                              ["tags", "select-multiple", "", {"multiple": True, "options": ["a", "b", "c"]}]]}  # fmt: skip
    got = _js([form], {"action": "/feedback", "fields": {"tags": ["a", "c"]}})
    assert got["values"] == [["fresh", ["a", "c"]]]
