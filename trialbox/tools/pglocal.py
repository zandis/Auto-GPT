"""A throwaway local PostgreSQL for the test suite, ``e2e_simple``, ``public_e2e`` and the demo (D-126).

    python -m tools.pglocal start /tmp/tb-pg      # prints a TB_DB_URL; idempotent (reuses a running cluster)
    python -m tools.pglocal stop /tmp/tb-pg

In code: ``url = ensure(Path("/tmp/tb-pg"))``. The cluster listens on a Unix socket in its own directory only (no
TCP port), trusts the local user, and runs with ``fsync=off``: it is for tests and demos, never for a box, where the
compose ``db`` service is the database. The PostgreSQL server binaries are found through ``TB_PG_BIN``,
``pg_config --bindir`` or ``/usr/lib/postgresql/<n>/bin``.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

DB = "trialbox_wf"


def bindir() -> Path:
    env = os.environ.get("TB_PG_BIN")
    if env:
        return Path(env)
    if shutil.which("pg_config"):
        out = subprocess.run(["pg_config", "--bindir"], capture_output=True, text=True, check=False).stdout.strip()
        if out and (Path(out) / "initdb").exists():
            return Path(out)
    found = sorted(Path("/usr/lib/postgresql").glob("*/bin/initdb"), key=lambda p: int(p.parent.parent.name))
    if found:
        return found[-1].parent
    if shutil.which("initdb"):
        return Path(str(shutil.which("initdb"))).parent
    raise RuntimeError("no PostgreSQL server binaries (initdb): install postgresql or set TB_PG_BIN")


def url_for(root: Path) -> str:
    return f"postgresql://{_user()}@/{DB}?host={(root / 'run').resolve()}"


def _user() -> str:
    return "trialbox"


def _run(cmd: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False, **kw)  # type: ignore[call-overload,no-any-return]


def _as_postgres_user() -> list[str]:
    """initdb and the server refuse to run as root: run them as an unprivileged owner of the directory."""
    if os.geteuid() != 0:
        return []
    for who in ("postgres", "nobody"):
        if _run(["id", who]).returncode == 0:
            return ["runuser", "-u", who, "--"]
    raise RuntimeError("running as root and no 'postgres' user to own the throwaway cluster")


def running(root: Path) -> bool:
    return (root / "data" / "postmaster.pid").exists() and _run(
        [str(bindir() / "pg_isready"), "-h", str((root / "run").resolve()), "-q"]
    ).returncode == 0


def ensure(root: Path) -> str:
    """Start (or reuse) the cluster under ``root`` and return its ``TB_DB_URL``."""
    root = root.resolve()
    data, sock = root / "data", root / "run"
    pre = _as_postgres_user()
    if running(root):
        return url_for(root)
    root.mkdir(parents=True, exist_ok=True)
    sock.mkdir(exist_ok=True)
    if pre:
        owner = pre[2]
        shutil.chown(root, owner)
        shutil.chown(sock, owner)
    b = bindir()
    if not (data / "PG_VERSION").exists():
        if data.exists():
            shutil.rmtree(data)
        r = _run([*pre, str(b / "initdb"), "-D", str(data), "-U", "postgres", "-A", "trust", "-E", "UTF8",
                  "--locale=C.UTF-8", "--no-instructions"])  # fmt: skip
        if r.returncode != 0:
            r = _run([*pre, str(b / "initdb"), "-D", str(data), "-U", "postgres", "-A", "trust", "-E", "UTF8",
                      "--locale=C"])  # fmt: skip
        if r.returncode != 0:
            raise RuntimeError(f"initdb failed: {r.stderr.strip()[-400:]}")
    opts = f"-c listen_addresses='' -c unix_socket_directories='{sock}' -c fsync=off -c synchronous_commit=off " \
           "-c full_page_writes=off -c max_connections=300"  # fmt: skip
    r = _run([*pre, str(b / "pg_ctl"), "-D", str(data), "-l", str(root / "server.log"), "-o", opts, "-w", "start"])
    if r.returncode != 0 and not running(root):
        log = (root / "server.log").read_text(errors="replace")[-600:] if (root / "server.log").exists() else ""
        raise RuntimeError(f"pg_ctl start failed: {r.stderr.strip()[-300:]} {log}")
    for _ in range(50):
        if running(root):
            break
        time.sleep(0.1)
    psql = [*pre, str(b / "psql"), "-h", str(sock), "-U", "postgres", "-d", "postgres", "-tAqc"]
    if _run([*psql, f"SELECT 1 FROM pg_roles WHERE rolname='{_user()}'"]).stdout.strip() != "1":
        _run([*psql, f"CREATE ROLE {_user()} LOGIN CREATEDB"])
    if _run([*psql, f"SELECT 1 FROM pg_database WHERE datname='{DB}'"]).stdout.strip() != "1":
        r = _run([*psql, f"CREATE DATABASE {DB} OWNER {_user()}"])
        if r.returncode != 0:
            raise RuntimeError(f"create database failed: {r.stderr.strip()}")
    return url_for(root)


def stop(root: Path) -> None:
    data = root.resolve() / "data"
    if (data / "postmaster.pid").exists():
        _run([*_as_postgres_user(), str(bindir() / "pg_ctl"), "-D", str(data), "-m", "immediate", "stop"])


SHARED = Path(os.environ.get("TB_PG_DIR") or f"/tmp/tb-pglocal-{os.getuid()}")


def for_work(work: Path) -> str:
    """The ``TB_DB_URL`` for a run whose files live in ``work`` (e2e_simple, public_e2e, the demos, the in-process box).

    ``TB_DB_URL`` in the environment wins (a box, CI with its own server, a test's ``db_url`` fixture). Otherwise
    one shared throwaway cluster (``TB_PG_DIR``, default ``/tmp/tb-pglocal-<uid>``) gives each work directory its own
    schemas (prefix from the directory's path). A new work directory (no ``.tb_db`` marker) starts from empty
    schemas, as it starts from empty files. The URL is also put in ``os.environ``.
    """
    if os.environ.get("TB_DB_URL"):
        return os.environ["TB_DB_URL"]
    import hashlib

    base = ensure(SHARED)
    prefix = "w" + hashlib.sha1(str(work.resolve()).encode()).hexdigest()[:10] + "_"
    marker = work / ".tb_db"
    if not marker.exists():
        drop_prefix(base, prefix)
        work.mkdir(parents=True, exist_ok=True)
        marker.write_text(prefix + "\n", encoding="utf-8")
    url = f"{base}&tb_prefix={prefix}"
    os.environ["TB_DB_URL"] = url
    return url


def drop_prefix(url: str, prefix: str) -> None:
    """Drop every schema whose name starts with ``prefix`` (never all of them: an empty prefix is refused)."""
    if not prefix:
        raise ValueError("drop_prefix: an empty prefix would drop every schema in the database")
    import psycopg
    from tb_common.db import split_url

    dsn, _ = split_url(url)
    with psycopg.connect(dsn, autocommit=True) as con:
        names = [
            r[0] for r in con.execute("SELECT nspname FROM pg_namespace WHERE starts_with(nspname, %s)", (prefix,))
        ]
        for n in names:
            con.execute(f'DROP SCHEMA "{n}" CASCADE')


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=["start", "stop", "url"])
    ap.add_argument("root", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "start":
        print(ensure(a.root))
    elif a.cmd == "stop":
        stop(a.root)
    else:
        print(url_for(a.root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
