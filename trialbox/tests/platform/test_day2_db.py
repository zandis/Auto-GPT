"""The platform's backup and restore jobs against a real database (T-633, D-416; acceptance 1 and 2 without a
cluster): the commands the CronJobs run, in the order they run them, with the database image's side played by the
same shell scripts (``pg-snapshot.sh``, ``pg-spool.sh``) and the PostgreSQL client tools on this machine. A backup
file appears on the share; the box is wiped; the restore job puts the rows and the files back; a restore over a box
that holds data keeps it first as one more encrypted backup. The same on a kind cluster: ``deploy/platform/kind-day2.sh``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

from tools.trialbox import backup as bk
from tools.trialbox import platform_day2 as d2

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "deploy" / "platform" / "base" / "day2"
NOW = datetime(2026, 11, 20, 4, 45, tzinfo=UTC)

pytestmark = pytest.mark.skipif(
    not (shutil.which("psql") and shutil.which("pg_dump") and shutil.which("pg_restore")),
    reason="needs the PostgreSQL client tools (psql, pg_dump, pg_restore) on PATH",
)


def _db(base: str, name: str) -> str:
    parts = urlsplit(base)
    with psycopg.connect(base, autocommit=True) as con:
        con.execute(f'DROP DATABASE IF EXISTS "{name}"')
        con.execute(f'CREATE DATABASE "{name}"')
    return urlunsplit((parts.scheme, parts.netloc, f"/{name}", parts.query, parts.fragment))


@pytest.fixture
def site(tmp_path: Path, pg_cluster_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, object]]:
    base = pg_cluster_url.split("?tb_prefix", maxsplit=1)[0].split("&tb_prefix", maxsplit=1)[0]
    tag = f"d2_{os.getpid()}"
    wf, hapi = _db(base, f"{tag}_wf"), _db(base, f"{tag}_hapi")
    with psycopg.connect(wf, autocommit=True) as con:
        con.execute("CREATE SCHEMA site")
        con.execute("CREATE TABLE site.marks (pid TEXT PRIMARY KEY, mark TEXT NOT NULL)")
        con.execute("INSERT INTO site.marks VALUES ('P1', 'approach'), ('P2', 'not_now')")
    with psycopg.connect(hapi, autocommit=True) as con:
        con.execute("CREATE TABLE hfj_resource (id INT PRIMARY KEY, kind TEXT)")
        con.execute("INSERT INTO hfj_resource VALUES (1, 'Patient')")
    vols = {n: tmp_path / "vol" / n for n in ("lake", "audit")}
    vols["lake"].mkdir(parents=True)
    (vols["lake"] / "patient.parquet").write_bytes(b"PAR1" + bytes(range(256)) * 10)
    vols["audit"].mkdir(parents=True)
    priv, pub = tmp_path / "envelope" / "backup.key", tmp_path / "cm" / "backup.pub"
    bk.keygen(priv, pub)
    env = {
        "TB_DB_URL": wf,
        "TB_HAPI_DB_URL": hapi,
        "TB_SITE_ID": "DEMO-PLATFORM",
        "TB_TZ": "UTC",
        "TB_BACKUP_DIRS": ",".join(f"{n}={p}" for n, p in vols.items()),
    }
    # the restore job's pg calls are `python -m tools.trialbox platform-day2 pg ...` in a child process, which has
    # the container's environment: the two connection variables among it
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(str(ROOT / p) for p in ("libs", "services", ".")))
    monkeypatch.setenv("TB_DB_URL", wf)
    monkeypatch.setenv("TB_HAPI_DB_URL", hapi)
    yield {"env": env, "vols": vols, "priv": priv, "pub": pub, "wf": wf, "hapi": hapi}
    with psycopg.connect(base, autocommit=True) as con:
        for n in (f"{tag}_wf", f"{tag}_hapi"):
            con.execute(f'DROP DATABASE IF EXISTS "{n}" WITH (FORCE)')


def _marks(url: str) -> list[tuple[str, str]]:
    with psycopg.connect(url) as con:
        return [(str(a), str(b)) for a, b in con.execute("SELECT pid, mark FROM site.marks ORDER BY pid").fetchall()]


def _backup_job(site: dict[str, object], spool: Path, share: Path, now: datetime) -> dict[str, object]:
    """The three containers of the CronJob trialbox-backup."""
    env = dict(site["env"])  # type: ignore[call-overload]
    assert d2.snapshot_prepare(spool, env) == ["trialbox_wf", "hapi"]
    script = (spool / "trialbox_wf.sql").read_text(encoding="utf-8")
    assert '--dbname "$TB_DB_URL"' in script and str(site["wf"]) not in script  # the variable, never the value
    r = subprocess.run(["sh", str(SCRIPTS / "pg-snapshot.sh"), str(spool)], env={**os.environ, **env},
                       capture_output=True, text=True, check=False)  # fmt: skip
    assert r.returncode == 0, r.stderr
    return d2.run_backup(share, site["pub"], {**env, "TB_PG_DUMP_DIR": str(spool)}, now=now)  # type: ignore[arg-type]


def _spool(spool: Path, env: dict[str, str]) -> subprocess.Popen[bytes]:
    """The restore job's database-image container."""
    return subprocess.Popen(["sh", str(SCRIPTS / "pg-spool.sh"), str(spool)], env={**os.environ, **env})


def _restore_env(site: dict[str, object], spool: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    shim = f"{sys.executable} -m tools.trialbox platform-day2 pg"
    monkeypatch.setenv("TB_PG_SPOOL", str(spool))  # the container's environment, which the pg calls inherit
    return {**site["env"], "TB_PG_SPOOL": str(spool), "TB_PG_DUMP_CMD": f"{shim} pg_dump",  # type: ignore[dict-item]
            "TB_PG_RESTORE_CMD": f"{shim} pg_restore"}  # fmt: skip


def test_backup_wipe_and_restore_through_the_job_commands(
    site: dict[str, object], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    share = tmp_path / "share" / "trialbox"
    rec = _backup_job(site, tmp_path / "spool", share, NOW)
    # acceptance 1: a backup file appears on the share, complete (its .sha256), with the record beside it
    f = share / rec["file"]["name"]  # type: ignore[index]
    assert f.is_file() and bk.read_sidecar(f) == rec["file"]["sha256"] and (share / d2.RECORD).is_file()  # type: ignore[index]
    man = bk.unpack(f, site["priv"], tmp_path / "unpacked")  # type: ignore[arg-type]
    assert man["site"] == "DEMO-PLATFORM" and set(man["databases"]) == {"trialbox_wf", "hapi"}
    assert man["databases"]["trialbox_wf"]["rows_from"] == "snapshot"  # counted in the dump's own snapshot
    assert man["databases"]["trialbox_wf"]["rows"]["site.marks"][0] == 2
    shutil.rmtree(tmp_path / "unpacked")
    assert d2.pick(share, "newest") == f
    # acceptance 2: wipe the box (databases and claims) ...
    vols: dict[str, Path] = site["vols"]  # type: ignore[assignment]
    with psycopg.connect(str(site["wf"]), autocommit=True) as con:
        con.execute("DROP SCHEMA site CASCADE")
    with psycopg.connect(str(site["hapi"]), autocommit=True) as con:
        con.execute("DROP TABLE hfj_resource")
    for v in vols.values():
        shutil.rmtree(v)
        v.mkdir()  # a claim is a mount point: it is there, empty
    spool = tmp_path / "pgspool"
    env = _restore_env(site, spool, monkeypatch)
    side = _spool(spool, env)
    try:
        out = d2.run_restore(f, site["priv"], env, site["pub"], tmp_path / "share" / "pre-restore",  # type: ignore[arg-type]
                             now=NOW + timedelta(hours=1))  # fmt: skip
    finally:
        spool.mkdir(parents=True, exist_ok=True)
        (spool / d2.STOP).touch()
        side.wait(30)
    # ... and the restore puts it back
    assert out["ok"] and out["kept_copy"] is None and out["copy"] == "the box held no data"
    assert _marks(str(site["wf"])) == [("P1", "approach"), ("P2", "not_now")]
    with psycopg.connect(str(site["hapi"])) as con:
        assert con.execute("SELECT kind FROM hfj_resource").fetchall() == [("Patient",)]
    assert (vols["lake"] / "patient.parquet").read_bytes() == b"PAR1" + bytes(range(256)) * 10
    assert not [p for v in vols.values() for p in v.iterdir() if p.name.startswith(".tb-restore-")]
    audit = "".join(f.read_text(encoding="utf-8") for f in sorted(vols["audit"].glob("*.jsonl")))
    assert '"backup.restored"' in audit and '"backup.restore_copy"' in audit
    assert side.returncode == 0  # the database image's container ends with the job


def test_a_restore_over_data_keeps_the_box_first(
    site: dict[str, object], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    share = tmp_path / "share" / "trialbox"
    rec = _backup_job(site, tmp_path / "spool", share, NOW)
    f = share / rec["file"]["name"]  # type: ignore[index]
    with psycopg.connect(str(site["wf"]), autocommit=True) as con:  # a change after the backup
        con.execute("INSERT INTO site.marks VALUES ('P3', 'later')")
    vols: dict[str, Path] = site["vols"]  # type: ignore[assignment]
    (vols["lake"] / "after.parquet").write_bytes(b"later")
    spool = tmp_path / "pgspool"
    env = _restore_env(site, spool, monkeypatch)
    side = _spool(spool, env)
    keep = tmp_path / "share" / "pre-restore"
    try:
        out = d2.run_restore(f, site["priv"], env, site["pub"], keep, now=NOW + timedelta(hours=2))  # type: ignore[arg-type]
    finally:
        spool.mkdir(parents=True, exist_ok=True)
        (spool / d2.STOP).touch()
        side.wait(30)
    assert out["kept_copy"] and Path(out["kept_copy"]).parent == keep
    assert _marks(str(site["wf"])) == [("P1", "approach"), ("P2", "not_now")]  # the backup's state
    assert not (vols["lake"] / "after.parquet").exists()
    kept = bk.unpack(Path(out["kept_copy"]), site["priv"], tmp_path / "kept")  # type: ignore[arg-type]
    assert "dirs/lake/after.parquet" in kept["files"]  # the box as it was is in the kept copy
    assert kept["databases"]["trialbox_wf"]["rows"]["site.marks"][0] == 3
    # a restore that fails before the files are touched leaves the claims as they were
    (spool / d2.STOP).unlink()
    side = _spool(spool, env)
    try:
        with pytest.raises(bk.BackupError, match="site"):
            d2.run_restore(f, site["priv"], {**env, "TB_SITE_ID": "ANOTHER"}, site["pub"], keep,  # type: ignore[arg-type]
                           now=NOW + timedelta(hours=3))  # fmt: skip
    finally:
        (spool / d2.STOP).touch()
        side.wait(30)
    assert (vols["lake"] / "patient.parquet").is_file()
    assert not [p for v in vols.values() for p in v.iterdir() if p.name.startswith(".tb-restore-")]
