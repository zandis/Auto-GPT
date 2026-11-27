"""P-19: the provenance index equals the audit chain after a night, an update and a downgrade.

The walk's doctor said ``provenance_index FAIL, 108 row(s) missing`` and the count did not move across an update and a
downgrade. The audit drain is the index's only writer, and it passed lines over in two ways that nothing wrote back:

* a downgrade (an update's rollback) puts the trial database back from the rollback point's dump, the provenance
  tables with it, while the chain keeps every line drained since: those lines' rows were gone for good (only a
  ``trialbox provenance --rebuild`` by hand wrote them);
* the drain asked once, at its start, whether the index's tables were there: tables made after that were not written
  until the drain was started again.

Now the drain, when it finds the database put back to an older point (its journal resync), writes the index rows of
the chain's lines drained from journal rows the database no longer holds, and it asks again for the tables while
they are not there. Older lines are never written back: their rows are in the index or were taken out at an opt-out,
which only ``trialbox provenance --rebuild`` may judge, with the register. Real drain, real tables, real ``pg_dump``
and ``pg_restore`` on the test cluster; fixed times for the events; synthetic pseudonyms only.
"""

from __future__ import annotations

import itertools
import json
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from tb_common import provenance_index as idx
from tb_common.audit_writer import Drain, _dsn

from tools import pglocal

TZ = "Asia/Taipei"
PID_A = "0ca5381cfa6bdf1c22961d65579f93b3"
PID_B = "1afe78d42518132b113c5858cedcbb54"
_N = itertools.count()
#: the journal's columns as the drain reads them (``audit_writer.JOURNAL_SQL`` without its roles and grants)
JOURNAL = """CREATE SCHEMA audit;
CREATE TABLE audit.journal (seq bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  at timestamptz NOT NULL DEFAULT clock_timestamp(), db_role text NOT NULL, event text NOT NULL, ts text NOT NULL,
  fields jsonb NOT NULL)"""


@pytest.fixture
def box(pg_cluster_url: str) -> Iterator[str]:
    """A database of this test's own: the journal and the provenance index, as the role script makes them."""
    name = f"tb_p19_{os.getpid()}_{next(_N)}"
    with psycopg.connect(_dsn(pg_cluster_url), autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    dsn = psycopg.conninfo.make_conninfo(_dsn(pg_cluster_url), dbname=name)
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute(JOURNAL)
    try:
        yield dsn
    finally:
        with psycopg.connect(_dsn(pg_cluster_url), autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


def _send(dsn: str, n: int, call: str, pid: str) -> None:
    """One night's model call and the verdict it was used for, as a service hands them to the journal."""
    ts = f"2026-11-{n:02d}T02:00:00+08:00"
    call_f = {"model": "m-judge", "prompt_version": "judge_v4", "input_sha": "i", "output_sha": "o",
              "detail": {"call_id": call, "build_sha": f"b{n}", "prompt_sha": "p" * 64}}  # fmt: skip
    ref = {"ruleset": "GZQO", "version": "1.0.0", "job": f"J{n}", "pid": pid, "crit": "N-INC-01"}
    use_f = {"detail": {"record_kind": "verdict", "record_ref": ref, "calls": [call]}}
    with psycopg.connect(dsn, autocommit=True) as c:
        for event, fields in (("llm.call", call_f), ("ai.used", use_f)):
            c.execute("INSERT INTO audit.journal (db_role, event, ts, fields) VALUES ('tb_orchestrator', %s, %s, %s)",
                      (event, ts, json.dumps(fields)))  # fmt: skip


def _drain(dsn: str, chain: Path) -> int:
    """The audit-writer service started (as after an update or a downgrade) and run until the journal is empty."""
    d = Drain("postgresql://x@h/db", chain, TZ, connect=lambda: psycopg.connect(dsn, autocommit=True))
    d.open()
    try:
        return d.run(once=True, alive=None)
    finally:
        d.con.close()


def _check(dsn: str, chain: Path) -> idx.Diff:
    with psycopg.connect(dsn, autocommit=True) as c:
        return idx.check(c, chain)


def _pg(tool: str, *args: str) -> None:
    subprocess.run([str(pglocal.bindir() / tool), *args], check=True, capture_output=True, timeout=120)


def test_the_index_equals_the_chain_after_a_night_an_update_and_a_downgrade(box: str, tmp_path: Path) -> None:
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    _send(box, 20, "c1", PID_A)  # a night
    assert _drain(box, chain) == 2
    assert _check(box, chain).ok
    dump = tmp_path / "rollback.dump"  # the update: its rollback point, then the box runs on the new release
    _pg("pg_dump", "-Fc", "-f", str(dump), box)
    _send(box, 21, "c2", PID_B)
    assert _drain(box, chain) == 2
    assert _check(box, chain).ok
    with psycopg.connect(box, autocommit=True) as c:  # the downgrade: the database back to the rollback point
        c.execute("DROP SCHEMA audit, provenance CASCADE")
    _pg("pg_restore", "-d", box, str(dump))
    _drain(box, chain)  # the drain starts again on the restored database (it records the resync)
    diff = _check(box, chain)
    assert diff.ok, diff.missing
    with psycopg.connect(box, autocommit=True) as c:
        assert sorted(r[0] for r in c.execute("SELECT call_id FROM provenance.model_calls")) == ["c1", "c2"]


def test_tables_made_after_the_drain_started_are_written_without_a_restart(box: str, tmp_path: Path) -> None:
    chain = tmp_path / "audit"
    d = Drain("postgresql://x@h/db", chain, TZ, connect=lambda: psycopg.connect(box, autocommit=True))
    d.open()
    try:
        assert not d.index
        with psycopg.connect(box, autocommit=True) as c:
            c.execute(idx.INDEX_SQL)  # the role script, run after the drain was up
        _send(box, 22, "c3", PID_A)
        assert d.step() == 2
        assert d.index
        with psycopg.connect(box, autocommit=True) as c:
            assert [r[0] for r in c.execute("SELECT call_id FROM provenance.model_calls")] == ["c3"]
    finally:
        d.con.close()


def test_a_use_row_taken_out_at_an_opt_out_is_not_written_back_at_a_start(box: str, tmp_path: Path) -> None:
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    _send(box, 20, "c1", PID_A)
    _send(box, 21, "c2", PID_B)
    _drain(box, chain)
    with psycopg.connect(box, autocommit=True) as c:
        assert idx.erase(c, [PID_B]) == 1  # the newest use row of the index
    _drain(box, chain)  # started again on the same database: nothing is written back
    assert _check(box, chain).missing == [("provenance.model_uses", _hash_of(chain, "c2", "ai.used"), "c2")]
    with psycopg.connect(box, autocommit=True) as c:
        assert idx.check(c, chain, erased=[PID_B]).ok


def _hash_of(chain: Path, call: str, event: str) -> str:
    recs: list[dict[str, Any]] = [r for r in idx.chain_records(chain) if r.get("event") == event]
    return next(str(r["hash"]) for r in recs if call in ((r.get("detail") or {}).get("calls") or []))
