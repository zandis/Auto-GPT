"""P-19: the provenance index equals the audit chain after a night, an update and a downgrade.

The walk's doctor said ``provenance_index FAIL, 108 row(s) missing`` and the count did not move across an update and a
downgrade. The audit drain is the index's only writer, and it passed lines over in two ways that nothing wrote back:

* a downgrade (an update's rollback) puts the trial database back from the rollback point's dump, the provenance
  tables with it, while the chain keeps every line drained since: those lines' rows were gone for good (only a
  ``trialbox provenance --rebuild`` by hand wrote them);
* the drain asked once, at its start, whether the index's tables were there: tables made after that were not written
  until the drain was started again.

Now every start of the drain owes a repair (``PROVENANCE_STATE`` in the audit directory, the one store a restore does
not put back), and the repair writes every row-bearing chain line the index does not hold, then sweeps. What stays
out is decided by the opt-out register alone, inside the database, on every insert (a trigger) and after a restore
(the sweep): an opt-out made after the dump, a registry refusal, a lift. Real drain, real tables, real ``pg_dump``
and ``pg_restore`` on the test cluster; a downgrade re-applies the live register before any service starts, as the
design asks of the update tool; fixed times for the events; synthetic pseudonyms only.
"""

from __future__ import annotations

import itertools
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

import psycopg
import pytest
from tb_common import provenance_index as idx
from tb_common.audit import AuditLog
from tb_common.audit_writer import Drain, _dsn
from tb_common.optout import REGISTRY_ACTOR, OptOutRegister

from tests.unit.test_provenance_index import REGISTER, register
from tools import pglocal
from tools.trialbox import update as up

TZ = "Asia/Taipei"
PID_A = "0ca5381cfa6bdf1c22961d65579f93b3"
PID_B = "1afe78d42518132b113c5858cedcbb54"
PID_C = "7f3e9a1c5b2d48e6a0c4f81b39d76e25"
_N = itertools.count()
#: the journal's columns as the drain reads them (``audit_writer.JOURNAL_SQL`` without its roles and grants)
JOURNAL = """CREATE SCHEMA audit;
CREATE TABLE audit.journal (seq bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  at timestamptz NOT NULL DEFAULT clock_timestamp(), db_role text NOT NULL, event text NOT NULL, ts text NOT NULL,
  fields jsonb NOT NULL)"""


@pytest.fixture
def box(pg_cluster_url: str) -> Iterator[str]:
    """A database of this test's own: the journal, the opt-out register and (run by each test) the provenance index,
    as the role script makes them."""
    name = f"tb_p19_{os.getpid()}_{next(_N)}"
    with psycopg.connect(_dsn(pg_cluster_url), autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    dsn = psycopg.conninfo.make_conninfo(_dsn(pg_cluster_url), dbname=name)
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute(JOURNAL)
        c.execute(REGISTER)
    try:
        yield dsn
    finally:
        with psycopg.connect(_dsn(pg_cluster_url), autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


def _fields(n: int, call: str, pid: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """The fields of one night's model call and of the verdict it was used for."""
    call_f = {"model": "m-judge", "prompt_version": "judge_v4", "input_sha": "i", "output_sha": "o",
              "detail": {"call_id": call, "build_sha": f"b{n}", "prompt_sha": "p" * 64}}  # fmt: skip
    ref = {"ruleset": "GZQO", "version": "1.0.0", "job": f"J{n}", "pid": pid, "crit": "N-INC-01"}
    return call_f, {"detail": {"record_kind": "verdict", "record_ref": ref, "calls": [call]}}


def _put(dsn: str, n: int, event: str, fields: dict[str, Any]) -> None:
    """One row a service hands to the journal, at 02:00 of day ``n``."""
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute("INSERT INTO audit.journal (db_role, event, ts, fields) VALUES ('tb_orchestrator', %s, %s, %s)",
                  (event, f"2026-11-{n:02d}T02:00:00+08:00", json.dumps(fields)))  # fmt: skip


def _send(dsn: str, n: int, call: str, pid: str) -> None:
    """One night's model call and the verdict it was used for, as a service hands them to the journal."""
    call_f, use_f = _fields(n, call, pid)
    _put(dsn, n, "llm.call", call_f)
    _put(dsn, n, "ai.used", use_f)


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


def _state(chain: Path) -> dict[str, Any]:
    return idx.read_state(chain)


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
    _restore(box, dump)  # the downgrade: the database back to the rollback point
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
    assert _opt_out(box, 22, PID_B) == 1  # the newest use row of the index
    _drain(box, chain)  # started again on the same database: nothing is written back
    assert _uses(box, PID_B) == []
    assert _check(box, chain).ok


# --- review of P-19 (P19-R1 to R5, F1 to F5): each case below fails on the first change


def _opt_out(dsn: str, n: int, pid: str) -> int:
    """The opt-out desk's no, as the console's transaction will make it (P19-DESIGN §5): under the index's lock, the
    register's row, the index's use rows erased, then ``console.opt_out`` journaled. The use rows erased."""
    fields = {"actor": "console:office1", "detail": {"pid": pid, "action": "opt_out", "reason": "", "source": "paper",
                                                     "removed_from": "screening, candidate lists, exports"}}  # fmt: skip
    at = f"2026-11-{n:02d}T09:00:00+08:00"
    with psycopg.connect(dsn, autocommit=True) as c, c.transaction():
        c.execute("SELECT pg_advisory_xact_lock(211989)")
        register(c, pid, "opt_out", at)
        gone = idx.erase(c, [pid])
        c.execute("INSERT INTO audit.journal (db_role, event, ts, fields) VALUES ('tb_console', 'console.opt_out', "
                  "%s, %s)", (at, json.dumps(fields)))  # fmt: skip
    return gone


def _restore(dsn: str, dump: Path) -> None:
    """The downgrade: the database back to the rollback point (the register and the index with it), then the live
    register's rows applied again before any service starts (P19-DESIGN §4: the live row wins)."""
    cols = "id, pid, action, source, note, by, at"
    with psycopg.connect(dsn, autocommit=True) as c:
        live = c.execute(f"SELECT {cols} FROM optout.optout_events").fetchall()
        c.execute("DROP SCHEMA audit, provenance, optout CASCADE")
    _pg("pg_restore", "-d", dsn, str(dump))
    with psycopg.connect(dsn, autocommit=True) as c:
        c.cursor().executemany(f"INSERT INTO optout.optout_events ({cols}) OVERRIDING SYSTEM VALUE "
                               "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING", live)  # fmt: skip
        c.execute("SELECT setval(pg_get_serial_sequence('optout.optout_events', 'id'), coalesce(max(id), 0) + 1, "
                  "false) FROM optout.optout_events")  # fmt: skip


def _calls(dsn: str) -> list[str]:
    with psycopg.connect(dsn, autocommit=True) as c:
        return sorted(str(r[0]) for r in c.execute("SELECT call_id FROM provenance.model_calls"))


def _uses(dsn: str, pid: str | None = None) -> list[str]:
    """The calls of the index's use rows (of one patient, or all), sorted."""
    with psycopg.connect(dsn, autocommit=True) as c:
        rows = c.execute("SELECT call_id FROM provenance.model_uses WHERE %(p)s::text IS NULL OR pid = %(p)s",
                         {"p": pid}).fetchall()  # fmt: skip
    return sorted(str(r[0]) for r in rows)


def test_an_opt_out_recorded_after_the_dump_stays_out_after_the_downgrade(box: str, tmp_path: Path) -> None:
    """P19-R1 / F1 (High): the dump's register is older than the opt-out; the live register, applied again after the
    restore, keeps B's row out."""
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    dump = tmp_path / "rollback.dump"
    _pg("pg_dump", "-Fc", "-f", str(dump), box)
    _send(box, 21, "c2", PID_B)  # B's verdict, then B says no and the use row goes
    _drain(box, chain)
    assert _opt_out(box, 22, PID_B) == 1
    _drain(box, chain)
    _restore(box, dump)
    _drain(box, chain)
    assert _uses(box, PID_B) == []
    assert _check(box, chain).ok
    assert _calls(box) == ["c1", "c2"]  # the call rows name no patient: they are written back


def test_a_row_journaled_before_the_dump_and_drained_after_it_is_written_back(box: str, tmp_path: Path) -> None:
    """P19-R2 / F2: the journal's newest row is not the index's newest line (a backlog at the dump, and a row a
    service journals after the restore and before the drain starts)."""
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    _send(box, 21, "c2", PID_A)  # in the journal, not yet drained, when the dump is taken
    dump = tmp_path / "rollback.dump"
    _pg("pg_dump", "-Fc", "-f", str(dump), box)
    _drain(box, chain)
    _send(box, 22, "c3", PID_B)
    _drain(box, chain)
    _restore(box, dump)
    _send(box, 23, "c4", PID_B)  # another service is up before the drain
    _drain(box, chain)
    diff = _check(box, chain)
    assert diff.ok, diff.missing
    assert _calls(box) == ["c1", "c2", "c3", "c4"]


def test_a_dump_taken_before_the_first_journal_row_is_caught_up(box: str, tmp_path: Path) -> None:
    """P19-R3 / F2: the restored journal is empty (no newest row at all); every line drained since is written back."""
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    dump = tmp_path / "rollback.dump"
    _pg("pg_dump", "-Fc", "-f", str(dump), box)
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    _restore(box, dump)
    _drain(box, chain)
    diff = _check(box, chain)
    assert diff.ok, diff.missing
    assert _calls(box) == ["c1"]


def test_a_catch_up_that_fails_part_way_is_tried_again_and_writes_each_row_once(
    box: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P19-R4 / F3: a failure after the first write leaves the recovery pending; the running drain tries it again."""
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    dump = tmp_path / "rollback.dump"
    _pg("pg_dump", "-Fc", "-f", str(dump), box)
    _send(box, 21, "c2", PID_B)
    _send(box, 22, "c3", PID_A)
    _drain(box, chain)
    _restore(box, dump)
    _flaky_add(monkeypatch)
    monkeypatch.setattr(Drain, "RETRY", 0.0, raising=False)  # tried again at the next batch, not a minute later
    d = Drain("postgresql://x@h/db", chain, TZ, connect=lambda: psycopg.connect(box, autocommit=True))
    d.open()
    try:
        assert _calls(box) == ["c1", "c2"]  # the first line was written, the rest was not
        _send(box, 23, "c4", PID_B)
        assert d.step() == 2
    finally:
        d.con.close()
    diff = _check(box, chain)
    assert diff.ok, diff.missing
    assert _calls(box) == ["c1", "c2", "c3", "c4"]
    assert _uses(box) == ["c1", "c2", "c3", "c4"]


def _flaky_add(monkeypatch: pytest.MonkeyPatch) -> None:
    """The catch-up's second line fails once: the database went away for a moment."""
    real, writes = idx.add, itertools.count()

    def flaky(con: Any, rec: dict[str, Any], *a: Any, **k: Any) -> int:
        if next(writes) == 1:
            raise psycopg.OperationalError("synthetic: the connection dropped")
        return real(con, rec, *a, **k)

    monkeypatch.setattr(idx, "add", flaky)


def test_a_line_whose_journal_time_cannot_be_read_is_not_passed_over(box: str, tmp_path: Path) -> None:
    """P19-R5: the catch-up does not judge a line by its journal time, so a naive or garbled one is written back."""
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    dump = tmp_path / "rollback.dump"
    _pg("pg_dump", "-Fc", "-f", str(dump), box)
    _send(box, 21, "c2", PID_B)
    _drain(box, chain)
    day = sorted(chain.glob("*.jsonl"))[-1]
    lines = day.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        rec = json.loads(line)
        if rec.get("event") == "llm.call" and (rec.get("detail") or {}).get("call_id") == "c2":
            rec["journal"]["at"] = "2026-11-21 02:00:00"  # no zone
            lines[i] = json.dumps(rec, sort_keys=True, ensure_ascii=False)
    day.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _restore(box, dump)
    _drain(box, chain)
    assert _calls(box) == ["c1", "c2"]


def test_index_not_installed_is_said_once_not_at_every_batch(
    box: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """F5: the drain asks before each batch while the tables are missing; it says so at its start only."""
    caplog.set_level("INFO", logger="tb.audit_writer")
    d = Drain("postgresql://x@h/db", tmp_path / "audit", TZ, connect=lambda: psycopg.connect(box, autocommit=True))
    d.open()
    try:
        for n in (20, 21):
            _send(box, n, f"c{n}", PID_A)
            assert d.step() == 2
    finally:
        d.con.close()
    assert sum("provenance index not installed" in r.getMessage() for r in caplog.records) == 1


# --- P19-DESIGN (reviews 1584 D1 to D7, N1 to N3): the register is the one authority, the repair obligation a file


def test_a_registry_refusal_in_the_register_is_withheld_at_catch_up(
    box: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """D1: the opt-out worker's copy of a registry refusal is a register row; its audit event holds counts only. The
    restore's catch-up withholds B's use row with no pseudonym written anywhere new."""
    caplog.set_level("DEBUG")
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    dump = tmp_path / "rollback.dump"
    _pg("pg_dump", "-Fc", "-f", str(dump), box)
    _send(box, 21, "c2", PID_B)
    _drain(box, chain)
    with psycopg.connect(box, autocommit=True) as c:  # the worker's copy; no console.opt_out anywhere
        register(c, PID_B, "opt_out", "2026-11-22T03:00:00+08:00", source="emr", by=REGISTRY_ACTOR)
    _restore(box, dump)
    _drain(box, chain)
    assert _uses(box, PID_B) == []
    assert _check(box, chain).ok
    assert _calls(box) == ["c1", "c2"]
    assert not any(r.get("event") == idx.OPT_OUT for r in idx.chain_records(chain))
    assert PID_B not in (chain / idx.STATE).read_text(encoding="utf-8")
    assert PID_B not in caplog.text


def test_a_use_row_in_the_dump_is_swept_after_the_restore(box: str, tmp_path: Path) -> None:
    """D2: B's use row is in the dump and B opts out after it: the restore puts the row back, the drain sweeps it."""
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    _send(box, 20, "c1", PID_A)
    _send(box, 21, "c2", PID_B)
    _drain(box, chain)
    dump = tmp_path / "rollback.dump"
    _pg("pg_dump", "-Fc", "-f", str(dump), box)
    assert _opt_out(box, 22, PID_B) == 1
    _drain(box, chain)
    _restore(box, dump)
    assert _uses(box, PID_B) == ["c2"]  # back from the dump, before the drain starts
    _drain(box, chain)
    assert _uses(box, PID_B) == []
    assert _state(chain)["state"] == idx.CLEAN
    assert _check(box, chain).ok


def test_a_restore_with_a_matching_cursor_still_repairs(box: str, tmp_path: Path) -> None:
    """D3: c2 is in the journal, undrained, at the dump, and drained after it: the restored journal holds the chain's
    last row exactly, so there is no resync, and the repair still runs."""
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    _send(box, 21, "c2", PID_A)
    dump = tmp_path / "rollback.dump"
    _pg("pg_dump", "-Fc", "-f", str(dump), box)
    _drain(box, chain)
    _restore(box, dump)
    _drain(box, chain)  # no new event in between
    assert not any(r.get("event") == "audit.journal_resync" for r in idx.chain_records(chain))
    assert _calls(box) == ["c1", "c2"]
    assert _uses(box) == ["c1", "c2"]
    assert _check(box, chain).ok


def test_a_fresh_drain_after_a_partial_failure_and_a_batch_finishes_the_repair(
    box: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D4: the repair fails part way, the drain indexes a new row before its retry is due and stops; the obligation is
    in the marker, so the next drain finishes it."""
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    dump = tmp_path / "rollback.dump"
    _pg("pg_dump", "-Fc", "-f", str(dump), box)
    _send(box, 21, "c2", PID_B)
    _send(box, 22, "c3", PID_A)
    _drain(box, chain)
    _restore(box, dump)
    _flaky_add(monkeypatch)
    monkeypatch.setattr(Drain, "RETRY", 3600.0)
    d = Drain("postgresql://x@h/db", chain, TZ, connect=lambda: psycopg.connect(box, autocommit=True))
    d.open()
    try:
        _send(box, 23, "c4", PID_B)
        assert d.step() == 2
        assert "c4" in _calls(box)  # indexed live, the retry not yet due
    finally:
        d.con.close()
    between = _state(chain)
    assert (between["state"], between["reason"], between["attempts"]) == (idx.REQUIRED, "repair failed", 1)
    _drain(box, chain)
    assert _state(chain)["state"] == idx.CLEAN
    assert _calls(box) == ["c1", "c2", "c3", "c4"]
    assert _uses(box) == ["c1", "c2", "c3", "c4"]


def test_a_failed_probe_at_the_resync_keeps_the_repair_owed(
    box: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """D5: the probe for the tables fails once at the start: the repair stays owed, the log says the index could not
    be read (not that it is absent), and the repair runs once the next probe answers."""
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    dump = tmp_path / "rollback.dump"
    _pg("pg_dump", "-Fc", "-f", str(dump), box)
    _send(box, 21, "c2", PID_A)
    _drain(box, chain)
    _restore(box, dump)
    real, once = idx.installed, iter([True])

    def probe(con: Any) -> bool:
        if next(once, False):
            raise psycopg.OperationalError("synthetic: the probe timed out")
        return real(con)

    monkeypatch.setattr(idx, "installed", probe)
    caplog.set_level("INFO", logger="tb.audit_writer")
    d = Drain("postgresql://x@h/db", chain, TZ, connect=lambda: psycopg.connect(box, autocommit=True))
    d.open()
    try:
        assert _state(chain)["state"] == idx.REQUIRED
        assert "could not be read" in caplog.text and "not installed" not in caplog.text
        _send(box, 22, "c3", PID_A)
        assert d.step() == 2
    finally:
        d.con.close()
    assert _state(chain)["state"] == idx.CLEAN
    assert _calls(box) == ["c1", "c2", "c3"]
    assert _check(box, chain).ok


def test_a_lift_releases_only_rows_after_it(box: str, tmp_path: Path) -> None:
    """D6: A's use before the opt-out and the one while it held stay out after the lift; the one after it is
    written, live and after the downgrade, and the check expects exactly that."""
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    dump = tmp_path / "rollback.dump"  # before all of it
    _pg("pg_dump", "-Fc", "-f", str(dump), box)
    _send(box, 20, "c1", PID_A)  # u1
    _drain(box, chain)
    assert _opt_out(box, 21, PID_A) == 1
    _send(box, 22, "c2", PID_A)  # u2, while A is out
    _drain(box, chain)
    with psycopg.connect(box, autocommit=True) as c:
        register(c, PID_A, "lift", "2026-11-23T09:00:00+08:00")
    _send(box, 24, "c3", PID_A)  # u3, after the lift
    _drain(box, chain)
    assert _uses(box, PID_A) == ["c3"]
    _restore(box, dump)
    _drain(box, chain)
    assert _uses(box, PID_A) == ["c3"]
    assert _check(box, chain).ok
    assert _calls(box) == ["c1", "c2", "c3"]


def test_catch_up_writes_a_line_with_a_naive_journal_time(box: str, tmp_path: Path) -> None:
    """D7: the record itself carries the naive journal time (its hash is valid), and the catch-up writes its rows."""
    log = AuditLog(tmp_path / "audit", TZ)
    recs = []
    for n, call, at in ((20, "c1", "2026-11-20T02:00:00+08:00"), (21, "c2", "2026-11-21 02:00:00")):
        call_f, use_f = _fields(n, call, PID_A)
        ts = datetime.fromisoformat(f"2026-11-{n:02d}T02:00:00+08:00")
        recs.append(log.append("llm.call", ts=ts, journal={"seq": 2 * n, "at": at}, **call_f))
        recs.append(log.append("ai.used", ts=ts, journal={"seq": 2 * n + 1, "at": at}, **use_f))
    (c2,) = [r for r in idx.chain_records(log.directory) if (r.get("detail") or {}).get("call_id") == "c2"]
    assert c2["journal"]["at"] == "2026-11-21 02:00:00"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
        for rec in recs[:2]:
            idx.add(c, rec)
        assert idx.catch_up(c, log.directory) == 2
    assert _calls(box) == ["c1", "c2"]
    assert _uses(box) == ["c1", "c2"]


def test_an_opt_out_between_the_restore_and_the_drains_start_is_withheld(box: str, tmp_path: Path) -> None:
    """N1 (the restore and the drain's start race): the console is up first and B opts out before the drain opens;
    the catch-up's insert of B's lost line reads the live register and is withheld."""
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    dump = tmp_path / "rollback.dump"
    _pg("pg_dump", "-Fc", "-f", str(dump), box)
    _send(box, 21, "c2", PID_B)
    _drain(box, chain)
    _restore(box, dump)
    assert _opt_out(box, 22, PID_B) == 0  # nothing of B's in the restored index yet
    _drain(box, chain)
    assert _uses(box, PID_B) == []
    assert "c2" in _calls(box)
    assert _check(box, chain).ok


def test_a_line_with_two_calls_is_written_whole_or_not_at_all(
    box: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N2: a verdict that used two calls gives two use rows; a failure between them leaves neither, so a line hash in
    the index means the whole line, and a retry writes both."""
    log = AuditLog(tmp_path / "audit", TZ)
    ts = datetime.fromisoformat("2026-11-21T02:00:00+08:00")
    calls = [log.append("llm.call", ts=ts, **_fields(21, c, PID_A)[0]) for c in ("c2", "c3")]
    ref = {"ruleset": "GZQO", "version": "1.0.0", "job": "J21", "pid": PID_A, "crit": "N-INC-01"}
    used = log.append("ai.used", ts=ts, detail={"record_kind": "verdict", "record_ref": ref, "calls": ["c2", "c3"]})
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
        for rec in calls:
            idx.add(c, rec)
        real, uses = c.execute, itertools.count()

        def second_fails(sql: Any, *a: Any, **k: Any) -> Any:
            if "INSERT INTO provenance.model_uses" in str(sql) and next(uses) == 1:
                raise psycopg.OperationalError("synthetic: the connection dropped")
            return real(sql, *a, **k)

        monkeypatch.setattr(c, "execute", second_fails)
        with pytest.raises(psycopg.OperationalError):
            idx.add(c, used)
        monkeypatch.undo()
        held = {str(r[0]) for t in idx.TABLES for r in c.execute(idx._KEYS[t]).fetchall()}
        assert used["hash"] not in held
        assert idx.add(c, used) == 2
        assert idx.check(c, log.directory).ok
    assert _uses(box) == ["c2", "c3"]


def test_a_failed_catch_up_leaves_the_connection_usable(
    box: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N3: on a connection that is not autocommit, a catch-up the database refuses part way leaves the transaction
    aborted; the drain rolls it back, so its next read works, and the repair stays owed."""
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    dump = tmp_path / "rollback.dump"
    _pg("pg_dump", "-Fc", "-f", str(dump), box)
    _send(box, 21, "c2", PID_A)
    _send(box, 22, "c3", PID_A)
    _drain(box, chain)
    _restore(box, dump)
    real, writes = idx.add, itertools.count()

    def refused(con: Any, rec: dict[str, Any]) -> int:
        if next(writes) == 1:
            con.execute("SELECT 1 / 0")  # the database refuses a statement: the transaction is aborted
        return real(con, rec)

    monkeypatch.setattr(idx, "add", refused)
    monkeypatch.setattr(Drain, "RETRY", 3600.0)
    d = Drain("postgresql://x@h/db", chain, TZ, connect=lambda: psycopg.connect(box, autocommit=False))
    d.open()
    try:
        assert d._rows() == []  # no InFailedSqlTransaction
        st = _state(chain)
        assert (st["state"], st["attempts"], st["last_error"]) == (idx.REQUIRED, 1, "DivisionByZero")
    finally:
        d.con.close()


#: the drain in a process of its own whose second catch-up line kills it (SIGKILL) after its first row, before its
#: transaction commits
_KILLED = """
import os, signal, sys
from pathlib import Path
import psycopg
from tb_common import provenance_index as idx
from tb_common.audit_writer import Drain

real, seen = idx.add, []

class Dying:
    def __init__(self, con):
        self.con = con

    def transaction(self):
        return self.con.transaction()

    def execute(self, *a, **k):
        cur = self.con.execute(*a, **k)
        os.kill(os.getpid(), signal.SIGKILL)
        return cur

def add(con, rec):
    seen.append(rec)
    return real(Dying(con) if len(seen) == 2 else con, rec)

idx.add = add
dsn = sys.argv[1]
d = Drain("postgresql://x@h/db", Path(sys.argv[2]), "Asia/Taipei",
          connect=lambda: psycopg.connect(dsn, autocommit=True))
d.open()
"""


def test_kill_9_mid_catch_up_is_finished_by_the_next_drain(box: str, tmp_path: Path) -> None:
    """P19-DESIGN §2: the drain is killed in the middle of the repair: the marker says ``repairing``, the line it was
    writing is in neither table, and the next drain finishes the repair."""
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    dump = tmp_path / "rollback.dump"
    _pg("pg_dump", "-Fc", "-f", str(dump), box)
    ref = {"ruleset": "GZQO", "version": "1.0.0", "job": "J21", "pid": PID_A, "crit": "N-INC-01"}
    _put(box, 21, "llm.call", _fields(21, "c2", PID_A)[0])  # three lines the restore loses
    _put(box, 21, "ai.used", {"detail": {"record_kind": "verdict", "record_ref": ref, "calls": ["c2", "c3"]}})
    _put(box, 21, "llm.call", _fields(21, "c3", PID_A)[0])
    _drain(box, chain)
    _restore(box, dump)
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(p for p in sys.path if p)}
    r = subprocess.run([sys.executable, "-c", _KILLED, box, str(chain)], env=env, capture_output=True, text=True,
                       timeout=120, check=False)  # fmt: skip
    assert r.returncode == -9, r.stderr[-1500:]
    assert _state(chain)["state"] == idx.REPAIRING
    assert _calls(box) == ["c1", "c2"]  # the first line
    assert _uses(box) == ["c1"]  # no part of the second
    _drain(box, chain)
    assert _state(chain)["state"] == idx.CLEAN
    assert _calls(box) == ["c1", "c2", "c3"]
    assert _uses(box) == ["c1", "c2", "c3"]
    assert _check(box, chain).ok


def test_search_refuses_while_the_repair_is_owed(box: str, tmp_path: Path) -> None:
    """§1: a restored index may hold rows the register withholds until the sweep: nothing is served until clean."""
    chain = tmp_path / "audit"
    chain.mkdir()
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    _send(box, 20, "c1", PID_A)
    idx.write_state(chain, state=idx.REQUIRED, reason="start", attempts=0)
    with psycopg.connect(box, autocommit=True) as c, pytest.raises(idx.ProvenanceUnderRepair):
        idx.search(c, model="m-judge", directory=chain)
    _drain(box, chain)
    with psycopg.connect(box, autocommit=True) as c:
        assert [r["call_id"] for r in idx.search(c, model="m-judge", directory=chain)] == ["c1"]


def test_the_doctor_check_agrees_with_the_writer(box: str, tmp_path: Path) -> None:
    """§1: A is out, B's opt-out was lifted, C never opted out: what the trigger wrote is what the check expects,
    before and after a rebuild."""
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
        register(c, PID_A, "opt_out", "2026-11-19T09:00:00+08:00")
        register(c, PID_B, "opt_out", "2026-11-19T09:00:00+08:00")
        register(c, PID_B, "lift", "2026-11-21T09:00:00+08:00")
    _send(box, 20, "c1", PID_A)
    _send(box, 20, "c2", PID_B)  # before B's lift
    _send(box, 22, "c3", PID_B)  # after it
    _send(box, 22, "c4", PID_C)
    _drain(box, chain)
    assert (_uses(box, PID_A), _uses(box, PID_B), _uses(box, PID_C)) == ([], ["c3"], ["c4"])
    with psycopg.connect(box, autocommit=True) as c:
        assert idx.check(c, chain).ok
        idx.rebuild(c, chain)
        assert idx.check(c, chain).ok
    assert (_uses(box, PID_A), _uses(box, PID_B), _uses(box, PID_C)) == ([], ["c3"], ["c4"])


def test_an_old_role_script_writes_no_unfiltered_index(
    box: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """§6.3: the tables without the register's trigger (a box on the old role script) are not the index: the drain
    writes the chain alone and says so."""
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
        c.execute("DROP TRIGGER model_uses_withhold ON provenance.model_uses")
        assert not idx.installed(c)
    caplog.set_level("INFO", logger="tb.audit_writer")
    _send(box, 20, "c1", PID_A)
    assert _drain(box, chain) == 2
    assert _calls(box) == [] and _uses(box) == []
    assert [r["event"] for r in idx.chain_records(chain) if r.get("event") in ("llm.call", "ai.used")] == [
        "llm.call",
        "ai.used",
    ]
    assert "provenance index not installed" in caplog.text


# --- review round 3 of P-19 (1584 codex P19-D1/D2, X1 to X8, N2; opus F1 to F6): the production paths


def _url(dsn: str) -> str:
    """The test's database as a ``TB_DB_URL`` (what ``OptOutRegister`` and ``trialbox provenance`` take)."""
    d = psycopg.conninfo.conninfo_to_dict(dsn)
    who, db = quote(str(d.pop("user")), safe=""), d.pop("dbname")
    return f"postgresql://{who}@/{db}?" + urlencode({k: str(v) for k, v in d.items()})


def _register(dsn: str) -> OptOutRegister:
    """The opt-out register as the console and the registry's worker open it (``tb_common.optout``: its own
    migration, in place of the fixture's hand-made table)."""
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute("DROP SCHEMA optout CASCADE")
    return OptOutRegister(_url(dsn))


def _rollback(dsn: str, dump: Path, tmp_path: Path) -> None:
    """The update's rollback of the trial database as ``ComposeBox.restore_databases`` runs it in the db container:
    ``update.RESTORE_SH`` under dash, the dump on stdin. Nothing of the live register is kept by this helper: what
    survives is what the production script keeps."""
    d = psycopg.conninfo.conninfo_to_dict(dsn)
    pgdata = tmp_path / "pgdata"  # the script's folder is under PGDATA, as on the db volume
    pgdata.mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    env.update(PGDATA=str(pgdata), POSTGRES_USER=str(d["user"]), PATH=f"{pglocal.bindir()}:{env.get('PATH', '')}")
    for key, var in (("host", "PGHOST"), ("port", "PGPORT"), ("password", "PGPASSWORD")):
        if d.get(key):
            env[var] = str(d[key])
    with dump.open("rb") as fh:
        r = subprocess.run([shutil.which("dash") or "sh", "-c", up.RESTORE_SH, "tb-restore", str(d["user"]),
                            str(d["dbname"]), up.RESET_SQL], stdin=fh, env=env, capture_output=True,
                           check=False)  # fmt: skip
    assert r.returncode == 0, r.stderr[-1200:]


def _events_of(dsn: str, pid: str) -> list[tuple[str, str]]:
    with psycopg.connect(dsn, autocommit=True) as c:
        return [(str(a), str(b)) for a, b in c.execute(
            "SELECT action, by FROM optout.optout_events WHERE pid = %s ORDER BY id", (pid,)).fetchall()]  # fmt: skip


@pytest.mark.parametrize("by", ["console:office1", REGISTRY_ACTOR])
def test_a_real_rollback_keeps_an_opt_out_made_after_the_dump(box: str, tmp_path: Path, by: str) -> None:
    """F1 / P19-D1 (High): B's verdict is drained after the dump, then B says no at the console, or the hospital's
    registry refuses (the worker's copy: counts only in the chain). The update's own rollback restores the dump; the
    drain's catch-up then finds B's line missing and writes it through the trigger: B's use row stays out."""
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    reg = _register(box)
    try:
        _send(box, 20, "c1", PID_A)
        _drain(box, chain)
        dump = tmp_path / "rollback.dump"
        _pg("pg_dump", "-Fc", "-f", str(dump), box)
        _send(box, 21, "c2", PID_B)
        _drain(box, chain)
        assert reg.add(PID_B, "emr" if by == REGISTRY_ACTOR else "paper", "", by, "2026-11-22T09:00:00+08:00")
    finally:
        reg.close()
    _rollback(box, dump, tmp_path)
    _drain(box, chain)
    assert _events_of(box, PID_B) == [("opt_out", by)]
    assert _uses(box, PID_B) == []
    assert _calls(box) == ["c1", "c2"]
    assert _check(box, chain).ok
    assert _state(chain)["state"] == idx.CLEAN


def test_a_real_rollback_sweeps_a_row_of_the_dump_before_the_database_is_served(box: str, tmp_path: Path) -> None:
    """P19-D2 (High) and X1: B's use row is in the dump and B opts out after it. The update's own rollback puts the
    register's later events back and sweeps before the restored database takes the old one's name, so no search can
    meet the row, whatever the marker still says; the drain then keeps it out."""
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    reg = _register(box)
    try:
        _send(box, 20, "c1", PID_A)
        _send(box, 21, "c2", PID_B)
        _drain(box, chain)
        dump = tmp_path / "rollback.dump"
        _pg("pg_dump", "-Fc", "-f", str(dump), box)
        assert reg.add(PID_B, "paper", "", "console:office1", "2026-11-22T09:00:00+08:00")
    finally:
        reg.close()
    _rollback(box, dump, tmp_path)
    assert _uses(box, PID_B) == []  # before the drain starts
    _drain(box, chain)
    assert _uses(box, PID_B) == []
    assert _uses(box, PID_A) == ["c1"]
    assert _check(box, chain).ok


def test_a_rollback_run_again_keeps_each_register_event_once(box: str, tmp_path: Path) -> None:
    """P19-D1: a rollback stopped after the swap is run again (the marker stays): the register it reads is the one
    the first run kept, and nothing is written twice."""
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    reg = _register(box)
    try:
        _send(box, 20, "c1", PID_A)
        _drain(box, chain)
        dump = tmp_path / "rollback.dump"
        _pg("pg_dump", "-Fc", "-f", str(dump), box)
        assert reg.add(PID_B, "paper", "", "console:office1", "2026-11-22T09:00:00+08:00")
        assert reg.lift(PID_B, "", "console:office1", "2026-11-23T09:00:00+08:00")
    finally:
        reg.close()
    _rollback(box, dump, tmp_path)
    _rollback(box, dump, tmp_path)
    assert _events_of(box, PID_B) == [("opt_out", "console:office1"), ("lift", "console:office1")]


@pytest.mark.parametrize("by", ["console:office1", REGISTRY_ACTOR])
def test_a_consent_change_and_an_index_insert_at_the_same_moment_leave_no_row(box: str, by: str) -> None:
    """P19-X2 (High) / F3: the drain's insert has read no register row and is not yet committed when the console's
    opt-out, or the registry worker's refusal, is written. The register's writer takes the index's lock, so it waits
    for the insert and its sweep removes the row in the opt-out's own transaction."""
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    reg = _register(box)
    ins = psycopg.connect(box)  # not autocommit: the insert's transaction stays open
    try:
        ins.execute("INSERT INTO provenance.model_uses (rec_hash, call_id, event, record_kind, record_ref, pid, at) "
                    "VALUES ('h1', 'c1', 'used', 'verdict', '{}', %s, '2026-11-21T02:00:00+08:00')", (PID_B,))  # fmt: skip
        done: list[bool] = []
        t = threading.Thread(target=lambda: done.append(reg.add(PID_B, "emr" if by == REGISTRY_ACTOR else "paper",
                                                                "", by, "2026-11-21T09:00:00+08:00")))  # fmt: skip
        t.start()
        with psycopg.connect(box, autocommit=True) as w:  # the writer either finished or waits on the lock
            while t.is_alive() and not w.execute("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
                                                 "AND NOT granted").fetchone()[0]:  # fmt: skip
                time.sleep(0.01)
        ins.commit()
        t.join()
    finally:
        ins.close()
        reg.close()
    assert done == [True]
    assert _uses(box, PID_B) == []


def test_the_cli_search_refuses_while_the_repair_is_owed(box: str, tmp_path: Path, capsys: Any) -> None:
    """P19-X1 (High): ``trialbox provenance --search`` asks the marker in its audit directory: refused while a repair
    is owed, answered once the drain says clean."""
    from tools.trialbox import provenance as cli

    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    argv = ["--search", "--model", "m-judge", "--audit-dir", str(chain), "--db-url", _url(box)]
    idx.write_state(chain, state=idx.REQUIRED, reason="resync", attempts=0)
    capsys.readouterr()
    assert cli.main(argv) == 1
    out = capsys.readouterr()
    assert "call c1" not in out.out and "being put back" in out.err
    _drain(box, chain)
    assert cli.main(argv) == 0
    assert "call c1" in capsys.readouterr().out


def _slipped(dsn: str, pid: str) -> None:
    """A use row of ``pid`` that the trigger never saw (what ``pg_restore`` loads before the trigger exists)."""
    with psycopg.connect(dsn, autocommit=True) as c, c.transaction():
        c.execute("ALTER TABLE provenance.model_uses DISABLE TRIGGER model_uses_withhold")
        c.execute("INSERT INTO provenance.model_uses (rec_hash, call_id, event, record_kind, record_ref, pid, at) "
                  "VALUES ('h9', 'c9', 'used', 'verdict', '{}', %s, '2026-11-20T02:00:00+08:00')", (pid,))  # fmt: skip
        c.execute("ALTER TABLE provenance.model_uses ENABLE TRIGGER model_uses_withhold")


def test_a_failed_sweep_after_an_opt_out_stays_owed_and_is_done(
    box: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P19-X3 (High): the sweep after a batch that drained an opt-out fails: the repair is owed (the marker, so the
    searches are held) and the drain's retry sweeps, with an empty journal."""
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    monkeypatch.setattr(Drain, "RETRY", 0.0)
    d = Drain("postgresql://x@h/db", chain, TZ, connect=lambda: psycopg.connect(box, autocommit=True))
    d.open()
    try:
        assert _state(chain)["state"] == idx.CLEAN
        _slipped(box, PID_B)
        real, calls = idx.sweep, itertools.count()

        def failing(con: Any) -> int:
            if next(calls) == 0:
                raise psycopg.OperationalError("synthetic: the connection dropped")
            return real(con)

        monkeypatch.setattr(idx, "sweep", failing)
        with psycopg.connect(box, autocommit=True) as c:  # the register's row and the journal's opt-out; no erase
            register(c, PID_B, "opt_out", "2026-11-22T09:00:00+08:00")
            c.execute("INSERT INTO audit.journal (db_role, event, ts, fields) VALUES ('tb_console', %s, %s, %s)",
                      (idx.OPT_OUT, "2026-11-22T09:00:00+08:00", json.dumps({"detail": {"action": "opt_out"}})))  # fmt: skip
        assert d.step() == 1
        assert _state(chain)["state"] == idx.REQUIRED
        assert _uses(box, PID_B) == ["c9"]
        assert d.step() == 0  # nothing new in the journal: the owed repair runs
    finally:
        d.con.close()
    assert _uses(box, PID_B) == []
    assert _state(chain)["state"] == idx.CLEAN


@pytest.mark.parametrize("how", ["disabled", "elsewhere"])
def test_a_trigger_that_does_not_filter_the_index_is_not_installed(box: str, how: str) -> None:
    """P19-X4 (High) / F5: a disabled trigger (an interrupted data restore leaves one) or one of the same name on
    another table is no filter: the drain must not write the index."""
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
        assert idx.installed(c)
        if how == "disabled":
            c.execute("ALTER TABLE provenance.model_uses DISABLE TRIGGER model_uses_withhold")
        else:
            c.execute("DROP TRIGGER model_uses_withhold ON provenance.model_uses")
            c.execute("CREATE TABLE provenance.elsewhere (pid text, at timestamptz)")
            c.execute("CREATE TRIGGER model_uses_withhold BEFORE INSERT ON provenance.elsewhere FOR EACH ROW "
                      "EXECUTE FUNCTION provenance.withhold()")  # fmt: skip
        assert not idx.installed(c)


def test_a_repair_is_committed_before_the_marker_says_clean(box: str, tmp_path: Path) -> None:
    """P19-X5 (High): on a drain connection that is not autocommit, the repair's rows are seen by another session
    when the marker says clean, and stay after the drain's connection closes."""
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    with psycopg.connect(box, autocommit=True) as c:  # the index lost its rows (a restore)
        c.execute("DELETE FROM provenance.model_uses")
        c.execute("DELETE FROM provenance.model_calls")
    d = Drain("postgresql://x@h/db", chain, TZ, connect=lambda: psycopg.connect(box, autocommit=False))
    d.open()
    try:
        assert _state(chain)["state"] == idx.CLEAN
        assert (_calls(box), _uses(box)) == (["c1"], ["c1"])
    finally:
        d.con.close()
    assert (_calls(box), _uses(box)) == (["c1"], ["c1"])


def test_a_line_of_which_one_row_is_missing_is_completed(box: str, tmp_path: Path) -> None:
    """P19-N2: a line written half by the old autocommit loop (one of its two use rows) is completed: the catch-up
    compares rows, not line hashes."""
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    call_f, use_f = _fields(20, "c2", PID_A)
    _put(box, 20, "llm.call", call_f)
    _put(box, 20, "llm.call", {**call_f, "detail": {**call_f["detail"], "call_id": "c3"}})
    _put(box, 20, "ai.used", {"detail": {**use_f["detail"], "calls": ["c2", "c3"]}})
    _drain(box, chain)
    with psycopg.connect(box, autocommit=True) as c:
        c.execute("DELETE FROM provenance.model_uses WHERE call_id = 'c3'")
        assert idx.catch_up(c, chain) == 1
        assert idx.check(c, chain).ok
    assert _uses(box) == ["c2", "c3"]


def test_live_failures_do_not_put_off_an_owed_repair(box: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """P19-X7: the retry's time is set when the repair first becomes owed; a later live failure keeps it."""
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    monkeypatch.setattr(Drain, "RETRY", 3600.0)
    d = Drain("postgresql://x@h/db", chain, TZ, connect=lambda: psycopg.connect(box, autocommit=True))
    d.open()

    def failing(con: Any, rec: dict[str, Any]) -> int:
        raise psycopg.OperationalError("synthetic: the connection dropped")

    monkeypatch.setattr(idx, "add", failing)
    try:
        _send(box, 20, "c1", PID_A)
        d.step()
        first = d._retry
        _send(box, 21, "c2", PID_A)
        d.step()
        assert d._retry == first
    finally:
        d.con.close()


def test_an_interrupted_rebuild_leaves_the_index_as_it_was(
    box: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P19-X8: ``trialbox provenance --rebuild`` (an autocommit connection) stopped half way: one transaction, so the
    index is the one it found, not a partial one under a clean marker."""
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
    _send(box, 20, "c1", PID_A)
    _send(box, 21, "c2", PID_B)
    _drain(box, chain)
    real, writes = idx.add, itertools.count()

    def stopped(con: Any, rec: dict[str, Any]) -> int:
        if next(writes) == 2:
            raise KeyboardInterrupt
        return real(con, rec)

    monkeypatch.setattr(idx, "add", stopped)
    with psycopg.connect(box, autocommit=True) as c, pytest.raises(KeyboardInterrupt):
        idx.rebuild(c, chain)
    assert (_calls(box), _uses(box)) == (["c1", "c2"], ["c1", "c2"])


def test_the_restore_sweep_runs_even_when_the_catch_up_cannot(
    box: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F2: a catch-up that fails at every try (a bad line, a database blip) does not keep a withheld row in the
    index: the sweep comes first."""
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
        register(c, PID_B, "opt_out", "2026-11-21T09:00:00+08:00")
    _slipped(box, PID_B)

    def broken(con: Any, directory: Path) -> int:
        raise ValueError("synthetic: a line that cannot be read")

    monkeypatch.setattr(idx, "catch_up", broken)
    d = Drain("postgresql://x@h/db", chain, TZ, connect=lambda: psycopg.connect(box, autocommit=True))
    d.open()
    d.con.close()
    assert _uses(box, PID_B) == []
    assert _state(chain)["state"] == idx.REQUIRED


def test_the_catch_up_counts_the_rows_it_wrote(box: str, tmp_path: Path) -> None:
    """F6: a use row the register withholds is not a row written back; a start with nothing missing writes 0."""
    chain = tmp_path / "audit"
    with psycopg.connect(box, autocommit=True) as c:
        c.execute(idx.INDEX_SQL)
        register(c, PID_A, "opt_out", "2026-11-19T09:00:00+08:00")
    _send(box, 20, "c1", PID_A)
    _drain(box, chain)
    with psycopg.connect(box, autocommit=True) as c:
        assert idx.catch_up(c, chain) == 0
    assert _state(chain)["rows_written"] == 0
