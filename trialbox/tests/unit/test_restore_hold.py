"""NEW-B-3 (D-522): a restore that is not complete holds the box's list jobs until a person releases the hold.

T-691 (D-455, review M3) left this open: the restore lists the audit events that came after the backup's snapshot
and exits 4, and nothing kept the box from screening before a steward had re-applied them. The hold is the audited
flag ``screening.after_restore``: the restore sets it, the scheduler and the list scenarios read it, a person
releases it on ``/ops/flags`` with a reason, and ``trialbox doctor`` shows it."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests import pg_client

FLAG = "screening.after_restore"


def _events(audit: Path, name: str) -> list[dict[str, Any]]:
    rows = [json.loads(ln) for p in sorted(audit.rglob("*.jsonl")) for ln in p.read_text().splitlines()
            if '"event"' in ln]  # fmt: skip
    return [r for r in rows if r["event"] == name]


def _restore(tmp_path: Path, db_url: str, monkeypatch: Any, late_events: bool) -> tuple[dict[str, Any], Path]:
    out, audit, _f, _priv = _backup_and_restore(tmp_path, db_url, monkeypatch, late_events)
    return out, audit


def _backup_and_restore(
    tmp_path: Path, db_url: str, monkeypatch: Any, late_events: bool
) -> tuple[dict[str, Any], Path, Path, Path]:
    """A backup and its restore on one database; with ``late_events`` an opt-out is typed between the database
    snapshot and the copy of the audit chain (so the restored databases do not hold it)."""
    from tb_common.audit import AuditLog
    from tb_common.db import Database

    from tools.trialbox import backup as bk

    db = Database.connect(db_url, "site")
    db.migrate(["CREATE TABLE marks (n BIGINT PRIMARY KEY)"])
    db.close()
    audit = tmp_path / "audit"
    log = AuditLog(audit)
    log.append("console.opt_out", actor="console:steward", detail={"note": "before the backup"})
    priv, pub = tmp_path / "it.key", tmp_path / "box.pub"
    bk.keygen(priv, pub)
    real = bk.take_snapshot

    def snapshot_then_events(src: Any, work: Path, env: Any) -> Any:
        out = real(src, work, env)
        if late_events:
            threading.Event().wait(1.1)  # the event comes a second after the snapshot
            log.append("console.opt_out", actor="console:steward", detail={"pid": "synthetic"})
        return out

    monkeypatch.setattr(bk, "take_snapshot", snapshot_then_events)
    f = bk.backup(
        [tmp_path / "nas"],
        pub,
        env={**pg_client.env(), "TB_DB_URL": db_url, "TB_SITE_ID": "CGMH"},
        dirs={"audit": audit},
    )[0]
    monkeypatch.setattr(bk, "take_snapshot", real)
    out = bk.restore(
        f, priv, env={**pg_client.env(), "TB_DB_URL": db_url, "TB_ENV": "DEV"}, dirs={"audit": audit}, no_copy=True
    )
    return out, audit, f, priv


def test_a_restore_that_is_not_complete_holds_the_list_jobs_until_it_is_released(
    tmp_path: Path, db_url: str, monkeypatch: Any
) -> None:
    from orchestrator import scheduler
    from orchestrator.clients import StepFailed
    from tb_common import flags
    from tb_common.audit import AuditLog

    out, audit = _restore(tmp_path, db_url, monkeypatch, late_events=True)
    assert out["complete"] is False and len(out["to_reapply"]) == 1
    assert out["hold"] == "held" and flags.Flags(url=db_url).row(FLAG) == "held"
    (ev,) = _events(audit, "backup.restored")
    assert ev["detail"]["hold"] == "held"  # in the restored chain: the restore says it left the box held
    written = json.dumps(ev) + json.dumps(flags.Flags(url=db_url).events(FLAG, limit=5), default=str)
    assert "synthetic" not in written  # counts and times only, never what an event was about
    # the orchestrator: the timer starts no list job, and a list job a person asks for fails at its first step
    flags.clear_cache()
    said: list[tuple[str, dict[str, Any]]] = []
    orch: Any = SimpleNamespace(audit=SimpleNamespace(append=lambda e, **kw: said.append((e, kw.get("detail") or {}))))
    monkeypatch.setattr(scheduler, "study_state", lambda rid, url=None: "open")
    assert scheduler._held(orch, "MICROBATCH", "ADX") and scheduler._held(orch, "NAV", "NHI1")
    assert not scheduler._held(orch, "RETENTION", None) and not scheduler._held(orch, "INGEST", None)
    assert said[0] == ("scheduler.held", {"job": "MICROBATCH", "state": "held after a restore"})
    with pytest.raises(StepFailed, match="restored from a backup"):
        scheduler.require_open("ADX")
    # a person releases the hold with a reason (the console's /ops/flags does this call)
    flags.Flags(url=db_url, audit=AuditLog(audit)).set(FLAG, "released", actor="console:steward",
                                                        reason="the opt-out was recorded again")  # fmt: skip
    flags.clear_cache()
    assert not scheduler._held(orch, "MICROBATCH", "ADX")
    scheduler.require_open("ADX")
    released = [e for e in _events(audit, "flag.set") if e["detail"]["flag"] == FLAG][-1]
    assert released["actor"] == "console:steward" and released["detail"]["new"] == "released"


def test_a_complete_restore_holds_nothing(tmp_path: Path, db_url: str, monkeypatch: Any) -> None:
    from tb_common import flags

    from tools.trialbox import backup as bk

    # the opt-out register's side is T-728's (D-493); here it is whole, so only the audit chain decides
    monkeypatch.setattr(bk, "optouts_ok", lambda lost: True)
    out, audit = _restore(tmp_path, db_url, monkeypatch, late_events=False)
    assert out["complete"] is True and out["to_reapply"] == []
    # the hold is set as soon as the trial database is replaced and released by the restore itself only when it
    # ends complete and no earlier hold or restore stands
    assert out["hold"] == "released" and flags.Flags(url=db_url).row(FLAG) == "released"
    (rel,) = [e for e in _events(audit, "flag.set") if e["detail"]["flag"] == FLAG]
    assert rel["detail"]["new"] == "released" and rel["actor"] == "trialbox restore"


def test_a_second_restore_never_removes_the_hold(tmp_path: Path, db_url: str, monkeypatch: Any) -> None:
    """Review H1: the first restore is not complete and holds the box. The operator runs the restore again (the
    command itself says so when a reference pack is missing). The second run finds nothing to re-apply: the chain
    it sets aside is the first run's restored one. The hold stands; only a person releases it."""
    from tb_common import flags

    from tools.trialbox import backup as bk

    out, audit, f, priv = _backup_and_restore(tmp_path, db_url, monkeypatch, late_events=True)
    assert out["hold"] == "held"
    monkeypatch.setattr(bk, "optouts_ok", lambda lost: True)  # the register's side is whole in both runs
    # the second run reads the chain the first run restored, not the one the box wrote: it finds nothing
    monkeypatch.setattr(bk, "events_to_reapply", lambda audit_dir, since: [])
    again = bk.restore(
        f, priv, env={**pg_client.env(), "TB_DB_URL": db_url, "TB_ENV": "DEV"}, dirs={"audit": audit}, no_copy=True
    )
    assert again["to_reapply"] == [] and again["complete"] is True
    assert again["hold"] == "held" and flags.Flags(url=db_url).row(FLAG) == "held"


def test_a_restore_that_stops_after_the_database_was_replaced_leaves_the_box_held(
    tmp_path: Path, db_url: str, monkeypatch: Any
) -> None:
    """Review H1 and M1: the hold is set as soon as the trial database is replaced, so a restore that fails or is
    killed after that (here: the running jobs cannot be failed) leaves a held box. INT-M5 (ruling 7178128292, this
    assertion by ruling 7179262165): its re-run of the same backup, ending complete, takes that hold off, audited with
    both restore ids, since the hold is its own and nothing changed it."""
    from tb_common import flags
    from tb_common.audit import AuditLog
    from tb_common.db import Database

    from tools.trialbox import backup as bk

    db = Database.connect(db_url, "site")
    db.migrate(["CREATE TABLE marks (n BIGINT PRIMARY KEY)"])
    db.close()
    audit = tmp_path / "audit"
    AuditLog(audit).append("console.opt_out", actor="console:steward", detail={"note": "before the backup"})
    priv, pub = tmp_path / "it.key", tmp_path / "box.pub"
    bk.keygen(priv, pub)
    f = bk.backup(
        [tmp_path / "nas"],
        pub,
        env={**pg_client.env(), "TB_DB_URL": db_url, "TB_SITE_ID": "CGMH"},
        dirs={"audit": audit},
    )[0]
    real = bk.fail_running_jobs

    def cannot(*a: Any, **k: Any) -> Any:
        raise RuntimeError("the queue is locked")

    monkeypatch.setattr(bk, "fail_running_jobs", cannot)
    with pytest.raises(bk.BackupError, match="could not be failed"):
        bk.restore(
            f, priv, env={**pg_client.env(), "TB_DB_URL": db_url, "TB_ENV": "DEV"}, dirs={"audit": audit}, no_copy=True
        )
    assert flags.Flags(url=db_url).row(FLAG) == "held"
    monkeypatch.setattr(bk, "fail_running_jobs", real)
    monkeypatch.setattr(bk, "optouts_ok", lambda lost: True)
    out = bk.restore(
        f, priv, env={**pg_client.env(), "TB_DB_URL": db_url, "TB_ENV": "DEV"}, dirs={"audit": audit}, no_copy=True
    )
    assert out["hold"] == "released" and flags.Flags(url=db_url).row(FLAG) == "released"  # the re-run releases it
    rel = [e for e in _events(audit, "flag.set") if e["detail"]["flag"] == FLAG][-1]
    assert rel["detail"]["new"] == "released" and rel["actor"] == "trialbox restore"
    done = _events(audit, "backup.restored")[-1]["detail"]
    assert done["rerun_of"] in json.dumps(rel) and done["restore_id"] in json.dumps(rel), rel  # both restore ids


def test_a_hold_that_cannot_be_read_is_a_hold(db_url: str, tmp_path: Path, monkeypatch: Any) -> None:
    """Review M2: the flag is held and the read fails once (the database refuses a connection). Before: "not
    held", and a list job a person asked for ran. No store at all (a bare test stack) is not a hold."""
    from orchestrator import scheduler
    from orchestrator.clients import StepFailed
    from tb_common import flags
    from tb_common.audit import AuditLog

    flags.Flags(url=db_url, audit=AuditLog(tmp_path / "audit")).set(FLAG, "held", actor="trialbox restore",
                                                                    reason="a restore")  # fmt: skip

    def down(self: Any, name: str) -> str:
        raise ConnectionError("the database refused the connection")

    real = flags.Flags.row
    monkeypatch.setattr(flags.Flags, "row", down)
    with pytest.raises(StepFailed, match="restored from a backup"):
        scheduler.require_open("ADX")
    orch: Any = SimpleNamespace(audit=SimpleNamespace(append=lambda e, **kw: {}))
    assert scheduler._held(orch, "MICROBATCH", "ADX")
    monkeypatch.setattr(flags.Flags, "row", real)
    monkeypatch.delenv("TB_DB_URL")
    assert not scheduler.restore_held()


def test_nav_and_the_weekly_sample_are_held_too(db_url: str, tmp_path: Path, monkeypatch: Any) -> None:
    """Review M3, M4: a NAV that was queued at the backup, or that the administrator retries, lists patients; so
    does the weekly sample of "criteria not matched". Neither passed the list scenarios' first check."""
    from orchestrator import notmatched_sample
    from orchestrator.clients import StepFailed
    from orchestrator.scenarios import nav
    from tb_common import flags
    from tb_common.audit import AuditLog

    flags.Flags(url=db_url, audit=AuditLog(tmp_path / "audit")).set(FLAG, "held", actor="trialbox restore",
                                                                    reason="a restore")  # fmt: skip
    ctx: Any = SimpleNamespace(job=SimpleNamespace(ruleset="NHI1", options={}))
    with pytest.raises(StepFailed, match="restored from a backup"):
        nav.run(ctx)
    # the owner's ruling of 2026-11-12: CASE (one patient a person names) is refused too; FEAS (counts) is not
    from orchestrator.scenarios import case, feas

    bare: Any = SimpleNamespace(job=SimpleNamespace(ruleset="ADX", options={}))
    with pytest.raises(StepFailed, match="restored from a backup"):
        case.run(bare)
    with pytest.raises(Exception) as not_the_hold:  # FEAS goes past the hold (and stops on this bare stand-in)
        feas.run(bare)
    assert "restored from a backup" not in str(not_the_hold.value)
    asked: list[int] = []

    def first_step(environ: Any) -> bool:  # the draw's first step after the hold (its own gate)
        asked.append(1)
        return True

    monkeypatch.setattr(notmatched_sample, "gate_on", first_step)
    reads: list[int] = []

    def register(*a: Any, **k: Any) -> set[str]:  # the next step: the register is read (the test stops the draw here)
        reads.append(1)
        raise RuntimeError("the test stops the draw here")

    monkeypatch.setattr(notmatched_sample, "register_now", register)
    assert notmatched_sample.weekly(SimpleNamespace()) == {} and asked == []  # held: not even begun
    assert reads == []  # and no register was read (the effective register of D-477 included)
    flags.Flags(url=db_url, audit=AuditLog(tmp_path / "audit")).set(FLAG, "released", actor="console:admin",
                                                                    reason="re-applied")  # fmt: skip
    notmatched_sample.weekly(SimpleNamespace())
    assert asked == [1] and reads == [1]  # released: the draw goes on, and reads the register


def test_doctor_shows_the_hold(db_url: str, tmp_path: Path) -> None:
    from tb_common import flags
    from tb_common.audit import AuditLog

    from tools.trialbox import doctor

    inp: Any = SimpleNamespace(env={**pg_client.env(), "TB_DB_URL": db_url, "TB_ENV": "DEV"})
    assert doctor.check_restore_hold(inp).status == "PASS"
    flags.Flags(url=db_url, audit=AuditLog(tmp_path / "audit")).set(FLAG, "held", actor="trialbox restore",
                                                                    reason="2 event(s) to re-apply")  # fmt: skip
    got = doctor.check_restore_hold(inp)
    assert got.status == "WARN" and got.name == "restore_hold" and "/ops/flags" in got.detail
    assert doctor.check_restore_hold in doctor.CHECKS
    nowhere: Any = SimpleNamespace(env={})
    assert doctor.check_restore_hold(nowhere).status == "PASS"  # no database here: not read


@pytest.mark.nodb
def test_the_flag_is_declared_and_described_in_three_languages() -> None:
    from console import i18n_flags
    from tb_common import flags

    d = flags.DECLARED[FLAG]
    assert d.values == ("released", "held") and d.default == "released" and d.seed_env is None
    for table in (i18n_flags.EN, i18n_flags.JA, i18n_flags.ZH):
        assert table[f"flags.desc.{FLAG}"]
