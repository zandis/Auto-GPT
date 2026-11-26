"""H-139: a PostgreSQL client tool that cannot be run is refused plainly, named with its setting, before any change.

On a host whose PostgreSQL is not on PATH, the backup met a bare ``FileNotFoundError: 'psql'``, and a restore emptied
the database's schemas before it found that ``pg_restore`` was missing. Each tool is given here as a command that does
not exist (a synthetic name under the test's own folder), the way a host without it would resolve it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tb_common.db import Database

from tests import pg_client
from tools.trialbox import backup as bk


def _missing(tmp_path: Path, name: str) -> str:
    return str(tmp_path / "no-such-folder" / name)


@pytest.fixture
def site(db_url: str) -> Database:
    db = Database.connect(db_url, "site")
    db.migrate(["CREATE TABLE marks (pid TEXT PRIMARY KEY, mark TEXT NOT NULL)"])
    db.execute("INSERT INTO marks VALUES (?, ?)", ("P1", "approach"))
    return db


@pytest.mark.parametrize(("var", "tool"), [("TB_PSQL_CMD", "psql"), ("TB_PG_DUMP_CMD", "pg_dump")])
def test_a_backup_without_a_client_tool_names_it_and_writes_nothing(
    tmp_path: Path, db_url: str, site: Database, var: str, tool: str
) -> None:
    priv, pub = tmp_path / "k.key", tmp_path / "k.pub"
    bk.keygen(priv, pub)
    env = {**pg_client.env(), "TB_DB_URL": db_url, "TB_SITE_ID": "CGMH", var: _missing(tmp_path, tool)}
    with pytest.raises(bk.BackupError) as got:
        bk.backup([tmp_path / "nas"], pub, env=env, dirs={})
    said = str(got.value)
    assert tool in said and var in said and "cannot be run" in said, said
    assert not list(tmp_path.rglob(f"*{bk.SUFFIX}")), "no backup file is written"


def test_a_dump_without_pg_dump_names_it(tmp_path: Path, db_url: str, site: Database) -> None:
    src = bk.db_sources({"TB_DB_URL": db_url})[0]
    with pytest.raises(bk.BackupError, match=r"pg_dump .*TB_PG_DUMP_CMD"):
        bk.dump(src, tmp_path / "x.dump", {"TB_PG_DUMP_CMD": _missing(tmp_path, "pg_dump")})
    assert not (tmp_path / "x.dump").exists()


def test_a_restore_without_pg_restore_is_refused_before_the_database_is_emptied(
    tmp_path: Path, db_url: str, site: Database
) -> None:
    src = bk.db_sources({"TB_DB_URL": db_url})[0]
    dump = tmp_path / "site.dump"
    bk.dump(src, dump, pg_client.env())
    with pytest.raises(bk.BackupError, match=r"pg_restore .*TB_PG_RESTORE_CMD"):
        bk.restore_db(src, dump, {"TB_PG_RESTORE_CMD": _missing(tmp_path, "pg_restore")})
    assert site.fetchall("SELECT pid, mark FROM marks") == [("P1", "approach")]  # the schema and its rows stay


def test_a_whole_restore_without_pg_restore_says_nothing_was_changed_never_that_the_box_is_half_restored(
    tmp_path: Path, db_url: str, site: Database
) -> None:
    """OCR 1498-3: the check came after the database was listed as replaced, so the put-back failed the same check
    and the refusal told the operator the untouched box "may be half restored or empty"."""
    priv, pub = tmp_path / "k.key", tmp_path / "k.pub"
    bk.keygen(priv, pub)
    env = {**pg_client.env(), "TB_DB_URL": db_url, "TB_SITE_ID": "CGMH"}
    made = bk.backup([tmp_path / "nas"], pub, env=env, dirs={})
    with pytest.raises(bk.BackupError) as got:
        bk.restore(made[0], priv, env={**env, "TB_PG_RESTORE_CMD": _missing(tmp_path, "pg_restore")},
                   dirs={}, running=lambda: [], no_copy=True)  # fmt: skip
    said = str(got.value)
    assert "pg_restore" in said and "TB_PG_RESTORE_CMD" in said, said
    assert "NOT put back" not in said and "half restored" not in said, said
    assert site.fetchall("SELECT pid, mark FROM marks") == [("P1", "approach")]
