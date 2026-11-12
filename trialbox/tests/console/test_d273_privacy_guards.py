"""D-273, fix group "console privacy guards" (TB-REG-01 CR-017 to CR-022, CR-055; PV-2 to PV-7, PV-15; ROLE-016).

The delegation log and the opt-out register are applied on the sibling pages too; the job page reveals through the
one guarded path; the opt-out door gives no pseudonym back and caps chart-number lookups; the assistant's "why"
answer checks delegation and opt-out and is audited; a mark, a screening number or an opt-out is never kept without
its audit event. Synthetic pseudonyms and chart numbers only."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest
from console.backend import Unavailable
from fastapi.testclient import TestClient
from tb_common.optout import OptOutRegister
from tb_contracts import RegistryUpdate

from tests.console.test_console_app import _done_screen, _ulid, box, login, name_pi  # noqa: F401 - the fixture by name
from tests.console.test_excluded_page import _with_excluded
from tests.console.test_role_pages import PW, _csrf, _user
from tests.console.test_site_setup_pages import KEY as SITE_KEY
from tests.console.test_site_setup_pages import PW as SITE_PW
from tests.console.test_site_setup_pages import sb  # noqa: F401 - the fixture by name
from tests.console.test_team_pages import _log_pi_and_sub

A, B, C = "a" * 32, "b" * 32, "c" * 32


def _events(b: dict[str, Any], name: str) -> list[dict[str, Any]]:
    out = []
    for f in sorted((b["dir"] / "audit").glob("*")):
        for line in f.read_text().splitlines():
            if line and json.loads(line).get("event") == name:
                out.append(json.loads(line))
    return out


def _api(b: dict[str, Any], user: str) -> tuple[TestClient, dict[str, str]]:
    api = TestClient(b["app"])
    tok = api.post("/api/v1/session", json={"username": user, "password": PW}).json()["token"]
    return api, {"Authorization": f"Bearer {tok}"}


def _steward(b: dict[str, Any]) -> TestClient:
    """D-380 (ROLE-005): the opt-out register is kept by the steward (or the privacy office) only."""
    if b["users"].get("stw") is None:
        b["users"].create("stw", "steward", PW, "stw@hospa.test")
    return login(b["app"], "stw", PW)[0]


def _opt_out(b: dict[str, Any], crc: TestClient, pid: str) -> None:
    stw = _steward(b)  # D-380: no longer the coordinator (``crc`` kept for the callers)
    r = stw.post("/site/opt-outs", data={"csrf": _csrf(stw.get("/site/opt-outs").text), "pid": pid},
                 follow_redirects=False)  # fmt: skip
    assert r.status_code == 303


# ---------------------------------------------------------------------------------------------- CR-018 (PV-3)
def test_the_delegation_rule_holds_on_the_sibling_pages(box: dict[str, Any]) -> None:  # noqa: F811
    jid = _with_excluded(box)
    pi = _user(box, "drsato", "investigator")
    sub = _user(box, "drkato", "investigator")
    _log_pi_and_sub(box, pi, ("refer",))  # the sub-investigator is not ticked "screen"
    box["backend"].registry_update("GZQO", RegistryUpdate(pid=A, status="candidate", by="crc1"))
    pages = ("/studies/GZQO/excluded", "/studies/GZQO/screening-log", "/studies/GZQO/cohort",
             "/studies/GZQO/subjects", "/studies/GZQO/entry", "/pilot/registry/GZQO",
             "/pilot/registry/GZQO/export.xlsx")  # fmt: skip
    for path in pages:
        assert sub.get(path).status_code == 403, path
    for path in ("/studies/GZQO/excluded", "/studies/GZQO/screening-log", "/studies/GZQO/cohort",
                 "/pilot/registry/GZQO", "/pilot/registry/GZQO/export.xlsx?reason=contact"):  # fmt: skip
        assert pi.get(path).status_code == 200, path
    # one refusal record per page: ``console.denied``, or for the export (a reveal since T-103, D-438) the one
    # path's ``console.reveal_refused`` (delegation)
    refusals = _events(box, "console.denied") + _events(box, "console.reveal_refused")
    assert sum(1 for e in refusals if e["actor"] == "console:drkato") >= len(pages)
    assert [e["detail"]["refused"] for e in _events(box, "console.reveal_refused")] == ["delegation"]
    # the job page shows the summary to the sub-investigator, not the patient rows
    assert 'data-testid="screen-rows"' not in sub.get(f"/pilot/jobs/{jid}").text
    assert 'data-testid="screen-rows"' in pi.get(f"/pilot/jobs/{jid}").text
    # /api/v1 as the page
    api, hdr = _api(box, "drkato")
    assert api.get("/api/v1/studies/GZQO/patients", headers=hdr).status_code == 403
    assert api.get("/api/v1/studies/GZQO/screening-log", headers=hdr).status_code == 403
    api, hdr = _api(box, "drsato")
    assert api.get("/api/v1/studies/GZQO/patients", headers=hdr).status_code == 200
    # N1: the sub-investigator's morning mail carries no row of the study
    from console import notify

    notices = notify.collect(box["app"].state.helpers, date(2026, 11, 10), ("N1",))
    assert not any(n.username == "drkato" and "aaaaaaaa" in n.body for n in notices)


def test_a_sub_investigator_ticked_for_data_entry_reads_the_participants(box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(981))
    pi = _user(box, "drsato", "investigator")
    sub = _user(box, "drkato", "investigator")
    _log_pi_and_sub(box, pi, ("enter_data",))
    assert sub.get("/studies/GZQO/subjects").status_code != 403
    assert sub.get("/studies/GZQO/excluded").status_code == 403  # not ticked "screen"


# ---------------------------------------------------------------------------------------------- CR-019 (PV-4)
def test_an_opted_out_patient_leaves_the_job_page_registry_and_excluded_list(box: dict[str, Any]) -> None:  # noqa: F811
    jid = _with_excluded(box)
    crc = _user(box, "crc1", "coordinator")
    admin = _user(box, "crc2", "coordinator")  # D-280 (OD-5): a patient-level reader is no longer the administrator
    csrf = _csrf(admin.get("/home").text)
    box["backend"].registry_update("GZQO", RegistryUpdate(pid=B, status="candidate", by="crc1"))
    assert "bbbbbbbb" in admin.get("/pilot/registry/GZQO").text
    assert admin.get(f"/pilot/jobs/{jid}").text.count("<tr data-pid=") == 2
    assert 'data-testid="ex-cccccccc"' in admin.get("/studies/GZQO/excluded").text
    _opt_out(box, crc, B)
    _opt_out(box, crc, C)
    page = admin.get(f"/pilot/jobs/{jid}").text
    assert page.count("<tr data-pid=") == 1 and f'data-pid="{B}"' not in page
    assert 'data-testid="optout-removed"' in page  # only the count
    assert "bbbbbbbb" not in admin.get("/pilot/registry/GZQO").text
    assert 'data-testid="ex-cccccccc"' not in admin.get("/studies/GZQO/excluded").text
    # the old job page cannot reveal the patient either (CR-017: one reveal path, the latest list only)
    r = admin.post(f"/pilot/jobs/{jid}/reveal", data={"csrf": csrf, "pid": B, "reason": "contact"})
    assert r.status_code == 404 and box["backend"].revealed == []


# ---------------------------------------------------------------------------------------------- CR-017 (PV-2)
def test_the_job_reveal_follows_the_delegation_log(box: dict[str, Any]) -> None:  # noqa: F811
    jid = _with_excluded(box)
    pi = _user(box, "drsato", "investigator")
    sub = _user(box, "drkato", "investigator")
    _log_pi_and_sub(box, pi, ("refer",))
    form = {"csrf": _csrf(sub.get("/home").text), "pid": A, "reason": "contact"}
    assert sub.post(f"/pilot/jobs/{jid}/reveal", data=form).status_code == 403
    assert box["backend"].revealed == []
    form["csrf"] = _csrf(pi.get("/home").text)
    r = pi.post(f"/pilot/jobs/{jid}/reveal", data=form)
    assert r.status_code == 200 and "MRN-000123" in r.text
    assert box["backend"].signed == [("reveal", "investigator", "*")]
    ev = _events(box, "console.reveal_patient")
    assert len(ev) == 1 and ev[0]["detail"]["via"] == "job" and ev[0]["detail"]["reason"] == "contact"


# ---------------------------------------------------------------------------------------------- CR-020 (PV-5)
def test_the_registry_export_is_audited_first_and_signed_with_role_and_studies(box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(982))
    crc = _user(box, "crc1", "coordinator", studies="GZQO")
    assert crc.get("/pilot/registry/GZQO/export.xlsx?reason=contact").status_code == 200
    assert box["backend"].signed == [("export", "coordinator", "GZQO")]
    kinds = [e["detail"]["action"] for e in _events(box, "console.registry")]
    assert kinds == ["export_requested", "export"]


# ---------------------------------------------------------------------------------------------- CR-021 (PV-6)
def test_the_opt_out_door_gives_no_pseudonym_back_and_caps_chart_lookups(
    box: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def study_api(method: str, path: str, body: dict[str, Any] | None = None, **_: Any) -> Any:
        if path == "/setup/pseudonym":
            return {"pid": B}
        raise Unavailable("no study store in this test")

    monkeypatch.setattr(box["backend"], "study_api", study_api, raising=False)
    crc = _user(box, "dpo1", "privacy")  # D-380 (ROLE-005): the privacy office keeps the register
    r = crc.post("/site/opt-outs", data={"csrf": _csrf(crc.get("/site/opt-outs").text), "chart_no": "SYN-0001"},
                 follow_redirects=False)  # fmt: skip
    assert r.status_code == 303 and "p=" not in r.headers["location"] and "bbbbbbbb" not in r.headers["location"]
    page = crc.get(r.headers["location"]).text
    assert 'data-testid="optout-done"' in page
    api, hdr = _api(box, "dpo1")
    out = api.post("/api/v1/site/opt-outs", json={"chart_no": "SYN-0002"}, headers=hdr)
    assert out.status_code == 200 and out.json() == {"opted_out": True, "changed": False}  # no pid, even unchanged
    lookups = _events(box, "console.chart_lookup")
    assert len(lookups) == 2 and lookups[-1]["detail"]["pid"] == B  # each lookup is its own audit event
    for i in range(3, 31):
        assert api.post("/api/v1/site/opt-outs", json={"chart_no": f"SYN-{i:04d}"}, headers=hdr).status_code == 200
    r = api.post("/api/v1/site/opt-outs", json={"chart_no": "SYN-0031"}, headers=hdr)
    assert r.status_code == 429
    assert [e["detail"]["action"] for e in _events(box, "console.rate_limited")] == ["chart_lookup"]
    assert len(_events(box, "console.chart_lookup")) == 30
    # a pseudonym typed by the steward is no lookup and is not capped
    assert api.post("/api/v1/site/opt-outs", json={"pid": A}, headers=hdr).status_code == 200


# ---------------------------------------------------------------------------------------------- CR-022 (PV-7)
def test_the_why_answer_checks_delegation_and_opt_out_and_is_audited(box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(983))
    pi = _user(box, "drsato", "investigator")
    sub = _user(box, "drkato", "investigator")
    crc = _user(box, "crc1", "coordinator")
    _log_pi_and_sub(box, pi, ("refer",))
    q = {"pid": A, "q": "why is this patient on the list", "study": "GZQO"}
    assert pi.get("/ask", params=q).status_code == 200
    asked = _events(box, "console.ask_patient")
    assert len(asked) == 1 and asked[0]["detail"]["pid"] == A and asked[0]["actor"] == "console:drsato"
    assert sub.get("/ask", params=q).status_code == 200
    assert len(_events(box, "console.ask_patient")) == 1  # not delegated: no answer about the patient
    assert any(e["detail"]["action"] == "ask why" for e in _events(box, "console.denied"))
    _opt_out(box, crc, A)
    assert pi.get("/ask", params=q).status_code == 200
    assert len(_events(box, "console.ask_patient")) == 1  # opted out: never answered


# ---------------------------------------------------------------------------------------------- CR-055 (DI-5)
def test_no_mark_number_or_opt_out_is_kept_without_its_audit_event(
    box: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _done_screen(box["backend"], _ulid(984))
    pi = _user(box, "drsato", "investigator")
    name_pi(box, "drsato")  # D-380 (ROLE-008): the steward names the PI
    _user(box, "crc1", "coordinator")
    store = box["app"].state.helpers.store
    real = box["audit"].append

    def failing(event: str, **kw: Any) -> Any:
        if event in ("console.pi_mark", "console.opt_out"):
            raise OSError("no space left on the audit volume")
        return real(event, **kw)

    monkeypatch.setattr(box["audit"], "append", failing)
    wk = pi.get("/studies/GZQO/week?list=all").text
    with pytest.raises(OSError):
        pi.post(f"/studies/GZQO/patients/{A}/mark", data={"csrf": _csrf(wk), "mark": "approach"})
    assert A not in store.latest_marks("GZQO") and store.screening_no("GZQO", A) is None
    stw = _steward(box)  # D-380 (ROLE-005): the steward keeps the register
    with pytest.raises(OSError):
        stw.post("/site/opt-outs", data={"csrf": _csrf(stw.get("/site/opt-outs").text), "pid": B})
    assert B not in OptOutRegister().active()
    monkeypatch.setattr(box["audit"], "append", real)
    r = pi.post(f"/studies/GZQO/patients/{A}/mark", data={"csrf": _csrf(wk), "mark": "approach"},
                follow_redirects=False)  # fmt: skip
    assert r.status_code == 303 and store.latest_marks("GZQO")[A].mark == "approach"
    ev = _events(box, "console.pi_mark")
    assert len(ev) == 1 and ev[0]["detail"]["to"] == store.screening_no("GZQO", A)


# ---------------------------------------------------------------------------------------------- ROLE-016
def test_a_reveal_for_other_needs_a_written_reason(box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(985))
    crc = _user(box, "crc1", "coordinator")
    page = crc.get(f"/studies/GZQO/patients/{A}").text
    assert 'data-testid="reveal-note"' in page
    form = {"csrf": _csrf(page), "reason": "other", "note": "  too   short "}
    assert crc.post(f"/studies/GZQO/patients/{A}/reveal", data=form).status_code == 400
    form["note"] = "monitor asked to check the source chart"
    r = crc.post(f"/studies/GZQO/patients/{A}/reveal", data=form)
    assert r.status_code == 200 and "MRN-000123" in r.text
    ev = _events(box, "console.reveal_patient")
    assert len(ev) == 1 and ev[0]["detail"]["note"] == "monitor asked to check the source chart"
    api, hdr = _api(box, "crc1")
    r = api.post(f"/api/v1/studies/GZQO/patients/{A}/reveal", json={"reason": "other"}, headers=hdr)
    assert r.status_code == 400


# ---------------------------------------------------------------------------------------------- review of #108
def test_a_pasted_chart_gives_no_pseudonym_back_and_counts_as_a_chart_lookup(
    box: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def study_api(method: str, path: str, body: dict[str, Any] | None = None, **_: Any) -> Any:
        calls.append(path)
        if path == "/setup/main/charts":
            return {"input": len(calls), "pid": B, "facts": 2}
        if path == "/setup/pseudonym":
            return {"pid": B}
        raise Unavailable("no study store in this test")

    monkeypatch.setattr(box["backend"], "study_api", study_api, raising=False)
    _user(box, "crc1", "coordinator")
    api, hdr = _api(box, "crc1")
    out = api.post("/api/v1/site/charts", json={"chart_no": "SYN-0001", "text": "synthetic note"}, headers=hdr)
    assert out.status_code == 200 and "pid" not in out.json() and B not in out.text
    ev = _events(box, "console.chart_lookup")
    assert len(ev) == 1 and ev[0]["detail"]["for"] == "chart" and ev[0]["actor"] == "console:crc1"
    # the pasted chart counts on the chart-lookup cap (30 an hour; the opt-out door shares it, but since D-380 the
    # door is the steward's and the privacy office's, so a coordinator reaches the cap through the charts)
    for i in range(2, 31):
        r = api.post("/api/v1/site/charts", json={"chart_no": f"SYN-{i:04d}", "text": "synthetic note"}, headers=hdr)
        assert r.status_code == 200
    n = len(calls)
    r = api.post("/api/v1/site/charts", json={"chart_no": "SYN-0031", "text": "synthetic note"}, headers=hdr)
    assert r.status_code == 429 and len(calls) == n  # refused before the box is asked
    assert [e["detail"]["action"] for e in _events(box, "console.rate_limited")] == ["chart_lookup"]


def test_the_conflicts_page_follows_the_delegation_log(box: dict[str, Any]) -> None:  # noqa: F811
    _done_screen(box["backend"], _ulid(986))
    pi = _user(box, "drsato", "investigator")
    sub = _user(box, "drkato", "investigator")
    _log_pi_and_sub(box, pi, ("refer",))  # neither "screen" nor "enter_data"
    assert sub.get("/studies/GZQO/conflicts").status_code == 403
    api, hdr = _api(box, "drkato")
    assert api.get("/api/v1/studies/GZQO/conflicts", headers=hdr).status_code == 403
    assert any(e["detail"]["action"] == "conflicts GZQO" for e in _events(box, "console.denied"))
    assert pi.get("/studies/GZQO/conflicts").status_code != 403


def test_an_opted_out_patients_chart_number_stays_masked_in_the_job_thread(box: dict[str, Any]) -> None:  # noqa: F811
    from tests.console.test_console_app import _done_case

    job = _done_case(box["backend"], {"mrn": "70000054", "lang": "en"})
    box["audit"].append("console.request", job_id=job.job_id, ruleset="GZQO", actor="console:admin",
                        detail={"line": "CASE GZQO mrn=••• lang=en", "channel": "web"})  # fmt: skip
    admin = _user(box, "crc2", "coordinator")  # D-280 (OD-5): the reader is a coordinator, not the administrator
    assert "mrn=70000054" in admin.get(f"/pilot/jobs/{job.job_id}").text
    _opt_out(box, _user(box, "crc1", "coordinator"), "ab" * 16)  # the CASE subject's pseudonym
    page = admin.get(f"/pilot/jobs/{job.job_id}").text
    assert "70000054" not in page and "mrn=•••" in page
    lines = [r for r in box["backend"].audit(job.job_id)
             if r.event == "console.reveal_patient" and r.detail.get("via") == "request_line"]  # fmt: skip
    assert len(lines) == 1  # T-103 (D-438): the one record shape


def test_the_lookup_cap_records_before_it_counts(box: dict[str, Any]) -> None:  # noqa: F811
    team = box["app"].state.helpers.team
    now, since = "2026-11-10T09:00:00+00:00", "2026-11-10T08:00:00+00:00"
    assert team.take("-", "-", "chart", "chart_lookup", "crc1", now, since, 2)
    assert team.take("-", "-", "chart", "chart_lookup", "crc1", now, since, 2)
    assert not team.take("-", "-", "chart", "chart_lookup", "crc1", now, since, 2)  # the third is over
    assert team.count_views("crc1", "chart_lookup", since) == 2  # a refused use is not recorded
    assert team.take("-", "-", "chart", "chart_lookup", "crc2", now, since, 2)  # per person


def test_the_job_reveal_has_no_preselected_reason(box: dict[str, Any]) -> None:  # noqa: F811
    jid = _with_excluded(box)
    admin = _user(box, "crc2", "coordinator")  # D-280 (OD-5): the reveal form is a coordinator's, not the admin's
    page = admin.get(f"/pilot/jobs/{jid}").text
    csrf = _csrf(page)
    assert '<select name="reason" required data-testid="reveal-reason"><option value="">' in page
    r = admin.post(f"/pilot/jobs/{jid}/reveal", data={"csrf": csrf, "pid": A, "reason": ""})
    assert r.status_code == 400 and box["backend"].revealed == []


# ---------------------------------------------------------------------------------------------- follow-up review
def _verdicts(pid: str) -> dict[str, Any]:
    return {"pid": pid, "short": pid[:8], "state": "needs",
            "criteria": [{"id": "I1", "kind": "inclusion", "label": "urate", "verdict": "met", "reason": "",
                          "facts": []}]}  # fmt: skip


def test_the_site_patient_check_follows_the_delegation_log_and_the_opt_out_register(
    box: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def study_api(method: str, path: str, body: dict[str, Any] | None = None, **_: Any) -> Any:
        if path.startswith("/setup/main/patients"):
            return {"approved": True, "patients": [_verdicts(A), _verdicts(B)]}
        raise Unavailable("no study store in this test")

    monkeypatch.setattr(box["backend"], "study_api", study_api, raising=False)
    _done_screen(box["backend"], _ulid(987))
    pi = _user(box, "drsato", "investigator")
    sub = _user(box, "drkato", "investigator")
    crc = _user(box, "crc1", "coordinator")
    _log_pi_and_sub(box, pi, ("refer",))
    assert sub.get("/site/patients?study=GZQO").status_code == 403  # refused here as at /ask
    assert any(e["detail"]["action"] == "/site/patients" for e in _events(box, "console.denied"))
    page = pi.get("/site/patients?study=GZQO").text
    assert 'data-testid="pc-aaaaaaaa"' in page and 'data-testid="pc-bbbbbbbb"' in page
    _opt_out(box, crc, B)
    page = pi.get("/site/patients?study=GZQO").text
    assert 'data-testid="pc-aaaaaaaa"' in page and "bbbbbbbb" not in page
    seen = _events(box, "console.site_patients")
    assert len(seen) == 2 and seen[-1]["actor"] == "console:drsato" and seen[-1]["detail"]["patients"] == 1


def test_the_site_facts_and_people_leave_out_opted_out_patients_and_the_api_gives_no_pseudonym(
    sb: dict[str, Any],  # noqa: F811
) -> None:
    from sitesetup import help as site_help
    from tb_common.crypto import pid_for_mrn

    crc, _ = login(sb["app"], "crc", SITE_PW)
    api = TestClient(sb["app"])
    api.headers["Authorization"] = (
        "Bearer " + api.post("/api/v1/session", json={"username": "crc", "password": SITE_PW}).json()["token"]
    )
    no, text = site_help.PRACTICE_CHARTS[0]
    assert api.post("/api/v1/site/charts", json={"chart_no": no, "text": text}).status_code == 200
    pid = pid_for_mrn(SITE_KEY, no)
    facts = api.get("/api/v1/site/facts").json()
    assert facts and all("pid" not in f and f["short"] == pid[:8] for f in facts)
    assert pid not in json.dumps(facts)
    assert pid[:8] in crc.get("/site/facts?study=GZQO").text
    assert f'data-testid="person-{pid[:8]}"' in crc.get("/site/people?study=GZQO").text
    _opt_out(sb, crc, pid)
    assert api.get("/api/v1/site/facts").json() == []
    assert pid[:8] not in crc.get("/site/facts?study=GZQO").text
    assert f'data-testid="person-{pid[:8]}"' not in crc.get("/site/people?study=GZQO").text


def test_a_running_case_job_masks_an_opted_out_subjects_chart_number(
    box: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime

    from tb_contracts import Job

    asked: list[dict[str, Any]] = []
    answer: dict[str, Any] = {"pid": "ab" * 16}

    def study_api(method: str, path: str, body: dict[str, Any] | None = None, **_: Any) -> Any:
        if path == "/setup/pseudonym":
            asked.append(dict(body or {}))
            if not answer:
                raise Unavailable("the box is down")
            return answer
        raise Unavailable("no study store in this test")

    monkeypatch.setattr(box["backend"], "study_api", study_api, raising=False)
    now = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
    job = box["backend"].add_job(Job(job_id=_ulid(988), type="CASE", ruleset="GZQO", ruleset_version="1.0.0",
                                     requested_by="admin@hospa.test", received_at=now, updated_at=now,
                                     state="running", options={"mrn": "70000054", "lang": "en"}, inputs=[],
                                     outputs=[]))  # fmt: skip
    box["audit"].append("console.request", job_id=job.job_id, ruleset="GZQO", actor="console:admin",
                        detail={"line": "CASE GZQO mrn=••• lang=en", "channel": "web"})  # fmt: skip
    admin = _user(box, "crc2", "coordinator")  # D-280 (OD-5): the reader is a coordinator, not the administrator
    assert "mrn=70000054" in admin.get(f"/pilot/jobs/{job.job_id}").text
    assert asked == []  # nobody on the register: no lookup at all
    _opt_out(box, _user(box, "crc1", "coordinator"), "cd" * 16)  # someone else
    assert "mrn=70000054" in admin.get(f"/pilot/jobs/{job.job_id}").text
    assert asked == [{"chart_no": "70000054"}]
    crc, _ = login(box["app"], "crc1", PW)
    _opt_out(box, crc, "ab" * 16)  # the subject
    page = admin.get(f"/pilot/jobs/{job.job_id}").text
    assert "70000054" not in page and "mrn=•••" in page
    answer.clear()  # the box cannot answer: the line stays masked
    assert "70000054" not in admin.get(f"/pilot/jobs/{job.job_id}").text
