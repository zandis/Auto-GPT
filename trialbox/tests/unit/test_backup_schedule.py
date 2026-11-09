"""The nightly backup, the off-box rule, the age alert and the Postgres settings (WS-08.6, D-187)."""

from __future__ import annotations

import json
import shlex
import stat
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

T0 = datetime(2026, 11, 9, 19, 45, tzinfo=UTC)  # a Monday (04:45 the next day in Japan)

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
    def kind(p: str, declared: tuple[str, ...] = ()) -> tuple[str, bool]:
        t = bs.target_kind(Path(p), MOUNTS, declared, sysblock)
        return t.kind, t.offbox

    assert kind("/mnt/nas/trialbox") == ("network share", True)
    assert kind("/mnt/smb/x") == ("network share", True)
    assert kind("/mnt/wsl-share/tb") == ("network share", True)  # a Windows share in WSL2 (UNC source)
    assert kind("/mnt/c/backups") == ("this box", False)  # the Windows system disk in WSL2
    assert kind("/media/usb/trialbox") == ("usb disk", True)
    assert kind("/mnt/second disk/tb") == ("this box", False)  # a second internal disk is not off-box
    assert kind("/opt/trialbox/deploy/backups") == ("this box", False)  # install.sh's default target
    assert kind("/mnt/second disk/tb", ("/mnt/second disk",)) == ("declared off-box", True)  # hospital IT says so


def _cfg(tmp_path: Path, **kw: Any) -> bs.Config:
    pub = tmp_path / "keys" / "box.pub"
    if not pub.exists():
        bk.keygen(tmp_path / "keys" / "it.key", pub)
    base: dict[str, Any] = {"deploy": tmp_path / "deploy", "targets": [tmp_path / "nas", tmp_path / "local"],
                            "public_key": pub, "production": True, "keep": 3, "site": "CGMH"}  # fmt: skip
    base.update(kw)
    return bs.Config(**base)


def _offbox(names: set[str]) -> Any:
    return lambda p: bs.Target(str(p), "network share" if p.name in names else "this box", p.name in names)


def _maker(tmp_path: Path, url: str, fail: bool = False, when: datetime = T0) -> Any:
    db = Database.connect(url, "site")
    db.migrate(["CREATE TABLE marks (pid TEXT PRIMARY KEY, mark TEXT)"])
    db.execute("INSERT INTO marks VALUES (?, ?) ON CONFLICT DO NOTHING", ("P1", "approach"))
    (tmp_path / "audit").mkdir(parents=True, exist_ok=True)
    (tmp_path / "audit" / "a.jsonl").write_text('{"e":1}\n')

    def make(targets: list[Path]) -> list[Path]:
        if fail:
            raise RuntimeError("pg_dump of trialbox_wf failed: connection refused")
        return bk.backup(targets, tmp_path / "keys" / "box.pub", env={"TB_DB_URL": url, "TB_SITE_ID": "CGMH"},
                         dirs={"audit": tmp_path / "audit"}, now=when)  # fmt: skip

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
    assert last["file"]["name"] == f["name"] and stat.S_IMODE(cfg.last_file.stat().st_mode) == 0o600
    assert [e for e, _ in events] == ["backup.done"]
    detail = events[0][1]
    assert detail["sha256"] == f["sha256"] and detail["offbox_targets"] == 1 and detail["errors"] == []
    text = cfg.last_file.read_text() + json.dumps(events)
    assert "approach" not in text and "P1" not in text  # names, sizes and hashes only


def test_in_production_a_box_with_only_local_targets_fails_and_stays_red(tmp_path: Path, db_url: str) -> None:
    cfg = _cfg(tmp_path)
    events: list[str] = []
    res = bs.nightly(cfg, _maker(tmp_path, db_url), lambda e, d: events.append(e), now=T0, classify=_offbox(set()))
    assert not res["ok"] and "no off-box target" in res["errors"][0] and events == ["backup.failed"]
    assert res["file"] is not None  # the backup is still written: better a local copy than none
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
    st = bs.status(cfg, now=later + timedelta(hours=1), classify=_offbox({"nas"}))
    assert st["level"] == "alert" and st["age_hours"] == 25.0
    assert st["problems"] == [f"the last nightly backup at {later.isoformat(timespec='seconds')} failed "
                              "(deploy/site/backup-last.json)"]  # fmt: skip


def test_no_key_or_no_target_fails_before_anything_is_written(tmp_path: Path) -> None:
    calls: list[Any] = []

    def make(ts: list[Path]) -> list[Path]:
        calls.append(ts)
        return []

    cfg = _cfg(tmp_path, targets=[])
    assert "no backup target" in bs.nightly(cfg, make, lambda e, d: None, now=T0)["errors"][0]
    cfg = _cfg(tmp_path, public_key=tmp_path / "none.pub")
    assert "no backup key" in bs.nightly(cfg, make, lambda e, d: None, now=T0)["errors"][0]
    assert calls == []


@pytest.mark.parametrize(("day", "kind"), [(0, "diff"), (6, "full")])
def test_pgbackrest_runs_after_the_backup_full_on_the_full_day(tmp_path: Path, db_url: str, day: int,
                                                               kind: str) -> None:  # fmt: skip
    cfg = _cfg(tmp_path, archive_on=True)
    kinds: list[str] = []
    now = T0 + timedelta(days=(day - T0.weekday()) % 7)
    res = bs.nightly(cfg, _maker(tmp_path, db_url), lambda e, d: None, kinds.append, now=now,
                     classify=_offbox({"nas"}))  # fmt: skip
    assert res["ok"] and kinds == [kind] and res["pgbackrest"] == {"type": kind, "ok": True}

    def broken(k: str) -> None:
        raise RuntimeError("archive-push failed")

    later = now + timedelta(hours=1)
    res = bs.nightly(cfg, _maker(tmp_path, db_url, when=later), lambda e, d: None, broken, now=later,
                     classify=_offbox({"nas"}))  # fmt: skip
    assert not res["ok"] and res["pgbackrest"]["ok"] is False and "pgBackRest" in res["errors"][0]


def _touch_backup(d: Path, at: datetime, complete: bool = True) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"trialbox-CGMH-{at.strftime('%Y%m%dT%H%M%SZ')}.tbbak"
    f.write_bytes(b"x" * 10)
    if complete:
        bs.sidecar(f).write_text(f"{'a' * 64}  {f.name}\n")
    return f


def test_status_turns_red_after_36_hours_and_counts_only_complete_off_box_backups(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    cls = _offbox({"nas"})
    st = bs.status(cfg, now=T0, classify=cls)
    assert st["level"] == "alert" and st["problems"] == ["no complete backup on an off-box target"]
    _touch_backup(tmp_path / "local", T0)  # on this box only: not counted in PRODUCTION
    _touch_backup(tmp_path / "nas", T0 + timedelta(hours=1), complete=False)  # no sidecar: not finished
    assert bs.status(cfg, now=T0 + timedelta(hours=2), classify=cls)["newest_good"] is None
    _touch_backup(tmp_path / "nas", T0 - timedelta(hours=1))
    st = bs.status(cfg, now=T0 + timedelta(hours=35), classify=cls)
    assert st["level"] == "ok" and st["age_hours"] == 36.0 and st["newest_good"]["path"].startswith(str(tmp_path))
    st = bs.status(cfg, now=T0 + timedelta(hours=36), classify=cls)
    assert st["level"] == "alert" and st["problems"] == ["the newest good backup is 37 h old (limit 36 h)"]
    assert bs.status(_cfg(tmp_path, max_age_hours=48), now=T0 + timedelta(hours=36), classify=cls)["level"] == "ok"
    st = bs.status(cfg, now=T0, classify=cls, archiver={"archive_mode": "on", "failing": True})
    assert st["level"] == "alert" and "WAL archiving" in st["problems"][0]


def test_the_alert_is_sent_once_repeated_daily_and_cleared(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    cls = _offbox({"nas"})
    _touch_backup(tmp_path / "nas", T0)
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
    _touch_backup(tmp_path / "nas", T0 + timedelta(hours=84))
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


def test_config_reads_deploy_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("TB_BACKUP_TARGETS", "TB_ENV", "TB_PG_ARCHIVE_MODE", "TB_BACKUP_MAX_AGE_HOURS", "TB_BACKUP_OFFBOX"):
        monkeypatch.delenv(k, raising=False)
    cfg = bs.config(tmp_path, {"TB_BACKUP_TARGETS": "/mnt/nas/tb, /media/usb/tb", "TB_PG_ARCHIVE_MODE": "on",
                               "TB_BACKUP_MAX_AGE_HOURS": "30", "TB_BACKUP_OFFBOX": "/mnt/iscsi"})  # fmt: skip
    assert cfg.targets == [Path("/mnt/nas/tb"), Path("/media/usb/tb")] and cfg.production and cfg.archive_on
    assert cfg.max_age_hours == 30 and cfg.declared_offbox == ["/mnt/iscsi"] and cfg.keep == 14
    assert cfg.public_key == tmp_path / "secrets" / "backup.pub"
    assert not bs.config(tmp_path, {"TB_ENV": "DEV"}).production


# ------------------------------------------------------------------------------------------------ the compose box
class FakeBox:
    """Records every command; plays the db container (pg_dump) and the backup container (a finished file)."""

    def __init__(self, fail_pgbackrest: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.dump_dirs: list[Path] = []
        self.fail_pgbackrest = fail_pgbackrest

    def __call__(self, argv: list[str], stdin_file: Path | None = None, stdout_file: Path | None = None,
                 env: dict[str, str] | None = None, timeout: float | None = None) -> str:  # fmt: skip
        self.calls.append(list(argv))
        if stdout_file is not None:
            stdout_file.write_bytes(b"PGDMP")
            self.dump_dirs.append(stdout_file.parent)
            assert stat.S_IMODE(stdout_file.parent.stat().st_mode) == 0o700
        if argv[:2] == ["docker", "run"]:
            for i, a in enumerate(argv):
                if a == "-v" and ":/backup/" in argv[i + 1]:
                    host = Path(argv[i + 1].split(":")[0])
                    f = host / "trialbox-CGMH-20261109T194500Z.tbbak"
                    f.write_bytes(b"encrypted")
                    bs.sidecar(f).write_text(f"{'b' * 64}  {f.name}\n")
        if "pgbackrest" in argv and self.fail_pgbackrest:
            raise RuntimeError("pgbackrest exit 82")
        if "psql" in argv:
            return "on|3|t\n"
        return ""


def test_compose_nightly_dumps_without_refdata_rows_and_removes_the_plaintext_dumps(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text("TB_DB_URL=postgresql://trialbox:pw@db:5432/trialbox_wf\nTB_SITE_ID=CGMH\n")
    fake = FakeBox()
    ops = bs.ComposeOps(deploy, fake)
    cfg = _cfg(tmp_path, deploy=deploy, archive_on=True)
    res = bs.nightly(cfg, ops.make_backup(cfg), lambda e, d: None, ops.pgbackrest, now=T0, classify=_offbox({"nas"}))
    assert res["ok"], res["errors"]
    dumps = [c for c in fake.calls if "pg_dump" in c]
    assert len(dumps) == 2 and all("-Z0" in c for c in dumps)
    assert "--exclude-table-data=refdata.*" in dumps[0] and not any("exclude" in a for a in dumps[1])
    run = next(c for c in fake.calls if c[:2] == ["docker", "run"])
    mounts = [run[i + 1] for i, a in enumerate(run) if a == "-v"]
    assert all(m.endswith(":ro") for m in mounts if "/v/" in m or "/dumps" in m)  # volumes and dumps read-only
    assert "TB_PG_DUMP_DIR=/dumps" in run and not any("pw" in a for a in run)  # passwords never on a command line
    assert all(not d.exists() for d in fake.dump_dirs)  # the plaintext dumps are gone after the run
    assert next(
        c[c.index("pgbackrest"):] for c in fake.calls if "pgbackrest" in c) == ["pgbackrest", "--stanza=trialbox", "--type=diff", "backup"]  # fmt: skip
    assert ops.archiver() == {"archive_mode": "on", "failed_count": 3, "failing": True}


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
    for k in ("TB_BACKUP_TARGETS", "TB_ENV", "TB_PG_ARCHIVE_MODE", "TB_BACKUP_OFFBOX", "TB_BACKUP_ALERT_CMD"):
        monkeypatch.delenv(k, raising=False)
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    nas = tmp_path / "nas"
    (deploy / ".env").write_text(f"TB_BACKUP_TARGETS={nas}\nTB_BACKUP_OFFBOX={nas}\nTB_ENV=PRODUCTION\n"
                                 "TB_COMPOSE=false\n")  # fmt: skip
    monkeypatch.setenv("TB_COMPOSE", "false")  # no docker here: the audit goes to the pending file
    assert cli(["backup-status", "--deploy", str(deploy)]) == 1
    assert "no complete backup" in capsys.readouterr().out
    _touch_backup(nas, datetime.now(UTC) - timedelta(hours=2))
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
    assert "db-pg:/var/lib/postgresql/data" in vols and int(conf["repo1-retention-full"]) >= 2
    assert "[trialbox]" in (DEPLOY / "pgbackrest" / "pgbackrest.conf").read_text() and bs.STANZA == "trialbox"


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
