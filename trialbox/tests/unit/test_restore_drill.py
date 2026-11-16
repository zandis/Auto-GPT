"""T-730d (D-892): ``trialbox restore-drill`` proves a backup restores, typed by hospital IT with the key in hand. It
restores into scratch databases, never the live one; cleans up after a failure too; refuses up front when space is
short; and its result is the key-check record the health check reads (red after the interval, or on a failed drill)
and a backup problem that goes through the alert route (D-735)."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from tb_common import metrics
from tb_common.db import Database, split_url

from tools.trialbox import backup as bk
from tools.trialbox import backup_schedule as bsch
from tools.trialbox import restore_drill as rd
from tools.trialbox.__main__ import main as cli


@pytest.fixture
def box(tmp_path: Path, db_url: str) -> dict[str, Any]:
    db = Database.connect(db_url, "site")
    db.migrate(["CREATE TABLE marks (pid TEXT PRIMARY KEY, mark TEXT NOT NULL)"])
    db.execute("INSERT INTO marks VALUES (?, ?)", ("P1", "approach"))
    db.execute("INSERT INTO marks VALUES (?, ?)", ("P2", "not_now"))
    dirs = {"audit": tmp_path / "audit", "lake": tmp_path / "lake"}
    dirs["audit"].mkdir()
    dirs["lake"].mkdir()
    (dirs["lake"] / "patient.parquet").write_bytes(b"PAR1" + bytes(range(256)) * 50)
    priv, pub = tmp_path / "usb" / "backup.key", tmp_path / "box" / "backup.pub"
    bk.keygen(priv, pub)
    env = {"TB_DB_URL": db_url, "TB_SITE_ID": "CGMH"}
    (f, *_) = bk.backup([tmp_path / "nas"], pub, env=env, dirs=dirs)
    return {"db": db, "dirs": dirs, "priv": priv, "file": f, "env": env, "url": db_url}


def _scratch_dbs(url: str) -> list[str]:
    dsn, _ = split_url(url)
    with psycopg.connect(dsn, autocommit=True) as con:
        return [n for (n,) in con.execute("SELECT datname FROM pg_database WHERE datname LIKE 'tb\\_drill\\_%'")]


def _plenty(_p: Path) -> int:
    return 10**12


def test_a_drill_restores_into_scratch_compares_and_leaves_the_live_database_alone(
    box: dict[str, Any], tmp_path: Path
) -> None:
    box["db"].execute("UPDATE marks SET mark = ? WHERE pid = ?", ("withdrawn", "P1"))  # the box moved on
    res = rd.drill(box["file"], box["priv"], box["env"], work=tmp_path, free=_plenty)
    assert res["ok"], res
    assert res["databases"]["trialbox_wf"]["differ_count"] == 0 and res["databases"]["trialbox_wf"]["rows"] > 0
    assert res["scratch_dropped"] and all(n.startswith("tb_drill_") for n in res["scratch_dropped"])
    assert res["unpacked_removed"] and not list(tmp_path.glob("tb-drill-*")) and _scratch_dbs(box["url"]) == []
    # the live database is as the box left it, not as the backup had it
    assert box["db"].fetchall("SELECT mark FROM marks WHERE pid = ?", ("P1",)) == [("withdrawn",)]


def test_the_scratch_database_is_never_the_live_one(box: dict[str, Any], tmp_path: Path) -> None:
    live = rd._dbname(split_url(box["url"])[0])
    src = bk.db_sources(box["env"])[0]
    for bad in (live, "postgres_backup", f"x{rd.SCRATCH_PREFIX}1"):
        with pytest.raises(rd.DrillError, match="scratch"):
            rd.scratch_source(src, src.dsn, bad)
    with pytest.raises(rd.DrillError):
        rd._drop(src.dsn, live)  # the last guard before DROP DATABASE
    # a drill whose scratch name would be the live database fails, and changes nothing
    res = rd.drill(box["file"], box["priv"], box["env"], work=tmp_path, free=_plenty, name=lambda _db: live)
    assert not res["ok"] and "scratch" in res["error"]
    assert box["db"].fetchall("SELECT count(*) FROM marks") == [(2,)]


def test_a_failure_part_way_still_drops_the_scratch_database_and_the_unpacked_files(
    box: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_a: Any, **_k: Any) -> None:
        raise bk.BackupError("pg_restore of trialbox_wf failed: synthetic")

    monkeypatch.setattr(bk, "restore_db", broken)
    res = rd.drill(box["file"], box["priv"], box["env"], work=tmp_path, free=_plenty)
    assert not res["ok"] and "synthetic" in res["error"]
    assert res["scratch_dropped"] and _scratch_dbs(box["url"]) == []
    assert res["unpacked_removed"] and not list(tmp_path.glob("tb-drill-*"))


def test_rows_that_differ_from_the_manifest_fail_the_drill(
    box: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = rd.compare
    monkeypatch.setattr(rd, "compare", lambda src, want: [*real(src, want), "site.marks"])
    res = rd.drill(box["file"], box["priv"], box["env"], work=tmp_path, free=_plenty)
    assert not res["ok"] and "differ" in res["error"] and _scratch_dbs(box["url"]) == []


def test_short_space_refuses_before_anything_starts(box: dict[str, Any], tmp_path: Path) -> None:
    with pytest.raises(rd.DrillError, match=r"needs [0-9.]+ GB free"):
        rd.drill(box["file"], box["priv"], box["env"], work=tmp_path, free=lambda _p: 0)
    assert _scratch_dbs(box["url"]) == [] and not list(tmp_path.glob("tb-drill-*"))


def test_a_wrong_key_is_a_failed_drill_with_nothing_left(box: dict[str, Any], tmp_path: Path) -> None:
    other, _ = tmp_path / "other.key", tmp_path / "other.pub"
    bk.keygen(other, tmp_path / "other.pub")
    res = rd.drill(box["file"], other, box["env"], work=tmp_path, free=_plenty)
    assert not res["ok"] and _scratch_dbs(box["url"]) == [] and res["unpacked_removed"]


# ------------------------------------------------------------------------- the record, the health check, the alert
def _ok(at: datetime) -> dict[str, Any]:
    return {"ok": True, "at": at.isoformat(timespec="seconds"), "file": "trialbox-CGMH-x.tbbak", "sha256": "ab",
            "created_at": "2026-11-15T01:00:00+00:00", "databases": {"trialbox_wf": {"tables": 3, "rows": 5}}}  # fmt: skip


def test_a_pass_is_the_key_check_record_and_a_fail_is_red_until_the_next_pass(tmp_path: Path) -> None:
    th = metrics.Thresholds()
    now = datetime(2026, 11, 16, tzinfo=UTC)
    metrics.record_drill(tmp_path, _ok(now - timedelta(days=1)))
    rec = metrics.read_verified(tmp_path)
    assert rec and rec["drill"] == {"trialbox_wf": {"tables": 3, "rows": 5}}
    assert metrics.check_verified(rec, now, th).level == metrics.OK
    assert "restore drill passed" in metrics.check_verified(rec, now, th).text
    metrics.record_drill(tmp_path, {"ok": False, "at": now.isoformat(), "file": "f", "error": "pg_restore failed"})
    rec = metrics.read_verified(tmp_path)
    red = metrics.check_verified(rec, now, th)
    assert red.level == metrics.RED and "restore drill" in red.text and "pg_restore failed" in red.text
    assert rec is not None and rec["at"] == (now - timedelta(days=1)).isoformat(
        timespec="seconds"
    )  # the last good check is kept
    metrics.record_drill(tmp_path, _ok(now + timedelta(hours=1)))
    assert metrics.check_verified(metrics.read_verified(tmp_path), now + timedelta(hours=2), th).level == metrics.OK


def test_red_after_the_interval_without_a_new_drill(tmp_path: Path) -> None:
    th = metrics.Thresholds()
    then = datetime(2026, 1, 1, tzinfo=UTC)
    metrics.record_drill(tmp_path, _ok(then))
    rec = metrics.read_verified(tmp_path)
    assert metrics.check_verified(rec, then + timedelta(days=th.verified_red_days + 1), th).level == metrics.RED
    assert metrics.check_verified(rec, then + timedelta(days=th.verified_warn_days + 1), th).level == metrics.WARN


def test_a_failed_drill_is_a_backup_problem_for_the_alert_route(tmp_path: Path) -> None:
    metrics.record_drill(tmp_path, {"ok": False, "at": "2026-11-16T00:00:00+00:00", "file": "f", "error": "boom"})
    said = bsch.drill_failure(tmp_path)
    assert "restore drill" in said and "boom" in said and "RUNBOOK §5" in said
    metrics.record_drill(tmp_path, _ok(datetime(2026, 11, 16, 1, tzinfo=UTC)))
    assert bsch.drill_failure(tmp_path) == ""
    cfg = bsch.Config(deploy=tmp_path, targets=[], public_key=tmp_path / "pub", production=False)
    metrics.record_drill(tmp_path, {"ok": False, "at": "2026-11-16T02:00:00+00:00", "file": "f", "error": "boom"})
    assert any("restore drill" in p for p in bsch.status(cfg)["problems"])


def test_neither_the_key_nor_its_path_is_kept(box: dict[str, Any], tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    res = rd.drill(box["file"], box["priv"], box["env"], work=tmp_path, free=_plenty)
    rd.record(deploy, res, box["env"], box["dirs"])
    key = box["priv"].read_text(encoding="utf-8")
    for f in [deploy / "site" / metrics.VERIFIED_FILE, *box["dirs"]["audit"].rglob("*.jsonl")]:
        text = f.read_text(encoding="utf-8")
        assert str(box["priv"]) not in text and "usb" not in text and key.strip()[-20:] not in text
    events = [json.loads(x) for f in box["dirs"]["audit"].rglob("*.jsonl") for x in f.read_text().splitlines()]
    assert any(e.get("event") == rd.EVENT and e["detail"]["ok"] for e in events)


def test_the_command_prints_the_result_and_exits_by_it(
    box: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    for k, v in box["env"].items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(shutil, "disk_usage", lambda _p: type("U", (), {"free": 10**12})())
    deploy = tmp_path / "deploy"
    args = ["restore-drill", str(box["file"]), "--key", str(box["priv"]), "--work", str(tmp_path),
            "--db-dir", str(tmp_path), "--deploy", str(deploy), "--dir", f"audit={box['dirs']['audit']}"]  # fmt: skip
    assert cli(args) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and (deploy / "site" / metrics.VERIFIED_FILE).is_file()
    monkeypatch.setattr(shutil, "disk_usage", lambda _p: type("U", (), {"free": 0})())
    assert cli(args) == 2 and "GB free" in capsys.readouterr().err
