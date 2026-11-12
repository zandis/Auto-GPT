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


def _keys(tmp_path: Path) -> tuple[Path, Path, Path]:
    from tools.trialbox import backup as bk

    priv, pub = tmp_path / "it.key", tmp_path / "box.pub"
    bk.keygen(priv, pub)
    return priv, pub, tmp_path / "kept"


def test_a_restore_keeps_the_opt_outs_recorded_after_the_backup(tmp_path: Path, db_url: str) -> None:
    """Case 2 of the row (F-8; review M1): two opt-outs and a lift are recorded after the backup. The restore puts
    the two opt-outs back into the restored register, so the next ingest and micro-batch (which read
    ``tb_common.optout.opted_out``) still leave those patients out. The lift stays reverted (the patient stays
    withheld) and the restore says so. Counts only, in the answer and in the audit; a re-run adds nothing twice."""
    from tb_common.optout import REGISTRY_ACTOR, OptOutRegister, opted_out

    from tools.trialbox import backup as bk

    reg, _jobs, dirs = _box(db_url, tmp_path)
    priv, pub, keep = _keys(tmp_path)
    env = {"TB_DB_URL": db_url, "TB_SITE_ID": "CGMH"}
    f = bk.backup([tmp_path / "nas"], pub, env=env, dirs=dirs)[0]
    time.sleep(1.1)  # the register's times and the snapshot's are a second apart at least
    now = datetime.now(UTC)
    reg.add("P-LATER-1", "office", "phoned", "office:a", now.isoformat())
    reg.add("P-LATER-2", "emr", "", REGISTRY_ACTOR, (now + timedelta(seconds=1)).isoformat())
    reg.lift("P-BEFORE", "", "steward:b", (now + timedelta(seconds=2)).isoformat())
    assert reg.active() == {"P-LATER-1", "P-LATER-2"}
    out = bk.restore(f, priv, env=env, dirs=dirs, public_key=pub, keep_to=keep)
    lost = out["optouts_after_backup"]
    assert lost["state"] == "counted" and lost["readable"] is True
    assert lost["events"] == 3 and lost["by_action"] == {"opt_out": 2, "lift": 1}
    assert lost["by_source"] == {"office": 1, "emr": 1}  # of the opt-outs
    assert (lost["from_registry"], lost["typed"]) == (1, 2)
    assert (lost["kept"], lost["not_kept"], lost["lifts_reverted"]) == (2, 0, 1)
    assert lost["first_at"] <= lost["last_at"]
    assert out["complete"] is False  # the lift a steward typed is not in the restored register
    for secret in ("P-LATER", "P-BEFORE", "office:a", "steward:b", "phoned"):
        assert secret not in json.dumps(out), secret
    after = OptOutRegister(db_url)
    assert after.active() == {"P-BEFORE", "P-LATER-1", "P-LATER-2"}  # nobody who said no is back
    assert {"P-LATER-1", "P-LATER-2"} <= opted_out(db_url)  # what the ingest and the micro-batch read
    kept = [e for e in after.events("P-LATER-1")]
    assert len(kept) == 1 and kept[0].by == "office:a" and kept[0].note == "phoned"  # the event as it was typed
    (ev,) = _audit_events(dirs["audit"], "backup.restored")
    assert ev["detail"]["optouts_after_backup"] == lost
    assert "P-LATER" not in json.dumps(ev)
    # run again (the first run stopped later, or IT repeats it): the same count, nothing twice
    again = bk.restore(f, priv, env=env, dirs=dirs, public_key=pub, keep_to=keep)
    assert again["optouts_after_backup"]["kept"] == 2
    assert len(OptOutRegister(db_url).events("P-LATER-1")) == 1
    assert OptOutRegister(db_url).active() == {"P-BEFORE", "P-LATER-1", "P-LATER-2"}


def test_a_restore_that_kept_every_later_opt_out_is_complete(
    tmp_path: Path, db_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    from tb_common.optout import OptOutRegister

    from tools.trialbox import backup as bk
    from tools.trialbox.__main__ import main as cli

    reg, _jobs, dirs = _box(db_url, tmp_path)
    priv, pub, keep = _keys(tmp_path)
    f = bk.backup([tmp_path / "nas"], pub, env={"TB_DB_URL": db_url, "TB_SITE_ID": "CGMH"}, dirs=dirs)[0]
    time.sleep(1.1)
    reg.add("P-LATER-1", "office", "", "office:a", datetime.now(UTC).isoformat())
    rc = cli(["restore", str(f), "--key", str(priv), "--yes", "--public", str(pub), "--keep-to", str(keep),
              "--dir", f"audit={dirs['audit']}"])  # fmt: skip
    err = capsys.readouterr().err
    assert rc == 0, err
    assert "1 opt-out(s) recorded after the backup" in err and "P-LATER" not in err
    assert OptOutRegister(db_url).active() == {"P-BEFORE", "P-LATER-1"}


def test_no_copy_is_refused_when_a_person_typed_an_opt_out_after_the_backup(tmp_path: Path, db_url: str) -> None:
    """Review M3: without a copy the live register is the only electronic record of them."""
    from tb_common.optout import OptOutRegister

    from tools.trialbox import backup as bk

    reg, _jobs, dirs = _box(db_url, tmp_path)
    priv, pub, _keep = _keys(tmp_path)
    env = {"TB_DB_URL": db_url, "TB_SITE_ID": "CGMH"}
    f = bk.backup([tmp_path / "nas"], pub, env=env, dirs=dirs)[0]
    time.sleep(1.1)
    reg.add("P-LATER-1", "office", "", "office:a", datetime.now(UTC).isoformat())
    with pytest.raises(bk.BackupError, match="--no-copy"):
        bk.restore(f, priv, env=env, dirs=dirs, no_copy=True)
    assert OptOutRegister(db_url).active() == {"P-BEFORE", "P-LATER-1"}  # nothing was replaced


def test_a_restore_that_fails_still_keeps_and_audits_the_later_opt_outs(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review H2: the count was read from the live register and was in no failure record; the second run then read
    a register that was already the backup's and said "none, complete"."""
    from tb_common.optout import OptOutRegister

    from tools.trialbox import backup as bk

    reg, _jobs, dirs = _box(db_url, tmp_path)
    priv, pub, keep = _keys(tmp_path)
    env = {"TB_DB_URL": db_url, "TB_SITE_ID": "CGMH"}
    f = bk.backup([tmp_path / "nas"], pub, env=env, dirs=dirs)[0]
    time.sleep(1.1)
    reg.add("P-LATER-1", "office", "", "office:a", datetime.now(UTC).isoformat())

    def broken(*a: Any, **kw: Any) -> Any:
        raise RuntimeError("the queue could not be changed")

    monkeypatch.setattr(bk, "fail_running_jobs", broken)
    with pytest.raises(bk.BackupError, match="1 opt-out"):
        bk.restore(f, priv, env=env, dirs=dirs, public_key=pub, keep_to=keep)
    (ev,) = _audit_events(dirs["audit"], "backup.restore_failed")
    assert ev["detail"]["optouts_after_backup"]["events"] == 1 and "P-LATER" not in json.dumps(ev)
    assert OptOutRegister(db_url).active() == {"P-BEFORE", "P-LATER-1"}  # kept although the restore stopped
    monkeypatch.undo()
    again = bk.restore(f, priv, env=env, dirs=dirs, public_key=pub, keep_to=keep)  # the second run
    assert again["optouts_after_backup"]["events"] == 1 and again["optouts_after_backup"]["kept"] == 1


def test_the_command_says_the_opt_outs_before_it_stops_for_the_reference_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Review H2: exit 3 (a reference-data pack is missing) came before the opt-out lines."""
    from tools.trialbox import backup as bk
    from tools.trialbox.__main__ import main as cli

    lost = {"readable": False, "events": None, "state": "unknown", "why": bk.NO_REGISTER, "since": "2026-11-01T00:00"}
    out = {"warnings": [], "refdata": {"missing": ["vocab"], "reloaded": []}, "optouts_after_backup": lost,
           "jobs_failed": [], "to_reapply": [], "reapply_since": "", "complete": False}  # fmt: skip
    monkeypatch.setattr(bk, "restore", lambda *a, **kw: out)
    rc = cli(["restore", str(tmp_path / "x.tbk"), "--key", str(tmp_path / "k"), "--yes"])
    err = capsys.readouterr().err
    assert rc == 3 and "are unknown" in err and "check the office's records" in err


def test_events_written_to_the_audit_after_its_backup_copy_are_listed(tmp_path: Path, db_url: str) -> None:
    """Review M2: the live audit folder is set aside and the restored copy read, so an erasure, a break-glass or a
    signature after the backup was in neither list and the restore said "complete"."""
    from tb_common.audit import AuditLog

    from tools.trialbox import backup as bk

    _reg, _jobs, dirs = _box(db_url, tmp_path)
    AuditLog(dirs["audit"]).append("job.created", actor="x")  # the folder holds a chain at the backup
    priv, pub, keep = _keys(tmp_path)
    env = {"TB_DB_URL": db_url, "TB_SITE_ID": "CGMH"}
    f = bk.backup([tmp_path / "nas"], pub, env=env, dirs=dirs)[0]
    time.sleep(1.1)
    AuditLog(dirs["audit"]).append("edc.erase_hidden", actor="steward:b", detail={"pid": "P-GONE"})
    out = bk.restore(f, priv, env=env, dirs=dirs, public_key=pub, keep_to=keep)
    assert [e["event"] for e in out["to_reapply"]] == ["edc.erase_hidden"]
    assert "pre-restore-" in out["to_reapply"][0]["where"] and "P-GONE" not in json.dumps(out)
    assert out["complete"] is False


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


def test_a_box_without_a_register_says_the_later_opt_outs_are_unknown(
    tmp_path: Path, db_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Review H1: a restore onto a new machine (or a box that never held a register) cannot know what the old box
    recorded after the backup. It says "unknown", never "none", and it is not complete."""
    from tb_common.db import Database

    from tools.trialbox import backup as bk
    from tools.trialbox.__main__ import main as cli

    db = Database.connect(db_url, "site")
    db.migrate(["CREATE TABLE marks (n BIGINT PRIMARY KEY)"])
    dirs = {"audit": tmp_path / "audit"}
    dirs["audit"].mkdir()
    priv, pub = tmp_path / "it.key", tmp_path / "box.pub"
    bk.keygen(priv, pub)
    env = {"TB_DB_URL": db_url, "TB_SITE_ID": "CGMH"}
    f = bk.backup([tmp_path / "nas"], pub, env=env, dirs=dirs)[0]
    out = bk.restore(f, priv, env=env, dirs=dirs, no_copy=True)
    lost = out["optouts_after_backup"]
    assert (lost["readable"], lost["events"], lost["state"]) == (False, None, "unknown")
    assert lost["why"] == "the box holds no register"
    assert out["jobs_failed"] == [] and out["complete"] is False
    rc = cli(["restore", str(f), "--key", str(priv), "--yes", "--no-copy", "--dir", f"audit={dirs['audit']}"])
    err = capsys.readouterr().err
    assert rc == 4 and "are unknown: check the office's records since then" in err


def test_a_backup_without_the_trial_database_loses_no_opt_out() -> None:
    """Review L4: the register is not replaced, so nothing is lost and nothing is said."""
    from tools.trialbox import backup as bk

    assert bk.optouts_ok({"readable": True, "events": 0, "state": "not_replaced"}) is True
    assert bk.optouts_ok({"readable": False, "events": None, "state": "unknown"}) is False
    assert bk.optouts_ok({"readable": False, "events": None, "state": "unreadable"}) is False
    counted = {"readable": True, "events": 2, "state": "counted", "kept": 2, "not_kept": 0, "lifts_reverted": 0}
    assert bk.optouts_ok(counted) is True
    assert (
        bk.optouts_ok({**counted, "not_kept": 1}) is False and bk.optouts_ok({**counted, "lifts_reverted": 1}) is False
    )


def test_an_as_of_export_reads_the_register_too_not_only_the_worker_s_copy(
    store: Any, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review L1: ``tb_withheld`` is the opt-out worker's copy and lags the register by a tick. An opt-out the
    worker has not applied yet is honoured by the as-of export all the same."""
    from omop.export import export_rows
    from omop.load import load_batch
    from tb_common.db import ENV
    from tb_common.optout import OptOutRegister

    out, stays = "P-OUT-0001", "P-STAYS-01"  # the register takes pseudonyms of 8 characters or more
    load_batch(store, "feed", "2026-10-04", _batch([out, stays]), tz=TZ)
    t1 = _tick()
    OptOutRegister(db_url).add(out, "office", "", "office:a", datetime.now(UTC).isoformat())  # no worker tick yet
    assert store.fetchval("SELECT count(*) FROM tb_withheld") == 0
    monkeypatch.setenv(ENV, db_url)
    rows = export_rows(store, as_of=t1)
    assert _rows_of(rows, out) == {}
    assert _rows_of(rows, stays) == {"patient": 1, "encounter": 1, "condition": 1}
    assert store.fetchval("SELECT count(*) FROM tb_withheld") == 0  # the export wrote nothing
