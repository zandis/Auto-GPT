"""NEW-MAIL-1 (D-863, the integrator's ruling of 2026-11-16): the mail outbox asks before it sends a job's files.

Found by the adversarial review of T-206b part 2b: the outbox read a job's patient-level files and sent them with no
look at the opt-out register. A mail held at publish (the SMTP server down) and sent hours later by the drain, or by a
person's ``trialbox mail resolve KEY --resend``, could name a patient who had opted out in between. Now every send of
a job's patient-level files passes one door (``Gateway._still_current``): the orchestrator is asked whether the job's
outputs are still current against the register (``GET /jobs/{job_id}/outputs-current``: a yes or no, never a patient).
No is held as ``failed`` with a typed reason (a person drops it; a resend asks again); no answer is held as ``queued``
(asked again later); only a yes sends. A mail of aggregate counts is not asked. Synthetic data only."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from mail_gateway.gateway import NO_ANSWER, OPTED_OUT, Gateway
from mail_gateway.store import MailDB
from tb_common.audit import AuditLog
from tb_common.config import Config, load_env
from tb_common.objstore import FsStore
from tb_contracts import SendRequest

from tests.unit.test_mail_resolve import MTA, SETTINGS

JOB = "01JB0000000000000000000000"
A, C = "a1b2c3d4e5f6c001" * 2, "d4e5f6a1b2c3c003" * 2  # A opts out after the list was made


class Register:
    """What the orchestrator answers: current unless an output names someone opted out now; or it does not answer."""

    def __init__(self) -> None:
        self.gone: set[str] = set()
        self.down = False
        self.asked: list[str] = []

    def __call__(self, job_id: str) -> bool:
        self.asked.append(job_id)
        if self.down:
            raise ConnectionError("the orchestrator did not answer")
        return A not in self.gone


def _gw(tmp_path: Path, mta: MTA, register: Any) -> Gateway:
    env = load_env(dotenv=tmp_path / "none.env", environ={"MAIL_FROM_ADDR": "trialbox@hospa.test"})
    store = FsStore(tmp_path / "obj")
    store.put(f"outputs/{JOB}/candidate_list.json", json.dumps({"rows": [{"pid": A}, {"pid": C}]}).encode())
    return Gateway(Config(env=env, settings=SETTINGS), store, MailDB(), AuditLog(tmp_path / "audit", "Asia/Taipei"),
                   mta, jobs=lambda req: pytest.fail("no job"), secrets_dir=tmp_path, authserv_id="mx",
                   allow_phi_zip=True, outputs_current=register)  # fmt: skip


def _phi(key: str) -> SendRequest:
    return SendRequest.model_validate({
        "job_id": JOB, "to": ["pi@hospa.test"], "subject": "Done 01JB · SCREEN GZQO", "body_md": "**Done.**",
        "tag": "phi", "idempotency_key": key,
        "attachments": [{"filename": "candidate_list.json", "minio_key": f"outputs/{JOB}/candidate_list.json"}],
    })  # fmt: skip


def _state(gw: Gateway, key: str) -> tuple[str, str]:
    row = gw.db.get(key)
    assert row is not None
    got = gw.db.db.fetchone("SELECT last_error FROM send_keys WHERE key = ?", (key,))
    return row.state, str(got[0] or "") if got else ""


def test_held_at_publish_then_an_opt_out_then_the_drain_never_sends_it(db_url: str, tmp_path: Path) -> None:
    mta, reg = MTA(), Register()
    gw = _gw(tmp_path, mta, reg)
    gw.send(_phi("k1"))  # the SMTP server is down at publish: queued
    assert _state(gw, "k1")[0] == "queued" and mta.sent == []
    reg.gone.add(A)  # the patient opts out while it waits
    mta.cause = None  # the server is back
    assert gw.drain(force=True) == {"failed": 1}
    assert _state(gw, "k1") == ("failed", OPTED_OUT) and mta.sent == []  # held, never sent
    assert gw.drain(force=True) == {} and mta.sent == []  # failed is never tried again by itself


def test_a_persons_resend_asks_again_and_is_held_again(db_url: str, tmp_path: Path) -> None:
    mta, reg = MTA(), Register()
    gw = _gw(tmp_path, mta, reg)
    gw.send(_phi("k2"))
    reg.gone.add(A)
    mta.cause = None
    gw.drain(force=True)
    gw.resolve("k2", "resend", "admin")  # trialbox mail resolve k2 --resend
    gw.drain(force=True)
    assert _state(gw, "k2") == ("failed", OPTED_OUT) and mta.sent == []


def test_an_orchestrator_that_does_not_answer_holds_the_mail(db_url: str, tmp_path: Path) -> None:
    mta, reg = MTA(), Register()
    mta.cause = None
    reg.down = True
    gw = _gw(tmp_path, mta, reg)
    gw.send(_phi("k3"))
    state, why = _state(gw, "k3")
    assert state == "queued" and why.startswith(NO_ANSWER) and mta.sent == []  # asked again later, never sent
    reg.down = False
    assert gw.drain(force=True) == {"sent": 1}  # a yes sends it (and its password, to the same recipient)
    assert mta.sent and all(to == ["pi@hospa.test"] for to, _data in mta.sent)


def test_a_gateway_with_no_way_to_ask_holds_every_patient_file(db_url: str, tmp_path: Path) -> None:
    mta = MTA()
    mta.cause = None
    gw = _gw(tmp_path, mta, None)
    gw.send(_phi("k4"))
    assert _state(gw, "k4")[0] == "queued" and mta.sent == []


def test_a_mail_of_counts_is_not_asked(db_url: str, tmp_path: Path) -> None:
    mta, reg = MTA(), Register()
    mta.cause = None
    gw = _gw(tmp_path, mta, reg)
    req = _phi("k5").model_copy(update={"tag": "aggregate", "attachments": None})
    gw.send(req)
    assert reg.asked == [] and len(mta.sent) == 1


# ---------------------------------------------------------------------------------------------- the orchestrator
def test_the_orchestrator_answers_from_the_jobs_own_outputs(tmp_path: Path) -> None:
    from orchestrator.app import outputs_name_opted_out

    store = FsStore(tmp_path / "obj")
    store.put("outputs/J/candidate_list.json", json.dumps({"rows": [{"pid": A.upper()}]}).encode())
    job = SimpleNamespace(outputs=[
        SimpleNamespace(tag="phi", filename="candidate_list.json", minio_key="outputs/J/candidate_list.json"),
        SimpleNamespace(tag="phi", filename=f"twpas_GZQO_{C[:12]}.json", minio_key="outputs/J/missing.json"),
        SimpleNamespace(tag="aggregate", filename="counts.json", minio_key="outputs/J/none"),
    ])  # fmt: skip
    o = SimpleNamespace(store=store)
    assert outputs_name_opted_out(o, job, frozenset({A}))  # the list names A (any case)
    assert outputs_name_opted_out(o, job, frozenset({C}))  # C's own bundle, by its name
    assert not outputs_name_opted_out(o, job, frozenset())
    assert not outputs_name_opted_out(o, job, frozenset({"e" * 32}))


# ---------------------------------------------------------------------------------------------- the opt-out worker
def _worker_env(db_url: str, store: Any, gone: set[str]) -> Any:
    from datacore.optout_worker import WorkerEnv
    from tb_common.optout import OptOutRegister

    reg = OptOutRegister(db_url)
    for p in gone:
        reg.add(p, "office", "synthetic", "crc", "2026-11-16T09:00:00+08:00")
    return WorkerEnv(register=reg, audit=None, now=None, extra={"store": store})  # type: ignore[arg-type]


def test_the_opt_out_worker_drops_a_held_mails_files_that_name_the_patient(db_url: str, tmp_path: Path) -> None:
    """The integrator's ruling: a held mail's attachment goes by the erasure path (objects:outputs off the owed list).
    The file naming the patient goes; the job's file naming no one stays; a mail not held is not touched."""
    from datacore.optout_worker import clear_held_mail, verify_held_mail

    mta, reg = MTA(), Register()
    gw = _gw(tmp_path, mta, reg)
    other = f"outputs/{JOB}/notes_{C[:12]}.json"
    gw.store.put(other, b'{"synthetic": true}')
    doc = _phi("k6").model_dump()
    doc["attachments"].append({"filename": f"notes_{C[:12]}.json", "minio_key": other})
    req = SendRequest.model_validate(doc)
    gw.send(req)
    reg.gone.add(A)
    mta.cause = None
    gw.drain(force=True)
    assert _state(gw, "k6") == ("failed", OPTED_OUT)
    env = _worker_env(db_url, gw.store, {A})
    gone = frozenset(env.register.effective())
    assert verify_held_mail(gone, env) == {"objects:outputs": 1}
    assert clear_held_mail(gone, env) == {"objects:outputs": 1}
    assert verify_held_mail(gone, env) == {"objects:outputs": 0}
    assert not gw.store.exists(f"outputs/{JOB}/candidate_list.json") and gw.store.exists(other)
    gw.resolve("k6", "resend", "admin")  # a person's resend asks again: held, never sent
    gw.drain(force=True)
    assert _state(gw, "k6")[0] == "failed" and mta.sent == []
    env.register.close()


def test_a_held_mail_the_worker_cannot_reach_is_never_called_cleared(db_url: str, tmp_path: Path) -> None:
    from datacore.optout_worker import clear_held_mail

    mta, reg = MTA(), Register()
    _gw(tmp_path, mta, reg)  # the outbox is there
    env = _worker_env(db_url, None, {A})
    with pytest.raises(RuntimeError):
        clear_held_mail(frozenset({A}), env)
    env.register.close()
