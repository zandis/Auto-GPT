"""The nightly phone walk (H-21, D-1138; tests/e2e/test_life_cycle_walk_390.py, steps 15 to 17) found the participant
page (/studies/{rs}/subjects/{record}, and the page a step answers with) holding tables wider than a 390 px phone:
the visit schedule and the trail, 405 to 413 px with the phone-first layout off (its default). Both tables now carry
the console's ``stack`` class (one card per row at 640 px and below, D-104), whatever the layout flag; with the flag
on they keep its labelled cards. Measured at 390 px in Chromium on this page: 332 px. Synthetic data only."""

from __future__ import annotations

import re
from typing import Any

from tests.console.test_console_app import box, login  # noqa: F401 - the fixture is used by name
from tests.console.test_lifecycle_pages import PW, lb  # noqa: F401 - the fixture is used by name


def _tables(page: str) -> list[str]:
    return re.findall(r'<table class="([^"]*)"', page)


def test_the_participant_pages_tables_are_cards_on_a_phone(lb: dict[str, Any]) -> None:  # noqa: F811
    no, other = lb["nos"]
    c, csrf = login(lb["app"], "crc", PW)
    c.post("/studies/GZQO/forms/builtin", data={"csrf": csrf})
    c.get("/studies/GZQO/subjects")
    c.post("/studies/GZQO/schedule", data={"csrf": csrf, "action": "save", "visit": ["v1", "", ""],
                                           "label": ["Week 1", "", ""], "day": ["7", "", ""], "before": ["2", "", ""],
                                           "after": ["2", "", ""], "anchor": ["enrolment"] * 3})  # fmt: skip
    for to in ("approached", "consented", "enrolled"):
        c.post(f"/studies/GZQO/subjects/{no}/step", data={"csrf": csrf, "to": to, "on_day": "2026-11-05"})
    page = c.get(f"/studies/GZQO/subjects/{no}").text
    assert 'data-testid="life-visits"' in page and 'data-testid="life-trail"' in page
    tables = _tables(page)
    assert len(tables) >= 2 and all("stack" in t.split() for t in tables), tables
    refused = c.post(f"/studies/GZQO/subjects/{other}/step", data={"csrf": csrf, "to": "screen_fail"}).text
    assert all("stack" in t.split() for t in _tables(refused)), _tables(refused)  # the page a step answers with
