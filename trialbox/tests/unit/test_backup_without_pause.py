"""T-691 (D-455): the nightly backup without a pause; step limits from the size of the data; retention by size; the
console's Backup stops nothing; the watchdog leaves a paused container alone and honours a maintenance flag.

Scale review 2026-11-11 F-02: the nightly backup paused every service but db for the whole dump, with 7,200 s per
step: at 50,000 patients 30 to 75 minutes of a frozen box every night, at 500,000 a step that is killed and no backup
that ever completes. Docker and the db container are recording fakes here; the steps under test are the real ones.
The last test writes to a real PostgreSQL and to the files while a backup runs, and restores it.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_backup_schedule import T0, RunningBox, _cfg, _hermetic, _offbox  # noqa: F401 (_hermetic: autouse)
from tools.trialbox import backup_schedule as bs
from tools.trialbox import ops as tb_ops
from tools.trialbox import update as up
from tools.trialbox import watchdog as wd

GB = 10**9
HOUR = 3600.0


class SizedBox(RunningBox):
    """The running box of a big hospital: each database answers its size, and a step that is given less time than
    it takes is killed the way ``subprocess.run(timeout=...)`` kills it."""

    def __init__(self, db_bytes: int, step_s: dict[str, float], jobs: int = 0) -> None:
        super().__init__()
        self.db_bytes, self.step_s, self.jobs = db_bytes, step_s, jobs
        self.timeouts: dict[str, float | None] = {}

    def __call__(self, argv: list[str], **kw: Any) -> str:  # type: ignore[override]
        line = " ".join(argv)
        if "orch.jobs" in line:
            self.calls.append(list(argv))
            return f"{self.jobs}\n"
        if "pg_database_size(current_database())" in line:
            self.calls.append(list(argv))
            return f"{self.db_bytes}\n"
        if "sum(pg_database_size(datname))" in line:
            self.calls.append(list(argv))
            return f"{2 * self.db_bytes}\n"
        step = ("snapshot" if "psql -X -q" in line else "copy" if " cp " in f" {line} " else
                "container" if argv[:2] == ["docker", "run"] else "pgbackrest" if "pgbackrest" in argv else "")  # fmt: skip
        if step:
            t = kw.get("timeout")
            self.timeouts.setdefault(step, t)
            if t is not None and t < self.step_s.get(step, 0.0):
                self.calls.append(list(argv))
                raise subprocess.TimeoutExpired(argv, t)
        return super().__call__(argv, **kw)


def _deploy(tmp_path: Path, env: str = "") -> Path:
    deploy = tmp_path / "deploy"
    (deploy / "site").mkdir(parents=True, exist_ok=True)
    (deploy / ".env").write_text(f"TB_SITE_ID=CGMH\n{env}")
    return deploy


def _verbs(calls: list[list[str]]) -> list[str]:
    return [a for c in calls for a in c if a in ("pause", "unpause", "stop", "start", "restart")]


# ------------------------------------------------------------------------------------------------ acceptance
def test_a_three_hour_snapshot_step_ends_written_and_nothing_is_paused_by_default(tmp_path: Path) -> None:
    """The card's acceptance: a snapshot step of 3 h (fake runner). Before D-455 the step had 7,200 s and the nightly
    ended "failed", and every service but db was paused for it."""
    deploy = _deploy(tmp_path)
    fake = SizedBox(db_bytes=100 * GB, step_s={"snapshot": 3 * HOUR, "copy": 1 * HOUR, "container": 3 * HOUR})
    ops = bs.ComposeOps(deploy, fake)
    cfg = bs.config(deploy, {"TB_SITE_ID": "CGMH"}, process_env=False)
    cfg.targets, cfg.public_key = [tmp_path / "nas"], _cfg(tmp_path).public_key
    res = bs.nightly(cfg, ops.make_backup(cfg), lambda e, d: None, now=T0, classify=_offbox({"nas"}))
    assert res["ok"], res["errors"]
    assert cfg.quiesce == "off"  # D-455: the snapshot alone, unless the site asks for a pause
    assert res["file"]["name"].endswith(bs.SUFFIX)
    assert "pause" not in _verbs(fake.calls) and "stop" not in _verbs(fake.calls)
    pit = res["point_in_time"]
    assert pit["held"] is False and pit["paused"] == [] and "snapshot alone" in pit["why"]
    assert set(pit["snapshot_at"]) == {"trialbox_wf", "hapi"} and pit["files_done_at"] >= pit["snapshot_at"]["hapi"]
    # the limit is the size at the declared slowest rate plus the start: 100 GB at 5 MB/s + 900 s
    assert fake.timeouts["snapshot"] == pytest.approx(900 + 100 * GB / 5e6) == pit["limits"]["trialbox_wf"]
    assert json.loads(cfg.last_file.read_text())["point_in_time"]["held"] is False


def test_a_step_slower_than_its_size_allows_is_still_stopped(tmp_path: Path) -> None:
    """The limit is not gone: a step running below the declared slowest rate counts as hung and the night fails."""
    deploy = _deploy(tmp_path)
    fake = SizedBox(db_bytes=1 * GB, step_s={"snapshot": 10 * HOUR})
    cfg = _cfg(tmp_path, deploy=deploy, targets=[tmp_path / "nas"])
    res = bs.nightly(cfg, bs.ComposeOps(deploy, fake).make_backup(cfg), lambda e, d: None, now=T0,
                     classify=_offbox({"nas"}))  # fmt: skip
    assert not res["ok"] and "TimeoutExpired" in res["errors"][0]
    assert fake.timeouts["snapshot"] == pytest.approx(900 + GB / 5e6)


def test_without_a_size_a_step_has_no_limit_never_a_fixed_one(tmp_path: Path) -> None:
    deploy = _deploy(tmp_path)
    fake = SizedBox(db_bytes=0, step_s={})
    fake.db_bytes = None  # type: ignore[assignment]

    def no_size(argv: list[str], **kw: Any) -> str:
        if "pg_database_size" in " ".join(argv):
            raise RuntimeError("psql: could not connect")
        return SizedBox.__call__(fake, argv, **kw)

    ops = bs.ComposeOps(deploy, no_size)
    cfg = _cfg(tmp_path, deploy=deploy, targets=[tmp_path / "nas"])
    res = bs.nightly(cfg, ops.make_backup(cfg), lambda e, d: None, now=T0, classify=_offbox({"nas"}))
    assert res["ok"], res["errors"]
    assert fake.timeouts["snapshot"] is None and fake.timeouts["copy"] is None
    assert res["point_in_time"]["limits"]["trialbox_wf"] is None


def test_the_step_limit_formula_and_its_settings() -> None:
    assert bs.step_timeout(None) is None
    assert bs.step_timeout(0) == 900
    assert bs.step_timeout(50 * GB) == pytest.approx(900 + 10_000)
    assert bs.step_timeout(50 * GB, min_mbps=50, start_s=60) == pytest.approx(60 + 1_000)
    cfg = bs.config(Path("/x"), {"TB_BACKUP_MIN_MBPS": "50", "TB_BACKUP_STEP_START_S": "60",
                                 "TB_BACKUP_KEEP_SHARE": "0.25", "TB_BACKUP_QUIESCE": "pause"}, process_env=False)  # fmt: skip
    assert cfg.timeout(50 * GB) == pytest.approx(1_060) and cfg.keep_share == 0.25 and cfg.quiesce == "pause"
    assert bs.config(Path("/x"), {"TB_BACKUP_QUIESCE": "none"}, process_env=False).quiesce == "off"


# ------------------------------------------------------------------------------------------------ the pause, opt-in
def test_a_pause_is_never_taken_while_a_job_runs(tmp_path: Path) -> None:
    deploy = _deploy(tmp_path)
    fake = SizedBox(db_bytes=GB, step_s={}, jobs=2)
    cfg = _cfg(tmp_path, deploy=deploy, targets=[tmp_path / "nas"], quiesce="pause")
    res = bs.nightly(cfg, bs.ComposeOps(deploy, fake).make_backup(cfg), lambda e, d: None, now=T0,
                     classify=_offbox({"nas"}))  # fmt: skip
    assert res["ok"], res["errors"]
    assert "pause" not in _verbs(fake.calls)
    assert res["point_in_time"]["held"] is False and res["point_in_time"]["running_jobs"] == 2
    assert "2 job(s) running" in res["point_in_time"]["why"]


def test_a_pause_holds_the_maintenance_flag_and_drops_it_after(tmp_path: Path) -> None:
    deploy = _deploy(tmp_path)
    seen: list[dict[str, Any] | None] = []
    fake = SizedBox(db_bytes=GB, step_s={}, jobs=0)

    def run(argv: list[str], **kw: Any) -> str:
        if argv[:2] == ["docker", "run"]:
            seen.append(wd.maintenance_state(deploy))
        return fake(argv, **kw)

    cfg = _cfg(tmp_path, deploy=deploy, targets=[tmp_path / "nas"], quiesce="pause")
    res = bs.nightly(cfg, bs.ComposeOps(deploy, run).make_backup(cfg), lambda e, d: None, now=T0,
                     classify=_offbox({"nas"}))  # fmt: skip
    assert res["ok"] and _verbs(fake.calls) == ["pause", "unpause"]
    assert seen and seen[0] is not None and seen[0]["by"] == "backup" and seen[0]["pid"] == os.getpid()
    assert wd.maintenance_state(deploy) is None and not (deploy / "watchdog" / wd.MAINTENANCE).exists()


def test_pgbackrest_gets_its_limit_from_the_size_of_every_database(tmp_path: Path) -> None:
    deploy = _deploy(tmp_path)
    fake = SizedBox(db_bytes=50 * GB, step_s={"pgbackrest": 5 * HOUR})
    bs.ComposeOps(deploy, fake).pgbackrest("full")  # 4 h before D-455: this full backup was killed
    assert fake.timeouts["pgbackrest"] == pytest.approx(900 + 100 * GB / 5e6)


# ------------------------------------------------------------------------------------------------ retention
def _file(d: Path, stamp: str, size: int) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"trialbox-CGMH-{stamp}{bs.SUFFIX}"
    f.write_bytes(b"x" * size)
    bs.sidecar(f).write_text(f"{'a' * 64}  {f.name}\n")
    return f


def test_a_target_keeps_backups_by_count_and_by_size_and_always_the_newest(tmp_path: Path) -> None:
    nas = tmp_path / "nas"
    files = [_file(nas, f"2026110{i}T194500Z", 100) for i in range(1, 6)]
    other = nas / f"trialbox-OTHER-20261101T194500Z{bs.SUFFIX}"
    other.write_bytes(b"x" * 100)
    gone = bs.prune(nas, keep=4, prefix="trialbox-CGMH-", max_bytes=250)
    assert files[0] in gone and files[1] in gone and files[2] in gone  # 4 by count, then 2 by size
    assert [f.exists() for f in files] == [False, False, False, True, True] and other.exists()
    assert not bs.sidecar(files[0]).exists()
    bs.prune(nas, keep=4, prefix="trialbox-CGMH-", max_bytes=10)  # the newest stays, whatever its size
    assert [f.exists() for f in files] == [False, False, False, False, True]
    cfg = _cfg(tmp_path, keep_share=0.5)
    assert cfg.keep_bytes(nas) == pytest.approx(__import__("shutil").disk_usage(nas).total * 0.5, rel=1e-6)


# ------------------------------------------------------------------------------------------------ the update path
def test_the_update_paths_dumps_and_container_get_limits_from_size(tmp_path: Path, monkeypatch: Any) -> None:
    """F-03 (rest): the two dumps had no limit and the container 7,200 s. Now both come from the size."""
    deploy = _deploy(tmp_path, f"TB_BACKUP_TARGETS={tmp_path / 'nas'}\n")
    (deploy / "secrets").mkdir()
    (deploy / "secrets" / "backup.pub").write_text("pub")
    vols = tmp_path / "vols"
    for v in up.BACKUP_VOLUMES.values():
        (vols / f"trialbox_{v}" / "_data").mkdir(parents=True)
    (vols / "trialbox_lake-data" / "_data" / "big.parquet").write_bytes(b"x" * 5_000_000)
    monkeypatch.setenv("TB_DOCKER_VOLUMES", str(vols))
    seen: dict[str, float | None] = {}

    def run(argv: list[str], stdout_file: Path | None = None, timeout: float | None = None, **_: Any) -> str:
        line = " ".join(argv)
        if "pg_database_size" in line:
            return f"{10 * GB}\n"
        if "pg_dump" in line:
            seen[argv[-1]] = timeout
            Path(str(stdout_file)).write_bytes(b"d" * 1_000_000)
        if argv[:2] == ["docker", "run"]:
            seen["container"] = timeout
        return ""

    up.ComposeBox(deploy, run=run).backup(None, tmp_path)  # type: ignore[arg-type]
    assert seen["trialbox_wf"] == seen["hapi"] == pytest.approx(900 + 10 * GB / 5e6)
    assert seen["container"] == pytest.approx(900 + (2_000_000 + 5_000_000) / 5e6, abs=1)


# ------------------------------------------------------------------------------------------------ the console
def _ops_box(tmp_path: Path, monkeypatch: Any, run: Any) -> tb_ops.Box:
    deploy = _deploy(tmp_path, f"TB_BACKUP_TARGETS={tmp_path / 'nas'}\nTB_ENV=DEV\n")
    (deploy / "secrets").mkdir(exist_ok=True)
    pub = _cfg(tmp_path).public_key
    (deploy / "secrets" / "backup.pub").write_bytes(pub.read_bytes())
    monkeypatch.setattr(bs, "ComposeOps", lambda d, r=None, _real=bs.ComposeOps: _real(d, run))
    monkeypatch.setattr(up, "run_cmd", run)
    return tb_ops.Box("compose", deploy, {"TB_BACKUP_TARGETS": str(tmp_path / "nas")})


def test_the_consoles_backup_stops_and_pauses_nothing_and_is_recorded(tmp_path: Path, monkeypatch: Any) -> None:
    fake = SizedBox(db_bytes=GB, step_s={}, jobs=3)
    box = _ops_box(tmp_path, monkeypatch, fake)
    summary, lines = tb_ops.OpsRunner(box, tb_ops.OpsDir(tmp_path / "ops")).do_backup({"mode": "running"})
    assert "no service was stopped" in summary and any("step limit trialbox_wf" in ln for ln in lines)
    assert not set(_verbs(fake.calls)) & {"pause", "stop", "start"}
    last = json.loads((box.deploy / "site" / "backup-last.json").read_text())
    assert last["ok"] and last["point_in_time"]["held"] is False and "pgbackrest" not in last


def test_the_consoles_backup_waits_for_a_running_nightly(tmp_path: Path, monkeypatch: Any) -> None:
    box = _ops_box(tmp_path, monkeypatch, SizedBox(db_bytes=GB, step_s={}))
    with bs._lock(box.deploy) as mine:
        assert mine
        with pytest.raises(tb_ops.OpsFailed, match="another backup run"):
            tb_ops.OpsRunner(box, tb_ops.OpsDir(tmp_path / "ops")).do_backup({"mode": "running"})


def test_an_old_stop_request_is_refused_while_a_job_runs(tmp_path: Path, monkeypatch: Any) -> None:
    fake = SizedBox(db_bytes=GB, step_s={}, jobs=1)
    monkeypatch.setattr(up, "ComposeBox", lambda d, run=fake, _real=up.ComposeBox: _real(d, run))
    box = _ops_box(tmp_path, monkeypatch, fake)
    with pytest.raises(tb_ops.OpsFailed, match="1 job"):
        tb_ops.OpsRunner(box, tb_ops.OpsDir(tmp_path / "ops")).do_backup({})
    assert "stop" not in _verbs(fake.calls)


def test_the_console_sends_the_running_mode() -> None:
    src = (Path(__file__).resolve().parents[2] / "services" / "console" / "ops_pages.py").read_text()
    assert 'args["mode"] = "running"' in src


# ------------------------------------------------------------------------------------------------ the watchdog
class InspectDocker:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self.docs, self.calls = docs, []  # type: ignore[var-annotated]

    def __call__(self, argv: Any, timeout: float) -> str:
        self.calls.append(list(argv))
        if "ps" in argv:
            return "\n".join(d["Id"] for d in self.docs)
        if "inspect" in argv:
            return json.dumps(self.docs)
        return ""


def _doc(service: str, paused: bool = False, health: str = "unhealthy") -> dict[str, Any]:
    return {"Id": f"{service}-id", "Name": f"/trialbox-{service}-1",
            "Config": {"Labels": {wd.SERVICE_LABEL: service, wd.LABEL: "restart"}},
            "State": {"Status": "paused" if paused else "running", "Paused": paused,
                      "Health": {"Status": health, "FailingStreak": 9, "Log": [{"ExitCode": 1}]}}}  # fmt: skip


def _dog(tmp_path: Path, docker: InspectDocker, clock: list[float], dry: bool) -> wd.Watchdog:
    # a dry run keeps no state between passes, so it acts on an unhealthy container at once (after 0 minutes)
    return wd.Watchdog(tmp_path / "deploy", run=docker, audit=lambda e: None, clock=lambda: clock[0], dry_run=dry,
                       after_minutes=0 if dry else 2.0, out=lambda m: None)  # fmt: skip


def test_the_watchdogs_dry_run_reports_no_restart_for_a_paused_container(tmp_path: Path) -> None:
    """The card's acceptance: a paused container (its probe times out, so Docker calls it unhealthy) is not restarted,
    however long it stays paused; an unpaused unhealthy one still is."""
    docker = InspectDocker([_doc("orchestrator", paused=True), _doc("gateway")])
    clock = [1_000_000.0]
    dog = _dog(tmp_path, docker, clock, dry=True)
    dog.tick()
    clock[0] += 6 * 60
    acts = {a["service"]: a["action"] for a in dog.tick()}
    assert acts == {"orchestrator": "paused", "gateway": "would_restart"}
    live = _dog(tmp_path, docker, clock, dry=False)
    live.tick()
    clock[0] += 6 * 60
    live.tick()
    assert [c[-1] for c in docker.calls if "restart" in c] == ["gateway-id"]


def test_the_maintenance_flag_stops_restarts_and_a_stale_one_is_ignored(tmp_path: Path) -> None:
    docker = InspectDocker([_doc("gateway")])
    clock = [1_000_000.0]
    deploy = tmp_path / "deploy"
    with wd.maintenance(deploy, "backup", "services paused"):
        dog = _dog(tmp_path, docker, clock, dry=False)
        dog.tick()
        clock[0] += 6 * 60
        assert [a["action"] for a in dog.tick()] == ["maintenance"]
    assert not any("restart" in c for c in docker.calls)
    # a person's flag (no pid) holds; a killed holder's flag (its pid is gone) is ignored and removed
    flag = deploy / "watchdog" / wd.MAINTENANCE
    flag.write_text(json.dumps({"by": "IT", "why": "disk swap"}))
    assert [a["action"] for a in _dog(tmp_path, docker, clock, dry=True).tick()] == ["maintenance"]
    dead = subprocess.Popen(["true"])
    dead.wait()
    flag.write_text(json.dumps({"by": "backup", "why": "services paused", "pid": dead.pid}))
    assert [a["action"] for a in _dog(tmp_path, docker, clock, dry=True).tick()] == ["would_restart"]
    assert flag.exists()  # a dry run changes nothing
    _dog(tmp_path, docker, clock, dry=False).tick()
    assert not flag.exists() and any("restart" in c for c in docker.calls)


# ------------------------------------------------------------------------------------------------ consistency
def test_a_backup_taken_while_the_box_writes_restores_exactly_its_snapshot(tmp_path: Path, db_url: str) -> None:
    """D-455's promise without a pause: rows and files are written all through the backup (here: a writer thread,
    started before the backup and stopped after it), and the restore gives back exactly the rows the snapshot counted
    (the restore checks every table against the manifest, and fails otherwise), the files as read, and nothing torn."""
    from tb_common.db import Database

    from tools.trialbox import backup as bk

    db = Database.connect(db_url, "site")
    db.migrate(["CREATE TABLE marks (n BIGINT PRIMARY KEY, note TEXT NOT NULL)"])
    db.execute("INSERT INTO marks VALUES (?, ?)", (0, "before"))
    dirs = {"audit": tmp_path / "audit", "lake": tmp_path / "lake"}
    for d in dirs.values():
        d.mkdir()
    log = dirs["audit"] / "log.jsonl"
    log.write_text('{"n": 0}\n')
    (dirs["lake"] / "patient.parquet").write_bytes(b"PAR1" + bytes(range(256)) * 8000)
    priv, pub = tmp_path / "usb" / "it.key", tmp_path / "box" / "backup.pub"
    bk.keygen(priv, pub)
    stop, written = threading.Event(), [0]

    def writer() -> None:
        w = Database.connect(db_url, "site")
        n = 0
        while not stop.is_set():
            n += 1
            w.execute("INSERT INTO marks VALUES (?, ?)", (n, f"during {n}"))
            with log.open("a") as fh:
                fh.write(json.dumps({"n": n}) + "\n")
            (dirs["lake"] / f"part-{n}.parquet").write_bytes(b"PAR1" * 64)
            written[0] = n

    t = threading.Thread(target=writer, daemon=True)
    t.start()
    try:
        while written[0] < 5:  # the box is writing before the backup starts
            threading.Event().wait(0.01)
        env = {"TB_DB_URL": db_url, "TB_SITE_ID": "CGMH"}
        f = bk.backup([tmp_path / "nas"], pub, env=env, dirs=dirs, now=datetime.now(UTC))[0]
        at_end = written[0]
    finally:
        stop.set()
        t.join()
    assert written[0] > at_end >= 5  # the writer ran during and after the backup: nothing was held still
    m = bk.unpack(f, priv, tmp_path / "x")
    counted = m["databases"]["trialbox_wf"]["rows"][f"{db.schema}.marks"][0]
    assert 1 <= counted <= at_end + 1
    out = bk.restore(f, priv, env={"TB_DB_URL": db_url}, dirs=dirs, no_copy=True)
    assert out["ok"] and out["warnings"] == []
    rows = Database.connect(db_url, "site").fetchall("SELECT n FROM marks ORDER BY n")
    assert [r[0] for r in rows] == list(range(counted))  # a prefix: every row up to the snapshot, none after
    lines = log.read_text().splitlines()
    assert lines and all(json.loads(ln)["n"] == i for i, ln in enumerate(lines))  # the audit file whole, untorn
