"""9g-19 (D-1370, review 02/J-25, A11Y-3, WCAG 2.2.1): a warning one minute before the idle lock, with "Stay signed
in"; what was typed stays on the page.

The server half runs here with the test client: every signed-in page carries the warning (hidden, as an
``alertdialog`` in three languages) and the session's real times; "Stay signed in" opens a page the person may open
anyway with ``keep=1``, which is activity as any page is and is answered with the session's times only (no page,
no notice taken, no page remembered to return to); the check before the lock adds ``auto=1`` and is not activity; the
idle and the absolute limits are the ones the console had (8 hours,
however often the person stays). The browser half (``tests/console/idle_warn.js``) runs the console's own script in
Chromium on pages this console rendered, with the browser's clock moved forward: the warning comes at nine minutes, is
reached and pressed by keyboard, the clock starts again from the press, the lock keeps the typed text and leaves the
page where it is, a session the server already ended shows the lock, a session another tab kept awake does not, and the
absolute end shows no "Stay"."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.console.test_console_app import VIEWER_PW
from tests.console.test_identity import Clock, _app, _password, _signed_in
from tests.console.test_phone_first import _node_playwright

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).with_name("idle_warn.js")
WARN = re.compile(r'<div id="idle-warn"(.*?)>', re.S)


def _attrs(html: str) -> dict[str, str]:
    m = WARN.search(html)
    assert m, "the page carries the idle warning"
    return dict(re.findall(r'([\w-]+)="([^"]*)"', m.group(1)))


def _box(tmp_path: Path, **env: str) -> tuple[Any, Any, Clock, TestClient]:
    clock = Clock()
    app, users, _ = _app(tmp_path, clock, **{"TB_CONSOLE_WORKSPACE": "on", **env})
    c = TestClient(app)
    _password(c, "viewer", VIEWER_PW)
    return app, users, clock, c


def test_every_signed_in_page_carries_the_warning_hidden_with_the_sessions_times(tmp_path: Path) -> None:
    _, _, clock, c = _box(tmp_path)
    html = c.get("/help").text
    a = _attrs(html)
    assert ' hidden data-testid="idle-warn"' in html  # shown only by the script
    assert a["role"] == "alertdialog" and a["aria-labelledby"] == "idle-warn-title"
    assert a["aria-describedby"] == "idle-warn-text"
    assert (a["data-idle"], a["data-idle-left"], a["data-abs-left"]) == ("600", "600", str(8 * 3600))
    assert a["data-lead"] == "60"
    assert a["data-stay-url"] == "/help"
    assert a["data-soon-text"].startswith("Nothing has reached TrialBox from this page for 10 minutes.")
    clock.tick(minutes=3)
    a = _attrs(c.get("/help").text)  # a page is activity: the idle clock starts again, the absolute one does not
    assert (a["data-idle-left"], a["data-abs-left"]) == ("600", str(8 * 3600 - 180))
    assert 'id="idle-warn"' not in TestClient(c.app).get("/login").text  # nobody signed in: nothing to warn of


@pytest.mark.parametrize(
    ("lang", "title", "stay"),
    [("en", "You will be signed out in one minute", "Stay signed in"), ("ja", "1 分後にログアウトされます", "ログインを続ける"),
     ("zh-TW", "一分鐘後將登出", "保持登入")],
)  # fmt: skip
def test_the_warning_speaks_the_page_language(tmp_path: Path, lang: str, title: str, stay: str) -> None:
    _, _, _, c = _box(tmp_path)
    csrf = re.search(r'name="csrf" value="([^"]+)"', c.get("/help").text)
    assert csrf
    c.post("/lang", data={"csrf": csrf.group(1), "lang": lang, "back": "/help"})
    html = c.get("/help").text
    a = _attrs(html)
    assert a["data-soon-title"] == title and f'data-testid="idle-stay">{stay}</button>' in html
    assert all(a[k] for k in ("data-limit-title", "data-limit-text", "data-locked-title", "data-locked-text"))


def test_a_short_idle_limit_warns_half_way_and_says_so(tmp_path: Path) -> None:
    """With a one-minute idle limit the warning comes after 30 seconds, and its title says 30 seconds, not a minute."""
    _, _, _, c = _box(tmp_path, TB_CONSOLE_IDLE_MINUTES="1")
    a = _attrs(c.get("/help").text)
    assert (a["data-idle"], a["data-lead"]) == ("60", "30")
    assert a["data-soon-title"] == "You will be signed out in 30 seconds"
    assert a["data-limit-title"] == "This session ends in 30 seconds"


def test_the_keep_request_is_answered_with_the_times_only(tmp_path: Path) -> None:
    """``keep=1`` on the warning's page: after every check the page makes, the session's times and no page; with
    ``auto=1`` it is not activity. A notice for the account is not taken by it (the next real page shows it), and an
    ended session sends it to the sign-in without remembering it as the page to return to."""
    _, users, clock, c = _box(tmp_path)
    users.add_notice("viewer", "password", "admin")
    clock.tick(minutes=4)
    r = c.get("/help?keep=1&auto=1", follow_redirects=False)
    assert r.status_code == 204 and r.content == b""
    assert (r.headers["x-tb-idle-left"], r.headers["x-tb-abs-left"]) == ("360", str(8 * 3600 - 240))  # not touched
    r = c.get("/help?keep=1", follow_redirects=False)
    assert r.status_code == 204 and r.headers["x-tb-idle-left"] == "600"  # touched: activity
    assert users.has_notices("viewer")  # not taken by the warning's requests
    assert 'data-testid="account-notice"' in c.get("/help").text and not users.has_notices("viewer")
    assert c.get("/studies/GZQO/week?keep=1", follow_redirects=False).status_code == 403  # the page's own checks
    clock.tick(minutes=10, seconds=1)
    r = c.get("/help?keep=1&auto=1", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login?why=idle"
    assert "tb_console_next" not in r.headers.get("set-cookie", "")  # no page to return to
    c2 = TestClient(c.app, cookies={"tb_console": "ended-token"})
    r2 = c2.get("/help", follow_redirects=False)
    assert "tb_console_next" in r2.headers.get("set-cookie", "")  # a real page is still remembered (D-777)


def test_keep_on_a_page_the_role_may_not_open_gets_that_pages_refusal(tmp_path: Path) -> None:
    """``keep=1`` is answered only on the warning's own pages: on a page whose route refuses the role after the
    session check (the users page refuses a viewer in its own body), the refusal answers, not the session's times."""
    _, _, _, c = _box(tmp_path)
    for url in ("/ops/users?keep=1", "/ops/users?keep=1&auto=1"):
        r = c.get(url, follow_redirects=False)
        assert r.status_code == 403 and "x-tb-idle-left" not in r.headers, url


def test_keep_without_a_session_neither_creates_nor_extends_one(tmp_path: Path) -> None:
    """Nobody signed in, or a session already ended: ``keep=1`` goes to the sign-in, and no session is made or kept
    awake by it."""
    _, users, clock, c = _box(tmp_path)

    def count() -> int:
        return int(users.db.fetchone("SELECT COUNT(*) FROM sessions")[0])

    before = count()
    for url in ("/help?keep=1", "/?keep=1", "/ops/users?keep=1", "/help?keep=1&auto=1"):
        r = TestClient(c.app).get(url, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/login"), url
        assert "x-tb-idle-left" not in r.headers and "tb_console=" not in r.headers.get("set-cookie", ""), url
    assert count() == before
    token = c.cookies.get("tb_console")
    clock.tick(minutes=10, seconds=1)
    r = c.get("/help?keep=1", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login?why=idle"
    assert users.session(token) is None and count() == before - 1


def test_without_the_workspace_pages_stay_signed_in_opens_the_overview(tmp_path: Path) -> None:
    """A console with the workspace off (``TB_CONSOLE_WORKSPACE=off``) has no help page; the overview, which every
    signed-in person opens there, is the button's page."""
    _, _, clock, c = _box(tmp_path, TB_CONSOLE_WORKSPACE="off")
    url = _attrs(c.get("/").text)["data-stay-url"]
    assert url == "/"
    clock.tick(minutes=9, seconds=50)
    assert c.get(url + "?keep=1", follow_redirects=False).status_code == 204
    clock.tick(minutes=9, seconds=50)
    assert _signed_in(c)


def test_a_pages_own_refresh_shows_the_time_really_left(tmp_path: Path) -> None:
    """A running job's page reloads itself with auto=1, which is not activity (D-192 H3): its warning counts from the
    last real request, not from the reload."""
    _, _, clock, c = _box(tmp_path)
    c.get("/help")
    clock.tick(minutes=4)
    a = _attrs(c.get("/help?auto=1").text)
    assert a["data-idle-left"] == "360"


def test_stay_signed_in_is_activity_and_never_passes_the_absolute_limit(tmp_path: Path) -> None:
    """The button's request is an ordinary page of the person's (no new route, no new right): it moves the idle clock
    as any page does, and no number of presses keeps a session past its absolute limit."""
    _, users, clock, c = _box(tmp_path)
    url = _attrs(c.get("/help").text)["data-stay-url"]
    for _ in range(8 * 6):  # pressed every 9 minutes 50 seconds for 7 hours 52 minutes
        clock.tick(minutes=9, seconds=50)
        assert c.get(url + "?keep=1", follow_redirects=False).status_code == 204
    a = _attrs(c.get(url).text)
    assert int(a["data-abs-left"]) < 600 and int(a["data-idle-left"]) == 600  # the limit warning comes next
    clock.tick(seconds=int(a["data-abs-left"]) + 1)
    r = c.get(url + "?keep=1", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")  # what the script reads as the lock
    assert not _signed_in(c)
    assert users.idle == timedelta(minutes=10) and users.absolute == timedelta(hours=8)  # the limits as they were


def test_reading_the_times_is_not_activity(tmp_path: Path) -> None:
    _, users, clock, _ = _box(tmp_path)
    user = users.get("viewer")
    token, sess = users.new_session(user)
    clock.tick(minutes=9)
    assert users.session_left(sess.token_sha) == (600, 60, 8 * 3600 - 540)
    clock.tick(minutes=1, seconds=1)
    assert users.session_left(sess.token_sha) == (600, 0, 8 * 3600 - 601)  # never below nought
    assert users.session(token) is None  # reading did not keep it awake
    assert users.session_left(sess.token_sha) is None  # gone


def test_a_directory_sessions_end_is_its_own_shorter_limit(tmp_path: Path) -> None:
    _, users, _, _ = _box(tmp_path)
    _, sess = users.new_session(users.get("viewer"), via="oidc")
    assert users.session_left(sess.token_sha) == (600, 600, 3600)


def test_the_script_reads_and_stores_nothing_typed() -> None:
    """Section 7 of the console's script touches no field and no browser store: what was typed is kept only by staying
    on the page (and by D-1222's and D-777's tab storage, unchanged)."""
    js = (ROOT / "services" / "console" / "static" / "console.js").read_text(encoding="utf-8")
    part = js.split("// 7. D-1370")[1]
    for word in ("sessionStorage", "localStorage", "indexedDB", ".value", "location.assign", "location.replace",
                 "location.href =", "reload(", "submit", "history."):  # fmt: skip
        assert word not in part, word


def _rendered(tmp_path: Path) -> dict[str, Any]:
    """Pages this console rendered for the browser half: en and ja, and one whose session ends in 5 minutes."""
    app, users, _, c = _box(tmp_path)
    out: dict[str, Any] = {"en": c.get("/help").text}
    csrf = re.search(r'name="csrf" value="([^"]+)"', out["en"])
    assert csrf
    c.post("/lang", data={"csrf": csrf.group(1), "lang": "ja", "back": "/help"})
    out["ja"] = c.get("/help").text
    c.post("/lang", data={"csrf": csrf.group(1), "lang": "en", "back": "/help"})
    c2 = TestClient(app)
    _password(c2, "viewer", VIEWER_PW)
    users.absolute = timedelta(minutes=5)  # a new sign-in near a short limit: the absolute end comes first
    out["limit"] = c2.get("/help").text
    out["csp"] = c2.get("/help").headers["content-security-policy"]
    return out


@pytest.mark.skipif(not _node_playwright(), reason="Node Playwright is not installed")
def test_in_a_browser_the_warning_comes_a_minute_before_and_the_typed_text_stays(tmp_path: Path) -> None:
    pages = tmp_path / "pages.json"
    pages.write_text(json.dumps(_rendered(tmp_path)), encoding="utf-8")
    out = subprocess.run([shutil.which("node") or "node", str(SCRIPT), str(pages)], cwd=ROOT, capture_output=True,
                         text=True, timeout=300, check=False)  # fmt: skip
    assert out.returncode == 0, out.stdout + out.stderr
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert not [k for k, v in got.items() if isinstance(v, dict) and "error" in v], got
    w = got["warned_then_stayed"]
    assert w["at_8m58"] is True and w["at_9m01"]["hidden"] is False  # not before, then one minute before
    assert w["at_9m01"]["state"] == "soon" and w["at_9m01"]["role"] == "alertdialog"
    assert w["at_9m01"]["title"] == "You will be signed out in one minute" and w["at_9m01"]["focus"] == "idle-stay"
    assert w["at_9m01"]["seen"] == ["stay"]  # on the screen: the one button, not Close
    assert w["after_enter"] == {"hidden": True, "stay_requests": 1, "focus": "cmd-q", "typed": "half-typed note"}
    assert w["escape"] == {"hidden": True, "stay_requests": 2}  # Escape on the warning is "Stay signed in"
    assert w["again_9m01_after_the_press"] == {"hidden": False, "state": "soon"}  # counted from the press
    locked = got["locked_keeps_the_text"]
    assert locked["state"] == "locked" and locked["title"] == "You have been signed out" and locked["stay_hidden"]
    assert locked["typed"] == "half-typed note" and locked["url_same"] and locked["stay_requests"] == 1
    assert locked["checks"] == 1  # it asked (auto=1, not activity) before saying so
    assert locked["focus"] == "idle-close" and locked["closed_stays_closed"] and locked["seen"] == ["close"]
    assert got["server_already_ended"] == {"state": "locked", "title": "You have been signed out"}
    awake = got["another_tab_kept_it_awake"]  # the second tab is idle, the session is alive: no false lock
    assert awake["at_lock"] == {"hidden": True, "state": "", "checks": 1}
    assert awake["warned_again"] == {"hidden": False, "state": "soon"}  # re-armed from the answer's times
    assert awake["before_that"] is True
    assert got["sent_to_the_password_page"] == {"hidden": True, "state": "", "checks": 1}  # never a false lock
    assert got["woke_up"] == {"checks": 1, "state": "soon"}  # asked on waking, warned from the answer's 30 s
    assert got["late_page"] == {"warned_within_3s_early": True}  # from the navigation's start: early, never late
    lim = got["absolute_limit"]
    assert lim["at_4m01"] == {"hidden": False, "state": "limit", "stay_hidden": True, "seen": ["close"],
                              "title": "This session ends in one minute"}  # fmt: skip
    assert got["japanese"]["title"] == "1 分後にログアウトされます" and got["japanese"]["stay"] == "ログインを続ける"
