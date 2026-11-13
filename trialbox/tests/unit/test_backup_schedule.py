"""The nightly backup, the off-box rule, the age alert and the Postgres settings (WS-08.6, D-187, D-188)."""

from __future__ import annotations

import json
import shlex
import stat
from collections import namedtuple
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from tb_common.db import Database

from tools.backup_drill import DEPLOY, compose_pg_settings
from tools.trialbox import backup as bk
from tools.trialbox import backup_schedule as bs
from tools.trialbox.__main__ import main as cli

T0 = datetime(2026, 11, 9, 19, 45, tzinfo=UTC)  # a Monday in UTC; Tuesday 04:45 in Japan

MOUNTS = """\
/dev/nvme0n1p2 / ext4 rw 0 0
nas.hospital.local:/trialbox /mnt/nas nfs4 rw 0 0
//fileserver/backup /mnt/smb cifs rw 0 0
\\134\\134nas\\134share /mnt/wsl-share 9p rw 0 0
C:\\134 /mnt/c 9p rw 0 0
/dev/sdb1 /media/usb ext4 rw 0 0
/dev/nvme1n1p1 /mnt/second\\040disk ext4 rw 0 0
"""


@pytest.fixture
def sysblock(tmp_path: Path) -> Path:
    dev = tmp_path / "sys" / "devices" / "pci0000:00" / "usb2" / "2-1" / "block" / "sdb" / "sdb1"
    dev.mkdir(parents=True)
    nv = tmp_path / "sys" / "devices" / "pci0000:00" / "nvme" / "block" / "nvme1n1" / "nvme1n1p1"
    nv.mkdir(parents=True)
    links = tmp_path / "class-block"
    links.mkdir()
    (links / "sdb1").symlink_to(dev)
    (links / "nvme1n1p1").symlink_to(nv)
    return links


def test_targets_are_classified_off_box_only_when_they_leave_the_box(sysblock: Path) -> None:
    def kind(p: str) -> tuple[str, bool]:
        t = bs.target_kind(Path(p), MOUNTS, (), sysblock)
        return t.kind, t.offbox

    assert kind("/mnt/nas/trialbox") == ("network share", True)
    assert kind("/mnt/smb/x") == ("network share", True)
    assert kind("/mnt/wsl-share/tb") == ("network share", True)  # a Windows share in WSL2 (UNC source)
    assert kind("/mnt/c/backups") == ("this box", False)  # the Windows system disk in WSL2
    assert kind("/media/usb/trialbox") == ("usb disk", True)
    assert kind("/mnt/second disk/tb") == ("this box", False)  # a second internal disk is not off-box
    assert kind("/opt/trialbox/deploy/backups") == ("this box", False)  # install.sh's default target


def test_a_declared_target_counts_only_off_the_boxs_disk_or_with_its_marker(tmp_path: Path) -> None:
    """M1: TB_BACKUP_OFFBOX on the same device as / and deploy/ is a typo or a wish, not an off-box copy."""
    share = tmp_path / "iscsi"
    share.mkdir()
    same = bs.target_kind(share / "tb", "", [str(share)], local=(Path("/"), tmp_path))
    assert not same.offbox and "no .trialbox-offbox file" in same.kind
    (share / bs.OFFBOX_MARKER).write_text("hospital IT, 2026-11-09\n")
    assert bs.target_kind(share / "tb", "", [str(share)], local=(Path("/"), tmp_path)).offbox
    (share / bs.OFFBOX_MARKER).unlink()
    real_stat = Path.stat
    Dev = namedtuple("Dev", "st_dev")

    def fake_stat(self: Path, **kw: Any) -> Any:
        return Dev(999) if self == share else real_stat(self, **kw)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Path, "stat", fake_stat)
        assert bs.target_kind(share / "tb", "", [str(share)], local=(tmp_path,)).kind == "declared off-box"


@pytest.fixture(autouse=True)
def _hermetic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No test here reads the runner's docker state, volumes or compose settings: every variable the compose steps
    read from the process is removed, and the docker volume root is an empty folder."""
    import os

    for k in list(os.environ):
        if k.startswith(("TB_COMPOSE", "TB_DOCKER", "TB_IMAGE", "TB_UPDATE_", "TB_BACKUP_", "TB_PG_", "TB_PGBACKREST",
                         "COMPOSE_", "DOCKER_")) or k in ("TB_MODELS_DIR", "TB_SITE_ID", "TB_SETTINGS_FILE"):  # fmt: skip
            monkeypatch.delenv(k, raising=False)
    (tmp_path / "no-docker-volumes").mkdir(exist_ok=True)
    monkeypatch.setenv("TB_DOCKER_VOLUMES", str(tmp_path / "no-docker-volumes"))


def _cfg(tmp_path: Path, **kw: Any) -> bs.Config:
    pub = tmp_path / "keys" / "box.pub"
    if not pub.exists():
        bk.keygen(tmp_path / "keys" / "it.key", pub)
    base: dict[str, Any] = {"deploy": tmp_path / "deploy", "targets": [tmp_path / "nas", tmp_path / "local"],
                            "public_key": pub, "production": True, "keep": 3, "site": "CGMH",
                            "mailto": "it@hospital.example"}  # fmt: skip
    base.update(kw)
    return bs.Config(**base)


def _offbox(names: set[str]) -> Any:
    return lambda p: bs.Target(str(p), "network share" if p.name in names else "this box", p.name in names)


def _maker(tmp_path: Path, url: str, fail: bool = False, when: datetime = T0, only_first: bool = False) -> Any:
    db = Database.connect(url, "site")
    db.migrate(["CREATE TABLE marks (pid TEXT PRIMARY KEY, mark TEXT)"])
    db.execute("INSERT INTO marks VALUES (?, ?) ON CONFLICT DO NOTHING", ("P1", "approach"))
    (tmp_path / "audit").mkdir(parents=True, exist_ok=True)
    (tmp_path / "audit" / "a.jsonl").write_text('{"e":1}\n')

    def make(targets: list[Path]) -> list[Path]:
        if fail:
            raise RuntimeError("pg_dump of trialbox_wf failed: connection refused")
        out = bk.backup(targets, tmp_path / "keys" / "box.pub", env={"TB_DB_URL": url, "TB_SITE_ID": "CGMH"},
                        dirs={"audit": tmp_path / "audit"}, now=when)  # fmt: skip
        return out[:1] if only_first else out

    return make


def test_nightly_writes_records_and_audits_a_good_backup(tmp_path: Path, db_url: str) -> None:
    cfg = _cfg(tmp_path)
    events: list[tuple[str, dict[str, Any]]] = []
    res = bs.nightly(cfg, _maker(tmp_path, db_url), lambda e, d: events.append((e, d)), now=T0,
                     classify=_offbox({"nas"}))  # fmt: skip
    assert res["ok"] and res["errors"] == [] and res["good_at"] == T0.isoformat(timespec="seconds")
    f = res["file"]
    assert len(f["copies"]) == 2 and f["sha256"] == bk.read_sidecar(Path(f["copies"][0]["path"]))
    last = json.loads(cfg.last_file.read_text())
    assert last["good_file"] == {k: f[k] for k in ("name", "bytes", "sha256")}
    assert stat.S_IMODE(cfg.last_file.stat().st_mode) == 0o600
    assert [e for e, _ in events] == ["backup.done"]
    detail = events[0][1]
    assert detail["sha256"] == f["sha256"] and detail["offbox_targets"] == 1 and detail["errors"] == []
    text = cfg.last_file.read_text() + json.dumps(events)
    assert "approach" not in text and "P1" not in text  # names, sizes and hashes only
    assert bs.status(cfg, now=T0 + timedelta(hours=1), classify=_offbox({"nas"}))["level"] == "ok"


def test_in_production_a_box_with_only_local_targets_fails_and_stays_red(tmp_path: Path, db_url: str) -> None:
    cfg = _cfg(tmp_path)
    events: list[str] = []
    res = bs.nightly(cfg, _maker(tmp_path, db_url), lambda e, d: events.append(e), now=T0, classify=_offbox(set()))
    assert not res["ok"] and "no off-box target" in res["errors"][0] and events == ["backup.failed"]
    assert res["file"] is not None and res["good_file"] is None  # written (better than none) but never good
    st = bs.status(cfg, now=T0 + timedelta(hours=1), classify=_offbox(set()))
    assert st["level"] == "alert" and any("no off-box" in p for p in st["problems"])
    dev = _cfg(tmp_path, production=False)  # DEV: a local target is enough
    res = bs.nightly(dev, _maker(tmp_path, db_url, when=T0 + timedelta(hours=2)), lambda e, d: None,
                     now=T0 + timedelta(hours=2), classify=_offbox(set()))  # fmt: skip
    assert res["ok"] and bs.status(dev, now=T0 + timedelta(hours=3), classify=_offbox(set()))["level"] == "ok"


def test_a_failed_nightly_run_is_recorded_audited_and_alerts(tmp_path: Path, db_url: str) -> None:
    cfg = _cfg(tmp_path)
    good = bs.nightly(cfg, _maker(tmp_path, db_url), lambda e, d: None, now=T0, classify=_offbox({"nas"}))
    assert good["ok"]
    events: list[tuple[str, dict[str, Any]]] = []
    later = T0 + timedelta(days=1)
    res = bs.nightly(cfg, _maker(tmp_path, db_url, fail=True), lambda e, d: events.append((e, d)), now=later,
                     classify=_offbox({"nas"}))  # fmt: skip
    assert not res["ok"] and events[0][0] == "backup.failed" and "connection refused" in events[0][1]["errors"][0]
    assert res["good_file"] == good["good_file"]  # the last good one is carried over
    st = bs.status(cfg, now=later + timedelta(hours=1), classify=_offbox({"nas"}))
    assert st["level"] == "alert" and st["age_hours"] == 25.0
    assert st["problems"] == [f"the last nightly backup at {later.isoformat(timespec='seconds')} failed "
                              "(deploy/site/backup-last.json)"]  # fmt: skip


def test_a_failed_copy_to_the_second_target_is_red_though_a_newer_file_is_there(tmp_path: Path, db_url: str) -> None:
    """H2: the run wrote the off-box copy but not the second one. The file stamp is later than nothing recorded; the
    run's failure decides, not the stamp."""
    cfg = _cfg(tmp_path)
    assert bs.nightly(cfg, _maker(tmp_path, db_url), lambda e, d: None, now=T0, classify=_offbox({"nas"}))["ok"]
    later = T0 + timedelta(hours=24)
    res = bs.nightly(cfg, _maker(tmp_path, db_url, when=later, only_first=True), lambda e, d: None, now=later,
                     classify=_offbox({"nas"}))  # fmt: skip
    assert not res["ok"] and "1 of 2 targets" in res["errors"][0]
    st = bs.status(cfg, now=later + timedelta(minutes=5), classify=_offbox({"nas"}))
    assert st["level"] == "alert" and any("failed" in p for p in st["problems"])
    assert st["newest_good"]["path"].endswith(T0.strftime("%Y%m%dT%H%M%SZ.tbbak"))  # the recorded good one


def test_a_failed_pgbackrest_run_is_red_even_when_the_tbbak_is_fine(tmp_path: Path, db_url: str) -> None:
    """H2: the pgBackRest check runs on its own, not only when the rest of the run was good."""
    cfg = _cfg(tmp_path, archive_on=True)

    def broken(kind: str) -> None:
        raise RuntimeError("archive-push failed")

    res = bs.nightly(cfg, _maker(tmp_path, db_url), lambda e, d: None, broken, now=T0, classify=_offbox({"nas"}))
    assert not res["ok"] and res["file"] is not None
    st = bs.status(cfg, now=T0 + timedelta(minutes=5), classify=_offbox({"nas"}))
    assert "the last pgBackRest backup failed (deploy/site/backup-last.json)" in st["problems"]


def test_no_key_no_target_or_no_space_fails_before_anything_is_written(tmp_path: Path,
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    calls: list[Any] = []

    def make(ts: list[Path]) -> list[Path]:
        calls.append(ts)
        return []

    cfg = _cfg(tmp_path, targets=[])
    assert "no backup target" in bs.nightly(cfg, make, lambda e, d: None, now=T0)["errors"][0]
    cfg = _cfg(tmp_path, public_key=tmp_path / "none.pub")
    assert "no backup key" in bs.nightly(cfg, make, lambda e, d: None, now=T0)["errors"][0]
    cfg = _cfg(tmp_path)
    bs._write_json(cfg.last_file, {"ok": True, "good_file": {"name": "x", "bytes": 10 * 2**30, "sha256": "a"}})
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr("shutil.disk_usage", lambda p: Usage(0, 0, 2**30))
    res = bs.nightly(cfg, make, lambda e, d: None, now=T0)
    assert "not enough free space" in res["errors"][0] and calls == []


@pytest.mark.parametrize(("day", "kind"), [(0, "diff"), (6, "full")])
def test_pgbackrest_runs_after_the_backup_full_on_the_full_day(tmp_path: Path, db_url: str, day: int,
                                                               kind: str) -> None:  # fmt: skip
    cfg = _cfg(tmp_path, archive_on=True)
    kinds: list[str] = []
    now = T0 + timedelta(days=(day - T0.weekday()) % 7)
    res = bs.nightly(cfg, _maker(tmp_path, db_url, when=now), lambda e, d: None, kinds.append, now=now,
                     classify=_offbox({"nas"}))  # fmt: skip
    assert res["ok"] and kinds == [kind] and res["pgbackrest"] == {"type": kind, "ok": True}


def test_the_full_day_is_the_boxs_local_day(tmp_path: Path, db_url: str) -> None:
    """T0 is Monday 19:45 UTC, Tuesday 04:45 in Tokyo: a Tuesday full backup runs then in Japan."""
    kinds: list[str] = []
    cfg = _cfg(tmp_path, archive_on=True, full_day=1, tz="Asia/Tokyo")
    assert bs.nightly(cfg, _maker(tmp_path, db_url), lambda e, d: None, kinds.append, now=T0,
                      classify=_offbox({"nas"}))["ok"]  # fmt: skip
    assert kinds == ["full"]


def _touch_backup(d: Path, at: datetime, complete: bool = True, site: str = "CGMH") -> Path:
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"trialbox-{site}-{at.strftime('%Y%m%dT%H%M%SZ')}.tbbak"
    f.write_bytes(b"x" * 10)
    if complete:
        bs.sidecar(f).write_text(f"{'a' * 64}  {f.name}\n")
    return f


def _record_good(cfg: bs.Config, f: Path, at: datetime) -> None:
    bs._write_json(cfg.last_file, {"at": at.isoformat(timespec="seconds"), "ok": True,
                                   "good_at": at.isoformat(timespec="seconds"),
                                   "good_file": {"name": f.name, "bytes": f.stat().st_size, "sha256": "a" * 64}})  # fmt: skip


def test_status_turns_red_after_36_hours_and_counts_only_the_recorded_off_box_backup(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    cls = _offbox({"nas"})
    st = bs.status(cfg, now=T0, classify=cls)
    assert st["level"] == "alert" and st["problems"][0].startswith("no good backup on an off-box target")
    local = _touch_backup(tmp_path / "local", T0)  # on this box only: not counted in PRODUCTION
    _record_good(cfg, local, T0)
    assert bs.status(cfg, now=T0 + timedelta(hours=2), classify=cls)["newest_good"] is None
    good = _touch_backup(tmp_path / "nas", T0 - timedelta(hours=1))
    _record_good(cfg, good, T0 - timedelta(hours=1))
    st = bs.status(cfg, now=T0 + timedelta(hours=35), classify=cls)
    assert st["level"] == "ok" and st["age_hours"] == 36.0 and st["newest_good"]["path"] == str(good)
    st = bs.status(cfg, now=T0 + timedelta(hours=36), classify=cls)
    assert st["level"] == "alert" and st["problems"] == ["the newest good backup is 37 h old (limit 36 h)"]
    assert bs.status(_cfg(tmp_path, max_age_hours=48), now=T0 + timedelta(hours=36), classify=cls)["level"] == "ok"


def test_garbage_other_sites_and_unrecorded_files_do_not_count(tmp_path: Path) -> None:
    """H4: a newer file with a bogus sidecar, another box's file on the same share, a file whose size or sha256
    differs from the record: none of them is the good backup."""
    cfg = _cfg(tmp_path)
    cls = _offbox({"nas"})
    good = _touch_backup(tmp_path / "nas", T0)
    _record_good(cfg, good, T0)
    _touch_backup(tmp_path / "nas", T0 + timedelta(hours=40))  # newer, sidecar present, never recorded
    _touch_backup(tmp_path / "nas", T0 + timedelta(hours=40), site="OTHER")
    st = bs.status(cfg, now=T0 + timedelta(hours=40), classify=cls)
    assert st["newest_good"]["path"] == str(good) and st["level"] == "alert" and "40 h old" in st["problems"][0]
    good.write_bytes(b"y" * 11)  # changed size on the share
    assert bs.status(cfg, now=T0 + timedelta(hours=1), classify=cls)["newest_good"] is None
    good.write_bytes(b"x" * 10)
    bs.sidecar(good).write_text(f"{'b' * 64}  {good.name}\n")  # another sha256
    assert bs.status(cfg, now=T0 + timedelta(hours=1), classify=cls)["newest_good"] is None


def test_a_future_dated_or_mismatched_good_backup_is_an_alert(tmp_path: Path) -> None:
    """H3: a file name dated after now (a wrong clock or a crafted name) never keeps the status green."""
    cfg = _cfg(tmp_path)
    cls = _offbox({"nas"})
    future = _touch_backup(tmp_path / "nas", T0 + timedelta(days=30))
    _record_good(cfg, future, T0 + timedelta(days=30))
    st = bs.status(cfg, now=T0, classify=cls)
    assert st["level"] == "alert" and "dated in the future" in st["problems"][0]
    assert bs.status(cfg, now=T0 + timedelta(days=30, minutes=30), classify=cls)["level"] == "ok"
    _record_good(cfg, future, T0)  # the record says T0, the name says 30 days later
    st = bs.status(cfg, now=T0 + timedelta(days=30, minutes=30), classify=cls)
    assert any("disagree" in p for p in st["problems"])


def test_archiving_that_is_off_failing_or_stale_is_an_alert(tmp_path: Path) -> None:
    """M6: archiving turned on in deploy/.env but off on the server, failing, or quiet for more than 26 h."""
    cfg = _cfg(tmp_path, archive_on=True)
    cls = _offbox({"nas"})
    good = _touch_backup(tmp_path / "nas", T0)
    _record_good(cfg, good, T0)

    def problems(arch: dict[str, Any]) -> list[str]:
        return list(bs.status(cfg, now=T0 + timedelta(hours=1), archiver=arch, classify=cls)["problems"])

    assert problems({"archive_mode": "on", "failing": False, "last_archived_age_s": 600}) == []
    assert "archive_mode=off" in problems({"archive_mode": "off", "failing": False, "last_archived_age_s": 600})[0]
    assert "up -d db" in problems({"archive_mode": "off", "last_archived_age_s": 600})[0]
    assert "failing" in problems({"archive_mode": "on", "failing": True, "last_archived_age_s": 600})[0]
    assert "26 h" in problems({"archive_mode": "on", "failing": False, "last_archived_age_s": 27 * 3600})[0]
    assert "26 h" in problems({"archive_mode": "on", "failing": False, "last_archived_age_s": -1})[0]
    assert "did not answer" in problems({"failing": True, "error": "RuntimeError: db down"})[0]


def test_the_alert_is_sent_once_repeated_daily_and_cleared(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    cls = _offbox({"nas"})
    _record_good(cfg, _touch_backup(tmp_path / "nas", T0), T0)
    events: list[str] = []
    sent: list[str] = []

    def audit(e: str, d: dict[str, Any]) -> None:
        events.append(e)

    def at(h: float) -> tuple[dict[str, Any], datetime]:
        return bs.status(cfg, now=T0 + timedelta(hours=h), classify=cls), T0 + timedelta(hours=h)

    st, now = at(1)
    assert bs.alert(cfg, st, audit, sent.append, now=now) == "quiet" and events == []
    st, now = at(40)
    assert bs.alert(cfg, st, audit, sent.append, now=now) == "sent"
    assert "backup alert" in sent[0] and "37 h old" not in sent[0] and "40 h old" in sent[0]
    assert "RUNBOOK" in sent[0] and "no patient data" in sent[0]
    st, now = at(41)  # the problem text changes with the age: still one alert a day, not one an hour
    assert st["problems"] != json.loads(cfg.alert_file.read_text())["problems"]
    assert bs.alert(cfg, st, audit, sent.append, now=now) == "quiet"
    st, now = at(42)
    st["problems"] = [*st["problems"], "WAL archiving to pgBackRest is failing"]  # a new kind of problem: at once
    assert bs.alert(cfg, st, audit, sent.append, now=now) == "sent" and len(sent) == 2
    st, now = at(60)
    assert bs.alert(cfg, st, audit, sent.append, now=now) == "sent" and len(sent) == 3  # back to one kind: a change
    st, now = at(70)
    assert bs.alert(cfg, st, audit, sent.append, now=now) == "quiet"
    st, now = at(84)
    assert bs.alert(cfg, st, audit, sent.append, now=now) == "sent" and len(sent) == 4  # 24 h on: again
    _record_good(cfg, _touch_backup(tmp_path / "nas", T0 + timedelta(hours=84)), T0 + timedelta(hours=84))
    st, now = at(85)
    assert bs.alert(cfg, st, audit, sent.append, now=now) == "cleared"
    assert events == ["backup.alert"] * 4 + ["backup.alert_cleared"]

    def broken(msg: str) -> None:
        raise OSError("relay down")

    st, now = at(200)
    assert bs.alert(cfg, st, audit, broken, now=now) == "sent" and events[-1] == "backup.alert_not_sent"


def test_alert_cmd_reads_the_message_on_stdin(tmp_path: Path) -> None:
    out = tmp_path / "mail.txt"
    send = bs.send_cmd(f"sh -c {shlex.quote(f'cat > {out}')}")
    assert send is not None and bs.send_cmd("") is None
    send("hello\n")
    assert out.read_text() == "hello\n"


def test_config_reads_deploy_env_with_quotes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("TB_BACKUP_TARGETS", "TB_ENV", "TB_PG_ARCHIVE_MODE", "TB_BACKUP_MAX_AGE_HOURS", "TB_BACKUP_OFFBOX",
              "TB_TZ", "TB_BACKUP_KEEP"):  # fmt: skip
        monkeypatch.delenv(k, raising=False)
    cfg = bs.config(tmp_path, {"TB_BACKUP_TARGETS": '"/mnt/nas/tb, /media/usb/tb"', "TB_PG_ARCHIVE_MODE": "'on'",
                               "TB_BACKUP_MAX_AGE_HOURS": "30", "TB_BACKUP_OFFBOX": "/mnt/iscsi",
                               "TB_TZ": '"Asia/Tokyo"'})  # fmt: skip
    assert cfg.targets == [Path("/mnt/nas/tb"), Path("/media/usb/tb")] and cfg.production and cfg.archive_on
    assert cfg.max_age_hours == 30 and cfg.declared_offbox == ["/mnt/iscsi"] and cfg.keep == 14
    assert cfg.public_key == tmp_path / "secrets" / "backup.pub" and cfg.tz == "Asia/Tokyo"
    assert not bs.config(tmp_path, {"TB_ENV": "DEV"}).production


def test_prune_touches_only_this_sites_files(tmp_path: Path) -> None:
    mine = [_touch_backup(tmp_path, T0 + timedelta(days=d)) for d in range(3)]
    other = _touch_backup(tmp_path, T0 - timedelta(days=9), site="OTHER")
    longer = _touch_backup(tmp_path, T0 - timedelta(days=9), site="CGMH-EAST")
    (tmp_path / f"{other.name}.part").write_bytes(b"half")
    gone = bs.prune(tmp_path, 1, "trialbox-CGMH-")
    assert not mine[0].exists() and not mine[1].exists() and mine[2].exists()
    assert other.exists() and longer.exists() and (tmp_path / f"{other.name}.part").exists()
    assert len(gone) == 4  # two files and their sidecars


def test_one_nightly_run_at_a_time(tmp_path: Path) -> None:
    with bs._lock(tmp_path) as first, bs._lock(tmp_path) as second:
        assert first and not second


# ------------------------------------------------------------------------------------------------ the compose box
class FakeBox:
    """Records every command; plays the db container (the snapshot script) and the backup container."""

    def __init__(self, fail_pgbackrest: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.scripts: dict[str, str] = {}
        self.copied: list[Path] = []
        self.fail_pgbackrest = fail_pgbackrest
        self.db = ""

    def __call__(self, argv: list[str], stdin_file: Path | None = None, stdout_file: Path | None = None,
                 env: dict[str, str] | None = None, timeout: float | None = None) -> str:  # fmt: skip
        self.calls.append(list(argv))
        if "psql" in " ".join(argv) and stdin_file is not None:
            self.db = argv[-1].split("/")[-1].removesuffix(".sql")
            self.scripts[self.db] = stdin_file.read_text()
        if argv[-3:-2] == ["cp"] or (len(argv) >= 2 and argv[-3] == "cp"):
            dest = Path(argv[-1])
            assert stat.S_IMODE(dest.stat().st_mode) == 0o700
            db = self.db
            (dest / f"{db}.dump").write_bytes(b"PGDMP")
            (dest / f"{db}.dump.rc").write_text("0\n")
            (dest / f"{db}.rows").write_text("public.t|1|abc\n")
            (dest / f"{db}.packs").write_text("")
            self.copied.append(dest)
        if argv[:2] == ["docker", "run"]:
            for i, a in enumerate(argv):
                if a == "-v" and ":/backup/" in argv[i + 1]:
                    host = Path(argv[i + 1].split(":")[0])
                    f = host / "trialbox-CGMH-20261109T194500Z.tbbak"
                    f.write_bytes(b"encrypted")
                    bs.sidecar(f).write_text(f"{'b' * 64}  {f.name}\n")
        if "pgbackrest" in argv and self.fail_pgbackrest:
            raise RuntimeError("pgbackrest exit 82")
        if "-tAc" in argv:
            return "on|3|t|120\n"
        return ""


def test_compose_nightly_takes_one_snapshot_per_database_and_removes_the_plaintext_dumps(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text("TB_DB_URL=postgresql://trialbox:pw@db:5432/trialbox_wf\nTB_SITE_ID=CGMH\n")
    (deploy / ".backup-stale").mkdir()  # left by a killed run
    fake = FakeBox()
    ops = bs.ComposeOps(deploy, fake)
    ops.sweep()
    assert not (deploy / ".backup-stale").exists()
    cfg = _cfg(tmp_path, deploy=deploy, archive_on=True, keep=9)
    res = bs.nightly(cfg, ops.make_backup(cfg), lambda e, d: None, ops.pgbackrest, now=T0, classify=_offbox({"nas"}))
    assert res["ok"], res["errors"]
    wf, hapi = fake.scripts["trialbox_wf"], fake.scripts["hapi"]
    for s in (wf, hapi):
        assert "REPEATABLE READ" in s and "pg_export_snapshot()" in s and "--snapshot=" in s and "-Z0" in s
        assert s.index("pg_export_snapshot") < s.index("pg_dump") < s.index(".rows") < s.index("COMMIT")
    assert '--exclude-table-data "refdata.ctgov_study"' in wf and "site-fetch" in wf
    assert "exclude-table-data" not in hapi and '--exclude-table-data "refdata.pack' not in wf
    run = next(c for c in fake.calls if c[:2] == ["docker", "run"])
    mounts = [run[i + 1] for i, a in enumerate(run) if a == "-v"]
    assert all(m.endswith(":ro") for m in mounts if "/v/" in m or "/dumps" in m)  # volumes and dumps read-only
    assert "TB_PG_DUMP_DIR=/dumps" in run and not any("pw" in a for a in run)  # passwords never on a command line
    assert run[run.index("--keep") + 1] == "9"  # M4: TB_BACKUP_KEEP reaches the container step
    assert fake.copied and all(not d.exists() for d in fake.copied)  # the plaintext dumps are gone after the run
    assert any(c[-3:] == ["rm", "-rf", bs.CONTAINER_SPOOL] for c in fake.calls)  # and from the db container
    assert next(c[c.index("pgbackrest"):] for c in fake.calls if "pgbackrest" in c) == [
        "pgbackrest", "--stanza=trialbox", "--type=diff", "backup"]  # fmt: skip
    assert ops.archiver() == {"archive_mode": "on", "failed_count": 3, "failing": True, "last_archived_age_s": 120}


def test_the_snapshot_script_runs_on_this_postgres(tmp_path: Path, db_url: str) -> None:
    """The very script the db container runs, here with the local psql: the files it writes parse."""
    import subprocess

    from tb_common.db import split_url

    db = Database.connect(db_url, "site")
    db.migrate(["CREATE TABLE marks (pid TEXT PRIMARY KEY, mark TEXT)"])
    db.execute("INSERT INTO marks VALUES (?, ?)", ("P1", "approach"))
    dsn, prefix = split_url(db_url)
    script = bs.snapshot_script(str(tmp_path), "trialbox_wf", "pg_dump", f'--dbname "{dsn}"', [f"{prefix}*"],
                                f"{prefix}refdata")  # fmt: skip
    (tmp_path / "s.sql").write_text(script)
    subprocess.run(["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "--dbname", dsn, "-f", str(tmp_path / "s.sql")],
                   check=True, capture_output=True)  # fmt: skip
    snap = bs.parse_snapshot(tmp_path, "trialbox_wf")
    assert snap["rows"][f"{db.schema}.marks"][0] == 1 and snap["packs"] == []
    src = bk.db_sources({"TB_DB_URL": db_url})[0]
    assert snap["rows"] == bk.row_counts(src)  # the same expression as the restore's check
    (tmp_path / "trialbox_wf.dump.rc").write_text("1\n")
    with pytest.raises(RuntimeError, match="exit 1"):
        bs.parse_snapshot(tmp_path, "trialbox_wf")


def test_compose_audit_falls_back_to_a_pending_file_when_the_orchestrator_is_down(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text("")

    def down(argv: list[str], **kw: Any) -> str:
        raise RuntimeError("orchestrator is not running")

    bs.ComposeOps(deploy, down).audit("backup.failed", {"errors": ["x"], "sha256": None})
    line = json.loads((deploy / "site" / "backup-audit-pending.jsonl").read_text().splitlines()[0])
    assert line["event"] == "backup.failed" and not list((deploy / "site").glob(".audit-*"))


def test_cli_status_exit_codes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    for k in (
        "TB_BACKUP_TARGETS",
        "TB_ENV",
        "TB_PG_ARCHIVE_MODE",
        "TB_BACKUP_OFFBOX",
        "TB_BACKUP_ALERT_CMD",
        "TB_BACKUP_MAILTO",
    ):
        monkeypatch.delenv(k, raising=False)
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    nas = tmp_path / "nas"
    nas.mkdir()
    (nas / bs.OFFBOX_MARKER).write_text("")
    (deploy / ".env").write_text(
        f"TB_BACKUP_TARGETS={nas}\nTB_BACKUP_OFFBOX={nas}\nTB_ENV=PRODUCTION\nTB_BACKUP_MAILTO=it@hospital.example\n"
    )
    monkeypatch.setenv("TB_COMPOSE", "false")  # no docker here: the audit goes to the pending file
    assert cli(["backup-status", "--deploy", str(deploy)]) == 1
    assert "no good backup" in capsys.readouterr().out
    at = datetime.now(UTC) - timedelta(hours=2)
    cfg = bs.config(deploy, {})
    _record_good(cfg, _touch_backup(nas, at), at)
    assert cli(["backup-status", "--deploy", str(deploy), "--quiet"]) == 0
    assert capsys.readouterr().out == ""
    assert cli(["backup-status", "--deploy", str(deploy), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["level"] == "ok"
    events = [json.loads(x)["event"] for x in (deploy / "site" / "backup-audit-pending.jsonl").read_text().split("\n")
              if x]  # fmt: skip
    assert events == ["backup.alert", "backup.alert_cleared"]


# ------------------------------------------------------------------------------------------------ Postgres settings
def test_compose_db_sets_the_compression_and_archiving_settings() -> None:
    pg = compose_pg_settings()
    assert pg["wal_compression"] == "zstd" and pg["default_toast_compression"] == "lz4"
    assert pg["archive_mode"] == "off"  # on only once the site has the image, the repository and the cipher file
    assert pg["archive_command"] == "pgbackrest --stanza=trialbox archive-push %p"
    db = yaml.safe_load((DEPLOY / "docker-compose.yml").read_text(encoding="utf-8"))["services"]["db"]
    vols = db["volumes"]
    assert "./pgbackrest/pgbackrest.conf:/etc/pgbackrest/pgbackrest.conf:ro" in vols
    assert "./secrets/pgbackrest:/etc/pgbackrest/conf.d:ro" in vols  # the cipher pass: db only, never in .env
    assert db["environment"]["POSTGRES_INITDB_ARGS"] == "${POSTGRES_INITDB_ARGS:---data-checksums}"
    assert "PGBACKREST" not in json.dumps(db["environment"])
    conf = pg["pgbackrest"]
    assert conf["compress-type"] == "zst" and conf["repo1-cipher-type"] == "aes-256-cbc"
    assert "repo1-cipher-pass" not in conf and conf["pg1-path"] == "/var/lib/postgresql/data"
    # M8: weekly fulls and three kept give at least two full weeks of point-in-time restore
    assert "db-pg:/var/lib/postgresql/data" in vols and int(conf["repo1-retention-full"]) >= 3
    assert "[trialbox]" in (DEPLOY / "pgbackrest" / "pgbackrest.conf").read_text() and bs.STANZA == "trialbox"


def test_install_and_update_keep_the_reference_pack_for_a_restore() -> None:
    sh = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    loop = sh[sh.index("deploy/refdata/pending/*.tar") :][:900]
    assert "deploy/refdata/loaded" in loop and 'rm -f "$f"' not in loop
    up = (DEPLOY.parent / "tools" / "trialbox" / "update.py").read_text(encoding="utf-8")
    assert '"refdata" / "loaded"' in up


def test_this_postgres_accepts_the_settings_and_toasts_with_lz4(db_url: str) -> None:
    """The settings are valid on a PostgreSQL built with lz4 and zstd (the official images are); a TOASTed column
    written under ``default_toast_compression = lz4`` is lz4."""
    import psycopg
    from tb_common.db import split_url

    with psycopg.connect(split_url(db_url)[0], autocommit=True) as con:
        enum = con.execute("SELECT enumvals FROM pg_settings WHERE name = 'wal_compression'").fetchone()
        assert enum is not None and "zstd" in enum[0]
        con.execute("SET default_toast_compression = lz4")
        con.execute("CREATE TEMP TABLE t (note text)")
        con.execute("INSERT INTO t VALUES (repeat('synthetic note ', 4000))")
        assert con.execute("SELECT pg_column_compression(note) FROM t").fetchall() == [("lz4",)]


def test_pitr_recovers_to_a_time_between_two_commits() -> None:
    """With the box's settings, WAL archived after a base backup brings back the commit before the target time and
    not the one after it (plain archiving stands in for pgBackRest, whose binary is not on this machine)."""
    import tempfile

    from tools.backup_drill import pitr_drill

    ok, detail = pitr_drill(Path(tempfile.mkdtemp(prefix="tb-pitr-")))
    assert ok, detail
    assert detail.startswith("rows 1,2 ")


def test_the_cron_schedule_runs_the_nightly_backup_and_the_hourly_status() -> None:
    cron = (DEPLOY / "backup" / "trialbox-backup.cron").read_text(encoding="utf-8")
    lines = [ln for ln in cron.splitlines() if ln and not ln.startswith("#") and "=" not in ln.split()[0]]
    assert any("backup-nightly" in ln and ln.split()[1] != "*" for ln in lines)
    assert any("backup-status --quiet" in ln and ln.split()[1] == "*" for ln in lines)


# ------------------------------------------------------------------------------------------------ D-274 (T-117b)
class RunningBox(FakeBox):
    """The FakeBox with running services, a db image with pgBackRest, and a docker volume folder."""

    def __init__(self, fail: str = "", pgbackrest: bool = True) -> None:
        super().__init__()
        self.fail, self.has_pgbackrest = fail, pgbackrest

    def __call__(self, argv: list[str], **kw: Any) -> str:  # type: ignore[override]
        # NEW-B-15: the words of the command, never its paths. The failure word used to be looked for in the whole
        # line, so a temp folder whose name holds it (a branch called "...-recheck" against ``fail="check"``) made
        # the very first command fail and the test take another branch of the product
        said = " ".join(a for a in argv if not a.startswith(("/", "./", "../")))
        if self.fail and self.fail in said:
            self.calls.append(list(argv))
            raise RuntimeError(f"{self.fail} failed")
        if "command -v pgbackrest" in said and not self.has_pgbackrest:
            self.calls.append(list(argv))
            raise RuntimeError("exit 1")
        if argv[-2:] == ["-u", "postgres"]:
            self.calls.append(list(argv))
            return "999\n"
        out = super().__call__(argv, **kw)
        if "ps" in argv and "--services" in argv:
            return "db\norchestrator\nconsole\nadapter\n"
        if argv[-1] == bs.RUNNING_JOBS_SQL:  # D-455: no job runs, so TB_BACKUP_QUIESCE=pause may pause
            return "0\n"
        if "pg_database_size" in " ".join(argv):  # D-455 (M4): every size is known, so a pause has its limits
            return "1000\n"
        return out


def test_compose_nightly_holds_the_writers_still_and_takes_the_host_files(tmp_path: Path) -> None:
    """DI-11: with TB_BACKUP_QUIESCE=pause (opt-in since D-455) every running service but db is paused from the first
    snapshot until the backup container is done, and unpaused even when the run fails. DI-12 / OPS-046: deploy/.env,
    settings, deploy/site and the identity and proxy volumes go in through the dump folder's host/ part."""
    deploy = tmp_path / "deploy"
    (deploy / "site").mkdir(parents=True)
    vols = tmp_path / "volumes"
    (vols / "trialbox_caddy-data" / "_data").mkdir(parents=True)
    (vols / "trialbox_caddy-data" / "_data" / "root.crt").write_text("synthetic CA")
    (deploy / ".env").write_text(f"TB_SITE_ID=CGMH\nTB_SETTINGS_FILE=./settings.yaml\nTB_DOCKER_VOLUMES={vols}\n")
    (deploy / "settings.yaml").write_text("site: {tz: Asia/Taipei}\n")
    (deploy / "site" / "registry.site.yaml").write_text("pins: {}\n")
    (deploy / "site" / "backup.lock").write_text("")
    seen: dict[str, list[str]] = {}
    fake = RunningBox()
    real_container = None

    def spy(work: Path, *a: Any, **kw: Any) -> None:
        seen["host"] = sorted(str(p.relative_to(work / "host")) for p in (work / "host").rglob("*") if p.is_file())
        assert real_container is not None
        real_container(work, *a, **kw)

    ops = bs.ComposeOps(deploy, fake)
    real_container = ops.box._backup_container
    ops.box._backup_container = spy  # type: ignore[method-assign,assignment]
    cfg = _cfg(tmp_path, deploy=deploy, quiesce="pause")
    make = ops.make_backup(cfg)
    res = bs.nightly(cfg, make, lambda e, d: None, now=T0, classify=_offbox({"nas"}))
    assert res["ok"], res["errors"]
    verbs = [c[c.index("pause") if "pause" in c else c.index("unpause")] for c in fake.calls
             if "pause" in c or "unpause" in c]  # fmt: skip
    assert verbs == ["pause", "unpause"]
    pause = next(c for c in fake.calls if "pause" in c)
    assert pause[-3:] == ["adapter", "console", "orchestrator"] and "db" not in pause[pause.index("pause") :]
    i_pause, i_unpause = fake.calls.index(pause), next(i for i, c in enumerate(fake.calls) if "unpause" in c)
    i_snap = next(i for i, c in enumerate(fake.calls) if "psql -X -q" in " ".join(c))  # the snapshot script
    i_run = next(i for i, c in enumerate(fake.calls) if c[:2] == ["docker", "run"])
    assert i_pause < i_snap < i_run < i_unpause
    assert res["point_in_time"]["held"] and res["point_in_time"]["paused"] == ["adapter", "console", "orchestrator"]
    assert json.loads(cfg.last_file.read_text())["point_in_time"]["held"]
    assert seen["host"] == ["deploy.env", "settings.yaml", "site/registry.site.yaml", "volumes/caddy-data/root.crt"]
    # a failing snapshot still unpauses
    bad = RunningBox(fail="psql -X -q")  # the snapshot script (not the job count before the pause)
    ops2 = bs.ComposeOps(deploy, bad)
    res2 = bs.nightly(cfg, ops2.make_backup(cfg), lambda e, d: None, now=T0, classify=_offbox({"nas"}))
    assert not res2["ok"] and any("unpause" in c for c in bad.calls)
    # TB_BACKUP_QUIESCE=off: nothing paused, and the record says so
    (deploy / ".env").write_text("TB_SITE_ID=CGMH\nTB_BACKUP_QUIESCE=off\n")
    off = RunningBox()
    cfg_off = bs.config(deploy, {"TB_SITE_ID": "CGMH", "TB_BACKUP_QUIESCE": "off"})
    assert cfg_off.quiesce == "off"
    res3 = bs.nightly(cfg, bs.ComposeOps(deploy, off).make_backup(cfg, cfg_off.quiesce), lambda e, d: None, now=T0,
                      classify=_offbox({"nas"}))  # fmt: skip
    assert not any("pause" in c for c in off.calls) and res3["point_in_time"]["held"] is False


def test_audit_events_kept_while_the_orchestrator_was_down_are_sent_first_in_order(tmp_path: Path) -> None:
    """DI-10: a parked backup event reaches the audit log with the next one that can be sent."""
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text("")
    up = {"ok": False}
    sent: list[str] = []

    def box(argv: list[str], stdin_file: Path | None = None, **kw: Any) -> str:
        if not up["ok"]:
            raise RuntimeError("orchestrator is not running")
        assert stdin_file is not None
        sent.append(json.loads(stdin_file.read_text())["event"])
        return ""

    ops = bs.ComposeOps(deploy, box)
    ops.audit("backup.failed", {"errors": ["x"]})
    ops.audit("backup.alert", {"problems": ["y"]})
    pending = deploy / "site" / "backup-audit-pending.jsonl"
    assert [json.loads(x)["event"] for x in pending.read_text().splitlines()] == ["backup.failed", "backup.alert"]
    up["ok"] = True
    ops.audit("backup.done", {"sha256": "a" * 64})
    assert sent == ["backup.failed", "backup.alert", "backup.done"] and not pending.exists()
    assert not list((deploy / "site").glob(".audit-*"))


def _deploy_with_template(tmp_path: Path, env: str) -> Path:
    deploy = tmp_path / "opt" / "tb" / "deploy"
    (deploy / "backup").mkdir(parents=True)
    (deploy / "backup" / "trialbox-backup.cron").write_text(
        (DEPLOY / "backup" / "trialbox-backup.cron").read_text(encoding="utf-8")
    )
    (deploy / ".env").write_text(env)
    return deploy


def test_install_writes_the_cron_file_and_production_needs_an_alert_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CR-058, OPS-028: install installs the cron; in PRODUCTION without an alert route it refuses."""
    for k in ("TB_ENV", "TB_BACKUP_ALERT_CMD", "TB_BACKUP_MAILTO", "TB_BACKUP_TARGETS"):
        monkeypatch.delenv(k, raising=False)
    cron = tmp_path / "cron.d"
    deploy = _deploy_with_template(tmp_path, "TB_ENV=PRODUCTION\n")
    cfg = bs.config(deploy, {"TB_ENV": "PRODUCTION"})
    with pytest.raises(ValueError, match="PRODUCTION needs a backup alert route"):
        bs.install_cron(cfg, cron, deploy.parent, has_mta=True)
    assert not (cron / bs.CRON_NAME).exists()
    cfg = bs.config(deploy, {"TB_ENV": "PRODUCTION", "TB_BACKUP_MAILTO": "it@hospital.example"})
    with pytest.raises(ValueError, match="no mail transfer agent"):
        bs.install_cron(cfg, cron, deploy.parent, has_mta=False)
    notes = bs.install_cron(cfg, cron, deploy.parent, has_mta=True)
    text = (cron / bs.CRON_NAME).read_text()
    assert notes[0].startswith("cron: ") and stat.S_IMODE((cron / bs.CRON_NAME).stat().st_mode) == 0o644
    assert 'MAILTO="it@hospital.example"' in text and "/opt/trialbox" not in text
    assert f"cd {deploy.parent} && {{ python3 -m tools.trialbox backup-nightly" in text
    assert not list(cron.glob(".*"))  # no temporary file left where cron reads
    cfg = bs.config(deploy, {"TB_ENV": "PRODUCTION", "TB_BACKUP_ALERT_CMD": "/usr/local/bin/tb-mail"})
    bs.install_cron(cfg, cron, deploy.parent, has_mta=False)
    assert 'MAILTO=""' in (cron / bs.CRON_NAME).read_text()
    dev = bs.config(deploy, {"TB_ENV": "DEV"})
    assert any("no backup alert route" in n for n in bs.install_cron(dev, cron, deploy.parent, has_mta=False))


def test_status_in_production_is_red_without_an_alert_route(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, mailto="")
    assert any("no alert route" in p for p in bs.status(cfg, now=T0, classify=_offbox({"nas"}))["problems"])
    assert not any("alert route" in p for p in bs.status(_cfg(tmp_path, mailto="", production=False), now=T0,
                                                         classify=_offbox({"nas"}))["problems"])  # fmt: skip


def test_wal_archiving_is_on_by_default_when_the_image_and_an_off_box_share_allow_it(tmp_path: Path) -> None:
    """DATA-024, OPS-048: stanza, then archive_mode=on, then pgbackrest check; off again when the check fails; left
    off when the site chose off, the image has no pgBackRest or nothing is off the box."""
    deploy = _deploy_with_template(tmp_path, "TB_SITE_ID=CGMH\n")
    nas = tmp_path / "nas"
    cfg = bs.config(deploy, {"TB_SITE_ID": "CGMH", "TB_BACKUP_TARGETS": str(nas)})
    fake = RunningBox()
    notes = bs.setup_archiving(cfg, bs.ComposeOps(deploy, fake), classify=_offbox({"nas"}))
    assert notes[0].startswith("WAL archiving: on") and "pgbackrest-CGMH" in notes[0]
    env = (deploy / ".env").read_text()
    assert "TB_PG_ARCHIVE_MODE=on" in env and f"TB_PGBACKREST_REPO={nas / 'pgbackrest-CGMH'}" in env
    cipher = deploy / "secrets" / "pgbackrest" / "cipher.conf"
    assert stat.S_IMODE(cipher.stat().st_mode) == 0o600 and "repo1-cipher-pass=" in cipher.read_text()
    steps = [c[c.index("pgbackrest") + 2] if "pgbackrest" in c and "--stanza=trialbox" in c else
             ("up" if "up" in c else None) for c in fake.calls]  # fmt: skip
    steps = [x for x in steps if x]
    assert steps == ["up", "stanza-create", "up", "check"]
    # the check fails: archiving goes off again, the db is recreated without it
    deploy2 = _deploy_with_template(tmp_path / "b", "")
    bad = RunningBox(fail="check")
    notes = bs.setup_archiving(bs.config(deploy2, {"TB_BACKUP_TARGETS": str(nas)}), bs.ComposeOps(deploy2, bad),
                               classify=_offbox({"nas"}))  # fmt: skip
    assert "set-up failed" in notes[0] and "TB_PG_ARCHIVE_MODE=off" in (deploy2 / ".env").read_text()
    assert bad.calls[-1][-3:] == ["up", "-d", "db"]
    for env_, box, want in (({"TB_PG_ARCHIVE_MODE": "off"}, RunningBox(), "the site's choice"),
                            ({}, RunningBox(pgbackrest=False), "no pgBackRest"),
                            ({"TB_BACKUP_TARGETS": str(tmp_path / "local")}, RunningBox(), "no off-box target")):  # fmt: skip
        d = _deploy_with_template(tmp_path / want.replace(" ", "-"), "")
        assert want in bs.setup_archiving(bs.config(d, env_), bs.ComposeOps(d, box), classify=_offbox({"nas"}))[0]


def test_backup_install_installs_the_cron_and_runs_the_first_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """The card's rehearsal in small: after install the cron exists and the first backup has run."""
    for k in ("TB_ENV", "TB_BACKUP_ALERT_CMD", "TB_BACKUP_MAILTO", "TB_BACKUP_TARGETS", "TB_PG_ARCHIVE_MODE"):
        monkeypatch.delenv(k, raising=False)
    deploy = _deploy_with_template(tmp_path, "TB_ENV=PRODUCTION\nTB_PG_ARCHIVE_MODE=off\n")
    cron = tmp_path / "cron.d"
    monkeypatch.setenv("TB_COMPOSE", "false")
    assert cli(["backup-install", "--deploy", str(deploy), "--cron-dir", str(cron)]) == 1
    assert "alert route" in capsys.readouterr().out and not (cron / bs.CRON_NAME).exists()
    with (deploy / ".env").open("a") as fh:
        fh.write("TB_BACKUP_ALERT_CMD=/usr/local/bin/tb-mail\n")
    assert cli(["backup-install", "--deploy", str(deploy), "--cron-dir", str(cron)]) == 0
    assert "no backup key" in capsys.readouterr().out and (cron / bs.CRON_NAME).is_file()
    (deploy / "secrets").mkdir()
    bk.keygen(tmp_path / "it.key", deploy / "secrets" / "backup.pub")
    ran: list[Path] = []

    def nightly(d: Path) -> int:
        ran.append(d)
        return 0

    monkeypatch.setattr(bs, "main_nightly", nightly)
    assert cli(["backup-install", "--deploy", str(deploy), "--cron-dir", str(cron)]) == 0
    assert ran == [deploy] and "first backup: done" in capsys.readouterr().out


def test_install_sh_runs_the_backup_step_after_the_stack_is_up() -> None:
    sh = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    step = sh.index("python3 -m tools.trialbox backup-install --deploy deploy")
    assert (
        sh.index("--wait --wait-timeout")
        < step
        < sh.index(
            "# ------------------------------------------------------------------------------------------------ 5. accounts"
        )
    )
    assert 'die "the backup schedule is not installed' in sh[step : step + 600]
