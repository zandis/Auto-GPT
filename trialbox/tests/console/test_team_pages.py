"""D-147: the delegation log (sub-investigators by delegation), the whole-hospital candidate view, the referral to the
treating doctor (who may be unknown), the IRB / consent-form warning before Approach, and the opt-out register. Pages
and ``/api/v1`` alike, in three languages."""

from __future__ import annotations

import io
import json
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from console.app import create_app
from console.i18n import CATALOGUES
from console.teamstore import Irb, TeamStore
from fastapi.testclient import TestClient
from tb_common.crypto import sha256_bytes
from tb_common.optout import OptOutRegister, opted_out
from tb_contracts import Job, JobOutput

from tests.console.test_console_app import (  # noqa: F401 - the fixture is used by name
    PILOT_ENV,
    _done_screen,
    _ulid,
    box,
    login,
    name_pi,
    review_book,
)
from tests.console.test_role_pages import PW, _csrf, _user

A, B = "a" * 32, "b" * 32


def _events(b: dict[str, Any], name: str) -> list[dict[str, Any]]:
    out = []
    for f in sorted((b["dir"] / "audit").glob("*.jsonl")):
        for line in f.read_text().splitlines():
            if line and json.loads(line).get("event") == name:
                out.append(json.loads(line))
    return out


def _no_doctor(b: dict[str, Any], jid: str) -> None:
    """Patient B's row names no treating doctor (the feed often has none)."""
    key = next(k for k in b["backend"].objects if k.startswith(f"outputs/{jid}/candidate_list_"))
    cl = json.loads(b["backend"].objects[key])
    cl["rows"][1]["practitioner_id"] = None
    b["backend"].objects[key] = json.dumps(cl).encode()


def _log_pi_and_sub(b: dict[str, Any], pi: TestClient, tasks: tuple[str, ...]) -> None:
    name_pi(b, "drsato")  # D-380 (ROLE-008): the steward writes the PI entry; the PI adds the sub-investigator
    page = pi.get("/studies/GZQO/team").text
    r = pi.post("/studies/GZQO/team", data={"csrf": _csrf(page), "username": "drkato", "role": "sub_pi",
                                            "tasks": list(tasks), "start": "2026-01-01"}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303, r.text[-400:]


# ---------------------------------------------------------------------------------------------- store and register
def test_team_store_log_referral_irb_and_views() -> None:
    t = TeamStore()
    eid = t.add_entry("GZQO", username="drsato", name="Dr Sato", role="pi", tasks=(), start="2026-01-01", end=None,
                      training_day="2025-06-01", training_ref="GCP-1", by="drsato", at="2026-10-01T00:00:00+00:00")  # fmt: skip
    pi = t.pi_of("GZQO", date(2026, 10, 1))
    assert pi is not None and pi.id == eid and set(pi.tasks) == {"screen", "approach", "refer", "enter_data", "run"}
    sub = t.add_entry("GZQO", username="drkato", name="Dr Kato", role="sub_pi", tasks=["screen", "bogus"],
                      start="2026-01-01", end=None, training_day=None, training_ref=None, by="drsato",
                      at="2026-10-01T00:01:00+00:00")  # fmt: skip
    assert t.entry("GZQO", sub).tasks == ("screen",)  # type: ignore[union-attr]
    t.update_entry("GZQO", sub, tasks=["screen", "refer"], end="2026-12-31", training_day="2026-02-01",
                   training_ref="", by="drsato", at="2026-10-02T00:00:00+00:00")  # fmt: skip
    e = t.entry("GZQO", sub)
    assert e is not None and e.tasks == ("screen", "refer") and not e.active_on(date(2027, 1, 1))
    assert [a for _i, ev in t.history("GZQO") for a in [ev.action]] == ["add", "add", "update"]
    rid = t.add_referral("GZQO", A, route="outside", physician="", physician_id="", department="", suggested="",
                         suggested_source="", note="", by="drkato", at="2026-10-02T01:00:00+00:00")  # fmt: skip
    ref = t.answer("GZQO", rid, "decline", "bogus", "fax", "", "crc1", "2026-10-03T00:00:00+00:00")
    assert (ref.state, ref.reason, ref.channel, ref.answered_by) == ("declined", "other", "other", "crc1")
    with pytest.raises(ValueError):
        t.answer("GZQO", rid, "agree", "", "phone", "", "crc1", "2026-10-03T00:01:00+00:00")  # answered already
    assert Irb().warnings(date(2026, 10, 1)) == ["irb_missing", "icf_missing"]
    rec = t.save_irb("GZQO", Irb("IRB-1", "2026-01-01", "2026-06-30", "v2.0", ""), "crc1", "2026-10-01T00:00:00+00:00")
    assert rec.warnings(date(2026, 10, 1)) == ["irb_expired"] and rec.warnings(date(2026, 5, 1)) == []
    t.record_view("GZQO", A, "eligibility", "view", "drkato", "2026-10-01T00:00:00+00:00")
    assert t.count_views("drkato", "view", "2026-09-30T00:00:00+00:00") == 1


def test_opt_out_register_as_of_and_read_only_reader() -> None:
    assert opted_out() == frozenset()  # no register yet: nothing to remove, and nothing created
    reg = OptOutRegister()
    assert reg.add(A, "paper", "", "office1", "2026-10-01T09:00:00+09:00")
    # already opted out: not a change, but the person's request is its own event (D-441, review HIGH-2)
    assert not reg.add(A, "paper", "", "office1", "2026-10-01T10:00:00+09:00")
    assert reg.lift(A, "changed her mind", "office1", "2026-10-05T09:00:00+09:00")
    assert reg.add(B, "phone", "", "office1", "2026-10-06T09:00:00+09:00")
    assert reg.active() == {B}
    assert reg.active("2026-10-02T00:00:00+00:00") == {A}  # as it stood then: a re-run of an old job is unchanged
    assert opted_out(as_of="2026-10-02T00:00:00+00:00") == frozenset({A}) and opted_out() == frozenset({B})
    assert [e.action for e in reg.events()] == ["opt_out", "opt_out", "lift", "opt_out"]


# ---------------------------------------------------------------------------------------------- permissions
def test_sub_investigator_rights_come_from_the_delegation_log(box: dict[str, Any]) -> None:
    _done_screen(box["backend"], _ulid(961))
    pi = _user(box, "drsato", "investigator")
    sub = _user(box, "drkato", "investigator")
    other = _user(box, "drito", "investigator")
    # D-380 (ROLE-008): before the log names a PI, nobody acts as PI
    assert other.get("/studies/GZQO/candidates").status_code == 403
    _log_pi_and_sub(box, pi, ("screen", "refer"))
    page = pi.get("/studies/GZQO/team").text
    assert 'data-testid="tick-2-screen">✓' in page and 'data-testid="tick-2-approach">–' in page
    # the sub-PI sees the candidates and may refer, but marks no Approach without the tick
    assert sub.get("/studies/GZQO/candidates").status_code == 200
    cp = sub.get(f"/studies/GZQO/candidates/{A}?purpose=eligibility")
    assert cp.status_code == 200 and "two flares this spring" in cp.text and 'data-testid="referral-form"' in cp.text
    wk = sub.get(f"/studies/GZQO/week?list=all&pid={A}").text
    assert f'data-testid="approach-{A[:8]}"' not in wk
    r = sub.post(f"/studies/GZQO/patients/{A}/mark", data={"csrf": _csrf(wk), "mark": "approach"})
    assert r.status_code == 403
    r = sub.post(f"/studies/GZQO/patients/{B}/mark", data={"csrf": _csrf(wk), "mark": "need_info"},
                 follow_redirects=False)  # fmt: skip
    assert r.status_code == 303  # "screen" covers the other marks
    # an investigator not on the log: refused everywhere patient-level
    for path in ("/studies/GZQO/candidates", f"/studies/GZQO/candidates/{A}?purpose=eligibility",
                 "/studies/GZQO/week", f"/studies/GZQO/patients/{A}"):  # fmt: skip
        assert other.get(path).status_code == 403, path
    # D-143's reveal follows the log: the delegated sub-PI reveals, the investigator not on the log does not
    r = other.post(
        f"/studies/GZQO/patients/{A}/reveal", data={"csrf": _csrf(other.get("/home").text), "reason": "contact"}
    )
    assert r.status_code == 403 and not box["backend"].revealed
    api = TestClient(box["app"])
    tok = api.post("/api/v1/session", json={"username": "drito", "password": PW}).json()["token"]
    r = api.post(f"/api/v1/studies/GZQO/patients/{A}/reveal", json={"reason": "contact"},
                 headers={"Authorization": f"Bearer {tok}"})  # fmt: skip
    assert r.status_code == 403 and not box["backend"].revealed
    r = sub.post(f"/studies/GZQO/patients/{A}/reveal", data={"csrf": _csrf(wk), "reason": "eligibility"})
    assert r.status_code == 200 and "MRN-000123" in r.text and box["backend"].revealed[-1][2] == "console:drkato"
    # only the PI keeps the log; the sub-PI cannot add themselves a tick
    r = sub.post("/studies/GZQO/team/2", data={"csrf": _csrf(wk), "tasks": ["screen", "approach"]})
    assert r.status_code == 403
    # the PI ticks Approach: now the sub-PI may mark it (the IRB warning is recorded as an override)
    r = pi.post("/studies/GZQO/team/2", data={"csrf": _csrf(page), "tasks": ["screen", "approach", "refer"]},
                follow_redirects=False)  # fmt: skip
    assert r.status_code == 303
    r = sub.post(f"/studies/GZQO/patients/{A}/mark", data={"csrf": _csrf(wk), "mark": "approach"},
                 follow_redirects=False)  # fmt: skip
    assert r.status_code == 303
    assert _events(box, "console.pi_mark")[-1]["actor"] == "console:drkato"
    assert {e["detail"]["action"] for e in _events(box, "console.delegation")} == {"add", "update"}


def test_only_the_logged_pi_approves(box: dict[str, Any]) -> None:
    _done_screen(box["backend"], _ulid(962))
    pi = _user(box, "drsato", "investigator")
    sub = _user(box, "drkato", "investigator")
    _log_pi_and_sub(box, pi, ("screen", "approach", "refer"))
    book = review_book([("GZQO-INC-01", "inclusion", "structured", "Age 18 or over.", None, 100, None)])
    jid = _ulid(963)
    key = f"outputs/{jid}/review_GZQO_v1.1.0_r1.xlsx"
    box["backend"].objects[key] = book
    now = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
    out = JobOutput(filename="review_GZQO_v1.1.0_r1.xlsx", sha256=sha256_bytes(book), minio_key=key, recipients=[],
                    tag="aggregate")  # fmt: skip
    box["backend"].add_job(Job(job_id=jid, type="FEAS", ruleset="GZQO", ruleset_version="1.1.0",
                               requested_by="admin@hospa.test", received_at=now, updated_at=now,
                               state="awaiting_approval", options={}, outputs=[out]))  # fmt: skip
    page = sub.get(f"/pilot/jobs/{jid}/approval").text
    assert 'data-testid="approve-who"' in page and 'data-testid="approve"' not in page
    r = sub.post(f"/pilot/jobs/{jid}/approve", data={"csrf": _csrf(page)})
    assert r.status_code == 403
    assert 'data-testid="approve"' in pi.get(f"/pilot/jobs/{jid}/approval").text


def test_cro_and_viewer_stay_masked(box: dict[str, Any]) -> None:
    _done_screen(box["backend"], _ulid(964))
    cro = _user(box, "cro1", "cro", affiliation="cro", studies="GZQO")  # D-380 (ROLE-011): names its studies
    vc = _user(box, "view2", "viewer")
    for c in (cro, vc):
        for path in ("/studies/GZQO/candidates", f"/studies/GZQO/candidates/{A}?purpose=eligibility",
                     "/studies/GZQO/referrals", "/studies/GZQO/team", "/site/opt-outs"):  # fmt: skip
            r = c.get(path)
            assert r.status_code in (403, 404), (path, r.status_code)
            assert "MRN-000123" not in r.text and "two flares" not in r.text
    api = TestClient(box["app"])
    tok = api.post("/api/v1/session", json={"username": "view2", "password": PW}).json()["token"]
    hdr = {"Authorization": f"Bearer {tok}"}
    assert api.get("/api/v1/studies/GZQO/candidates", headers=hdr).status_code == 403
    r = api.post(f"/api/v1/studies/GZQO/patients/{A}/reveal", json={"reason": "contact"}, headers=hdr)
    assert r.status_code == 403 and not box["backend"].revealed


# ---------------------------------------------------------------------------------------------- candidate view
def test_candidate_view_needs_a_purpose_is_logged_and_reveals_for_the_pi(box: dict[str, Any]) -> None:
    _done_screen(box["backend"], _ulid(965))
    pi = _user(box, "drsato", "investigator")
    name_pi(box, "drsato")  # D-380 (ROLE-008): the steward names the PI
    page = pi.get("/studies/GZQO/candidates").text
    assert 'data-testid="cand-aaaaaaaa"' in page and 'data-testid="cand-bbbbbbbb"' in page
    assert "Dr Lin" in page and "(suggested from the data)" in page
    first = pi.get(f"/studies/GZQO/candidates/{A}").text
    assert 'data-testid="purpose"' in first and "two flares" not in first  # nothing patient-level yet
    assert not _events(box, "console.candidate_view")
    r = pi.get(f"/studies/GZQO/candidates/{A}?purpose=bogus")  # an unknown purpose: asked again, nothing shown
    assert (
        'data-testid="purpose"' in r.text and "two flares" not in r.text and not _events(box, "console.candidate_view")
    )
    api = TestClient(box["app"])
    tok = api.post("/api/v1/session", json={"username": "drsato", "password": PW}).json()["token"]
    r = api.get(f"/api/v1/studies/GZQO/candidates/{A}", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 400 and r.json()["error"] == "candidate.purpose"
    p = pi.get(f"/studies/GZQO/candidates/{A}?purpose=eligibility").text
    assert "two flares this spring" in p and 'data-testid="why"' in p and 'data-testid="reveal"' in p
    ev = _events(box, "console.candidate_view")[-1]
    assert ev["ruleset"] == "GZQO" and ev["detail"]["purpose"] == "eligibility" and ev["detail"]["pid"] == A
    assert 'data-testid="reveal-reason"' in p  # D-143: a reason is asked, as on the patient page
    r = pi.post(f"/studies/GZQO/candidates/{A}/reveal", data={"csrf": _csrf(p), "purpose": "contact"})
    assert r.status_code == 400 and not box["backend"].revealed  # no reason, no chart number
    # D-143: the PI sees the chart number here through the same reveal, with its reason and the view's purpose
    r = pi.post(f"/studies/GZQO/candidates/{A}/reveal",
                data={"csrf": _csrf(p), "purpose": "contact", "reason": "contact"})  # fmt: skip
    assert "MRN-000123" in r.text and box["backend"].revealed[-1][2] == "console:drsato"
    rev = _events(box, "console.reveal_patient")[-1]
    assert rev["detail"]["purpose"] == "contact" and rev["detail"]["via"] == "candidates"
    assert rev["detail"]["reason"] == "contact"
    # and on the patient page (D-143 reversed D-133's "the investigator may not reveal")
    r = pi.post(f"/studies/GZQO/patients/{A}/reveal", data={"csrf": _csrf(p), "reason": "consent"})
    assert r.status_code == 200 and "MRN-000123" in r.text
    assert _events(box, "console.reveal_patient")[-1]["detail"]["via"] == "patient"
    for lang, word in (("ja", "院内の候補者"), ("zh-TW", "全院候選者")):
        pi.post("/lang", data={"csrf": _csrf(p), "lang": lang, "back": "/home"})
        assert word in pi.get("/studies/GZQO/candidates").text


def test_candidate_views_are_rate_limited_and_reveals_meet_the_d143_cap(box: dict[str, Any]) -> None:
    from console.backend import Refused

    _done_screen(box["backend"], _ulid(966))
    env = {**PILOT_ENV, "TB_CONSOLE_DIR": str(box["dir"] / "console2"), "TB_CANDIDATE_VIEWS_PER_HOUR": "2"}
    app = create_app(env, backend=box["backend"], audit=box["audit"], users=box["users"])
    box["users"].create("drsato", "investigator", PW, "drsato@hospa.test")
    name_pi(box, "drsato")  # D-380 (ROLE-008): the steward names the PI
    pi, _ = login(app, "drsato", PW)
    for _ in range(2):
        assert pi.get(f"/studies/GZQO/candidates/{A}?purpose=eligibility").status_code == 200
    r = pi.get(f"/studies/GZQO/candidates/{B}?purpose=eligibility")
    assert r.status_code == 429 and "two flares" not in r.text
    csrf = _csrf(pi.get("/studies/GZQO/candidates").text)
    form = {"csrf": csrf, "purpose": "contact", "reason": "contact"}
    assert "MRN-000123" in pi.post(f"/studies/GZQO/candidates/{A}/reveal", data=form).text
    real = box["backend"].reveal

    def capped(job_id: str, pid: str, by: str, role: str = "", scope: str = "") -> str | None:  # D-143 cap
        raise Refused("too many chart numbers revealed in the last hour")

    box["backend"].reveal = capped
    r = pi.post(f"/studies/GZQO/candidates/{A}/reveal", data=form)
    assert r.status_code == 409 and "MRN-000123" not in r.text  # the candidate page meets the same cap
    box["backend"].reveal = real
    assert len(box["backend"].revealed) == 1
    assert [e["detail"]["action"] for e in _events(box, "console.rate_limited")] == ["view"]


# ---------------------------------------------------------------------------------------------- referral
def test_referral_never_stalls_on_an_unknown_doctor(box: dict[str, Any]) -> None:
    jid = _ulid(967)
    _done_screen(box["backend"], jid)
    _no_doctor(box, jid)
    pi = _user(box, "drsato", "investigator")
    name_pi(box, "drsato")  # D-380 (ROLE-008): the steward names the PI
    crc = _user(box, "crc1", "coordinator")
    stw = _user(box, "stw", "steward")  # D-380 (ROLE-005): the steward keeps the directory
    # the steward's directory and department contact
    sp = stw.get("/site/staff").text
    stw.post("/site/staff", data={"csrf": _csrf(sp), "kind": "person", "name": "Dr Mori", "department": "RHEU",
                                  "practitioner_id": "DR-MORI"})  # fmt: skip
    stw.post("/site/staff", data={"csrf": _csrf(sp), "kind": "contact", "department": "RHEU", "name": "Ward clerk Abe",
                                  "contact": "ext 4410"})  # fmt: skip
    cand = pi.get("/studies/GZQO/candidates?show=unknown").text
    assert 'data-testid="cand-bbbbbbbb"' in cand and 'data-testid="cand-aaaaaaaa"' not in cand
    p = pi.get(f"/studies/GZQO/candidates/{B}?purpose=referral").text
    assert "Doctor unknown" in p and 'value="suggested"' not in p  # nothing to suggest: no suggestion offered
    # no route, no name: still a referral (to the department contact), and the patient gets a screening number
    r = pi.post(f"/studies/GZQO/candidates/{B}/referral", data={"csrf": _csrf(p)}, follow_redirects=False)
    assert r.status_code == 303
    t = box["app"].state.helpers.team
    ref = t.referrals("GZQO", B)[-1]
    assert (ref.route, ref.physician, ref.department, ref.suggested) == ("department", "Ward clerk Abe", "RHEU", "")
    assert box["app"].state.helpers.store.screening_no("GZQO", B)
    # Approach waits for the doctor's agreement
    wk = pi.get(f"/studies/GZQO/patients/{B}").text
    assert 'data-testid="ref-wait"' in wk and f'data-testid="approach-{B[:8]}"' not in wk
    r = pi.post(f"/studies/GZQO/patients/{B}/mark", data={"csrf": _csrf(wk), "mark": "approach"})
    assert r.status_code == 409 and "has not agreed" in r.text
    # the CRC records the doctor's answer: decline with a reason, then a new request typed by hand, then agree
    lp = crc.get("/studies/GZQO/referrals").text
    assert f'data-testid="ref-{ref.id}"' in lp and "Ward clerk Abe" in lp
    crc.post(f"/studies/GZQO/referrals/{ref.id}/answer", data={"csrf": _csrf(lp), "answer": "decline",
                                                               "reason": "unwell", "channel": "phone"})  # fmt: skip
    assert pi.post(f"/studies/GZQO/patients/{B}/mark", data={"csrf": _csrf(wk), "mark": "approach"}).status_code == 409
    r = pi.post(f"/studies/GZQO/candidates/{B}/referral",
                data={"csrf": _csrf(p), "route": "typed", "name": ""}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303 and t.referrals("GZQO", B)[-1].route == "typed"
    again = t.referrals("GZQO", B)[-1]
    crc.post(f"/studies/GZQO/referrals/{again.id}/answer", data={"csrf": _csrf(lp), "answer": "agree",
                                                                 "channel": "emr"})  # fmt: skip
    r = pi.post(f"/studies/GZQO/patients/{B}/mark", data={"csrf": _csrf(wk), "mark": "approach"},
                follow_redirects=False)  # fmt: skip
    assert r.status_code == 303
    # the known doctor is only a suggestion; the PI may pick the directory instead, or arrange it outside TrialBox
    pa = pi.get(f"/studies/GZQO/candidates/{A}?purpose=referral").text
    assert 'value="suggested" checked' in pa and "Dr Lin (DR-LIN)" in pa
    sid = t.staff()[0].id
    pi.post(f"/studies/GZQO/candidates/{A}/referral", data={"csrf": _csrf(pa), "route": "directory",
                                                            "staff_id": str(sid)})  # fmt: skip
    ra = t.referrals("GZQO", A)[-1]
    assert (ra.route, ra.physician, ra.physician_id, ra.suggested) == ("directory", "Dr Mori", "DR-MORI",
                                                                      "Dr Lin (DR-LIN)")  # fmt: skip
    # the screening log counts every referral with its route and outcome
    log = crc.get("/studies/GZQO/screening-log").text
    assert "Name typed · Doctor agreed" in log and "From the staff directory · Waiting for the doctor" in log
    from openpyxl import load_workbook

    ws: Any = load_workbook(io.BytesIO(crc.get("/studies/GZQO/screening-log.xlsx").content)).active
    rows = [list(x) for x in ws.iter_rows(values_only=True)]
    head = rows[0]
    by_pid = {r[1]: dict(zip(head, r, strict=True)) for r in rows[1:]}
    assert by_pid[B]["referral_route"] == "typed" and by_pid[B]["referral_outcome"] == "agreed"
    assert by_pid[A]["referral_route"] == "directory" and by_pid[A]["referral_outcome"] == "asked"
    acts = [(e["detail"]["action"], e["actor"]) for e in _events(box, "console.referral")]
    assert acts == [("requested", "console:drsato"), ("answered", "console:crc1"), ("requested", "console:drsato"),
                    ("answered", "console:crc1"), ("requested", "console:drsato")]  # fmt: skip


def test_outside_referral_outcome_recorded_later_by_the_pi_and_api(box: dict[str, Any]) -> None:
    _done_screen(box["backend"], _ulid(968))
    _user(box, "drsato", "investigator")
    name_pi(box, "drsato")  # D-380 (ROLE-008): the steward names the PI
    _user(box, "crc1", "coordinator")
    api = TestClient(box["app"])
    tok = api.post("/api/v1/session", json={"username": "drsato", "password": PW}).json()["token"]
    hdr = {"Authorization": f"Bearer {tok}"}
    r = api.post(f"/api/v1/studies/GZQO/candidates/{A}/referral", json={"route": "outside"}, headers=hdr)
    assert r.status_code == 200 and r.json()["route"] == "outside" and r.json()["state"] == "asked"
    ref_id = r.json()["id"]
    r = api.post(f"/api/v1/studies/GZQO/referrals/{ref_id}/answer", json={"answer": "agree", "channel": "in_person"},
                 headers=hdr)  # fmt: skip
    assert r.status_code == 200 and r.json()["state"] == "agreed"
    cands = api.get("/api/v1/studies/GZQO/candidates", headers=hdr).json()["candidates"]
    assert {c["pid"]: c["referral"] for c in cands}[A] == "agreed"
    one = api.get(f"/api/v1/studies/GZQO/candidates/{A}?purpose=eligibility", headers=hdr).json()
    assert one["doctor"]["known"] and one["why"]["total"] >= 1 and one["irb_warnings"]
    log = api.get("/api/v1/studies/GZQO/screening-log", headers=hdr).json()
    assert {x["pid"]: (x["referral_route"], x["referral_outcome"]) for x in log}[A] == ("outside", "agreed")


# ---------------------------------------------------------------------------------------------- IRB warning
def test_irb_warning_is_not_a_gate_and_each_override_is_logged(box: dict[str, Any]) -> None:
    _done_screen(box["backend"], _ulid(969))
    pi = _user(box, "drsato", "investigator")
    name_pi(box, "drsato")  # D-380 (ROLE-008): the steward names the PI
    crc = _user(box, "crc1", "coordinator")
    wk = pi.get(f"/studies/GZQO/patients/{A}").text
    assert 'data-testid="irb-warning"' in wk and "no IRB approval date" in wk
    r = pi.post(f"/studies/GZQO/patients/{A}/mark", data={"csrf": _csrf(wk), "mark": "approach"},
                follow_redirects=False)  # fmt: skip
    assert r.status_code == 303  # a warning, not a gate
    ov = _events(box, "console.approach_override")
    assert (
        len(ov) == 1 and ov[0]["detail"]["reason"] == "irb_missing,icf_missing" and ov[0]["actor"] == "console:drsato"
    )
    irb = crc.get("/studies/GZQO/irb").text
    assert "irb_missing" not in irb and 'data-testid="overrides"' in irb
    today = date.today()
    r = crc.post("/studies/GZQO/irb", data={"csrf": _csrf(irb), "approval_no": "IRB-2026-01",
                                            "approved_on": (today - timedelta(days=30)).isoformat(),
                                            "expires_on": (today + timedelta(days=300)).isoformat(),
                                            "icf_version": "v2.0"}, follow_redirects=False)  # fmt: skip
    assert r.status_code == 303 and 'data-testid="irb-ok"' in crc.get("/studies/GZQO/irb").text
    wk = pi.get(f"/studies/GZQO/patients/{B}").text
    assert 'data-testid="irb-warning"' not in wk
    api = TestClient(box["app"])
    tok = api.post("/api/v1/session", json={"username": "drsato", "password": PW}).json()["token"]
    r = api.post(f"/api/v1/studies/GZQO/patients/{B}/mark", json={"mark": "approach"},
                 headers={"Authorization": f"Bearer {tok}"})  # fmt: skip
    assert r.status_code == 200 and r.json()["irb_override"] is None
    assert len(_events(box, "console.approach_override")) == 1
    # an expired approval warns again, and the override says why
    r = crc.post("/studies/GZQO/irb", data={"csrf": _csrf(irb), "approval_no": "IRB-2024-01",
                                            "approved_on": "2024-01-01", "expires_on": "2025-01-01",
                                            "icf_version": "v2.0", "reason": "the older approval was the one in force"},
                 follow_redirects=False)  # fmt: skip
    assert r.status_code == 303  # D-380 (ROLE-015): a change needs its approval number and a reason
    pi.post(f"/studies/GZQO/patients/{A}/mark", data={"csrf": _csrf(wk), "mark": "approach"})
    assert _events(box, "console.approach_override")[-1]["detail"]["reason"] == "irb_expired"
    log = crc.get("/studies/GZQO/screening-log").text
    assert 'data-testid="override-' in log


# ---------------------------------------------------------------------------------------------- opt-out
def test_opt_out_removes_the_patient_from_lists_pages_and_exports(box: dict[str, Any]) -> None:
    _done_screen(box["backend"], _ulid(970 + 1))
    pi = _user(box, "drsato", "investigator")
    name_pi(box, "drsato")  # D-380 (ROLE-008): the steward names the PI
    crc = _user(box, "crc1", "coordinator")
    wk = pi.get("/studies/GZQO/week?list=all").text
    pi.post(f"/studies/GZQO/patients/{B}/mark", data={"csrf": _csrf(wk), "mark": "need_info"})
    crc.post(f"/studies/GZQO/patients/{B}/outcome", data={"csrf": _csrf(wk), "outcome": "not_reached"})
    assert pi.get("/site/opt-outs").status_code == 403  # D-380 (ROLE-005): kept by the steward or privacy office
    assert crc.get("/site/opt-outs").status_code == 403
    stw = _user(box, "stw", "steward")
    op = stw.get("/site/opt-outs").text
    r = stw.post("/site/opt-outs", data={"csrf": _csrf(op), "pid": B, "source": "paper"}, follow_redirects=True)
    assert r.status_code == 200 and 'data-testid="optout-bbbbbbbb"' in r.text
    gone = _events(box, "console.opt_out")
    assert len(gone) == 1 and gone[0]["detail"]["pid"] == B and gone[0]["actor"] == "console:stw"
    assert 'data-testid="row-bbbbbbbb"' not in pi.get("/studies/GZQO/week?list=all").text
    cand = pi.get("/studies/GZQO/candidates").text
    assert 'data-testid="cand-bbbbbbbb"' not in cand and 'data-testid="optout-count"' in cand
    assert pi.get(f"/studies/GZQO/patients/{B}").status_code == 404
    assert pi.get(f"/studies/GZQO/candidates/{B}?purpose=eligibility").status_code == 404
    assert "bbbbbbbb" not in crc.get("/studies/GZQO/screening-log").text
    assert B not in crc.get("/studies/GZQO/screening-log.xlsx").content.decode("latin-1")
    api = TestClient(box["app"])
    tok = api.post("/api/v1/session", json={"username": "drsato", "password": PW}).json()["token"]
    hdr = {"Authorization": f"Bearer {tok}"}
    assert B not in {p["pid"] for p in api.get("/api/v1/studies/GZQO/patients", headers=hdr).json()["patients"]}
    assert B not in {p["pid"] for p in api.get("/api/v1/studies/GZQO/screening-log", headers=hdr).json()}
    # the patient takes it back: on the lists again
    op = stw.get("/site/opt-outs").text
    stw.post("/site/opt-outs", data={"csrf": _csrf(op), "pid": B, "lift": "1", "note": "the patient took it back"})
    assert 'data-testid="row-bbbbbbbb"' in pi.get("/studies/GZQO/week?list=all").text
    assert [e["detail"]["action"] for e in _events(box, "console.opt_out")] == ["opt_out", "lift"]


def test_orchestrator_screen_drops_opted_out_patients() -> None:
    from orchestrator.scenarios.screen import Scoped, drop_opted_out

    reg = OptOutRegister()
    reg.add(B, "paper", "", "office1", "2026-10-01T00:00:00+00:00")
    audit: list[tuple[str, dict[str, Any]]] = []

    class Ctx:
        class job:  # noqa: N801 - the attribute the scenario reads
            job_id = "J1"
            ruleset = "GZQO"
            received_at = datetime(2026, 10, 2, tzinfo=UTC)

        class orch:  # noqa: N801
            class audit:  # noqa: N801
                @staticmethod
                def append(event: str, **kw: Any) -> None:
                    audit.append((event, kw))

    scoped = [Scoped(A, None, "DR-LIN", "RHEU"), Scoped(B, None, "DR-LIN", "RHEU")]
    assert [s.pid for s in drop_opted_out(Ctx(), scoped)] == [A]  # type: ignore[arg-type]
    assert audit == [("screen.opt_out_removed", {"job_id": "J1", "ruleset": "GZQO",
                                                 "detail": {"removed": 1, "register": "optout"}})]  # fmt: skip
    Ctx.job.received_at = datetime(2026, 9, 30, tzinfo=UTC)  # a re-run of a job received before the opt-out
    assert [s.pid for s in drop_opted_out(Ctx(), scoped)] == [A, B]  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------------------- pages and words
def test_team_pages_render_in_three_languages_with_their_strings(box: dict[str, Any]) -> None:
    _done_screen(box["backend"], _ulid(972))
    pi = _user(box, "drsato", "investigator")
    name_pi(box, "drsato")  # D-380 (ROLE-008): the steward names the PI
    crc = _user(box, "crc1", "coordinator")
    stw = _user(box, "stw", "steward")
    for lang in ("en", "ja", "zh-TW"):
        for c in (pi, crc):
            c.post("/lang", data={"csrf": _csrf(c.get("/home").text), "lang": lang, "back": "/home"})
        for path in ("/studies/GZQO/candidates", f"/studies/GZQO/candidates/{A}", "/studies/GZQO/referrals",
                     "/studies/GZQO/team", "/studies/GZQO/irb", "/site/staff"):  # fmt: skip
            r = pi.get(path)
            text = re.sub(r"<[^>]+>", " ", r.text)
            assert r.status_code == 200 and "team." not in text and not re.search(r"\bNone\b", text), (lang, path)
        r = stw.get("/site/opt-outs")  # D-380: the steward's register
        assert r.status_code == 200 and "team." not in re.sub(r"<[^>]+>", " ", r.text), lang
    from console import i18n_team

    assert set(i18n_team.EN) == set(i18n_team.JA) == set(i18n_team.ZH)
    for lang in ("ja", "zh-TW"):
        same = [k for k, v in i18n_team.EN.items() if CATALOGUES[lang][k] == v and not re.fullmatch(r"[A-Z ]+", v)]
        assert same == [], (lang, same)


def test_study_tasks_live_in_the_role_table() -> None:
    """D-147: the delegation rights are rows of tb_common.authz's role table, read with the study's log."""
    from tb_common.authz import ROLE_STUDY_TASKS, STUDY_TASKS, study_tasks

    none: frozenset[str] = frozenset()
    assert study_tasks("investigator", log_names_pi=False, is_pi=True, ticked=none) == none  # D-380 (ROLE-008)
    assert "investigator" not in ROLE_STUDY_TASKS
    assert study_tasks("investigator", log_names_pi=True, is_pi=True, ticked=none) == frozenset(STUDY_TASKS)
    assert study_tasks("investigator", log_names_pi=True, is_pi=False, ticked=frozenset({"refer", "x"})) == {"refer"}
    assert study_tasks("investigator", log_names_pi=True, is_pi=False, ticked=none) == none
    assert study_tasks("coordinator", log_names_pi=True, is_pi=False, ticked=none) == {"screen", "enter_data"}
    assert study_tasks("viewer", log_names_pi=False, is_pi=False, ticked=frozenset(STUDY_TASKS)) == none
    assert study_tasks("cro", log_names_pi=True, is_pi=False, ticked=frozenset(STUDY_TASKS)) == none


def test_candidates_say_whose_patients_the_run_screened(box: dict[str, Any]) -> None:
    """D-146's "Who to screen": the page says whether the run looked at the whole hospital and links the choice."""
    jid = _ulid(973)
    _done_screen(box["backend"], jid)
    pi = _user(box, "drsato", "investigator")
    name_pi(box, "drsato")  # D-380 (ROLE-008): the steward names the PI
    page = pi.get("/studies/GZQO/candidates").text
    assert 'data-testid="scope-pract"' in page and "DR-LIN" in page and "/studies/GZQO/setup#who" in page
    key = next(k for k in box["backend"].objects if k.startswith(f"outputs/{jid}/screen_"))
    summary = json.loads(box["backend"].objects[key])
    summary["scope"] = {"practitioners": [], "whole_hospital": True}
    box["backend"].objects[key] = json.dumps(summary).encode()
    page = pi.get("/studies/GZQO/candidates").text
    assert 'data-testid="scope-hospital"' in page and 'data-testid="scope-pract"' not in page
