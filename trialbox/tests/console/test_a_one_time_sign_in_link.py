"""D-776 (the owner's ruling D-509 of 2026-11-15): a person sets their own password from a one-time link.

D-719's first sign-in already holds every rule of D-509: the holder chooses the password (``/enrol``), the enrolment
code works once, an unused one expires, wrong attempts are slowed and lock the account. What was missing is the
link: the holder typed the user name and the code. Now:

* where a new account's code is shown once (the administrator's page; the confirming person's page), the link is shown
  beside it: ``<box>/enrol#u=<name>&c=<code>``;
* ``/enrol`` fills the two fields from the part after ``#`` (the console's script) and removes it from the address
  bar. A browser never sends that part to the server: the code is in no request line, log or Referer;
* the link is the code: it works once and then is refused like the code (the rules of D-719 hold unchanged);
* a reset password is not a link (it is typed at the sign-in page, as before).

Synthetic data only."""

from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from tests.console.test_console_app import ADMIN_PW
from tests.console.test_no_one_holds_both_factors import (
    CRC_PW,
    STEWARD_PW,
    _add,
    _box,
    _redeem,
    _request_ids,
    _requests,
    _signin,
)

PUBLIC = "https://trialbox.site-a.test"


def _link(text: str) -> str:
    m = re.search(r'data-testid="enrol-link"[^>]*value="([^"]+)"', text)
    assert m, text[-600:]
    return html.unescape(m.group(1))


def _parts(link: str) -> tuple[str, dict[str, str]]:
    u = urlsplit(link)
    return u.path, {k: v[0] for k, v in parse_qs(u.fragment).items()}


@pytest.mark.usefixtures("held_dir")
def test_the_administrators_page_shows_the_link_beside_the_code(tmp_path: Path) -> None:
    app, _users, _audit, _clock = _box(tmp_path, steward=False, TB_CONSOLE_PUBLIC_URL=PUBLIC)
    admin, csrf = _signin(app, "admin", ADMIN_PW)
    r = admin.post("/ops/users", data={"csrf": csrf, "action": "add", "username": "shadow", "role": "coordinator",
                                       "affiliation": "hospital", "studies": ""},
                   headers={"host": "evil.example:8443"}, follow_redirects=True)  # a forged Host  # fmt: skip
    code = re.search(r'data-testid="enrol-code-value"[^>]*value="([a-z0-9-]+)"', r.text)
    assert code
    path, frag = _parts(_link(r.text))
    assert path == "/enrol" and frag == {"u": "shadow", "c": code.group(1)}
    assert _link(r.text).startswith(PUBLIC + "/enrol#") and "evil.example" not in r.text  # the box's address only
    assert "?" not in _link(r.text).split("#")[0]  # nothing of the code before the '#': the server never gets it


@pytest.mark.usefixtures("held_dir")
def test_the_confirming_persons_page_shows_the_link(tmp_path: Path) -> None:
    app, _users, _audit, _clock = _box(tmp_path, steward=True, TB_CONSOLE_PUBLIC_URL=PUBLIC)
    admin, csrf = _signin(app, "admin", ADMIN_PW)
    _add(admin, csrf, "shadow", "coordinator")
    (rid,) = _request_ids(_requests(admin))
    stew, scsrf = _signin(app, "stew", STEWARD_PW)
    r = stew.post("/ops/accounts/requests", data={"csrf": scsrf, "request": rid, "decision": "confirm"})
    secret = re.search(r'data-testid="request-secret"[^>]*value="([a-z0-9-]+)"', r.text)
    assert secret
    _path, frag = _parts(_link(r.text))
    assert frag == {"u": "shadow", "c": secret.group(1)}


@pytest.mark.usefixtures("held_dir")
def test_the_link_works_once_like_the_code(tmp_path: Path) -> None:
    app, _users, _audit, _clock = _box(tmp_path, steward=False, TB_CONSOLE_PUBLIC_URL=PUBLIC)
    admin, csrf = _signin(app, "admin", ADMIN_PW)
    _path, frag = _parts(_link(_add(admin, csrf, "shadow", "coordinator").text))
    r = _redeem(app, frag["u"], frag["c"], CRC_PW)  # what the filled form posts
    assert r.status_code == 303
    again = _redeem(app, frag["u"], frag["c"], CRC_PW + "x")
    assert again.status_code == 401 and 'data-testid="enrol-code-used"' in again.text


def test_the_first_sign_in_page_takes_the_link(tmp_path: Path) -> None:
    """The page carries the form the script fills, and the script reads the part after '#' and then removes it."""
    from console.app import CONSOLE_JS

    app, _users, _audit, _clock = _box(tmp_path, steward=False)
    from fastapi.testclient import TestClient

    page = TestClient(app, base_url="https://testserver").get("/enrol").text
    assert "data-enrol-link" in page and 'id="username"' in page and 'id="enrol_code"' in page
    assert "data-enrol-link" in CONSOLE_JS and "location.hash" in CONSOLE_JS and "replaceState" in CONSOLE_JS


@pytest.mark.usefixtures("held_dir")
def test_a_password_reset_is_never_a_link(tmp_path: Path) -> None:
    """A reset password is typed at the sign-in page, never given as a link."""
    app, users, _audit, _clock = _box(tmp_path, steward=True, TB_CONSOLE_PUBLIC_URL=PUBLIC)
    admin, csrf = _signin(app, "admin", ADMIN_PW)
    users.create("crc9", "coordinator", CRC_PW, "crc9@hospa.test")
    r = admin.post("/ops/users", data={"csrf": csrf, "action": "reset", "username": "crc9", "confirm": "yes"})
    assert r.status_code == 200 and 'data-testid="account-requested"' in r.text
    (rid,) = _request_ids(_requests(admin))
    stew, scsrf = _signin(app, "stew", STEWARD_PW)
    page = stew.post("/ops/accounts/requests", data={"csrf": scsrf, "request": rid, "decision": "confirm"}).text
    assert 'data-testid="request-secret"' in page and 'data-testid="enrol-link"' not in page


@pytest.mark.usefixtures("held_dir")
def test_without_the_boxs_public_address_no_link_is_made(tmp_path: Path) -> None:
    """A link to the request's own Host could point anywhere (a tunnel, a forged header): no address, no link."""
    app, _users, _audit, _clock = _box(tmp_path, steward=False)
    admin, csrf = _signin(app, "admin", ADMIN_PW)
    r = _add(admin, csrf, "shadow", "coordinator")
    assert 'data-testid="enrol-link"' not in r.text and 'data-testid="enrol-link-none"' in r.text


RUN_JS = """
const [src, hash, path, hasForm, preset] = process.argv.slice(1);
const fields = {username: {value: preset}, enrol_code: {value: ""}};
const form = {querySelector: (q) => fields[q.slice(1)]};
let replaced = null;
global.navigator = {};
global.window = {location: {hash, pathname: path, search: ""}, history: {length: 1,
  replaceState: (_s, _t, url) => { replaced = url; }}, addEventListener: () => {}};
global.document = {querySelectorAll: () => [], getElementById: () => null,
  querySelector: (q) => (q === "form[data-enrol-link]" && hasForm === "1" ? form : null)};
eval(src);
console.log(JSON.stringify({u: fields.username.value, c: fields.enrol_code.value, replaced}));
"""


def _run_console_js(hash_: str, path: str, form: bool, preset: str = "") -> dict[str, object]:
    import json
    import shutil
    import subprocess

    from console.app import CONSOLE_JS

    node = shutil.which("node")
    assert node, "node runs the console's script in the tests (as tests/testbench does)"
    out = subprocess.run([node, "-e", RUN_JS, CONSOLE_JS, hash_, path, "1" if form else "0", preset],
                         capture_output=True, text=True, timeout=30, check=True)  # fmt: skip
    got: dict[str, object] = json.loads(out.stdout.strip().splitlines()[-1])
    return got


def test_the_script_fills_the_form_and_clears_the_code_on_every_page() -> None:
    """The console's own script, run: on the first sign-in it fills the two fields and clears the part after '#'; on
    any other page (a signed-in person is sent on to the home page with it) it clears it too."""
    got = _run_console_js("#u=shadow&c=abcd-1234", "/enrol", form=True)
    assert got == {"u": "shadow", "c": "abcd-1234", "replaced": "/enrol"}
    got = _run_console_js("#u=shadow&c=abcd-1234", "/", form=False)
    assert got["replaced"] == "/"  # the code leaves the address bar even where there is no form
    got = _run_console_js("#u=other&c=abcd-1234", "/enrol", form=True, preset="typed")
    assert got["u"] == "typed"  # a typed user name is never overwritten
    assert _run_console_js("#made", "/ops/users", form=False)["replaced"] is None  # an ordinary anchor stays
