"""T-746 (D-474; owner's ruling 2026-11-12 "Admin can retry"): the administrator runs a failed job of the box's own
scheduler again, every type of ``scheduler.plan``, with the failed job's own type, study, options and inputs. The
orchestrator copies them (``POST /jobs/{job_id}/retry``); the console names the job and the reply mailbox only.
A real orchestrator (job store in this test's PostgreSQL schema, no worker), per-service tokens in PRODUCTION, signed
actor assertions. Synthetic data only."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from orchestrator.core import Ctx, NotRetryable, Orchestrator, Outcome, Rejected, Services
from orchestrator.db import JobDB
from orchestrator.scheduler import scheduled_types
from tb_common import service_auth as sa
from tb_common.audit import AuditLog
from tb_common.config import Config, load_env, load_settings
from tb_common.objstore import FsStore
from tb_contracts import Job, JobCreate, JobError, JobFile

from tests.service_tokens import per_service_tokens, token_of

ROOT = Path(__file__).resolve().parents[2]
ADMIN_MAIL = "admin@hospa.test"
BOX_WIDE = ("INGEST", "RETENTION")  # the scheduler starts these for no study


class FakeMail:
    def send(self, req: Any) -> Any:
        from tb_contracts import SendResult

        return SendResult(message_id="<1@t>", sent_to=req.to, encrypted=bool(req.encrypt))


def _noop(ctx: Ctx) -> Outcome:
    return Outcome(summary_md="ok")


def _ruleset(jtype: str) -> str | None:
    return None if jtype in BOX_WIDE else "GZQO"


@pytest.fixture
def orch(tmp_path: Path) -> Orchestrator:
    cfg = Config(
        env=load_env(dotenv=tmp_path / "x.env", environ={}),
        settings=load_settings(ROOT / "deploy/settings.example.yaml"),
    )
    services = Services(lake=None, parser=None, compiler=None, mail=FakeMail(), llm=None)  # type: ignore[arg-type]
    return Orchestrator(
        cfg,
        JobDB(),
        FsStore(tmp_path / "obj"),
        AuditLog(tmp_path / "audit"),
        services,
        {t: _noop for t in [*scheduled_types(), "FEAS"]},
        tmp_path / "rulesets",
        tmp_path,
        today=lambda: date(2026, 11, 12),
        workers=0,
        async_notify=False,
    )


@pytest.fixture
def client(orch: Orchestrator, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from orchestrator import app as oapp

    per_service_tokens(tmp_path, monkeypatch)  # the console signs; PRODUCTION names every caller (D-464)
    monkeypatch.setenv("TB_ENV", "PRODUCTION")
    monkeypatch.setattr(oapp, "orch", lambda: orch)
    return TestClient(oapp.app, raise_server_exceptions=False)


def _failed(orch: Orchestrator, jtype: str, requested_by: str = "scheduler", state: str = "failed") -> Job:
    f = JobFile(filename="night.txt", sha256="0" * 64, minio_key="attachments/x/night.txt", content_type="text/plain")
    job = orch.create(
        JobCreate(type=jtype, ruleset=_ruleset(jtype), requested_by=requested_by,  # type: ignore[arg-type]
                  options={"window": "1", "timer": "1"}, comment="night", inputs=[f]),
        role="" if requested_by == "scheduler" else "admin",
    )  # fmt: skip
    if state == "failed":
        job = orch.set_state(job, "failed", error=JobError(step="running", message="source unreachable"))
    elif state != job.state:
        job = orch.set_state(job, state)
    return job


def _events(orch: Orchestrator) -> list[dict[str, Any]]:
    return [json.loads(line) for p in sorted(orch.audit.directory.glob("*.jsonl"))
            for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]  # fmt: skip


_SIGN = "x-test-sign-as"  # the person a call is signed as: the test's own note, taken off before the call


def _as(service: str, role: str = "admin", who: str = "console:admin") -> dict[str, str]:
    return {sa.TOKEN_HEADER: token_of(service), _SIGN: f"{who}|{role}"}


def _retry(client: TestClient, job_id: str, headers: dict[str, str], body: dict[str, Any] | None = None) -> Any:
    """T-715 refuse mode (D-871): the route takes a v3 assertion of ``job.retry_scheduled`` for exactly this call."""
    from tb_common import actor_v3

    body = body if body is not None else {"reply_to": ADMIN_MAIL}
    path, hdr = f"/jobs/{job_id}/retry", dict(headers)
    who, _, role = hdr.pop(_SIGN, "|").partition("|")
    if who:
        hdr[actor_v3.HEADER] = actor_v3.mint(sub=who, role=role, action="job.retry_scheduled", method="POST",
                                             path=path, body=body, study="")  # fmt: skip
    return client.post(path, json=body, headers=hdr)


def test_the_scheduled_types_are_the_plan() -> None:
    assert scheduled_types() == {"INGEST", "MICROBATCH", "NAV", "COHORT", "RETENTION", "CALIBRATION"}


@pytest.mark.parametrize("jtype", sorted(scheduled_types()))
def test_the_administrator_retries_a_failed_scheduler_job_of_every_type(
    client: TestClient, orch: Orchestrator, jtype: str
) -> None:
    failed = _failed(orch, jtype)
    r = _retry(client, failed.job_id, _as("console"))
    assert r.status_code == 200, r.text
    new = orch.db.get(r.json()["job_id"])
    assert new is not None and new.job_id != failed.job_id and new.state == "received"
    # the same type, study and parameters as the failed job; nothing chosen by the caller
    assert (new.type, new.ruleset, new.options, new.comment) == (failed.type, failed.ruleset, failed.options, "night")
    assert [f.minio_key for f in new.inputs or []] == [f.minio_key for f in failed.inputs or []]
    # who retried it, and which job it retries
    assert new.requested_by == ADMIN_MAIL and new.parent_job_id == failed.job_id
    ev = [e for e in _events(orch) if e.get("event") == "job.retried"]
    assert ev and ev[-1]["job_id"] == new.job_id and ev[-1]["detail"]["from"] == failed.job_id
    assert ev[-1]["detail"]["by"] == "console:admin" and ev[-1]["detail"]["role"] == "admin"


def test_the_role_alone_still_cannot_start_these_types(client: TestClient) -> None:
    """The retry right is not a right to start INGEST, RETENTION or CALIBRATION with parameters of one's own."""
    for jtype in ("INGEST", "RETENTION", "CALIBRATION"):
        body = {"type": jtype, "requested_by": ADMIN_MAIL, "options": {"window": "99"}}
        assert client.post("/jobs", json=body, headers=_as("console")).status_code == 403, jtype


@pytest.mark.parametrize("role", ["coordinator", "investigator", "viewer", "cro", "steward", "privacy"])
def test_a_role_other_than_the_administrator_is_refused(client: TestClient, orch: Orchestrator, role: str) -> None:
    failed = _failed(orch, "INGEST")
    r = _retry(client, failed.job_id, _as("console", role=role, who="console:someone"))
    assert r.status_code == 403
    assert orch.db.unfinished("INGEST", None) == []


def test_a_retry_names_a_signed_person(client: TestClient, orch: Orchestrator) -> None:
    failed = _failed(orch, "INGEST")
    assert _retry(client, failed.job_id, {sa.TOKEN_HEADER: token_of("console")}).status_code == 403
    forged = {sa.TOKEN_HEADER: token_of("console"), sa.ACTOR_HEADER: "console:admin", sa.ROLE_HEADER: "admin"}
    assert _retry(client, failed.job_id, forged).status_code == 403
    assert orch.db.unfinished("INGEST", None) == []


def test_a_job_a_person_started_is_not_retried_by_this_route(client: TestClient, orch: Orchestrator) -> None:
    failed = _failed(orch, "MICROBATCH", requested_by="crc@hospa.test")
    r = _retry(client, failed.job_id, _as("console"))
    assert r.status_code == 409 and "scheduler" in r.json()["detail"]
    feas = _failed(orch, "FEAS", requested_by="crc@hospa.test")
    assert _retry(client, feas.job_id, _as("console")).status_code == 409


@pytest.mark.parametrize("state", ["received", "running", "done"])
def test_a_job_that_has_not_failed_is_refused(client: TestClient, orch: Orchestrator, state: str) -> None:
    job = _failed(orch, "INGEST", state=state)
    r = _retry(client, job.job_id, _as("console"))
    assert r.status_code == 409
    assert orch.db.unfinished("INGEST", None) == ([job.job_id] if state != "done" else [])


def test_no_such_job(client: TestClient) -> None:
    assert _retry(client, "01JB0000000000000000000746", _as("console")).status_code == 404


def test_the_mail_gateway_and_the_operator_token_are_refused_by_the_route_gate(
    client: TestClient, orch: Orchestrator
) -> None:
    failed = _failed(orch, "INGEST")
    for svc in ("mail-gateway", "operator"):
        r = _retry(client, failed.job_id, _as(svc))
        assert r.status_code == 403 and r.headers.get("X-TB-Refusal") == "route_not_allowed", svc
    refused = [e for e in _events(orch) if e.get("event") == "service.route_refused"]
    assert {e["detail"]["service"] for e in refused} == {"mail-gateway", "operator"}
    assert {e["detail"]["route"] for e in refused} == {"POST /jobs/{job_id}/retry"}
    assert orch.db.unfinished("INGEST", None) == []


@pytest.mark.parametrize(
    "extra",
    [{"type": "SCREEN"}, {"options": {"window": "99"}}, {"ruleset": "OTHER"}, {"inputs": []}, {"requested_by": "x"}],
)
def test_the_body_cannot_change_the_parameters(client: TestClient, orch: Orchestrator, extra: dict[str, Any]) -> None:
    failed = _failed(orch, "INGEST")
    r = _retry(client, failed.job_id, _as("console"), {"reply_to": ADMIN_MAIL, **extra})
    assert r.status_code == 422
    assert orch.db.unfinished("INGEST", None) == []


@pytest.mark.parametrize("reply_to", ["scheduler", "system", "", "not-a-mailbox"])
def test_the_reply_address_is_a_mailbox_never_an_internal_principal(
    client: TestClient, orch: Orchestrator, reply_to: str
) -> None:
    failed = _failed(orch, "INGEST")
    assert _retry(client, failed.job_id, _as("console"), {"reply_to": reply_to}).status_code == 403
    assert orch.db.unfinished("INGEST", None) == []


def test_no_two_of_the_same_type_and_study_at_once(client: TestClient, orch: Orchestrator) -> None:
    first, second = _failed(orch, "INGEST"), _failed(orch, "INGEST")
    assert _retry(client, first.job_id, _as("console")).status_code == 200
    r = _retry(client, second.job_id, _as("console"))
    assert r.status_code == 409 and "already queued or running" in r.json()["detail"]
    assert len(orch.db.unfinished("INGEST", None)) == 1
    # a MICROBATCH of another study is not the same job
    gz = _failed(orch, "MICROBATCH")
    orch.create(JobCreate(type="MICROBATCH", ruleset="OTHER", requested_by="scheduler"))
    assert _retry(client, gz.job_id, _as("console")).status_code == 200


def test_a_failed_retry_is_retried_again_and_its_chain_is_checked(client: TestClient, orch: Orchestrator) -> None:
    failed = _failed(orch, "RETENTION")
    new = orch.db.get(_retry(client, failed.job_id, _as("console")).json()["job_id"])
    assert new is not None
    orch.set_state(new, "failed", error=JobError(step="running", message="again"))
    r = _retry(client, new.job_id, _as("console"))
    assert r.status_code == 200 and r.json()["parent_job_id"] == new.job_id
    assert r.json()["options"] == failed.options


def test_core_refuses_without_the_matrix_right(orch: Orchestrator) -> None:
    failed = _failed(orch, "CALIBRATION")
    with pytest.raises(Rejected):
        orch.retry_scheduled(failed.job_id, by="console:crc", role="coordinator", reply_to=ADMIN_MAIL)
    with pytest.raises(NotRetryable):
        orch.retry_scheduled(_failed(orch, "CALIBRATION", state="done").job_id, by="console:admin", role="admin",
                             reply_to=ADMIN_MAIL)  # fmt: skip


# ---------------------------------------------------------------------------------------- T-715 refuse mode: cancel
def _cancel(client: TestClient, job_id: str, who: str | None, role: str = "admin", action: str = "request.prepare",
            by: str | None = None) -> Any:  # fmt: skip
    from tb_common import actor_v3

    path = f"/jobs/{job_id}/cancel"
    hdr = {sa.TOKEN_HEADER: token_of("console")}
    if who:
        hdr[actor_v3.HEADER] = actor_v3.mint(sub=who, role=role, action=action, method="POST", path=path, body={},
                                             study="")  # fmt: skip
    return client.post(path + (f"?by={by}" if by else ""), json={}, headers=hdr)


def test_a_cancel_takes_the_verified_administrator_and_nothing_else(orch: Orchestrator, client: TestClient) -> None:
    """T-715 refuse mode (D-871): no v2 name and no ``by``; a coordinator holds the row and is refused at the
    orchestrator as the console's jobs page refuses them; the administrator cancels."""
    job = _failed(orch, "NAV", state="running")
    assert _cancel(client, job.job_id, None, by="console:admin").status_code == 403  # a name is no person
    old = {sa.TOKEN_HEADER: token_of("console"), **sa.actor_header("console:admin", role="admin")}
    assert client.post(f"/jobs/{job.job_id}/cancel", json={}, headers=old).status_code == 403  # v2 is refused
    assert _cancel(client, job.job_id, "console:crc1", role="coordinator").status_code == 403
    assert _cancel(client, job.job_id, "console:admin", action="job.retry_scheduled").status_code == 403
    r = _cancel(client, job.job_id, "console:admin")
    assert r.status_code == 200, r.text
    refused = [e for e in _events(orch) if e["event"] == "actor.refused"]
    assert {e["detail"]["route"] for e in refused} >= {"POST /jobs/{job_id}/cancel"}
