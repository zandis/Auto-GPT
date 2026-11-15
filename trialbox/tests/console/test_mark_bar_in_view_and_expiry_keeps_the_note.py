"""NEW-UX-1 and NEW-UX-6 (D-777; the deep review's UX-001 and UX-007).

UX-001: on the desktop week list the three main mark buttons sat under all criteria, about 2,000 px down; only the
phone sheet kept the bar in view. Now the panel's mark bar sticks to the bottom of the screen on the desktop too.

UX-007: an expired session sent the person to the sign-in page with no reason, lost the typed note, and landed them on
the week list. Now:

* a request whose session has ended goes to ``/login?why=idle``, which says why (the idle limit in minutes);
* the page they were on (a GET's own address, a POST's same-origin Referer) is kept in a short cookie and, after
  sign-in (with or without the authenticator step), is where they land; only a same-origin path is kept;
* a mark's note is kept in the browser's session storage while it is typed, restored on that patient's page after
  sign-in, and dropped once the mark is saved (the console's own script, run here in Node).

Synthetic data only."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.console.test_console_app import ADMIN_PW, box, login, login_totp  # noqa: F401 - the fixture is used by name

ROOT = Path(__file__).resolve().parents[2]
NEXT = "tb_console_next"


def _kept(c: TestClient) -> str:
    from urllib.parse import unquote

    return unquote((c.cookies.get(NEXT) or "").strip('"'))


def _expired(app: Any) -> TestClient:
    """A browser whose session cookie names no live session (idle limit passed, or ended)."""
    c = TestClient(app)
    c.cookies.set("tb_console", "a-session-that-has-ended")
    return c


# ---------------------------------------------------------------------------------------------- UX-001
def test_the_desktop_week_panel_keeps_the_mark_bar_in_view() -> None:
    css = (ROOT / "services" / "console" / "static" / "console.css").read_text(encoding="utf-8")
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)

    def top_level(pattern: str) -> bool:
        """A rule matching ``pattern`` outside any media query (the desktop's own rules)."""
        return any(css[: m.start()].count("{") == css[: m.start()].count("}") for m in re.finditer(pattern, css))

    assert top_level(r"\.chartp \.markbar\s*\{[^}]*position:\s*sticky[^}]*bottom:\s*0"), "not sticky on the desktop"
    assert not top_level(r"\.chartp\s*\{[^}]*overflow:\s*hidden")  # a hidden overflow would stop the sticky bar


# ---------------------------------------------------------------------------------------------- UX-007
def test_an_ended_session_says_why_and_keeps_the_page(box: dict[str, Any]) -> None:  # noqa: F811
    c = _expired(box["app"])
    r = c.get("/studies/GZQO/week?list=all", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login?why=idle"
    assert _kept(c) == "/studies/GZQO/week?list=all"
    page = c.get("/login?why=idle").text
    assert 'data-testid="login-idle"' in page and "10" in page.split('data-testid="login-idle"')[1][:300]


def test_a_post_after_the_session_ended_keeps_the_page_it_came_from(box: dict[str, Any]) -> None:  # noqa: F811
    c = _expired(box["app"])
    r = c.post("/studies/GZQO/patients/" + "a" * 32 + "/mark", data={"csrf": "x", "mark": "need_info", "note": "n"},
               headers={"referer": "http://testserver/studies/GZQO/patients/" + "a" * 32}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303 and r.headers["location"] == "/login?why=idle"
    assert _kept(c) == "/studies/GZQO/patients/" + "a" * 32


@pytest.mark.parametrize("bad", ["http://evil.example/x", "//evil.example/x", "/login", "/logout", "/api/v1/me"])
def test_only_a_same_origin_page_is_kept(box: dict[str, Any], bad: str) -> None:  # noqa: F811
    c = _expired(box["app"])
    c.post("/studies/GZQO/patients/" + "a" * 32 + "/mark", data={"csrf": "x"},
           headers={"referer": bad if bad.startswith("http") else "http://testserver" + bad}, follow_redirects=False)  # fmt: skip
    assert not _kept(c), bad


def test_after_sign_in_the_person_lands_where_they_were(box: dict[str, Any]) -> None:  # noqa: F811
    c = _expired(box["app"])
    c.get("/reports?x=1", follow_redirects=False)
    token = re.search(r'name="login_csrf" value="([^"]+)"', c.get("/login?why=idle").text)
    assert token
    r = c.post("/login", data={"username": "admin", "password": ADMIN_PW, "login_csrf": token.group(1)},
               follow_redirects=False)  # fmt: skip
    assert r.status_code == 303 and r.headers["location"] == "/reports?x=1"
    assert not _kept(c)  # used once


def test_a_first_visit_has_no_idle_message(box: dict[str, Any]) -> None:  # noqa: F811
    c = TestClient(box["app"])
    r = c.get("/reports", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_the_mark_note_is_marked_for_keeping_and_a_saved_mark_for_dropping() -> None:
    tpl = (ROOT / "services" / "console" / "templates" / "_mark.html").read_text(encoding="utf-8")
    assert 'data-keep-note="{{ pid }}"' in tpl and 'data-mark-saved="{{ pid }}"' in tpl


RUN_JS = """
const [src, page, saved, typed] = process.argv.slice(1);
const store = {};
global.sessionStorage = {getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); },
  removeItem: (k) => { delete store[k]; }, get length() { return Object.keys(store).length; },
  key: (i) => Object.keys(store)[i]};
if (page) Object.assign(store, JSON.parse(page));
const listeners = [];
const note = {value: typed, getAttribute: (a) => (a === "data-keep-note" ? "p1" : null),
  addEventListener: (ev, fn) => listeners.push(fn)};
global.navigator = {};
global.window = {location: {hash: "", pathname: "/x", search: ""}, history: {length: 1}, addEventListener: () => {}};
global.document = {getElementById: () => null, querySelector: () => null,
  querySelectorAll: (q) => (q === "input[data-keep-note]" ? [note] :
    q === "[data-mark-saved]" ? (saved === "1" ? [{getAttribute: () => "p1"}] : []) : [])};
eval(src);
if (typed === "typing") { note.value = "typed later"; listeners.forEach((f) => f()); }
console.log(JSON.stringify({value: note.value, store}));
"""


def _run(store: dict[str, str], saved: bool, typed: str = "") -> dict[str, Any]:
    from console.app import CONSOLE_JS

    node = shutil.which("node")
    assert node, "node runs the console's script in the tests"
    out = subprocess.run([node, "-e", RUN_JS, CONSOLE_JS, json.dumps(store), "1" if saved else "0", typed],
                         capture_output=True, text=True, timeout=30, check=True)  # fmt: skip
    got: dict[str, Any] = json.loads(out.stdout.strip().splitlines()[-1])
    return got


def test_the_script_keeps_restores_and_drops_the_note() -> None:
    assert _run({}, saved=False, typed="typing")["store"] == {"tb-note:p1": "typed later"}  # kept while typed
    got = _run({"tb-note:p1": "check the creatinine"}, saved=False)
    assert got["value"] == "check the creatinine"  # restored after sign-in, on that patient's page
    got = _run({"tb-note:p1": "check the creatinine"}, saved=True)
    assert got["value"] == "" and got["store"] == {}  # the mark was saved: dropped, not restored
    assert _run({"tb-note:p1": "old"}, saved=False, typed="new")["value"] == "new"  # never over a typed note
