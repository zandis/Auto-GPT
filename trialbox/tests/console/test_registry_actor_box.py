"""T-715b (D-550): the registry's two changing routes refuse a call without a verified person.

On the real orchestrator in the production trust configuration. Before this card the routes were in stage `report`:
any admitted token could set a candidate's status or promote a screening's candidates under a name typed in the body
(``"by": "dr_tanaka"``), and the registry, its export and the audit trail showed that name."""

from __future__ import annotations

from typing import Any

from tests.actor3 import signed
from tests.console.test_console_app import CRC_PW, login
from tests.console.test_orch_box import site  # noqa: F401  (the console of the box)
from tests.orch_box import STUDY, OrchBox

ACT = "request.prepare"


def _rows(ob: OrchBox) -> list[dict[str, Any]]:
    return list(ob.client("console").get(f"/registry/{STUDY}").json())


def test_a_name_in_the_body_sets_no_status_and_promotes_nobody(orch_box: OrchBox) -> None:
    pid = orch_box.listed()[0]
    c = orch_box.client("console")
    r = c.post(f"/registry/{STUDY}", json={"pid": pid, "status": "contacted", "by": "console:dr_tanaka"})
    assert r.status_code == 403, r.text[:300]
    r = c.post(f"/registry/{STUDY}/promote", json={"by": "dr_tanaka"})
    assert r.status_code == 403, r.text[:300]
    assert _rows(orch_box) == []
    assert [e["detail"]["action"] for e in orch_box.events("actor.refused")] == [ACT, ACT]
    assert orch_box.events("registry.update") == [] and orch_box.events("registry.promote") == []


def test_a_signed_call_is_recorded_under_the_verified_person_whatever_the_body_says(orch_box: OrchBox) -> None:
    pid = orch_box.listed()[0]
    c = orch_box.client("console")
    path, body = f"/registry/{STUDY}", {"pid": pid, "status": "contacted", "reason": "phone", "source": "manual"}
    r = c.post(path, json=body, headers=signed(ACT, STUDY, "POST", path, body, sub="console:crc"))
    assert r.status_code == 200, r.text[:300]
    assert r.json()["updated_by"] == "console:crc"
    # a `by` in the body is not a field of the request any more: it is refused, not ignored (the body is signed)
    typed = {**body, "by": "console:dr_tanaka"}
    r = c.post(path, json=typed, headers=signed(ACT, STUDY, "POST", path, typed, sub="console:crc"))
    assert r.status_code == 422, r.text[:300]
    path, body = f"/registry/{STUDY}/promote", {"tiers": ["high", "review"]}
    r = c.post(path, json=body, headers=signed(ACT, STUDY, "POST", path, body, sub="console:crc"))
    assert r.status_code == 200 and r.json()["added"] >= 1, r.text[:300]
    assert {row["updated_by"] for row in _rows(orch_box)} == {"console:crc"}
    assert {e["actor"] for e in orch_box.events("registry.promote")} == {"console:crc"}


def test_another_study_another_body_or_a_role_without_the_right_is_refused(orch_box: OrchBox) -> None:
    pid = orch_box.listed()[0]
    c = orch_box.client("console")
    path, body = f"/registry/{STUDY}", {"pid": pid, "status": "contacted"}
    cases = {
        "study": signed(ACT, "OTHER1", "POST", path, body),
        "body": signed(ACT, STUDY, "POST", path, {**body, "status": "enrolled"}),
        "request": signed(ACT, STUDY, "POST", path + "/promote", body),
        "right": signed(ACT, STUDY, "POST", path, body, sub="console:viewer1", role="viewer"),
        "action": signed("study.setup", STUDY, "POST", path, body),
    }
    for why, headers in cases.items():
        r = c.post(path, json=body, headers=headers)
        assert r.status_code == 403 and why in r.text, (why, r.text[:200])
    assert _rows(orch_box) == []


def test_the_coordinator_promotes_and_edits_through_the_console(site: dict[str, Any]) -> None:  # noqa: F811
    ob: OrchBox = site["ob"]
    ob.screen()
    c, csrf = login(site["app"], "crc", CRC_PW)
    r = c.post(f"/pilot/registry/{STUDY}/promote", data={"csrf": csrf}, follow_redirects=False)
    assert r.status_code == 303 and "added=" in r.headers["location"], r.text[-300:]
    pid = _rows(ob)[0]["pid"]
    r = c.post(f"/pilot/registry/{STUDY}", data={"csrf": csrf, "pid": pid, "status": "contacted", "reason": "phone"},
               follow_redirects=False)  # fmt: skip
    assert r.status_code == 303, r.text[-300:]
    rows = {row["pid"]: row for row in _rows(ob)}
    assert rows[pid]["status"] == "contacted" and {row["updated_by"] for row in rows.values()} == {"console:crc"}
    assert not ob.events("actor.refused") and not ob.events("actor.unsigned")
