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

FLAG = "screening.after_restore"


def _events(audit: Path, name: str) -> list[dict[str, Any]]:
    rows = [json.loads(ln) for p in sorted(audit.rglob("*.jsonl")) for ln in p.read_text().splitlines()
            if '"event"' in ln]  # fmt: skip
    return [r for r in rows if r["event"] == name]


def _restore(tmp_path: Path, db_url: str, monkeypatch: Any, late_events: bool) -> tuple[dict[str, Any], Path]:
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
    f = bk.backup([tmp_path / "nas"], pub, env={"TB_DB_URL": db_url, "TB_SITE_ID": "CGMH"}, dirs={"audit": audit})[0]
    monkeypatch.setattr(bk, "take_snapshot", real)
    out = bk.restore(f, priv, env={"TB_DB_URL": db_url}, dirs={"audit": audit}, no_copy=True)
    return out, audit


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
    (ev,) = [e for e in _events(audit, "flag.set") if e["detail"]["flag"] == FLAG]
    assert ev["detail"]["new"] == "held" and "1 event" in ev["detail"]["reason"]
    assert "synthetic" not in json.dumps(ev)  # counts and times only, never what an event was about
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
    assert out["hold"] == "not needed" and flags.Flags(url=db_url).row(FLAG) in (None, "released")
    assert not [e for e in _events(audit, "flag.set") if e["detail"]["flag"] == FLAG]


def test_a_second_incomplete_restore_under_a_hold_keeps_the_hold(tmp_path: Path, db_url: str, monkeypatch: Any) -> None:
    """The backup was taken while the box was held (the flag is in the restored database): the restore does not
    fail on "already held", and the hold stays."""
    from tb_common import flags
    from tb_common.audit import AuditLog

    from tools.trialbox import backup as bk

    (tmp_path / "audit").mkdir()
    flags.Flags(url=db_url, audit=AuditLog(tmp_path / "audit")).set(FLAG, "held", actor="trialbox restore",
                                                                    reason="an earlier restore")  # fmt: skip
    assert bk.hold_screening({"TB_DB_URL": db_url}, tmp_path / "audit", "a second restore") == "held"
    assert flags.Flags(url=db_url).row(FLAG) == "held"
    assert bk.hold_screening({"TB_DB_URL": db_url}, None, "no audit directory").startswith("NOT set")


def test_doctor_shows_the_hold(db_url: str, tmp_path: Path) -> None:
    from tb_common import flags
    from tb_common.audit import AuditLog

    from tools.trialbox import doctor

    inp: Any = SimpleNamespace(env={"TB_DB_URL": db_url})
    assert doctor.check_restore_hold(inp).status == "PASS"
    flags.Flags(url=db_url, audit=AuditLog(tmp_path / "audit")).set(FLAG, "held", actor="trialbox restore",
                                                                    reason="2 event(s) to re-apply")  # fmt: skip
    got = doctor.check_restore_hold(inp)
    assert got.status == "WARN" and "/ops/flags" in got.detail and "2 event(s)" in got.detail
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
