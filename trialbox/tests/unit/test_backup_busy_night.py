"""BACKUP-RESTORE (D-724), finding DATA-009 of lane G's review of 2026-11-13: a backup taken while the box writes
its audit chain must hold a chain and a head anchor that agree.

The backup copied the day file (``audit/<day>.jsonl``) and then ``HEAD.json`` (the walk's order: digits before
``H``). One event written in between gave a copy whose head anchor says one event more than its chain: ``verify``
fails, and a restore of that backup raised ``AuditAnchorBroken`` after the databases and folders were already in
place. The drill could not see it: its box is idle while it backs up."""

from __future__ import annotations

from datetime import UTC, datetime
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


@pytest.mark.parametrize("between", ["day file then head", "head then day file"])
def test_an_event_written_during_the_copy_leaves_a_chain_and_head_that_agree(
    box: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, between: str
) -> None:
    """An event is written between the copies of the day file and of the head anchor, in either order."""
    audit_dir = box["dirs"]["audit"]
    (audit_dir / "2026" / "log.jsonl").unlink()  # the fixture's line is not a chain; this test writes a real one
    (audit_dir / "2026").rmdir()
    log = _chain(audit_dir, 3)
    real = bk._add
    wrote: list[str] = []

    def add_and_write(tar: Any, path: Path, arcname: str, *a: Any, **kw: Any) -> tuple[str, int]:
        day = arcname.startswith("dirs/audit/") and arcname.endswith(".jsonl") and not wrote
        if day and between == "head then day file":  # after the head anchor was read, before the day file is copied
            log.append("test.event", ts=AT, actor="test", detail={"i": "during"})
            wrote.append(arcname)
        out = real(tar, path, arcname, *a, **kw)
        if day and between == "day file then head":  # after the day file, before the head anchor
            log.append("test.event", ts=AT, actor="test", detail={"i": "during"})
            wrote.append(arcname)
        return out

    monkeypatch.setattr(bk, "_add", add_and_write)
    files = _backup(box, tmp_path)
    assert wrote, "the copy never reached the audit chain"
    copied = _copied_audit(box, tmp_path, files)
    res = audit.verify(copied)
    assert res.ok, res.errors
    assert res.lines in (3, 4)  # the chain as it stood at one moment: before the event, or with it
    assert audit.verify(audit_dir).ok  # and the box's own chain is whole


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
