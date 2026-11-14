"""BACKUP-RESTORE (D-724), finding DATA-009 of lane G's review of 2026-11-13: a backup taken while the box writes
its audit chain must hold a chain and a head anchor that agree.

The backup copied the day file (``audit/<day>.jsonl``) and then ``HEAD.json`` (the walk's order: digits before
``H``). One event written in between gave a copy whose head anchor says one event more than its chain: ``verify``
fails, and a restore of that backup raised ``AuditAnchorBroken`` after the databases and folders were already in
place. The drill could not see it: its box is idle while it backs up."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from tb_common import audit
from tb_common.audit import AuditLog
from tb_common.db import Database

from tests.unit.test_backup import _backup
from tools.trialbox import backup as bk

AT = datetime(2026, 11, 14, 1, 0, tzinfo=UTC)


@pytest.fixture
def box(tmp_path: Path, db_url: str) -> dict[str, Any]:
    """As tests/unit/test_backup.py's: a database with rows, an audit folder and a lake, and a key pair."""
    db = Database.connect(db_url, "site")
    db.migrate(["CREATE TABLE marks (pid TEXT PRIMARY KEY, mark TEXT NOT NULL, note TEXT)"])
    db.execute("INSERT INTO marks VALUES (?, ?, ?)", ("P1", "approach", "a note"))
    dirs = {"audit": tmp_path / "audit", "lake": tmp_path / "lake"}
    (dirs["audit"] / "2026").mkdir(parents=True)
    (dirs["audit"] / "2026" / "log.jsonl").write_text('{"e": 1}\n', encoding="utf-8")
    dirs["lake"].mkdir()
    (dirs["lake"] / "patient.parquet").write_bytes(b"PAR1" + bytes(range(256)) * 50)
    priv, pub = tmp_path / "usb" / "backup.key", tmp_path / "box" / "backup.pub"
    fp = bk.keygen(priv, pub)
    return {"db": db, "dirs": dirs, "priv": priv, "pub": pub, "fp": fp, "url": db_url}


def _chain(directory: Path, n: int) -> AuditLog:
    log = AuditLog(directory, tz="UTC")
    for i in range(n):
        log.append("test.event", ts=AT, actor="test", detail={"i": i})
    return log


def _copied_audit(box: dict[str, Any], tmp_path: Path, files: list[Path]) -> Path:
    into = tmp_path / "unpacked"
    bk.unpack(files[0], box["priv"], into)
    return into / "dirs" / "audit"


def _fresh_chain(box: dict[str, Any], n: int = 3) -> tuple[Path, AuditLog]:
    audit_dir = box["dirs"]["audit"]
    (audit_dir / "2026" / "log.jsonl").unlink()  # the fixture's line is not a chain; these tests write a real one
    (audit_dir / "2026").rmdir()
    return audit_dir, _chain(audit_dir, n)


def _verifies(box: dict[str, Any], tmp_path: Path, files: list[Path]) -> audit.VerifyResult:
    res = audit.verify(_copied_audit(box, tmp_path, files))
    assert res.ok, res.errors
    assert audit.verify(box["dirs"]["audit"]).ok  # and the box's own chain is whole
    return res


def test_an_event_written_between_the_day_file_and_the_head_anchor(
    box: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The finding as it was: the day file copied, an event written, then the head anchor copied."""
    _, log = _fresh_chain(box)
    real = bk._add
    wrote: list[str] = []

    def add_then_write(tar: Any, path: Path, arcname: str, *a: Any, **kw: Any) -> tuple[str, int]:
        out = real(tar, path, arcname, *a, **kw)
        if arcname.startswith("dirs/audit/") and arcname.endswith(".jsonl") and not wrote:
            log.append("test.event", ts=AT, actor="test", detail={"i": "during"})
            wrote.append(arcname)
        return out

    monkeypatch.setattr(bk, "_add", add_then_write)
    files = _backup(box, tmp_path)
    assert wrote
    assert _verifies(box, tmp_path, files).lines == 3  # the chain as it stood at the moment


def test_a_new_day_file_started_after_the_folder_was_listed(
    box: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Found by the review, by running (1 backup in 25 with the day moving): the folder was listed before the
    moment; an event of a new day written in between made a day file the copy did not know, while the head anchor
    read at the moment pointed into it."""
    _, log = _fresh_chain(box)
    real = bk.select_files
    wrote: list[str] = []

    def list_then_write(name: str, root: Path) -> Any:
        out = real(name, root)
        if name == "audit" and not wrote:
            log.append("test.event", ts=AT + timedelta(days=1), actor="test", detail={"i": "next day"})
            wrote.append(name)
        return out

    monkeypatch.setattr(bk, "select_files", list_then_write)
    files = _backup(box, tmp_path)
    assert wrote
    res = _verifies(box, tmp_path, files)
    assert res.lines == 4 and res.files == 2  # the new day's file is in the backup, with its event


def test_the_first_event_ever_written_after_the_folder_was_listed(
    box: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audit_dir = box["dirs"]["audit"]
    (audit_dir / "2026" / "log.jsonl").unlink()
    (audit_dir / "2026").rmdir()
    real = bk.select_files
    wrote: list[str] = []

    def list_then_write(name: str, root: Path) -> Any:
        out = real(name, root)
        if name == "audit" and not wrote:
            AuditLog(audit_dir, tz="UTC").append("test.event", ts=AT, actor="test", detail={})
            wrote.append(name)
        return out

    monkeypatch.setattr(bk, "select_files", list_then_write)
    files = _backup(box, tmp_path)
    assert _verifies(box, tmp_path, files).lines == 1


def test_a_torn_last_line_repaired_between_the_moment_and_the_copy(
    box: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Found by the review, by running: the length read at the moment ran past the last whole line; the writer then
    cut the torn tail and wrote new events, and the copy took them up to that length."""
    audit_dir, log = _fresh_chain(box)
    (day,) = audit_dir.glob("*.jsonl")
    with day.open("ab") as fh:
        fh.write(b'{"ts": "2026-11-14T01:00:00+00:00", "event": "torn' + b"x" * 3000)  # a write cut by a crash
    real = bk._add
    wrote: list[str] = []

    def write_then_add(tar: Any, path: Path, arcname: str, *a: Any, **kw: Any) -> tuple[str, int]:
        if arcname.startswith("dirs/audit/") and arcname.endswith(".jsonl") and not wrote:
            log.append("test.event", ts=AT, actor="test", detail={"i": "after the repair"})  # cuts the tail first
            log.append("test.event", ts=AT, actor="test", detail={"i": "and one more"})
            wrote.append(arcname)
        return real(tar, path, arcname, *a, **kw)

    monkeypatch.setattr(bk, "_add", write_then_add)
    files = _backup(box, tmp_path)
    assert wrote
    assert _verifies(box, tmp_path, files).lines == 3


def test_the_backup_never_creates_the_writers_lock_file(box: dict[str, Any], tmp_path: Path) -> None:
    """The backup runs as root: a lock file it made would be root's, and the writer (another user) could not open
    it to write its next event."""
    audit_dir = box["dirs"]["audit"]
    assert not (audit_dir / ".lock").exists()
    _backup(box, tmp_path)
    assert not (audit_dir / ".lock").exists()


# ------------------------------------------------------------------------- DATA-010: a restore keeps file owners
def _env(box: dict[str, Any]) -> dict[str, str]:
    return {"TB_DB_URL": str(box["url"]), "TB_SITE_ID": "CGMH"}


def test_a_restore_gives_each_file_and_folder_the_owner_it_had(
    box: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lane G (DATA-010, verified by running): a restore run as root of a 10001-owned file gave owner 0; the services
    run as 10001 and could not write their volumes after it. The owner each file had is in the backup (its tar
    member); the restore gives it back, and a folder it makes gets the owner of the folder it replaces."""
    import tarfile

    real_info = tarfile.TarFile.gettarinfo

    def as_the_service(self: tarfile.TarFile, *a: Any, **kw: Any) -> tarfile.TarInfo:
        info = real_info(self, *a, **kw)
        if info.name.startswith("dirs/"):
            info.uid, info.gid = 10001, 10002  # what the services' volumes hold on a box
        return info

    monkeypatch.setattr(tarfile.TarFile, "gettarinfo", as_the_service)
    files = _backup(box, tmp_path)
    monkeypatch.setattr(tarfile.TarFile, "gettarinfo", real_info)
    tops = {d: (box["dirs"][d].stat().st_uid, box["dirs"][d].stat().st_gid) for d in ("audit", "lake")}
    given: dict[str, tuple[int, int]] = {}
    monkeypatch.setattr(bk, "_chown", lambda p, uid, gid: given.__setitem__(str(p), (uid, gid)))
    monkeypatch.setattr(bk, "_is_root", lambda: True)
    out = bk.restore(files[0], box["priv"], env=_env(box), dirs=box["dirs"], public_key=box["pub"],
                     keep_to=tmp_path / "kept", running=lambda: ["db"])  # fmt: skip
    assert out["ok"]
    m = bk.unpack(files[0], box["priv"], tmp_path / "again")
    for dname in ("audit", "lake"):
        root = box["dirs"][dname]
        folder = tops[dname]
        for p in root.rglob("*"):
            if p.is_file():
                in_backup = f"dirs/{dname}/{p.relative_to(root)}" in m["files"]
                # a file of the backup: the owner it had; a file the restore wrote itself (its audit event, the
                # writer's lock file): the owner of the folder it replaced
                assert given.get(str(p)) == ((10001, 10002) if in_backup else folder), p
        for p in [root, *(q for q in root.rglob("*") if q.is_dir())]:
            assert str(p) in given, p  # every folder too (copytree and mkdir make them as root)
    audit_dir = box["dirs"]["audit"]
    written = [
        p for p in audit_dir.rglob("*") if p.is_file() and f"dirs/audit/{p.relative_to(audit_dir)}" not in m["files"]
    ]
    assert written, "the restore wrote no audit file of its own: the end pass is not tested"


def test_not_as_root_the_owner_is_left_as_it_is(
    box: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = _backup(box, tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(bk, "_chown", lambda p, uid, gid: calls.append(str(p)))
    monkeypatch.setattr(bk, "_is_root", lambda: False)
    out = bk.restore(files[0], box["priv"], env=_env(box), dirs=box["dirs"], public_key=box["pub"],
                     keep_to=tmp_path / "kept", running=lambda: ["db"])  # fmt: skip
    assert out["ok"] and calls == []  # a user who is not root cannot give a file away; the files are its own


# ---------------------------------------------------------------- DATA-011: a restore on a box that runs services
def test_a_restore_is_refused_while_other_services_run_and_nothing_changes(box: dict[str, Any], tmp_path: Path) -> None:
    """Lane G (DATA-011): the restore renamed each volume's data aside while the services ran; a running service
    went on writing the renamed copy, and those writes were lost. Only the database may run (the restore needs it)."""
    files = _backup(box, tmp_path)
    box["db"].execute("UPDATE marks SET mark = ? WHERE pid = ?", ("withdrawn", "P1"))
    with pytest.raises(bk.BackupError) as stop:
        bk.restore(files[0], box["priv"], env=_env(box), dirs=box["dirs"], public_key=box["pub"],
                   keep_to=tmp_path / "kept", running=lambda: ["db", "orchestrator", "console"])  # fmt: skip
    said = str(stop.value)
    assert "orchestrator" in said and "console" in said and "docker compose stop" in said and "db" in said
    assert box["db"].fetchval("SELECT mark FROM marks WHERE pid = 'P1'") == "withdrawn"  # nothing was restored
    assert not list(tmp_path.glob("*.pre-restore-*")) and not (tmp_path / "kept").exists()


def test_a_restore_is_refused_when_docker_cannot_say_what_runs(box: dict[str, Any], tmp_path: Path) -> None:
    files = _backup(box, tmp_path)
    with pytest.raises(bk.BackupError, match="cannot tell which services run"):
        bk.restore(files[0], box["priv"], env=_env(box), dirs=box["dirs"], public_key=box["pub"],
                   keep_to=tmp_path / "kept", running=lambda: None)  # fmt: skip


def test_the_command_asks_the_box_which_services_run(
    box: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``trialbox restore`` on a box asks compose; ``--services-stopped`` is the operator's word when compose cannot
    answer (a box whose compose is broken), and is then the only way through."""
    from tools.trialbox import update
    from tools.trialbox.__main__ import main as cli

    files = _backup(box, tmp_path)
    seen: dict[str, Any] = {}

    def fake_restore(*a: Any, **kw: Any) -> dict[str, Any]:
        seen.update(kw)
        raise bk.BackupError("stopped here")

    monkeypatch.setattr(bk, "restore", fake_restore)
    monkeypatch.setattr(update.ComposeBox, "running_services", lambda self: ["db", "gateway"])
    args = ["restore", str(files[0]), "--key", str(box["priv"]), "--yes", "--deploy", str(tmp_path / "deploy")]
    assert cli(args) == 1
    assert seen["running"]() == ["db", "gateway"]
    seen.clear()
    assert cli([*args, "--services-stopped"]) == 1
    assert seen["running"]() == ["db"]


# --------------------------------------------------------------------------------- found by the review of D-724
def test_a_restore_keeps_the_modes_of_folders_and_files(box: dict[str, Any], tmp_path: Path) -> None:
    """Found by the review, by running: every folder came back 0755 (an audit folder of 0700 readable by all), a
    0660 file came back 0640. A folder gets the mode (and owner) of the same folder it replaced, else of the
    volume's top folder; a file the mode of its backup member (no set-id bits)."""
    lake = box["dirs"]["lake"]
    (lake / "db" / "gen").mkdir(parents=True)
    (lake / "db" / "gen" / "x.json").write_text("{}", encoding="utf-8")
    (lake / "shared.txt").write_text("s", encoding="utf-8")
    (lake / "shared.txt").chmod(0o660)
    for d in (lake, lake / "db", lake / "db" / "gen"):
        d.chmod(0o700)
    files = _backup(box, tmp_path)
    out = bk.restore(files[0], box["priv"], env=_env(box), dirs=box["dirs"], public_key=box["pub"],
                     keep_to=tmp_path / "kept", running=lambda: ["db"])  # fmt: skip
    assert out["ok"]
    for d in (lake, lake / "db", lake / "db" / "gen"):
        assert d.stat().st_mode & 0o7777 == 0o700, d
    assert (lake / "shared.txt").stat().st_mode & 0o7777 == 0o660


def test_a_failed_restore_leaves_no_audit_file_that_only_root_can_write(
    box: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Found by the review, by running: `backup.restore_failed` was written as root into the live audit folder, and
    the audit writer (another user) could not write the day's chain after it. Every audit write of the restore
    gives the files it made to the folder's owner."""
    files = _backup(box, tmp_path)
    audit_dir = box["dirs"]["audit"]
    given: dict[str, tuple[int, int]] = {}
    monkeypatch.setattr(bk, "_is_root", lambda: True)
    monkeypatch.setattr(bk, "_chown", lambda p, uid, gid: given.__setitem__(str(p), (uid, gid)))
    real = bk._uid_gid
    monkeypatch.setattr(bk, "_uid_gid", lambda p: (10001, 10002) if Path(p) == audit_dir else real(p))

    def broken(*_a: Any, **_kw: Any) -> dict[str, Any]:
        return {"snapshots": 0, "problems": ["a synthetic problem"], "unsigned": 0}  # the restore then stops

    monkeypatch.setattr(bk, "lake_check", broken)
    with pytest.raises(bk.BackupError):
        bk.restore(files[0], box["priv"], env=_env(box), dirs=box["dirs"], public_key=box["pub"],
                   keep_to=tmp_path / "kept", running=lambda: ["db"])  # fmt: skip
    made = [p for p in audit_dir.rglob("*") if p.is_file() and real(p) == (os.geteuid(), os.getegid())]
    assert made, "the failed restore wrote no audit file: the test does not reach the failure path"
    for p in made:
        assert given.get(str(p)) == (10001, 10002), p


def test_a_service_that_is_restarting_or_paused_counts_as_running() -> None:
    """Found by the review, by reading: a crash-looping service (restart: unless-stopped) is `restarting`, not
    `running`, and would come back during the restore."""
    from tools.trialbox.update import ComposeBox

    asked: list[list[str]] = []

    def run(argv: list[str], *a: Any, **kw: Any) -> str:
        asked.append(list(argv))
        return "db\norchestrator\n"

    box = ComposeBox.__new__(ComposeBox)
    box.compose, box.run = ["docker", "compose"], run
    assert box.running_services() == ["db", "orchestrator"]
    (argv,) = asked
    for status in ("running", "restarting", "paused"):
        assert ["--status", status] == argv[argv.index(status) - 1 : argv.index(status) + 1], status
