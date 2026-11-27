"""P-30: a box's first boot logs no ``relation "pidmap.site_key" does not exist``.

Before the first night no service has made schema ``pidmap`` (``adapter.pidmap`` makes it on first use), but the host
check asks for the site's row at every boot: once in ``deploy/check_host.sh`` and once in the doctor's launcher
(``tools.trialbox.doctor_image.pidmap_row``). Each read failed in the database, which logged the error twice. The read
now asks the catalog first: no table is "no row" (``none``), and the database logs nothing. Run against a real
database with no ``pidmap`` schema, then with the adapter's migrations applied.
"""

from __future__ import annotations

import re
import subprocess
import uuid
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import psycopg
import pytest
from tb_common.db import split_url

from tools import pglocal
from tools.trialbox import doctor_image

ROOT = Path(__file__).resolve().parents[2]
CHECK_HOST = ROOT / "deploy" / "check_host.sh"
SITE = "SITE-P30"


@pytest.fixture
def fresh_db(pg_cluster_url: str) -> Iterator[str]:
    """A database of its own on the test cluster (the SQL names schema ``pidmap`` with no test prefix)."""
    dsn = split_url(pg_cluster_url)[0]
    name = f"tb_p30_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(dsn, autocommit=True) as con:
        con.execute(f'CREATE DATABASE "{name}"')
    own = psycopg.conninfo.make_conninfo(dsn, dbname=name)
    try:
        yield own
    finally:
        with psycopg.connect(dsn, autocommit=True) as con:
            con.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _psql(dsn: str, args: Sequence[str], sql: str) -> subprocess.CompletedProcess[str]:
    """``psql`` as the box runs it inside the db container (``-U``/``-d`` are the box's; here the test database's)."""
    rest: list[str] = []
    it = iter(args)
    for a in it:
        if a in ("-U", "-d"):
            next(it)
            continue
        rest.append(a)
    return subprocess.run([str(pglocal.bindir() / "psql"), *rest, dsn], input=sql, capture_output=True, text=True,
                          check=False, timeout=60)  # fmt: skip


class _Box:
    """A runner for ``pidmap_row``: ``docker compose ... exec -T db psql ...`` is run with the real psql."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.ran: list[subprocess.CompletedProcess[str]] = []

    def __call__(self, cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        got = _psql(self.dsn, cmd[cmd.index("psql") + 1 :], kw.get("input") or "")
        self.ran.append(got)
        return got


def _check_host_sql() -> tuple[list[str], str]:
    """The psql arguments and the SQL ``deploy/check_host.sh`` sends for the pid map's row."""
    text = CHECK_HOST.read_text(encoding="utf-8")
    m = re.search(r"PIDMAP_OUT=\"\$\(.*?exec -T db (psql [^\n]*?) 2>/dev/null <<'SQL'\n(.*?)\nSQL\n", text, re.S)
    assert m, "check_host.sh reads the pid map's row with a quoted heredoc"
    args = [a.replace('"$SITE_ID"', SITE) for a in m.group(1).split()[1:]]
    return args, m.group(2) + "\n"


def _make_pidmap(dsn: str) -> None:
    from adapter.pidmap import MIGRATIONS

    with psycopg.connect(dsn, autocommit=True) as con:
        con.execute("CREATE SCHEMA pidmap")
        con.execute("SET search_path TO pidmap")
        for m in MIGRATIONS:
            con.execute(m)
        con.execute("INSERT INTO site_key (site_id, fingerprint, recorded_at, chartno_rule) VALUES (%s, %s, %s, %s)",
                    (SITE, "fp0123", "2026-11-27T00:00:00+00:00", "digits:8"))  # fmt: skip


def test_launcher_reads_no_pidmap_without_an_error(fresh_db: str, tmp_path: Path) -> None:
    box = _Box(fresh_db)
    got = doctor_image.pidmap_row(["docker"], tmp_path, {"TB_SITE_ID": SITE}, '[{"Id": "x"}]', box)
    assert [(r.returncode, r.stderr) for r in box.ran] == [(0, "")]
    assert got == "none"
    _make_pidmap(fresh_db)
    assert (
        doctor_image.pidmap_row(["docker"], tmp_path, {"TB_SITE_ID": SITE}, '[{"Id": "x"}]', box) == "fp0123|digits:8"
    )
    assert [(r.returncode, r.stderr) for r in box.ran][1:] == [(0, "")]


def test_check_host_reads_no_pidmap_without_an_error(fresh_db: str) -> None:
    args, sql = _check_host_sql()
    assert sql == doctor_image.PIDMAP_ROW_SQL, "one query in both readers"
    first = _psql(fresh_db, args, sql)
    assert (first.returncode, first.stderr, first.stdout.strip()) == (0, "", "")
    _make_pidmap(fresh_db)
    then = _psql(fresh_db, args, sql)
    assert (then.returncode, then.stderr, then.stdout.strip()) == (0, "", "fp0123|digits:8")
