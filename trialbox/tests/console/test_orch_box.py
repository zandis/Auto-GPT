"""T-714 (D-482; trust review TR-7, plan v6.1 §5.3): the console's reveal, export and job calls against the real
orchestrator.

The console app runs on its real backend (``console.backend.HttpBackend``), bound to the real orchestrator app in
the production trust configuration (``tests/orch_box.py``): a token registry, the console's own token, the actor
keys. What the console signs is checked by the route that checks it on a box, so a console that signs the wrong
role, the wrong studies or nothing fails here. The acceptance of T-714 (dropping ``scope=`` from the console's
reveal call fails a console test) is, since T-716 made the reveal a v3 claim, the first case of
``test_a_console_that_signs_something_else_gets_no_chart_number``: the study dropped from the claim.
Synthetic patients only.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
from console.app import create_app
from console.auth import UserStore
from console.backend import Refused
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from tb_common import service_auth as sa
from tb_contracts import JobCreate, RegistryPromote

from tests.actor3 import reveal_headers, signer
from tests.console.test_console_app import ADMIN_PW, CRC_PW, PILOT_ENV, VIEWER_PW, login
from tests.orch_box import STUDY, OrchBox


@pytest.fixture
def site(orch_box: OrchBox, tmp_path: Path) -> dict[str, Any]:
    """The console of the box: its real backend, the box's audit chain, a coordinator, a viewer, an administrator."""
    users = UserStore()
    users.create("admin", "admin", ADMIN_PW, "admin@hospa.test")
    users.create("crc", "coordinator", CRC_PW, "crc1@hospa.test")
    users.create("viewer", "viewer", VIEWER_PW)
    backend = orch_box.backend()
    env = {**PILOT_ENV, "TB_CONSOLE_DIR": str(tmp_path / "console")}
    app = create_app(env, backend=backend, audit=orch_box.box.orch.audit, users=users)
    return {"app": app, "backend": backend, "users": users, "ob": orch_box}


def _reveal(site: dict[str, Any], pid: str, reason: str = "contact") -> Any:
    c, csrf = login(site["app"], "crc", CRC_PW)
    job = site["ob"].screen()
    return c.post(f"/pilot/jobs/{job.job_id}/reveal", data={"csrf": csrf, "pid": pid, "reason": reason})


# ------------------------------------------------------------------------------------------------------- reveal
def test_a_coordinator_reveals_a_listed_patient(site: dict[str, Any]) -> None:
    """The whole path: the page, the console's rule, its signed assertion, the orchestrator's checks, the pid map."""
    ob: OrchBox = site["ob"]
    job, pid = ob.screen(), ob.listed()[0]
    r = _reveal(site, pid)
    assert r.status_code == 200, r.text[-400:]
    assert 'data-testid="mrn"' in r.text and ob.mrn[pid] in r.text  # the patient's own chart number, from the map
    given = ob.events("screen.reveal")
    assert len(given) == 1 and given[0]["actor"] == "console:crc" and given[0]["job_id"] == job.job_id
    assert given[0]["detail"] | {"session": ""} == {
        "pid": pid, "found": True, "session": "", "verified": True, "role": "coordinator",
        "purpose": "screening_list", "reason": "contact",
    }  # fmt: skip
    assert given[0]["detail"]["session"]  # the console session the person signed in with
    shown = ob.events("console.reveal_patient")
    assert len(shown) == 1 and shown[0]["actor"] == "console:crc" and shown[0]["detail"]["via"] == "job"
    assert not ob.events("screen.reveal_refused") and not ob.events("actor.refused")


def _drop_in_backend(monkeypatch: pytest.MonkeyPatch, site: dict[str, Any], field: str) -> None:
    """A ``console.backend.HttpBackend`` call of the older assertion (export, jobs) without ``field=`` in its
    ``actor_header`` call."""
    from console import backend as cb

    real = sa.actor_header
    monkeypatch.setattr(
        cb, "actor_header", lambda name, *a, **kw: real(name, *a, **{k: v for k, v in kw.items() if k != field})
    )


def _mint_with(monkeypatch: pytest.MonkeyPatch, **change: Any) -> None:
    """The console's one minting place signing something else than it should (T-716: the reveal is a v3 claim)."""
    from tb_common import actor_v3

    real = actor_v3.mint
    monkeypatch.setattr(actor_v3, "mint", lambda **kw: real(**{**kw, **change}))  # console.actor calls this


@pytest.mark.parametrize(
    ("change", "event", "why"),
    [
        ({"study": ""}, "screen.reveal_refused", "study scope"),  # T-714's acceptance, in v3: the study dropped
        ({"study": "OTHER"}, "screen.reveal_refused", "study scope"),
        ({"role": "viewer"}, "actor.refused", "right"),
        ({"action": "phi.view"}, "actor.refused", "action"),
        ({"path": "/jobs/another-job/reveal"}, "actor.refused", "request"),
        ({"body": {"pid": "f" * 32}}, "actor.refused", "body"),
    ],
    ids=["no study", "another study", "another role", "another action", "another job", "another patient"],
)
def test_a_console_that_signs_something_else_gets_no_chart_number(
    site: dict[str, Any], monkeypatch: pytest.MonkeyPatch, change: dict[str, Any], event: str, why: str
) -> None:
    """Whatever the console's claim gets wrong, the real route refuses, the page shows no chart number, and the
    refusal is on the orchestrator's record."""
    ob: OrchBox = site["ob"]
    pid = ob.listed()[0]
    _mint_with(monkeypatch, **change)
    r = _reveal(site, pid)
    assert r.status_code == 409 and ob.mrn[pid] not in r.text
    assert not ob.events("screen.reveal") and not ob.events("console.reveal_patient")
    refused = ob.events(event)
    assert len(refused) == 1 and refused[0]["detail"]["reason"] == why and refused[0]["actor"] == "console:crc"
    assert ob.events("console.reveal_refused")[-1]["detail"]["refused"] == "back end"


def test_the_orchestrator_refuses_what_the_console_did_not_check(site: dict[str, Any]) -> None:
    """Each refusal of the real route reaches the console's backend as ``Refused`` (never a chart number, never a
    crash): another study, a role without identifier authority, a patient the job did not list, a patient who opted
    out since. And the route itself answers only the console."""
    from tb_common.optout import OptOutRegister

    ob: OrchBox = site["ob"]
    bk, job, pids = site["backend"], ob.screen(), ob.listed()
    for sign, why in (
        (signer("OTHER"), "study scope"),
        (signer(""), "study scope"),
        (signer(STUDY, role="viewer"), "right"),
        (signer(STUDY, role="admin"), "right"),
        (signer(STUDY, role="breakglass"), "right"),  # T-716: the word is no role
        (signer(STUDY, role="investigator", sub="console:dr"), "delegation"),  # the log names no such PI
    ):
        with pytest.raises(Refused, match=why):
            bk.reveal(job.job_id, pids[0], sign, purpose="patient")
    unlisted = next(p for p in ob.mrn if p not in pids)
    with pytest.raises(Refused, match="not on this job's list"):
        bk.reveal(job.job_id, unlisted, signer(STUDY))
    register = OptOutRegister()
    register.add(pids[1], "patient", "asked at the desk", "console:stw", "2026-10-05T09:00:00+08:00")
    register.close()
    with pytest.raises(Refused, match="opted out"):
        bk.reveal(job.job_id, pids[1], signer(STUDY))
    assert not ob.events("screen.reveal")
    # the same call from another service's token, and with a token that signs nothing
    body = {"pid": pids[0]}
    r = ob.client("mail-gateway").post(
        f"/jobs/{job.job_id}/reveal", json=body, headers=reveal_headers(STUDY, job.job_id, body)
    )
    assert r.status_code == 403 and "route_not_allowed" in r.text
    r = ob.client(None).post(f"/jobs/{job.job_id}/reveal", json=body, headers=reveal_headers(STUDY, job.job_id, body))
    assert r.status_code == 401
    r = ob.client("console").post(f"/jobs/{job.job_id}/reveal", json={**body, "by": "console:crc"})
    assert r.status_code == 403 and not ob.events("screen.reveal")  # a body field names nobody
    assert bk.reveal(job.job_id, pids[0], signer(STUDY)) == ob.mrn[pids[0]]


# ------------------------------------------------------------------------------------------------------- export
def test_the_screening_log_goes_out_with_chart_numbers_to_a_signed_coordinator_only(
    site: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    ob: OrchBox = site["ob"]
    pids = ob.listed()
    from tests.actor3 import signer

    as_crc = signer(STUDY, action="request.prepare")  # T-715b (D-550): the registry takes its person from this
    assert site["backend"].registry_promote(STUDY, RegistryPromote(by="console:crc"), as_crc) >= 1
    c, _ = login(site["app"], "crc", CRC_PW)
    r = c.get(f"/pilot/registry/{STUDY}/export.xlsx?reason=contact")
    assert r.status_code == 200, r.text[-300:]
    sheet = load_workbook(io.BytesIO(r.content)).worksheets[0]
    cells = {str(v) for row in sheet.iter_rows(values_only=True) for v in row}
    assert ob.mrn[pids[0]] in cells  # real chart numbers, from the orchestrator's own export
    done = ob.events("registry.export")
    assert (
        len(done) == 1
        and done[0]["actor"] == "console:crc"
        and done[0]["detail"] | {"session": ""} == {"session": "", "verified": True, "caller": "console"}
    )  # the record names the verified caller and person; the role is not on it (a finding for T-721)
    v, _ = login(site["app"], "viewer", VIEWER_PW)
    assert v.get(f"/pilot/registry/{STUDY}/export.xlsx?reason=contact").status_code == 403  # the console's own rule
    # and the orchestrator's, for a console that signs less than it should
    bk = site["backend"]
    for kw in ({"role": "coordinator", "scope": "OTHER"}, {"role": "viewer", "scope": STUDY}, {"role": "coordinator"},
               {"role": "breakglass", "scope": "*"}):  # fmt: skip
        with pytest.raises(Refused):
            bk.registry_export(STUDY, "console:crc", **kw)
    assert len(ob.events("registry.export")) == 1 and len(ob.events("registry.export_refused")) == 4
    _drop_in_backend(monkeypatch, site, "scope")
    assert c.get(f"/pilot/registry/{STUDY}/export.xlsx?reason=contact").status_code == 409
    assert len(ob.events("registry.export")) == 1


# --------------------------------------------------------------------------------------------------------- jobs
def test_a_console_job_is_authorised_by_the_signed_role(site: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """D-146: the role in the signed assertion decides, not the mailbox. The real ``Orchestrator.create`` answers."""
    ob: OrchBox = site["ob"]
    bk = site["backend"]
    req = JobCreate(type="FEAS", ruleset=STUDY, requested_by="nobody@hospa.test", options={})
    job = bk.create_job(req, by="console:crc", role="coordinator")  # a mailbox with no rights, a role with them
    assert job.state == "done" and job.type == "FEAS", job.error
    made = [e for e in ob.events("job.state") if e["job_id"] == job.job_id and e["detail"]["to"] == "received"]
    assert made and made[0]["detail"]["by"] == "console:crc" and made[0]["detail"]["role"] == "coordinator"
    with pytest.raises(Refused, match="the viewer role may not run FEAS"):
        bk.create_job(req, by="console:viewer", role="viewer")
    # D-555: the refusal says "this sender", not the address it was sent
    with pytest.raises(Refused, match="this sender is not permitted to run FEAS") as said:
        bk.create_job(req)  # no person: the mailbox rules of the settings
    assert "nobody@hospa.test" not in str(said.value)
    _drop_in_backend(monkeypatch, site, "role")  # a console that loses role= in create_job
    with pytest.raises(Refused, match="this sender is not permitted"):
        bk.create_job(req, by="console:crc", role="coordinator")
    with pytest.raises(Refused, match="internal_principal"):
        bk.create_job(JobCreate(type="FEAS", ruleset=STUDY, requested_by="scheduler", options={}))  # D-464
    assert len([j for j in bk.list_jobs() if j.type == "FEAS"]) == 1


def test_the_box_is_the_production_configuration(orch_box: OrchBox) -> None:
    """What makes the fixture the real boundary: no token is no caller, a foreign service is refused its routes, and
    an assertion signed with another key names nobody."""
    job = orch_box.screen()
    assert orch_box.client(None).get("/jobs").status_code == 401
    assert orch_box.client("console").get("/jobs").status_code == 200
    assert orch_box.client("lake").get("/jobs").status_code == 403
    forged = reveal_headers(STUDY, job.job_id, {"pid": orch_box.listed()[0]})
    head, _, mac = forged[sa.ASSERTION_HEADER].rpartition(".")
    forged[sa.ASSERTION_HEADER] = f"{head}.{'0' * len(mac)}"
    r = orch_box.client("console").post(
        f"/jobs/{job.job_id}/reveal", json={"pid": orch_box.listed()[0]}, headers=forged
    )
    assert r.status_code in (401, 403) and not orch_box.events("screen.reveal")
    assert isinstance(orch_box.client("console"), TestClient)
