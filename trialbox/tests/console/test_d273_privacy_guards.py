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

from tests.console.test_console_app import _done_screen, _ulid, box, login  # noqa: F401 - the fixture by name
from tests.console.test_excluded_page import _with_excluded
from tests.console.test_role_pages import PW, _csrf, _user
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


def _opt_out(b: dict[str, Any], crc: TestClient, pid: str) -> None:
    r = crc.post("/site/opt-outs", data={"csrf": _csrf(crc.get("/site/opt-outs").text), "pid": pid},
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
                 "/pilot/registry/GZQO", "/pilot/registry/GZQO/export.xlsx"):  # fmt: skip
        assert pi.get(path).status_code == 200, path
    assert sum(1 for e in _events(box, "console.denied") if e["actor"] == "console:drkato") >= len(pages)
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
    admin, csrf = login(box["app"])
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
    assert crc.get("/pilot/registry/GZQO/export.xlsx").status_code == 200
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
    crc = _user(box, "crc1", "coordinator")
    r = crc.post("/site/opt-outs", data={"csrf": _csrf(crc.get("/site/opt-outs").text), "chart_no": "SYN-0001"},
                 follow_redirects=False)  # fmt: skip
    assert r.status_code == 303 and "p=" not in r.headers["location"] and "bbbbbbbb" not in r.headers["location"]
    page = crc.get(r.headers["location"]).text
    assert 'data-testid="optout-done"' in page
    api, hdr = _api(box, "crc1")
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
    crc = _user(box, "crc1", "coordinator")
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
    with pytest.raises(OSError):
        crc.post("/site/opt-outs", data={"csrf": _csrf(crc.get("/site/opt-outs").text), "pid": B})
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
