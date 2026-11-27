# ruff: noqa: F811 - the fixtures are imported from other test modules and taken by name
"""E2E P-35: an investigator on no study's delegation log was sent at sign-in (``/home`` → ``/week``) straight to
``/studies/GOUT-301/week``, which then refused them (403). ``/week`` now picks among the studies whose week page
admits the account, as the home page's own week link does; the study's PI is still sent straight to its week."""

from __future__ import annotations

from typing import Any

from tests.console.test_console_app import box, login, name_pi  # noqa: F401
from tests.console.test_lifecycle_pages import PW, lb  # noqa: F401
from tests.console.test_rc1_guard import _job


def test_an_investigator_on_no_log_lands_on_a_page_that_opens(lb: dict[str, Any]) -> None:
    _job(lb["backend"], 1, "SCREEN", ())  # the study has a screening list: /week used to go straight to its week
    name_pi(lb, "pi")
    lb["users"].create("other", "investigator", PW, "other@hospa.test")  # on no study's log
    c, _ = login(lb["app"], "other", PW)
    first = c.get("/home")  # followed to the end, as the browser does after sign-in
    assert first.status_code == 200, (first.url, first.status_code)
    assert "/studies/GZQO/week" not in str(first.url)
    pi, _ = login(lb["app"], "pi", PW)
    r = pi.get("/week", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/studies/GZQO/week"  # its PI: straight there, as before
