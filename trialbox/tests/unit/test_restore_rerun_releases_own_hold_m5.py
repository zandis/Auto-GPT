"""INT-M5, the integrator's ruling 7178128292 ("go, narrowly"): a rerun of the SAME restore, ending complete, takes
off the hold ``screening.after_restore`` that this restore itself set, and nothing else.

Before, the ending decided: a restore stopped by TERM put the databases back and held the box, and its rerun, ending
complete, left the hold for a person; after KILL or a power loss the same rerun ended differently. Now the restore
writes its id (the backup's sha256 and the run's start) first in the hold's reason. A rerun takes the hold off only when
all four hold:
- it restores the same backup;
- the hold carries that restore's id;
- nothing changed the hold since (its latest change is that restore's own setting of it);
- the rerun ends complete.
The release is audited with both restore ids and the backup's id. Anything else stays for a person (RUNBOOK §5).

Each condition has its own test: the positive control (the earlier restore's id is read back) and the case where only
that condition is broken (the rerun leaves the box held). TERM, KILL and a power loss (the whole process group killed
at once) are sent for real to a restore in a child process, at the same step; each rerun ends the same way.
Fixed clocks (the backup's time and each run's start are given); synthetic rows only."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests import pg_client

ROOT = Path(__file__).resolve().parents[2]
FLAG = "screening.after_restore"
MADE = datetime(2026, 11, 20, 2, 0, tzinfo=UTC)  # the backup's time
FIRST = MADE + timedelta(hours=1)  # the first run's start
SECOND = MADE + timedelta(hours=2)  # the rerun's start


def _events(audit: Path, name: str) -> list[dict[str, Any]]:
    rows = [json.loads(ln) for p in sorted(audit.rglob("*.jsonl")) for ln in p.read_text().splitlines()
            if '"event"' in ln]  # fmt: skip
    return [r for r in rows if r["event"] == name]


def _box(tmp_path: Path, db_url: str, n: int = 1) -> tuple[list[Path], Path, Path, dict[str, str]]:
    """``n`` backups of one synthetic database (made at fixed times) and the key to open them."""
    from tb_common.db import Database

    from tools.trialbox import backup as bk

    db = Database.connect(db_url, "site")
    db.migrate(["CREATE TABLE marks (n BIGINT PRIMARY KEY)"])
    db.close()
    audit = tmp_path / "audit"
    audit.mkdir()
    priv, pub = tmp_path / "it.key", tmp_path / "box.pub"
    bk.keygen(priv, pub)
    env = {**pg_client.env(), "TB_DB_URL": db_url, "TB_SITE_ID": "CGMH", "TB_ENV": "DEV"}
    files = []
    for i in range(n):
        made = MADE - timedelta(minutes=10 * i)
        files.append(bk.backup([tmp_path / f"nas{i}"], pub, env=env, dirs={"audit": audit}, now=made)[0])
    return files, priv, audit, env


def _restore(f: Path, priv: Path, audit: Path, env: dict[str, str], now: datetime) -> dict[str, Any]:
    from tools.trialbox import backup as bk

    return bk.restore(f, priv, env=env, dirs={"audit": audit}, now=now, no_copy=True)


def _stopped_by_term(monkeypatch: pytest.MonkeyPatch, f: Path, priv: Path, audit: Path, env: dict[str, str]) -> None:
    """The first run, stopped by TERM after the trial database was replaced (its handler's exception, in-process)."""
    from tools.trialbox import backup as bk

    real = bk.fail_running_jobs

    def term(*a: Any, **k: Any) -> Any:
        raise bk.RestoreInterrupted("the restore was stopped by signal SIGTERM")

    monkeypatch.setattr(bk, "fail_running_jobs", term)
    with pytest.raises(bk.BackupError):
        _restore(f, priv, audit, env, FIRST)
    monkeypatch.setattr(bk, "fail_running_jobs", real)


def _flags(db_url: str, audit: Path | None = None) -> Any:
    from tb_common.audit import AuditLog
    from tb_common.flags import Flags

    return Flags(url=db_url, audit=AuditLog(audit) if audit is not None else None)


def _complete(monkeypatch: pytest.MonkeyPatch) -> None:
    from tools.trialbox import backup as bk

    monkeypatch.setattr(bk, "optouts_ok", lambda lost: True)  # the register's side is whole (T-728's own tests)


def _sha(f: Path) -> str:
    import hashlib

    return hashlib.sha256(f.read_bytes()).hexdigest()


def test_a_rerun_of_the_same_restore_ending_complete_releases_its_own_hold_audited(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.trialbox import backup as bk

    (f,), priv, audit, env = _box(tmp_path, db_url)
    _stopped_by_term(monkeypatch, f, priv, audit, env)
    first = bk.restore_id(_sha(f), FIRST)
    assert _flags(db_url).row(FLAG) == "held"
    assert str(_flags(db_url).events(FLAG, limit=1)[0]["reason"]).startswith(f"[restore {first}] ")
    _complete(monkeypatch)
    out = _restore(f, priv, audit, env, SECOND)
    assert out["complete"] is True and out["hold"] == "released" and _flags(db_url).row(FLAG) == "released"
    second = bk.restore_id(_sha(f), SECOND)
    rel = [e for e in _events(audit, "flag.set") if e["detail"]["flag"] == FLAG][-1]
    assert rel["detail"]["new"] == "released" and rel["actor"] == "trialbox restore"
    said = json.dumps(rel)
    assert second in said and first in said and _sha(f) in said, said  # both restore ids and the backup's id
    (done,) = [e for e in _events(audit, "backup.restored") if e["detail"].get("restore_id") == second]
    assert done["detail"]["rerun_of"] == first and done["detail"]["hold"] == "released"


def test_condition_same_backup_a_rerun_of_another_backup_leaves_the_hold(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.trialbox import backup as bk

    (f, other), priv, audit, env = _box(tmp_path, db_url, n=2)
    _stopped_by_term(monkeypatch, f, priv, audit, env)
    assert bk.own_rerun_hold(env, _sha(f)) == bk.restore_id(_sha(f), FIRST)  # the same backup: its own
    assert bk.own_rerun_hold(env, _sha(other)) is None
    _complete(monkeypatch)
    out = _restore(other, priv, audit, env, SECOND)
    assert out["complete"] is True and out["hold"] == "held" and _flags(db_url).row(FLAG) == "held"


def test_condition_the_hold_carries_the_restores_id_a_hold_without_one_stays(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.trialbox import backup as bk

    (f,), priv, audit, env = _box(tmp_path, db_url)
    _stopped_by_term(monkeypatch, f, priv, audit, env)
    assert bk.own_rerun_hold(env, _sha(f)) == bk.restore_id(_sha(f), FIRST)
    flags = _flags(db_url, audit)  # a restore of an older release: the same actor, no id in its reason
    flags.set(FLAG, "released", actor="trialbox restore", reason="synthetic: the older restore's release")
    flags.set(FLAG, "held", actor="trialbox restore", reason="restore of the backup of 2026-11-20: held until ...")
    assert bk.own_rerun_hold(env, _sha(f)) is None
    _complete(monkeypatch)
    out = _restore(f, priv, audit, env, SECOND)
    assert out["hold"] == "held" and _flags(db_url).row(FLAG) == "held"


def test_condition_nothing_changed_the_hold_since_a_persons_change_keeps_it(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.trialbox import backup as bk

    (f,), priv, audit, env = _box(tmp_path, db_url)
    _stopped_by_term(monkeypatch, f, priv, audit, env)
    first = bk.restore_id(_sha(f), FIRST)
    assert bk.own_rerun_hold(env, _sha(f)) == first
    flags = _flags(db_url, audit)  # a person took it off and held it again, with the restore's words copied in
    flags.set(FLAG, "released", actor="console:steward", reason="synthetic: looked at it")
    flags.set(FLAG, "held", actor="console:steward", reason=f"[restore {first}] held again by hand")
    assert bk.own_rerun_hold(env, _sha(f)) is None
    _complete(monkeypatch)
    out = _restore(f, priv, audit, env, SECOND)
    assert out["hold"] == "held" and _flags(db_url).row(FLAG) == "held"


def test_condition_the_rerun_ends_complete_one_that_does_not_keeps_the_hold(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.trialbox import backup as bk

    (f,), priv, audit, env = _box(tmp_path, db_url)
    _stopped_by_term(monkeypatch, f, priv, audit, env)
    assert bk.own_rerun_hold(env, _sha(f)) == bk.restore_id(_sha(f), FIRST)
    monkeypatch.setattr(bk, "optouts_ok", lambda lost: False)  # the opt-outs after the backup are not all back
    out = _restore(f, priv, audit, env, SECOND)
    assert out["complete"] is False and out["hold"] == "held" and _flags(db_url).row(FLAG) == "held"


#: the first run in a child process: it stops at the step after the hold was set and waits for its ending
CHILD = textwrap.dedent(
    """
    import json, os, sys, threading
    from datetime import datetime
    from pathlib import Path
    cfg = json.loads(sys.argv[1])
    sys.path[:0] = [cfg["root"], os.path.join(cfg["root"], "libs"), os.path.join(cfg["root"], "services")]
    from tools.trialbox import backup as bk

    def wait_here(*a, **k):
        Path(cfg["ready"]).write_text("ready")
        threading.Event().wait(120)  # the parent's signal ends this
        raise RuntimeError("synthetic: no signal came")

    bk.fail_running_jobs = wait_here
    bk.restore(Path(cfg["file"]), Path(cfg["key"]), env=cfg["env"], dirs={"audit": Path(cfg["audit"])},
               now=datetime.fromisoformat(cfg["now"]), no_copy=True)
    """
)


@pytest.mark.parametrize("ending", ["TERM", "KILL", "power loss"])
def test_term_kill_and_power_loss_end_the_same_way(
    tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch, ending: str
) -> None:
    from tools.trialbox import backup as bk

    (f,), priv, audit, env = _box(tmp_path, db_url)
    ready = tmp_path / "ready"
    child = tmp_path / "child.py"
    child.write_text(CHILD, encoding="utf-8")
    cfg = {"root": str(ROOT), "ready": str(ready), "file": str(f), "key": str(priv), "audit": str(audit), "env": env,
           "now": FIRST.isoformat()}  # fmt: skip
    p = subprocess.Popen([sys.executable, str(child), json.dumps(cfg)], env={"PATH": os.environ.get("PATH", "")},
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)  # fmt: skip
    got = threading.Event()
    for _ in range(600):  # bounded by steps, not a clock: the child writes the file when it reached the step
        if ready.exists() or p.poll() is not None:
            break
        got.wait(0.1)
    assert ready.exists(), p.communicate(timeout=30)
    assert _flags(db_url).row(FLAG) == "held"  # the hold was set before the step it stopped at
    if ending == "TERM":
        p.send_signal(signal.SIGTERM)
    elif ending == "KILL":
        p.send_signal(signal.SIGKILL)
    else:  # a power loss: the whole process group at once, no handler runs
        os.killpg(p.pid, signal.SIGKILL)
    p.communicate(timeout=120)
    assert _flags(db_url).row(FLAG) == "held"  # every ending leaves the box held
    assert bk.own_rerun_hold(env, _sha(f)) == bk.restore_id(_sha(f), FIRST)
    _complete(monkeypatch)
    out = _restore(f, priv, audit, env, SECOND)
    assert (out["complete"], out["hold"], _flags(db_url).row(FLAG)) == (True, "released", "released"), ending
