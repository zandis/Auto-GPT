"""SAFE-1 A6: the death check stays fail-closed for the one patient being approached, and the list never depends on
the check of the whole list. When the list's batch check cannot be answered (a large study, a slow lake), the list
still shows, with its warning; an Approach or a contact outcome then asks the death records for that one patient at
the moment of the mark: answered and alive, the mark is kept; answered and dead, it is refused (409); not answered, it
is refused (503). All data is synthetic."""

from __future__ import annotations

from typing import Any

from console.backend import Unavailable

import tests.console.test_console_app as _app
from tests.console.test_role_pages import _csrf, _user

box = _app.box  # the fixture, found by name
_done_screen, _ulid, name_pi = _app._done_screen, _app._ulid, _app.name_pi

A, B = "a" * 32, "b" * 32


def test_a_failed_list_check_does_not_hold_the_patient_being_approached(box: dict[str, Any]) -> None:
    bk = box["backend"]
    _done_screen(bk, _ulid(964))
    pi = _user(box, "drsato", "investigator")
    name_pi(box, "drsato")
    asked: list[list[str]] = []
    dead_one = {A}

    def batch_down(pids: list[str]) -> set[str]:
        asked.append(list(pids))
        if len(pids) > 1:  # the whole list's check is not answered
            raise Unavailable("lake too slow for the whole list")
        return set(pids) & dead_one

    bk.deceased = batch_down
    page = pi.get("/studies/GZQO/week?list=all").text
    assert 'data-testid="dead-unchecked"' in page and 'data-testid="row-bbbbbbbb"' in page  # the list shows, warned
    asked.clear()
    r = pi.post(f"/studies/GZQO/patients/{B}/mark", data={"csrf": _csrf(page), "mark": "approach"})
    assert r.status_code in (200, 303) and asked[-1] == [B]  # one pid, at the moment of the mark
    asked.clear()
    r = pi.post(f"/studies/GZQO/patients/{A}/mark", data={"csrf": _csrf(page), "mark": "approach"})
    assert r.status_code == 409 and asked[-1] == [A]  # the one patient died: refused
    crc = _user(box, "crc1", "coordinator")
    asked.clear()
    r = crc.post(f"/studies/GZQO/patients/{A}/outcome",
                 data={"csrf": _csrf(crc.get("/home").text), "outcome": "reached_booked"})  # fmt: skip
    assert r.status_code == 409 and asked[-1] == [A]  # a contact outcome is checked the same way


def test_the_one_patient_check_not_answered_still_refuses(box: dict[str, Any]) -> None:
    bk = box["backend"]
    _done_screen(bk, _ulid(965))
    pi = _user(box, "drsato", "investigator")
    name_pi(box, "drsato")
    page = pi.get("/studies/GZQO/week?list=all").text

    def down(pids: list[str]) -> set[str]:
        raise Unavailable("lake down")

    bk.deceased = down
    r = pi.post(f"/studies/GZQO/patients/{B}/mark", data={"csrf": _csrf(page), "mark": "approach"})
    assert r.status_code == 503  # never a quiet "nobody died"
    r = pi.post(f"/studies/GZQO/patients/{B}/mark", data={"csrf": _csrf(page), "mark": "need_info"})
    assert r.status_code in (200, 303)  # only contacts wait
    crc = _user(box, "crc1", "coordinator")
    r = crc.post(f"/studies/GZQO/patients/{B}/outcome",
                 data={"csrf": _csrf(crc.get("/home").text), "outcome": "reached_booked"})  # fmt: skip
    assert r.status_code == 503
