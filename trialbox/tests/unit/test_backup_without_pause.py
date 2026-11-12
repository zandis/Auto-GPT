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
    fake = SizedBox(db_bytes=100 * GB, step_s={"snapshot": 3 * HOUR, "copy": 1 * HOUR, "container": 600})
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


def _appended_during_every_read(monkeypatch: pytest.MonkeyPatch, path: Path, grow: Any) -> None:
    """Every read of ``path`` by the backup meets a change made while it reads (``grow`` is called once per try)."""
    from tools.trialbox import backup as bk

    real = bk._HashReader.read
    grown: set[int] = set()

    def read(self: Any, size: int = -1) -> bytes:
        out = real(self, size)
        if id(self) not in grown and out:  # one reader per try: its first bytes are read, then the file changes
            grown.add(id(self))
            grow()
        return out

    monkeypatch.setattr(bk._HashReader, "read", read)


def test_an_audit_file_appended_to_during_every_read_is_taken_up_to_a_line_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The audit chain is appended to all night (every model call writes a line). A day file that grew while it
    was read is not "kept changing": the bytes read are a whole earlier state of an append-only file, cut at a line
    end. (The test above failed under load with "log.jsonl kept changing while it was backed up (3 reads)".)"""
    import tarfile

    from tools.trialbox import backup as bk

    day = tmp_path / "2026-11-12.jsonl"
    day.write_text("".join(json.dumps({"n": i}) + "\n" for i in range(50)) + '{"n": 50, "torn')  # a line being written
    n = [50]

    def grow() -> None:
        n[0] += 1
        with day.open("a") as fh:
            fh.write(json.dumps({"n": n[0]}) + "\n")

    _appended_during_every_read(monkeypatch, day, grow)
    with tarfile.open(tmp_path / "a.tar", "w") as tar:
        sha, size = bk._add(tar, day, "dirs/audit/2026-11-12.jsonl")
    with tarfile.open(tmp_path / "a.tar") as tar:
        got = tar.extractfile("dirs/audit/2026-11-12.jsonl").read()  # type: ignore[union-attr]
    import hashlib

    assert len(got) == size and hashlib.sha256(got).hexdigest() == sha
    lines = got.decode().splitlines()
    assert got.endswith(b"\n") and [json.loads(ln)["n"] for ln in lines] == list(range(50))  # whole lines, a prefix


def test_any_other_file_that_keeps_changing_still_fails_the_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rule is the audit chain's only: a file that may be rewritten in place (a DuckDB file, a list) is read
    again and, if it never holds still, fails the backup. So does an audit file that was replaced or cut back."""
    import tarfile

    from tools.trialbox import backup as bk

    f = tmp_path / "list.jsonl"
    f.write_text('{"n": 0}\n')

    def grow() -> None:
        with f.open("a") as fh:
            fh.write('{"n": 1}\n')

    _appended_during_every_read(monkeypatch, f, grow)
    with tarfile.open(tmp_path / "a.tar", "w") as tar, pytest.raises(bk.BackupError, match="kept changing"):
        bk._add(tar, f, "dirs/lake/list.jsonl")

    day = tmp_path / "2026-11-12.jsonl"
    day.write_text('{"n": 0}\n{"n": 1}\n')

    turn = [0]

    def rewritten() -> None:  # not an append: the same file, longer, but its beginning is no longer what was read
        turn[0] += 1
        day.write_text("".join(json.dumps({"n": turn[0] * 10 + i}) + "\n" for i in range(turn[0] + 3)))

    _appended_during_every_read(monkeypatch, day, rewritten)
    with tarfile.open(tmp_path / "b.tar", "w") as tar, pytest.raises(bk.BackupError, match="kept changing"):
        bk._add(tar, day, "dirs/audit/2026-11-12.jsonl")


# ------------------------------------------------------------------------------------------------ review fixes
def _sidecar_ok(f: Path) -> bool:
    import hashlib

    side = f.with_name(f.name + ".sha256")
    return side.is_file() and side.read_text().split()[0] == hashlib.sha256(f.read_bytes()).hexdigest()


def _lake_files(lake: Path, gen: str, tables: tuple[str, ...]) -> None:
    import hashlib

    for rel, data in [("db/S.duckdb", f"DUCK {gen}".encode() * 1000),
                      *[(f"parquet/snapshot=S/{t}.parquet", f"PAR1 {t} {gen}".encode() * 500) for t in tables]]:  # fmt: skip
        f = lake / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
        f.with_name(f.name + ".sha256").write_text(f"{hashlib.sha256(data).hexdigest()}  {f.name}\n")


def _swap(lake: Path) -> None:
    """A rebuild's swap of snapshot S, as lake.store does it: several renames under the lake's lock."""
    import fcntl

    with (lake / ".rebuild.lock").open("a") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        new = lake / "new"
        _lake_files(new, "new", ("a", "c"))
        for f in (lake / "parquet" / "snapshot=S").iterdir():
            f.unlink()
        for f in sorted((new / "parquet" / "snapshot=S").iterdir()):
            f.rename(lake / "parquet" / "snapshot=S" / f.name)
        (new / "db" / "S.duckdb").rename(lake / "db" / "S.duckdb")
        (new / "db" / "S.duckdb.sha256").rename(lake / "db" / "S.duckdb.sha256")
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _swap_during_read(monkeypatch: Any, lake: Path, bk: Any) -> list[threading.Thread]:
    """Start the swap right after db/S.duckdb is read; give it time to run if nothing holds it back."""
    real, started = bk._add, list[threading.Thread]()

    def add(tar: Any, path: Path, arcname: str) -> Any:
        out = real(tar, path, arcname)
        if arcname == "dirs/lake/db/S.duckdb" and not started:
            t = threading.Thread(target=_swap, args=(lake,))
            t.start()
            started.append(t)
            t.join(0.5)  # without the lake lock the swap is done here, between two reads of the backup
        return out

    monkeypatch.setattr(bk, "_add", add)
    return started


def test_a_rebuild_swap_waits_for_the_lakes_read_and_the_restored_lake_passes_its_check(
    tmp_path: Path, db_url: str, monkeypatch: Any
) -> None:
    """Review H1: the lake was listed once and read file by file without the lake's lock, so a swap in the middle
    gave the old DuckDB file with the new sidecar and a mix of Parquet files: a "good" backup whose restored lake
    failed its own check. Now the swap waits for the lake's served files to be read."""
    from tb_common.db import Database

    from tools.trialbox import backup as bk

    Database.connect(db_url, "site").migrate(["CREATE TABLE marks (n BIGINT PRIMARY KEY)"])
    lake = tmp_path / "lake"
    _lake_files(lake, "old", ("a", "b"))
    (lake / ".rebuild.lock").write_text("")
    priv, pub = tmp_path / "it.key", tmp_path / "box.pub"
    bk.keygen(priv, pub)
    started = _swap_during_read(monkeypatch, lake, bk)
    env = {"TB_DB_URL": db_url, "TB_SITE_ID": "CGMH"}
    f = bk.backup([tmp_path / "nas"], pub, env=env, dirs={"lake": lake})[0]
    started[0].join()
    assert (lake / "parquet" / "snapshot=S" / "c.parquet").exists()  # the swap did happen, after the read
    out = tmp_path / "x"
    bk.unpack(f, priv, out)
    got = out / "dirs" / "lake"
    files = sorted(p.name for p in (got / "parquet" / "snapshot=S").glob("*.parquet"))
    assert files == ["a.parquet", "b.parquet"]  # one state: all old
    assert all(_sidecar_ok(p) for p in [got / "db" / "S.duckdb", *(got / "parquet" / "snapshot=S").glob("*.parquet")])
    res = bk.restore(f, priv, env={"TB_DB_URL": db_url}, dirs={"lake": tmp_path / "restored"}, no_copy=True)
    assert res["lake_check"] == {"snapshots": 1, "problems": [], "unsigned": 0, "checked": True}


def test_without_the_lake_lock_a_swap_mid_read_fails_the_backup(tmp_path: Path, db_url: str, monkeypatch: Any) -> None:
    import contextlib as cl

    from tb_common.db import Database

    from tools.trialbox import backup as bk

    Database.connect(db_url, "site").migrate(["CREATE TABLE marks (n BIGINT PRIMARY KEY)"])
    lake = tmp_path / "lake"
    _lake_files(lake, "old", ("a", "b"))
    priv, pub = tmp_path / "it.key", tmp_path / "box.pub"
    bk.keygen(priv, pub)
    monkeypatch.setattr(bk, "_lake_lock", lambda root: cl.nullcontext(False))  # a lake whose lock cannot be had
    started = _swap_during_read(monkeypatch, lake, bk)
    with pytest.raises(bk.BackupError, match="lake (changed|file)"):
        bk.backup([tmp_path / "nas"], pub, env={"TB_DB_URL": db_url, "TB_SITE_ID": "CGMH"}, dirs={"lake": lake})
    started[0].join()
    assert not list((tmp_path / "nas").glob(f"*{bs.SUFFIX}"))


def test_the_lake_check_finds_a_mismatch_and_an_empty_folder(tmp_path: Path) -> None:
    from tools.trialbox import backup as bk

    lake = tmp_path / "lake"
    _lake_files(lake, "old", ("a",))
    assert bk.lake_check(lake) == {"snapshots": 1, "problems": [], "unsigned": 0}
    (lake / "parquet" / "snapshot=S" / "a.parquet").write_bytes(b"other")
    (lake / "db" / "T.duckdb").write_bytes(b"x")
    got = bk.lake_check(lake)
    assert any("a.parquet: content does not match" in p for p in got["problems"])
    assert any("snapshot=T: missing" in p for p in got["problems"]) and got["unsigned"] == 1  # T.duckdb: no sidecar


def test_retention_never_prunes_before_the_new_file_is_checked(tmp_path: Path) -> None:
    """Review M1: the size rule ran before the new file's sidecar was checked and always kept the newest file, so a
    cut new file could leave a target with no good backup at all."""
    nas = tmp_path / "nas"
    old = [_file(nas, f"2026110{i}T194500Z", 1000) for i in (1, 2, 3)]
    cfg = _cfg(tmp_path, targets=[nas], keep_share=1e-12, production=False)

    def make(targets: list[Path]) -> list[Path]:
        cut = nas / f"trialbox-CGMH-20261104T194500Z{bs.SUFFIX}"
        cut.write_bytes(b"x" * 10)  # no sidecar: the run was cut
        return [cut]

    res = bs.nightly(cfg, make, lambda e, d: None, now=T0, classify=_offbox({"nas"}))
    assert not res["ok"] and "sidecar" in res["errors"][0]
    assert all(f.exists() for f in old)  # every good backup is still there


def test_the_size_rule_keeps_two_good_backups_and_says_so(tmp_path: Path) -> None:
    nas = tmp_path / "nas"
    files = [_file(nas, f"2026110{i}T194500Z", 1000) for i in (1, 2, 3)]
    cut = nas / f"trialbox-CGMH-20261105T194500Z{bs.SUFFIX}"
    cut.write_bytes(b"x" * 5)  # not a backup: neither counted nor kept as one
    notes: list[str] = []
    bs.prune(nas, keep=10, prefix="trialbox-CGMH-", max_bytes=10, min_good=bs.MIN_GOOD, notes=notes)
    assert [f.exists() for f in files] == [False, True, True] and cut.exists()
    assert notes and "2 newest good backups" in notes[0]

    def make(targets: list[Path]) -> list[Path]:
        return [_file(nas, "20261106T194500Z", 1000)]

    cfg = _cfg(tmp_path, targets=[nas], keep_share=1e-12, production=False)
    res = bs.nightly(cfg, make, lambda e, d: None, now=T0, classify=_offbox({"nas"}))
    assert not res["ok"] and any("TB_BACKUP_KEEP_SHARE" in e for e in res["errors"])
    assert len([f for f in nas.glob(f"*{bs.SUFFIX}") if bs.read_sidecar(f)]) == 2


def test_an_old_stop_request_is_refused_when_the_jobs_cannot_be_counted(tmp_path: Path, monkeypatch: Any) -> None:
    """Review M2: an unknown job count (psql failed) was taken as zero and every service was stopped."""
    fake = SizedBox(db_bytes=GB, step_s={})

    def run(argv: list[str], **kw: Any) -> str:
        if "orch.jobs" in " ".join(argv):
            raise up.UpdateFailed("psql: could not connect")
        return fake(argv, **kw)

    monkeypatch.setattr(up, "ComposeBox", lambda d, run=run, _real=up.ComposeBox: _real(d, run))
    box = _ops_box(tmp_path, monkeypatch, run)
    with pytest.raises(tb_ops.OpsFailed, match="could not be counted"):
        tb_ops.OpsRunner(box, tb_ops.OpsDir(tmp_path / "ops")).do_backup({})
    assert "stop" not in _verbs(fake.calls)


def test_a_restore_lists_the_events_after_the_snapshot_to_reapply(
    tmp_path: Path, db_url: str, monkeypatch: Any
) -> None:
    """Review M3: the audit chain is copied after the database snapshot, so an opt-out typed in between is in the
    restored chain and not in the restored database. The restore lists it, audits the list and is not complete."""
    from tb_common.audit import AuditLog
    from tb_common.db import Database

    from tools.trialbox import backup as bk
    from tools.trialbox.__main__ import main as cli

    db = Database.connect(db_url, "site")
    db.migrate(["CREATE TABLE marks (n BIGINT PRIMARY KEY)"])
    audit = tmp_path / "audit"
    log = AuditLog(audit)
    log.append("console.opt_out", actor="console:steward", detail={"note": "before the backup"})
    priv, pub = tmp_path / "it.key", tmp_path / "box.pub"
    bk.keygen(priv, pub)
    real = bk.take_snapshot

    def snapshot_then_events(src: Any, work: Path, env: Any) -> Any:
        out = real(src, work, env)
        threading.Event().wait(1.1)  # the events come a second after the snapshot
        log.append("console.opt_out", actor="console:steward", detail={"pid": "synthetic"})
        log.append("console.breakglass_open", actor="console:doctor")
        log.append("console.audit_search", actor="console:admin")  # not one whose loss is unsafe
        return out

    monkeypatch.setattr(bk, "take_snapshot", snapshot_then_events)
    f = bk.backup([tmp_path / "nas"], pub, env={"TB_DB_URL": db_url, "TB_SITE_ID": "CGMH"}, dirs={"audit": audit})[0]
    monkeypatch.setattr(bk, "take_snapshot", real)
    out = bk.restore(f, priv, env={"TB_DB_URL": db_url}, dirs={"audit": audit}, no_copy=True)
    assert [e["event"] for e in out["to_reapply"]] == ["console.opt_out", "console.breakglass_open"]
    assert out["complete"] is False and all(set(e) == {"ts", "event", "where"} for e in out["to_reapply"])
    rows = [json.loads(ln) for p in sorted(audit.rglob("*.jsonl")) for ln in p.read_text().splitlines()
            if '"event"' in ln]  # fmt: skip
    (ev,) = [r for r in rows if r["event"] == "backup.restore_reapply"]
    assert ev["detail"]["count"] == 2 and ev["detail"]["since_from"] == "snapshot_at"
    rc = cli(["restore", str(f), "--key", str(priv), "--yes", "--no-copy", "--dir", f"audit={audit}"])
    assert rc == 4  # the restore's exit says it is not complete


def test_the_reapply_event_has_its_label() -> None:
    from console.i18n_audit import EVENTS

    assert len(EVENTS["backup.restore_reapply"]) == 3 and all(EVENTS["backup.restore_reapply"])


def test_a_pause_is_not_taken_when_a_size_cannot_be_measured(tmp_path: Path) -> None:
    """Review M4: a step without a limit under a pause (and the watchdog's flag) could hold the box for ever."""
    deploy = _deploy(tmp_path)
    fake = SizedBox(db_bytes=GB, step_s={}, jobs=0)

    def run(argv: list[str], **kw: Any) -> str:
        if "pg_database_size(current_database())" in " ".join(argv) and "hapi" in argv:
            raise RuntimeError("psql: timeout")
        return fake(argv, **kw)

    cfg = _cfg(tmp_path, deploy=deploy, targets=[tmp_path / "nas"], quiesce="pause")
    res = bs.nightly(cfg, bs.ComposeOps(deploy, run).make_backup(cfg), lambda e, d: None, now=T0,
                     classify=_offbox({"nas"}))  # fmt: skip
    assert res["ok"] and "pause" not in _verbs(fake.calls)
    assert "no size for hapi" in res["point_in_time"]["why"] and not (deploy / "watchdog" / wd.MAINTENANCE).exists()


def test_the_small_queries_have_their_declared_limit(tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def run(argv: list[str], timeout: float | None = None, **_: Any) -> str:
        line = " ".join(argv)
        key = "jobs" if "orch.jobs" in line else "size" if "pg_database_size(current" in line else "cluster"
        seen[key] = timeout
        return "1\n"

    deploy = _deploy(tmp_path, "TB_BACKUP_QUERY_TIMEOUT_S=7\n")
    ops = bs.ComposeOps(deploy, run)
    ops.db_bytes("hapi", "hapi"), ops.running_jobs(), ops.cluster_bytes()
    assert seen == {"size": 7.0, "jobs": 7.0, "cluster": 7.0}
    assert "queued" not in bs.RUNNING_JOBS_SQL  # D-455: a queued job counts too (it would start under a pause)


def test_a_bad_setting_fails_the_run_with_a_record(tmp_path: Path) -> None:
    deploy = _deploy(tmp_path)
    cfg = bs.config(deploy, {"TB_BACKUP_MIN_MBPS": "0", "TB_BACKUP_STEP_START_S": "fast", "TB_BACKUP_KEEP_SHARE": "2"},
                    process_env=False)  # fmt: skip
    events: list[str] = []
    res = bs.nightly(cfg, lambda t: [], lambda e, d: events.append(e), now=T0)
    assert not res["ok"] and events == ["backup.failed"]
    assert any("TB_BACKUP_MIN_MBPS='0' must be above 0" in e for e in res["errors"])
    assert any("TB_BACKUP_STEP_START_S='fast' is not a number" in e for e in res["errors"])
    assert any("TB_BACKUP_KEEP_SHARE='2'" in e for e in res["errors"])
    assert json.loads(cfg.last_file.read_text())["ok"] is False


def test_a_reused_pid_does_not_keep_the_flag_and_paused_services_are_printed(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    flag = deploy / "watchdog" / wd.MAINTENANCE
    flag.parent.mkdir(parents=True)
    flag.write_text(json.dumps({"by": "backup", "why": "x", "pid": os.getpid(), "pid_start": "1"}))  # not this one
    assert wd.maintenance_state(deploy) is None
    with wd.maintenance(deploy, "backup", "x"):
        assert wd.maintenance_state(deploy) is not None  # this process, its own start time
    said: list[str] = []
    docker = InspectDocker([_doc("orchestrator", paused=True)])
    wd.Watchdog(deploy, run=docker, audit=lambda e: None, out=said.append).tick()
    assert any("paused orchestrator" in s for s in said)


# ------------------------------------------------------------------------------------------------ R1: the wait
class JobsBox(SizedBox):
    """The box whose job count follows ``counts`` (one value per question; the last one stays); None: unknown."""

    def __init__(self, counts: list[int | None]) -> None:
        super().__init__(db_bytes=GB, step_s={})
        self.counts = counts
        self.asked_at: list[str] = []

    def __call__(self, argv: list[str], **kw: Any) -> str:  # type: ignore[override]
        line = " ".join(argv)
        if argv[-1] == bs.JOBS_LIST_SQL:
            return "J-17|SCREEN\nJ-18|MICROBATCH\n"
        if "orch.jobs" in line:
            self.calls.append(list(argv))
            n = self.counts.pop(0) if len(self.counts) > 1 else self.counts[0]
            if n is None:
                raise RuntimeError("psql: could not connect")
            return f"{n}\n"
        return super().__call__(argv, **kw)


def _waiting_ops(deploy: Path, box: JobsBox) -> tuple[bs.ComposeOps, list[float]]:
    ops = bs.ComposeOps(deploy, box)
    t = [0.0]
    ops.clock = lambda: t[0]

    def sleep(s: float) -> None:
        t[0] += s

    ops.sleep = sleep
    return ops, t


def test_the_nightly_waits_while_a_job_runs_then_goes_on_when_it_ends(tmp_path: Path) -> None:
    """The owner's ruling on R1: the backup waits while a job runs (queued ones count) before its snapshot."""
    deploy = _deploy(tmp_path)
    box = JobsBox([2, 1, 1, 0])
    ops, t = _waiting_ops(deploy, box)
    cfg = _cfg(tmp_path, deploy=deploy, targets=[tmp_path / "nas"], job_wait_s=6 * HOUR)
    events: list[tuple[str, dict[str, Any]]] = []
    res = bs.nightly(cfg, ops.make_backup(cfg), lambda e, d: events.append((e, d)), now=T0, classify=_offbox({"nas"}))
    assert res["ok"], res["errors"]
    assert t[0] == 3 * bs.JOB_POLL_S and res["point_in_time"]["waited_s"] == 3 * bs.JOB_POLL_S
    assert "beside_jobs" not in res["point_in_time"] and events[0][1]["beside_jobs"] is None
    i_last_count = max(i for i, c in enumerate(box.calls) if "orch.jobs" in " ".join(c))
    i_snap = next(i for i, c in enumerate(box.calls) if "psql -X -q" in " ".join(c))
    assert i_last_count < i_snap  # the snapshot came after the last job ended


def test_at_the_bound_the_snapshot_is_taken_beside_the_job_and_recorded(tmp_path: Path) -> None:
    deploy = _deploy(tmp_path)
    box = JobsBox([2])
    ops, t = _waiting_ops(deploy, box)
    cfg = _cfg(tmp_path, deploy=deploy, targets=[tmp_path / "nas"], job_wait_s=600.0)
    events: list[tuple[str, dict[str, Any]]] = []
    res = bs.nightly(cfg, ops.make_backup(cfg), lambda e, d: events.append((e, d)), now=T0, classify=_offbox({"nas"}))
    assert res["ok"], res["errors"]  # never skipped: the snapshot is consistent on its own
    assert t[0] == 600.0
    beside = res["point_in_time"]["beside_jobs"]
    assert beside == {"count": 2, "jobs": [{"job_id": "J-17", "type": "SCREEN"}, {"job_id": "J-18", "type": "MICROBATCH"}],
                      "waited_s": 600.0, "bound_s": 600.0}  # fmt: skip
    assert json.loads(cfg.last_file.read_text())["point_in_time"]["beside_jobs"]["count"] == 2
    assert events[0][0] == "backup.done" and events[0][1]["beside_jobs"]["jobs"][0]["job_id"] == "J-17"


def test_an_unknown_job_count_waits_like_a_running_job(tmp_path: Path) -> None:
    deploy = _deploy(tmp_path)
    box = JobsBox([None, None, 0])
    ops, t = _waiting_ops(deploy, box)
    cfg = _cfg(tmp_path, deploy=deploy, targets=[tmp_path / "nas"], job_wait_s=6 * HOUR)
    res = bs.nightly(cfg, ops.make_backup(cfg), lambda e, d: None, now=T0, classify=_offbox({"nas"}))
    assert res["ok"] and t[0] == 2 * bs.JOB_POLL_S and "beside_jobs" not in res["point_in_time"]
    box2 = JobsBox([None])
    ops2, t2 = _waiting_ops(deploy, box2)
    cfg2 = _cfg(tmp_path, deploy=deploy, targets=[tmp_path / "nas2"], job_wait_s=300.0)  # a new target: a new file
    res2 = bs.nightly(cfg2, ops2.make_backup(cfg2), lambda e, d: None, now=T0, classify=_offbox({"nas2"}))
    assert res2["ok"] and t2[0] == 300.0 and res2["point_in_time"]["beside_jobs"]["count"] is None


def test_the_wait_bound_is_declared_from_the_schedule() -> None:
    assert bs.JOB_WAIT_S == 6 * HOUR  # (36 h age alert - 24 h cron interval) / 2
    assert bs.config(Path("/x"), {}, process_env=False).job_wait_s == 6 * HOUR
    assert bs.config(Path("/x"), {"TB_BACKUP_JOB_WAIT_S": "0"}, process_env=False).job_wait_s == 0
    assert bs.config(Path("/x"), {"TB_BACKUP_JOB_WAIT_S": "-1"}, process_env=False).setting_errors
