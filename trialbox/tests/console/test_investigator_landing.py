# ruff: noqa: F811 - the fixtures are imported from other test modules and taken by name
"""E2E P-35: an investigator on no study's delegation log reaches ``/studies/<id>/week`` at sign-in (``/home`` →
``/week``) and was refused with the bare "your role cannot open this page" (403). The home and the menus keep their
ruled shape; the refusal stays a 403 but is a page that names why (no study log is assigned to the account) and the
next step (who assigns one, the request page). The study's PI is still sent straight to its week."""

from __future__ import annotations

import html
import re
from typing import Any

import pytest
from console.i18n import CATALOGUES

from tests.console.test_console_app import box, login, name_pi  # noqa: F401
from tests.console.test_lifecycle_pages import PW, lb  # noqa: F401
from tests.console.test_rc1_guard import _job

LANGS = ("en", "ja", "zh-TW")


def _no_log_investigator(lb: dict[str, Any]) -> tuple[Any, str]:
    _job(lb["backend"], 1, "SCREEN", ())  # the study has a screening list: /week goes straight to its week
    name_pi(lb, "pi")
    lb["users"].create("other", "investigator", PW, "other@hospa.test")  # on no study's log
    return login(lb["app"], "other", PW)


def test_the_pi_is_still_sent_straight_to_its_week(lb: dict[str, Any]) -> None:
    _job(lb["backend"], 1, "SCREEN", ())
    name_pi(lb, "pi")
    pi, _ = login(lb["app"], "pi", PW)
    r = pi.get("/week", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/studies/GZQO/week"


@pytest.mark.parametrize("lang", LANGS)
def test_an_investigator_on_no_log_gets_a_403_page_that_says_why_and_what_next(lb: dict[str, Any], lang: str) -> None:
    c, csrf = _no_log_investigator(lb)
    c.post("/lang", data={"csrf": csrf, "lang": lang, "back": "/"})
    r = c.get("/home")  # followed to the end, as the browser does after sign-in
    assert r.status_code == 403, (r.url, r.status_code)
    assert str(r.url).endswith("/studies/GZQO/week")  # the same dead end as before, now with words
    cat = CATALOGUES[lang]
    text = html.unescape(r.text)
    assert cat["problem.h.week.no_log"] in text
    assert cat["week.no_log"].format(rs="GZQO") in text
    assert cat["problem.why.week.no_log"] in text  # who assigns one: the PI, or the administrator
    assert 'href="/pilot/request?ruleset=GZQO"' in text and cat["week.no_log.request"] in text
    link = re.search(r'href="(/pilot/request\?ruleset=GZQO)"', text)
    assert link  # the rendered link leads somewhere that opens: not a second 403/404
    page = c.get(link.group(1))
    assert page.status_code == 200, (page.status_code, page.url)
    assert cat["request.title"] in html.unescape(page.text)  # the request page itself ...
    assert data-testid=problem-home not in page.text  # ... and not another refusal page
    assert 'data-testid="problem-home"' in text  # the way out of it is still there
    assert cat["forbidden"] not in text  # no longer the bare role refusal
