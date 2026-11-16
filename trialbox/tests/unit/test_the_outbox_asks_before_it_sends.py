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
from mail_gateway.gateway import MAX_ATTEMPTS, NO_ANSWER, NO_JOB, OPTED_OUT, Gateway, NoSuchJob
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

    def __call__(self, job_id: str, files: list[str]) -> bool:
        self.asked.append(job_id)
        self.files = files
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


def test_a_mail_of_patient_files_under_a_counts_label_is_still_asked(db_url: str, tmp_path: Path) -> None:
    """The review of D-863: the gateway judges a mail patient-level as the mail builder does (any file's tag)."""
    mta, reg = MTA(), Register()
    mta.cause = None
    gw = _gw(tmp_path, mta, reg)
    doc = _phi("k7").model_dump()
    doc["tag"], doc["attachments"][0]["tag"] = "aggregate", "phi"
    reg.gone.add(A)
    gw.send(SendRequest.model_validate(doc))
    assert reg.asked == [JOB] and reg.files == ["candidate_list.json"]
    assert _state(gw, "k7") == ("failed", OPTED_OUT) and mta.sent == []


def test_a_file_of_another_job_is_never_vouched_for(db_url: str, tmp_path: Path) -> None:
    mta, reg = MTA(), Register()
    mta.cause = None
    gw = _gw(tmp_path, mta, reg)
    doc = _phi("k8").model_dump()
    doc["attachments"][0]["minio_key"] = "outputs/01JBOTHER000000000000000000/candidate_list.json"
    gw.send(SendRequest.model_validate(doc))
    assert reg.asked == [] and _state(gw, "k8") == ("failed", NO_JOB) and mta.sent == []


def test_a_job_the_orchestrator_no_longer_has_goes_to_a_person(db_url: str, tmp_path: Path) -> None:
    mta = MTA()
    mta.cause = None

    def gone_job(job_id: str, files: list[str]) -> bool:
        raise NoSuchJob(job_id)

    gw = _gw(tmp_path, mta, gone_job)
    gw.send(_phi("k9"))
    assert _state(gw, "k9") == ("failed", NO_JOB) and mta.sent == []


def test_no_answer_is_counted_and_ends_with_a_person(db_url: str, tmp_path: Path) -> None:
    """The review of D-863: a mail never answered for is not tried every minute for ever."""
    mta, reg = MTA(), Register()
    mta.cause = None
    reg.down = True
    gw = _gw(tmp_path, mta, reg)
    gw.send(_phi("k10"))
    for _ in range(MAX_ATTEMPTS + 2):
        gw.drain(force=True)
    state, why = _state(gw, "k10")
    assert state == "failed" and why.startswith(NO_ANSWER) and mta.sent == []
    assert gw.db.get("k10").attempts == MAX_ATTEMPTS  # type: ignore[union-attr]


# ---------------------------------------------------------------------------------------------- the orchestrator
def _out(name: str, key: str, tag: str = "phi") -> SimpleNamespace:
    return SimpleNamespace(tag=tag, filename=name, minio_key=key)


def test_the_orchestrator_answers_for_the_files_the_mail_carries(tmp_path: Path) -> None:
    from orchestrator.app import outputs_name_opted_out

    store = FsStore(tmp_path / "obj")
    store.put("outputs/J/candidate_list.json", json.dumps({"rows": [{"pid": A.upper()}]}).encode())
    store.put("outputs/J/excluded.jsonl", json.dumps({"pid": C}).encode())
    job = SimpleNamespace(outputs=[
        _out("candidate_list.json", "outputs/J/candidate_list.json"),
        _out("candidate_list.xlsx", "outputs/J/candidate_list.xlsx"),
        _out("excluded.jsonl", "outputs/J/excluded.jsonl"),
        _out(f"twpas_GZQO_{C[:12]}.json", "outputs/J/missing.json"),
        _out("counts.json", "outputs/J/none", "aggregate"),
    ])  # fmt: skip
    o = SimpleNamespace(store=store)
    assert outputs_name_opted_out(o, job, frozenset({A}))  # the list names A (any case)
    assert outputs_name_opted_out(o, job, frozenset({C}), [f"twpas_GZQO_{C[:12]}.json"])  # C's bundle, by its name
    assert not outputs_name_opted_out(o, job, frozenset(), None)
    assert not outputs_name_opted_out(o, job, frozenset({"e" * 32}))
    # the review of D-863: the workbook is judged by its own list, not by a list of the excluded
    assert not outputs_name_opted_out(o, job, frozenset({C}), ["candidate_list.xlsx", "candidate_list.json"])
    assert outputs_name_opted_out(o, job, frozenset({A}), ["candidate_list.xlsx"])
    assert outputs_name_opted_out(o, job, frozenset(), ["not_of_this_job.json"])  # not the job's own: never vouched
    alone = SimpleNamespace(outputs=[_out("list.pdf", "outputs/J/list.pdf")])
    assert outputs_name_opted_out(o, alone, frozenset({C}))  # nothing to judge it by: names one (fail closed)


# ---------------------------------------------------------------------------------------------- the opt-out worker
def _worker_env(db_url: str, gone: set[str]) -> Any:
    from datetime import UTC, datetime

    from datacore.optout_worker import WorkerEnv
    from tb_common.optout import OptOutRegister

    reg = OptOutRegister(db_url)
    for p in gone:
        reg.add(p, "office", "synthetic", "crc", "2026-11-16T09:00:00+08:00")
    return WorkerEnv(register=reg, audit=None, now=datetime(2026, 11, 16, 9, tzinfo=UTC))


def test_the_opt_out_worker_drops_a_held_mail_and_keeps_the_jobs_files(db_url: str, tmp_path: Path) -> None:
    """The integrator's ruling, as the review of D-863 bounded it: the held mail goes (its request and recipients),
    so nothing sends it again; the job's files stay, as other patients' pages read them (D-513)."""
    from datacore.optout_worker import clear_held_mail, verify_held_mail

    mta, reg = MTA(), Register()
    gw = _gw(tmp_path, mta, reg)
    gw.send(_phi("k6"))
    gw.send(_phi("k11").model_copy(update={"subject": "Another"}))
    reg.gone.add(A)
    mta.cause = None
    reg.down = True
    gw.drain(force=True)  # both queued, not answered for
    reg.down = False
    gw.db.db.execute("UPDATE send_keys SET next_at = NULL")  # due again now
    gw.drain(force=True)
    assert _state(gw, "k6") == ("failed", OPTED_OUT)
    env = _worker_env(db_url, {A})
    gone = frozenset(env.register.effective())
    assert verify_held_mail(gone, env) == {"mail.send_keys": 2}
    assert clear_held_mail(gone, env) == {"mail.send_keys": 2}
    assert verify_held_mail(gone, env) == {"mail.send_keys": 0}
    row = gw.db.db.fetchone("SELECT state, request, recipients FROM send_keys WHERE key = 'k6'")
    assert row is not None and tuple(row) == ("dropped", None, None)
    assert gw.store.exists(f"outputs/{JOB}/candidate_list.json")  # the job's file stays
    assert gw.drain(force=True) == {} and mta.sent == []
    env.register.close()
