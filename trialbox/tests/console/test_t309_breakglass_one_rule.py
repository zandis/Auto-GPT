"""T-309 (D-430): break-glass to owner decision OD-5, one rule for the administrator and a non-admin reader.

A grant has a reason, covers one patient or one job, ends by itself at 60 minutes and is reviewed by the steward
afterwards; no second person. The same rule holds for the administrator and for an investigator outside its own
rights (one the study's delegation log does not reach). Every use is one line on the steward's review list.
Synthetic pseudonyms and chart numbers only."""

from __future__ import annotations

import re
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tb_common import authz
from tb_common.authz import permit

from tests.console.test_console_app import _done_screen, _ulid, box, login, name_pi  # noqa: F401 - the fixture by name
from tests.console.test_d280_breakglass import A, B, _events, _open, _shift
from tests.console.test_role_pages import PW, _csrf, _user


def _reader(b: dict[str, Any], who: str) -> TestClient:
    """The administrator, or an investigator the GZQO log does not name (the log names drsato as PI)."""
    _user(b, "drsato", "investigator")
    name_pi(b, "drsato")
    if who == "admin":
        return login(b["app"])[0]
    return _user(b, "drlee", "investigator")


def _uses_on_review_list(stw: TestClient, gid: int) -> list[str]:
    page = stw.get("/breakglass").text
    row = re.search(rf'<tr data-grant="{gid}".*?</tr>', page, re.S)
    assert row, page[-500:]
    return [re.sub(r"<[^>]+>", "", x) for x in re.findall(r'data-testid="bg-use">(.*?)</li>', row.group(0))]


@pytest.mark.parametrize("who", ["admin", "investigator"])
def test_one_rule_for_the_administrator_and_a_non_admin_reader(box: dict[str, Any], who: str) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(980))
    reader = _reader(box, who)
    stw = _user(box, "stw1", "steward")
    # outside its own rights: no patient page, no chart number
    assert reader.get(f"/studies/GZQO/patients/{A}").status_code == 403
    csrf = _csrf(reader.get("/breakglass").text)
    r = reader.post(f"/studies/GZQO/patients/{A}/reveal", data={"csrf": csrf, "reason": "contact"})
    assert r.status_code == 403 and box["backend"].revealed == []
    # a reason, one patient: no second person is asked
    assert _open(reader, kind="patient", ruleset="GZQO", pid=A).headers["location"] == "/breakglass?done=open"
    gid = _events(box, "console.breakglass_open")[-1]["detail"]["grant"]
    p = reader.get(f"/studies/GZQO/patients/{A}")
    assert p.status_code == 200 and 'data-testid="reveal"' in p.text
    assert reader.get(f"/studies/GZQO/patients/{B}").status_code == 403  # that patient only
    r = reader.post(f"/studies/GZQO/patients/{A}/reveal", data={"csrf": _csrf(p.text), "reason": "contact"})
    assert r.status_code == 200 and "MRN-000123" in r.text
    assert box["backend"].signed == [("reveal", authz.BREAK_GLASS_ROLE, "*")]  # the grant's role, never the account's
    # the steward and the study's PI are told at once
    assert any(
        n[0] == "BG" and "stw1@hospa.test" in n[1] and "drsato@hospa.test" in n[1] for n in box["backend"].notices
    )
    # still open at 59 minutes, ended by itself at 60
    _shift(box, 59)
    assert reader.get(f"/studies/GZQO/patients/{A}").status_code == 200
    _shift(box, 1)
    assert reader.get(f"/studies/GZQO/patients/{A}").status_code == 403
    r = reader.post(f"/studies/GZQO/patients/{A}/reveal", data={"csrf": _csrf(p.text), "reason": "contact"})
    assert r.status_code == 403 and len(box["backend"].revealed) == 1
    # every use is on the steward's review list, one line each, as in the audit trail
    used = [e for e in _events(box, "console.breakglass_use") if e["detail"]["grant"] == gid]
    lines = _uses_on_review_list(stw, gid)
    assert len(lines) == len(used) == 3
    assert sum("patient page" in x for x in lines) == 2 and sum("chart number" in x for x in lines) == 1
    assert all(A[:8] in x and A not in x for x in lines)  # the pseudonym cut to 8 characters
    page = stw.get("/breakglass").text
    assert 'data-testid="bg-review"' in page  # ended: the steward reviews it


def test_an_investigator_job_grant_opens_that_job_only(box: dict[str, Any]) -> None:  # noqa: F811
    jid = _ulid(982)
    _done_screen(box["backend"], jid)
    drlee = _reader(box, "investigator")
    stw = _user(box, "stw1", "steward")
    assert 'data-testid="screen-rows"' not in drlee.get(f"/pilot/jobs/{jid}").text
    assert _open(drlee, kind="job", job_id=jid, reason="incident", note="incident 7: list check").status_code == 303
    page = drlee.get(f"/pilot/jobs/{jid}").text
    assert 'data-testid="screen-rows"' in page and 'data-testid="reveal"' in page
    gid = _events(box, "console.breakglass_open")[-1]["detail"]["grant"]
    assert any("job page" in x for x in _uses_on_review_list(stw, gid))


def test_no_grant_for_what_the_account_already_reads(box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(984))
    _reader(box, "investigator")
    pi = _login_as(box, "drsato")
    r = _open(pi, kind="patient", ruleset="GZQO", pid=A)  # the logged PI reads GZQO's patients by its own rights
    assert r.headers["location"] == "/breakglass?err=bg.err.needless"
    assert _events(box, "console.breakglass_open") == []
    crc = _user(box, "crc1", "coordinator")  # a coordinator reads the study already; no grant row at all
    assert _open(crc, kind="patient", ruleset="GZQO", pid=A).status_code == 403
    # the steward reviews and never opens; the PI reads the grants of its study
    assert not permit("steward", "breakglass.open") and not permit("coordinator", "breakglass.open")
    drlee = _login_as(box, "drlee")
    _open(drlee, kind="patient", ruleset="GZQO", pid=A)
    gid = _events(box, "console.breakglass_open")[-1]["detail"]["grant"]
    page = pi.get("/breakglass").text
    assert f'data-grant="{gid}"' in page and 'data-testid="bg-review"' not in page
    assert 'data-testid="bg-form"' in page  # the PI may open its own, outside its own rights


def _login_as(b: dict[str, Any], name: str) -> TestClient:
    return login(b["app"], name, PW)[0]
