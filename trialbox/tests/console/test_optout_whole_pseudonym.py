"""NEW-JRN-2 (JRN-002, D-542): the opt-out register takes a chart number or the whole pseudonym, never a prefix,
and says when nobody matched.

Every screen shows a patient by the first eight characters of the pseudonym. Typed that way, the register stored
an opt-out for the eight characters and answered "Recorded: the patient opted out", while the patient stayed on
the PI's list. A mistyped pseudonym was confirmed the same way.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from tb_common.optout import OptOutRegister

from tests.console.test_console_app import _done_screen, _ulid, box, name_pi  # noqa: F401 - fixture by name
from tests.console.test_role_pages import PW, _csrf, _user
from tests.console.test_team_pages import B, _events


def _post(c: TestClient, **data: str) -> Any:
    return c.post("/site/opt-outs", data={"csrf": _csrf(c.get("/site/opt-outs").text), **data},
                  follow_redirects=False)  # fmt: skip


def test_a_prefix_or_a_mistyped_pseudonym_is_refused_and_the_patient_stays_listed(box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(981))
    pi = _user(box, "drsato", "investigator")
    name_pi(box, "drsato")
    stw = _user(box, "stw", "steward")
    for typed in (B[:8], "deadbeef", B[:31], B + "0", "g" * 32):
        r = _post(stw, pid=typed, source="paper")
        assert r.status_code == 400, (typed, r.status_code)
        assert "whole pseudonym" in r.text and "chart number" in r.text
    assert _events(box, "console.opt_out") == [] and OptOutRegister().current() == []
    assert 'data-testid="row-bbbbbbbb"' in pi.get("/studies/GZQO/week?list=all").text  # still on the list
    api = TestClient(box["app"])
    tok = api.post("/api/v1/session", json={"username": "stw", "password": PW}).json()["token"]
    r = api.post("/api/v1/site/opt-outs", json={"pid": B[:8]}, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 400 and OptOutRegister().current() == []


def test_the_whole_pseudonym_is_recorded_and_the_page_says_what_matched(box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(982))
    pi = _user(box, "drsato", "investigator")
    name_pi(box, "drsato")
    stw = _user(box, "stw", "steward")
    r = _post(stw, pid=f"  {B.upper()} ", source="paper")  # as copied: spaces and capitals
    assert r.status_code == 303 and "done=added" in r.headers["location"]
    page = stw.get(r.headers["location"]).text
    assert 'data-testid="optout-matched"' in page and 'data-testid="optout-nomatch"' not in page
    assert "GZQO" not in r.headers["location"] and B not in r.headers["location"]  # one yes or no, no study, no id
    shown = _events(box, "console.opt_out")[-1]["detail"]
    assert shown["match_shown"] == "yes"  # on the record: the keeper was told this pseudonym is listed
    assert [e.pid for e in OptOutRegister().current()] == [B]
    assert 'data-testid="row-bbbbbbbb"' not in pi.get("/studies/GZQO/week?list=all").text
    # a whole pseudonym nobody on this box has: recorded (a patient may opt out before any list names them), and
    # the page says that nobody matched instead of "the patient is removed"
    nobody = "d" * 32
    r = _post(stw, pid=nobody, source="paper")
    assert r.status_code == 303
    page = stw.get(r.headers["location"]).text
    assert 'data-testid="optout-nomatch"' in page and 'data-testid="optout-matched"' not in page
    assert _events(box, "console.opt_out")[-1]["detail"]["match_shown"] == "no"
    # the note is yes or no: text typed into the address is not shown
    assert "<b>" not in stw.get("/site/opt-outs?done=added&on=%3Cb%3Ex").text
    assert 'data-testid="optout-matched"' not in stw.get("/site/opt-outs?done=added&on=GZQO").text
    api = TestClient(box["app"])
    tok = api.post("/api/v1/session", json={"username": "stw", "password": PW}).json()["token"]
    hdr = {"Authorization": f"Bearer {tok}"}
    r = api.post("/api/v1/site/opt-outs", json={"pid": "e" * 32}, headers=hdr)
    assert r.status_code == 200 and r.json() == {"opted_out": True, "changed": True, "matched": False}
    again = api.post("/api/v1/site/opt-outs", json={"pid": "e" * 32}, headers=hdr)
    assert again.json() == {"opted_out": True, "changed": False}  # review L2: unchanged says nothing about a match
    assert "pid" not in r.text  # D-273 (PV-6): still no pseudonym back


def test_an_entry_made_before_this_rule_can_still_be_lifted(box: dict[str, Any]) -> None:  # noqa: F811
    """Old data: a register row for eight characters, stored before this card. It names nobody; the keeper of the
    register must be able to take it back from the page (the lift form posts the entry's own text)."""
    OptOutRegister().add("e7543f47", "paper", "", "stw", "2026-11-01T09:00:00+08:00")
    stw = _user(box, "stw", "steward")
    assert 'data-testid="optout-e7543f47"' in stw.get("/site/opt-outs").text
    r = _post(stw, pid="e7543f47", lift="1", note="entered as shown on screen: it named no patient")
    assert r.status_code == 303 and "done=lifted" in r.headers["location"]
    assert OptOutRegister().current() == []
    r = _post(stw, pid="e7543f48", lift="1", note="another short text that is on no register row")
    assert r.status_code == 400


# ------------------------------------------------------------------------------ the adversarial review's findings
def test_review_a_chart_number_gets_the_plain_answer_and_a_pseudonym_is_not_a_chart_number(
    box: dict[str, Any],  # noqa: F811
) -> None:
    """Review H1: every opt-out by chart number showed "no patient with this pseudonym is on a list", also for a
    patient who had just left a list. A chart number gets the plain "Recorded" and no note. Review M3: a whole
    pseudonym typed into the chart-number field was hashed again and recorded for nobody."""
    _done_screen(box["backend"], _ulid(984))  # B is on the GZQO list

    def study_api(method: str, path: str, body: dict[str, Any] | None = None, **_: Any) -> Any:
        assert path == "/setup/pseudonym", path  # the box turns the chart number into B's pseudonym
        return {"pid": B, "known": True}  # NEW-DIN-3 (D-544): and says B is a patient of this box

    box["backend"].study_api = study_api
    stw = _user(box, "stw", "steward")
    r = _post(stw, chart_no="SYN-0001", source="paper")
    assert r.status_code == 303 and r.headers["location"] == "/site/opt-outs?done=added"
    page = stw.get(r.headers["location"]).text
    assert 'data-testid="optout-done"' in page and 'data-testid="optout-nomatch"' not in page
    assert "match_shown" not in _events(box, "console.opt_out")[-1]["detail"]
    before = len(OptOutRegister().current())
    r = _post(stw, chart_no=B, source="paper")
    assert r.status_code == 400 and "pseudonym" in r.text and len(OptOutRegister().current()) == before


def test_review_no_note_when_a_list_could_not_be_read_or_the_cap_is_used_up(box: dict[str, Any]) -> None:  # noqa: F811
    """Review M1: with a registry that could not be read the page said "nobody matched" for a listed patient.
    Review M2: the note is a lookup ("is this pseudonym on a list"); it is counted per person and hour like the
    chart-number lookup, and past the cap the opt-out is still taken, without a note."""
    _done_screen(box["backend"], _ulid(983))
    stw = _user(box, "stw", "steward")

    def broken(_rs: str) -> Any:
        raise RuntimeError("the registry cannot be read")

    real = box["backend"].registry_rows
    box["backend"].registry_rows = broken
    r = _post(stw, pid=B, source="paper")
    assert r.status_code == 303 and r.headers["location"] == "/site/opt-outs?done=added"  # recorded, no note
    assert [e.pid for e in OptOutRegister().current()] == [B]
    box["backend"].registry_rows = real
    limit = box["app"].state.helpers.pid_match_per_hour
    notes = []
    for i in range(limit + 2):
        r = _post(stw, pid=f"{i:032x}", source="paper")
        assert r.status_code == 303  # the register always takes the opt-out
        notes.append("on=" in r.headers["location"])
    assert notes[: limit - 1] == [True] * (limit - 1) and notes[-1] is False


def test_review_an_old_row_in_capitals_can_be_lifted(box: dict[str, Any]) -> None:  # noqa: F811
    """Review L1: the text was lowered before the register was asked for the row."""
    OptOutRegister().add("ABCDEF0123456789ABCDEF0123456789", "paper", "", "stw", "2026-11-01T09:00:00+08:00")
    stw = _user(box, "stw", "steward")
    r = _post(stw, pid="ABCDEF0123456789ABCDEF0123456789", lift="1", note="an old row, typed in capitals")
    assert r.status_code == 303 and "done=lifted" in r.headers["location"] and OptOutRegister().current() == []
