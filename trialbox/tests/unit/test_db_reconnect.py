"""Review A-02 (D-142): a store survives a lost database connection.

Each store keeps one connection (one serialised writer, as before). When the server drops it (a Postgres restart, a
killed backend), the next call reopens it: ``BEGIN`` on a dead connection is retried once on a fresh one, since
nothing of the transaction ran. A failure inside a transaction is still raised (never repeated), and the call after
it works. The console's ``/healthz`` and the services' health checks touch the database.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest
from tb_common.db import Database, split_url

from tools import pglocal


def _kill(db: Database, url: str) -> None:
    """Terminate ``db``'s backend from a second connection (as a restart or an OOM kill would)."""
    pid = db.fetchval("SELECT pg_backend_pid()")
    with Database.connect(url, "killer") as k:
        k.execute("SELECT pg_terminate_backend(?)", (pid,))


def test_a_killed_connection_is_reopened_for_the_next_call(db_url: str) -> None:
    db = Database.connect(db_url, "reconn")
    db.migrate(["CREATE TABLE t (k TEXT PRIMARY KEY, v TEXT)"])
    db.execute("INSERT INTO t VALUES (?, ?)", ("a", "1"))
    before = db.fetchval("SELECT pg_backend_pid()")
    _kill(db, db_url)
    assert db.fetchval("SELECT v FROM t WHERE k = ?", ("a",)) == "1"  # read: reopened, same schema
    assert db.fetchval("SELECT pg_backend_pid()") != before and db.reconnects == 1
    _kill(db, db_url)
    db.execute("INSERT INTO t VALUES (?, ?)", ("b", "2"))  # a write after a loss works too
    assert db.fetchall("SELECT k FROM t ORDER BY k") == [("a",), ("b",)]
    db.migrate(["CREATE TABLE t (k TEXT PRIMARY KEY, v TEXT)", "ALTER TABLE t ADD COLUMN w TEXT"])  # still locked
    assert db.fetchval("SELECT max(version) FROM _schema_version") == 2
    assert db.schema.endswith("reconn") and db.schema.startswith(split_url(db_url)[1])  # tb_prefix kept
    db.close()


def test_a_failure_inside_a_transaction_is_raised_and_the_next_call_works(db_url: str) -> None:
    db = Database.connect(db_url, "reconn2")
    db.migrate(["CREATE TABLE t (k TEXT PRIMARY KEY)"])
    with pytest.raises(Exception), db.transaction() as tx:  # noqa: B017 - psycopg's own error class
        tx.execute("INSERT INTO t VALUES (?)", ("a",))
        _kill(db, db_url)
        tx.execute("INSERT INTO t VALUES (?)", ("b",))
    assert db.fetchall("SELECT k FROM t") == []  # rolled back by the server, never half-written or repeated
    db.close()


@pytest.fixture
def own_cluster() -> Any:
    """A throwaway cluster of its own: this test restarts it (the session's is shared by every test)."""
    root = Path(tempfile.mkdtemp(prefix="tb-pgrestart-"))
    root.chmod(0o755)
    url = pglocal.ensure(root)
    yield root, url
    pglocal.stop(root)
    shutil.rmtree(root, ignore_errors=True)


def test_a_postgres_restart_does_not_take_the_store_down(own_cluster: Any) -> None:
    root, url = own_cluster
    db = Database.connect(url + "?tb_prefix=r1_" if "?" not in url else url + "&tb_prefix=r1_", "store")
    db.migrate(["CREATE TABLE t (k TEXT PRIMARY KEY)"])
    db.execute("INSERT INTO t VALUES (?)", ("kept",))
    # a restart as `docker compose restart db` does it: a fast shutdown (clients are told, data is flushed), a start
    pg_ctl = str(pglocal.bindir() / "pg_ctl")
    r = subprocess.run(
        [*pglocal._as_postgres_user(), pg_ctl, "-D", str(root / "data"), "-m", "fast", "-w", "stop"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    pglocal.ensure(root)  # the same data directory comes back
    assert db.fetchall("SELECT k FROM t") == [("kept",)]
    assert db.ping() == {"db:r1_store": "ok"}
    db.close()
