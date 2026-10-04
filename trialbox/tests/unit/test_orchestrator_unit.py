"""Orchestrator rules with fake services: routing enforcement, idempotency, permissions, restart recovery, audit."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from orchestrator.core import Ctx, Delivery, Orchestrator, Outcome, Rejected, Services
from orchestrator.db import JobDB
from tb_common.audit import AuditLog, verify
from tb_common.config import Config, load_env, load_settings
from tb_common.objstore import FsStore
from tb_contracts import JobCreate, Routing, SendRequest, SendResult

ROOT = Path(__file__).resolve().parents[2]


class FakeMail:
    def __init__(self) -> None:
        self.sent: list[SendRequest] = []

    def send(self, req: SendRequest) -> SendResult:
        self.sent.append(req)
        return SendResult(message_id=f"<{len(self.sent)}@t>", sent_to=req.to, encrypted=req.encrypt or False)


def _phi_to(addr: str) -> Any:
    def scenario(ctx: Ctx) -> Outcome:
        ctx.state("running")
        routing = Routing(list_to=["pi@hospa.test"], aggregate_to=["crc1@hospa.test"])
        out = ctx.publish("candidates.xlsx", b"PK list", "phi", [addr])
        agg = ctx.publish("summary.pdf", b"%PDF", "aggregate", ["crc1@hospa.test"])
        return Outcome(
            deliveries=[
                Delivery(to=["crc1@hospa.test"], outputs=[agg], routing=routing),
                Delivery(to=[addr], outputs=[out], routing=routing),
            ]
        )

    return scenario


@pytest.fixture
def make(tmp_path: Path) -> Any:
    def build(scenarios: dict[str, Any], db: JobDB | None = None) -> tuple[Orchestrator, FakeMail]:
        cfg = Config(
            env=load_env(dotenv=tmp_path / "x.env", environ={}),
            settings=load_settings(ROOT / "deploy/settings.example.yaml"),
        )
        mail = FakeMail()
        services = Services(lake=None, parser=None, compiler=None, mail=mail)  # type: ignore[arg-type]
        orch = Orchestrator(
            cfg,
            db or JobDB(tmp_path / "jobs.sqlite"),
            FsStore(tmp_path / "obj"),
            AuditLog(tmp_path / "audit"),
            services,
            scenarios,
            tmp_path / "rulesets",
            tmp_path,
            today=lambda: date(2026, 10, 5),
            workers=0,
            async_notify=False,
        )
        return orch, mail

    return build


def test_routing_violation_fails_job(make: Any, tmp_path: Path) -> None:
    orch, mail = make({"SCREEN": _phi_to("sponsor@pharma.example")})
    job = orch.create(JobCreate(type="SCREEN", ruleset="GZQO", requested_by="crc1@hospa.test"))
    orch.drain()
    got = orch.db.get(job.job_id)
    assert got is not None and got.state == "failed" and got.error is not None and got.error.step == "routing"
    phi_mails = [m for m in mail.sent if any(a.tag == "phi" for a in m.attachments or [])]
    assert not phi_mails  # nothing tagged phi left the box
    assert [m.subject.split(" ")[0] for m in mail.sent] == ["Received", "Failed"]  # routes checked before sending
    assert verify(tmp_path / "audit").ok


def test_phi_routed_internally_is_encrypted(make: Any) -> None:
    orch, mail = make({"SCREEN": _phi_to("pi@hospa.test")})
    job = orch.create(JobCreate(type="SCREEN", ruleset="GZQO", requested_by="crc1@hospa.test"))
    orch.drain()
    assert orch.db.get(job.job_id).state == "done"
    phi = [m for m in mail.sent if m.tag == "phi"]
    assert len(phi) == 1 and phi[0].encrypt and phi[0].to == ["pi@hospa.test"]


def test_create_rules(make: Any, tmp_path: Path) -> None:
    orch, mail = make({})
    j = orch.create(
        JobCreate(type="FEAS", ruleset="GZQO", requested_by="CRC1@hospa.test", job_id="01JB0000000000000000000000")
    )
    again = orch.create(JobCreate(type="FEAS", ruleset="GZQO", requested_by="crc1@hospa.test", job_id=j.job_id))
    assert again.job_id == j.job_id and len(mail.sent) == 1  # idempotent; one Received
    with pytest.raises(Rejected):
        orch.create(JobCreate(type="SUBMIT", ruleset="RA-BIO", requested_by="crc1@hospa.test"))  # physicians only
    with pytest.raises(Rejected):
        orch.create(JobCreate(type="FEAS", ruleset="GZQO", requested_by="nobody@hospa.test"))
    for _ in range(19):
        orch.create(JobCreate(type="FEAS", ruleset="GZQO", requested_by="pi@hospa.test"))
    orch.create(JobCreate(type="FEAS", ruleset="GZQO", requested_by="pi@hospa.test"))
    with pytest.raises(Rejected, match="rate limit"):
        orch.create(JobCreate(type="FEAS", ruleset="GZQO", requested_by="pi@hospa.test"))
    orch.drain()
    assert orch.db.get(j.job_id).error.message.startswith("FEAS jobs are not available")


def test_restart_recovery(make: Any, tmp_path: Path) -> None:
    calls: list[str] = []

    def scenario(ctx: Ctx) -> Outcome:
        calls.append(ctx.job.job_id)
        ctx.state("running")
        return Outcome(summary_md="ok")

    db = JobDB(tmp_path / "jobs.sqlite")
    orch, _ = make({"FEAS": scenario}, db)
    job = orch.create(JobCreate(type="FEAS", ruleset="GZQO", requested_by="crc1@hospa.test"))
    assert db.claim() == job.job_id  # a worker took it ...
    orch.set_state(job, "running")  # ... and died mid-run
    orch2, _ = make({"FEAS": scenario}, db)
    orch2.n_workers = 0
    orch2.start()
    orch2.drain()
    assert calls == [job.job_id] and db.get(job.job_id).state == "done"  # type: ignore[union-attr]
