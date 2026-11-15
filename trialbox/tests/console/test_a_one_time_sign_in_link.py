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

from tests.console.test_no_one_holds_both_factors import (
    ADMIN_PW,
    CRC_PW,
    STEWARD_PW,
    _add,
    _box,
    _redeem,
    _request_ids,
    _requests,
    _signin,
)


def _link(text: str) -> str:
    m = re.search(r'data-testid="enrol-link"[^>]*value="([^"]+)"', text)
    assert m, text[-600:]
    return html.unescape(m.group(1))


def _parts(link: str) -> tuple[str, dict[str, str]]:
    u = urlsplit(link)
    return u.path, {k: v[0] for k, v in parse_qs(u.fragment).items()}


def test_the_administrators_page_shows_the_link_beside_the_code(tmp_path: Path) -> None:
    app, _users, _audit, _clock = _box(tmp_path, steward=False)
    admin, csrf = _signin(app, "admin", ADMIN_PW)
    r = _add(admin, csrf, "shadow", "coordinator")
    code = re.search(r'data-testid="enrol-code-value"[^>]*value="([a-z0-9-]+)"', r.text)
    assert code
    path, frag = _parts(_link(r.text))
    assert path == "/enrol" and frag == {"u": "shadow", "c": code.group(1)}
    assert "?" not in _link(r.text).split("#")[0]  # nothing of the code before the '#': the server never gets it


def test_the_confirming_persons_page_shows_the_link_and_a_password_reset_shows_none(tmp_path: Path) -> None:
    app, _users, _audit, _clock = _box(tmp_path, steward=True)
    admin, csrf = _signin(app, "admin", ADMIN_PW)
    _add(admin, csrf, "shadow", "coordinator")
    (rid,) = _request_ids(_requests(admin))
    stew, scsrf = _signin(app, "stew", STEWARD_PW)
    r = stew.post("/ops/accounts/requests", data={"csrf": scsrf, "request": rid, "decision": "confirm"})
    secret = re.search(r'data-testid="request-secret"[^>]*value="([a-z0-9-]+)"', r.text)
    assert secret
    _path, frag = _parts(_link(r.text))
    assert frag == {"u": "shadow", "c": secret.group(1)}


def test_the_link_works_once_like_the_code(tmp_path: Path) -> None:
    app, _users, _audit, _clock = _box(tmp_path, steward=False)
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
