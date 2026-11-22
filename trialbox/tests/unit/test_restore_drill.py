"""T-730d (D-892): ``trialbox restore-drill`` proves a backup restores, typed by hospital IT with the key in hand. It
restores into scratch databases, never the live one; cleans up after a failure too; refuses up front when space is
short; and its result is the key-check record the health check reads (red after the interval, or on a failed drill)
and a backup problem that goes through the alert route (D-735).

H-84: the drill restores into a throwaway database server of its own (a one-off container of the box's database
image, ``--network none``, reached through a socket folder of its own). The unit tier has no Docker daemon: a stand-in
``docker`` on PATH records every call and, for ``run -d``, links the throwaway's socket to the test cluster, so the
restore, the comparison and the clean-up below run for real against PostgreSQL and only Docker is stood in for. The
invariant test is ``test_a_drill_never_touches_the_live_server_or_any_object_of_the_box``."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from tb_common import metrics
from tb_common.db import Database, split_url

from tools import images_lock, pglocal
from tools.trialbox import backup as bk
from tools.trialbox import backup_schedule as bsch
from tools.trialbox import restore_drill as rd
from tools.trialbox.__main__ import main as cli

STANDIN = r"""
import json, os, stat, subprocess, sys, time
from pathlib import Path

argv = sys.argv[1:]
state_f = Path(os.environ["STANDIN_STATE"])
st = json.loads(state_f.read_text())
with open(os.environ["STANDIN_LOG"], "a") as log:
    log.write(json.dumps({"argv": argv, "pgpassword_in_env": bool(os.environ.get("PGPASSWORD"))}) + "\n")


def save():
    state_f.write_text(json.dumps(st))


def opt(args, flag):
    return [args[i + 1] for i, a in enumerate(args[:-1]) if a == flag]


cmd = argv[0] if argv else ""
if cmd == "version":
    if os.environ.get("STANDIN_NO_DAEMON"):
        print("Cannot connect to the Docker daemon", file=sys.stderr)
        sys.exit(1)
    print("27.0.0")
elif cmd == "image" and argv[1] == "inspect":
    if argv[-1] not in os.environ.get("STANDIN_IMAGES", "").split(","):
        print("Error: No such image: " + argv[-1], file=sys.stderr)
        sys.exit(1)
    print("sha256:0")
elif cmd == "run":
    name = opt(argv, "--name")[0]
    labels = dict(x.split("=", 1) for x in opt(argv, "--label"))
    mounts = [m.rsplit(":", 1)[0] if m.count(":") == 2 else m for m in opt(argv, "-v")]
    if "-d" not in argv:  # the one-off initdb: the password file is there, 0400, while it runs
        pw = [m.split(":")[0] for m in opt(argv, "-v") if m.split(":")[1] == "/run/tb-drill"][0]
        f = Path(pw) / "pw"
        st.setdefault("initdb", []).append({"pw_file": f.is_file(), "mode": oct(stat.S_IMODE(f.stat().st_mode))})
        save()
        if os.environ.get("STANDIN_FAIL_INITDB"):
            print("initdb: synthetic failure", file=sys.stderr)
            sys.exit(1)
        sys.exit(0)
    data = [m.split(":")[0] for m in mounts if m.split(":", 1)[1] == "/var/lib/postgresql/data"][0]
    st.setdefault("pw_at_start", []).append(any(Path(data).parent.rglob("pw")))  # removed once initdb is done
    st["containers"][name] = {"labels": labels, "mounts": mounts}
    save()
    for m in mounts:
        src, dst = m.split(":", 1)
        if src == dst:  # the socket folder, at the same path inside: the test cluster's socket stands in
            os.symlink(os.path.join(os.environ["STANDIN_PG_SOCK"], ".s.PGSQL.5432"), os.path.join(src, ".s.PGSQL.5432"))
    print("0" * 64)
elif cmd == "inspect":
    name = argv[-1]
    c = st["containers"].get(name)
    if c is None:
        print("Error: No such object: " + name, file=sys.stderr)
        sys.exit(1)
    print(c["labels"].get("tb.restore-drill", "<no value>"))
elif cmd == "ps":
    if os.environ.get("STANDIN_PS_ALL"):  # a docker that ignores the filter: the sweep's own label check must hold
        print("\n".join(st["containers"]))
        sys.exit(0)
    kind, key = opt(argv, "--filter")[0].split("=", 1)
    print("\n".join(n for n, c in st["containers"].items() if (key in n if kind == "name" else key in c["labels"])))
elif cmd == "rm":
    name = argv[-1]
    c = st["containers"].pop(name, None)
    save()
    if c is not None:  # its databases go with it, as a throwaway's data does
        drill = c["labels"].get("tb.restore-drill", "")
        for m in c["mounts"]:
            src, dst = m.split(":", 1)
            if src == dst and os.path.lexists(os.path.join(src, ".s.PGSQL.5432")):
                os.unlink(os.path.join(src, ".s.PGSQL.5432"))
        if drill:
            psql = [os.path.join(os.environ["STANDIN_PG_BIN"], "psql"), "-X", "-q", "-h", os.environ["STANDIN_PG_SOCK"],
                    "-U", "postgres", "-d", "postgres", "-tAc"]
            names = subprocess.run([*psql, f"SELECT datname FROM pg_database WHERE datname LIKE 'tb_drill_{drill}_%'"],
                                   capture_output=True, text=True).stdout.split()
            for n in names:
                subprocess.run([*psql, f'DROP DATABASE IF EXISTS "{n}" WITH (FORCE)'], capture_output=True)
elif cmd == "exec":
    name = [a for a in argv[1:] if not a.startswith("-") and a != "PGPASSWORD"][0]
    if name not in st["containers"]:
        print("Error: No such container: " + name, file=sys.stderr)
        sys.exit(1)
    rest = argv[argv.index(name) + 1 :]
    if os.environ.get("STANDIN_HANG"):
        Path(os.environ["STANDIN_HANG"]).write_text(str(os.getpid()))
        time.sleep(120)
    r = subprocess.run([os.path.join(os.environ["STANDIN_PG_BIN"], rest[0]), *rest[1:]])
    sys.exit(r.returncode)
"""

BOX_OBJECTS = {"containers": {"deploy-db-1": {"labels": {"com.docker.compose.project": "deploy"}, "mounts": []},
                              "tb-restore-drill-lookalike": {"labels": {}, "mounts": []}},
               "volumes": ["deploy_db-pg", "deploy_lake"], "networks": ["deploy_trialbox-net"]}  # fmt: skip


@pytest.fixture
def standin(tmp_path: Path, pg_cluster_url: str, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The stand-in ``docker`` on PATH, its state (the box's own objects planted in it) and its call log."""
    from psycopg.conninfo import conninfo_to_dict

    bindir = tmp_path / "standin-bin"
    bindir.mkdir()
    d = bindir / "docker"
    d.write_text(f"#!{sys.executable}\n{STANDIN}", encoding="utf-8")
    d.chmod(0o755)
    state, log = tmp_path / "standin-state.json", tmp_path / "standin-log.jsonl"
    state.write_text(json.dumps(BOX_OBJECTS), encoding="utf-8")
    log.write_text("", encoding="utf-8")
    sock = conninfo_to_dict(split_url(pg_cluster_url)[0]).get("host") or ""
    image = images_lock.load()["images"]["db"]["image"]
    for k, v in {"PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}", "STANDIN_STATE": str(state),
                 "STANDIN_LOG": str(log), "STANDIN_PG_SOCK": str(sock), "STANDIN_PG_BIN": str(pglocal.bindir()),
                 "STANDIN_IMAGES": image}.items():  # fmt: skip
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("POSTGRES_IMAGE", raising=False)
    owned: list[tuple[str, int, int]] = []
    monkeypatch.setattr(rd, "_chown", lambda p, u, g: owned.append((str(p), u, g)))  # not root here: said, not done
    return {"state": state, "log": log, "image": image, "owned": owned, "bin": bindir}


def _calls(standin: dict[str, Any]) -> list[dict[str, Any]]:
    return [json.loads(x) for x in standin["log"].read_text(encoding="utf-8").splitlines() if x.strip()]


def _objects(standin: dict[str, Any]) -> dict[str, Any]:
    return dict(json.loads(standin["state"].read_text(encoding="utf-8")))


@pytest.fixture
def box(tmp_path: Path, db_url: str, standin: dict[str, Any]) -> dict[str, Any]:
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
    return {"db": db, "dirs": dirs, "priv": priv, "file": f, "env": env, "url": db_url, "standin": standin}


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


# ------------------------------------------------------------------ H-84: the throwaway server, confined from the box
class _Recorder:
    """A planted live server: a TCP port that counts every connection attempt (the drill must make none)."""

    def __init__(self) -> None:
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.hits = 0
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                con, _ = self.sock.accept()
            except OSError:
                return
            self.hits += 1
            con.close()


@pytest.fixture
def live() -> Any:
    r = _Recorder()
    yield r
    r.sock.close()


def _planted_env(box: dict[str, Any], live: _Recorder) -> dict[str, str]:
    """The box's settings with the live database URL pointed at the recorder (same database name and tb_prefix), and
    the box's own restore route (an exec into the live db) as TB_PG_RESTORE_CMD."""
    prefix = box["url"].split("tb_prefix=", 1)[1]
    return {**box["env"], "TB_DB_URL": f"postgresql://trialbox:x@127.0.0.1:{live.port}/trialbox_wf?tb_prefix={prefix}",
            "TB_PG_RESTORE_CMD": "docker compose --project-directory deploy exec -T db pg_restore"}  # fmt: skip


SENTINEL = "PW-SENTINEL-not-a-real-password-0123456789abcdef"


def _assert_confined(box: dict[str, Any], live: _Recorder, work: Path, state: Path) -> None:
    s = box["standin"]
    assert live.hits == 0, "a connection was opened to the live server"
    after = _objects(s)
    assert {k: after[k] for k in ("volumes", "networks")} == {k: BOX_OBJECTS[k] for k in ("volumes", "networks")}
    assert {n: c for n, c in after["containers"].items() if not n.startswith("tb-restore-drill-") or
            "tb.restore-drill" not in c["labels"]} == BOX_OBJECTS["containers"]  # fmt: skip
    for c in _calls(s):
        a = c["argv"]
        assert a[0] in {"version", "image", "run", "inspect", "ps", "rm", "exec"}, a  # no compose, volume, network
        if a[0] in {"rm", "exec"}:
            assert any(x.startswith("tb-restore-drill-") for x in a) and "deploy-db-1" not in a, a
        if a[0] == "run":
            assert a[a.index("--network") + 1] == "none" and "-p" not in a and "--publish" not in a, a
            assert a.count("--network") == 1 and a[a.index("--pull") + 1] == "never", a
            for m in [a[i + 1] for i, x in enumerate(a) if x == "-v"]:
                src = m.split(":")[0]
                assert src.startswith((str(work), "/tmp/tbd-")) and "deploy" not in m and "docker" not in src, m
        assert SENTINEL not in json.dumps(a)
    assert _scratch_dbs(box["url"]) == []
    assert not [p for p in work.glob("tb-drill-*")] and not list(Path("/tmp").glob(f"tbd-*{os.getpid()}*"))
    assert not list(state.glob("*.json")), "a record is left: the drill did not clean up"
    assert box["db"].fetchall("SELECT count(*) FROM marks") == [(2,)]


@pytest.mark.parametrize("case", ["pass", "restore_fails", "mismatch", "initdb_fails"])
def test_a_drill_never_touches_the_live_server_or_any_object_of_the_box(
    box: dict[str, Any], tmp_path: Path, live: _Recorder, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """THE INVARIANT (H-84): during a drill no connection is opened to the live server and nothing of the box
    (container, volume, network, database, role, grant) is made, changed or removed; the result names only what was
    made; the password is on no command line, in no record and not in the result. SIGTERM and a crash: below."""
    monkeypatch.setattr(rd, "_password", lambda: SENTINEL)
    if case == "restore_fails":
        monkeypatch.setenv("STANDIN_PG_BIN", str(tmp_path / "nowhere"))
    if case == "mismatch":
        real = rd.compare
        monkeypatch.setattr(rd, "compare", lambda src, want: [*real(src, want), "site.marks"])
    if case == "initdb_fails":
        monkeypatch.setenv("STANDIN_FAIL_INITDB", "1")
    work, state = tmp_path / "work", tmp_path / "state"
    work.mkdir()
    (work / "tb-drill-deadbeef-server").mkdir()  # a look-alike folder without the drill's mark or a record
    res = rd.drill(box["file"], box["priv"], _planted_env(box, live), work=work, free=_plenty, state=state)
    (work / "tb-drill-deadbeef-server").rmdir()  # it was left alone (rmdir fails otherwise)
    _assert_confined(box, live, work, state)
    text = json.dumps(res)
    assert SENTINEL not in text and "PGPASSWORD" not in text
    s = box["standin"]
    assert all(i["pw_file"] and i["mode"] == "0o400" for i in _objects(s)["initdb"])
    assert not any(_objects(s).get("pw_at_start", []))
    assert all(c["pgpassword_in_env"] for c in _calls(s) if c["argv"][0] == "exec")
    assert not list(work.rglob("pw"))
    if case == "pass":
        assert res["ok"] and res["server"]["removed"] and res["scratch_dropped"], res
    elif case == "initdb_fails":  # nothing was created on a server that never started: nothing is listed
        assert not res["ok"] and "initdb" in res["error"] and "server" not in res, res
        assert res["scratch_dropped"] == [] and res["databases"] == {} and "left_behind" not in res, res
        assert "scratch_removed_with_server" not in res
    else:
        assert not res["ok"] and res["scratch_dropped"] and "left_behind" not in res, res
        assert ("differ" in res["error"]) if case == "mismatch" else ("pg_restore" in res["error"])


def test_the_throwaway_is_started_confined_with_the_box_image_limits_and_label(
    box: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rd, "_password", lambda: SENTINEL)
    res = rd.drill(box["file"], box["priv"], box["env"], work=tmp_path, free=_plenty)
    assert res["ok"], res
    runs = [c["argv"] for c in _calls(box["standin"]) if c["argv"][0] == "run"]
    assert len(runs) == 2
    init, srv = runs
    name = f"tb-restore-drill-{res['drill']}"
    for a in runs:
        for flag, want in (("--network", "none"), ("--pull", "never"), ("--user", "999:999"), ("--memory", rd.MEMORY),
                           ("--memory-swap", rd.MEMORY), ("--pids-limit", str(rd.PIDS)), ("--cap-drop", "ALL"),
                           ("--label", f"tb.restore-drill={res['drill']}")):  # fmt: skip
            assert a[a.index(flag) + 1] == want, (flag, a)
        assert "--rm" in a and "--read-only" in a and box["standin"]["image"] in a
        assert not any(x.startswith(("-p", "--publish", "--net=", "--network=", "--add-host", "--link")) and
                       x not in ("--pids-limit", "--pull") for x in a), a  # fmt: skip
        assert "-e" not in a and "--env" not in a and "--env-file" not in a, a  # no secret in the container's config
    assert init[init.index("--name") + 1] == f"{name}-init" and init[init.index("--entrypoint") + 1] == "initdb"
    assert "--pwfile=/run/tb-drill/pw" in init and "--auth-local=scram-sha-256" in init and "--auth-host=reject" in init
    assert srv[srv.index("--name") + 1] == name and "-d" in srv and srv[-2:] == ["-c", "listen_addresses="]
    mounts = [srv[i + 1] for i, x in enumerate(srv) if x == "-v"]
    sock = next(m.split(":")[0] for m in mounts if m.endswith(":/var/run/postgresql"))
    assert f"{sock}:{sock}" in mounts and len(mounts) == 3 and len(f"{sock}/.s.PGSQL.5432") <= rd.SOCK_MAX
    execs = [c["argv"] for c in _calls(box["standin"]) if c["argv"][0] == "exec"]
    assert execs and all(a[:5] == ["exec", "-i", "-e", "PGPASSWORD", name] and a[5] == "pg_restore" for a in execs)
    for a in execs:  # the very flags of trialbox restore (backup.restore_db), the throwaway's socket as the host
        assert a[6:11] == ["--clean", "--if-exists", "--no-owner", "--no-privileges", "--single-transaction"]
        assert f"host={sock}" in a[a.index("--dbname") + 1] and "password" not in a[a.index("--dbname") + 1]
    owned = {(Path(p).name, u, g) for p, u, g in box["standin"]["owned"]}  # the database user's, on a box (root)
    assert owned >= {("data", 999, 999), ("s", 999, 999), ("secret", 999, 999), ("pw", 999, 999)}


def test_refusals_start_nothing_and_say_why(
    box: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / "state"

    def nothing_made() -> None:
        assert not [c for c in _calls(box["standin"]) if c["argv"][0] in ("run", "exec", "rm")]
        assert (
            not list(state.glob("*.json")) and not list(tmp_path.glob("tb-drill-*")) and _scratch_dbs(box["url"]) == []
        )

    def run(**k: Any) -> dict[str, Any]:
        return rd.drill(box["file"], box["priv"], box["env"], work=tmp_path, free=_plenty, state=state, **k)

    monkeypatch.setenv("STANDIN_NO_DAEMON", "1")
    with pytest.raises(rd.DrillError, match="Docker is not available"):
        run()
    monkeypatch.delenv("STANDIN_NO_DAEMON")
    monkeypatch.setenv("STANDIN_IMAGES", "something-else:1")
    with pytest.raises(rd.DrillError, match="is not on this box.*never pulls"):
        run()
    monkeypatch.setenv("STANDIN_IMAGES", box["standin"]["image"])
    with pytest.raises(rd.DrillError, match="not enough free memory"):
        run(mem_free=lambda: 10)
    held = rd._lock(state)
    held.__enter__()
    try:
        with pytest.raises(rd.DrillError, match="still running"):
            run()
    finally:
        held.__exit__(None, None, None)
    nothing_made()
    assert not any(c["argv"][0] == "image" and "pull" in c["argv"] for c in _calls(box["standin"]))


def test_the_image_is_the_one_the_box_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    assert rd.db_image({}) == images_lock.load()["images"]["db"]["image"]
    assert rd.db_image({"POSTGRES_IMAGE": "site/postgres:16-x"}) == "site/postgres:16-x"  # as the compose file reads it


def _cli_env(box: dict[str, Any], live: _Recorder, **extra: str) -> dict[str, str]:
    root = Path(__file__).resolve().parents[2]
    return {**os.environ, **_planted_env(box, live), "PYTHONPATH": f"{root / 'libs'}:{root / 'services'}:{root}",
            **extra}  # fmt: skip


def _cli(box: dict[str, Any], tmp_path: Path, env: dict[str, str]) -> subprocess.Popen[bytes]:
    root = Path(__file__).resolve().parents[2]
    args = [sys.executable, "-m", "tools.trialbox", "restore-drill", str(box["file"]), "--key", str(box["priv"]),
            "--work", str(tmp_path / "work"), "--deploy", str(tmp_path / "deploy"),
            "--dir", f"audit={box['dirs']['audit']}"]  # fmt: skip
    return subprocess.Popen(args, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _wait_for(f: Path, p: subprocess.Popen[bytes]) -> None:
    end = time.monotonic() + 60
    while not f.exists():
        assert p.poll() is None, p.communicate()
        assert time.monotonic() < end, "the drill never reached its restore"
        time.sleep(0.1)


def test_sigterm_cleans_up_and_a_crash_is_swept_by_the_next_drill(
    box: dict[str, Any], tmp_path: Path, live: _Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "work").mkdir()
    state = tmp_path / "deploy" / "site" / "restore-drill"
    hang = tmp_path / "hang"
    env = _cli_env(box, live, STANDIN_HANG=str(hang))
    p = _cli(box, tmp_path, env)
    _wait_for(hang, p)
    p.send_signal(signal.SIGTERM)
    out, err = p.communicate(timeout=60)
    assert p.returncode == 130 and b"interrupted" in err, (out, err)
    _assert_confined(box, live, tmp_path / "work", state)
    # a crash (kill -9): nothing of its own clean-up runs; its record says what it made
    hang.unlink()
    p = _cli(box, tmp_path, env)
    _wait_for(hang, p)
    p.send_signal(signal.SIGKILL)
    p.wait(timeout=60)
    with contextlib.suppress(ProcessLookupError):  # the crashed drill's docker client, as an orphan, ends too
        os.kill(int(hang.read_text(encoding="utf-8")), signal.SIGKILL)
    p.communicate(timeout=60)
    recs = list(state.glob("*.json"))
    assert len(recs) == 1
    rec = json.loads(recs[0].read_text(encoding="utf-8"))
    assert f"tb-restore-drill-{rec['drill']}" in _objects(box["standin"])["containers"]
    assert all(Path(f).is_dir() for f in rec["folders"])
    lookalike = tmp_path / "work" / f"tb-drill-{rec['drill']}x-server"
    lookalike.mkdir()  # a folder with a drill's look but no mark: never swept
    forged = tmp_path / "work" / "tb-drill-feedface-server"
    forged.mkdir()  # named by a record, but without the drill's mark: never swept; nor is an unlabelled container
    (state / "feedface.json").write_text(json.dumps({"drill": "feedface", "folders": [str(forged)],
                                                     "containers": ["tb-restore-drill-lookalike"]}))  # fmt: skip
    monkeypatch.delenv("STANDIN_HANG", raising=False)
    res = rd.drill(box["file"], box["priv"], _planted_env(box, live), work=tmp_path / "work", free=_plenty,
                   state=state)  # fmt: skip
    assert res["ok"], res
    assert f"container tb-restore-drill-{rec['drill']}" in res["swept"]
    assert all(f"folder {f}" in res["swept"] for f in rec["folders"]) and not any(
        Path(f).exists() for f in rec["folders"]
    )
    assert "tb-restore-drill-lookalike" in _objects(box["standin"])["containers"] and lookalike.is_dir()
    assert forged.is_dir()  # (the record itself, naming nothing of a drill's, is dropped)
    lookalike.rmdir()
    forged.rmdir()
    _assert_confined(box, live, tmp_path / "work", state)


def test_the_sweep_removes_only_the_drills_own_containers_whatever_docker_lists(
    standin: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    objs = _objects(standin)
    objs["containers"]["tb-restore-drill-0badc0de"] = {"labels": {"tb.restore-drill": "0badc0de"}, "mounts": []}
    objs["containers"]["tb-restore-drill-cafe0000"] = {"labels": {"tb.restore-drill": "cafe0000"}, "mounts": []}
    standin["state"].write_text(json.dumps(objs), encoding="utf-8")
    # a record that names another drill's container: removed only when its label is the record's drill
    assert (
        rd._rm_container(["docker"], "tb-restore-drill-cafe0000", "0badc0de")
        and "tb-restore-drill-cafe0000" in (_objects(standin)["containers"])
    )
    monkeypatch.setenv("STANDIN_PS_ALL", "1")
    state = tmp_path / "state"
    state.mkdir()
    swept = rd.sweep(["docker"], state)
    left = _objects(standin)["containers"]
    assert sorted(swept) == ["container tb-restore-drill-0badc0de", "container tb-restore-drill-cafe0000"]
    assert left == BOX_OBJECTS["containers"]  # the box's db and the unlabelled look-alike are left alone
    assert not [c for c in _calls(standin) if c["argv"][0] == "rm" and c["argv"][-1] in BOX_OBJECTS["containers"]]
