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

from tests import pg_client
from tools.trialbox import backup as bk
from tools.trialbox import backup_schedule as bsch
from tools.trialbox import restore_drill as rd
from tools.trialbox.__main__ import main as cli


@pytest.fixture
def box(tmp_path: Path, db_url: str, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    for var, cmd in pg_client.env().items():  # the CLI forms read the process environment, as TB_DB_URL is set
        monkeypatch.setenv(var, cmd)
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
    env = {"TB_DB_URL": db_url, "TB_SITE_ID": "CGMH", **pg_client.env()}
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


def test_box_restore_with_the_installers_nocreatedb_owner(
    box: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Replace Docker transport only. Run the real PostgreSQL programs and the image's unpack and compare code."""
    import secrets
    from urllib.parse import urlsplit, urlunsplit

    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    from tools.trialbox import __main__ as entry
    from tools.trialbox import box_drill, update

    dsn = split_url(box["url"])[0]
    with psycopg.connect(dsn) as con:
        row = con.execute("SELECT rolname FROM pg_roles WHERE rolsuper AND rolcanlogin ORDER BY oid LIMIT 1").fetchone()
    assert row is not None
    admin = row[0]
    owner = "drill_" + secrets.token_hex(6)
    parts = urlsplit(box["url"])
    limited_url = urlunsplit(parts._replace(netloc=owner + "@" + parts.netloc.rpartition("@")[2]))
    settings = tmp_path / "deploy"
    settings.mkdir()
    (settings / ".env").write_text(f"TB_DB_URL={limited_url}\n")
    conn = conninfo_to_dict(dsn)
    pg_env = {"PGHOST": conn["host"], "POSTGRES_USER": admin, "POSTGRES_DB": conn["dbname"]}
    if "port" in conn:
        pg_env["PGPORT"] = conn["port"]

    visited = []
    audit_events = []
    run_cmd = update.run_cmd
    installed = box_drill.BoxDrill(settings)

    def docker(
        argv: list[str], stdin_file: Path | None = None, env: dict[str, str] | None = None, timeout: float | None = None
    ) -> str:  # run_cmd's signature (the audit send is bounded, review 1534)
        if argv[:2] == [*installed.box.docker, "inspect"]:
            assert argv[-1] == "synthetic-container-id"
            return json.dumps([{"Destination": "/var/lib/postgresql/data", "Source": str(tmp_path)}])
        if argv == installed.box._c("ps", "-q", "db"):
            return "synthetic-container-id"
        if box_drill.MODULE in argv:
            args = argv[argv.index(box_drill.MODULE) + 1 :]
            work = Path(next(v.removesuffix(":/work:ro").removesuffix(":/work") for v in argv if ":/work" in v))
            visited.append(args[0])
            if args[0] == "unpack":
                assert "--network" in argv and argv[argv.index("--network") + 1] == "none"
                assert f"{box['priv']}:/key:ro" in argv
                args = ["unpack", str(box["file"]), str(box["priv"])]
            else:
                assert "container:synthetic-container-id" in argv
                assert env == {"TB_DB_URL": limited_url} and limited_url not in argv
                assert str(box["priv"]) not in " ".join(argv)
                monkeypatch.setenv("TB_DB_URL", limited_url)
            return json.dumps(box_drill.image_step(args, work))
        assert argv[: len(installed.box.compose)] == installed.box.compose
        if "orchestrator" in argv:
            assert stdin_file is not None
            audit_events.append(json.loads(stdin_file.read_text()))
            return ""
        cmd = argv[argv.index("db") + 1 :]
        visited.append(cmd[0])
        tool = (
            pg_client.tool(cmd[0]) if cmd[0] in pg_client.TOOLS else cmd[0]
        )  # the db image's client, here the cluster's
        return run_cmd([tool, *cmd[1:]], stdin_file=stdin_file, env=pg_env)

    with psycopg.connect(dsn, user=admin, autocommit=True) as con:
        # A second, empty source database exercises a full HAPI dump alongside the workflow's schema-filtered dump.
        source_name = rd.SCRATCH_PREFIX + secrets.token_hex(6)
        privileged = make_conninfo(dsn, user=admin)
        rd._create(privileged, source_name)
        try:
            sources = {**box["env"], "TB_HAPI_DB_URL": make_conninfo(privileged, dbname=source_name)}
            box["file"], *_ = bk.backup([tmp_path / "both"], tmp_path / "box/backup.pub", env=sources, dirs=box["dirs"])
        finally:
            rd._drop(privileged, source_name)
        con.execute(sql.SQL("CREATE ROLE {} LOGIN NOCREATEDB").format(sql.Identifier(owner)))
        try:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                rd._create(split_url(limited_url)[0], rd.SCRATCH_PREFIX + secrets.token_hex(8))
            monkeypatch.setattr(installed.box, "run", docker)
            assert installed.data_dir() == tmp_path
            # The CLI's default deploy path is beside the signed release tools.
            monkeypatch.setattr(entry, "__file__", str(tmp_path / "tools/trialbox/__main__.py"))
            monkeypatch.setattr(update, "run_cmd", docker)
            monkeypatch.setenv("TB_DB_URL", "postgresql://wrong-host/wrong-db")
            assert cli(["restore-drill", str(box["file"]), "--key", str(box["priv"])], installed=True) == 0
            res = json.loads(capsys.readouterr().out)
            assert (settings / "site" / metrics.VERIFIED_FILE).is_file()
            assert [event["event"] for event in audit_events] == [rd.EVENT]
            assert str(box["priv"]) not in json.dumps(audit_events)
            assert res["ok"], res
            assert visited == ["unpack", "sh", "pg_restore", "compare", "sh", "pg_restore", "compare", "sh", "sh"]
            assert set(res["databases"]) == {"trialbox_wf", "hapi"}
            assert res["scratch_dropped"] and not _scratch_dbs(box["url"])
            assert res["unpacked_removed"] and res["databases"]["trialbox_wf"]["differ_count"] == 0
        finally:
            con.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(owner)))


def test_the_module_form_keeps_the_callers_connection_beside_site_settings(
    box: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Review of #1305 (12): ``python -m tools.trialbox restore-drill`` switched to the box's Compose stack whenever
    ``deploy/.env`` existed, ignoring the caller's TB_DB_URL and ``--dir``. Only the installed command uses the box."""
    for k, v in box["env"].items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(shutil, "disk_usage", lambda _p: type("U", (), {"free": 10**12})())
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / ".env").write_text("TB_DB_URL=postgresql://box-owner@db:5432/trialbox_wf\n", encoding="utf-8")
    rehearsal = tmp_path / "rehearsal-audit"
    rehearsal.mkdir()
    args = ["restore-drill", str(box["file"]), "--key", str(box["priv"]), "--work", str(tmp_path),
            "--db-dir", str(tmp_path), "--deploy", str(deploy), "--dir", f"audit={rehearsal}"]  # fmt: skip
    assert cli(args) == 0, capsys.readouterr().err
    assert json.loads(capsys.readouterr().out)["ok"]
    events = [json.loads(x) for f in rehearsal.rglob("*.jsonl") for x in f.read_text().splitlines()]
    assert any(e.get("event") == rd.EVENT for e in events)
