"""T-728 (D-493; lifecycle review F-8, F-9, F-11): an as-of export keeps the opt-out tombstones, and a restore
reports and audits the opt-outs typed after the backup and fails, not re-queues, the jobs that were running then.

The two cases of the card's row as tests, each with the orders of events that could undo it. Synthetic patients, a
real PostgreSQL, ``pg_dump`` / ``pg_restore`` as the backup tool runs them."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

TZ = "Asia/Taipei"
A, B = "P-OUT", "P-STAYS"
# job ids are ULIDs
J_DONE, J_RUNNING, J_REPORTING, J_QUEUED, J_WAITING = (f"01JT728{n:019d}" for n in range(1, 6))


def _batch(pids: list[str], code: str = "M10.0", consent: tuple[str, ...] = ()) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {"Patient": [], "Encounter": [], "Condition": [], "Consent": []}
    for i, p in enumerate(pids):
        out["Patient"].append(
            {"resourceType": "Patient", "id": p, "birthDate": f"1960-01-0{i + 1}", "gender": "female"}
        )
        out["Encounter"].append(
            {
                "resourceType": "Encounter",
                "id": f"e-{p}",
                "status": "finished",
                "class": {"code": "AMB"},
                "subject": {"reference": f"Patient/{p}"},
                "period": {"start": "2026-10-01T09:00:00", "end": "2026-10-01T10:00:00"},
            }
        )
        out["Condition"].append(
            {
                "resourceType": "Condition",
                "id": f"c-{p}",
                "subject": {"reference": f"Patient/{p}"},
                "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": code}]},
                "onsetDateTime": "2026-09-01",
                "recordedDate": "2026-09-01",
                "encounter": {"reference": f"Encounter/e-{p}"},
            }
        )
    for p in consent:
        out["Consent"].append(
            {
                "resourceType": "Consent",
                "id": f"k-{p}",
                "status": "rejected",
                "patient": {"reference": f"Patient/{p}"},
                "dateTime": "2026-10-02",
                "provision": {"type": "deny"},
            }
        )
    return out


def _tick() -> datetime:
    """An instant strictly between two transactions (``now()`` is the transaction's start)."""
    time.sleep(0.01)
    at = datetime.now(UTC)
    time.sleep(0.01)
    return at


def _rows_of(rows: dict[str, list[dict[str, Any]]], pid: str) -> dict[str, int]:
    return {t: n for t, rs in rows.items() if (n := sum(1 for r in rs if r.get("pid") == pid))}


@pytest.fixture
def store(db_url: str) -> Any:
    from omop import schema

    db = schema.connect(db_url, "omop_t728")
    yield db
    db.close()


# ------------------------------------------------------------------------------------------------ the as-of export
def test_an_as_of_export_before_an_opt_out_has_no_row_of_the_patient_but_the_consent_row(store: Any) -> None:
    """Case 1 of the row (F-9): the opt-out's tombstone keeps its before-images, and the wind-back restored them."""
    from omop.export import export_rows
    from omop.load import load_batch, withhold

    load_batch(store, "feed", "2026-10-04", _batch([A, B], consent=(A,)), tz=TZ)
    before = _tick()
    full = export_rows(store)
    assert _rows_of(full, A) == {"patient": 1, "encounter": 1, "condition": 1, "consent": 1}
    withhold(store, [A])
    after = _tick()
    for at in (before, after, None):
        got = export_rows(store, as_of=at)
        assert _rows_of(got, A) == {"consent": 1}, at  # the refusal itself still reaches the lake (D-441)
        assert _rows_of(got, B) == _rows_of(full, B) == {"patient": 1, "encounter": 1, "condition": 1}
    # the as-of export wrote nothing: the store is as the opt-out left it
    assert store.fetchval("SELECT count(*) FROM tb_withheld") == 1
    assert store.fetchval("SELECT count(*) FROM tb_record_event WHERE event = 'tombstone'") == 3
    assert _rows_of(export_rows(store), A) == {"consent": 1}


def test_a_record_changed_between_the_as_of_time_and_the_opt_out_stays_out_too(store: Any) -> None:
    """The order that a filter on the opt-out's own event misses: a later night changes the record first (the
    record's first event after the as-of time is that update, whose before-image is a live row), then the opt-out."""
    from omop.export import export_rows
    from omop.load import load_batch, withhold

    load_batch(store, "feed", "2026-10-04", _batch([A, B]), tz=TZ)
    night1 = _tick()
    rep = load_batch(store, "feed", "2026-10-05", _batch([A, B], code="M10.9"), tz=TZ)
    assert rep.updated == 2
    night2 = _tick()
    withhold(store, [A])
    for at in (night1, night2):
        got = export_rows(store, as_of=at)
        assert _rows_of(got, A) == {}, at
        assert _rows_of(got, B) == {"patient": 1, "encounter": 1, "condition": 1}
    # B's record of the first night is still the first night's: the wind-back itself is unchanged
    assert [r["code"] for r in export_rows(store, as_of=night1)["condition"]] == ["M10.0"]
    assert [r["code"] for r in export_rows(store, as_of=night2)["condition"]] == ["M10.9"]


def test_a_patient_first_loaded_after_the_as_of_time_and_a_lifted_opt_out(store: Any) -> None:
    from omop.export import export_rows
    from omop.load import load_batch, withhold

    load_batch(store, "feed", "2026-10-04", _batch([B]), tz=TZ)
    night1 = _tick()
    load_batch(store, "feed", "2026-10-05", _batch([B, A]), tz=TZ)
    night2 = _tick()
    withhold(store, [A])
    assert _rows_of(export_rows(store, as_of=night1), A) == {}  # not loaded yet then, and withheld now
    assert _rows_of(export_rows(store, as_of=night2), A) == {}
    withhold(store, [])  # the opt-out is lifted: the register of today no longer withholds A
    assert _rows_of(export_rows(store, as_of=night2), A) == {"patient": 1, "encounter": 1, "condition": 1}
    assert _rows_of(export_rows(store), A) == {}  # the live store waits for the next load (D-441)


# ------------------------------------------------------------------------------------------------ the restore
def _job_row(job_id: str, state: str, received: datetime) -> tuple[Any, ...]:
    data = {
        "job_id": job_id,
        "type": "SCREEN",
        "state": state,
        "requested_by": "crc1@hospa.test",
        "received_at": received.isoformat(),
        "updated_at": received.isoformat(),
    }
    return (job_id, "SCREEN", state, "crc1@hospa.test", received.isoformat(), json.dumps(data))


def _box(db_url: str, tmp_path: Path) -> tuple[Any, Any, dict[str, Path]]:
    """A box with an opt-out register and a job queue: one opt-out and four jobs before the backup."""
    from orchestrator.db import JobDB
    from tb_common.optout import OptOutRegister

    reg = OptOutRegister(db_url)
    jobs = JobDB(db_url)
    t0 = datetime.now(UTC) - timedelta(hours=2)
    reg.add("P-BEFORE", "office", "", "office:a", t0.isoformat())
    with jobs.tx() as tx:
        for jid, state, queued in (
            (J_DONE, "done", 0),
            (J_RUNNING, "running", 0),
            (J_REPORTING, "reporting", 0),
            (J_QUEUED, "received", 1),
            (J_WAITING, "awaiting_approval", 0),
        ):
            tx.execute(
                "INSERT INTO jobs (job_id, type, state, requested_by, received_at, data, queued) "
                "VALUES (?,?,?,?,?,?,?)",
                (*_job_row(jid, state, t0), queued),
            )
    dirs = {"audit": tmp_path / "audit"}
    dirs["audit"].mkdir()
    return reg, jobs, dirs


def _audit_events(audit: Path, name: str) -> list[dict[str, Any]]:
    rows = [json.loads(ln) for p in sorted(audit.rglob("*.jsonl")) for ln in p.read_text().splitlines() if ln.strip()]
    return [r for r in rows if r.get("event") == name]


def test_a_restore_reports_and_audits_the_opt_outs_typed_after_the_backup(tmp_path: Path, db_url: str) -> None:
    """Case 2 of the row (F-8): two opt-outs and a lift are typed after the backup. The restore says so before it
    empties the register, by count, action and source and never by who; it is in the audit; it is not complete."""
    from tb_common.optout import REGISTRY_ACTOR, OptOutRegister

    from tools.trialbox import backup as bk
    from tools.trialbox.__main__ import main as cli

    reg, _jobs, dirs = _box(db_url, tmp_path)
    priv, pub = tmp_path / "it.key", tmp_path / "box.pub"
    bk.keygen(priv, pub)
    env = {"TB_DB_URL": db_url, "TB_SITE_ID": "CGMH"}
    f = bk.backup([tmp_path / "nas"], pub, env=env, dirs=dirs)[0]
    time.sleep(1.1)  # the register's times and the snapshot's are a second apart at least
    now = datetime.now(UTC)
    reg.add("P-LATER-1", "office", "phoned", "office:a", now.isoformat())
    reg.add("P-LATER-2", "emr", "", REGISTRY_ACTOR, (now + timedelta(seconds=1)).isoformat())
    reg.lift("P-BEFORE", "", "steward:b", (now + timedelta(seconds=2)).isoformat())
    assert reg.active() == {"P-LATER-1", "P-LATER-2"}
    out = bk.restore(f, priv, env=env, dirs=dirs, no_copy=True)
    lost = out["optouts_after_backup"]
    assert lost["events"] == 3 and lost["by_action"] == {"opt_out": 2, "lift": 1}
    assert lost["by_source"] == {"office": 1, "emr": 1}  # of the opt-outs
    # the registry's own come back at the worker's next tick; what a person typed must be entered again
    assert (lost["from_registry"], lost["typed"]) == (1, 2)
    assert lost["first_at"] <= lost["last_at"] and lost["readable"] is True
    assert out["complete"] is False
    for secret in ("P-LATER", "P-BEFORE", "office:a", "steward:b", "phoned"):
        assert secret not in json.dumps(out), secret
    assert OptOutRegister(db_url).active() == {"P-BEFORE"}  # the register is the backup's again
    (ev,) = _audit_events(dirs["audit"], "backup.restored")
    assert ev["detail"]["optouts_after_backup"] == lost
    assert "P-LATER" not in json.dumps(ev)
    # a second restore of the same backup has nothing later to lose and says so
    again = bk.restore(f, priv, env=env, dirs=dirs, no_copy=True)
    assert again["optouts_after_backup"]["events"] == 0 and again["complete"] is True
    # the command line prints the count and exits "not complete"
    OptOutRegister(db_url).add("P-LATER-3", "office", "", "office:a", datetime.now(UTC).isoformat())
    rc = cli(["restore", str(f), "--key", str(priv), "--yes", "--no-copy", "--dir", f"audit={dirs['audit']}"])
    assert rc == 4


def test_a_restore_fails_the_jobs_that_were_running_at_the_backup(tmp_path: Path, db_url: str) -> None:
    """F-11: the restored queue holds jobs as ``running``. They are failed with a message, not run again: the
    orchestrator's restart recovery finds nothing to re-queue. A queued job and a waiting one are left alone."""
    from orchestrator.db import JobDB

    from tools.trialbox import backup as bk

    _reg, jobs, dirs = _box(db_url, tmp_path)
    assert sorted(jobs.interrupted()) == [J_RUNNING, J_REPORTING]
    priv, pub = tmp_path / "it.key", tmp_path / "box.pub"
    bk.keygen(priv, pub)
    env = {"TB_DB_URL": db_url, "TB_SITE_ID": "CGMH"}
    f = bk.backup([tmp_path / "nas"], pub, env=env, dirs=dirs)[0]
    out = bk.restore(f, priv, env=env, dirs=dirs, no_copy=True)
    assert out["ok"] and out["warnings"] == []  # the row check against the manifest ran before the jobs were failed
    assert sorted(j["job_id"] for j in out["jobs_failed"]) == [J_RUNNING, J_REPORTING]
    assert {j["type"] for j in out["jobs_failed"]} == {"SCREEN"}
    after = JobDB(db_url)
    assert after.interrupted() == []  # nothing for the restart recovery to run again
    for jid, step in ((J_RUNNING, "running"), (J_REPORTING, "reporting")):
        job = after.get(jid)
        assert job is not None and job.state == "failed" and job.error is not None
        assert job.error.step == step and "restore" in job.error.message
        assert job.updated_at is not None and job.updated_at > job.received_at
    states = {jid: after.get(jid).state for jid in (J_DONE, J_QUEUED, J_WAITING)}  # type: ignore[union-attr]
    assert states == {J_DONE: "done", J_QUEUED: "received", J_WAITING: "awaiting_approval"}
    assert after.claim() == J_QUEUED  # the job that had not started is still in the queue
    (ev,) = _audit_events(dirs["audit"], "backup.restored")
    assert ev["detail"]["jobs_failed"] == 2
    # interrupted mid-way and run again: the second restore fails the same two jobs, once
    again = bk.restore(f, priv, env=env, dirs=dirs, no_copy=True)
    assert sorted(j["job_id"] for j in again["jobs_failed"]) == [J_RUNNING, J_REPORTING]


def test_a_register_that_cannot_be_read_is_not_reported_as_zero(tmp_path: Path, db_url: str) -> None:
    """A box whose database holds no register (a first install, a damaged box): "not readable", never "none"."""
    from tb_common.db import Database

    from tools.trialbox import backup as bk

    db = Database.connect(db_url, "site")
    db.migrate(["CREATE TABLE marks (n BIGINT PRIMARY KEY)"])
    dirs = {"audit": tmp_path / "audit"}
    dirs["audit"].mkdir()
    priv, pub = tmp_path / "it.key", tmp_path / "box.pub"
    bk.keygen(priv, pub)
    env = {"TB_DB_URL": db_url, "TB_SITE_ID": "CGMH"}
    f = bk.backup([tmp_path / "nas"], pub, env=env, dirs=dirs)[0]
    out = bk.restore(f, priv, env=env, dirs=dirs, no_copy=True)
    assert out["optouts_after_backup"] == {"readable": False, "events": None, "why": "the box holds no register"}
    assert out["jobs_failed"] == [] and out["complete"] is True  # nothing was there to lose
