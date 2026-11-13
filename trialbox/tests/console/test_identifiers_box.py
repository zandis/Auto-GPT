"""T-719 (D-487; trust review F3, TR-8): a chart number becomes a pseudonym only for a verified person with a right.

On the real orchestrator in the production trust configuration (``tests/orch_box.py``). The acceptance of the card:
the two routes that answered any admitted token (``POST /setup/pseudonym`` and ``POST /registry/{rs}`` with a chart
number) refuse a bare token. Synthetic chart numbers only.
"""

from __future__ import annotations

from typing import Any

from tests.actor3 import signed
from tests.orch_box import STUDY, OrchBox


def _pairs(ob: OrchBox, n: int = 3) -> list[tuple[str, str]]:
    """(chart number, pseudonym) of ``n`` synthetic patients of the site."""
    return [(mrn, pid) for pid, mrn in sorted(ob.mrn.items())[:n]]


def test_the_two_open_routes_refuse_a_bare_token(orch_box: OrchBox) -> None:
    """F3 as the review ran it: the console's token, a chart number, no person."""
    c = orch_box.client("console")
    (mrn, pid), (mrn2, pid2) = _pairs(orch_box, 2)
    r = c.post("/setup/pseudonym", json={"chart_no": mrn})
    assert r.status_code == 403 and pid not in r.text, r.text[:200]
    body: dict[str, Any] = {"mrn": mrn2, "status": "candidate", "source": "manual"}
    r = c.post(f"/registry/{STUDY}", json=body)
    assert r.status_code == 403 and pid2 not in r.text, r.text[:200]
    assert c.get(f"/registry/{STUDY}").json() == []  # and nothing was written
    refused = orch_box.events("actor.refused")
    # the pseudonym route's door, and since T-715b (D-550) the registry's own stage, which comes before its door
    assert len(refused) == 2 and {e["detail"]["reason"] for e in refused} == {
        "a chart number needs a verified person", "no signed-in user on this call (X-TB-Actor-Assertion)"}  # fmt: skip
    assert not orch_box.events("screen.to_pid")
    # T-715b: a row by pseudonym is no lookup, and it too needs the verified person now
    body = {"pid": pid, "status": "candidate", "source": "manual"}
    assert c.post(f"/registry/{STUDY}", json=body).status_code == 403
    assert c.get(f"/registry/{STUDY}").json() == []


def test_a_verified_person_with_a_right_gets_the_pseudonym_and_it_is_on_the_record(orch_box: OrchBox) -> None:
    c = orch_box.client("console")
    (mrn, pid), (mrn2, pid2) = _pairs(orch_box, 2)
    path, body = "/setup/pseudonym", {"chart_no": mrn}
    r = c.post(
        path, json=body, headers=signed("optout.keep", "", "POST", path, body, sub="console:stw", role="steward")
    )
    assert r.status_code == 200 and r.json() == {"pid": pid}
    done = orch_box.events("screen.to_pid")
    assert len(done) == 1 and done[0]["actor"] == "console:stw"
    assert done[0]["detail"] == {"pid": pid, "role": "steward", "action": "optout.keep", "via": "POST /setup/pseudonym"}
    assert mrn not in str(done[0])  # the chart number is never on the record
    path = f"/registry/{STUDY}"
    reg: dict[str, Any] = {"mrn": mrn2, "status": "candidate", "source": "manual"}
    r = c.post(path, json=reg, headers=signed("request.prepare", STUDY, "POST", path, reg))
    assert r.status_code == 200 and r.json()["pid"] == pid2
    assert orch_box.events("screen.to_pid")[-1]["detail"]["via"] == "POST /registry/{ruleset}"
    # a role the matrix does not give the action, an action that is not one of the door's, another body
    for headers, why in (
        (signed("optout.keep", "", "POST", "/setup/pseudonym", body, role="viewer"), "right"),
        (signed("study.setup", "", "POST", "/setup/pseudonym", body), "action"),
        (signed("optout.keep", "", "POST", "/setup/pseudonym", {"chart_no": mrn2}, sub="console:stw", role="steward"),
         "a chart number needs a verified person"),
    ):  # fmt: skip
        r = c.post("/setup/pseudonym", json=body, headers=headers)
        assert r.status_code == 403 and orch_box.events("actor.refused")[-1]["detail"]["reason"] == why
    assert len(orch_box.events("screen.to_pid")) == 2


def test_the_number_space_cannot_be_walked(orch_box: OrchBox, monkeypatch: Any) -> None:
    """A cap per person and hour in the orchestrator's store (``TB_TO_PID_MAX_PER_HOUR``), as for reveals."""
    monkeypatch.setenv("TB_TO_PID_MAX_PER_HOUR", "2")
    c = orch_box.client("console")
    codes = []
    for mrn, _pid in _pairs(orch_box, 3):
        body = {"chart_no": mrn}
        h = signed("optout.keep", "", "POST", "/setup/pseudonym", body, sub="console:stw", role="steward")
        codes.append(c.post("/setup/pseudonym", json=body, headers=h).status_code)
    assert codes == [200, 200, 429]
    assert orch_box.events("actor.refused")[-1]["detail"]["reason"] == "rate limit"
    assert len(orch_box.events("screen.to_pid")) == 2


def test_the_consoles_backend_signs_a_row_by_chart_number(orch_box: OrchBox) -> None:
    """``HttpBackend.registry_update`` on the real orchestrator: refused without the person's assertion, a row and a
    record with it; since T-715b a row by pseudonym needs it too."""
    import pytest
    from console.backend import Refused
    from tb_contracts import RegistryUpdate

    from tests.actor3 import signer

    bk = orch_box.backend()
    (mrn, pid), (_m, pid2) = _pairs(orch_box, 2)
    upd = RegistryUpdate(mrn=mrn, status="candidate", by="crc1@hospa.test", source="manual")
    with pytest.raises(Refused, match="no signed-in user"):  # a signer that signs nothing
        bk.registry_update(STUDY, upd, lambda *_a: {})
    assert bk.registry_update(STUDY, upd, signer(STUDY, action="request.prepare")).pid == pid
    assert [e["detail"]["pid"] for e in orch_box.events("screen.to_pid")] == [pid]
    by_pid = RegistryUpdate(pid=pid2, status="candidate", by="crc1@hospa.test", source="manual")
    with pytest.raises(Refused, match="no signed-in user"):  # T-715b (D-550): a row by pseudonym too
        bk.registry_update(STUDY, by_pid, lambda *_a: {})
    assert bk.registry_update(STUDY, by_pid, signer(STUDY, action="request.prepare")).pid == pid2


# ------------------------------------------------------------------------------ the adversarial review's findings
def test_site_setup_turns_no_chart_number_into_a_pseudonym_for_a_bare_token(orch_box: OrchBox) -> None:
    """Review H1: a pasted chart and an uploaded sheet hash chart numbers too, and their read routes give the
    pseudonyms back. With the console's token alone that was a walk of the number space with no person, no cap and
    no event. The three routes need the verified person of the call (`site.setup`)."""
    import base64

    c = orch_box.client("console")
    chart = {"chart_no": "10000001", "text": "synthetic note", "by": "nobody", "lang": "en"}
    sheet = {"kind": "sheet", "name": "list.csv", "roles": {}, "by": "nobody",
             "b64": base64.b64encode(b"chart,age\n10000001,61\n10000002,58\n").decode("ascii")}  # fmt: skip
    for path, body in (("/setup/main/charts", chart), ("/setup/main/sheets", sheet),
                       ("/setup/main/sheets/1/roles", {"roles": {}, "by": "nobody"})):  # fmt: skip
        r = c.post(path, json=body)
        assert r.status_code == 403, (path, r.status_code, r.text[:200])
        assert orch_box.events("actor.refused")[-1]["detail"]["route"].endswith(path.rsplit("/", 1)[-1])
    assert (
        c.get("/setup/main/people").json() in ([], {"people": []}) or "10000001" not in c.get("/setup/main/people").text
    )
    assert not orch_box.events("screen.to_pid")
    # the coordinator's own signed call is admitted, counted, and on the record without the chart number
    path = "/setup/main/charts"
    r = c.post(path, json=chart, headers=signed("site.setup", "", "POST", path, chart))
    assert r.status_code == 200, r.text[:300]
    done = orch_box.events("screen.to_pid")
    assert len(done) == 1 and done[0]["actor"] == "console:crc" and done[0]["detail"]["action"] == "site.setup"
    assert done[0]["detail"]["via"] == "POST /setup/{ws}/charts" and "10000001" not in str(done[0])


def test_the_door_ties_the_action_to_the_route(orch_box: OrchBox) -> None:
    """Review M1: any of the door's actions opened any of its routes: the nightly timer's `request.prepare` on the
    opt-out lookup, a steward's `optout.keep` on a registry row, a coordinator's claim for a made-up study."""
    c = orch_box.client("console")
    ((mrn, _pid),) = _pairs(orch_box, 1)
    path, body = "/setup/pseudonym", {"chart_no": mrn}
    for headers in (
        signed("request.prepare", "", "POST", path, body, sub="service:console-nightly", role="service"),
        signed("request.prepare", "ZZZZ", "POST", path, body),
        signed("request.prepare", "", "POST", path, body),
        signed("site.setup", "", "POST", path, body),
    ):
        r = c.post(path, json=body, headers=headers)
        assert r.status_code == 403, r.text[:200]
        assert orch_box.events("actor.refused")[-1]["detail"]["reason"] in ("action", "principal", "study")
    path = f"/registry/{STUDY}"
    reg: dict[str, Any] = {"mrn": mrn, "status": "candidate", "by": "crc1@hospa.test", "source": "manual"}
    r = c.post(
        path, json=reg, headers=signed("optout.keep", STUDY, "POST", path, reg, sub="console:stw", role="steward")
    )
    assert r.status_code == 403 and orch_box.events("actor.refused")[-1]["detail"]["reason"] == "action"
    assert not orch_box.events("screen.to_pid")
